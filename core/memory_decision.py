"""
Capa de decisión de memoria para Nexus BNL.
Determina qué memorias priorizar, ignorar y cómo dar forma al contexto de respuesta.
Determinista — sin AI, sin persistencia, sin mutación.
"""
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class MemoryDecisionLayer:
    """
    Capa que decide qué memorias usar para la respuesta.

    Se inserta entre MemoryIdentityLayer y MemorySynthesizer.
    No modifica los datos de entrada — retorna una nueva lista filtrada y re-scoreada.

    Lógica:
        1. Normalizar mensaje del usuario + detección ligera de intención
        2. Re-scorear cada memoria según relevancia contextual (word-based + stemming)
        3. Penalizar ruido solo en memorias generales débiles
        4. Ordenar por nuevo score descendente
        5. Selección diversa: priorizar identidad por relevancia + top scores, evitar duplicados
        6. Retornar copia filtrada
    """

    # Keys fuertemente ligadas a identidad, en orden de prioridad
    IDENTITY_KEYS: List[str] = ["user_name", "project_name", "goal"]
    IDENTITY_PRIORITY: List[str] = ["goal", "project_name", "user_name"]

    # ── Code intent: Signal A — imperative verbs ──────────────────────
    # Substring match: "haz" matches "hazme", "crea" matches "creame", etc.
    _CODE_VERB_SIGNALS: List[str] = [
        # Spanish imperatives
        "haz", "crea", "genera", "construye", "escribe",
        "implementa", "desarrolla", "programa", "diseña", "dame",
        # English imperatives
        "make", "build", "create", "generate", "write", "implement",
    ]

    # ── Code intent: Signal B — developer/technology keywords ─────────
    # Substring match: covers both full words and compound terms.
    _CODE_DEV_KEYWORDS: List[str] = [
        # UI / screens
        "login", "registro", "pantalla", "componente", "formulario",
        "boton", "navbar", "sidebar", "modal", "form", "vista",
        # App architecture
        "app", "aplicacion", "api", "backend", "frontend", "endpoint",
        "ruta", "router", "servicio", "service", "crud", "modelo", "schema",
        # Frameworks & runtimes
        "react", "native", "firebase", "fastapi", "django", "flask",
        "nodejs", "express", "nextjs", "vue", "angular", "svelte",
        # Languages
        "python", "javascript", "typescript", "kotlin", "swift",
        # Code constructs
        "auth", "autenticacion", "hook", "context", "clase", "funcion",
        "metodo", "modulo", "module", "codigo", "code", "script",
        # Data
        "base de datos", "database", "tabla", "query", "sql",
    ]

    # Mapa de transliteración de acentos -> ASCII (determinista, sin AI)
    ACCENT_MAP: Dict[str, str] = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n",
        "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u",
        "Ü": "u", "Ñ": "n",
    }

    @staticmethod
    def _remove_accents(text: str) -> str:
        """Elimina acentos de forma determinista usando transliteracion."""
        for accented, plain in MemoryDecisionLayer.ACCENT_MAP.items():
            text = text.replace(accented, plain)
        return text

    @staticmethod
    def _normalize(text: str) -> str:
        """
        Normaliza texto para comparacion determinista.
        Convierte a minusculas, elimina acentos y espacios extra.
        """
        text = text.lower().strip()
        text = MemoryDecisionLayer._remove_accents(text)
        return text

    @staticmethod
    def _stem(word: str) -> str:
        """
        Stemming ligero: elimina 's' final en palabras de mas de 3 caracteres.
        Permite que "agentes" coincida con "agente", "python" sigue siendo "python".
        """
        if word.endswith("s") and len(word) > 3:
            return word[:-1]
        return word

    @classmethod
    def _word_based_match(cls, value: str, message: str) -> bool:
        """
        Verifica si hay al menos una palabra en comun entre value y message,
        aplicando stemming basico para robustez linguistica.
        Previene falsos positivos como "ia" dentro de "familia".
        """
        message_words: Set[str] = {cls._stem(w) for w in message.split()}
        value_words: Set[str] = {cls._stem(w) for w in cls._normalize(value).split()}
        return bool(message_words & value_words)

    @classmethod
    def _detect_intent(cls, message: str) -> str:
        """
        Detecta intencion ligera del mensaje del usuario.
        Returns one of the registered intents in ActionRouter.INTENT_ACTION_MAP
        or "general" / "action" / "profile" as fallback categories.

        Intents detectados:
            notion_create, notion_update, notion_delete -> NotionAction
            code_generate, code_refactor, code_debug   -> CodeAction
            file_write, file_read                       -> FileAction
            command_run                                 -> CommandAction
            action, profile, general                    -> Categorias semanticas

        Toda entrada se normaliza (minusculas + sin acentos) antes de comparar,
        por lo que acentos en el input del usuario son ignorados.

        code_generate usa deteccion de dos señales:
            - Señal A: verbo imperativo (haz/crea/genera/build/...)
            - Señal B: keyword de desarrollo (react/api/login/firebase/...)
        Ambas deben estar presentes. No requiere frases exactas.
        """
        message = cls._normalize(message)

        # ── 1. NOTION CREATE ─────────────────────────────────────────
        if any(p in message for p in [
            "crear pagina", "crea una pagina", "crear una pagina",
            "nueva pagina", "crea pagina",
        ]):
            return "notion_create"

        # ── 2. NOTION UPDATE ─────────────────────────────────────────
        if any(p in message for p in [
            "actualiza pagina", "actualizar pagina",
            "actualiza la pagina", "actualizar la pagina",
            "modifica pagina", "modificar pagina",
            "modifica la pagina", "modificar la pagina",
            "edita pagina", "editar pagina",
            "edita la pagina", "editar la pagina",
            "actualiza notion", "actualizar notion",
        ]):
            return "notion_update"

        # ── 3. NOTION DELETE ─────────────────────────────────────────
        if any(p in message for p in [
            "elimina pagina", "eliminar pagina",
            "elimina la pagina", "eliminar la pagina",
            "borra pagina", "borrar pagina",
            "borra la pagina", "borra esa pagina",
            "elimina notion", "eliminar notion",
        ]):
            return "notion_delete"

        # ── 4. CODE GENERATE — two-signal detection ──────────────────
        # Requires BOTH: an imperative verb AND a dev/tech keyword.
        # Substring matching handles inflected forms:
        #   "haz"   matches "hazme", "haz un", "haz una"
        #   "crea"  matches "creame", "crear", "crea un"
        #   "genera" matches "generame", "generar"
        has_verb = any(v in message for v in cls._CODE_VERB_SIGNALS)
        has_dev_kw = any(k in message for k in cls._CODE_DEV_KEYWORDS)

        if has_verb and has_dev_kw:
            return "code_generate"

        # Exact-phrase fallback (backward compatibility)
        if any(p in message for p in [
            "genera codigo", "generar codigo",
            "escribe codigo", "escribir codigo",
            "crea codigo", "crear codigo",
            "write code", "create a component", "generate code",
        ]):
            return "code_generate"

        # ── 5. CODE REFACTOR ─────────────────────────────────────────
        if any(p in message for p in [
            "refactoriza", "refactorizar", "refactor",
            "mejora este codigo", "mejorar este codigo",
            "optimiza codigo", "optimizar codigo",
            "limpia codigo", "limpiar codigo",
        ]):
            return "code_refactor"

        # ── 6. CODE DEBUG ────────────────────────────────────────────
        if any(p in message for p in [
            "debug esto", "debug este codigo",
            "depura", "depurar",
            "arregla este codigo", "arreglar este codigo",
            "corrige el error", "corregir error",
            "debug this",
        ]):
            return "code_debug"

        # ── 7. FILE WRITE ────────────────────────────────────────────
        if any(p in message for p in [
            # Formas directas
            "crea un archivo", "crear archivo", "crear un archivo",
            "crees un archivo",          # "quiero que crees un archivo"
            "crea el archivo",
            # Con adjetivos: "crea un archivo local/simple/nuevo"
            "crea un archivo local", "crea un archivo simple", "crea un archivo nuevo",
            # Escribe
            "escribe un archivo", "escribir archivo", "escribe el archivo",
            # Genera
            "genera un archivo", "generar archivo",
            # Guarda
            "guarda archivo", "guardar archivo",
            # Inglés
            "create a file", "write a file", "create file",
            # Patrones de nombre + extensión comunes
            "archivo llamado", "archivo con el contenido",
        ]):
            return "file_write"

        # ── 8. FILE READ ─────────────────────────────────────────────
        if any(p in message for p in [
            "lee este archivo", "leer archivo",
            "abre archivo", "abrir archivo",
            "muestra archivo", "mostrar archivo",
            "que contiene",
            "read this file", "read file",
        ]):
            return "file_read"

        # ── 9. COMMAND RUN ───────────────────────────────────────────
        if any(p in message for p in [
            "ejecuta", "ejecutar",
            "lanza", "lanzar",
            "run this", "corre el comando",
        ]):
            return "command_run"

        # ── 10. ACTION (preguntas de "como hacer algo") ───────────────
        action_phrases = [
            "como se", "como hacer", "como funciona", "como puedo",
            "como creo", "como creas", "como configuro", "como uso",
            "como ejecuto", "como instalo", "como escribo",
            "how to", "how do", "how can",
        ]
        if any(phrase in message for phrase in action_phrases):
            return "action"

        # ── 11. PROFILE ──────────────────────────────────────────────
        if any(p in message for p in [
            "que sabes", "perfil",
            "sobre mi", "sobre mi perfil",
        ]):
            return "profile"

        # ── 12. GENERAL (fallback) ───────────────────────────────────
        return "general"

    def detect_intent(self, query: str) -> str:
        """
        Metodo publico para detectar intencion.
        Delega al metodo privado _detect_intent.
        """
        return self._detect_intent(query)

    @classmethod
    def _select_diverse(
        cls,
        scored: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Seleccion diversa con prioridad de identidad.

        Estrategia:
            1. Priorizar por tipo: goal > project_name > user_name
            2. Si existe, incluir la mejor de cada tipo (la de mayor score por tipo)
            3. Llenar hasta 5 slots con las memorias de mayor score
            4. Evitar duplicados de mismo (key, value)
        """
        # Agrupar candidatos de identidad por tipo
        identity_by_type: Dict[str, List[Dict[str, Any]]] = {}
        other_candidates: List[Dict[str, Any]] = []

        for item in scored:
            key = item.get("memory", {}).get("key", "")
            if key in cls.IDENTITY_KEYS:
                identity_by_type.setdefault(key, []).append(item)
            else:
                other_candidates.append(item)

        seen_pairs: Set[Tuple[str, str]] = set()
        selected: List[Dict[str, Any]] = []

        # Step 1: seleccionar en orden de prioridad goal > project_name > user_name
        for priority_key in cls.IDENTITY_PRIORITY:
            if len(selected) >= 5:
                break
            candidates = identity_by_type.get(priority_key, [])
            if candidates:
                # candidates ya ordenados por score descendente
                best = candidates[0]
                pair = (best["memory"]["key"], best["memory"]["value"])
                if pair not in seen_pairs:
                    selected.append(best)
                    seen_pairs.add(pair)

        # Step 2: llenar con identidades restantes + otras memorias
        all_remaining: List[Dict[str, Any]] = []
        for key in cls.IDENTITY_PRIORITY:
            candidates = identity_by_type.get(key, [])
            all_remaining.extend(candidates[1:] if candidates else [])
        all_remaining.extend(other_candidates)

        for item in all_remaining:
            if len(selected) >= 5:
                break
            pair = (item["memory"]["key"], item["memory"]["value"])
            if pair not in seen_pairs:
                selected.append(item)
                seen_pairs.add(pair)

        return selected

    @classmethod
    def decide(
        cls,
        ranked_memories: List[Dict[str, Any]],
        identity: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filtra y re-score memorias basandose en el mensaje del usuario y su identidad.

        Args:
            ranked_memories: Lista de dicts con "memory" y "score".
            identity: Dict con perfil de identidad del usuario.
            user_message: Mensaje original del usuario.
            intent: Intencion precomputada. Si es None, se detecta internamente.

        Returns:
            Lista nueva con las top 5 memorias re-scoreadas (sin mutar original).
        """
        if not ranked_memories:
            return []

        # 1. Normalizar mensaje del usuario + detectar intencion
        normalized_message: str = cls._normalize(user_message)

        intent = intent or cls._detect_intent(normalized_message)

        # 2-3. Re-scorear y filtrar
        result: List[Dict[str, Any]] = []

        for item in ranked_memories:
            memory = item.get("memory", {})
            base_score = item.get("score", 0)

            # Ignorar memorias deprecated
            if memory.get("status") == "deprecated":
                continue

            value = memory.get("value", "")
            key = memory.get("key", "")

            if not value:
                continue

            score = base_score

            # +3 si al menos una palabra del valor coincide con el mensaje
            if value and cls._word_based_match(value, normalized_message):
                score += 3

            # +2 si la key esta fuertemente ligada a identidad
            if key in cls.IDENTITY_KEYS:
                score += 2

            # +2 si el valor esta en identity["patterns"]
            if value in identity.get("patterns", []):
                score += 2

            # +1 si el valor esta en identity["interests"]
            if value in identity.get("interests", []):
                score += 1

            # Ajuste por intencion detectada
            if intent == "action" and key == "goal":
                score += 2
            if intent == "profile" and key in ["user_name", "project_name"]:
                score += 2

            # Penalizar ruido: solo memorias "general" cuyo score final
            # sea menor al base (es decir, no recibieron bonus significativo)
            if key == "general" and score < base_score:
                score -= 2

            # Construir nuevo item sin mutar el original
            new_item = dict(item)  # shallow copy del dict externo
            new_item["score"] = score
            result.append(new_item)

        # 4. Ordenar por score descendente
        result.sort(key=lambda x: x.get("score", 0), reverse=True)

        # 5. Seleccion diversa
        selected = cls._select_diverse(result)

        return selected
