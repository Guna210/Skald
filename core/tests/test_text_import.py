"""Tests for TXT and Markdown import (SPEC T02.4)."""

from __future__ import annotations

import codecs
import hashlib
import re
from pathlib import Path

import pytest

from skald_core.book import TextImport, load_markdown_book, load_text_book
from skald_core.book import text_import as text_import_mod
from skald_core.rpc.server import SkaldError
from skald_core.schemas.models import Book

_CH_ID_RE = re.compile(r"^ch_[0-9a-f]{8}$")
_P_ID_RE = re.compile(r"^p_[0-9a-f]{16}$")


def _assert_book_invariants(book: Book) -> None:
    ch_ids: list[str] = []
    p_ids: list[str] = []
    for ch_idx, ch in enumerate(book.chapters):
        assert _CH_ID_RE.match(ch.id)
        assert ch.linear is True
        assert ch.included is (not ch.skip_reasons)
        ch_ids.append(ch.id)

        char_count = len(" ".join(p.text for p in ch.paragraphs))
        expected_reasons = ["short"] if char_count < 200 else []
        assert ch.skip_reasons == expected_reasons, f"chapter {ch_idx} ({ch.title!r})"

        for p_idx, p in enumerate(ch.paragraphs):
            assert p.text
            assert p.text.strip() == p.text
            assert all(line.strip() == line and line for line in p.text.split("\n"))
            expected_p_id = (
                "p_" + hashlib.sha256(f"{ch.id}\0{p_idx}\0{p.text}".encode()).hexdigest()[:16]
            )
            assert _P_ID_RE.match(p.id)
            assert p.id == expected_p_id
            assert p.unbalanced_quotes is False
            assert p.sentences == []
            p_ids.append(p.id)

    assert len(ch_ids) == len(set(ch_ids))
    assert len(p_ids) == len(set(p_ids))


@pytest.mark.parametrize(
    ("raw_bytes", "expected_encoding", "expected_guessed", "expected_snippet"),
    [
        (
            "Chapter 1\n\nCafé naïve résumé — test.".encode(),
            "utf-8",
            False,
            "Café naïve résumé — test.",
        ),
        (
            codecs.BOM_UTF8 + "Chapter 1\n\nBOM UTF-8 café.".encode(),
            "utf-8",
            False,
            "BOM UTF-8 café.",
        ),
        (
            codecs.BOM_UTF16_LE + "Chapter 1\n\nUTF-16 LE BOM café.".encode("utf-16-le"),
            "utf-16-le",
            False,
            "UTF-16 LE BOM café.",
        ),
        (
            codecs.BOM_UTF16_BE + "Chapter 1\n\nUTF-16 BE BOM café.".encode("utf-16-be"),
            "utf-16-be",
            False,
            "UTF-16 BE BOM café.",
        ),
        (
            codecs.BOM_UTF32_LE + "Chapter 1\n\nUTF-32 LE BOM café.".encode("utf-32-le"),
            "utf-32-le",
            False,
            "UTF-32 LE BOM café.",
        ),
        (
            codecs.BOM_UTF32_BE + "Chapter 1\n\nUTF-32 BE BOM café.".encode("utf-32-be"),
            "utf-32-be",
            False,
            "UTF-32 BE BOM café.",
        ),
        (
            "Chapter 1\n\nASCII UTF-16 LE without BOM.".encode("utf-16-le"),
            "utf-16-le",
            True,
            "ASCII UTF-16 LE without BOM.",
        ),
        (
            "Chapter 1\n\nMixed UTF-16 LE café.".encode("utf-16-le"),
            "utf-16-le",
            True,
            "Mixed UTF-16 LE café.",
        ),
        (
            "Chapter 1\n\nASCII UTF-16 BE without BOM.".encode("utf-16-be"),
            "utf-16-be",
            True,
            "ASCII UTF-16 BE without BOM.",
        ),
        (
            "Chapter 1\n\n“Smart quotes” — cp1252 café.".encode("cp1252"),
            "cp1252",
            True,
            "“Smart quotes” — cp1252 café.",
        ),
        (
            b"Chapter 1\n\nLatin-1 fallback \x81\x8d\x90\x9d caf\xe9.",
            "latin-1",
            True,
            "Latin-1 fallback \x81\x8d\x90\x9d café.",
        ),
    ],
)
def test_encoding_detection_for_txt_and_markdown(
    tmp_path: Path,
    raw_bytes: bytes,
    expected_encoding: str,
    expected_guessed: bool,
    expected_snippet: str,
) -> None:
    txt_path = tmp_path / "sample.txt"
    txt_path.write_bytes(raw_bytes)
    txt_res = load_text_book(txt_path)
    assert isinstance(txt_res, TextImport)
    assert txt_res.encoding == expected_encoding
    assert txt_res.guessed is expected_guessed
    assert txt_res.book.chapters[0].paragraphs[1].text == expected_snippet
    assert "\ufeff" not in txt_res.book.chapters[0].paragraphs[0].text
    _assert_book_invariants(txt_res.book)

    md_bytes = raw_bytes.replace(b"Chapter 1", b"# Chapter 1")
    if expected_encoding in {"utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"}:
        md_text = "# Chapter 1\n\n" + expected_snippet
        bom_map = {
            "utf-16-le": codecs.BOM_UTF16_LE,
            "utf-16-be": codecs.BOM_UTF16_BE,
            "utf-32-le": codecs.BOM_UTF32_LE,
            "utf-32-be": codecs.BOM_UTF32_BE,
        }
        has_bom = any(raw_bytes.startswith(b) for b in bom_map.values())
        md_bytes = (bom_map[expected_encoding] if has_bom else b"") + md_text.encode(
            expected_encoding
        )
    md_path = tmp_path / "sample.md"
    md_path.write_bytes(md_bytes)
    md_res = load_markdown_book(md_path)
    assert md_res.encoding == expected_encoding
    assert md_res.guessed is expected_guessed
    assert md_res.book.chapters[0].paragraphs[1].text == expected_snippet
    _assert_book_invariants(md_res.book)


