"""Text normalization, pronunciation lexicon, and chunking utilities for Skald core."""

from skald_core.text.chunk import ParagraphChunks, chunk_paragraph, normalize_language
from skald_core.text.lexicon import apply_lexicon, count_lexicon_matches
from skald_core.text.normalize import normalize

__all__ = [
    "ParagraphChunks",
    "apply_lexicon",
    "chunk_paragraph",
    "count_lexicon_matches",
    "normalize",
    "normalize_language",
]
