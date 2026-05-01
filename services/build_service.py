"""
NexusAgentes — Servicio de construcción de aplicaciones (Build App)
Pipeline: Notion search -> blueprint -> task planner -> plan (pendiente de ejecución)
"""
import json
import re
from typing import Dict, List, Any

from app.config import logger
from services.notion_service import notion_search
from notion_client import APIResponseError


# Palabras que indican páginas irrelevantes (notas internas, config, etc.)
IRRELEVANT_KEYWORDS = [
    "nexus", "configuración", "configuracion", "webhook",
    "resumen", "migración", "migracion", "conversación", "conversacion",
    "backup", "template", "plantilla", "log", "debug",
]


def _is_relevant_page(title: str, project_name: str) -> bool:
    """
    Determina si una página de Notion es relevante para el proyecto.
    Filtra páginas internas del sistema y prioriza coincidencia semántica.
    """
    title_lower = title.lower()
    project_lower = project_name.lower()

    # Descartar páginas con palabras irrelevantes
    for kw in IRRELEVANT_KEYWORDS:
        if kw in title_lower:
            logger.debug(f"Pagina irrelevante descartada: '{title}' (contiene '{kw}')")
            return False

    # Extraer palabras clave del input del usuario
    project_keywords = set(re.findall(r'\w+', project_lower))

    # Contar cuántas palabras clave coinciden en el título
    title_words = set(re.findall(r'\w+', title_lower))
    matches = project_keywords & title_words

    if matches:
        logger.debug(
            f"Pagina relevante: '{title}' "
            f"(coincidencias: {matches})"
        )
        return True

    # Si no hay coincidencias directas, considerar irrelevante
    logger.debug(f"Pagina sin coincidencias descartada: '{title}'")
    return False


def _filter_relevant_pages(
    notion_data: List[Dict[str, Any]],
    project_name: str,
) -> List[Dict[str, Any]]:
    """
    Filtra los resultados de Notion para quedarse solo con páginas
    que sean semánticamente relevantes al proyecto del usuario.
    """
    relevant = [
        page for page in notion_data
        if _is_relevant_page(page.get("title", ""), project_name)
    ]
    logger.info(
        f"Filtro de relevancia: {len(notion_data)} paginas -> "
        f"{len(relevant)} relevantes para '{project_name}'"
    )
    return relevant


def _generate_fallback_blueprint(project_name: str) -> Dict[str, Any]:
    """
    Genera un blueprint desde cero basado en el input del usuario,
    infiriendo entidades lógicas a partir de palabras clave.
    """
    logger.info(
        f"Generando blueprint desde cero para: '{project_name}'"
    )

    project_lower = project_name.lower()

    # Mapa de dominios conocidos -> entidades típicas
    domain_entities: Dict[str, List[Dict[str, str]]] = {
        "futbol": [
            {"name": "Usuario", "type": "user"},
            {"name": "Equipo", "type": "business_object"},
            {"name": "Jugador", "type": "business_object"},
            {"name": "Estadistica", "type": "business_object"},
            {"name": "Ranking", "type": "business_object"},
        ],
        "entrenador": [
            {"name": "Usuario", "type": "user"},
            {"name": "Equipo", "type": "business_object"},
            {"name": "Jugador", "type": "business_object"},
            {"name": "Estadistica", "type": "business_object"},
            {"name": "Ranking", "type": "business_object"},
        ],
        "ranking": [
            {"name": "Usuario", "type": "user"},
            {"name": "Categoria", "type": "business_object"},
            {"name": "Participante", "type": "business_object"},
            {"name": "Puntuacion", "type": "business_object"},
            {"name": "Ranking", "type": "business_object"},
        ],
        "estadistica": [
            {"name": "Usuario", "type": "user"},
            {"name": "Categoria", "type": "business_object"},
            {"name": "Metrica", "type": "business_object"},
            {"name": "Reporte", "type": "business_object"},
            {"name": "Dashboard", "type": "business_object"},
        ],
        "tienda": [
            {"name": "Usuario", "type": "user"},
            {"name": "Producto", "type": "business_object"},
            {"name": "Categoria", "type": "business_object"},
            {"name": "Carrito", "type": "business_object"},
            {"name": "Pedido", "type": "business_object"},
        ],
        "inventario": [
            {"name": "Usuario", "type": "user"},
            {"name": "Producto", "type": "business_object"},
            {"name": "Categoria", "type": "business_object"},
            {"name": "Proveedor", "type": "business_object"},
            {"name": "Movimiento", "type": "business_object"},
        ],
        "blog": [
            {"name": "Usuario", "type": "user"},
            {"name": "Articulo", "type": "business_object"},
            {"name": "Categoria", "type": "business_object"},
            {"name": "Comentario", "type": "business_object"},
            {"name": "Etiqueta", "type": "business_object"},
        ],
    }

    # Detectar dominio por palabras clave en el input
    entities: List[Dict[str, str]] = []
    for keyword, domain_ents in domain_entities.items():
        if keyword in project_lower:
            entities = domain_ents
            logger.info(
                f"Dominio detectado: '{keyword}' -> "
                f"{len(entities)} entidades"
            )
            break

    # Si no se detectó ningún dominio conocido, usar plantilla genérica
    if not entities:
        entities = [
            {"name": "Usuario", "type": "user"},
            {"name": "Proyecto", "type": "business_object"},
            {"name": "Tarea", "type": "business_object"},
            {"name": "Configuracion", "type": "business_object"},
        ]
        logger.info(
            f"Usando plantilla generica: {len(entities)} entidades"
        )

    # Construir blueprint
    blueprint: Dict[str, Any] = {
        "project_name": project_name,
        "entities": [],
        "screens": [],
        "components": [],
        "flows": [],
    }

    for ent in entities:
        ent_name = ent["name"]
        blueprint["entities"].append({
            "name": ent_name,
            "type": ent["type"],
        })
        blueprint["screens"].append({
            "name": f"{ent_name}_screen",
            "entity": ent_name,
        })
        blueprint["components"].append({
            "name": f"{ent_name}_form",
            "type": "form",
        })
        blueprint["flows"].append({
            "name": f"{ent_name}_flow",
            "steps": [
                f"Listar {ent_name}",
                f"Crear {ent_name}",
                f"Editar {ent_name}",
                f"Eliminar {ent_name}",
            ],
        })

    logger.info(
        f"Blueprint desde cero generado: {len(blueprint['entities'])} entidades, "
        f"{len(blueprint['screens'])} pantallas, "
        f"{len(blueprint['components'])} componentes, "
        f"{len(blueprint['flows'])} flujos"
    )
    return blueprint