@pytest.mark.parametrize(
    ("total_bytes", "nul_count"),
    [(64, 4), (160, 10), (1600, 100)],
)
def test_stray_nuls_strip_and_decode_as_guessed_utf8(
    tmp_path: Path,
    total_bytes: int,
    nul_count: int,
) -> None:
    prefix = b"Chapter 1.\n\n"
    body_len = total_bytes - len(prefix) - nul_count
    raw = prefix + b"a\x00" * nul_count + b"a" * (body_len - nul_count)
    assert len(raw) == total_bytes
    assert raw.count(0) == nul_count

    path = tmp_path / "stray_nuls.txt"
    path.write_bytes(raw)
    res = load_text_book(path)
    assert res.encoding == "utf-8"
    assert res.guessed is True
    assert res.book.chapters[0].paragraphs[1].text == "a" * body_len
    _assert_book_invariants(res.book)


@pytest.mark.parametrize(
    ("label", "text", "require_high_bytes"),
    [
        ("cjk_40", "你好世界。" * 40, False),
        ("cyrillic", "Глава первая.\n\nПривет мир!", False),
        ("cjk_high_bytes", "中文測試。\n\n測試內容。", True),
    ],
)
def test_bomless_utf16_le_cjk_and_cyrillic(
    tmp_path: Path,
    label: str,
    text: str,
    require_high_bytes: bool,
) -> None:
    raw = text.encode("utf-16-le")
    if require_high_bytes:
        assert any(b >= 0x80 for b in raw)

    path = tmp_path / f"{label}.txt"
    path.write_bytes(raw)
    res = load_text_book(path)
    assert res.encoding == "utf-16-le"
    assert res.guessed is True
    joined = "\n\n".join(p.text for ch in res.book.chapters for p in ch.paragraphs)
    assert joined == text
    _assert_book_invariants(res.book)


