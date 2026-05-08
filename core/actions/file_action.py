# core/actions/file_action.py

from core.actions.base_action import BaseAction
from pathlib import Path
from typing import Dict, Any, List
import json
import logging
import time

logger = logging.getLogger(__name__)

BASE_DIR = Path("generated_apps")


class FileAction(BaseAction):
    """
    Executor de acciones sobre archivos del sistema.

    Operaciones soportadas:
    - write_project: Persiste un proyecto multi-archivo de forma segura
    - read: Leer archivo
    - write: Escribir archivo
    - delete: Eliminar archivo
    - move: Mover/renombrar archivo
    - copy: Copiar archivo
    """

    def __init__(self, context: Dict[str, Any]):
        super().__init__(context)
        self.operation = context.get("operation")
        self.params = context.get("params", {})

    async def execute(self) -> Dict[str, Any]:
        """
        Ejecuta la operación de archivo (async).

        Returns:
            Dict con formato:
            {
                "success": bool,
                "result": Any,
                "error": Optional[str]
            }
        """
        if self.operation == "write_project":
            files = self.params.get("files", [])
            result = self.write_project(files)
            return {
                "success": result["success"],
                "result": result,
                "error": result.get("error"),
            }

        if self.operation in ("write", "create"):
            result = self._write_single_file()
            return {
                "success": result["success"],
                "result": result,
                "error": result.get("error"),
            }

        logger.warning(f"FileAction.{self.operation} not implemented yet")
        return {
            "success": False,
            "result": None,
            "error": f"Operation '{self.operation}' not implemented",
        }

    def write_project(self, files: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Persiste un conjunto de archivos en un directorio de proyecto aislado.

        Cada llamada crea un subdirectorio único bajo BASE_DIR. Ningún archivo
        puede escapar de ese subdirectorio: se rechazan rutas absolutas, rutas
        con componentes ".." y cualquier ruta cuya resolución caiga fuera del
        directorio del proyecto.

        Args:
            files: Lista de dicts con claves "path" (str) y "content" (str).

        Returns:
            {
                "success": bool,
                "project_path": str,       # sólo presente si success=True
                "files_written": int,      # sólo presente si success=True
                "error": str,              # sólo presente si success=False
            }
        """
        if not isinstance(files, list) or len(files) == 0:
            return {"success": False, "error": "files must be a non-empty list"}

        project_id = f"project_{int(time.time())}"
        project_path = BASE_DIR.resolve() / project_id

        try:
            project_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Could not create project directory %s: %s", project_path, exc)
            return {"success": False, "error": f"Cannot create project directory: {exc}"}

        files_written = 0

        for entry in files:
            validation_error = self._validate_file_entry(entry)
            if validation_error:
                logger.warning("Skipping invalid entry %r: %s", entry, validation_error)
                return {"success": False, "error": validation_error}

            raw_path: str = entry["path"]
            content: str = entry["content"]

            # Reject absolute paths before any Path resolution
            if Path(raw_path).is_absolute():
                return {
                    "success": False,
                    "error": f"Absolute paths are forbidden: '{raw_path}'",
                }

            # Reject any path component that is ".."
            parts = Path(raw_path).parts
            if ".." in parts:
                return {
                    "success": False,
                    "error": f"Path traversal detected in: '{raw_path}'",
                }

            candidate = (project_path / raw_path).resolve()

            # Canonical check: resolved path must still be inside project_path
            try:
                candidate.relative_to(project_path)
            except ValueError:
                return {
                    "success": False,
                    "error": f"Path escapes project directory: '{raw_path}'",
                }

            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(content, encoding="utf-8")
                files_written += 1
                logger.info("Written: %s", candidate.relative_to(BASE_DIR.resolve()))
            except OSError as exc:
                logger.error("Failed to write %s: %s", candidate, exc)
                return {"success": False, "error": f"Write failed for '{raw_path}': {exc}"}

        # Create __init__.py in every directory that contains .py files but
        # lacks one — this makes them proper Python packages so uvicorn can
        # import dotted module paths like "backend.app" or "api.server".
        try:
            py_dirs = {
                f.parent
                for f in project_path.rglob("*.py")
                if f.name != "__init__.py" and f.parent != project_path
            }
            for d in sorted(py_dirs):
                init = d / "__init__.py"
                if not init.exists():
                    init.write_text("", encoding="utf-8")
                    logger.info("Written: %s", init.relative_to(BASE_DIR.resolve()))
        except Exception as _exc:
            logger.warning("Could not create __init__.py files: %s", _exc)

        # Write agent metadata sidecar — maps file paths to their source agent.
        # Silent failure: metadata is informational, never blocks the return.
        agent_map = {
            entry["path"]: entry["agent"]
            for entry in files
            if isinstance(entry.get("agent"), str)
        }
        if agent_map:
            try:
                meta_file = project_path / "_nexus_metadata.json"
                meta_file.write_text(json.dumps(agent_map, indent=2), encoding="utf-8")
                logger.info("Written: _nexus_metadata.json (%d entries)", len(agent_map))
            except OSError as exc:
                logger.warning("Could not write metadata sidecar: %s", exc)

        return {
            "success": True,
            "project_path": str(project_path),
            "files_written": files_written,
        }

    def _write_single_file(self) -> Dict[str, Any]:
        """
        Crea/sobreescribe un único archivo en el directorio de trabajo del servidor.

        Usa params["name"] como nombre de archivo y params["content"] como contenido.
        Solo permite nombres de archivo simples (sin directorios) para evitar path traversal.
        """
        name: str = (
            self.params.get("name")
            or self.params.get("filename")
            or self.params.get("path")
            or "output.txt"
        )
        content: str = self.params.get("content") or ""

        # Tomar solo el componente final — rechaza traversal silenciosamente
        safe_name = Path(name).name
        if not safe_name:
            return {"success": False, "error": f"Nombre de archivo inválido: '{name}'"}

        target = Path.cwd() / safe_name
        try:
            target.write_text(content, encoding="utf-8")
            logger.info("📄 FileAction.write: %s (%d bytes)", target, len(content))
            return {"success": True, "path": str(target), "name": safe_name}
        except OSError as exc:
            logger.error("❌ FileAction.write failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_file_entry(entry: Any) -> str | None:
        """Returns an error message if the entry is invalid, else None."""
        if not isinstance(entry, dict):
            return "Each file entry must be a dict"
        if "path" not in entry or not isinstance(entry["path"], str) or not entry["path"].strip():
            return "Each file entry must have a non-empty string 'path'"
        if "content" not in entry or not isinstance(entry["content"], str):
            return "Each file entry must have a string 'content'"
        return None

    def requires_approval(self) -> bool:
        """Operaciones destructivas requieren aprobación."""
        return self.operation in ("delete", "move")

    def get_description(self) -> str:
        """Descripción legible de la acción."""
        if self.operation == "write_project":
            n = len(self.params.get("files", []))
            return f"Write project to disk ({n} file{'s' if n != 1 else ''})"
        return f"FileAction (operation: {self.operation})"
