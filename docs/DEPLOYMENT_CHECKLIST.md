# ✅ Checklist de Deployment — Nexus BNL

Este documento es una guía paso a paso para asegurar que todos los componentes de Nexus BNL estén correctamente configurados y funcionando.

---

## Pre-requisitos
- [ ] Python 3.10+ instalado y agregado al PATH.
- [ ] Node.js 18+ instalado (se recomienda usar `nvm`).
- [ ] n8n instalado globalmente (`npm install -g n8n`).
- [ ] ngrok instalado y autenticado.

---

## Fase 1: Configuración Inicial
- [ ] Clona el repositorio del proyecto.
- [ ] Navega a la carpeta del proyecto.
- [ ] Instala las dependencias de Python: `pip install -r requirements.txt`.
- [ ] Renombra `.env.example` a `.env`.
- [ ] Abre el archivo `.env` y llena **TODAS** las credenciales:
    - `NOTION_TOKEN`
    - `API_KEY` (la clave de 64 caracteres para el backend)
    - `TELEGRAM_BOT_TOKEN`
    - `GROQ_API_KEY`
- [ ] **(Opcional pero recomendado)** Ejecuta el script de verificación para confirmar que todo está en orden: `python verify_setup.py`.

---

## Fase 2: Iniciar Servicios
- [ ] Ejecuta el script `start_services.ps1` en PowerShell.
- [ ] Sigue las instrucciones del script para abrir tres terminales y ejecutar los comandos correspondientes.
- [ ] Verifica que los servicios estén corriendo:
    - [ ] **Backend Python:** Deberías ver logs de Uvicorn indicando que corre en `http://0.0.0.0:8000`.
    - [ ] **n8n:** Deberías poder acceder a la interfaz web en `http://localhost:5678`.
    - [ ] **ngrok:** Deberías ver una URL de "Forwarding" tipo `https://xxxx-xxxx-xxxx.ngrok-free.dev`. Cópiala para el siguiente paso.

---

## Fase 3: Configuración de n8n
- [ ] Abre n8n en tu navegador (`http://localhost:5678`).
- [ ] **Importar el Workflow:**
    - [ ] Ve a la sección "Workflows".
    - [ ] Click en "Add Workflow" > "Import from file".
    - [ ] Selecciona el archivo `nexus_bnl_workflow_v2.json` (la versión optimizada que se generará).
- [ ] **Configurar Credenciales:**
    - [ ] Abre el workflow importado.
    - [ ] **Telegram:** En el nodo "Telegram Trigger", haz clic en el campo de credenciales y crea una nueva ("Create New") o selecciona una existente, pegando tu `TELEGRAM_BOT_TOKEN`. Haz lo mismo para el nodo "Telegram Response".
    - [ ] **Groq:** En el nodo "Groq Chat Model", haz clic en el campo de credenciales y crea una nueva o selecciona una existente, pegando tu `GROQ_API_KEY`.
- [ ] **Configurar Variable de Entorno para Herramientas:**
    - [ ] En la interfaz de n8n, ve a "Settings" > "Environment Variables".
    - [ ] Agrega una nueva variable:
        - **Name:** `API_KEY`
        - **Value:** Pega aquí el mismo valor de 64 caracteres que pusiste en tu archivo `.env`.
    - [ ] Guarda los cambios. Esto es **CRÍTICO** para que el Agente de IA pueda usar las herramientas de Notion.
- [ ] **Activar el Workflow:**
    - [ ] Vuelve al workflow.
    - [ ] Haz clic en el interruptor en la esquina superior izquierda para pasarlo de "Inactive" a "Active".

---

## Fase 4: Testing Final
- [ ] Envía un mensaje de prueba a tu bot de Telegram (ej. "hola").
- [ ] El bot debería responder.
- [ ] Pídele que realice una búsqueda en Notion (ej. "busca documentos sobre el proyecto X").
- [ ] Verifica que la búsqueda se realice y te devuelva resultados.
- [ ] Pídele que lea una página (usando el ID de la página o el título si el agente es capaz de encontrarlo).
- [ ] Pídele que cree una página nueva.
- [ ] Confirma que la página fue creada en Notion.

---

## Troubleshooting
Si algo falla en cualquier punto, consulta el archivo `TROUBLESHOOTING.md` para posibles soluciones a problemas comunes.
