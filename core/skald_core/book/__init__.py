"""Book import and parsing modules for Skald core."""

from skald_core.book.epub import (
    BodySlice,
    EpubChapterEntry,
    EpubCover,
    EpubMetadata,
    EpubStructure,
    parse_epub,
    resolve_body_slices,
    walk_body_slice,
)

__all__ = [
    "BodySlice",
    "EpubChapterEntry",
    "EpubCover",
    "EpubMetadata",
    "EpubStructure",
    "parse_epub",
    "resolve_body_slices",
    "walk_body_slice",
]
