"""Tests for EPUB container, spine, navigation, metadata, DRM, and safety (T02.2)."""

from __future__ import annotations

import logging
import time
import tomllib
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from lxml import etree  # type: ignore[import-untyped]

from skald_core.book import EpubStructure, parse_epub
from skald_core.book.epub import _recover_parser, _strict_parser
from skald_core.rpc.server import SkaldError

DATA_DIR = Path(__file__).resolve().parent / "data"
EPUB_DEFS_DIR = DATA_DIR / "epub_defs"
EPUB_OUT_DIR = DATA_DIR / "epub"
PUBLIC_DOMAIN_DIR = DATA_DIR / "public_domain"


def _build_minimal_epub(
    dest: Path,
    *,
    container_xml: str | None = None,
    opf_xml: str | None = None,
    nav_xml: str | None = None,
    ncx_xml: str | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    default_container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="OEBPS/content.opf"'
        ' media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )
    default_opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Test Book</dc:title>\n"
        "    <dc:creator>Test Author</dc:creator>\n"
        "    <dc:language>en</dc:language>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        "  <spine>\n"
        '    <itemref idref="ch1"/>\n'
        "  </spine>\n"
        "</package>\n"
    )
    default_ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head><title>Ch1</title></head>\n"
        "<body><h1>Chapter One</h1><p>" + ("word " * 60) + "</p></body>\n"
        "</html>\n"
    )

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml or default_container)
        zf.writestr("OEBPS/content.opf", opf_xml or default_opf)
        if nav_xml is not None:
            zf.writestr("OEBPS/nav.xhtml", nav_xml)
        if ncx_xml is not None:
            zf.writestr("OEBPS/toc.ncx", ncx_xml)
        if extra_files is None or "OEBPS/ch1.xhtml" not in extra_files:
            zf.writestr("OEBPS/ch1.xhtml", default_ch1)
        if extra_files:
            for name, content in extra_files.items():
                zf.writestr(name, content)
    return dest


def _synthetic_fixture_ids() -> list[str]:
    return [p.stem for p in sorted(EPUB_DEFS_DIR.glob("*.toml"))]


@pytest.mark.parametrize("fixture_id", _synthetic_fixture_ids())
def test_synthetic_fixture_matches_expected(
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
            parse_epub(epub_path)
        assert exc_info.value.kind == exp["status"]
        return

    with caplog.at_level(logging.WARNING):
        result = parse_epub(epub_path)

    assert isinstance(result, EpubStructure)
    assert result.metadata.title == exp["title"]
    assert result.metadata.authors == exp["authors"]
    assert result.metadata.language == exp["language"]

    if exp["has_cover"]:
        assert result.cover is not None
        assert result.cover.href == exp["cover_href"]
        assert result.cover.media_type == "image/png"
        with zipfile.ZipFile(epub_path, "r") as zf:
            assert result.cover.data == zf.read(exp["cover_href"])
    else:
        assert result.cover is None

    expected_chapters = exp["chapters"]
    assert len(result.chapters) == len(expected_chapters)
    for actual, want in zip(result.chapters, expected_chapters, strict=True):
        assert actual.title == want["title"]
        assert actual.full_href == want["href"]
        assert actual.linear is want["linear"]
        assert actual.suggested_skip is want["suggested_skip"]
        assert actual.skip_reasons == want["skip_reasons"]

    if fixture_id == "11_malformed_xhtml":
        assert any("OEBPS/ch1.xhtml" in rec.message for rec in caplog.records)


def test_public_domain_gutenberg_smoke() -> None:
    jekyll = parse_epub(PUBLIC_DOMAIN_DIR / "pg43-jekyll-hyde.epub")
    assert jekyll.metadata.title
    assert jekyll.metadata.authors
    assert jekyll.metadata.language
    assert len(jekyll.chapters) == 14
    jekyll_titles = [ch.title for ch in jekyll.chapters]
    assert "STORY OF THE DOOR" in jekyll_titles
    assert "DR. JEKYLL WAS QUITE AT EASE" in jekyll_titles

    carol = parse_epub(PUBLIC_DOMAIN_DIR / "pg46-christmas-carol.epub")
    assert carol.metadata.title
    assert carol.metadata.authors
    assert carol.metadata.language
    assert len(carol.chapters) == 25
    stave_one = [ch for ch in carol.chapters if ch.title == "STAVE ONE."]
    assert len(stave_one) == 1
    assert stave_one[0].suggested_skip is True
    assert "short" in stave_one[0].skip_reasons


@pytest.mark.parametrize(
    "bad_href",
    [
        "../outside.xhtml",
        "../../etc/passwd",
        "/etc/passwd",
        r"..\outside.xhtml",
        "%2e%2e/outside.xhtml",
        "%2e%2e%5coutside.xhtml",
        "file:///etc/passwd",
    ],
)
def test_zip_slip_paths_rejected_in_opf(tmp_path: Path, bad_href: str) -> None:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Bad Path</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        f'    <item id="ch1" href="{bad_href}" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        "  <spine>\n"
        '    <itemref idref="ch1"/>\n'
        "  </spine>\n"
        "</package>\n"
    )
    epub_path = _build_minimal_epub(tmp_path / "zipslip.epub", opf_xml=opf)
    with pytest.raises(SkaldError) as exc_info:
        parse_epub(epub_path)
    assert exc_info.value.kind == "epub_invalid"


