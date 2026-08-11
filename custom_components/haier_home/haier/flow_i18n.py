"""Config/Options flow text, selected by the user's language option.

Unlike ``translations/*.json`` (which the Home Assistant frontend renders using
the *frontend* language of the logged-in user), this module is keyed by the
integration's own ``language`` choice (BCP-47 tags: ``zh-Hans`` / ``en``).

The per-language text lives in ``haier/i18n/<lang>.json`` and is loaded once at
import time. Add a new language by dropping another ``<lang>.json`` file in that
directory (and exposing it in ``LANGUAGE_OPTIONS`` of ``config_flow.py``).

Only pages that come *after* the language selection step can use these strings
(``oauth``, ``homes`` and the whole options flow). The ``eula`` and ``region``
steps are shown before/at the moment of selection, so they keep following the
HA frontend language via ``translations/*.json`` (with ``en.json`` acting as
the fallback for any non-Chinese locale).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..const import DEFAULT_LANGUAGE

_LOGGER = logging.getLogger(__name__)


# Restrict translation files to BCP-47-ish names (``en.json``, ``zh.json``,
# ``zh-Hans.json``...). This blocks path-traversal-style names (``../etc.json``)
# and any unrelated JSON that may end up in the directory. See CWE-22 / CWE-73.
_LANG_FILENAME_RE = re.compile(r"^[a-z]{2}(-[A-Za-z]{2,4})?\.json$")

_I18N_DIR = Path(__file__).resolve().parent / "i18n"

# A translation value is either a leaf string or a nested map of strings (used
# for selector option labels). We never expose ``list`` / ``int`` values.
TranslationValue = str | dict


def _load_translations() -> dict[str, dict]:
    """Load every safe ``i18n/<lang>.json`` file into a ``{lang: data}`` map.

    Only filenames matching ``_LANG_FILENAME_RE`` are loaded, and each resolved
    path must stay inside ``_I18N_DIR`` (defends against symlinks and any
    accidental traversal payload).
    """
    data: dict[str, dict] = {}
    try:
        filenames = [p.name for p in _I18N_DIR.iterdir()]
    except OSError:
        _LOGGER.exception("Failed to list i18n directory %s", _I18N_DIR)
        return data

    for filename in filenames:
        if not _LANG_FILENAME_RE.match(filename):
            if filename.endswith(".json"):
                _LOGGER.warning(
                    "Ignoring unexpected i18n filename %s in %s",
                    filename,
                    _I18N_DIR,
                )
            continue

        path = (_I18N_DIR / filename).resolve()
        # ``resolve()`` follows symlinks. Make sure the final target is still
        # under the package's i18n directory.
        try:
            path.relative_to(_I18N_DIR)
        except ValueError:
            _LOGGER.exception("Refusing to load i18n file outside %s: %s", _I18N_DIR, path)
            continue

        try:
            with path.open(encoding="utf-8") as file:
                loaded = json.load(file)
        except (OSError, ValueError):  # fmt: skip
            _LOGGER.exception("Failed to load i18n file %s", path)
            continue

        if not isinstance(loaded, dict):
            _LOGGER.error("i18n file %s is not a JSON object", path)
            continue

        lang = filename[: -len(".json")]
        data[lang] = loaded
    return data


# Loaded once when the module is first imported.
_TRANSLATIONS: dict[str, dict] = _load_translations()

# Languages that actually have a translation file available.
SUPPORTED_FLOW_LANGUAGES: tuple[str, ...] = tuple(sorted(_TRANSLATIONS)) or (DEFAULT_LANGUAGE,)


def normalize_flow_language(lang: str | None) -> str:
    """Return a language code that has a loaded translation, else English."""
    if lang in _TRANSLATIONS:
        return lang  # type: ignore[return-value]
    return DEFAULT_LANGUAGE


def translate(
    lang: str | None,
    key: str,
    default: Any = "",
) -> Any:
    """Look up ``key`` for ``lang``.

    ``key`` supports a dotted path (e.g. ``"room_sync_options.none"``). The
    lookup falls back to English when the key is missing for the requested
    language, and finally to ``default`` when it is missing everywhere.

    The returned value is either a ``str`` (titles, descriptions, labels) or a
    ``dict[str, str]`` (selector option maps). Callers know the expected type
    per key and may need a runtime check / cast for strict type-checkers.
    Intermediate non-dict values in a dotted key are treated as a miss and
    trigger the English / ``default`` fallback chain, never a ``TypeError``.
    """
    for candidate in (normalize_flow_language(lang), DEFAULT_LANGUAGE):
        result: Any = _TRANSLATIONS.get(candidate)
        found = True
        for part in key.split("."):
            if isinstance(result, dict) and part in result:
                result = result[part]
            else:
                found = False
                break
        if found:
            return result
    return default


# Alias for ``translate``.
flow_t = translate
