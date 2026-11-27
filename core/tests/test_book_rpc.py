"""RPC-level tests for `book.*` and `lexicon.*` through JobManager (T02.7)."""

from __future__ import annotations

import io
import json
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from skald_core.book import rpc as book_rpc
from skald_core.book import xhtml as xhtml_mod
from skald_core.jobs import JobManager
from skald_core.rpc import APP_ERROR, INVALID_PARAMS, RpcServer
from skald_core.rpc.methods import register_all
from skald_core.schemas import Book, BookUpdateResult, Lexicon
from skald_core.text import apply_lexicon, chunk_paragraph, normalize

DATA_DIR = Path(__file__).resolve().parent / "data"
EPUB_OUT_DIR = DATA_DIR / "epub"
PUBLIC_DOMAIN_DIR = DATA_DIR / "public_domain"


class _RecordingNotifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.finished_events: dict[str, threading.Event] = {}

    def __call__(self, method: str, params: BaseModel | dict[str, Any]) -> None:
        payload = params.model_dump(mode="json") if isinstance(params, BaseModel) else dict(params)
        with self._lock:
            self.events.append((method, payload))
            if method == "job.finished":
                ev = self.finished_events.setdefault(payload["job_id"], threading.Event())
                ev.set()

    def wait_finished(self, job_id: str, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            ev = self.finished_events.setdefault(job_id, threading.Event())
        assert ev.wait(timeout=timeout), f"Timed out waiting for job.finished on {job_id}"
        with self._lock:
            matches = [p for m, p in self.events if m == "job.finished" and p["job_id"] == job_id]
        assert len(matches) == 1
        return matches[0]

    def progress_for(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [p for m, p in self.events if m == "job.progress" and p["job_id"] == job_id]

    def logs_for(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [p for m, p in self.events if m == "job.log" and p["job_id"] == job_id]


@pytest.fixture
def rpc_env() -> Iterator[tuple[RpcServer, JobManager, _RecordingNotifier]]:
    notifier = _RecordingNotifier()
    stdin = io.BytesIO()
    stdout = io.BytesIO()
    server = RpcServer(stdin=stdin, stdout=stdout)
    manager = JobManager(max_workers=2, notify_fn=notifier, progress_interval_s=0.0)
    register_all(server, job_manager=manager)
    try:
        yield server, manager, notifier
    finally:
        manager.shutdown(timeout=2.0)


def _rpc_call(
    server: RpcServer,
    method: str,
    params: dict[str, Any] | None = None,
    req_id: int = 1,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    resp = server.handle_line(json.dumps(payload))
    assert resp is not None
    return resp


def _create_project(server: RpcServer, project_dir: Path, name: str = "Test Book") -> None:
    resp = _rpc_call(
        server,
        "project.create",
        {"path": str(project_dir), "name": name, "base_seed": 42},
    )
    assert "result" in resp, resp


def _import_book(
    server: RpcServer,
    notifier: _RecordingNotifier,
    source_path: Path,
) -> dict[str, Any]:
    resp = _rpc_call(server, "book.import", {"source_path": str(source_path)})
    assert "result" in resp, resp
    job_id = resp["result"]["job_id"]
    return notifier.wait_finished(job_id)


def _build_epub_with_cover(
    dest: Path,
    *,
    cover_href: str,
    cover_media_type: str | None,
    cover_bytes: bytes,
) -> Path:
    media_attr = f' media-type="{cover_media_type}"' if cover_media_type is not None else ""
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:1234</dc:identifier>\n'
        "    <dc:title>Cover Test</dc:title>\n"
        "    <dc:language>en</dc:language>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        f'    <item id="cov" href="{cover_href}"{media_attr} properties="cover-image"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml">Chapter One</a></li>'
        "</ol></nav></body></html>\n"
    )
    ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<body><h1>Chapter One</h1><p>First paragraph of sufficient length for the book.</p>"
        "</body></html>\n"
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles>\n'
        "</container>\n"
    )
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/ch1.xhtml", ch1)
        zf.writestr(f"OEBPS/{cover_href}", cover_bytes)
    return dest


def test_methods_require_open_project(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, _ = rpc_env
    sample_txt = tmp_path / "sample.txt"
    sample_txt.write_text("Hello world.", encoding="utf-8")

    for method, params in [
        ("book.import", {"source_path": str(sample_txt)}),
        ("book.get", None),
        ("book.update", {"language": "en"}),
        ("lexicon.get", None),
        ("lexicon.set", {"rules": []}),
    ]:
        resp = _rpc_call(server, method, params)
        assert resp["error"]["code"] == APP_ERROR
        assert resp["error"]["data"]["kind"] == "project_invalid"


def test_import_epub_fixture_cover_and_progress(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env
    proj_dir = tmp_path / "epub_proj"
    _create_project(server, proj_dir)

    epub_path = EPUB_OUT_DIR / "01_epub3_basic.epub"
    finished = _import_book(server, notifier, epub_path)
    assert finished["status"] == "succeeded", finished

    book = Book.model_validate(finished["result"])
    assert book.title == "The North Wind"
    assert book.source_path == "source/original.epub"
    assert book.cover_path == "source/cover.png"
    assert (proj_dir / "source" / "original.epub").read_bytes() == epub_path.read_bytes()
    assert (proj_dir / "source" / "cover.png").is_file()
    assert (proj_dir / "book.json").is_file()
    assert all(p.sentences == [] for ch in book.chapters for p in ch.paragraphs)

    progress = notifier.progress_for(finished["job_id"])
    assert any(p["stage"] == "extract" for p in progress)
    assert progress[-1]["fraction"] == 1.0

    got = _rpc_call(server, "book.get")
    assert Book.model_validate(got["result"]) == book


def test_import_public_domain_epub_txt_and_markdown(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env

    # 1. Public-domain EPUB
    pd_proj = tmp_path / "pd_proj"
    _create_project(server, pd_proj, "PD Book")
    pd_epub = PUBLIC_DOMAIN_DIR / "pg43-jekyll-hyde.epub"
    fin_pd = _import_book(server, notifier, pd_epub)
    assert fin_pd["status"] == "succeeded", fin_pd
    pd_book = Book.model_validate(fin_pd["result"])
    assert pd_book.source_path == "source/original.epub"
    assert len(pd_book.chapters) > 1
    assert all(p.sentences == [] for ch in pd_book.chapters for p in ch.paragraphs)

    # 2. TXT with case-insensitive suffix and guessed encoding warning
    txt_proj = tmp_path / "txt_proj"
    _create_project(server, txt_proj, "TXT Book")
    txt_file = tmp_path / "Story.TXT"
    txt_file.write_bytes("Chapter 1\n\n“Smart quotes” — cp1252 café.".encode("cp1252"))
    fin_txt = _import_book(server, notifier, txt_file)
    assert fin_txt["status"] == "succeeded", fin_txt
    txt_book = Book.model_validate(fin_txt["result"])
    assert txt_book.source_path == "source/original.txt"
    assert txt_book.cover_path is None
    assert (txt_proj / "source" / "original.txt").read_bytes() == txt_file.read_bytes()
    logs = notifier.logs_for(fin_txt["job_id"])
    assert any(log["level"] == "warning" and "cp1252" in log["message"] for log in logs)

    # 3. Markdown (.Markdown) including zero-paragraph chapter from image-only h1
    md_proj = tmp_path / "md_proj"
    _create_project(server, md_proj, "MD Book")
    md_file = tmp_path / "Notes.Markdown"
    md_file.write_text(
        "# ![Cover](cover.png)\n\n## Second Chapter\n\nBody text in second chapter.\n",
        encoding="utf-8",
    )
    fin_md = _import_book(server, notifier, md_file)
    assert fin_md["status"] == "succeeded", fin_md
    md_book = Book.model_validate(fin_md["result"])
    assert md_book.source_path == "source/original.markdown"
    assert md_book.cover_path is None
    assert len(md_book.chapters) == 2
    assert md_book.chapters[0].paragraphs == []
    assert notifier.logs_for(fin_md["job_id"]) == []
    got_md = _rpc_call(server, "book.get")
    assert Book.model_validate(got_md["result"]) == md_book


def test_import_cover_jpeg_and_skip_non_raster_cover(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env

    # JPEG cover -> source/cover.jpg
    jpg_proj = tmp_path / "jpg_proj"
    _create_project(server, jpg_proj)
    jpg_epub = _build_epub_with_cover(
        tmp_path / "jpg.epub",
        cover_href="images/cover.jpeg",
        cover_media_type="image/jpeg",
        cover_bytes=b"\xff\xd8\xff\xe0fakejpeg",
    )
    fin_jpg = _import_book(server, notifier, jpg_epub)
    assert fin_jpg["status"] == "succeeded", fin_jpg
    assert fin_jpg["result"]["cover_path"] == "source/cover.jpg"
    assert (jpg_proj / "source" / "cover.jpg").read_bytes() == b"\xff\xd8\xff\xe0fakejpeg"

    # SVG cover -> skipped (cover_path is None, no source/cover.* created)
    svg_proj = tmp_path / "svg_proj"
    _create_project(server, svg_proj)
    svg_epub = _build_epub_with_cover(
        tmp_path / "svg.epub",
        cover_href="images/cover.svg",
        cover_media_type="image/svg+xml",
        cover_bytes=b"<svg xmlns='http://www.w3.org/2000/svg'/>",
    )
    fin_svg = _import_book(server, notifier, svg_epub)
    assert fin_svg["status"] == "succeeded", fin_svg
    assert fin_svg["result"]["cover_path"] is None
    assert not any((svg_proj / "source").glob("cover.*"))


def test_import_errors_unsupported_twice_and_missing_book_get(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env
    proj_dir = tmp_path / "err_proj"
    _create_project(server, proj_dir)

    # book.get before any import -> project_invalid
    missing_get = _rpc_call(server, "book.get")
    assert missing_get["error"]["data"]["kind"] == "project_invalid"

    # Unsupported suffix -> unsupported_format, no files written
    pdf_file = tmp_path / "book.pdf"
    pdf_file.write_bytes(b"%PDF-1.7")
    fin_pdf = _import_book(server, notifier, pdf_file)
    assert fin_pdf["status"] == "failed"
    assert fin_pdf["error"]["data"]["kind"] == "unsupported_format"
    assert not (proj_dir / "book.json").exists()
    assert not (proj_dir / "source").exists()

    # Valid import succeeds
    txt_file = tmp_path / "book.txt"
    txt_file.write_text("Chapter 1\n\nFirst paragraph.", encoding="utf-8")
    fin_ok = _import_book(server, notifier, txt_file)
    assert fin_ok["status"] == "succeeded"

    # Importing a second time -> project_invalid ("This project already has a book")
    txt2 = tmp_path / "other.txt"
    txt2.write_text("Chapter 1\n\nOther paragraph.", encoding="utf-8")
    fin_dup = _import_book(server, notifier, txt2)
    assert fin_dup["status"] == "failed"
    assert fin_dup["error"]["data"]["kind"] == "project_invalid"
    assert "This project already has a book" in fin_dup["error"]["message"]
    assert (proj_dir / "source" / "original.txt").read_text(encoding="utf-8") == (
        "Chapter 1\n\nFirst paragraph."
    )


def test_import_pause_resume_and_cancel_mid_import_and_retry(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, notifier = rpc_env
    proj_dir = tmp_path / "cancel_proj"
    _create_project(server, proj_dir)

    epub_path = EPUB_OUT_DIR / "01_epub3_basic.epub"
    entered_ch0 = threading.Event()
    release_ch0 = threading.Event()
    orig_load_epub_import = xhtml_mod.load_epub_import

    def gated_epub_import(path: Path | str, on_chapter: Any = None) -> Any:
        def wrapped_on_chapter(idx: int, total: int) -> None:
            if idx == 0:
                entered_ch0.set()
                release_ch0.wait(timeout=5.0)
            if on_chapter is not None:
                on_chapter(idx, total)

        return orig_load_epub_import(path, on_chapter=wrapped_on_chapter)

    monkeypatch.setattr(book_rpc, "load_epub_import", gated_epub_import)

    # Cancel mid-import: pause at chapter 0, then cancel, then release gate.
    resp = _rpc_call(server, "book.import", {"source_path": str(epub_path)})
    job_id = resp["result"]["job_id"]
    assert entered_ch0.wait(timeout=5.0)
    cancel_resp = _rpc_call(server, "job.cancel", {"job_id": job_id})
    assert "result" in cancel_resp
    release_ch0.set()

    fin_cancel = notifier.wait_finished(job_id)
    assert fin_cancel["status"] == "cancelled"
    assert not (proj_dir / "book.json").exists()
    assert not (proj_dir / "source" / "original.epub").exists()
    assert not (proj_dir / "source" / "cover.png").exists()

    # Also test pause/resume mid-import + retry overwriting stale source files if present.
    (proj_dir / "source").mkdir(parents=True, exist_ok=True)
    (proj_dir / "source" / "original.epub").write_bytes(b"stale leftover")
    (proj_dir / "source" / "cover.jpg").write_bytes(b"stale cover")

    entered_ch0.clear()
    release_ch0.clear()
    entered_ch1 = threading.Event()

    def pause_aware_import(path: Path | str, on_chapter: Any = None) -> Any:
        def wrapped(idx: int, total: int) -> None:
            if idx == 0:
                entered_ch0.set()
                release_ch0.wait(timeout=5.0)
            if idx == 1:
                entered_ch1.set()
            if on_chapter is not None:
                on_chapter(idx, total)

        return orig_load_epub_import(path, on_chapter=wrapped)

    monkeypatch.setattr(book_rpc, "load_epub_import", pause_aware_import)
    resp2 = _rpc_call(server, "book.import", {"source_path": str(epub_path)})
    job_id2 = resp2["result"]["job_id"]
    assert entered_ch0.wait(timeout=5.0)
    pause_resp = _rpc_call(server, "job.pause", {"job_id": job_id2})
    assert pause_resp["result"]["status"] == "paused"
    release_ch0.set()

    # Worker blocks at chapter 0's ctx.checkpoint() and does not reach chapter 1 while paused.
    assert not entered_ch1.wait(timeout=0.05)
    assert _rpc_call(server, "job.status", {"job_id": job_id2})["result"]["status"] == "paused"
    resume_resp = _rpc_call(server, "job.resume", {"job_id": job_id2})
    assert resume_resp["result"]["status"] == "running"
    assert entered_ch1.wait(timeout=5.0)

    fin_ok = notifier.wait_finished(job_id2)
    assert fin_ok["status"] == "succeeded", fin_ok
    assert (proj_dir / "source" / "original.epub").read_bytes() == epub_path.read_bytes()
    assert not (proj_dir / "source" / "cover.jpg").exists()
    assert (proj_dir / "source" / "cover.png").is_file()


def _paragraph_chunk_ids(book: Book, rules: list[Any] | None = None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ch in book.chapters:
        for p in ch.paragraphs:
            synth, _ = apply_lexicon(normalize(p.text), rules or [])
            res = chunk_paragraph(ch.id, p.id, synth, book.language, max_chars=400)
            out[p.id] = [c.id for c in res.chunks]
    return out


def test_import_update_reopen_roundtrip_and_only_edited_chunk_ids_change(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env
    proj_dir = tmp_path / "roundtrip_proj"
    _create_project(server, proj_dir, "Round Trip")

    epub_path = EPUB_OUT_DIR / "01_epub3_basic.epub"
    fin = _import_book(server, notifier, epub_path)
    assert fin["status"] == "succeeded"

    book_before = Book.model_validate(_rpc_call(server, "book.get")["result"])
    chunks_before = _paragraph_chunk_ids(book_before)

    target_ch = book_before.chapters[1]
    edited_p = book_before.chapters[0].paragraphs[1]
    untouched_ids = [
        p.id for ch in book_before.chapters for p in ch.paragraphs if p.id != edited_p.id
    ]
    assert len(untouched_ids) >= 5

    new_text = "Clara adjusted her dark woollen scarf and watched the beacon fade."
    upd_resp = _rpc_call(
        server,
        "book.update",
        {
            "chapters": [{"id": target_ch.id, "included": False}],
            "paragraphs": [{"id": edited_p.id, "text": new_text}],
            "language": "en-GB",
        },
    )
    assert "result" in upd_resp, upd_resp
    upd = BookUpdateResult.model_validate(upd_resp["result"])
    assert upd.chapter_ids == [target_ch.id]
    assert upd.paragraph_ids == [edited_p.id]

    # Partial patch without language keeps "en-GB" intact.
    upd2 = _rpc_call(
        server,
        "book.update",
        {"chapters": [{"id": target_ch.id, "included": False}]},
    )
    assert upd2["result"] == {"chapter_ids": [], "paragraph_ids": []}

    # Reopen the project and verify exact round-trip.
    open_resp = _rpc_call(server, "project.open", {"path": str(proj_dir)})
    assert "result" in open_resp, open_resp
    book_after = Book.model_validate(_rpc_call(server, "book.get")["result"])

    assert book_after.language == "en-GB"
    assert book_after.chapters[1].included is False
    # Paragraph IDs are NEVER recomputed on edit; sentences remain empty.
    assert book_after.chapters[0].paragraphs[1].id == edited_p.id
    assert book_after.chapters[0].paragraphs[1].text == new_text
    assert all(p.sentences == [] for ch in book_after.chapters for p in ch.paragraphs)

    # Only the edited paragraph's chunk IDs differ.
    chunks_after = _paragraph_chunk_ids(book_after)
    assert chunks_after[edited_p.id] != chunks_before[edited_p.id]
    for p_id in untouched_ids:
        assert chunks_after[p_id] == chunks_before[p_id]

    # Explicit language=null clears language back to None.
    _rpc_call(server, "book.update", {"language": None})
    assert Book.model_validate(_rpc_call(server, "book.get")["result"]).language is None


def test_book_update_validation_and_atomicity(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env
    proj_dir = tmp_path / "update_valid_proj"
    _create_project(server, proj_dir)

    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("Chapter 1\n\nParagraph one.\n\nParagraph two.", encoding="utf-8")
    assert _import_book(server, notifier, txt_file)["status"] == "succeeded"

    book_orig = Book.model_validate(_rpc_call(server, "book.get")["result"])
    ch_id = book_orig.chapters[0].id
    p1_id = book_orig.chapters[0].paragraphs[1].id

    # Unknown chapter id -> -32602, nothing applied
    r_bad_ch = _rpc_call(
        server,
        "book.update",
        {
            "chapters": [{"id": "ch_unknown", "included": True}],
            "paragraphs": [{"id": p1_id, "text": "Should not apply"}],
            "language": "fr-FR",
        },
    )
    assert r_bad_ch["error"]["code"] == INVALID_PARAMS

    # Unknown paragraph id -> -32602, nothing applied
    r_bad_p = _rpc_call(
        server,
        "book.update",
        {
            "chapters": [{"id": ch_id, "included": True}],
            "paragraphs": [
                {"id": p1_id, "text": "Should not apply"},
                {"id": "p_unknown", "text": "Missing"},
            ],
        },
    )
    assert r_bad_p["error"]["code"] == INVALID_PARAMS

    # Empty or whitespace-only text -> -32602
    for blank in ("", "   ", "\t\n"):
        r_blank = _rpc_call(
            server,
            "book.update",
            {"paragraphs": [{"id": p1_id, "text": blank}]},
        )
        assert r_blank["error"]["code"] == INVALID_PARAMS

    # Invalid language tags -> -32602
    for bad_lang in ("", "e", "english", "en_US", "en-1", "en-123456789"):
        r_lang = _rpc_call(
            server,
            "book.update",
            {"paragraphs": [{"id": p1_id, "text": "No apply"}], "language": bad_lang},
        )
        assert r_lang["error"]["code"] == INVALID_PARAMS

    # Verify disk/book state was never partially mutated
    assert Book.model_validate(_rpc_call(server, "book.get")["result"]) == book_orig

    # Valid BCP-47 tags succeed
    for good_lang in ("en", "en-US", "zh-Hans-CN", "pt-br"):
        r_good = _rpc_call(server, "book.update", {"language": good_lang})
        assert "result" in r_good, (good_lang, r_good)


def test_lexicon_get_set_live_counts_duplicates_and_caps(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env
    proj_dir = tmp_path / "lex_proj"
    _create_project(server, proj_dir)

    # Empty before lexicon.set
    empty_lex = Lexicon.model_validate(_rpc_call(server, "lexicon.get")["result"])
    assert empty_lex.rules == []

    txt_file = tmp_path / "lex.txt"
    txt_file.write_text(
        "Chapter 1\n\nSkald met Zoë and Skald smiled at Zoe\u0308.",
        encoding="utf-8",
    )
    assert _import_book(server, notifier, txt_file)["status"] == "succeeded"

    # lexicon.set writes lexicon.json without match_count and returns live counts
    set_resp = _rpc_call(
        server,
        "lexicon.set",
        {
            "rules": [
                {"word": "Skald", "replacement": "skahld", "match_count": 999},
                {"word": "Zoë", "replacement": "ZOH-ee"},
                {"word": "Missing", "replacement": "none"},
            ]
        },
    )
    assert "result" in set_resp, set_resp
    lex = Lexicon.model_validate(set_resp["result"])
    assert [(r.word, r.match_count) for r in lex.rules] == [
        ("Skald", 2),
        ("Zoë", 2),
        ("Missing", 0),
    ]

    on_disk = json.loads((proj_dir / "lexicon.json").read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 1
    assert all("match_count" not in item for item in on_disk["rules"])

    # Counts update live after book.update without touching lexicon.json
    book = Book.model_validate(_rpc_call(server, "book.get")["result"])
    p_id = book.chapters[0].paragraphs[1].id
    _rpc_call(server, "book.update", {"paragraphs": [{"id": p_id, "text": "Skald once."}]})
    lex_after_edit = Lexicon.model_validate(_rpc_call(server, "lexicon.get")["result"])
    assert [(r.word, r.match_count) for r in lex_after_edit.rules] == [
        ("Skald", 1),
        ("Zoë", 0),
        ("Missing", 0),
    ]

    # Duplicate rejection: exact, NFD/NFC normalized, whitespace-padded
    for dup_pair in (
        [{"word": "Skald", "replacement": "a"}, {"word": "Skald", "replacement": "b"}],
        [{"word": "Cafe\u0301", "replacement": "a"}, {"word": "Café", "replacement": "b"}],
        [{"word": "  Skald ", "replacement": "a"}, {"word": "Skald", "replacement": "b"}],
    ):
        dup_resp = _rpc_call(server, "lexicon.set", {"rules": dup_pair})
        assert dup_resp["error"]["code"] == INVALID_PARAMS

    # Same word with different flags is allowed, and replaces the whole list
    diff_flags = _rpc_call(
        server,
        "lexicon.set",
        {
            "rules": [
                {"word": "Skald", "replacement": "a", "case_sensitive": True, "whole_word": True},
                {"word": "Skald", "replacement": "b", "case_sensitive": False, "whole_word": True},
                {"word": "Skald", "replacement": "c", "case_sensitive": True, "whole_word": False},
            ]
        },
    )
    assert "result" in diff_flags, diff_flags
    assert len(diff_flags["result"]["rules"]) == 3

    # Caps: 1000 rules OK, 1001 -> -32602; word <= 100 chars; replacement <= 500 chars
    rules_1000 = [{"word": f"w{i}", "replacement": f"r{i}"} for i in range(1000)]
    assert "result" in _rpc_call(server, "lexicon.set", {"rules": rules_1000})
    rules_1001 = [*rules_1000, {"word": "w1000", "replacement": "r1000"}]
    assert (
        _rpc_call(server, "lexicon.set", {"rules": rules_1001})["error"]["code"] == INVALID_PARAMS
    )

    assert "result" in _rpc_call(
        server,
        "lexicon.set",
        {"rules": [{"word": "a" * 100, "replacement": "b" * 500}]},
    )
    assert (
        _rpc_call(
            server,
            "lexicon.set",
            {"rules": [{"word": "a" * 101, "replacement": "ok"}]},
        )["error"]["code"]
        == INVALID_PARAMS
    )
    assert (
        _rpc_call(
            server,
            "lexicon.set",
            {"rules": [{"word": "ok", "replacement": "b" * 501}]},
        )["error"]["code"]
        == INVALID_PARAMS
    )

    # Empty rules list clears the lexicon
    cleared = Lexicon.model_validate(_rpc_call(server, "lexicon.set", {"rules": []})["result"])
    assert cleared.rules == []
    assert Lexicon.model_validate(_rpc_call(server, "lexicon.get")["result"]).rules == []


def test_drm_epub_dangling_anchor_zero_para_and_corrupt_json_files(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, notifier = rpc_env

    # DRM EPUB fails cleanly with epub_drm and leaves no book.json or source/
    drm_proj = tmp_path / "drm_proj"
    _create_project(server, drm_proj)
    fin_drm = _import_book(server, notifier, EPUB_OUT_DIR / "10_drm_encrypted.epub")
    assert fin_drm["status"] == "failed"
    assert fin_drm["error"]["data"]["kind"] == "epub_drm"
    assert not (drm_proj / "book.json").exists()
    assert not (drm_proj / "source").exists()

    # Dangling EPUB anchor yields a 0-paragraph chapter that round-trips via book.get
    dangling_epub = tmp_path / "dangling.epub"
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:5678</dc:identifier>\n'
        "    <dc:title>Dangling Anchor</dc:title>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        '  <spine><itemref idref="ch1"/></spine>\n'
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<body><nav epub:type="toc"><ol>'
        '<li><a href="ch1.xhtml#s1">First</a></li>'
        '<li><a href="ch1.xhtml#missing">Gone</a></li>'
        "</ol></nav></body></html>\n"
    )
    ch1 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<body><p id="s1">Only paragraph here.</p></body></html>\n'
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles>\n'
        "</container>\n"
    )
    with zipfile.ZipFile(dangling_epub, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/ch1.xhtml", ch1)

    dangling_proj = tmp_path / "dangling_proj"
    _create_project(server, dangling_proj)
    fin_dang = _import_book(server, notifier, dangling_epub)
    assert fin_dang["status"] == "succeeded", fin_dang
    got_dang = Book.model_validate(_rpc_call(server, "book.get")["result"])
    assert len(got_dang.chapters) == 2
    assert got_dang.chapters[1].paragraphs == []

    # Corrupt book.json / lexicon.json -> project_invalid
    (dangling_proj / "book.json").write_text("{corrupt", encoding="utf-8")
    assert _rpc_call(server, "book.get")["error"]["data"]["kind"] == "project_invalid"
    (dangling_proj / "lexicon.json").write_text(json.dumps({"schema_version": 99, "rules": []}))
    assert _rpc_call(server, "lexicon.get")["error"]["data"]["kind"] == "project_invalid"


def test_import_rollback_on_cover_or_book_json_write_failure_and_retry(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, notifier = rpc_env
    epub_path = EPUB_OUT_DIR / "01_epub3_basic.epub"

    # 1. Cover write failure rolls back source/original.* and allows retry.
    proj_cov = tmp_path / "cov_fail_proj"
    _create_project(server, proj_cov)
    orig_write_bytes = book_rpc.atomic_write_bytes

    def fail_cover_write(dest: Path, data: bytes) -> None:
        if dest.name.startswith("cover."):
            raise OSError("simulated cover write failure")
        orig_write_bytes(dest, data)

    monkeypatch.setattr(book_rpc, "atomic_write_bytes", fail_cover_write)
    fin_cov = _import_book(server, notifier, epub_path)
    assert fin_cov["status"] == "failed"
    assert not (proj_cov / "book.json").exists()
    assert not any((proj_cov / "source").glob("*")) if (proj_cov / "source").exists() else True

    monkeypatch.setattr(book_rpc, "atomic_write_bytes", orig_write_bytes)
    fin_cov_retry = _import_book(server, notifier, epub_path)
    assert fin_cov_retry["status"] == "succeeded", fin_cov_retry
    assert (proj_cov / "book.json").is_file()
    assert (proj_cov / "source" / "original.epub").read_bytes() == epub_path.read_bytes()
    assert (proj_cov / "source" / "cover.png").is_file()

    # 2. book.json write failure rolls back source/original.* and cover, and retry succeeds.
    proj_json = tmp_path / "json_fail_proj"
    _create_project(server, proj_json)
    orig_write_json = book_rpc.atomic_write_json

    def fail_book_json_write(dest: Path, data: Any) -> None:
        if dest.name == "book.json":
            raise OSError("simulated book.json write failure")
        orig_write_json(dest, data)

    monkeypatch.setattr(book_rpc, "atomic_write_json", fail_book_json_write)
    fin_json = _import_book(server, notifier, epub_path)
    assert fin_json["status"] == "failed"
    assert not (proj_json / "book.json").exists()
    assert not any((proj_json / "source").glob("*")) if (proj_json / "source").exists() else True

    monkeypatch.setattr(book_rpc, "atomic_write_json", orig_write_json)
    fin_json_retry = _import_book(server, notifier, epub_path)
    assert fin_json_retry["status"] == "succeeded", fin_json_retry
    assert (proj_json / "book.json").is_file()
    assert (proj_json / "source" / "original.epub").read_bytes() == epub_path.read_bytes()
    assert (proj_json / "source" / "cover.png").is_file()


def test_lexicon_set_and_get_without_book_return_zero_match_count(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
) -> None:
    server, _, _ = rpc_env
    proj_dir = tmp_path / "no_book_lex_proj"
    _create_project(server, proj_dir)

    set_resp = _rpc_call(
        server,
        "lexicon.set",
        {
            "rules": [
                {"word": "Skald", "replacement": "skahld"},
                {"word": "Odyssey", "replacement": "AH-duh-see", "match_count": 42},
            ]
        },
    )
    assert "result" in set_resp, set_resp
    lex_set = Lexicon.model_validate(set_resp["result"])
    assert [(r.word, r.match_count) for r in lex_set.rules] == [("Skald", 0), ("Odyssey", 0)]

    get_resp = _rpc_call(server, "lexicon.get")
    assert "result" in get_resp, get_resp
    lex_get = Lexicon.model_validate(get_resp["result"])
    assert [(r.word, r.match_count) for r in lex_get.rules] == [("Skald", 0), ("Odyssey", 0)]


def test_import_cancel_at_later_chapter_and_pre_save_checkpoint(
    rpc_env: tuple[RpcServer, JobManager, _RecordingNotifier],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, notifier = rpc_env
    epub_path = EPUB_OUT_DIR / "01_epub3_basic.epub"
    orig_load_epub_import = xhtml_mod.load_epub_import

    # 1. Cancel at a later chapter (chapter index 2 of 3).
    proj_later = tmp_path / "cancel_ch2_proj"
    _create_project(server, proj_later)
    entered_ch2 = threading.Event()
    release_ch2 = threading.Event()

    def gate_ch2(path: Path | str, on_chapter: Any = None) -> Any:
        def wrapped(idx: int, total: int) -> None:
            if idx == 2:
                entered_ch2.set()
                release_ch2.wait(timeout=5.0)
            if on_chapter is not None:
                on_chapter(idx, total)

        return orig_load_epub_import(path, on_chapter=wrapped)

    monkeypatch.setattr(book_rpc, "load_epub_import", gate_ch2)
    resp1 = _rpc_call(server, "book.import", {"source_path": str(epub_path)})
    job_id1 = resp1["result"]["job_id"]
    assert entered_ch2.wait(timeout=5.0)
    assert "result" in _rpc_call(server, "job.cancel", {"job_id": job_id1})
    release_ch2.set()

    fin1 = notifier.wait_finished(job_id1)
    assert fin1["status"] == "cancelled"
    assert not (proj_later / "book.json").exists()
    assert not (proj_later / "source" / "original.epub").exists()
    assert not (proj_later / "source" / "cover.png").exists()

    # 2. Cancel at the pre-save checkpoint (after extraction returns, before saving).
    proj_presave = tmp_path / "cancel_presave_proj"
    _create_project(server, proj_presave)
    entered_presave = threading.Event()
    release_presave = threading.Event()

    def gate_presave(path: Path | str, on_chapter: Any = None) -> Any:
        result = orig_load_epub_import(path, on_chapter=on_chapter)
        entered_presave.set()
        release_presave.wait(timeout=5.0)
        return result

    monkeypatch.setattr(book_rpc, "load_epub_import", gate_presave)
    resp2 = _rpc_call(server, "book.import", {"source_path": str(epub_path)})
    job_id2 = resp2["result"]["job_id"]
    assert entered_presave.wait(timeout=5.0)
    assert "result" in _rpc_call(server, "job.cancel", {"job_id": job_id2})
    release_presave.set()

    fin2 = notifier.wait_finished(job_id2)
    assert fin2["status"] == "cancelled"
    assert not (proj_presave / "book.json").exists()
    assert not (proj_presave / "source" / "original.epub").exists()
    assert not (proj_presave / "source" / "cover.png").exists()