def test_url_encoded_href_resolves_cleanly(tmp_path: Path) -> None:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Encoded Href</dc:title>\n"
        "    <dc:language>fr</dc:language>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="text/chapitre%20%C3%A9t%C3%A9.xhtml"'
        ' media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        "  <spine>\n"
        '    <itemref idref="ch1"/>\n'
        "  </spine>\n"
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<body>\n"
        '  <nav epub:type="toc"><ol>'
        '<li><a href="text/chapitre%20%C3%A9t%C3%A9.xhtml">L’Été</a></li>'
        "</ol></nav>\n"
        "</body></html>\n"
    )
    ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<body><h1>L’Été</h1><p>" + ("bonjour " * 40) + "</p></body></html>\n"
    ).encode("utf-8")

    epub_path = _build_minimal_epub(
        tmp_path / "encoded.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files={"OEBPS/text/chapitre été.xhtml": ch1},
    )
    result = parse_epub(epub_path)
    assert len(result.chapters) == 1
    assert result.chapters[0].href == "OEBPS/text/chapitre été.xhtml"
    assert result.chapters[0].title == "L’Été"


def test_uncompressed_size_limit_500_000_000(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epub_path = _build_minimal_epub(tmp_path / "size.epub")
    orig_infolist = zipfile.ZipFile.infolist

    def _make_infolist(limit: int) -> Any:
        def _infolist(self: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
            infos = orig_infolist(self)
            if infos:
                other = sum(i.file_size for i in infos[1:])
                infos[0].file_size = limit - other
            return infos

        return _infolist

    with monkeypatch.context() as mp:
        mp.setattr(zipfile.ZipFile, "infolist", _make_infolist(500_000_000))
        result = parse_epub(epub_path)
        assert len(result.chapters) == 1

    with monkeypatch.context() as mp:
        mp.setattr(zipfile.ZipFile, "infolist", _make_infolist(500_000_001))
        with pytest.raises(SkaldError) as exc_info:
            parse_epub(epub_path)
        assert exc_info.value.kind == "epub_invalid"
        assert "500,000,000" in exc_info.value.message


def test_duplicate_zip_entry_names_rejected(tmp_path: Path) -> None:
    epub_path = tmp_path / "dup.epub"
    _build_minimal_epub(epub_path)
    with zipfile.ZipFile(epub_path, "a") as zf:
        zf.writestr("OEBPS/ch1.xhtml", b"<html/>")

    with pytest.raises(SkaldError) as exc_info:
        parse_epub(epub_path)
    assert exc_info.value.kind == "epub_invalid"


def test_parser_factories_enforce_safe_flags() -> None:
    with patch("skald_core.book.epub.etree.XMLParser", wraps=etree.XMLParser) as spy:
        _strict_parser()
        spy.assert_called_once_with(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        )

    with patch("skald_core.book.epub.etree.XMLParser", wraps=etree.XMLParser) as spy:
        _recover_parser()
        spy.assert_called_once_with(
            recover=True,
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        )


def test_external_entity_blocked_in_opf_and_xhtml_and_recover(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret.txt"
    secret = "SECRET_PAYLOAD_DO_NOT_LEAK"
    secret_file.write_text(secret, encoding="utf-8")
    secret_uri = secret_file.as_uri()

    # 1. External entity in OPF
    xxe_opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE package [<!ENTITY x SYSTEM "{secret_uri}">]>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>&x;</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    opf_epub = _build_minimal_epub(tmp_path / "xxe_opf.epub", opf_xml=xxe_opf)
    try:
        res = parse_epub(opf_epub)
        assert secret not in res.metadata.title
    except SkaldError as exc:
        assert exc.kind == "epub_invalid"

    # 2. External entity in well-formed content XHTML
    xxe_xhtml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE html [<!ENTITY x SYSTEM "{secret_uri}">]>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<body><h1>&x;</h1><p>Body text.</p></body></html>\n"
    ).encode()
    xhtml_epub = _build_minimal_epub(
        tmp_path / "xxe_xhtml.epub",
        extra_files={"OEBPS/ch1.xhtml": xxe_xhtml},
    )
    res_xhtml = parse_epub(xhtml_epub)
    assert secret not in res_xhtml.chapters[0].title
    assert res_xhtml.chapters[0].char_count < 100

    # 3. External entity in MALFORMED content XHTML (recover=True path)
    xxe_malformed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE html [<!ENTITY x SYSTEM "{secret_uri}">]>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<body><h1>&x;</h1><p>Unclosed <b>bold</p></b></body></html>\n"
    ).encode()
    malformed_epub = _build_minimal_epub(
        tmp_path / "xxe_malformed.epub",
        extra_files={"OEBPS/ch1.xhtml": xxe_malformed},
    )
    res_malformed = parse_epub(malformed_epub)
    assert secret not in res_malformed.chapters[0].title
    assert res_malformed.chapters[0].char_count < 100


def test_billion_laughs_entity_bomb_bounded(tmp_path: Path) -> None:
    entities = (
        '  <!ENTITY lol "lol">\n'
        '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
        '  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">\n'
        '  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">\n'
        '  <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">\n'
        '  <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">\n'
        '  <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">\n'
        '  <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">\n'
    )
    bomb_opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<!DOCTYPE package [\n{entities}]>\n"
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>&lol9;</dc:title>\n"
        "  </metadata>\n"
        '  <manifest><item id="ch1" href="ch1.xhtml"'
        ' media-type="application/xhtml+xml"/></manifest>\n'
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    epub_path = _build_minimal_epub(tmp_path / "laughs.epub", opf_xml=bomb_opf)
    t0 = time.monotonic()
    try:
        res = parse_epub(epub_path)
        assert "lol" * 10 not in res.metadata.title
        assert len(res.metadata.title) < 100
    except SkaldError as exc:
        assert exc.kind == "epub_invalid"
    assert time.monotonic() - t0 < 2.0


def test_d2_char_count_rules_and_boundaries(tmp_path: Path) -> None:
    # 199 chars vs 200 chars, headings included, script/style excluded (tails kept),
    # whitespace/newlines collapsed, comments & PIs excluded (tails kept).
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>D2 Rules</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="c199" href="c199.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="c200" href="c200.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="c199"/><itemref idref="c200"/></spine>\n'
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="c199.xhtml">Short</a></li>'
        '<li><a href="c200.xhtml">Exact</a></li>'
        "</ol></nav></body></html>\n"
    )
    # "Head" (4) + " " (1) + "a"*190 (190) + " " (1) + "end" (3) = 199
    c199 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        "  <h1>  Head  </h1>\n"
        f"  <script>alert('ignore me');</script>{'a' * 190}\n"
        "  <style>.x{color:red;}</style><!-- comment ignored --><?pi ignored?>end\n"
        "</body></html>\n"
    ).encode()
    # "Head" (4) + " " (1) + "b"*195 (195) = 200
    c200 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        "  <h2>Head</h2>\n\n\n"
        f"  <p>{'b' * 195}</p>\n"
        "</body></html>\n"
    ).encode()

    epub_path = _build_minimal_epub(
        tmp_path / "d2.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files={"OEBPS/c199.xhtml": c199, "OEBPS/c200.xhtml": c200},
    )
    res = parse_epub(epub_path)
    assert res.chapters[0].char_count == 199
    assert res.chapters[0].suggested_skip is True
    assert res.chapters[0].skip_reasons == ["short"]

    assert res.chapters[1].char_count == 200
    assert res.chapters[1].suggested_skip is False
    assert res.chapters[1].skip_reasons == []


