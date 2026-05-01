# 📌 Notion Unification — Canonical Implementation Decision

> **Date:** 28/04/2026
> **Status:** Design only — no implementation
> **Purpose:** Decide which Notion implementation should be the single source of truth

---

## The Two Implementations

| Aspect | `services/notion_service.py` (Legacy) | `core/notion_gateway.py` (Modern) |
|---|---|---|
| **Location** | `services/notion_service.py` | `core/notion_gateway.py` |
| **Librería** | `notion_client` SDK (official) | `httpx` raw API calls |
| **Async/Sync** | **Sync** | **Async** |
| **Dependencies** | `notion-client` package | `httpx` only |
| **Used by** | `routes/notion_routes.py`, `routes/build_routes.py` (legacy REST endpoints) | `core/memory_manager.py`, `orchestrators/conversation_orchestrator.py`, `orchestrators/cleaning_orchestrator.py` |
| **`notion_search`** | Retorna `List[dict]` (formateado) | Retorna `Dict` (API response crudo) |
| **`notion_create`** | `(parent_id, title, content)` → page | `(database_id, properties, children)` → database page |
| **`notion_fetch`** | Retorna markdown procesado | Retorna blocks API response |
| **Error handling** | Basic | Robust (ID cleaning, 404/400 messages, timeout handling) |
| **Test coverage** | None | None |
| **Lines of code** | ~100 | ~317 |

---

## Decision: Keep `core/notion_gateway.py`, Deprecate `services/notion_service.py`

### Why `core/notion_gateway.py` wins

| Reason | Detail |
|---|---|
| **Async-native** | Matches the entire modern stack (`httpx.AsyncClient`). The legacy sync SDK blocks the event loop. |
| **Active usage** | Every active flow uses `core/notion_gateway.py` — memory manager, conversation orchestrator, cleaning orchestrator. The legacy `services/notion_service.py` is only used by dead REST routes. |
| **Superior error handling** | Validates and cleans page IDs (`_clean_page_id`), returns descriptive error messages ("No se encontró la página con ID..."), handles 404/400 separately, wraps all calls in try/except for network errors. |
| **Database-specific operations** | Supports `_notion_query_database()` for filtering by title within a specific database — needed by MemoryManager and CleaningOrchestrator. Legacy has no equivalent. |
| **Fuzzy matching** | `_fuzzy_match_title()` for duplicate detection in cleaning flow. Legacy has no equivalent. |
| **Block construction** | `build_notion_blocks()` for creating structured Notion content with chunking. Legacy has no equivalent. |
| **Granularity** | `notion_update()` for updating just properties of existing pages — used by cleaning orchestrator. Legacy has no equivalent. |
| **Design philosophy** | Wraps raw API in deterministic pure functions. No SDK coupling. Easy to test (mock httpx). |

### What would be lost from `services/notion_service.py`

| Feature | Status |
|---|---|
| `notion_search()` returning `List[dict]` | Formatting preference — `core/notion_gateway.py` returns raw `Dict` which is less convenient for direct display but preserves all data. The `MemoryManager._normalize_notion_result()` already handles this normalization for the memory flow. |
| SDK-backed reliability | The official SDK handles edge cases like pagination and rate limiting. However, the raw httpx implementation has proven stable and the SDK's extra abstraction adds complexity without benefit for this use case. |

### Deprecation plan (conceptual)

1. **Add deprecation warning** to `services/notion_service.py` docstring: `"⚠️ DEPRECATED — use core/notion_gateway instead"`
2. **Rewrite `routes/notion_routes.py`** to import from `core/notion_gateway.py` (the legacy endpoints still serve n8n workflows)
3. **Verify n8n compatibility** — the legacy endpoints (`/search`, `/fetch`, `/create`) return different schemas. Either:
   - Adapt the routes to maintain backward compatibility for n8n
   - Or update the n8n workflow to match the new response format
4. **Remove** `notion_client` from `requirements.txt` after migration

### Why NOT to keep both

- **Bugs are asymmetric** — a fix in one implementation won't apply to the other
- **Cognitive load** — developers must know which implementation is "correct"
- **Testing burden** — both need to be tested independently
- **Schema drift** — the two implementations can return incompatible data for the same operation
- **The legacy has zero active callers in the modern flow** — it only exists for backward compatibility with n8n, which already has a directly connected workflow

---

## Summary

| Decision | Value |
|---|---|
| **Keep** | `core/notion_gateway.py` |
