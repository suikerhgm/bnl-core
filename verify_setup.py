# verify_setup.py
import os
import json
import sys
import re

# --- Constants ---
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
NC = '\033[0m'  # No Color

REQUIRED_ENV_VARS = [
    "NOTION_TOKEN",
    "NOTION_VERSION",
    "API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "GROQ_API_KEY",
]
REQUIRED_PYTHON_DEPS = ["fastapi", "uvicorn", "notion_client"]
BACKEND_FILE = "nexus_notion_tools.py"
WORKFLOW_FILE = "nexus_bnl_workflow_v2.json"

# --- Helper Functions ---

def print_status(component, status, message=""):
    """Prints a formatted status line."""
    if status == "ok":
        print(f"{GREEN}✅ {component}{NC}")
    elif status == "warn":
        print(f"{YELLOW}⚠️  {component}{NC}")
    elif status == "fail":
        print(f"{RED}❌ {component}{NC}")
    
    if message:
        print(f"   {message}")

# --- Verification Functions ---

def verify_backend_python():
    """Verifies all components related to the Python backend."""
    print_status("Backend Python", "ok")
    
    # 1. Check for nexus_notion_tools.py
    if os.path.exists(BACKEND_FILE):
        print_status(f"{BACKEND_FILE} encontrado", "ok")
    else:
        print_status(f"{BACKEND_FILE} no encontrado", "fail", f"Asegúrate de que el archivo '{BACKEND_FILE}' exista en el directorio actual.")
        return False # Stop if main file is missing

    # 2. Check for dependencies
    try:
        from fastapi import FastAPI
        from uvicorn import run
        from notion_client import Client
        print_status("Dependencias instaladas", "ok")
    except ImportError as e:
        print_status("Dependencias no instaladas", "fail", f"Falta el módulo: {e.name}. Ejecuta 'pip install -r requirements.txt'.")
        return False
        
    # 3. Check .env file
    if not os.path.exists(".env"):
        print_status(".env configurado", "fail", "El archivo .env no existe.")
        return False
        
    env_vars = {}
    with open(".env", "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()

    all_vars_present = True
    for var in REQUIRED_ENV_VARS:
        if not env_vars.get(var):
            print_status(".env configurado", "fail", f"La variable '{var}' no está definida en el archivo .env.")
            all_vars_present = False
    
    if not all_vars_present:
        return False

    print_status(".env configurado correctamente", "ok")

    # 4. Validate API Key format
    api_key = env_vars.get("API_KEY", "")
    if len(api_key) == 64 and re.match(r"^[0-9a-fA-F]{64}$", api_key):
        print_status("API Key válida (64 caracteres)", "ok")
    else:
        print_status("API Key inválida", "fail", f"La API_KEY debe tener 64 caracteres hexadecimales. Longitud actual: {len(api_key)}.")
        return False
        
    return True

def verify_n8n():
    """Verifies n8n related configurations."""
    print_status("n8n", "warn")
    
    # 1. Check workflow file validity
    if not os.path.exists(WORKFLOW_FILE):
        print_status(f"Workflow JSON ('{WORKFLOW_FILE}')", "fail", "No se encontró el archivo del workflow.")
        return False
    
    try:
        with open(WORKFLOW_FILE, "r") as f:
            json.load(f)
        print_status("Workflow JSON válido", "ok")
    except json.JSONDecodeError:
        print_status("Workflow JSON inválido", "fail", "El archivo tiene un formato JSON incorrecto.")
        return False

    # 2. Mock process check as per instructions
    print_status("n8n no está corriendo", "fail", "(esperado antes de deployment)")
    return True

def verify_ngrok():
    """Mocks ngrok verification as per instructions."""
    print_status("ngrok", "warn")
    print_status("ngrok no está corriendo", "fail", "(esperado antes de deployment)")
    return True

# --- Main Execution ---

if __name__ == "__main__":
    print("🔍 Verificando configuración de Nexus BNL...")
    
    backend_ok = verify_backend_python()
    n8n_ok = verify_n8n()
    ngrok_ok = verify_ngrok()
    
    print("-" * 30)
    if backend_ok and n8n_ok and ngrok_ok:
        print(f"{GREEN}✅ Verificación completada. Todo listo para el siguiente paso.{NC}")
        print("📝 Siguiente paso: Iniciar servicios con start_services.ps1")
    else:
        print(f"{RED}❌ Verificación fallida. Por favor, revisa los errores anteriores antes de continuar.{NC}")

