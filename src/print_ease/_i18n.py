"""Internationalisierung für PrintEase via GNU gettext."""
from __future__ import annotations

import gettext
import os
from pathlib import Path

LOCALE_DIR = Path(__file__).parent / "locale"
DOMAIN = "print_ease"

# Nativsprachige Klarnamen aller 34 unterstützten Sprachen
LANG_NAMES: dict[str, str] = {
    "de":    "Deutsch",
    "en":    "English",
    "fr":    "Français",
    "es":    "Español",
    "it":    "Italiano",
    "pl":    "Polski",
    "pt":    "Português",
    "nl":    "Nederlands",
    "cs":    "Čeština",
    "ro":    "Română",
    "ja":    "日本語",
    "sv":    "Svenska",
    "da":    "Dansk",
    "nb":    "Norsk bokmål",
    "fi":    "Suomi",
    "hu":    "Magyar",
    "sk":    "Slovenčina",
    "hr":    "Hrvatski",
    "sr":    "Srpski",
    "bg":    "Български",
    "el":    "Ελληνικά",
    "tr":    "Türkçe",
    "zh_CN": "中文（简体）",
    "zh_TW": "中文（繁體）",
    "ar":    "العربية",
    "hi":    "हिन्दी",
    "th":    "ภาษาไทย",
    "vi":    "Tiếng Việt",
    "id":    "Bahasa Indonesia",
    "uk":    "Українська",
    "ru":    "Русский",
    "he":    "עברית",
    "fa":    "فارسی",
}


def _load_linguas() -> list[str]:
    """Liest verfügbare Sprachcodes aus locale/LINGUAS."""
    try:
        return (LOCALE_DIR / "LINGUAS").read_text(encoding="utf-8").split()
    except OSError:
        return list(LANG_NAMES.keys())


SUPPORTED_LANGS: list[str] = _load_linguas()

_translation: gettext.GNUTranslations | gettext.NullTranslations | None = None


def setup_i18n(lang: str | None = None) -> None:
    """
    Initialisiert die Übersetzung.
    lang=None → Systemsprache (LANGUAGE/LANG-Umgebungsvariablen).
    lang="de" → explizit Deutsch usw.
    """
    global _translation
    languages: list[str] | None = None
    if lang:
        # FIX #47: Fallback-Kette: gewünschte Sprache → Basis-Code → Englisch → Deutsch
        candidates = [lang]
        if len(lang) > 2:
            candidates.append(lang[:2])
        candidates += ["en", "de"]
        languages = candidates
    try:
        _translation = gettext.translation(
            DOMAIN,
            localedir=str(LOCALE_DIR),
            languages=languages,
            fallback=True,
        )
    except Exception:
        _translation = gettext.NullTranslations()


def _(text: str) -> str:
    if _translation is None:
        return text
    return _translation.gettext(text)


def get_current_lang() -> str:
    """
    Gibt den aktuell aktiven Sprachcode zurück (z.B. 'de', 'en', 'zh_CN').
    Priorität: gespeicherte Einstellung → Systemumgebung → 'de'.
    """
    # 1. Gespeicherte Einstellung
    try:
        from print_ease import settings
        saved = settings.get("language")
        if saved and saved in SUPPORTED_LANGS:
            return saved
    except Exception:
        pass

    # 2. Umgebungsvariablen (LANGUAGE kann colon-separiert sein)
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        raw = os.environ.get(var, "")
        for token in raw.split(":"):
            code = token.split(".")[0]  # "de_AT.UTF-8" → "de_AT"
            if code in SUPPORTED_LANGS:
                return code
            base = code[:2]             # "de_AT" → "de"
            if base in SUPPORTED_LANGS:
                return base

    return "de"
