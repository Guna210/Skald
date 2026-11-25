"""Text normalization and pronunciation lexicon utilities for Skald core."""

from skald_core.text.lexicon import apply_lexicon, count_lexicon_matches
from skald_core.text.normalize import normalize

__all__ = [
    "apply_lexicon",
    "count_lexicon_matches",
    "normalize",
]