def test_text_before_first_anchor_and_dangling_anchors(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Anchor Cases</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/><itemref idref="ch2"/></spine>\n'
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml#sec1">Sec 1</a></li>'
        '<li><a href="ch1.xhtml#sec2">Sec 2</a></li>'
        '<li><a href="ch2.xhtml#missing">Dangling</a></li>'
        "</ol></nav></body></html>\n"
    )
    ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        f"<p>{'P' * 210}</p>\n"
        '<section id="sec1"><p>First section.</p></section>\n'
        f'<section id="sec2"><p>{"S" * 205}</p></section>\n'
        "</body></html>\n"
    ).encode()
    ch2 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        f"<p>{'D' * 220}</p>\n"
        "</body></html>\n"
    ).encode()

    epub_path = _build_minimal_epub(
        tmp_path / "anchors.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files={"OEBPS/ch1.xhtml": ch1, "OEBPS/ch2.xhtml": ch2},
    )
    with caplog.at_level(logging.WARNING):
        res = parse_epub(epub_path)

    assert len(res.chapters) == 3
    # Text before #sec1 belongs to the first chapter in ch1.xhtml
    assert res.chapters[0].title == "Sec 1"
    assert res.chapters[0].char_count == 210 + len(" First section.")
    assert res.chapters[0].suggested_skip is False

    assert res.chapters[1].title == "Sec 2"
    assert res.chapters[1].char_count == 205

    # Dangling anchor in ch2.xhtml logs warning naming file#fragment and starts at top of file
    assert res.chapters[2].title == "Dangling"
    assert res.chapters[2].char_count == 220
    assert any("OEBPS/ch2.xhtml#missing" in rec.message for rec in caplog.records)


