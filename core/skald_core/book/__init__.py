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
from skald_core.book.text_import import TextImport, load_markdown_book, load_text_book
from skald_core.book.xhtml import load_epub_book

__all__ = [
    "BodySlice",
    "EpubChapterEntry",
    "EpubCover",
    "EpubMetadata",
    "EpubStructure",
    "TextImport",
    "load_epub_book",
    "load_markdown_book",
    "load_text_book",
    "parse_epub",
    "resolve_body_slices",
    "walk_body_slice",
]