def generate_blueprint(
    project_name: str, notion_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Genera un blueprint estructurado a partir de los resultados de Notion.

    PASO 1: Filtra páginas irrelevantes de Notion
    PASO 2: Si hay datos relevantes, construye blueprint desde Notion
    PASO 3: Si no hay datos relevantes, genera blueprint desde cero
           basado en el input del usuario
    """
    logger.info(
        f"Generando blueprint para proyecto '{project_name}' "
        f"con {len(notion_data)} paginas de Notion"
    )

    # Filtrar páginas relevantes
    relevant_data = _filter_relevant_pages(notion_data, project_name)

    if relevant_data:
        # Usar datos de Notion filtrados
        blueprint: Dict[str, Any] = {
            "project_name": project_name,
            "entities": [],
            "screens": [],
            "components": [],
            "flows": [],
            "_source": "notion_filtered",
        }

        for page in relevant_data:
            page_title = page.get("title", "Untitled")

            blueprint["entities"].append({
                "name": page_title,
                "type": "business_object",
            })
            blueprint["screens"].append({
                "name": f"{page_title}_screen",
                "entity": page_title,
            })
            blueprint["components"].append({
                "name": f"{page_title}_form",
                "type": "form",
            })
            blueprint["flows"].append({
                "name": f"{page_title}_flow",
                "steps": [
                    f"Display {page_title}",
                    f"Edit {page_title}",
                    f"Save {page_title}",
                ],
            })

        logger.info(
            f"Blueprint desde Notion filtrado: "
            f"{len(blueprint['entities'])} entidades"
        )
    else:
        # Fallback: generar desde cero
        logger.info(
            "No se encontraron paginas relevantes en Notion. "
            "Generando blueprint desde el input del usuario..."
        )
        blueprint = _generate_fallback_blueprint(project_name)

    logger.info(
        f"Blueprint generado: {len(blueprint['entities'])} entidades, "
        f"{len(blueprint['screens'])} pantallas, "
        f"{len(blueprint['components'])} componentes, "
        f"{len(blueprint['flows'])} flujos"
    )
    return blueprint


def plan_tasks(blueprint: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convierte un blueprint en una lista de tareas accionables (task planner).
    """
    logger.info("Planificando tareas desde el blueprint")

    tasks: List[Dict[str, Any]] = []

    for entity in blueprint.get("entities", []):
        tasks.append({
            "id": f"task_entity_{entity['name']}",
            "type": "create_entity",
            "description": f"Crear entidad '{entity['name']}'",
            "status": "pending",
        })

    for screen in blueprint.get("screens", []):
        tasks.append({
            "id": f"task_screen_{screen['name']}",
            "type": "build_screen",
            "description": (
                f"Construir pantalla '{screen['name']}' "
                f"vinculada a entidad '{screen['entity']}'"
            ),
            "status": "pending",
        })

    for component in blueprint.get("components", []):
        tasks.append({
            "id": f"task_component_{component['name']}",
            "type": "create_component",
            "description": (
                f"Crear componente '{component['name']}' "
                f"de tipo '{component['type']}'"
            ),
            "status": "pending",
        })

    for flow in blueprint.get("flows", []):
        tasks.append({
            "id": f"task_flow_{flow['name']}",
            "type": "assemble_flow",
            "description": (
                f"Ensamblar flujo '{flow['name']}' "
                f"con pasos: {flow['steps']}"
            ),
            "status": "pending",
        })

    logger.info(f"Planificacion completa: {len(tasks)} tareas generadas")
    return tasks


def generate_cline_prompt(
    task: Dict[str, Any],
    project_context: str = ""
) -> str:
    """
    Genera un prompt estructurado listo para pegar en Cline,
    de modo que Cline pueda ejecutar la tarea real.
    """
    prompt = f"""## Tarea: {task['description']}

### Contexto del proyecto
{project_context}

### Instrucciones
Ejecuta la tarea descrita a continuacion siguiendo las mejores practicas
de desarrollo. Genera el codigo necesario, crea los archivos, y documenta
cada paso.

### Detalle de la tarea
- **ID**: {task['id']}
- **Tipo**: {task['type']}
- **Descripcion**: {task['description']}
- **Estado**: {task.get('status', 'pending')}

### Entregables esperados
1. Codigo fuente funcional y bien estructurado
2. Pruebas unitarias o de integracion (si aplica)
3. Documentacion minima del componente creado

### Restricciones
- Sigue la arquitectura modular del proyecto NexusAgentes
- Usa Python 3.10+ y FastAPI para APIs
- Usa TypeScript / React para frontend (si aplica)
- Incluye manejo de errores y logging
"""
    logger.info(f"Prompt generado para tarea: {task['id']}")
    return prompt


def execute_task(
    task: Dict[str, Any],
    project_context: str = ""
) -> Dict[str, Any]:
    """
    Ejecuta una tarea generando un prompt estructurado para Cline.
    En lugar de simular, produce instrucciones accionables.
    """
    logger.info(
        f"Generando prompt para tarea: {task['description']} (id={task['id']})"
    )

    prompt = generate_cline_prompt(task, project_context)

    result = {
        "task_id": task["id"],
        "task_type": task["type"],
        "description": task["description"],
        "status": "prompt_generated",
        "cline_prompt": prompt,
    }

    logger.info(f"Prompt generado exitosamente para tarea: {task['id']}")
    return result


def plan_project(project_name: str) -> Dict[str, Any]:
    """
    Genera el PLAN de un proyecto: busca en Notion, filtra páginas relevantes,
    construye blueprint y planifica tareas. NO ejecuta nada.

    Si no hay datos relevantes en Notion, genera un blueprint
    inteligente desde el input del usuario.
    """
    logger.info(f"Iniciando plan_project para proyecto: {project_name}")

    # -- Step a: Busqueda en Notion -----------------
    notion_data: List[Dict[str, Any]] = []
    try:
        notion_data = notion_search(project_name)
        logger.info(
            f"Notion search retorno {len(notion_data)} paginas "
            f"para '{project_name}'"
        )
    except APIResponseError as e:
        logger.warning(f"Notion search fallo (API), continuando sin datos: {e}")
    except Exception as e:
        logger.warning(
            f"Notion search fallo (inesperado), continuando sin datos: {e}"
        )

    # -- Step b: Generar blueprint -----------------
    # generate_blueprint internamente filtra datos irrelevantes
    # y usa fallback si no hay datos útiles
    blueprint = generate_blueprint(project_name, notion_data)

    # -- Step c: Planificar tareas -----------------
    task_list = plan_tasks(blueprint)

    logger.info(f"plan_project completado para proyecto '{project_name}'")
    return {
        "blueprint": blueprint,
        "tasks": task_list,
    }


def build_app(project_name: str) -> Dict[str, Any]:
    """
    Orquesta el pipeline completo de creacion de aplicacion:

    1. Buscar paginas relacionadas en Notion
    2. Generar blueprint estructurado (con filtrado + fallback)
    3. Planificar tareas desde el blueprint
    4. Generar prompt ejecutable para Cline con la primera tarea
    """
    logger.info(f"Iniciando build_app para proyecto: {project_name}")

    # -- Step a: Busqueda en Notion -----------------
    try:
        notion_data = notion_search(project_name)
        logger.info(
            f"Notion search retorno {len(notion_data)} paginas "
            f"para '{project_name}'"
        )
    except APIResponseError as e:
        logger.error(f"Notion search fallo (API): {e}")
        raise
    except Exception as e:
        logger.error(f"Notion search fallo (inesperado): {e}")
        raise

    # -- Step b: Generar blueprint -----------------
    blueprint = generate_blueprint(project_name, notion_data)

    # -- Step c: Planificar tareas -----------------
    task_list = plan_tasks(blueprint)

    # -- Step d: Generar prompt para Cline ---------
    if not task_list:
        logger.warning("No se generaron tareas, nada que ejecutar")
        executed_task: Dict[str, Any] = {}
    else:
        context = (
            f"Proyecto: {project_name}\n"
            f"Blueprint: {json.dumps(blueprint, indent=2)}"
        )
        executed_task = execute_task(task_list[0], project_context=context)

    logger.info(f"build_app completado para proyecto '{project_name}'")
    return {
        "project_name": project_name,
        "blueprint": blueprint,
        "task_list": task_list,
        "executed_task": executed_task,
        "status": "success",
    }
