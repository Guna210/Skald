"""Tests for synthetic EPUB fixture generation and public-domain fixtures."""

from __future__ import annotations

import hashlib
import importlib.util
import tomllib
import zipfile
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
EPUB_DEFS_DIR = DATA_DIR / "epub_defs"
EPUB_OUT_DIR = DATA_DIR / "epub"
PUBLIC_DOMAIN_DIR = DATA_DIR / "public_domain"
SOURCES_MD = DATA_DIR / "SOURCES.md"
MAKE_EPUBS_PATH = DATA_DIR / "make_epubs.py"

UTF8_FILENAME_FLAG = 0x800


def _load_make_epubs() -> Any:
    spec = importlib.util.spec_from_file_location("make_epubs", MAKE_EPUBS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_at_least_ten_definitions_exist() -> None:
    defs = sorted(EPUB_DEFS_DIR.glob("*.toml"))
    assert len(defs) >= 10


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
            chapters = exp["chapters"]
            assert chapters
            for ch in chapters:
                assert ch["paragraphs"]
                text_len = sum(len(p) for p in ch["paragraphs"])
                if not ch["suggested_skip"]:
                    assert text_len >= 200, (
                        f"{def_path.name} chapter {ch['title']!r} has <200 chars "
                        f"({text_len}) but suggested_skip=false"
                    )


def test_public_domain_hashes_and_gutenberg_notice() -> None:
    sources_text = SOURCES_MD.read_text(encoding="utf-8")
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
