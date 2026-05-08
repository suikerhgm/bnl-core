"""
ValidationLayer — verifica que el resultado de una build cumple todos los
requisitos del prompt original antes de dar el flujo por terminado.

Usa exclusivamente string-matching y regex (sin IA).
"""
import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# Números en español → int
_SPANISH_NUMBERS: Dict[str, int] = {
    "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}

# Frameworks reconocidos y sus importaciones canónicas en código
_FRAMEWORK_IMPORTS: Dict[str, List[str]] = {
    "fastapi":  ["from fastapi", "import fastapi"],
    "flask":    ["from flask",   "import flask"],
    "express":  ["require('express')", 'require("express")', "from express"],
    "django":   ["from django",  "import django"],
    "react":    ["from react",   "import react", "import React"],
    "vue":      ["from vue",     "import vue",   "createApp"],
}

# Extensions treated as UI/frontend files for button counting
_UI_EXTENSIONS = (".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte")

# Words that negate a framework mention ("sin vue", "no react", "without vue")
_NEGATION_WORDS = frozenset({"sin", "no", "without", "none", "not", "ningún", "ninguna"})


class ValidationLayer:
    """Valida determinísticamente que un resultado de build cumple el prompt."""

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def validate(self, idea: str, result: dict) -> dict:
        """
        Compara los requisitos extraídos de *idea* contra los archivos en *result*.

        Args:
            idea:   Prompt original del usuario.
            result: Dict con clave "files" → lista de {path, content}.

        Returns:
            {
                "is_valid":      bool,
                "missing":       list[str],
                "suggested_fix": str,
            }
        """
        logger.warning("=" * 60)
        logger.warning("🔍 [VALIDATION] START")
        logger.warning("🔍 [VALIDATION] idea: %s", idea)

        requirements = self._extract_requirements(idea)
        logger.warning(
            "🔍 [VALIDATION] requirements extracted → endpoints=%s  buttons=%d  frameworks=%s",
            requirements["endpoints"],
            requirements["buttons"],
            requirements["frameworks"],
        )

        contents = self._collect_contents(result)
        logger.warning(
            "🔍 [VALIDATION] files to analyse: %s",
            list(contents.keys()) or "(none)",
        )
        for path, content in contents.items():
            preview = content[:300].replace("\n", "\\n")
            logger.warning("🔍 [VALIDATION] %s → %s", path, preview)

        missing = self._find_missing(requirements, contents)

        if not missing:
            logger.warning("✅ [VALIDATION PASSED] proyecto completo")
            logger.warning("=" * 60)
            return {"is_valid": True, "missing": [], "suggested_fix": ""}

        logger.warning("❌ [VALIDATION FAILED]")
        logger.warning("❌ missing: %s", missing)
        logger.warning("=" * 60)

        suggested_fix = "corrige lo siguiente: " + ", ".join(missing)
        return {
            "is_valid": False,
            "missing": missing,
            "suggested_fix": suggested_fix,
        }

    # ──────────────────────────────────────────────────────────────────
    # Requirement extraction
    # ──────────────────────────────────────────────────────────────────

    def _extract_requirements(self, idea: str) -> dict:
        return {
            "endpoints":  self._extract_endpoints(idea),
            "buttons":    self._extract_button_count(idea),
            "frameworks": self._extract_frameworks(idea),
        }

    def _extract_endpoints(self, idea: str) -> List[str]:
        """Extrae rutas /palabra del prompt, ignora extensiones de archivo."""
        raw = re.findall(r'/[a-zA-Z][a-zA-Z0-9_/-]*', idea)
        seen: List[str] = []
        for ep in raw:
            # Skip file-path-like tokens (contain a dot extension)
            if ep not in seen and not re.search(r'\.\w{1,5}$', ep):
                seen.append(ep)
        return seen

    def _extract_button_count(self, idea: str) -> int:
        """Extrae cantidad de botones requeridos; 0 si no se menciona."""
        # Arabic digit: "2 botones", "3 buttons"
        m = re.search(r'(\d+)\s*boton(?:es)?', idea, re.IGNORECASE)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d+)\s*button', idea, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # Spanish word: "dos botones"
        idea_lower = idea.lower()
        for word, value in _SPANISH_NUMBERS.items():
            if re.search(rf'\b{word}\s+boton(?:es)?', idea_lower):
                return value
        return 0

    def _extract_frameworks(self, idea: str) -> List[str]:
        """Return frameworks explicitly requested in *idea*, skipping negated mentions.

        Bug #2 fix: "sin vue", "no vue", "without vue" must NOT add vue to requirements.
        Looks back up to 40 chars before each match for a negation word.
        """
        idea_lower = idea.lower()
        result: List[str] = []
        for fw in _FRAMEWORK_IMPORTS:
            for m in re.finditer(re.escape(fw), idea_lower):
                window = idea_lower[max(0, m.start() - 40): m.start()]
                if set(window.split()) & _NEGATION_WORDS:
                    continue  # negated mention — skip
                result.append(fw)
                break
        return result

    # ──────────────────────────────────────────────────────────────────
    # Content collection
    # ──────────────────────────────────────────────────────────────────

    def _collect_contents(self, result: dict) -> Dict[str, str]:
        """Devuelve {path: content} de todos los archivos en result["files"]."""
        contents: Dict[str, str] = {}
        for f in result.get("files", []):
            path = f.get("path", "")
            content = f.get("content", "")
            if path:
                contents[path] = content
        return contents

    # ──────────────────────────────────────────────────────────────────
    # Missing detection
    # ──────────────────────────────────────────────────────────────────

    def _find_missing(self, requirements: dict, contents: Dict[str, str]) -> List[str]:
        missing: List[str] = []
        all_text = "\n".join(contents.values())

        # ── 1. Endpoints ──────────────────────────────────────────────
        # Must appear as a quoted route string: "/ping" or '/ping'
        for endpoint in requirements["endpoints"]:
            ep_esc = re.escape(endpoint)
            # Match "/ping" or '/ping' in route decorators / route definitions
            pattern = rf'["\']({ep_esc})["\']'
            found = bool(re.search(pattern, all_text))
            logger.warning(
                "🔍 [VALIDATION] endpoint '%s' → quoted match: %s",
                endpoint, found,
            )
            if not found:
                missing.append(f"endpoint {endpoint}")

        # ── 2. Buttons ────────────────────────────────────────────────
        required_buttons = requirements["buttons"]
        if required_buttons > 0:
            ui_text = ""
            for path, content in contents.items():
                if path.lower().endswith(_UI_EXTENSIONS):
                    ui_text += content

            # Count both HTML <button and JSX <Button
            actual = len(re.findall(r'<[Bb]utton[\s\n\r>\/]', ui_text))
            logger.warning(
                "🔍 [VALIDATION] buttons → required=%d  found=%d  ui_files=%s",
                required_buttons,
                actual,
                [p for p in contents if p.lower().endswith(_UI_EXTENSIONS)],
            )
            if actual < required_buttons:
                missing.append(
                    f"botón(es) en frontend "
                    f"(encontrados: {actual}, requeridos: {required_buttons})"
                )

        # ── 3. Frameworks ─────────────────────────────────────────────
        all_lower = all_text.lower()
        for fw in requirements["frameworks"]:
            tokens = _FRAMEWORK_IMPORTS.get(fw, [fw])
            found = any(t.lower() in all_lower for t in tokens)
            logger.warning(
                "🔍 [VALIDATION] framework '%s' → found: %s", fw, found,
            )
            if not found:
                missing.append(f"framework {fw}")

        return missing
