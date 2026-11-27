"""Golden text-pipeline tests (SPEC V2, T02.8)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from skald_core.book import load_epub_book
from skald_core.rpc.server import SkaldError
from skald_core.schemas.models import Chunk
from skald_core.text import apply_lexicon, chunk_paragraph, normalize

TESTS_DIR = Path(__file__).resolve().parent
DATA_DIR = TESTS_DIR / "data"
EPUB_DEFS_DIR = DATA_DIR / "epub_defs"
EPUB_OUT_DIR = DATA_DIR / "epub"
PUBLIC_DOMAIN_DIR = DATA_DIR / "public_domain"
GOLDEN_DIR = TESTS_DIR / "golden"
GOLDEN_JSON_PATH = GOLDEN_DIR / "text_golden.json"
MAKE_GOLDEN_SCRIPT = GOLDEN_DIR / "make_golden_text.py"
REPO_ROOT = TESTS_DIR.parents[1]
REVIEW_MD_PATH = REPO_ROOT / "docs" / "verification" / "text-review.md"

MAX_CHARS = 400
_WS_RUN_RE = re.compile(r"\s+")


def _synthetic_fixture_ids() -> list[str]:
    return [path.stem for path in sorted(EPUB_DEFS_DIR.glob("*.toml"))]


def _assert_strict_reconstruction(text: str, chunks: list[Chunk]) -> None:
    expected = _WS_RUN_RE.sub(" ", text).strip()
    pos = 0
    rebuilt: list[str] = []
    for idx, ch in enumerate(chunks):
        assert ch.text and ch.text == ch.text.strip()
        assert len(ch.text) <= MAX_CHARS
        if idx > 0:
            if pos < len(expected) and expected[pos] == " ":
                rebuilt.append(" ")
                pos += 1
            else:
                rebuilt.append("")
        assert expected.startswith(ch.text, pos), (
            f"Chunk {idx} {ch.text!r} mismatches {expected[pos : pos + 40]!r} at pos {pos}"
        )
        pos += len(ch.text)
        rebuilt.append(ch.text)
    assert pos == len(expected)
    assert "".join(rebuilt) == expected


@pytest.mark.parametrize("fixture_id", _synthetic_fixture_ids())
def test_synthetic_fixtures_full_text_pipeline_against_toml(fixture_id: str) -> None:
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

    book = load_epub_book(epub_path)
    assert book.title == exp["title"]
    assert book.authors == exp["authors"]
    assert book.language == exp["language"]

    expected_chapters = exp["chapters"]
    assert len(book.chapters) == len(expected_chapters)

    for ch, want in zip(book.chapters, expected_chapters, strict=True):
        assert ch.title == want["title"]
        assert ch.linear is want["linear"]
        assert ch.skip_reasons == want["skip_reasons"]
        assert ch.included is (want["linear"] and not want["suggested_skip"])
        assert [p.text for p in ch.paragraphs] == want["paragraphs"]

        for p in ch.paragraphs:
            synth_text, counts = apply_lexicon(normalize(p.text), [])
            assert counts == []
            res = chunk_paragraph(ch.id, p.id, synth_text, book.language, max_chars=MAX_CHARS)
            assert len(res.chunks) >= 1
            _assert_strict_reconstruction(synth_text, res.chunks)


@pytest.mark.parametrize(
    "epub_name",
    ["pg43-jekyll-hyde.epub", "pg46-christmas-carol.epub"],
)
def test_public_domain_epubs_match_golden_json(epub_name: str) -> None:
    assert GOLDEN_JSON_PATH.is_file(), f"Missing golden file: {GOLDEN_JSON_PATH}"
    golden = json.loads(GOLDEN_JSON_PATH.read_text(encoding="utf-8"))
    assert golden["max_chars"] == MAX_CHARS
    assert set(golden["books"]) == {"pg43-jekyll-hyde.epub", "pg46-christmas-carol.epub"}

    expected_book = golden["books"][epub_name]
    epub_path = PUBLIC_DOMAIN_DIR / epub_name
    book = load_epub_book(epub_path)

    assert book.title == expected_book["title"]
    assert book.authors == expected_book["authors"]
    assert book.language == expected_book["language"]

    actual_chapters: list[dict[str, Any]] = []
    for ch in book.chapters:
        display_char_count = sum(len(p.text) for p in ch.paragraphs)
        chunk_count = 0
        for p in ch.paragraphs:
            synth_text, counts = apply_lexicon(normalize(p.text), [])
            assert counts == []
            res = chunk_paragraph(ch.id, p.id, synth_text, book.language, max_chars=MAX_CHARS)
            _assert_strict_reconstruction(synth_text, res.chunks)
            chunk_count += len(res.chunks)
        actual_chapters.append(
            {
                "chunk_count": chunk_count,
                "display_char_count": display_char_count,
                "paragraph_count": len(ch.paragraphs),
                "title": ch.title,
            }
        )

    assert actual_chapters == expected_book["chapters"]


def test_make_golden_text_help_refuses_overwrite_and_matches_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    help_proc = subprocess.run(
        [sys.executable, str(MAKE_GOLDEN_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert help_proc.returncode == 0
    assert "--force" in help_proc.stdout
    assert "Orchestrator approval" in help_proc.stdout
    assert "C3.3" in help_proc.stdout

    # Refuses to overwrite existing committed golden file without --force.
    refuse_proc = subprocess.run(
        [sys.executable, str(MAKE_GOLDEN_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert refuse_proc.returncode != 0
    assert "--force" in refuse_proc.stderr

    # Regenerating into temporary paths produces identical LF UTF-8 bytes.
    sys.path.insert(0, str(GOLDEN_DIR))
    try:
        import make_golden_text  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    tmp_golden = tmp_path / "text_golden.json"
    tmp_review = tmp_path / "text-review.md"
    monkeypatch.setattr(make_golden_text, "GOLDEN_PATH", tmp_golden)
    monkeypatch.setattr(make_golden_text, "REVIEW_PATH", tmp_review)

    # First write succeeds; second write without --force refuses and keeps original bytes.
    assert make_golden_text.main([]) == 0
    sentinel = b'{"sentinel": true}\n'
    tmp_golden.write_bytes(sentinel)
    assert make_golden_text.main([]) == 1
    assert tmp_golden.read_bytes() == sentinel

    # --force overwrites and matches committed artifacts byte-for-byte.
    assert make_golden_text.main(["--force"]) == 0
    golden_bytes = tmp_golden.read_bytes()
    review_bytes = tmp_review.read_bytes()
    assert b"\r\n" not in golden_bytes
    assert b"\r\n" not in review_bytes
    assert golden_bytes == GOLDEN_JSON_PATH.read_bytes()
    assert review_bytes == REVIEW_MD_PATH.read_bytes()

    review_text = review_bytes.decode("utf-8")
    assert "## What to look for" in review_text
    assert "## Known issues" in review_text
    assert "pg43-jekyll-hyde.epub" in review_text
    assert "pg46-christmas-carol.epub" in review_text
