"""
Formateadores de respuestas para mostrar resultados al usuario.
Incluye formateo de salidas y construcción de contexto de memoria.
"""
from typing import Dict, List


def _format_plan_result(result: Dict) -> str:
    """Formatea la respuesta de build_app para mostrarla en Telegram."""
    plan_id = result.get("plan_id", "?")
    status = result.get("status", "unknown")
    blueprint = result.get("blueprint", {})
    tasks = result.get("tasks", [])

    lines = [
        f"✅ **Plan generado exitosamente**",
        "",
        f"📋 **Plan ID:** `{plan_id}`",
        f"📌 **Estado:** {status}",
        "",
        f"🏗️ **Blueprint:**",
        f"  • Proyecto: {blueprint.get('project_name', '?')}",
        f"  • Entidades: {len(blueprint.get('entities', []))}",
        f"  • Pantallas: {len(blueprint.get('screens', []))}",
        f"  • Componentes: {len(blueprint.get('components', []))}",
        f"  • Flujos: {len(blueprint.get('flows', []))}",
        "",
        f"📝 **Tareas planificadas ({len(tasks)}):**",
    ]
    for i, task in enumerate(tasks[:10], 1):
        lines.append(f"  {i}. `{task['description']}`")
    if len(tasks) > 10:
        lines.append(f"  ... y {len(tasks) - 10} tareas más")
    lines.extend([
        "",
        f"⚡ **¿Quieres que lo ejecute?**",
    ])
    return "\n".join(lines)



def _format_execution_result(result: Dict) -> str:
    """Formatea la respuesta de execute_plan para mostrarla en Telegram."""
    plan_id = result.get("plan_id", "?")
    status = result.get("status", "unknown")
    results = result.get("results", [])

    lines = [
        f"⚡ **Ejecución completada**",
        "",
        f"📋 **Plan ID:** `{plan_id}`",
        f"📌 **Estado:** {status}",
        "",
        f"📝 **Resultados ({len(results)} tareas):**",
    ]
    for i, task_result in enumerate(results, 1):
        t_id = task_result.get("task_id", "?")
        t_status = task_result.get("status", "?")
        t_desc = task_result.get("description", "?")
        emoji = "✅" if t_status == "prompt_generated" else "⏳"
        lines.append(f"  {emoji} `{t_id}` — {t_desc} ({t_status})")
    lines.append("")
    lines.append("💡 Los prompts generados están listos para usar en Cline.")
    return "\n".join(lines)


# ── Memory context builder ──────────────────────────────────────────

def build_memory_context(memories: list[dict]) -> str:
    """
    Construye un bloque de contexto textual a partir de memorias recuperadas.

    Args:
        memories: Lista de dicts normalizados (type, summary, content, tags).

    Returns:
        String formateado listo para inyectar en el prompt de la IA.
        Vacío si no hay memorias.
    """
    if not memories:
        return ""

    context = "[MEMORY CONTEXT]\n\n"
    for m in memories:
        summary = m.get("summary", "")
        if summary:
            context += f"- {summary}\n"

    context += "\n[END MEMORY]"
    return context