def test_crlf_and_cr_line_endings_normalized(tmp_path: Path) -> None:
    txt_path = tmp_path / "crlf.txt"
    txt_path.write_bytes(b"Chapter 1\r\n\r\nFirst wrapped\r\nline here.\r\rSecond paragraph.\r\n")
    txt_res = load_text_book(txt_path)
    assert [p.text for p in txt_res.book.chapters[0].paragraphs] == [
        "Chapter 1",
        "First wrapped line here.",
        "Second paragraph.",
    ]

    md_path = tmp_path / "crlf.markdown"
    md_path.write_bytes(b"# Heading\r\n\r\nLine one\r\nline two.\r\rSecond para.\r\n")
    md_res = load_markdown_book(md_path)
    assert md_res.book.title == "crlf"
    assert [p.text for p in md_res.book.chapters[0].paragraphs] == [
        "Heading",
        "Line one line two.",
        "Second para.",
    ]


@pytest.mark.parametrize(
    ("name", "raw", "expected_chapters"),
    [
        (
            "no_headings",
            "First   line\nwrapped here.\n\nSecond paragraph.",
            [
                (
                    "Chapter 1",
                    1,
                    [("First line wrapped here.", False), ("Second paragraph.", False)],
                ),
            ],
        ),
        (
            "pre_heading_and_rule_a_cases",
            (
                "Foreword text.\n\n"
                "CHAPTER I\nThe Boy Who Lived\n\n"
                "Mr. and Mrs. Dursley were proud.\n\n"
                "part two\n\n"
                "Second part body.\n\n"
                "Book III: Return\n\n"
                "Final part."
            ),
            [
                ("Chapter 1", 1, [("Foreword text.", False)]),
                (
                    "CHAPTER I",
                    3,
                    [
                        ("CHAPTER I The Boy Who Lived", True),
                        ("Mr. and Mrs. Dursley were proud.", False),
                    ],
                ),
                ("part two", 8, [("part two", True), ("Second part body.", False)]),
                ("Book III: Return", 12, [("Book III: Return", True), ("Final part.", False)]),
            ],
        ),
        (
            "rule_b_two_blank_lines_vs_one_blank_line",
            (
                "Opening line.\n\n"
                "Not A Heading\n\n"
                "Body after single blank.\n\n\n"
                "Prologue\n\n"
                "Body after two blanks.\n\n\n"
                "Multi-line block\nafter two blanks.\n\n"
                "Tail."
            ),
            [
                (
                    "Chapter 1",
                    1,
                    [
                        ("Opening line.", False),
                        ("Not A Heading", False),
                        ("Body after single blank.", False),
                    ],
                ),
                (
                    "Prologue",
                    8,
                    [
                        ("Prologue", True),
                        ("Body after two blanks.", False),
                        ("Multi-line block after two blanks.", False),
                        ("Tail.", False),
                    ],
                ),
            ],
        ),
        (
            "prose_chapter_inside_block_and_word_boundaries",
            (
                "He read through the night.\n"
                "Chapter after chapter passed without rest.\n\n"
                "Chapters in History\n\n"
                "Bookish people read slowly.\n\n"
                "Partitioning matters."
            ),
            [
                (
                    "Chapter 1",
                    1,
                    [
                        (
                            "He read through the night. Chapter after chapter passed without rest.",
                            False,
                        ),
                        ("Chapters in History", False),
                        ("Bookish people read slowly.", False),
                        ("Partitioning matters.", False),
                    ],
                ),
            ],
        ),
        (
            "headings_over_80_chars_do_not_split",
            (
                "Intro.\n\n"
                + ("Chapter 1: " + "x" * 70)
                + "\n\n"
                + ("Chapter 1: " + "y" * 69)
                + "\n\n\n"
                + ("Short " * 14)
                + "\n\n\n"
                + ("z" * 80)
            ),
            [
                (
                    "Chapter 1",
                    1,
                    [
                        ("Intro.", False),
                        ("Chapter 1: " + "x" * 70, False),  # 81 chars: no split
                    ],
                ),
                (
                    "Chapter 1: " + "y" * 69,  # 80 chars: splits
                    5,
                    [
                        ("Chapter 1: " + "y" * 69, True),
                        (("Short " * 14).strip(), False),  # 83 chars after 2 blanks: no split
                    ],
                ),
                (
                    "z" * 80,  # 80 chars after 2 blanks: splits
                    11,
                    [("z" * 80, True)],
                ),
            ],
        ),
        (
            "rule_a_word_and_line_limits",
            (
                "Part of the reason we are here today is to see\n"
                "what happens next in the story.\n\n"
                "Book lovers will know why this old edition matters\n"
                "so much to collectors.\n\n"
                "Chapter 1\n"
                "line two\n"
                "line three\n"
                "line four is too many lines.\n\n"
                "CHAPTER I.\n\n"
                "Opening paragraph.\n\n"
                "BOOK THE FIRST\n\n"
                "First book body.\n\n"
                "BOOK ONE\nRECALLED TO LIFE\n\n"
                "Tale of Two Cities."
            ),
            [
                (
                    "Chapter 1",
                    1,
                    [
                        (
                            "Part of the reason we are here today is to see "
                            "what happens next in the story.",
                            False,
                        ),
                        (
                            "Book lovers will know why this old edition matters "
                            "so much to collectors.",
                            False,
                        ),
                        (
                            "Chapter 1 line two line three line four is too many lines.",
                            False,
                        ),
                    ],
                ),
                ("CHAPTER I.", 12, [("CHAPTER I.", True), ("Opening paragraph.", False)]),
                ("BOOK THE FIRST", 16, [("BOOK THE FIRST", True), ("First book body.", False)]),
                (
                    "BOOK ONE",
                    20,
                    [("BOOK ONE RECALLED TO LIFE", True), ("Tale of Two Cities.", False)],
                ),
            ],
        ),
    ],
)
def test_txt_chapter_splitting_and_paragraphs(
    tmp_path: Path,
    name: str,
    raw: str,
    expected_chapters: list[tuple[str, int, list[tuple[str, bool]]]],
) -> None:
    path = tmp_path / f"{name}.txt"
    path.write_text(raw, encoding="utf-8")
    res = load_text_book(path)

    book = res.book
    assert book.title == name
    assert book.authors == []
    assert book.language is None
    assert book.cover_path is None
    assert book.source_path is None
    assert len(book.chapters) == len(expected_chapters)

    for idx, (ch, (exp_title, exp_line, exp_paras)) in enumerate(
        zip(book.chapters, expected_chapters, strict=True)
    ):
        expected_ch_id = "ch_" + hashlib.sha256(f"{idx}\0L{exp_line}".encode()).hexdigest()[:8]
        assert ch.id == expected_ch_id
        assert ch.title == exp_title
        assert [(p.text, p.is_heading) for p in ch.paragraphs] == exp_paras

    _assert_book_invariants(book)


