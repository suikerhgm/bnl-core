"""
run.py — Arranque único de Nexus BNL
=====================================
Un solo comando levanta todo el sistema:
  - Backend  (FastAPI, puerto 8000)
  - Dashboard (FastAPI, puerto 8001)
  - ngrok    (túnel HTTPS, auto-detectado)
  - Webhook  (configurado automáticamente con la URL de ngrok)

Uso:
    python run.py                          # todo
    python run.py --no-ngrok               # sin túnel
    python run.py --no-dash                # sin dashboard
    python run.py --backend-port 9000      # puerto distinto
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# ── Constantes ────────────────────────────────────────────────────────────────

VENV_PYTHON   = str(Path(sys.executable))
NGROK_API     = "http://localhost:4040/api/tunnels"
NGROK_TIMEOUT = 30   # segundos esperando la URL pública

# ── Lifecycle guards ──────────────────────────────────────────────────────────

# Set once when shutdown begins; all threads and the watchdog check this flag.
_shutdown_called = threading.Event()

# Serialises all print() calls so that _stream threads and the signal handler
# never write to the buffered stdout concurrently — which is what causes
# "RuntimeError: reentrant call inside <_io.BufferedWriter name='<stdout>'>".
_STDOUT_LOCK = threading.Lock()


def _safe_print(*args, **kwargs) -> None:
    """Thread-safe print; silently swallowed if stdout is already closed."""
    with _STDOUT_LOCK:
        try:
            print(*args, **kwargs)
        except Exception:
            pass


# ── Streaming de stdout/stderr ────────────────────────────────────────────────

def _stream(proc: subprocess.Popen, prefix: str) -> None:
    """Lee stdout del proceso y lo imprime con prefijo."""
    try:
        for line in proc.stdout:
            _safe_print(f"[{prefix}] {line}", end="", flush=True)
    except Exception:
        pass


def launch(name: str, cmd: list, env: dict | None = None) -> subprocess.Popen:
    """Lanza un subprocess y arranca un hilo que reenvía su stdout."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env or os.environ.copy(),
    )
    threading.Thread(target=_stream, args=(proc, name), daemon=True).start()
    return proc


# ── Detección e inicio de ngrok ───────────────────────────────────────────────

def _find_ngrok() -> str | None:
    """Devuelve la ruta del ejecutable ngrok o None si no está instalado."""
    return shutil.which("ngrok")