def test_remote_manifest_resource_ignored(tmp_path: Path) -> None:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Remote OK</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="remote_css" href="https://example.com/style.css"'
        ' media-type="text/css" properties="remote-resources"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    epub_path = _build_minimal_epub(tmp_path / "remote.epub", opf_xml=opf)
    res = parse_epub(epub_path)
    assert res.metadata.title == "Remote OK"
    assert len(res.chapters) == 1


def test_embedded_toc_nav_inside_prose_not_flagged(tmp_path: Path) -> None:
    ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<body>\n"
        "  <div>\n"
        '    <nav epub:type="toc"><ol><li><a href="#p1">Part 1</a></li></ol></nav>\n'
        f'    <p id="p1">{"Prose " * 50}</p>\n'
        '    <div epub:type="index"><p>Embedded index note</p></div>\n'
        "  </div>\n"
        "</body></html>\n"
    ).encode()
    epub_path = _build_minimal_epub(
        tmp_path / "embedded_nav.epub",
        extra_files={"OEBPS/ch1.xhtml": ch1},
    )
    res = parse_epub(epub_path)
    assert len(res.chapters) == 1
    assert res.chapters[0].suggested_skip is False
    assert res.chapters[0].skip_reasons == []


def test_broken_ncx_ignored_when_nav_has_entries(tmp_path: Path) -> None:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Good Nav Broken NCX</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine toc="ncx"><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml">Chapter One</a></li>'
        "</ol></nav></body></html>\n"
    )
    broken_ncx = "<ncx><unclosed></ncx>"
    epub_path = _build_minimal_epub(
        tmp_path / "broken_ncx.epub",
        opf_xml=opf,
        nav_xml=nav,
        ncx_xml=broken_ncx,
    )
    res = parse_epub(epub_path)
    assert len(res.chapters) == 1
    assert res.chapters[0].title == "Chapter One"


