"""User-facing string translation: English source text -> Persian.

Deliberately not Qt's .ts/.qm tooling -- a plain dict keyed by the exact
English string is enough for two languages and needs no build step. Every
user-visible literal in ui/*.py is wrapped in tr(); with the default
language "en" (or any key missing from the fa table) tr() returns the
English text unchanged, so this module never breaks the default UI and
never raises -- a bad or missing translation degrades to English, not a
crash.

core/ must stay Qt-free and English (see CLAUDE.md); this module is
imported only by ui/*.py, which passes core's own English strings
through tr() using the exact same source text the fa table is keyed on.
"""
from __future__ import annotations

from .i18n_fa import TRANSLATIONS_FA

_SUPPORTED = ("en", "fa")
_current = "en"


def set_language(code: str) -> None:
    global _current
    _current = code if code in _SUPPORTED else "en"


def current() -> str:
    return _current


def tr(text: str, **params) -> str:
    """`text` translated to the current language, else `text` itself; then
    `.format(**params)` if `params` were given. Never raises: a missing
    key or a translation with the wrong placeholders both fall back to
    the formatted English source."""
    table = TRANSLATIONS_FA if _current == "fa" else None
    translated = table.get(text, text) if table else text
    if not params:
        return translated
    try:
        return translated.format(**params)
    except (KeyError, IndexError, ValueError):
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