def test_markdown_headings_blocks_inlines_and_skips(tmp_path: Path) -> None:
    md_content = """<!-- leading comment should not create an empty chapter -->

![cover](cover.png)

# ATX Chapter One

Intro with *emphasis*, **bold**, `inline_code`, and [a link](https://example.com).
Softbreak wraps here.

Line with hardbreak\x20\x20
continues below.

### Subheading Three

#### Subheading Four

##### Subheading Five

###### Subheading Six

![skipped image](pic.png "alt never read")

Inline <span class="keep">text between HTML tags</span> and<!-- gone --> end.

<div>html block should be skipped</div>

```python
def should_not_be_read():
    return 42
```

    indented_code_block()

- Bullet one
- Bullet two line 1
  Bullet two line 2
  1. Ordered nested
- Loose item A

  Loose item B

> Blockquote paragraph one.
>
> > Nested blockquote paragraph.

| Col A | ![img](x.png) | Col `B` |
| --- | --- | --- |
|   | ![](y.png) |   |
| [Link](https://x) | *Em* | <b>Val</b> |

Setext H1 Chapter
=================

Body under setext H1.

Setext H2 Chapter
-----------------

Body under setext H2.
"""
    md_path = tmp_path / "my.story.md"
    md_path.write_text(md_content, encoding="utf-8")
    res = load_markdown_book(md_path)
    book = res.book

    assert book.title == "my.story"
    assert book.authors == []
    assert book.language is None
    assert book.cover_path is None
    assert book.source_path is None

    assert [ch.title for ch in book.chapters] == [
        "ATX Chapter One",
        "Setext H1 Chapter",
        "Setext H2 Chapter",
    ]

    ch1_expected = [
        ("ATX Chapter One", True),
        ("Intro with emphasis, bold, inline_code, and a link. Softbreak wraps here.", False),
        ("Line with hardbreak\ncontinues below.", False),
        ("Subheading Three", True),
        ("Subheading Four", True),
        ("Subheading Five", True),
        ("Subheading Six", True),
        ("Inline text between HTML tags and end.", False),
        ("Bullet one", False),
        ("Bullet two line 1 Bullet two line 2", False),
        ("Ordered nested", False),
        ("Loose item A", False),
        ("Loose item B", False),
        ("Blockquote paragraph one.", False),
        ("Nested blockquote paragraph.", False),
        ("Col A Col B", False),
        ("Link Em Val", False),
    ]
    assert [(p.text, p.is_heading) for p in book.chapters[0].paragraphs] == ch1_expected
    assert [(p.text, p.is_heading) for p in book.chapters[1].paragraphs] == [
        ("Setext H1 Chapter", True),
        ("Body under setext H1.", False),
    ]
    assert [(p.text, p.is_heading) for p in book.chapters[2].paragraphs] == [
        ("Setext H2 Chapter", True),
        ("Body under setext H2.", False),
    ]
    _assert_book_invariants(book)


