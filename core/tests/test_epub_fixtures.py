"""Tests for synthetic EPUB fixture generation and public-domain fixtures."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import tomllib
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
EPUB_DEFS_DIR = DATA_DIR / "epub_defs"
EPUB_OUT_DIR = DATA_DIR / "epub"
PUBLIC_DOMAIN_DIR = DATA_DIR / "public_domain"
SOURCES_MD = DATA_DIR / "SOURCES.md"
MAKE_EPUBS_PATH = DATA_DIR / "make_epubs.py"

UTF8_FILENAME_FLAG = 0x800
SKIP_REASON_ORDER = ("cover", "toc", "copyright-page", "index", "short")


class _BodyTextExtractor(HTMLParser):
    """Extract normalized D2 text from ``<body>`` or an anchor element."""

    def __init__(self, target_id: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self._target_id = target_id
        self._capture_depth = 0 if target_id is not None else -1
        self._in_body = False
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        local = tag.lower().rsplit(":", 1)[-1]
        if self._target_id is None:
            if local == "body":
                self._in_body = True
        elif self._capture_depth > 0:
            self._capture_depth += 1
        elif dict(attrs).get("id") == self._target_id:
            self._capture_depth = 1
        if local in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        local = tag.lower().rsplit(":", 1)[-1]
        if local in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._target_id is None:
            if local == "body":
                self._in_body = False
        elif self._capture_depth > 0:
            self._capture_depth -= 1

    def handle_data(self, data: str) -> None:
        capturing = self._in_body if self._target_id is None else self._capture_depth > 0
        if capturing and self._skip_depth == 0:
            self.chunks.append(data)


def _d2_char_count(epub_path: Path, chapter_href: str) -> int:
    doc_href, _, fragment = chapter_href.partition("#")
    with zipfile.ZipFile(epub_path, "r") as zf:
        xhtml = zf.read(doc_href).decode("utf-8")
    extractor = _BodyTextExtractor(fragment or None)
    extractor.feed(xhtml)
    extractor.close()
    normalized = re.sub(r"\s+", " ", "".join(extractor.chunks)).strip()
    return len(normalized)


def _load_make_epubs() -> Any:
    spec = importlib.util.spec_from_file_location("make_epubs", MAKE_EPUBS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_at_least_ten_definitions_exist() -> None:
    defs = sorted(EPUB_DEFS_DIR.glob("*.toml"))
    assert len(defs) >= 10


def test_no_orphan_epubs() -> None:
    def_stems = {path.stem for path in EPUB_DEFS_DIR.glob("*.toml")}
    epub_stems = {path.stem for path in EPUB_OUT_DIR.glob("*.epub")}
    assert epub_stems == def_stems


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    make_epubs = _load_make_epubs()
    defs = sorted(EPUB_DEFS_DIR.glob("*.toml"))
    assert defs

    first_run = tmp_path / "run1"
    second_run = tmp_path / "run2"
    make_epubs.generate_all(EPUB_DEFS_DIR, first_run)
    make_epubs.generate_all(EPUB_DEFS_DIR, second_run)

    for def_path in defs:
        epub_name = f"{def_path.stem}.epub"
        committed_path = EPUB_OUT_DIR / epub_name
        assert committed_path.is_file(), f"Missing committed EPUB fixture: {committed_path}"

        committed_bytes = committed_path.read_bytes()
        run1_bytes = (first_run / epub_name).read_bytes()
        run2_bytes = (second_run / epub_name).read_bytes()

        assert run1_bytes == run2_bytes
        assert run1_bytes == committed_bytes


def test_every_synthetic_epub_is_valid_zip_with_stored_mimetype_first() -> None:
    epubs = sorted(EPUB_OUT_DIR.glob("*.epub"))
    assert len(epubs) >= 10

    for epub_path in epubs:
        with zipfile.ZipFile(epub_path, "r") as zf:
            assert zf.testzip() is None
            infos = zf.infolist()
            assert infos, f"{epub_path.name} is empty"
            first = infos[0]
            assert first.filename == "mimetype"
            assert first.compress_type == zipfile.ZIP_STORED
            assert first.extra == b""
            assert zf.read("mimetype") == b"application/epub+zip"
            for info in infos:
                assert info.compress_type == zipfile.ZIP_STORED


def test_every_public_domain_epub_is_valid_zip_with_stored_mimetype_first() -> None:
    epubs = sorted(PUBLIC_DOMAIN_DIR.glob("*.epub"))
    assert len(epubs) == 2

    for epub_path in epubs:
        with zipfile.ZipFile(epub_path, "r") as zf:
            assert zf.testzip() is None
            infos = zf.infolist()
            assert infos
            first = infos[0]
            assert first.filename == "mimetype"
            assert first.compress_type == zipfile.ZIP_STORED
            assert zf.read("mimetype") == b"application/epub+zip"


def test_non_ascii_fixture_uses_utf8_zip_flag() -> None:
    epub_path = EPUB_OUT_DIR / "08_non_ascii_utf8.epub"
    assert epub_path.is_file()
    with zipfile.ZipFile(epub_path, "r") as zf:
        non_ascii = [info for info in zf.infolist() if not info.filename.isascii()]
        assert non_ascii
        for info in non_ascii:
            assert info.flag_bits & UTF8_FILENAME_FLAG


def test_definitions_have_explicit_expectations() -> None:
    for def_path in sorted(EPUB_DEFS_DIR.glob("*.toml")):
        with def_path.open("rb") as fh:
            data = tomllib.load(fh)
        assert "meta" in data and "epub" in data and "expected" in data
        exp = data["expected"]
        assert exp["status"] in {"ok", "epub_drm", "epub_invalid"}
        assert isinstance(exp["title"], str) and exp["title"]
        assert isinstance(exp["authors"], list) and exp["authors"]
        assert isinstance(exp["language"], str) and exp["language"]
        assert isinstance(exp["has_cover"], bool)
        if exp["status"] == "ok":
            epub_path = EPUB_OUT_DIR / f"{def_path.stem}.epub"
            chapters = exp["chapters"]
            assert chapters
            for ch in chapters:
                assert ch["paragraphs"]
                char_len = _d2_char_count(epub_path, ch["href"])
                reasons = ch["skip_reasons"]
                assert [r for r in SKIP_REASON_ORDER if r in reasons] == reasons
                if ch["href"].endswith("boundary_199.xhtml"):
                    assert char_len == 199
                    assert ch["suggested_skip"] is True
                    assert reasons == ["short"]
                elif ch["href"].endswith("boundary_200.xhtml"):
                    assert char_len == 200
                    assert ch["suggested_skip"] is False
                    assert reasons == []
                elif not ch["suggested_skip"]:
                    assert char_len >= 250, (
                        f"{def_path.name} chapter {ch['title']!r} has <250 chars "
                        f"({char_len}) under D2 rule"
                    )
                if char_len < 200:
                    assert ch["suggested_skip"] is True
                    assert "short" in reasons


def test_font_obfuscation_fixture_lists_both_algorithms() -> None:
    epub_path = EPUB_OUT_DIR / "09_font_obfuscation_ok.epub"
    with zipfile.ZipFile(epub_path, "r") as zf:
        enc_xml = zf.read("META-INF/encryption.xml").decode("utf-8")
    assert "http://www.idpf.org/2008/embedding" in enc_xml
    assert "http://ns.adobe.com/pdf/enc#RC" in enc_xml


def test_epub3_with_ncx_has_differing_titles() -> None:
    with (EPUB_DEFS_DIR / "01_epub3_basic.toml").open("rb") as fh:
        spec = tomllib.load(fh)
    epub_path = EPUB_OUT_DIR / "01_epub3_basic.epub"
    with zipfile.ZipFile(epub_path, "r") as zf:
        nav_xml = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        ncx_xml = zf.read("OEBPS/toc.ncx").decode("utf-8")
    for ch, ncx_entry in zip(spec["expected"]["chapters"], spec["ncx"], strict=True):
        assert ch["title"] in nav_xml
        assert ncx_entry["title"] in ncx_xml
        assert ch["title"] != ncx_entry["title"]


def test_suggested_skips_clean_mechanisms() -> None:
    epub_path = EPUB_OUT_DIR / "07_suggested_skips.epub"
    with zipfile.ZipFile(epub_path, "r") as zf:
        nav_xml = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        cover_xml = zf.read("OEBPS/cover.xhtml").decode("utf-8")
        copyright_xml = zf.read("OEBPS/copyright.xhtml").decode("utf-8")
        toc_xml = zf.read("OEBPS/toc.xhtml").decode("utf-8")
        index_xml = zf.read("OEBPS/index.xhtml").decode("utf-8")

    # cover and copyright-page marked ONLY via landmarks
    assert 'epub:type="cover"' in nav_xml and 'epub:type="cover"' not in cover_xml
    assert 'epub:type="copyright-page"' in nav_xml
    assert 'epub:type="copyright-page"' not in copyright_xml
    # toc and index marked ONLY via in-document epub:type (not in landmarks)
    assert 'href="toc.xhtml"' in nav_xml
    assert 'epub:type="toc" href="toc.xhtml"' not in nav_xml
    assert 'epub:type="toc"' in toc_xml
    assert 'epub:type="index"' not in nav_xml
    assert 'epub:type="index"' in index_xml


def test_public_domain_hashes_and_gutenberg_notice() -> None:
    sources_text = SOURCES_MD.read_text(encoding="utf-8")
    assert "Ebook #43" in sources_text
    assert "Ebook #46" in sources_text
    assert "Project Gutenberg License (section 1.E)" in sources_text
    assert "never shipped in Skald installers or releases" in sources_text

    epubs = sorted(PUBLIC_DOMAIN_DIR.glob("*.epub"))
    assert len(epubs) == 2

    for epub_path in epubs:
        digest = hashlib.sha256(epub_path.read_bytes()).hexdigest()
        assert epub_path.name in sources_text
        assert digest in sources_text
        with zipfile.ZipFile(epub_path, "r") as zf:
            combined = b"".join(
                zf.read(name) for name in zf.namelist() if name.endswith((".html", ".xhtml"))
            ).decode("utf-8", errors="replace")
            assert "Project Gutenberg" in combined
