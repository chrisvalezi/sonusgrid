# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiny bilingual helper. Strings are written inline as (pt, en) pairs.

Language resolution: explicit `set_language()` (from config `ui.language`),
else $LANGUAGE / $LC_ALL / $LC_MESSAGES / $LANG.
"""

from __future__ import annotations

import locale
import os

_forced: str | None = None


def _env_lang() -> str:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            return v.split(":")[0]
    try:
        return locale.getlocale()[0] or ""
    except Exception:
        return ""


def set_language(lang: str | None) -> None:
    """`pt`, `en` or None/'auto'."""
    global _forced
    _forced = lang if lang in ("pt", "en") else None


def is_pt() -> bool:
    if _forced:
        return _forced == "pt"
    return _env_lang().lower().startswith("pt")


def _t(pt: str, en: str) -> str:
    return pt if is_pt() else en
