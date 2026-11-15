"""Book import and parsing modules for Skald core."""

from skald_core.book.epub import (
    EpubChapterEntry,
    EpubCover,
    EpubMetadata,
    EpubStructure,
    parse_epub,
)

__all__ = [
    "EpubChapterEntry",
    "EpubCover",
    "EpubMetadata",
    "EpubStructure",
    "parse_epub",
]
