"""Plain text (.txt) and Markdown (.md/.markdown) book import (SPEC T02.4)."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

from skald_core.book.epub import SHORT_CHAPTER_CHARS, _collapse_ws
from skald_core.book.xhtml import _chapter_id, _finalize_segments, _paragraph_id
from skald_core.rpc.server import SkaldError
from skald_core.schemas.models import Book, Chapter, Paragraph

MAX_TEXT_BYTES = 100_000_000  # 100 MB (SPEC T02.4)
MAX_HEADING_LINE_CHARS = 80

_TXT_HEADING_RE = re.compile(r"^(?:chapter|part|book)\b", re.IGNORECASE)
_MD_PARSER = MarkdownIt("commonmark").enable("table")


@dataclass(frozen=True, slots=True)
class TextImport:
    """Imported book along with the detected text encoding and whether it was guessed."""

    book: Book
    encoding: str
    guessed: bool


@dataclass(slots=True)
class _ChapterDraft:
    title: str | None
    start_line: int
    paragraphs: list[tuple[str, bool]] = field(default_factory=list)


def _unsupported_format(
    message: str,
    *,
    details: str | None = None,
    hint: str | None = None,
) -> SkaldError:
    return SkaldError(
        kind="unsupported_format",
        message=message,
        details=details,
        hint=hint,
    )


def _decode_text_bytes(raw: bytes) -> tuple[str, str, bool]:
    if raw.startswith(codecs.BOM_UTF8):
        try:
            return raw[len(codecs.BOM_UTF8) :].decode("utf-8", errors="strict"), "utf-8", False
        except UnicodeDecodeError as exc:
            raise _unsupported_format(
                "Text file has a UTF-8 BOM but is not valid UTF-8.",
                details=str(exc),
                hint="Re-save the file as valid UTF-8.",
            ) from exc

    if raw.startswith(codecs.BOM_UTF16_LE):
        try:
            return (
                raw[len(codecs.BOM_UTF16_LE) :].decode("utf-16-le", errors="strict"),
                "utf-16-le",
                False,
            )
        except UnicodeDecodeError as exc:
            raise _unsupported_format(
                "Text file has a UTF-16 LE BOM but is not valid UTF-16 LE.",
                details=str(exc),
                hint="Re-save the file as UTF-8 or valid UTF-16.",
            ) from exc

    if raw.startswith(codecs.BOM_UTF16_BE):
        try:
            return (
                raw[len(codecs.BOM_UTF16_BE) :].decode("utf-16-be", errors="strict"),
                "utf-16-be",
                False,
            )
        except UnicodeDecodeError as exc:
            raise _unsupported_format(
                "Text file has a UTF-16 BE BOM but is not valid UTF-16 BE.",
                details=str(exc),
                hint="Re-save the file as UTF-8 or valid UTF-16.",
            ) from exc

    # Check NUL-byte cadence before strict UTF-8 because ASCII UTF-16 bytes also decode as UTF-8.
    if b"\x00" in raw and len(raw) >= 2 and len(raw) % 2 == 0:
        even_nuls = raw[0::2].count(0)
        odd_nuls = raw[1::2].count(0)
        threshold = max(1, len(raw) // 16)
        if odd_nuls >= threshold and odd_nuls > even_nuls * 2:
            try:
                return raw.decode("utf-16-le", errors="strict"), "utf-16-le", True
            except UnicodeDecodeError:
                pass
        elif even_nuls >= threshold and even_nuls > odd_nuls * 2:
            try:
                return raw.decode("utf-16-be", errors="strict"), "utf-16-be", True
            except UnicodeDecodeError:
                pass

    try:
        return raw.decode("utf-8", errors="strict"), "utf-8", False
    except UnicodeDecodeError:
        pass

    try:
        return raw.decode("cp1252", errors="strict"), "cp1252", True
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="strict"), "latin-1", True


def _read_and_decode(path: Path | str) -> tuple[Path, str, str, bool]:
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise _unsupported_format(
            f"Cannot open text file: {file_path.name}",
            details=str(exc),
            hint="Verify that the file exists and is readable.",
        ) from exc

    if size > MAX_TEXT_BYTES:
        raise _unsupported_format(
            f"File {file_path.name} exceeds the 100 MB size limit.",
            details=f"size_bytes={size}, max_bytes={MAX_TEXT_BYTES}",
            hint="The file is too large to import (maximum supported size is 100 MB).",
        )

    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise _unsupported_format(
            f"Cannot read text file: {file_path.name}",
            details=str(exc),
            hint="Verify that the file exists and is readable.",
        ) from exc

    if len(raw) > MAX_TEXT_BYTES:
        raise _unsupported_format(
            f"File {file_path.name} exceeds the 100 MB size limit.",
            details=f"size_bytes={len(raw)}, max_bytes={MAX_TEXT_BYTES}",
            hint="The file is too large to import (maximum supported size is 100 MB).",
        )

    text, encoding, guessed = _decode_text_bytes(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise _unsupported_format(
            f"File {file_path.name} contains no readable text.",
            hint="Provide a file with non-whitespace text.",
        )
    return file_path, text, encoding, guessed


def _build_chapters(drafts: list[_ChapterDraft]) -> list[Chapter]:
    chapters: list[Chapter] = []
    for ch_idx, draft in enumerate(drafts):
        ch_id = _chapter_id(ch_idx, f"L{draft.start_line}")
        paragraphs = [
            Paragraph(
                id=_paragraph_id(ch_id, p_idx, text),
                text=text,
                is_heading=is_heading,
            )
            for p_idx, (text, is_heading) in enumerate(draft.paragraphs)
        ]
        char_count = len(" ".join(p.text for p in paragraphs))
        skip_reasons = ["short"] if char_count < SHORT_CHAPTER_CHARS else []
        title = draft.title if draft.title else f"Chapter {ch_idx + 1}"
        chapters.append(
            Chapter(
                id=ch_id,
                title=title,
                included=not skip_reasons,
                linear=True,
                skip_reasons=skip_reasons,
                paragraphs=paragraphs,
            )
        )
    return chapters


def _parse_txt_drafts(text: str) -> list[_ChapterDraft]:
    lines = text.split("\n")
    blocks: list[tuple[int, int, list[str]]] = []
    blank_count = 0
    cur_lines: list[str] = []
    cur_start = 1

    for line_no, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            if cur_lines:
                blocks.append((cur_start, blank_count, cur_lines))
                cur_lines = []
                blank_count = 1
            else:
                blank_count += 1
        else:
            if not cur_lines:
                cur_start = line_no
            cur_lines.append(raw_line)

    if cur_lines:
        blocks.append((cur_start, blank_count, cur_lines))

    drafts: list[_ChapterDraft] = []
    current: _ChapterDraft | None = None

    for start_line, blanks_before, block_lines in blocks:
        first_stripped = block_lines[0].strip()
        is_rule_a = (
            len(first_stripped) <= MAX_HEADING_LINE_CHARS
            and _TXT_HEADING_RE.match(first_stripped) is not None
        )
        is_rule_b = (
            len(block_lines) == 1
            and blanks_before >= 2
            and len(first_stripped) <= MAX_HEADING_LINE_CHARS
        )
        if is_rule_a or is_rule_b:
            title = _collapse_ws(first_stripped)
            heading_text = _collapse_ws(" ".join(block_lines))
            current = _ChapterDraft(
                title=title or None,
                start_line=start_line,
                paragraphs=[(heading_text, True)] if heading_text else [],
            )
            drafts.append(current)
        else:
            para_text = _collapse_ws(" ".join(block_lines))
            if para_text:
                if current is None:
                    current = _ChapterDraft(title=None, start_line=start_line)
                    drafts.append(current)
                current.paragraphs.append((para_text, False))

    return drafts


def _extract_inline_text(token: Token) -> str:
    if not token.children:
        return _collapse_ws(token.content)
    segments: list[list[str]] = [[]]
    for child in token.children:
        ctype = child.type
        if ctype in {"text", "code_inline"}:
            segments[-1].append(child.content)
        elif ctype == "softbreak":
            segments[-1].append(" ")
        elif ctype == "hardbreak":
            segments.append([])
    return _finalize_segments(segments)


def _parse_markdown_drafts(text: str) -> list[_ChapterDraft]:
    tokens = _MD_PARSER.parse(text)
    drafts: list[_ChapterDraft] = []
    current: _ChapterDraft | None = None

    in_heading = False
    heading_start_line = 1
    heading_splits_chapter = False

    in_tr = False
    tr_start_line = 1
    tr_cells: list[str] = []
    in_cell = False

    def _ensure_chapter(start_line: int) -> _ChapterDraft:
        nonlocal current
        if current is None:
            current = _ChapterDraft(title=None, start_line=start_line)
            drafts.append(current)
        return current

    for tok in tokens:
        ttype = tok.type
        if ttype == "heading_open":
            level = int(tok.tag[1:])
            in_heading = True
            heading_start_line = tok.map[0] + 1 if tok.map else 1
            heading_splits_chapter = level in (1, 2) and tok.level == 0
            if heading_splits_chapter:
                current = _ChapterDraft(title=None, start_line=heading_start_line)
                drafts.append(current)
        elif ttype == "heading_close":
            in_heading = False
            heading_splits_chapter = False
        elif ttype == "tr_open":
            in_tr = True
            tr_start_line = tok.map[0] + 1 if tok.map else 1
            tr_cells = []
        elif ttype == "tr_close":
            if in_tr and tr_cells:
                row_text = " ".join(tr_cells)
                _ensure_chapter(tr_start_line).paragraphs.append((row_text, False))
            in_tr = False
            tr_cells = []
        elif ttype in {"th_open", "td_open"}:
            in_cell = True
        elif ttype in {"th_close", "td_close"}:
            in_cell = False
        elif ttype == "inline":
            para_text = _extract_inline_text(tok)
            if not para_text:
                continue
            if in_cell:
                tr_cells.append(para_text)
            elif in_heading:
                if heading_splits_chapter:
                    assert current is not None
                    current.title = _collapse_ws(para_text)
                    current.paragraphs.append((para_text, True))
                else:
                    _ensure_chapter(heading_start_line).paragraphs.append((para_text, True))
            else:
                start_line = tok.map[0] + 1 if tok.map else 1
                _ensure_chapter(start_line).paragraphs.append((para_text, False))

    return drafts


def load_text_book(path: Path | str) -> TextImport:
    """Import a plain text (.txt) file into a ``Book`` wrapped in ``TextImport``."""
    file_path, text, encoding, guessed = _read_and_decode(path)
    chapters = _build_chapters(_parse_txt_drafts(text))
    book = Book(
        title=file_path.stem,
        authors=[],
        language=None,
        cover_path=None,
        source_path=None,
        chapters=chapters,
    )
    return TextImport(book=book, encoding=encoding, guessed=guessed)


def load_markdown_book(path: Path | str) -> TextImport:
    """Import a Markdown (.md/.markdown) file into a ``Book`` wrapped in ``TextImport``."""
    file_path, text, encoding, guessed = _read_and_decode(path)
    chapters = _build_chapters(_parse_markdown_drafts(text))
    book = Book(
        title=file_path.stem,
        authors=[],
        language=None,
        cover_path=None,
        source_path=None,
        chapters=chapters,
    )
    return TextImport(book=book, encoding=encoding, guessed=guessed)
