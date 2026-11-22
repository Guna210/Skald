"""XHTML-to-paragraphs extractor for EPUB books (C1.1 step 5)."""

from __future__ import annotations

import hashlib
import itertools
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree  # type: ignore[import-untyped]

from skald_core.book.epub import (
    HEADING_TAGS,
    BodySlice,
    _collapse_ws,
    _get_epub_type_tokens,
    _local_name,
    _parse_content_xhtml,
    parse_epub,
    resolve_body_slices,
    walk_body_slice,
)
from skald_core.schemas.models import Book, Chapter, Paragraph

_SKIP_TAGS: frozenset[str] = frozenset({"script", "style", "img", "rt", "rp"})
_SKIP_EPUB_TYPES: frozenset[str] = frozenset({"noteref", "footnote", "endnote", "pagebreak"})
_SKIP_ROLES: frozenset[str] = frozenset(
    {"doc-noteref", "doc-footnote", "doc-endnote", "doc-pagebreak"}
)

_BLOCK_TAGS: frozenset[str] = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "caption",
        "center",
        "dd",
        "details",
        "dialog",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "legend",
        "li",
        "main",
        "menu",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)


@dataclass(slots=True)
class _TableRow:
    cells: list[str] = field(default_factory=list)
    current_cell: list[list[str]] | None = None


def _get_role_tokens(el: etree._Element) -> set[str]:
    if not isinstance(el.tag, str):
        return set()
    raw = el.get("role") or ""
    return {tok.strip().lower() for tok in raw.split() if tok.strip()}


def _should_skip_element(el: etree._Element, tag_name: str) -> bool:
    if tag_name in _SKIP_TAGS:
        return True
    if _get_epub_type_tokens(el) & _SKIP_EPUB_TYPES:
        return True
    if _get_role_tokens(el) & _SKIP_ROLES:
        return True
    return False


def _finalize_segments(segments: list[list[str]]) -> str:
    lines: list[str] = []
    for seg in segments:
        cleaned = _collapse_ws("".join(seg))
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _chapter_id(index: int, full_href: str) -> str:
    digest = hashlib.sha256(f"{index}\0{full_href}".encode()).hexdigest()
    return f"ch_{digest[:8]}"


def _paragraph_id(chapter_id: str, paragraph_index: int, text: str) -> str:
    digest = hashlib.sha256(f"{chapter_id}\0{paragraph_index}\0{text}".encode()).hexdigest()
    return f"p_{digest[:16]}"


def _extract_slice_paragraphs(body_slice: BodySlice, chapter_id: str) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    buf_segments: list[list[str]] = [[]]
    heading_depth = 0
    row_stack: list[_TableRow] = []
    skipped_stack: list[etree._Element] = []

    def _emit_paragraph(text: str, *, is_heading: bool) -> None:
        if not text:
            return
        idx = len(paragraphs)
        paragraphs.append(
            Paragraph(
                id=_paragraph_id(chapter_id, idx, text),
                text=text,
                is_heading=is_heading,
            )
        )

    def _flush_buffer() -> None:
        nonlocal buf_segments
        text = _finalize_segments(buf_segments)
        buf_segments = [[]]
        if text:
            _emit_paragraph(text, is_heading=heading_depth > 0)

    def _flush_cell() -> None:
        row = row_stack[-1]
        if row.current_cell is None:
            return
        cell_text = _finalize_segments(row.current_cell)
        row.current_cell = None
        if cell_text:
            row.cells.append(cell_text)

    def _on_enter(el: etree._Element) -> bool | None:
        nonlocal heading_depth
        tag_name = _local_name(el)

        if _should_skip_element(el, tag_name):
            if not row_stack and tag_name in _BLOCK_TAGS:
                _flush_buffer()
            skipped_stack.append(el)
            return False

        if tag_name == "br":
            if row_stack:
                cell = row_stack[-1].current_cell
                if cell is not None:
                    cell.append([])
            else:
                buf_segments.append([])
            return None

        if tag_name == "tr":
            if not row_stack:
                _flush_buffer()
            row_stack.append(_TableRow())
            return None

        if row_stack:
            row = row_stack[-1]
            if tag_name in {"td", "th"}:
                if row.current_cell is not None:
                    _flush_cell()
                row.current_cell = [[]]
            elif tag_name in _BLOCK_TAGS and row.current_cell is not None:
                row.current_cell[-1].append(" ")
            return None

        if tag_name in _BLOCK_TAGS:
            _flush_buffer()
            if tag_name in HEADING_TAGS:
                heading_depth += 1

        return None

    def _on_text(text: str) -> None:
        if row_stack:
            cell = row_stack[-1].current_cell
            if cell is not None:
                cell[-1].append(text)
        else:
            buf_segments[-1].append(text)

    def _on_exit(el: etree._Element) -> None:
        nonlocal heading_depth
        if skipped_stack and skipped_stack[-1] is el:
            skipped_stack.pop()
            return

        tag_name = _local_name(el)

        if tag_name == "tr":
            if row_stack:
                _flush_cell()
                row = row_stack.pop()
                if row.cells:
                    _emit_paragraph(" ".join(row.cells), is_heading=False)
            return

        if row_stack:
            row = row_stack[-1]
            if tag_name in {"td", "th"}:
                _flush_cell()
            elif tag_name in _BLOCK_TAGS and row.current_cell is not None:
                row.current_cell[-1].append(" ")
            return

        if tag_name in _BLOCK_TAGS:
            _flush_buffer()
            if tag_name in HEADING_TAGS and heading_depth > 0:
                heading_depth -= 1

    walk_body_slice(body_slice, on_enter=_on_enter, on_text=_on_text, on_exit=_on_exit)
    _flush_buffer()
    return paragraphs


def load_epub_book(path: Path | str) -> Book:
    """Parse an EPUB file and extract chapters and paragraphs into a ``Book``."""
    epub_path = Path(path)
    structure = parse_epub(epub_path)

    doc_cache: dict[str, etree._Element] = {}
    chapters: list[Chapter] = []

    with zipfile.ZipFile(epub_path, "r") as zf:
        for href, group in itertools.groupby(
            enumerate(structure.chapters),
            key=lambda pair: pair[1].href,
        ):
            entries = list(group)
            doc_root = doc_cache.get(href)
            if doc_root is None:
                doc_root = _parse_content_xhtml(zf.read(href), href)
                doc_cache[href] = doc_root

            anchors = [entry.anchor for _, entry in entries]
            body_slices = resolve_body_slices(doc_root, anchors, href)

            for (ch_index, entry), body_slice in zip(entries, body_slices, strict=True):
                ch_id = _chapter_id(ch_index, entry.full_href)
                paragraphs = _extract_slice_paragraphs(body_slice, ch_id)
                chapters.append(
                    Chapter(
                        id=ch_id,
                        title=entry.title,
                        included=entry.linear and not entry.suggested_skip,
                        linear=entry.linear,
                        skip_reasons=list(entry.skip_reasons),
                        paragraphs=paragraphs,
                    )
                )

    return Book(
        title=structure.metadata.title,
        authors=list(structure.metadata.authors),
        language=structure.metadata.language,
        cover_path=None,
        source_path=None,
        chapters=chapters,
    )