def test_markdown_pre_heading_chapter_and_no_headings(tmp_path: Path) -> None:
    pre_md = tmp_path / "pre.md"
    pre_md.write_text("Pre-heading paragraph.\n\n## Second\n\nBody.", encoding="utf-8")
    res1 = load_markdown_book(pre_md)
    assert [ch.title for ch in res1.book.chapters] == ["Chapter 1", "Second"]
    assert [(p.text, p.is_heading) for p in res1.book.chapters[0].paragraphs] == [
        ("Pre-heading paragraph.", False)
    ]
    assert [(p.text, p.is_heading) for p in res1.book.chapters[1].paragraphs] == [
        ("Second", True),
        ("Body.", False),
    ]
    _assert_book_invariants(res1.book)

    no_h_md = tmp_path / "flat.md"
    no_h_md.write_text("### Only H3\n\nJust text.", encoding="utf-8")
    res2 = load_markdown_book(no_h_md)
    assert [ch.title for ch in res2.book.chapters] == ["Chapter 1"]
    assert [(p.text, p.is_heading) for p in res2.book.chapters[0].paragraphs] == [
        ("Only H3", True),
        ("Just text.", False),
    ]
    _assert_book_invariants(res2.book)


def test_markdown_inline_br_and_heading_inside_blockquote(tmp_path: Path) -> None:
    md_path = tmp_path / "md_edge.md"
    md_path.write_text(
        "# Main Chapter\n\n"
        "world<br>next<br/>again<br />once<BR />more and <span>kept</span>.\n\n"
        "> ## Quoted Heading\n>\n> Body inside quote.\n",
        encoding="utf-8",
    )
    res = load_markdown_book(md_path)
    assert [ch.title for ch in res.book.chapters] == ["Main Chapter"]
    assert [(p.text, p.is_heading) for p in res.book.chapters[0].paragraphs] == [
        ("Main Chapter", True),
        ("world\nnext\nagain\nonce\nmore and kept.", False),
        ("Quoted Heading", True),
        ("Body inside quote.", False),
    ]
    _assert_book_invariants(res.book)


def test_short_chapter_threshold_boundary(tmp_path: Path) -> None:
    txt_path = tmp_path / "threshold.txt"
    txt_path.write_text(
        f"Chapter 1\n\n{'x' * 189}\n\nChapter 2\n\n{'y' * 190}",
        encoding="utf-8",
    )
    res = load_text_book(txt_path)
    ch1, ch2 = res.book.chapters
    assert len(" ".join(p.text for p in ch1.paragraphs)) == 199
    assert ch1.skip_reasons == ["short"]
    assert ch1.included is False

    assert len(" ".join(p.text for p in ch2.paragraphs)) == 200
    assert ch2.skip_reasons == []
    assert ch2.included is True
    _assert_book_invariants(res.book)