def test_corrupt_zip_and_missing_container_rejected(tmp_path: Path) -> None:
    bad_zip = tmp_path / "not_a_zip.epub"
    bad_zip.write_bytes(b"not a zip archive")
    with pytest.raises(SkaldError) as exc_info:
        parse_epub(bad_zip)
    assert exc_info.value.kind == "epub_invalid"

    no_container = tmp_path / "no_container.epub"
    with zipfile.ZipFile(no_container, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
    with pytest.raises(SkaldError) as exc_info:
        parse_epub(no_container)
    assert exc_info.value.kind == "epub_invalid"


def test_reversed_nav_anchors_ordered_by_document_position(tmp_path: Path) -> None:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Reversed Nav</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        f'<section id="a"><p>{"Alpha " * 18}</p></section>\n'
        f'<section id="b"><p>{"Bravo " * 18}</p></section>\n'
        f'<section id="c"><p>{"Charlie " * 18}</p></section>\n'
        "</body></html>\n"
    ).encode()

    # Whole-file count without nav splitting
    whole_epub = _build_minimal_epub(
        tmp_path / "whole.epub",
        opf_xml=opf.replace(
            '    <item id="nav" href="nav.xhtml"'
            ' media-type="application/xhtml+xml" properties="nav"/>\n',
            "",
        ),
        extra_files={"OEBPS/ch1.xhtml": ch1},
    )
    whole_count = parse_epub(whole_epub).chapters[0].char_count

    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml#c">Title C</a></li>'
        '<li><a href="ch1.xhtml#b">Title B</a></li>'
        '<li><a href="ch1.xhtml#a">Title A</a></li>'
        "</ol></nav></body></html>\n"
    )
    rev_epub = _build_minimal_epub(
        tmp_path / "reversed.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files={"OEBPS/ch1.xhtml": ch1},
    )
    res = parse_epub(rev_epub)
    assert [ch.title for ch in res.chapters] == ["Title A", "Title B", "Title C"]
    assert [ch.anchor for ch in res.chapters] == ["a", "b", "c"]
    assert all(ch.char_count > 0 for ch in res.chapters)
    assert abs(sum(ch.char_count for ch in res.chapters) - whole_count) <= 2