def _poll_ngrok_url(timeout: int = NGROK_TIMEOUT) -> str | None:
    """
    Consulta la API local de ngrok hasta encontrar una URL pública HTTPS.
    Devuelve la URL o None si no responde en `timeout` segundos.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(NGROK_API, timeout=2) as resp:
                data = json.load(resp)
                for tunnel in data.get("tunnels", []):
                    url = tunnel.get("public_url", "")
                    if url.startswith("https://"):
                        return url
        except Exception:
            pass
        time.sleep(0.5)
    return None


def launch_ngrok(backend_port: int) -> subprocess.Popen | None:
    """
    Lanza `ngrok http <backend_port>`.
    Devuelve el Popen o None si ngrok no está disponible.
    """
    ngrok_path = _find_ngrok()
    if not ngrok_path:
        print("⚠️  ngrok no encontrado en PATH — omitiendo túnel")
        print("   Instala ngrok: https://ngrok.com/download")
        return None

    try:
        proc = subprocess.Popen(
            [ngrok_path, "http", str(backend_port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Hilo para capturar errores de ngrok (autenticación, conflictos de puerto…)
        def _ngrok_err():
            try:
                for line in proc.stderr:
                    line = line.strip()
                    if line:
                        _safe_print(f"[NGROK-ERR] {line}", flush=True)
            except Exception:
                pass
        threading.Thread(target=_ngrok_err, daemon=True).start()
        return proc
    except Exception as exc:
        print(f"❌ Error al lanzar ngrok: {exc}")
        return None


# ── Configuración automática del webhook ──────────────────────────────────────

def _set_webhook(ngrok_url: str, backend_port: int) -> bool:
    """
    Llama a POST /set-webhook del backend con la URL pública de ngrok.
    Devuelve True si Telegram aceptó el webhook.
    """
    webhook_url = f"{ngrok_url}/webhook"
    payload     = json.dumps({"url": webhook_url}).encode()
    req = urllib.request.Request(
        f"http://localhost:{backend_port}/set-webhook",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.load(resp)
        if result.get("success"):
            print(f"   ✅ Webhook configurado: {webhook_url}")
            return True
        err = result.get("error") or result.get("result", {})
        print(f"   ⚠️  Webhook rechazado por Telegram: {err}")
        return False
    except Exception as exc:
        print(f"   ⚠️  No se pudo configurar el webhook: {exc}")
        return False


def _wait_backend_ready(backend_port: int, timeout: int = 20) -> bool:
    """Espera hasta que el backend responda en /ping."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        sock_timeout = min(1.0, remaining)
        try:
            with urllib.request.urlopen(
                f"http://localhost:{backend_port}/ping", timeout=sock_timeout
            ):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _ngrok_worker(ngrok_proc: subprocess.Popen, backend_port: int) -> None:
    """
    Hilo de fondo: espera a que ngrok exponga su URL, la muestra en consola
    y configura el webhook de Telegram automáticamente.
    """
    _safe_print("   ⏳ Esperando URL pública de ngrok...", flush=True)

    url = _poll_ngrok_url()
    if not url:
        rc = ngrok_proc.poll()
        if rc is not None:
            _safe_print(f"❌ ngrok terminó inesperadamente (rc={rc})")
        else:
            _safe_print(f"❌ ngrok no expuso una URL en {NGROK_TIMEOUT}s")
            _safe_print("   Verifica tu auth token: ngrok config add-authtoken <TOKEN>")
        return

    _safe_print(f"\n   🌐 Túnel público: \033[36m{url}\033[0m", flush=True)
    _safe_print(f"   📋 Panel ngrok:  http://localhost:4040", flush=True)

    # Guardar la URL en un archivo para referencia
    try:
        Path(".ngrok_url").write_text(url, encoding="utf-8")
    except OSError:
        pass

    # Esperar a que el backend esté listo y configurar el webhook
    if _wait_backend_ready(backend_port):
        _set_webhook(url, backend_port)
    else:
        _safe_print(f"   ⚠️  Backend no respondió — configura el webhook manualmente:")
        _safe_print(f"       curl -X POST http://localhost:{backend_port}/set-webhook")
        _safe_print(f'            -d \'{{"url":"{url}/webhook"}}\'')


# ── Reinicio automático ───────────────────────────────────────────────────────