def test_limits_size_empty_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Empty / whitespace / BOM-only / zero-chapter files -> unsupported_format
    for name, data in [
        ("empty.txt", b""),
        ("ws.txt", b"   \r\n\t  \n"),
        ("bom.txt", codecs.BOM_UTF8),
        ("bad_utf8_bom.txt", codecs.BOM_UTF8 + b"\xff\xfe"),
    ]:
        p = tmp_path / name
        p.write_bytes(data)
        with pytest.raises(SkaldError) as exc_info:
            load_text_book(p)
        assert exc_info.value.kind == "unsupported_format"

    for md_name, md_raw in [
        ("empty.md", b"  \n\t\r\n"),
        ("image_only.md", b"![alt](pic.png)\n"),
        ("code_only.md", b"```python\nprint(1)\n```\n"),
        ("html_only.md", b"<div>only html</div>\n"),
        ("heading_image_only.md", b"# ![only](pic.png)\n"),
    ]:
        md_p = tmp_path / md_name
        md_p.write_bytes(md_raw)
        with pytest.raises(SkaldError) as exc_info:
            load_markdown_book(md_p)
        assert exc_info.value.kind == "unsupported_format"
        assert "contains no text" in exc_info.value.message

    # Missing file -> unsupported_format
    with pytest.raises(SkaldError) as exc_info:
        load_text_book(tmp_path / "does_not_exist.txt")
    assert exc_info.value.kind == "unsupported_format"

    # Exact size limit boundary (patched constant): limit -> OK, limit + 1 -> unsupported_format
    monkeypatch.setattr(text_import_mod, "MAX_TEXT_BYTES", 64)
    ok_txt = tmp_path / "ok.txt"
    ok_txt.write_text("x" * 64, encoding="utf-8")
    assert load_text_book(ok_txt).book.chapters[0].paragraphs[0].text == "x" * 64

    ok_md = tmp_path / "ok.md"
    ok_md.write_text("# " + "x" * 62, encoding="utf-8")
    assert load_markdown_book(ok_md).book.chapters[0].title == "x" * 62

    big_txt = tmp_path / "big.txt"
    big_txt.write_text("x" * 65, encoding="utf-8")
    with pytest.raises(SkaldError) as exc_info:
        load_text_book(big_txt)
    assert exc_info.value.kind == "unsupported_format"
    assert exc_info.value.hint is not None
    assert "too large" in exc_info.value.hint.lower()

    big_md = tmp_path / "big.md"
    big_md.write_text("# " + "x" * 63, encoding="utf-8")
    with pytest.raises(SkaldError) as exc_info:
        load_markdown_book(big_md)
    assert exc_info.value.kind == "unsupported_format"
    assert exc_info.value.hint is not None
    assert "too large" in exc_info.value.hint.lower()


@pytest.mark.timeout(5)
def test_pathological_inputs_do_not_crash_or_hang(tmp_path: Path) -> None:
    huge_line = "word " * 40_000
    many_blanks = "Chapter 1\n" + ("\n" * 10_000) + "After blanks line 1.\nAfter blanks line 2.\n"

    txt_huge = tmp_path / "huge.txt"
    txt_huge.write_text(huge_line, encoding="utf-8")
    res_huge = load_text_book(txt_huge)
    assert len(res_huge.book.chapters) == 1
    _assert_book_invariants(res_huge.book)

    txt_blanks = tmp_path / "blanks.txt"
    txt_blanks.write_text(many_blanks, encoding="utf-8")
    res_blanks = load_text_book(txt_blanks)
    assert len(res_blanks.book.chapters) == 1
    assert [p.text for p in res_blanks.book.chapters[0].paragraphs] == [
        "Chapter 1",
        "After blanks line 1. After blanks line 2.",
    ]

    deep_lists = "\n".join("  " * i + "- item" for i in range(250))
    deep_quotes = "> " * 250 + "quoted"
    unmatched_stars = "*a " * 5_000 + "end"
    md_path = tmp_path / "pathological.md"
    md_payload = (
        f"# Title\n\n{huge_line}\n\n{many_blanks}\n\n"
        f"{deep_lists}\n\n{deep_quotes}\n\n{unmatched_stars}"
    )
    md_path.write_text(md_payload, encoding="utf-8")
    res_md = load_markdown_book(md_path)
    assert len(res_md.book.chapters) == 1
    _assert_book_invariants(res_md.book)
