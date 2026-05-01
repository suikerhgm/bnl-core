"""
Módulo de gestión de memoria para Nexus BNL.
Responsabilidades:
  1. Guardar memoria episódica en Notion
  2. Recuperar memoria relevante según consulta
Versión 1 — Sin embeddings, sin AI, sin async complejo.
"""
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.notion_gateway import notion_create, _notion_query_database

logger = logging.getLogger(__name__)

# ── IDs de bases de datos (desde .env) ──────────────────────────────
MEMORY_EPISODES_DB_ID = os.getenv("NOTION_MEMORY_EPISODES_DB_ID", "")
MEMORY_SEMANTIC_DB_ID = os.getenv("NOTION_MEMORY_SEMANTIC_DB_ID", "")


class MemoryManager:
    """
    Gestor de memoria del sistema.
    Versión 1 — búsqueda por heurística simple sin embeddings.
    """

    # ── API pública ─────────────────────────────────────────────

    async def deprecate_memory(self, key: str, value: str) -> None:
        """
        Marca memorias conflictivas como deprecated en almacenamiento persistente.

        En esta versión (v1) la operación es un no-op controlado,
        ya que el almacenamiento es solo-append.
        La corrección queda registrada en el log y en el historial
        de correcciones guardado por save_episode.

        Args:
            key:   Clave de la memoria (ej: "user_name").
            value: Valor que se desea deprecar.
        """
        logger.info(
            "🗑️  deprecate_memory called: key='%s' value='%s' "
            "(no-op en v1, corrección registrada vía save_episode)",
            key, value,
        )

    async def save_episode(
        self,
        content: str,
        summary: str,
        tags: list[str],
        importance: int = 3,
    ) -> None:
        """
        Guarda un episodio en la base de datos Memory_Episodes de Notion.

        Args:
            content:  Texto completo del episodio.
            summary:  Título / resumen corto del episodio.
            tags:     Lista de etiquetas (multi-select).
            importance: Nivel de importancia 1‑5.
        """
        if not MEMORY_EPISODES_DB_ID:
            logger.warning("⚠️  NOTION_MEMORY_EPISODES_DB_ID no está configurada")
            return

        now = datetime.utcnow().isoformat() + "Z"

        properties = {
            "summary": {
                "title": [{"type": "text", "text": {"content": summary[:100]}}],
            },
            "content": {
                "rich_text": [{"type": "text", "text": {"content": content}}],
            },
            "tags": {
                "multi_select": [{"name": t} for t in tags],
            },
            "importance": {
                "number": max(1, min(5, importance)),
            },
            "created_at": {
                "date": {"start": now},
            },
        }

        try:
            result = await notion_create(MEMORY_EPISODES_DB_ID, properties)
            if "error" in result:
                logger.error("❌ Error al guardar episodio en Notion: %s", result["error"])
            else:
                logger.info("✅ Episodio guardado en Notion: «%s»", summary)
        except Exception as e:
            logger.error("❌ Excepción al guardar episodio: %s", e, exc_info=True)

    async def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """
        Recupera las memorias más relevantes para una consulta.

        Args:
            query: Texto de la consulta.
            k:     Número máximo de resultados a retornar.

        Returns:
            Lista de dicts normalizados con las memorias más relevantes.
        """
        query_type = self._classify_query_type(query)
        logger.debug("🔍 Query type: %s — «%s»", query_type, query)

        sources: list[str] = []
        if query_type in ("contextual", "action"):
            sources.append("episodic")
        if query_type in ("knowledge", "action"):
            sources.append("semantic")

        # Si no se pudo clasificar, por defecto episódica
        if not sources:
            sources = ["episodic"]

        all_memories: list[dict] = []

        for source in sources:
            if source == "episodic" and MEMORY_EPISODES_DB_ID:
                raw = await _notion_query_database(MEMORY_EPISODES_DB_ID, query)
                all_memories.extend(
                    self._normalize_notion_result(raw, "episodic")
                )
            elif source == "semantic" and MEMORY_SEMANTIC_DB_ID:
                raw = await _notion_query_database(MEMORY_SEMANTIC_DB_ID, query)
                all_memories.extend(
                    self._normalize_notion_result(raw, "semantic")
                )

        # Puntuar y rankear
        scored = [
            (self._score_memory(query, m), m) for m in all_memories
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        results = [m for _, m in scored[:k]]

        # ── Fallback: si no hay resultados, traer episodios recientes ──
        if not results and MEMORY_EPISODES_DB_ID:
            logger.info("🔍 Sin resultados por query, trayendo episodios recientes")
            try:
                recent_raw = await _notion_query_database(
                    MEMORY_EPISODES_DB_ID, query=""
                )
                recent = self._normalize_notion_result(recent_raw, "episodic")
                results = recent[:k]
            except Exception as e:
                logger.warning("⚠️ Fallo al recuperar episodios recientes: %s", e)

        # ── Hard fallback: garantizar que siempre se retorne algo ──
        if not results:
            logger.warning("⚠️ No memories found at all — returning empty safe fallback")
            return [{
                "type": "episodic",
                "summary": "No stored memory found",
                "content": "",
                "tags": [],
            }]

        logger.info(f"🧠 Retrieved {len(results)} memories")
        return results

    # ── Métodos internos ────────────────────────────────────────

    @staticmethod
    def _classify_query_type(query: str) -> str:
        """
        Clasifica el tipo de consulta según palabras clave.

        Returns:
            "action", "knowledge" o "contextual".
        """
        q = query.lower().strip()

        if q.startswith("cómo") or q.startswith("how"):
            return "action"
        if q.startswith("qué es") or q.startswith("what is"):
            return "knowledge"
        return "contextual"

    @staticmethod
    def _score_memory(query: str, memory: dict) -> int:
        """
        Puntúa una memoria según su relevancia frente a la consulta.

        Reglas:
          +3 si la consulta aparece en content o summary.
          +2 si alguna tag coincide con palabras de la consulta.
          +1 si es reciente (no implementado en v1, se asume todo reciente).
        """
        score = 0
        q_lower = query.lower()

        # +3 coincidencia en contenido o resumen
        content = (memory.get("content") or "").lower()
        summary = (memory.get("summary") or "").lower()

        if q_lower in content or q_lower in summary:
            score += 3

        # +2 coincidencia por tags
        query_words = set(q_lower.split())
        memory_tags = memory.get("tags", [])
        if any(t.lower() in query_words for t in memory_tags):
            score += 2

        return score

    @staticmethod
    def _normalize_notion_result(
        raw: dict,
        memory_type: str,
    ) -> list[dict[str, Any]]:
        """
        Convierte la respuesta cruda de Notion en una lista de dicts
        normalizados con formato uniforme.
        """
        results = raw.get("results", [])
        normalized: list[dict[str, Any]] = []

        for page in results:
            props = page.get("properties", {})

            # Extraer título (summary)
            summary = ""
            title_field = props.get("summary") or props.get("title") or {}
            title_list = title_field.get("title", [])
            if title_list:
                summary = title_list[0].get("text", {}).get("content", "")

            # Extraer content (rich_text)
            content = ""
            content_field = props.get("content", {})
            rich_list = content_field.get("rich_text", [])
            if rich_list:
                content = rich_list[0].get("text", {}).get("content", "")

            # Extraer tags (multi_select)
            tags: list[str] = []
            tags_field = props.get("tags", {})
            for ms in tags_field.get("multi_select", []):
                tags.append(ms.get("name", ""))

            normalized.append({
                "type": memory_type,
                "summary": summary,
                "content": content,
                "tags": tags,
            })

        return normalized
