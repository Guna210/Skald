"""Tests for XHTML-to-paragraphs extraction and load_epub_book (T02.3)."""

from __future__ import annotations

import hashlib
import logging
import re
import tomllib
import zipfile
from pathlib import Path

import pytest

from skald_core.book import load_epub_book, parse_epub
from skald_core.rpc.server import SkaldError
from skald_core.schemas.models import Book

DATA_DIR = Path(__file__).resolve().parent / "data"
EPUB_DEFS_DIR = DATA_DIR / "epub_defs"
EPUB_OUT_DIR = DATA_DIR / "epub"
PUBLIC_DOMAIN_DIR = DATA_DIR / "public_domain"

_CH_ID_RE = re.compile(r"^ch_[0-9a-f]{8}$")
_P_ID_RE = re.compile(r"^p_[0-9a-f]{16}$")

# Fixtures that contain notes, tables, <br>, or page breaks (excluded from D2 length sanity check).
_FIXTURES_WITH_EXCLUDED_ELEMENTS = frozenset(
    {
        "05_nested_sections_and_blocks",
        "06_footnotes_endnotes",
    }
)


def _build_epub(
    dest: Path,
    *,
    body_xhtml: str | None = None,
    nav_entries: list[tuple[str, str]] | None = None,
    extra_files: dict[str, bytes] | None = None,
    spine_ids: list[tuple[str, str]] | None = None,
) -> Path:
    items = spine_ids or [("ch1", "ch1.xhtml")]
    manifest_lines = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    ]
    manifest_lines.extend(
        f'    <item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
        for item_id, href in items
    )
    spine_lines = [f'    <itemref idref="{item_id}"/>' for item_id, _ in items]
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Test Book</dc:title>\n"
        "    <dc:creator>Test Author</dc:creator>\n"
        "    <dc:language>en</dc:language>\n"
        "  </metadata>\n"
        "  <manifest>\n" + "\n".join(manifest_lines) + "\n  </manifest>\n"
        "  <spine>\n" + "\n".join(spine_lines) + "\n  </spine>\n"
        "</package>\n"
    )
    nav_lis = "".join(
        f'<li><a href="{href}">{title}</a></li>'
        for title, href in (nav_entries or [("Chapter 1", "ch1.xhtml")])
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        f'<body><nav epub:type="toc"><ol>{nav_lis}</ol></nav></body></html>\n'
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        if body_xhtml is not None:
            doc = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"'
                ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
                f"<body>\n{body_xhtml}\n</body></html>\n"
            ).encode()
            zf.writestr("OEBPS/ch1.xhtml", doc)
        if extra_files:
            for name, data in extra_files.items():
                zf.writestr(name, data)
    return dest


def _synthetic_fixture_ids() -> list[str]:
    return [p.stem for p in sorted(EPUB_DEFS_DIR.glob("*.toml"))]