@pytest.mark.parametrize(
    ("anchors", "expected_warnings"),
    [
        (["missing_first", "b", "c"], ["OEBPS/ch1.xhtml#missing_first"]),
        (["a", "missing_mid", "c"], ["OEBPS/ch1.xhtml#missing_mid"]),
        (["a", "b", "missing_last"], ["OEBPS/ch1.xhtml#missing_last"]),
        (["a", "m1", "m2", "c"], ["OEBPS/ch1.xhtml#m1", "OEBPS/ch1.xhtml#m2"]),
    ],
)
def test_dangling_anchors_first_middle_last_and_consecutive(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    anchors: list[str],
    expected_warnings: list[str],
) -> None:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Dangling Matrix</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        f'<section id="a"><p>{"Alpha " * 15}</p></section>\n'
        f'<section id="b"><p>{"Bravo " * 15}</p></section>\n'
        f'<section id="c"><p>{"Charlie " * 15}</p></section>\n'
        "</body></html>\n"
    ).encode()
    whole_count = (
        len(" ".join(["Alpha"] * 15))
        + 1
        + len(" ".join(["Bravo"] * 15))
        + 1
        + len(" ".join(["Charlie"] * 15))
    )

    lis = "".join(f'<li><a href="ch1.xhtml#{a}">{a}</a></li>' for a in anchors)
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        f'<body><nav epub:type="toc"><ol>{lis}</ol></nav></body></html>\n'
    )
    epub_path = _build_minimal_epub(
        tmp_path / "dangling.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files={"OEBPS/ch1.xhtml": ch1},
    )
    with caplog.at_level(logging.WARNING):
        res = parse_epub(epub_path)

    assert len(res.chapters) == len(anchors)
    for warn in expected_warnings:
        assert any(warn in rec.message for rec in caplog.records)
    # No overlap: sum of per-chapter counts matches whole-file count within boundary spaces.
    assert abs(sum(ch.char_count for ch in res.chapters) - whole_count) <= len(anchors)


