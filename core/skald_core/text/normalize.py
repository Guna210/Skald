"""Text normalization for synthesis (C1.2 step 1)."""

from __future__ import annotations

import re
import unicodedata

# Remove soft hyphens, zero-width spaces, word joiners, and BOM/ZWNBSP.
# Keep U+200C (ZWNJ) and U+200D (ZWJ): they affect spelling/pronunciation in Indic
# and Persian scripts (Kokoro supports Hindi) and join emoji sequences.
_REMOVED_CHARS_TABLE = str.maketrans("", "", "\u00ad\u200b\u2060\ufeff")
_WS_RUN_RE = re.compile(r"\s+")


def _collapse_ws_run(match: re.Match[str]) -> str:
    return "\n" if "\n" in match.group(0) else " "


def normalize(text: str) -> str:
    """Normalize display text into canonical Unicode NFC with collapsed whitespace."""
    # Strip invisible chars before NFC so combining marks adjacent to them still compose on pass 1.
    cleaned = text.translate(_REMOVED_CHARS_TABLE)
    composed = unicodedata.normalize("NFC", cleaned)
    return _WS_RUN_RE.sub(_collapse_ws_run, composed).strip()
