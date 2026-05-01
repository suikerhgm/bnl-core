<# 
.SYNOPSIS
Este script inicia los tres servicios necesarios para que Nexus BNL funcione:
1. Backend de Python (FastAPI)
2. n8n
3. ngrok (para exponer n8n a internet y conectar con el webhook de Telegram)

.DESCRIPTION
El script mostrará los comandos necesarios. Debes abrir TRES terminales de PowerShell 
separadas y ejecutar cada bloque de comandos en una de ellas.

Esto es necesario porque cada servicio es un proceso de larga duración 
y debe correr en su propio terminal.

.NOTES
Autor: Nexus BNL Deployment Agent
Versión: 1.0
#>

# --- INSTRUCCIONES ---
Clear-Host

Write-Host "--- SCRIPT DE INICIO DE SERVICIOS PARA NEXUS BNL ---" -ForegroundColor Green
Write-Host "IMPORTANTE: Abre tres (3) terminales de PowerShell." -ForegroundColor Yellow
Write-Host "Copia y pega cada uno de los siguientes bloques de comandos en una terminal separada."
Write-Host "--------------------------------------------------------------------------------"
Write-Host ""


# --- Bloque 1: Backend de Python ---
Write-Host "--- 1. Terminal 1: Backend de Python (FastAPI) ---" -ForegroundColor Cyan
Write-Host "Este comando inicia el servidor de herramientas de Notion en http://localhost:8000"
Write-Host ""
Write-Host '$env:PYTHONUNBUFFERED=1; uvicorn nexus_notion_tools:app --host 0.0.0.0 --port 8000 --reload' -ForegroundColor White
Write-Host ""
Write-Host "--------------------------------------------------------------------------------"
Write-Host ""


# --- Bloque 2: n8n ---
Write-Host "--- 2. Terminal 2: n8n ---" -ForegroundColor Cyan
Write-Host "Este comando inicia tu instancia local de n8n en http://localhost:5678"
Write-Host "Asegúrate de haber configurado las variables de entorno si es necesario (ej. para la API key de Nexus)."
Write-Host ""
Write-Host 'n8n start' -ForegroundColor White
Write-Host ""
Write-Host "--------------------------------------------------------------------------------"
Write-Host ""


# --- Bloque 3: ngrok ---
Write-Host "--- 3. Terminal 3: ngrok ---" -ForegroundColor Cyan
Write-Host "Este comando expone tu n8n local al público para que Telegram pueda enviarle mensajes."
Write-Host "Copia la URL 'Forwarding' (debe empezar con https://) que genere ngrok."
Write-Host "Esa URL la necesitarás para configurar el webhook en tu bot de Telegram la primera vez."
Write-Host ""
Write-Host 'ngrok http 5678' -ForegroundColor White
Write-Host ""
Write-Host "--------------------------------------------------------------------------------"
Write-Host ""

Write-Host "Una vez que los tres servicios estén corriendo, procede con el checklist de deployment." -ForegroundColor Green
