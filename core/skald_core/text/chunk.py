"""Sentence splitting, chunking, and dialogue detection (C1.2 steps 4–6)."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
import warnings
from functools import lru_cache
from typing import Any, Literal, NamedTuple

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"^pysbd(\.|$)")
    import pysbd  # type: ignore[import-untyped]
    from pysbd.languages import LANGUAGE_CODES  # type: ignore[import-untyped]

from skald_core.schemas.models import Chunk, Sentence

logger = logging.getLogger(__name__)

Role = Literal["narration", "dialogue"]


class ParagraphChunks(NamedTuple):
    """Result of splitting and chunking a single paragraph of synthesis text."""

    sentences: list[Sentence]
    chunks: list[Chunk]
    unbalanced_quotes: bool


# Languages where “ (U+201C) closes „ (U+201E) instead of opening “…”.
_LOW_OPEN_LANGUAGES: frozenset[str] = frozenset({"de", "cs", "sk", "pl", "bg", "ro", "hu"})
_SUPPORTED_PYSBD_LANGUAGES: frozenset[str] = frozenset(LANGUAGE_CODES.keys())

_WS_RUN_RE = re.compile(r"\s+")

_SPLIT_DELIMITERS: tuple[tuple[str, ...], ...] = (
    (";", "；"),
    (":", "："),
    (",", "，", "、"),
)

_CLOSING_PUNCT_CHARS: frozenset[str] = frozenset("\"'”“’»›」』】》〉〕）)]}")

_FALLBACK_SPLIT_STD_RE = re.compile(
    r"(?:[.!?…。！？؟।]*[。！？][.!?…。！？؟।]*[\"'”’»›」』】》〉〕）)\]}]*"
    r"|[.!?…؟।]+[\"'”’»›」』】》〉〕）)\]}]*(?=\s|$))"
)
_FALLBACK_SPLIT_LOW_RE = re.compile(
    r"(?:[.!?…。！？؟।]*[。！？][.!?…。！？؟।]*[\"'”“’»›」』】》〉〕）)\]}]*"
    r"|[.!?…؟।]+[\"'”“’»›」』】》〉〕）)\]}]*(?=\s|$))"
)


def normalize_language(language: str | None) -> str:
    """Return the lowercased primary subtag of a BCP-47 language tag (default 'en')."""
    if not language:
        return "en"
    primary = re.split(r"[-_]", language.strip(), maxsplit=1)[0].lower()
    return primary or "en"


@lru_cache(maxsize=32)
def _get_segmenter(lang: str) -> Any:
    return pysbd.Segmenter(language=lang, clean=False)


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
        or 0x31F0 <= code <= 0x31FF
        or 0xFF65 <= code <= 0xFF9F
        or 0xAC00 <= code <= 0xD7AF
        or 0x1100 <= code <= 0x11FF
        or 0x3130 <= code <= 0x318F
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2EBEF
    )


def _is_valid_dialogue_content(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    if len(stripped.split()) >= 2:
        return True
    if any(_is_cjk_char(ch) for ch in stripped):
        meaningful = sum(
            1 for ch in stripped if not unicodedata.category(ch).startswith(("P", "Z", "C"))
        )
        return meaningful >= 2
    return False


def _detect_dialogue_spans(text: str, lang: str) -> tuple[list[tuple[Role, str]], bool]:
    # Known limit: British single-quote ‘…’ dialogue is not detected because it
    # conflicts with apostrophes and is outside C1.2's quote list.
    low_open = lang in _LOW_OPEN_LANGUAGES
    if low_open:
        openers = {"„": "“", '"': '"', "«": "»", "「": "」"}
        closers = {"“", "”", '"', "»", "」"}
    else:
        openers = {"“": "”", '"': '"', "«": "»", "「": "」"}
        closers = {"”", '"', "»", "」"}

    stack: list[tuple[str, str, int]] = []
    # Each entry: (role, start, end, content_start, content_end)
    raw_spans: list[tuple[Role, int, int, int, int]] = []
    narration_start = 0
    had_inner_quotes = False

    for idx, ch in enumerate(text):
        if stack and ch == stack[-1][1]:
            _, _, open_idx = stack.pop()
            if not stack:
                had_inner_quotes = False
                if open_idx > narration_start:
                    raw_spans.append(("narration", narration_start, open_idx, 0, 0))
                raw_spans.append(("dialogue", open_idx, idx + 1, open_idx + 1, idx))
                narration_start = idx + 1
        elif ch in openers:
            if stack:
                had_inner_quotes = True
            stack.append((ch, openers[ch], idx))
        elif ch in closers:
            return [("narration", text)], True

    # Continued speech: one unclosed opener at EOF with every earlier quote balanced.
    if len(stack) > 1 or (len(stack) == 1 and had_inner_quotes):
        return [("narration", text)], True

    if len(stack) == 1:
        _, _, open_idx = stack[0]
        if open_idx > narration_start:
            raw_spans.append(("narration", narration_start, open_idx, 0, 0))
        raw_spans.append(("dialogue", open_idx, len(text), open_idx + 1, len(text)))
    elif narration_start < len(text):
        raw_spans.append(("narration", narration_start, len(text), 0, 0))

    resolved: list[tuple[Role, str]] = []
    for role, start, end, c_start, c_end in raw_spans:
        span_role: Role = role
        if span_role == "dialogue" and not _is_valid_dialogue_content(text[c_start:c_end]):
            span_role = "narration"
        resolved.append((span_role, text[start:end]))

    # Merge contiguous same-role spans and absorb whitespace-only gaps between dialogue spans.
    merged: list[tuple[Role, str]] = []
    idx = 0
    while idx < len(resolved):
        role, chunk = resolved[idx]
        if (
            role == "narration"
            and not chunk.strip()
            and merged
            and merged[-1][0] == "dialogue"
            and idx + 1 < len(resolved)
            and resolved[idx + 1][0] == "dialogue"
        ):
            prev_role, prev_text = merged[-1]
            merged[-1] = (prev_role, prev_text + chunk + resolved[idx + 1][1])
            idx += 2
            continue
        if merged and merged[-1][0] == role:
            merged[-1] = (role, merged[-1][1] + chunk)
        else:
            merged.append((role, chunk))
        idx += 1

    # Drop spans that contain only whitespace.
    cleaned = [(role, s.strip()) for role, s in merged if s.strip()]
    return cleaned, False


def _fallback_split(line: str, lang: str) -> list[str]:
    pattern = _FALLBACK_SPLIT_LOW_RE if lang in _LOW_OPEN_LANGUAGES else _FALLBACK_SPLIT_STD_RE
    sentences: list[str] = []
    pos = 0
    for match in pattern.finditer(line):
        end = match.end()
        seg = line[pos:end].strip()
        if seg:
            sentences.append(seg)
        pos = end
    tail = line[pos:].strip()
    if tail:
        sentences.append(tail)
    return sentences


_CJK_END_RE = re.compile(r"[。！？][\"'”“’»›」』】》〉〕）)\]}]*$")


def _is_closing_punct_only(seg: str) -> bool:
    return bool(seg) and all(ch in _CLOSING_PUNCT_CHARS for ch in seg)


def _pysbd_segments_valid(raw_segs: list[str], cleaned: list[str], line: str) -> bool:
    if not cleaned:
        return False
    if _WS_RUN_RE.sub(" ", "".join(raw_segs)).strip() != line:
        return False
    if not _is_closing_punct_only(line) and any(_is_closing_punct_only(seg) for seg in cleaned):
        return False
    non_empty_raw = [seg for seg in raw_segs if seg.strip()]
    for left, right in zip(non_empty_raw, non_empty_raw[1:]):
        if not left[-1].isspace() and not right[0].isspace():
            if _CJK_END_RE.search(left.strip()) is None:
                return False
    return True


def _attach_source_seps(line: str, segs: list[str]) -> list[tuple[str, bool]] | None:
    if not segs:
        return None
    out: list[tuple[str, bool]] = []
    pos = 0
    for idx, seg in enumerate(segs):
        if idx > 0:
            has_space = pos < len(line) and line[pos] == " "
            if has_space:
                pos += 1
            out[-1] = (out[-1][0], has_space)
        if not line.startswith(seg, pos):
            return None
        pos += len(seg)
        out.append((seg, False))
    if pos != len(line):
        return None
    return out


def _split_span_sentences(span_text: str, lang: str) -> list[tuple[str, bool]]:
    sentences: list[tuple[str, bool]] = []
    use_pysbd = lang in _SUPPORTED_PYSBD_LANGUAGES
    segmenter = _get_segmenter(lang) if use_pysbd else None

    for raw_line in span_text.split("\n"):
        line = _WS_RUN_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        if sentences:
            prev_text, _ = sentences[-1]
            sentences[-1] = (prev_text, True)

        if segmenter is None:
            fb_with_seps = _attach_source_seps(line, _fallback_split(line, lang))
            if fb_with_seps is not None:
                sentences.extend(fb_with_seps)
            continue

        raw_segs: list[str] = segmenter.segment(line)
        cleaned = [_WS_RUN_RE.sub(" ", seg).strip() for seg in raw_segs]
        cleaned = [seg for seg in cleaned if seg]

        with_seps = (
            _attach_source_seps(line, cleaned)
            if _pysbd_segments_valid(raw_segs, cleaned, line)
            else None
        )
        if with_seps is not None:
            sentences.extend(with_seps)
        else:
            logger.warning(
                "pysbd segments did not reproduce span for language %r; "
                "using punctuation fallback.",
                lang,
            )
            fb_with_seps = _attach_source_seps(line, _fallback_split(line, lang))
            if fb_with_seps is not None:
                sentences.extend(fb_with_seps)

    return sentences


def _is_forbidden_cut(text: str, cut: int) -> bool:
    if cut <= 0 or cut >= len(text):
        return False
    after = text[cut]
    code = ord(after)
    if (
        unicodedata.category(after).startswith("M")
        or after in ("\u200c", "\u200d")
        or 0xFE00 <= code <= 0xFE0F
        or 0x1F3FB <= code <= 0x1F3FF
    ):
        return True
    return text[cut - 1] == "\u200d"


def _split_long_sentence(text: str, max_chars: int) -> list[tuple[str, bool]]:
    text = _WS_RUN_RE.sub(" ", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [(text, False)]

    for delims in _SPLIT_DELIMITERS:
        best_end = -1
        for idx, ch in enumerate(text):
            if ch in delims:
                candidate_end = idx + 1
                while candidate_end < len(text) and text[candidate_end] in _CLOSING_PUNCT_CHARS:
                    candidate_end += 1
                if candidate_end <= max_chars:
                    best_end = candidate_end
                else:
                    break
        if best_end > 0:
            left = text[:best_end]
            has_space = best_end < len(text) and text[best_end] == " "
            rest = text[best_end + (1 if has_space else 0) :]
            out: list[tuple[str, bool]] = [(left, has_space)]
            if rest:
                out.extend(_split_long_sentence(rest, max_chars))
            return out

    space_idx = text.rfind(" ", 0, max_chars + 1)
    if space_idx > 0:
        left = text[:space_idx]
        rest = text[space_idx + 1 :]
        out = [(left, True)]
        if rest:
            out.extend(_split_long_sentence(rest, max_chars))
        return out

    cut = max_chars
    while cut > 0 and _is_forbidden_cut(text, cut):
        cut -= 1
    if cut == 0:
        # No allowed cut in (0, max_chars]; max_chars limit always wins.
        cut = max_chars
    has_space = cut < len(text) and text[cut] == " "
    left = text[:cut]
    rest = text[cut + (1 if has_space else 0) :]
    out = [(left, has_space)]
    if rest:
        out.extend(_split_long_sentence(rest, max_chars))
    return out


def _pack_span_chunks(
    sentences_with_seps: list[tuple[str, bool]],
    max_chars: int,
) -> list[str]:
    pieces: list[tuple[str, bool]] = []
    for sent, sent_has_space in sentences_with_seps:
        if len(sent) <= max_chars:
            pieces.append((sent, sent_has_space))
        else:
            split_pieces = _split_long_sentence(sent, max_chars)
            if split_pieces:
                last_text, _ = split_pieces[-1]
                split_pieces[-1] = (last_text, sent_has_space)
                pieces.extend(split_pieces)

    chunks: list[str] = []
    current = ""
    pending_space = False
    for piece, has_space in pieces:
        if not current:
            current = piece
            pending_space = has_space
        else:
            sep = " " if pending_space else ""
            if len(current) + len(sep) + len(piece) <= max_chars:
                current = f"{current}{sep}{piece}"
                pending_space = has_space
            else:
                chunks.append(current)
                current = piece
                pending_space = has_space
    if current:
        chunks.append(current)
    return chunks


def _stable_id(prefix: str, paragraph_id: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{paragraph_id}\0{index}\0{text}".encode()).hexdigest()
    return f"{prefix}{digest[:16]}"


def chunk_paragraph(
    chapter_id: str,
    paragraph_id: str,
    text: str,
    language: str | None,
    max_chars: int,
) -> ParagraphChunks:
    """Detect dialogue spans, split sentences, and pack chunks up to ``max_chars``."""
    if max_chars < 1:
        raise ValueError(f"max_chars must be >= 1, got {max_chars}")

    if not text.strip():
        return ParagraphChunks(sentences=[], chunks=[], unbalanced_quotes=False)

    lang = normalize_language(language)
    spans, unbalanced_quotes = _detect_dialogue_spans(text, lang)

    sentences: list[Sentence] = []
    chunks: list[Chunk] = []

    for role, span_text in spans:
        span_sentences_with_seps = _split_span_sentences(span_text, lang)
        for sent_text, _ in span_sentences_with_seps:
            s_idx = len(sentences)
            sentences.append(
                Sentence(
                    id=_stable_id("s_", paragraph_id, s_idx, sent_text),
                    text=sent_text,
                )
            )
        for chunk_text in _pack_span_chunks(span_sentences_with_seps, max_chars):
            c_idx = len(chunks)
            chunks.append(
                Chunk(
                    id=_stable_id("c_", paragraph_id, c_idx, chunk_text),
                    chapter_id=chapter_id,
                    paragraph_id=paragraph_id,
                    index=c_idx,
                    text=chunk_text,
                    role=role,
                    voice_id=None,
                    cache_key=None,
                )
            )

    return ParagraphChunks(
        sentences=sentences,
        chunks=chunks,
        unbalanced_quotes=unbalanced_quotes,
    )