def _watchdog(procs_ref: list, names: list) -> None:
    """
    Vigila procesos y los reinicia si mueren inesperadamente.

    Exits cleanly when _shutdown_called is set so it never races with
    the signal handler during controlled shutdown.
    """
    while not _shutdown_called.wait(timeout=2):
        for i, (proc, name) in enumerate(zip(procs_ref, names)):
            if proc is None or _shutdown_called.is_set():
                continue
            rc = proc.poll()
            if rc is not None:
                _safe_print(f"\n⚠️  [{name}] proceso terminó (rc={rc}) — reiniciando...")
                new_proc = subprocess.Popen(
                    proc.args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=os.environ.copy(),
                )
                threading.Thread(target=_stream, args=(new_proc, name), daemon=True).start()
                procs_ref[i] = new_proc


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus BNL — arranque único")
    parser.add_argument("--no-ngrok", action="store_true", help="No lanzar ngrok")
    parser.add_argument("--no-dash",  action="store_true", help="No lanzar el dashboard")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--dash-port",    type=int, default=8001)
    args = parser.parse_args()

    procs: list[subprocess.Popen | None] = []
    names: list[str] = []

    print("🚀 Nexus BNL — iniciando servicios...\n")

    # ── Backend ──────────────────────────────────────────────────────
    # --reload is intentionally omitted: uvicorn's StatReload watches the
    # entire project tree (including generated_apps/) and triggers spurious
    # reloads whenever auto-loop edits a generated backend.py, sending
    # signals that race with RuntimeEngine's own restart logic and cause
    # "RuntimeError: reentrant call inside <_io.BufferedWriter>".
    # RuntimeEngine is the sole restart controller for generated apps.
    backend_cmd = [
        VENV_PYTHON, "-m", "uvicorn",
        "nexus_bot:app",
        "--host", "0.0.0.0",
        "--port", str(args.backend_port),
    ]
    print(f"▶ Backend    → http://127.0.0.1:{args.backend_port}")
    procs.append(launch("BACKEND", backend_cmd))
    names.append("BACKEND")
    time.sleep(1.5)

    # ── Dashboard ────────────────────────────────────────────────────
    if not args.no_dash:
        dash_cmd = [
            VENV_PYTHON, "-m", "uvicorn",
            "app.dashboard:app",
            "--host", "0.0.0.0",
            "--port", str(args.dash_port),
        ]
        print(f"▶ Dashboard  → http://127.0.0.1:{args.dash_port}")
        procs.append(launch("DASH", dash_cmd))
        names.append("DASH")
        time.sleep(0.8)
    else:
        procs.append(None)
        names.append("DASH")

    # ── ngrok ────────────────────────────────────────────────────────
    if not args.no_ngrok:
        ngrok_exe = _find_ngrok()
        if ngrok_exe:
            print(f"▶ Ngrok      → detectado ({ngrok_exe})")
            ngrok_proc = launch_ngrok(args.backend_port)
            if ngrok_proc:
                procs.append(ngrok_proc)
                names.append("NGROK")
                # Hilo de fondo: espera URL y configura webhook
                threading.Thread(
                    target=_ngrok_worker,
                    args=(ngrok_proc, args.backend_port),
                    daemon=True,
                ).start()
            else:
                procs.append(None)
                names.append("NGROK")
        else:
            print("▶ Ngrok      → no instalado (usa --no-ngrok para omitir este aviso)")
            procs.append(None)
            names.append("NGROK")
    else:
        print("▶ Ngrok      → omitido (--no-ngrok)")
        procs.append(None)
        names.append("NGROK")

    print(f"\n✅ Servicios activos — Ctrl+C para detener todo\n")

    # ── Vigilancia + señales ─────────────────────────────────────────
    threading.Thread(target=_watchdog, args=(procs, names), daemon=True).start()

    def _shutdown(sig, frame):
        # Guard: only the first signal does any work.  Subsequent signals
        # (e.g. a second SIGINT while the first shutdown is running, or a
        # SIGTERM arriving at the same time) return immediately, preventing
        # the "reentrant call inside BufferedWriter" crash.
        if _shutdown_called.is_set():
            return
        _shutdown_called.set()

        # Write directly to the raw buffer — avoids going through the
        # high-level BufferedWriter that may already be locked by a _stream
        # thread, which is what causes RuntimeError: reentrant call.
        try:
            sys.stdout.write("\n\n⛔ Deteniendo todos los servicios...\n")
            sys.stdout.flush()
        except Exception:
            pass

        for proc in procs:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

        # Esperar hasta 3 s antes de forzar salida
        deadline = time.time() + 3
        for proc in procs:
            if proc and proc.poll() is None:
                remaining = max(0, deadline - time.time())
                try:
                    proc.wait(timeout=remaining)
                except Exception:
                    pass

        try:
            sys.stdout.write("👋 Hasta luego.\n")
            sys.stdout.flush()
        except Exception:
            pass

        # os._exit is signal-handler safe: it bypasses Python cleanup
        # handlers (atexit, __del__, sys.exit hooks) that are not safe
        # to invoke from a signal context.
        os._exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Bloquear hilo principal
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
