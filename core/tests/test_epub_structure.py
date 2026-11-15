"""Tests for EPUB container, spine, navigation, metadata, DRM, and safety (T02.2)."""

from __future__ import annotations

import logging
import tomllib
import zipfile
from pathlib import Path

import pytest

from skald_core.book import EpubStructure, parse_epub
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
        assert len(result.cover.data) > 0
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


@pytest.mark.parametrize(
    "filename",
    ["pg43-jekyll-hyde.epub", "pg46-christmas-carol.epub"],
)
def test_public_domain_gutenberg_smoke(filename: str) -> None:
    epub_path = PUBLIC_DOMAIN_DIR / filename
    result = parse_epub(epub_path)

    assert result.metadata.title
    assert result.metadata.authors
    assert result.metadata.language
    assert len(result.chapters) > 0
    for ch in result.chapters:
        assert ch.title
        assert ch.href


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


def test_uncompressed_size_over_500mb_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epub_path = _build_minimal_epub(tmp_path / "huge.epub")

    orig_infolist = zipfile.ZipFile.infolist

    def _huge_infolist(self: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        infos = orig_infolist(self)
        if infos:
            infos[0].file_size = 500 * 1024 * 1024 + 1
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", _huge_infolist)
    with pytest.raises(SkaldError) as exc_info:
        parse_epub(epub_path)
    assert exc_info.value.kind == "epub_invalid"
    assert "500 MB" in exc_info.value.message


def test_billion_laughs_entity_expansion_rejected_safely(tmp_path: Path) -> None:
    billion_laughs_opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE package [\n"
        '  <!ENTITY lol "lol">\n'
        '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
        '  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">\n'
        '  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">\n'
        '  <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">\n'
        '  <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">\n'
        '  <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">\n'
        '  <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">\n'
        "]>\n"
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:0000</dc:identifier>\n'
        "    <dc:title>&lol9;</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        "  <spine>\n"
        '    <itemref idref="ch1"/>\n'
        "  </spine>\n"
        "</package>\n"
    )
    epub_path = _build_minimal_epub(tmp_path / "laughs.epub", opf_xml=billion_laughs_opf)
    # With resolve_entities=False and load_dtd=False, lxml must not expand entities.
    # It either raises XMLSyntaxError (-> epub_invalid) or leaves the title empty/unexpanded.
    try:
        result = parse_epub(epub_path)
        assert "lol" * 10 not in result.metadata.title
    except SkaldError as exc:
        assert exc.kind == "epub_invalid"


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