def test_dangling_anchor_position_out_of_order_nav(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T02.2 R3-1: nav order a, gone, c, b places 'gone' after 'a' and before 'b'."""
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Dangling Order</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    ch1 = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        b'  <section id="a"><p>Alpha section text.</p></section>\n'
        b'  <section id="b"><p>Bravo section text.</p></section>\n'
        b'  <section id="c"><p>Charlie section text.</p></section>\n'
        b"</body></html>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml#a">A</a></li>'
        '<li><a href="ch1.xhtml#gone">Gone</a></li>'
        '<li><a href="ch1.xhtml#c">C</a></li>'
        '<li><a href="ch1.xhtml#b">B</a></li>'
        "</ol></nav></body></html>\n"
    )
    epub_path = _build_minimal_epub(
        tmp_path / "dangling_order.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files={"OEBPS/ch1.xhtml": ch1},
    )
    with caplog.at_level(logging.WARNING):
        res = parse_epub(epub_path)

    assert [ch.anchor for ch in res.chapters] == ["a", "gone", "b", "c"]
    assert res.chapters[1].char_count == 0
    assert res.chapters[0].char_count == len("Alpha section text.")
    assert res.chapters[2].char_count == len("Bravo section text.")
    assert res.chapters[3].char_count == len("Charlie section text.")
    assert any("OEBPS/ch1.xhtml#gone" in rec.message for rec in caplog.records)


def test_rule4_epub_type_scope_positive_and_negative(tmp_path: Path) -> None:
    prose = "word " * 50  # 250 chars -> never "short"
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Scope Test</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="html_flag" href="html_flag.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="body_flag" href="body_flag.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="split" href="split.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="top_sec" href="top_sec.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="neg" href="neg.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        "  <spine>\n"
        '    <itemref idref="html_flag"/>\n'
        '    <itemref idref="body_flag"/>\n'
        '    <itemref idref="split"/>\n'
        '    <itemref idref="top_sec"/>\n'
        '    <itemref idref="neg"/>\n'
        "  </spine>\n"
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="html_flag.xhtml">Html</a></li>'
        '<li><a href="body_flag.xhtml">Body</a></li>'
        '<li><a href="split.xhtml#cp">Anchor Self</a></li>'
        '<li><a href="split.xhtml#idx">Ancestor Div</a></li>'
        '<li><a href="split.xhtml#toc_sec">Ancestor Sec</a></li>'
        '<li><a href="top_sec.xhtml">Top Sec</a></li>'
        '<li><a href="neg.xhtml">Neg</a></li>'
        "</ol></nav></body></html>\n"
    )
    files = {
        "OEBPS/html_flag.xhtml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            f' xmlns:epub="http://www.idpf.org/2007/ops" epub:type="cover">'
            f"<body><p>{prose}</p></body></html>\n"
        ).encode(),
        "OEBPS/body_flag.xhtml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            ' xmlns:epub="http://www.idpf.org/2007/ops">'
            f'<body epub:type="toc"><p>{prose}</p></body></html>\n'
        ).encode(),
        "OEBPS/split.xhtml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            ' xmlns:epub="http://www.idpf.org/2007/ops"><body>\n'
            f'  <h1 id="cp" epub:type="copyright-page">Copyright</h1><p>{prose}</p>\n'
            f'  <div epub:type="index"><h1 id="idx">Index</h1><p>{prose}</p></div>\n'
            f'  <section epub:type="toc"><h1 id="toc_sec">TOC</h1><p>{prose}</p></section>\n'
            "</body></html>\n"
        ).encode(),
        "OEBPS/top_sec.xhtml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            ' xmlns:epub="http://www.idpf.org/2007/ops"><body>\n'
            f'  <section epub:type="index"><p>{prose}</p></section>\n'
            "</body></html>\n"
        ).encode(),
        "OEBPS/neg.xhtml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            ' xmlns:epub="http://www.idpf.org/2007/ops"><body>\n'
            f'  <div epub:type="index"><p>{prose}</p></div>\n'
            '  <section><div epub:type="toc"><p>Nested</p></div></section>\n'
            "</body></html>\n"
        ).encode(),
    }
    epub_path = _build_minimal_epub(
        tmp_path / "scope.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files=files,
    )
    res = parse_epub(epub_path)
    by_title = {ch.title: ch for ch in res.chapters}
    assert by_title["Html"].skip_reasons == ["cover"]
    assert by_title["Body"].skip_reasons == ["toc"]
    assert by_title["Anchor Self"].skip_reasons == ["copyright-page"]
    assert by_title["Ancestor Div"].skip_reasons == ["index"]
    assert by_title["Ancestor Sec"].skip_reasons == ["toc"]
    assert by_title["Top Sec"].skip_reasons == ["index"]
    assert by_title["Neg"].suggested_skip is False
    assert by_title["Neg"].skip_reasons == []


def test_landmark_scope_unanchored_and_anchored(tmp_path: Path) -> None:
    prose = "word " * 50
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>Landmark Scope</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/><itemref idref="ch2"/></spine>\n'
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops"><body>\n'
        '  <nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml#s1">F1 S1</a></li>'
        '<li><a href="ch1.xhtml#s2">F1 S2</a></li>'
        '<li><a href="ch2.xhtml#s1">F2 S1</a></li>'
        '<li><a href="ch2.xhtml#s2">F2 S2</a></li>'
        "</ol></nav>\n"
        '  <nav epub:type="landmarks"><ol>'
        '<li><a epub:type="cover" href="ch1.xhtml">Cover</a></li>'
        '<li><a epub:type="index" href="ch2.xhtml#s2">Index</a></li>'
        "</ol></nav>\n"
        "</body></html>\n"
    )
    split_body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>\n'
        f'  <section id="s1"><p>{prose}</p></section>\n'
        f'  <section id="s2"><p>{prose}</p></section>\n'
        "</body></html>\n"
    ).encode()
    epub_path = _build_minimal_epub(
        tmp_path / "landmarks.epub",
        opf_xml=opf,
        nav_xml=nav,
        extra_files={"OEBPS/ch1.xhtml": split_body, "OEBPS/ch2.xhtml": split_body},
    )
    res = parse_epub(epub_path)
    by_title = {ch.title: ch for ch in res.chapters}
    assert by_title["F1 S1"].skip_reasons == ["cover"]
    assert by_title["F1 S2"].skip_reasons == []
    assert by_title["F2 S1"].skip_reasons == []
    assert by_title["F2 S2"].skip_reasons == ["index"]