@pytest.mark.parametrize("fixture_id", _synthetic_fixture_ids())
def test_synthetic_fixtures_paragraphs_and_metadata(
    fixture_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def_path = EPUB_DEFS_DIR / f"{fixture_id}.toml"
    epub_path = EPUB_OUT_DIR / f"{fixture_id}.epub"
    with def_path.open("rb") as fh:
        spec = tomllib.load(fh)
    exp = spec["expected"]

    if exp["status"] in {"epub_drm", "epub_invalid"}:
        with pytest.raises(SkaldError) as exc_info:
            load_epub_book(epub_path)
        assert exc_info.value.kind == exp["status"]
        return

    with caplog.at_level(logging.WARNING):
        book = load_epub_book(epub_path)
    structure = parse_epub(epub_path)

    assert isinstance(book, Book)
    assert book.title == exp["title"]
    assert book.authors == exp["authors"]
    assert book.language == exp["language"]
    assert book.cover_path is None
    assert book.source_path is None

    expected_chapters = exp["chapters"]
    assert len(book.chapters) == len(expected_chapters)

    all_p_ids: list[str] = []
    for ch_idx, (ch, want, s_ch) in enumerate(
        zip(book.chapters, expected_chapters, structure.chapters, strict=True)
    ):
        expected_ch_id = (
            "ch_" + hashlib.sha256(f"{ch_idx}\0{s_ch.full_href}".encode()).hexdigest()[:8]
        )
        assert _CH_ID_RE.match(ch.id)
        assert ch.id == expected_ch_id
        assert ch.title == want["title"]
        assert ch.linear is want["linear"]
        assert ch.skip_reasons == want["skip_reasons"]
        assert ch.included is (want["linear"] and not want["suggested_skip"])

        assert [p.text for p in ch.paragraphs] == want["paragraphs"]
        for p_idx, p in enumerate(ch.paragraphs):
            expected_p_id = (
                "p_" + hashlib.sha256(f"{ch.id}\0{p_idx}\0{p.text}".encode()).hexdigest()[:16]
            )
            assert _P_ID_RE.match(p.id)
            assert p.id == expected_p_id
            assert p.unbalanced_quotes is False
            assert p.sentences == []
            all_p_ids.append(p.id)

        if fixture_id not in _FIXTURES_WITH_EXCLUDED_ELEMENTS:
            joined = " ".join(p.text for p in ch.paragraphs)
            assert abs(len(joined) - s_ch.char_count) <= len(ch.paragraphs)

    assert len(all_p_ids) == len(set(all_p_ids))

    if fixture_id == "05_nested_sections_and_blocks":
        assert [p.is_heading for p in book.chapters[0].paragraphs] == [
            True,  # Main Section (h1)
            False,  # nested inline p
            False,  # verse with br
            True,  # Nested Subsection (h2)
            False,  # blockquote p
            False,  # ul li 1
            False,  # ul li 2
            False,  # tr 1
            False,  # tr 2
            False,  # tr 3
        ]

    if fixture_id == "11_malformed_xhtml":
        assert any("OEBPS/ch1.xhtml" in rec.message for rec in caplog.records)


@pytest.mark.parametrize(
    "epub_name",
    ["pg43-jekyll-hyde.epub", "pg46-christmas-carol.epub"],
)
def test_public_domain_epubs_no_empty_paragraphs_and_unique_ids(epub_name: str) -> None:
    epub_path = PUBLIC_DOMAIN_DIR / epub_name
    book1 = load_epub_book(epub_path)
    book2 = load_epub_book(epub_path)

    assert book1 == book2
    assert book1.cover_path is None
    assert book1.source_path is None
    assert len(book1.chapters) > 0

    ch_ids = [ch.id for ch in book1.chapters]
    assert len(ch_ids) == len(set(ch_ids))

    p_ids: list[str] = []
    total_paragraphs = 0
    for ch in book1.chapters:
        for p in ch.paragraphs:
            total_paragraphs += 1
            assert p.text
            assert p.text.strip() == p.text
            assert all(line.strip() == line and line for line in p.text.split("\n"))
            assert _P_ID_RE.match(p.id)
            p_ids.append(p.id)

    assert total_paragraphs > 100
    assert len(p_ids) == len(set(p_ids))


def test_footnotes_endnotes_and_noteref_next_to_punctuation(tmp_path: Path) -> None:
    body = """
    <h1>Notes</h1>
    <p>Sentence ending here.<a epub:type="noteref" href="#fn1">1</a> Next sentence starts.</p>
    <p>Pause here<a role="doc-noteref" href="#fn2">*</a>, then continue!<sup
      class="fn"><a epub:type="noteref" href="#fn3">[3]</a></sup></p>
    <p>Tail after inline note body <span role="doc-footnote">ignored note</span>stays intact.</p>
    <aside epub:type="footnote" id="fn1"><p>Footnote body 1.</p></aside>
    <div role="doc-footnote" id="fn2"><p>Footnote body 2.</p></div>
    <section epub:type="endnote" id="fn3"><p>Endnote body 3.</p></section>
    <aside role="doc-endnote" id="en4"><p>Endnote body 4.</p></aside>
    """
    epub = _build_epub(tmp_path / "notes.epub", body_xhtml=body)
    book = load_epub_book(epub)
    assert [p.text for p in book.chapters[0].paragraphs] == [
        "Notes",
        "Sentence ending here. Next sentence starts.",
        "Pause here, then continue!",
        "Tail after inline note body stays intact.",
    ]


def test_nested_inline_markup_and_headings_h1_to_h6(tmp_path: Path) -> None:
    body = """
    <h1>Heading <i>1</i></h1>
    <h2>Heading 2</h2>
    <h3>Heading 3</h3>
    <h4>Heading 4</h4>
    <h5>Heading 5</h5>
    <h6>Heading 6</h6>
    <p>Deep <em>nested <strong><span class="x"><a
      href="#x"><i>inline</i></a></span> text</strong></em> with
      <code>code</code> and <small>small</small>.</p>
    """
    epub = _build_epub(tmp_path / "inline_headings.epub", body_xhtml=body)
    book = load_epub_book(epub)
    paras = book.chapters[0].paragraphs
    assert [p.text for p in paras] == [
        "Heading 1",
        "Heading 2",
        "Heading 3",
        "Heading 4",
        "Heading 5",
        "Heading 6",
        "Deep nested inline text with code and small.",
    ]
    assert [p.is_heading for p in paras] == [True, True, True, True, True, True, False]


def test_br_handling_and_literal_newlines(tmp_path: Path) -> None:
    body = """
    <p>
      Line one   with   spaces
      wrapped across source lines.<br/>
      <br/>
        Second verse line.  <br/>
    </p>
    <p><br/><br/></p>
    <p>   </p>
    """
    epub = _build_epub(tmp_path / "br.epub", body_xhtml=body)
    book = load_epub_book(epub)
    assert [p.text for p in book.chapters[0].paragraphs] == [
        "Line one with spaces wrapped across source lines.\nSecond verse line.",
    ]


def test_tables_lists_blockquotes_and_mixed_container_text(tmp_path: Path) -> None:
    body = """
    <div>
      Intro direct text in container.
      <p>Child paragraph inside div.</p>
      Middle direct text between blocks.
      <blockquote>Direct text inside blockquote.</blockquote>
      <blockquote>
        <p>First quoted paragraph.</p>
        <p>Second quoted paragraph.</p>
      </blockquote>
      <ol>
        <li>Ordered one.</li>
        <li><p>Ordered two A.</p><p>Ordered two B.</p></li>
      </ol>
      <table>
        <caption>Table Title</caption>
        <tr><th>Col A</th><th>Col B</th></tr>
        <tr><td><p>Cell 1</p><p>extra</p></td><td>&#160;</td><td>Cell 2</td></tr>
        <tr><td>&#160;</td><td></td></tr>
      </table>
      Trailing direct text in container.
    </div>
    """
    epub = _build_epub(tmp_path / "blocks.epub", body_xhtml=body)
    book = load_epub_book(epub)
    assert [p.text for p in book.chapters[0].paragraphs] == [
        "Intro direct text in container.",
        "Child paragraph inside div.",
        "Middle direct text between blocks.",
        "Direct text inside blockquote.",
        "First quoted paragraph.",
        "Second quoted paragraph.",
        "Ordered one.",
        "Ordered two A.",
        "Ordered two B.",
        "Table Title",
        "Col A Col B",
        "Cell 1 extra Cell 2",
        "Trailing direct text in container.",
    ]


def test_skip_img_script_style_pagebreak_and_ruby(tmp_path: Path) -> None:
    body = """
    <script>var x = 1;</script>
    <style>.a { color: red; }</style>
    <p>Before image<img src="pic.png" alt="Should never be read"/> after image.</p>
    <p>Page <span epub:type="pagebreak" id="pg12">12</span>breaks <span
      role="doc-pagebreak">xiii</span>quietly.</p>
    <div epub:type="pagebreak">42</div>
    <p>Read <ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp>字<rp>(</rp><rt>じ</rt><rp>)</rp></ruby>
      and <ruby><rb>東京</rb><rp>（</rp><rt>とうきょう</rt><rp>）</rp></ruby> cleanly.</p>
    <!-- comment skipped -->Tail after comment<?pi target?> and PI.
    """
    epub = _build_epub(tmp_path / "skips.epub", body_xhtml=body)
    book = load_epub_book(epub)
    assert [p.text for p in book.chapters[0].paragraphs] == [
        "Before image after image.",
        "Page breaks quietly.",
        "Read 漢字 and 東京 cleanly.",
        "Tail after comment and PI.",
    ]


def test_anchor_mid_paragraph_and_dangling_and_duplicate_text_unique_ids(tmp_path: Path) -> None:
    body = """
    <p>Pre-anchor text.</p>
    <p id="s1">First part <a id="s2"/>Second part.</p>
    <section id="s3"><p>Repeated line.</p><p>Repeated line.</p></section>
    """
    nav = [
        ("Sec 1", "ch1.xhtml#s1"),
        ("Sec 2", "ch1.xhtml#s2"),
        ("Gone", "ch1.xhtml#missing"),
        ("Sec 3", "ch1.xhtml#s3"),
    ]
    epub = _build_epub(tmp_path / "slices.epub", body_xhtml=body, nav_entries=nav)
    book = load_epub_book(epub)

    assert len(book.chapters) == 4
    assert [p.text for p in book.chapters[0].paragraphs] == ["Pre-anchor text.", "First part"]
    assert [p.text for p in book.chapters[1].paragraphs] == ["Second part."]
    assert book.chapters[2].paragraphs == []
    assert [p.text for p in book.chapters[3].paragraphs] == ["Repeated line.", "Repeated line."]

    p_ids = [p.id for ch in book.chapters for p in ch.paragraphs]
    assert len(p_ids) == len(set(p_ids))


def test_pre_preserves_line_breaks_like_br(tmp_path: Path) -> None:
    body = """
    <pre>
      First   stanza line
      <span>Second</span> <em>stanza</em> line

      Third line after blank.<br/>Fourth after br.
    </pre>
    <table>
      <tr><td><pre>Cell line 1
  Cell line 2  </pre></td><td>Col 2</td></tr>
    </table>
    <pre>

    </pre>
    """
    epub = _build_epub(tmp_path / "pre.epub", body_xhtml=body)
    book = load_epub_book(epub)
    assert [p.text for p in book.chapters[0].paragraphs] == [
        "First stanza line\nSecond stanza line\nThird line after blank.\nFourth after br.",
        "Cell line 1\nCell line 2 Col 2",
    ]


def test_figcaption_skipped_while_non_standard_div_fig_kept(tmp_path: Path) -> None:
    body = """
    <p>Paragraph before figure.</p>
    <figure>
      <img src="plate1.png" alt="Ignored alt text"/>
      <figcaption><p>Plate 1: Ignored caption text.</p></figcaption>
    </figure>
    <div class="fig">Non-standard Gutenberg caption stays in.</div>
    <p>Paragraph after figure.</p>
    """
    epub = _build_epub(tmp_path / "figcaption.epub", body_xhtml=body)
    book = load_epub_book(epub)
    assert [p.text for p in book.chapters[0].paragraphs] == [
        "Paragraph before figure.",
        "Non-standard Gutenberg caption stays in.",
        "Paragraph after figure.",
    ]


def test_anchor_inside_heading_keeps_is_heading_and_resets_after_heading(tmp_path: Path) -> None:
    body = """
    <h1><a id="c1"/>Chapter One</h1>
    <p>Body one.</p>
    <h2><a id="c2"/>Chapter Two</h2>
    <p>Body two.</p>
    <div><h3><span><a id="c3"/></span>Chapter Three</h3></div>
    <p>Body three.</p>
    """
    nav = [
        ("Chapter One", "ch1.xhtml#c1"),
        ("Chapter Two", "ch1.xhtml#c2"),
        ("Chapter Three", "ch1.xhtml#c3"),
    ]
    epub = _build_epub(tmp_path / "heading_anchors.epub", body_xhtml=body, nav_entries=nav)
    book = load_epub_book(epub)

    assert len(book.chapters) == 3
    assert [(p.text, p.is_heading) for p in book.chapters[0].paragraphs] == [
        ("Chapter One", True),
        ("Body one.", False),
    ]
    assert [(p.text, p.is_heading) for p in book.chapters[1].paragraphs] == [
        ("Chapter Two", True),
        ("Body two.", False),
    ]
    assert [(p.text, p.is_heading) for p in book.chapters[2].paragraphs] == [
        ("Chapter Three", True),
        ("Body three.", False),
    ]
