"""Tests for model file installer, revisions, project pins, pack cleanup, and license acceptance."""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import logging
import os
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from skald_core import net
from skald_core.catalog import schema as catalog_schema
from skald_core.catalog.client import get_catalog_cache_path
from skald_core.catalog.schema import (
    CatalogFile,
    CatalogHardware,
    CatalogLicense,
    CatalogNotes,
    CatalogSource,
    CpuHardware,
)
from skald_core.jobs import JobManager
from skald_core.models import installer
from skald_core.models.installer import (
    accept_license,
    is_license_accepted,
    licenses_path,
    list_installed_models,
    submit_model_install,
    submit_model_remove,
)
from skald_core.packs.manager import PackManager, PackMetadata, parse_lockfile
from skald_core.project.store import ProjectStore
from skald_core.rpc import RpcServer, SkaldError
from skald_core.rpc.methods import register_all
from skald_core.schemas import (
    AnnotatedCatalogCheckpoint,
    AnnotatedCatalogModel,
    AnnotatedCatalogRevision,
    GpuInfo,
    HardwareInfo,
)
from skald_core.storage import models_dir

_VALID_HF_REF = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "userdata"
    storage_dir = tmp_path / "storage"
    data_dir.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SKALD_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SKALD_STORAGE_DIR", str(storage_dir))
    monkeypatch.setattr(net, "BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(installer, "_REPLACE_RETRY_DELAYS", (0.001, 0.001))


@contextmanager
def _run_server(
    handler_cls: type[http.server.BaseHTTPRequestHandler],
) -> Iterator[str]:
    class _QuietServer(http.server.ThreadingHTTPServer):
        daemon_threads = True

    server = _QuietServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    port = int(server.server_address[1])
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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
                self.finished_events.setdefault(payload["job_id"], threading.Event()).set()

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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_file_entry(path: str, content: bytes, fmt: str = "onnx") -> dict[str, Any]:
    return {
        "path": path,
        "format": fmt,
        "size": len(content),
        "sha256": _sha256_bytes(content),
    }


def _make_revision(
    rev_id: str,
    files: list[dict[str, Any]],
    *,
    bundled: bool = False,
    min_adapter_version: str = "1.0.0",
) -> dict[str, Any]:
    return {
        "id": rev_id,
        "bundled": bundled,
        "min_adapter_version": min_adapter_version,
        "source": {
            "host": "huggingface",
            "repo": "example/tts",
            "ref": _VALID_HF_REF,
        },
        "files": files,
        "changelog": f"Changelog for {rev_id}",
    }


def _make_model(
    model_id: str = "demo",
    *,
    status: str = "active",
    family_adapter: str = "kokoro",
    pack: str | None = None,
    commercial: bool = True,
    license_name: str = "Apache-2.0",
    license_url: str = "https://example.com/apache-2.0",
    acknowledgement: str | None = None,
    checkpoints: list[dict[str, Any]] | None = None,
    hardware: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lic: dict[str, Any] = {
        "name": license_name,
        "url": license_url,
        "commercial": commercial,
    }
    if acknowledgement is not None:
        lic["acknowledgement"] = acknowledgement
    return {
        "id": model_id,
        "name": f"Model {model_id}",
        "status": status,
        "family_adapter": family_adapter,
        "pack": pack,
        "summary": "Test model",
        "license": lic,
        "languages": ["en-us"],
        "capabilities": ["presets"],
        "hardware": (
            {"cpu": {"min_ram_gb": 1.0, "rtf_reference": None}, "cuda": None}
            if hardware is None
            else hardware
        ),
        "notes": {"watermark": None},
        "checkpoints": checkpoints or [],
    }


def _write_catalog_cache(
    models: list[dict[str, Any]],
    *,
    min_app_version: str = "0.1.0",
) -> None:
    payload = {
        "schema_version": 1,
        "min_app_version": min_app_version,
        "updated_at": "2026-11-26",
        "models": models,
    }
    get_catalog_cache_path().write_text(json.dumps(payload), encoding="utf-8")


def _write_adapters(path: Path, versions: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"ADAPTER_VERSIONS = {versions!r}\n", encoding="utf-8")
    return path


def _make_file_server(
    files: dict[str, bytes],
) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            rel = self.path.lstrip("/")
            if rel not in files:
                self.send_response(404)
                self.end_headers()
                return
            data = files[rel]
            range_hdr = self.headers.get("Range")
            if range_hdr and range_hdr.startswith("bytes="):
                start = int(range_hdr[len("bytes=") :].split("-", 1)[0])
                chunk = data[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def _patch_file_urls(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setattr(
        catalog_schema,
        "build_file_url",
        lambda _source, file_path: f"{base_url}/{file_path.lstrip('/')}",
    )


def _write_pin_file(project_dir: Path, records: list[dict[str, Any]]) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    lock_path = project_dir / "models.lock.json"
    lock_path.write_text(
        json.dumps({"schema_version": 1, "models": records}),
        encoding="utf-8",
    )
    return lock_path


def _write_recent(data_dir: Path, entries: list[dict[str, Any]]) -> Path:
    recent_path = data_dir / "recent.json"
    recent_path.write_text(json.dumps(entries), encoding="utf-8")
    return recent_path


def test_end_to_end_install_update_remove_and_list_via_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r1_weights = b"weights-r1-content" * 20
    r1_cfg = b'{"rev": 1}'
    r2_weights = b"weights-r2-content" * 25
    files_map = {
        "sub/r1.onnx": r1_weights,
        "r1.json": r1_cfg,
        "sub/r2.onnx": r2_weights,
    }
    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    monkeypatch.setattr(
        "skald_core.catalog.client.get_adapters_path",
        lambda: adapters,
    )

    _write_catalog_cache(
        [
            _make_model(
                "demo",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [
                            _make_revision(
                                "r1",
                                [
                                    _make_file_entry("sub/r1.onnx", r1_weights, "onnx"),
                                    _make_file_entry("r1.json", r1_cfg, "json"),
                                ],
                            ),
                            _make_revision(
                                "r2",
                                [_make_file_entry("sub/r2.onnx", r2_weights, "onnx")],
                            ),
                        ],
                    }
                ],
            )
        ]
    )

    # Set up a project pinning r1 in recent.json.
    proj_dir = tmp_path / "BookProject"
    proj_dir.mkdir()
    (proj_dir / "skald-project.json").write_text(
        json.dumps({"schema_version": 1, "name": "Saga Book"}),
        encoding="utf-8",
    )
    lock_payload = {
        "schema_version": 1,
        "models": [
            {
                "model_id": "demo",
                "checkpoint_id": "cp1",
                "revision_id": "r1",
                "adapter_version": "1.0.0",
                "file_hashes": {"sub/r1.onnx": _sha256_bytes(r1_weights)},
            }
        ],
    }
    lock_path = proj_dir / "models.lock.json"
    lock_path.write_text(json.dumps(lock_payload), encoding="utf-8")
    _write_recent(tmp_path / "userdata", [{"path": str(proj_dir), "extra_key": "ignored"}])

    notifier = _RecordingNotifier()

    class _CapturingServer(RpcServer):
        def notify(self, method: str, params: Any = None) -> None:
            notifier(method, params)
            super().notify(method, params)

    server = _CapturingServer(stdin=io.BytesIO(), stdout=io.BytesIO())
    manager = register_all(server)
    try:
        with _run_server(_make_file_server(files_map)) as base_url:
            _patch_file_urls(monkeypatch, base_url)

            # 1. Install default revision r1 via RPC.
            resp_install = server.handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "models.install",
                        "params": {"model_id": "demo", "checkpoint_id": "cp1"},
                    }
                )
            )
            assert resp_install is not None
            job_install = resp_install["result"]["job_id"]
            fin_install = notifier.wait_finished(job_install)
            assert fin_install["status"] == "succeeded"
            assert fin_install["result"]["revision_id"] == "r1"
            assert fin_install["result"]["already_installed"] is False

            # Check progress reported per file & bytes.
            prog_events = notifier.progress_for(job_install)
            assert any(p["stage"] == "download" and "bytes)" in p["message"] for p in prog_events)
            assert prog_events[-1]["fraction"] == 1.0

            rev1_dir = models_dir() / "demo" / "cp1" / "r1"
            assert (rev1_dir / "sub" / "r1.onnx").read_bytes() == r1_weights
            assert (rev1_dir / "r1.json").read_bytes() == r1_cfg
            assert not (models_dir() / "demo" / "cp1" / "r1.part").exists()
            complete = json.loads((rev1_dir / ".complete").read_text(encoding="utf-8"))
            assert complete["files"] == {
                "sub/r1.onnx": _sha256_bytes(r1_weights),
                "r1.json": _sha256_bytes(r1_cfg),
            }
            assert complete["installed_at"].endswith("Z")

            # 2. Bump default_revision to r2 in catalog and call models.update.
            _write_catalog_cache(
                [
                    _make_model(
                        "demo",
                        checkpoints=[
                            {
                                "id": "cp1",
                                "max_chars": 400,
                                "default_revision": "r2",
                                "revisions": [
                                    _make_revision(
                                        "r1",
                                        [
                                            _make_file_entry("sub/r1.onnx", r1_weights, "onnx"),
                                            _make_file_entry("r1.json", r1_cfg, "json"),
                                        ],
                                    ),
                                    _make_revision(
                                        "r2",
                                        [_make_file_entry("sub/r2.onnx", r2_weights, "onnx")],
                                    ),
                                ],
                            }
                        ],
                    )
                ]
            )
            resp_update = server.handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "models.update",
                        "params": {"model_id": "demo", "checkpoint_id": "cp1"},
                    }
                )
            )
            assert resp_update is not None
            fin_update = notifier.wait_finished(resp_update["result"]["job_id"])
            assert fin_update["status"] == "succeeded"
            assert fin_update["result"]["revision_id"] == "r2"
            assert fin_update["result"]["already_installed"] is False

            # Update NEVER touches project pins (D5).
            assert json.loads(lock_path.read_text(encoding="utf-8")) == lock_payload

            # Calling update again when already on default r2 is a no-op.
            resp_update2 = server.handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "models.update",
                        "params": {"model_id": "demo", "checkpoint_id": "cp1"},
                    }
                )
            )
            assert resp_update2 is not None
            fin_update2 = notifier.wait_finished(resp_update2["result"]["job_id"])
            assert fin_update2["status"] == "succeeded"
            assert fin_update2["result"]["already_installed"] is True

            # 3. list_installed shows both r1 (pinned by Saga Book) and r2 (default).
            resp_list = server.handle_line(
                '{"jsonrpc":"2.0","id":4,"method":"models.list_installed"}'
            )
            assert resp_list is not None
            listed = resp_list["result"]
            by_rev = {r["revision_id"]: r for r in listed["revisions"]}
            assert set(by_rev) == {"r1", "r2"}
            assert by_rev["r1"]["is_default"] is False
            assert by_rev["r1"]["still_in_catalog"] is True
            assert by_rev["r1"]["used_by"] == [{"name": "Saga Book", "path": str(proj_dir)}]
            assert by_rev["r1"]["size_bytes"] > len(r1_weights)
            assert by_rev["r2"]["is_default"] is True
            assert by_rev["r2"]["used_by"] == []
            assert listed["cleanup_candidates"] == []

            # Unpin r1 -> r1 becomes a cleanup candidate!
            lock_path.unlink()
            resp_list2 = server.handle_line(
                '{"jsonrpc":"2.0","id":5,"method":"models.list_installed"}'
            )
            assert resp_list2 is not None
            candidates = resp_list2["result"]["cleanup_candidates"]
            assert [c["revision_id"] for c in candidates] == ["r1"]

            # 4. Remove r1 via RPC.
            resp_rm = server.handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "models.remove",
                        "params": {"model_id": "demo", "checkpoint_id": "cp1", "revision_id": "r1"},
                    }
                )
            )
            assert resp_rm is not None
            fin_rm = notifier.wait_finished(resp_rm["result"]["job_id"])
            assert fin_rm["status"] == "succeeded"
            assert fin_rm["result"]["removed"] is True
            assert not rev1_dir.exists()
    finally:
        manager.shutdown(timeout=2.0)


def test_checksum_failure_leaves_nothing_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good_bytes = b"expected-content"
    bad_bytes = b"corrupted-conten"  # same length, wrong hash
    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    _write_catalog_cache(
        [
            _make_model(
                "demo",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [
                            _make_revision("r1", [_make_file_entry("m.onnx", good_bytes)])
                        ],
                    }
                ],
            )
        ]
    )

    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        with _run_server(_make_file_server({"m.onnx": bad_bytes})) as base_url:
            _patch_file_urls(monkeypatch, base_url)
            job_id = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            fin = notifier.wait_finished(job_id)
            assert fin["status"] == "failed"
            assert fin["error"]["data"]["kind"] == "checksum_mismatch"
    finally:
        jm.shutdown(timeout=2.0)

    rev_dir = models_dir() / "demo" / "cp1" / "r1"
    assert not rev_dir.exists()
    assert not (rev_dir / ".complete").exists()


def test_interrupted_download_resumes_with_range_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"0123456789ABCDEF" * 8750  # 140,000 bytes (> net.DOWNLOAD_CHUNK_SIZE)
    expected_part_size = net.DOWNLOAD_CHUNK_SIZE
    seen_ranges: list[str | None] = []
    attempt_state = {"calls": 0}

    class DropMidFileHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            attempt_state["calls"] += 1
            range_hdr = self.headers.get("Range")
            seen_ranges.append(range_hdr)
            if attempt_state["calls"] <= 3:
                # Send >1 full chunk then drop connection mid-body (and fail retries with 503
                # so the first install job fails and leaves .part behind).
                if range_hdr is None:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content[: expected_part_size + 8192])
                    self.wfile.flush()
                else:
                    self.send_response(503)
                    self.end_headers()
                return

            assert range_hdr == f"bytes={expected_part_size}-"
            tail = content[expected_part_size:]
            self.send_response(206)
            self.send_header(
                "Content-Range",
                f"bytes {expected_part_size}-{len(content) - 1}/{len(content)}",
            )
            self.send_header("Content-Length", str(len(tail)))
            self.end_headers()
            self.wfile.write(tail)

    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    _write_catalog_cache(
        [
            _make_model(
                "demo",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [_make_file_entry("m.onnx", content)])],
                    }
                ],
            )
        ]
    )

    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        with _run_server(DropMidFileHandler) as base_url:
            _patch_file_urls(monkeypatch, base_url)

            job1 = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            fin1 = notifier.wait_finished(job1)
            assert fin1["status"] == "failed"

            part_file = models_dir() / "demo" / "cp1" / "r1.part" / "m.onnx.part"
            assert part_file.is_file()
            assert part_file.stat().st_size == expected_part_size

            job2 = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            fin2 = notifier.wait_finished(job2)
            assert fin2["status"] == "succeeded"
    finally:
        jm.shutdown(timeout=2.0)

    assert seen_ranges[-1] == f"bytes={expected_part_size}-"
    assert (models_dir() / "demo" / "cp1" / "r1" / "m.onnx").read_bytes() == content


def test_non_commercial_license_acceptance_and_url_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"nc-weights"
    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    url_v1 = "https://example.com/nc-v1"
    url_v2 = "https://example.com/nc-v2"

    def set_nc_url(url: str) -> None:
        _write_catalog_cache(
            [
                _make_model(
                    "nc_model",
                    commercial=False,
                    license_name="CC-BY-NC-4.0",
                    license_url=url,
                    acknowledgement="Personal use only.",
                    checkpoints=[
                        {
                            "id": "cp1",
                            "max_chars": 400,
                            "default_revision": "r1",
                            "revisions": [_make_revision("r1", [_make_file_entry("w.onnx", data)])],
                        }
                    ],
                )
            ]
        )

    set_nc_url(url_v1)
    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        with _run_server(_make_file_server({"w.onnx": data})) as base_url:
            _patch_file_urls(monkeypatch, base_url)

            # 1. Without acceptance -> license_not_accepted.
            job1 = submit_model_install(jm, "nc_model", "cp1", adapters_path=adapters)
            fin1 = notifier.wait_finished(job1)
            assert fin1["status"] == "failed"
            assert fin1["error"]["data"]["kind"] == "license_not_accepted"
            assert not licenses_path().exists()

            # 2. Invalid accept requests -> -32602 (INVALID_PARAMS).
            with pytest.raises(SkaldError) as exc_unknown:
                accept_license("missing_model", url_v1)
            assert exc_unknown.value.code == -32602

            with pytest.raises(SkaldError) as exc_wrong_url:
                accept_license("nc_model", "https://example.com/wrong")
            assert exc_wrong_url.value.code == -32602

            # 3. Valid accept -> licenses.json written, install succeeds.
            res = accept_license("nc_model", url_v1)
            assert res.model_id == "nc_model"
            assert res.license_url == url_v1
            assert is_license_accepted("nc_model", url_v1)
            raw_licenses = json.loads(licenses_path().read_text(encoding="utf-8"))
            assert raw_licenses["nc_model"]["license_url"] == url_v1

            job2 = submit_model_install(jm, "nc_model", "cp1", adapters_path=adapters)
            fin2 = notifier.wait_finished(job2)
            assert fin2["status"] == "succeeded"

            # 4. Catalog license URL changes -> existing acceptance no longer counts.
            set_nc_url(url_v2)
            assert not is_license_accepted("nc_model", url_v2)
            job3 = submit_model_install(jm, "nc_model", "cp1", adapters_path=adapters)
            fin3 = notifier.wait_finished(job3)
            assert fin3["status"] == "failed"
            assert fin3["error"]["data"]["kind"] == "license_not_accepted"
    finally:
        jm.shutdown(timeout=2.0)


def test_remove_pinned_refuses_and_force_overrides_and_open_project_counts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rev_dir = models_dir() / "demo" / "cp1" / "r1"
    rev_dir.mkdir(parents=True)
    (rev_dir / ".complete").write_text(
        json.dumps({"files": {}, "installed_at": "2026-11-26T00:00:00Z"}),
        encoding="utf-8",
    )
    _write_catalog_cache([])

    # Recent project with a pin, plus an unreadable recent project lockfile, plus an open project.
    proj_recent = tmp_path / "RecentBook"
    _write_pin_file(
        proj_recent,
        [
            {
                "model_id": "demo",
                "checkpoint_id": "cp1",
                "revision_id": "r1",
                "adapter_version": "1.0.0",
                "file_hashes": {},
            }
        ],
    )
    proj_corrupt_lock = tmp_path / "CorruptLockBook"
    proj_corrupt_lock.mkdir()
    (proj_corrupt_lock / "models.lock.json").write_text("{bad-json", encoding="utf-8")

    _write_recent(
        tmp_path / "userdata",
        [
            {"path": str(proj_recent), "name": "Recent Book", "last_opened": "2026-11-25"},
            {"path": str(proj_corrupt_lock)},
            {"path": "relative/ignored"},
        ],
    )

    store = ProjectStore()
    open_proj_dir = tmp_path / "OpenBook"
    store.create(open_proj_dir, "Current Open Book", base_seed=42)
    _write_pin_file(
        open_proj_dir,
        [
            {
                "model_id": "demo",
                "checkpoint_id": "cp1",
                "revision_id": "r1",
                "adapter_version": "1.0.0",
                "file_hashes": {},
            }
        ],
    )

    with caplog.at_level(logging.WARNING, logger="skald_core.models.installer"):
        listed = list_installed_models(project_store=store)
    assert len(listed.revisions) == 1
    assert listed.revisions[0].still_in_catalog is False
    assert listed.revisions[0].is_default is False
    assert {p.name for p in listed.revisions[0].used_by} == {"Recent Book", "Current Open Book"}
    assert any("Unreadable or invalid" in r.message for r in caplog.records)

    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        # Without force -> model_in_use with project names in hint.
        job1 = submit_model_remove(jm, "demo", "cp1", "r1", project_store=store)
        fin1 = notifier.wait_finished(job1)
        assert fin1["status"] == "failed"
        assert fin1["error"]["data"]["kind"] == "model_in_use"
        hint = fin1["error"]["data"]["hint"]
        assert "Recent Book" in hint
        assert "Current Open Book" in hint
        assert rev_dir.exists()

        # With force -> removed.
        job2 = submit_model_remove(jm, "demo", "cp1", "r1", force=True, project_store=store)
        fin2 = notifier.wait_finished(job2)
        assert fin2["status"] == "succeeded"
        assert fin2["result"]["removed"] is True
        assert not rev_dir.exists()
    finally:
        jm.shutdown(timeout=2.0)


def test_corrupt_or_missing_recent_json_warns_and_treats_as_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_catalog_cache([])
    with caplog.at_level(logging.WARNING, logger="skald_core.models.installer"):
        res_missing = list_installed_models()
    assert res_missing.revisions == []
    assert any("not found" in r.message for r in caplog.records)

    caplog.clear()
    (tmp_path / "userdata" / "recent.json").write_text("{corrupt", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="skald_core.models.installer"):
        res_corrupt = list_installed_models()
    assert res_corrupt.revisions == []
    assert any("Could not read recent projects" in r.message for r in caplog.records)


def test_concurrent_install_and_remove_same_revision_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"slow-bytes" * 10
    started = threading.Event()
    release = threading.Event()

    class BlockingHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content[:5])
            self.wfile.flush()
            started.set()
            assert release.wait(timeout=5.0)
            self.wfile.write(content[5:])
            self.wfile.flush()

    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    _write_catalog_cache(
        [
            _make_model(
                "demo",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [_make_file_entry("m.onnx", content)])],
                    }
                ],
            )
        ]
    )

    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=3, notify_fn=notifier)
    try:
        with _run_server(BlockingHandler) as base_url:
            _patch_file_urls(monkeypatch, base_url)
            job1 = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            assert started.wait(timeout=5.0)

            job2 = submit_model_install(jm, "demo", "cp1", revision_id="r1", adapters_path=adapters)
            fin2 = notifier.wait_finished(job2)
            assert fin2["status"] == "failed"
            assert "already in progress" in fin2["error"]["data"]["hint"].lower()

            job_rm = submit_model_remove(jm, "demo", "cp1", "r1")
            fin_rm = notifier.wait_finished(job_rm)
            assert fin_rm["status"] == "failed"
            assert "already in progress" in fin_rm["error"]["data"]["hint"].lower()

            release.set()
            fin1 = notifier.wait_finished(job1)
            assert fin1["status"] == "succeeded"
    finally:
        release.set()
        jm.shutdown(timeout=2.0)


def test_refusals_before_download_or_pack_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    download_called = False
    pack_called = False

    def fail_download(*_args: Any, **_kwargs: Any) -> Path:
        nonlocal download_called
        download_called = True
        raise AssertionError("net.download should not be called")

    def fail_pack(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal pack_called
        pack_called = True
        raise AssertionError("PackManager.install_job should not be called")

    monkeypatch.setattr(net, "download", fail_download)
    monkeypatch.setattr(PackManager, "install_job", fail_pack)

    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    dummy_file = _make_file_entry("m.onnx", b"x" * 100)

    # 1. Retired model -> model_download_failed with hint.
    _write_catalog_cache(
        [
            _make_model(
                "retired_m",
                status="retired",
                pack="torch-cpu-smoke",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [dummy_file])],
                    }
                ],
            ),
            # 2. Incompatible revision (adapter too old) -> adapter_unavailable.
            _make_model(
                "incompat_m",
                pack="torch-cpu-smoke",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [
                            _make_revision("r1", [dummy_file], min_adapter_version="9.0.0")
                        ],
                    }
                ],
            ),
            # 3. Bundled revision -> internal, hint mentions "bundled with the app".
            _make_model(
                "bundled_m",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [dummy_file], bundled=True)],
                    }
                ],
            ),
            # 4. Active compatible unbundled model for disk check.
            _make_model(
                "disk_m",
                pack="torch-cpu-smoke",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [dummy_file])],
                    }
                ],
            ),
        ]
    )

    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        fin_ret = notifier.wait_finished(
            submit_model_install(jm, "retired_m", "cp1", adapters_path=adapters)
        )
        assert fin_ret["status"] == "failed"
        assert fin_ret["error"]["data"]["kind"] == "model_download_failed"
        assert fin_ret["error"]["data"]["hint"]

        fin_inc = notifier.wait_finished(
            submit_model_install(jm, "incompat_m", "cp1", adapters_path=adapters)
        )
        assert fin_inc["status"] == "failed"
        assert fin_inc["error"]["data"]["kind"] == "adapter_unavailable"

        fin_bnd = notifier.wait_finished(
            submit_model_install(jm, "bundled_m", "cp1", adapters_path=adapters)
        )
        assert fin_bnd["status"] == "failed"
        assert fin_bnd["error"]["data"]["kind"] == "internal"
        assert "bundled with the app" in fin_bnd["error"]["data"]["hint"].lower()

        # 5. Not enough disk -> not_enough_disk.
        monkeypatch.setattr(
            shutil,
            "disk_usage",
            lambda _path: shutil._ntuple_diskusage(1000, 950, 50),
        )
        fin_disk = notifier.wait_finished(
            submit_model_install(jm, "disk_m", "cp1", adapters_path=adapters)
        )
        assert fin_disk["status"] == "failed"
        assert fin_disk["error"]["data"]["kind"] == "not_enough_disk"
    finally:
        jm.shutdown(timeout=2.0)

    assert not download_called
    assert not pack_called


def test_pickle_without_approved_exception_refused_defense_in_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Construct an unapproved pickle CatalogFile bypassing schema validation to verify installer
    # defense-in-depth refusal -> unsupported_format.
    bad_pickle_file = CatalogFile.model_construct(
        path="model.pt",
        format="pickle",
        size=128,
        sha256="a" * 64,
        approved_exception=None,
    )
    fake_model = AnnotatedCatalogModel.model_construct(
        id="pickle_m",
        name="Pickle Model",
        status="active",
        family_adapter="kokoro",
        pack=None,
        summary="Test",
        license=CatalogLicense(name="MIT", url="https://example.com/mit", commercial=True),
        languages=["en"],
        capabilities=[],
        hardware=CatalogHardware(cpu=CpuHardware(min_ram_gb=1.0), cuda=None),
        notes=CatalogNotes(),
        checkpoints=[
            AnnotatedCatalogCheckpoint.model_construct(
                id="cp1",
                max_chars=400,
                default_revision="r1",
                revisions=[
                    AnnotatedCatalogRevision.model_construct(
                        id="r1",
                        bundled=False,
                        min_adapter_version="1.0.0",
                        source=CatalogSource(
                            host="huggingface", repo="example/m", ref=_VALID_HF_REF
                        ),
                        files=[bad_pickle_file],
                        changelog="",
                        compatible=True,
                        reason=None,
                        installed=False,
                        update_available=False,
                    )
                ],
                compatible=True,
                reason=None,
                installed=False,
                update_available=False,
                fit=None,
            )
        ],
        compatible=True,
        reason=None,
        installed=False,
        update_available=False,
        fit=None,
    )

    class _FakeView:
        models = [fake_model]

    monkeypatch.setattr(installer, "get_catalog", lambda **_kw: _FakeView())
    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        job_id = submit_model_install(jm, "pickle_m", "cp1")
        fin = notifier.wait_finished(job_id)
        assert fin["status"] == "failed"
        assert fin["error"]["data"]["kind"] == "unsupported_format"
    finally:
        jm.shutdown(timeout=2.0)


def test_cancel_mid_download_keeps_part_and_next_install_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"chunked-payload-" * 8750  # 140,000 bytes (> net.DOWNLOAD_CHUNK_SIZE)
    first_chunk_written = threading.Event()
    allow_rest = threading.Event()
    resume_ranges: list[str | None] = []

    class SlowHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            range_hdr = self.headers.get("Range")
            resume_ranges.append(range_hdr)
            if range_hdr and range_hdr.startswith("bytes="):
                start = int(range_hdr[len("bytes=") :].split("-", 1)[0])
                tail = content[start:]
                self.send_response(206)
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(content) - 1}/{len(content)}"
                )
                self.send_header("Content-Length", str(len(tail)))
                self.end_headers()
                self.wfile.write(tail)
                return

            split = net.DOWNLOAD_CHUNK_SIZE + 1024
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content[:split])
            self.wfile.flush()
            allow_rest.wait(timeout=5.0)
            try:
                self.wfile.write(content[split:])
                self.wfile.flush()
            except OSError:
                pass

    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    _write_catalog_cache(
        [
            _make_model(
                "demo",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [_make_file_entry("m.onnx", content)])],
                    }
                ],
            )
        ]
    )

    class _ProgressWatcher(_RecordingNotifier):
        def __call__(self, method: str, params: BaseModel | dict[str, Any]) -> None:
            super().__call__(method, params)
            if method == "job.progress":
                first_chunk_written.set()

    notifier = _ProgressWatcher()
    jm = JobManager(max_workers=1, notify_fn=notifier, progress_interval_s=0.0)
    try:
        with _run_server(SlowHandler) as base_url:
            _patch_file_urls(monkeypatch, base_url)
            job1 = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            assert first_chunk_written.wait(timeout=5.0)
            jm.cancel(job1)
            allow_rest.set()
            fin1 = notifier.wait_finished(job1)
            assert fin1["status"] == "cancelled"

            part_dir = models_dir() / "demo" / "cp1" / "r1.part"
            part_file = part_dir / "m.onnx.part"
            assert part_dir.is_dir()
            assert part_file.is_file()
            assert part_file.stat().st_size == net.DOWNLOAD_CHUNK_SIZE

            job2 = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            fin2 = notifier.wait_finished(job2)
            assert fin2["status"] == "succeeded"
    finally:
        allow_rest.set()
        jm.shutdown(timeout=2.0)

    assert resume_ranges[-1] == f"bytes={net.DOWNLOAD_CHUNK_SIZE}-"
    assert (models_dir() / "demo" / "cp1" / "r1" / "m.onnx").read_bytes() == content


def test_pack_install_skip_concurrency_and_removal_refcount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"pack-model-bytes"
    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})

    # Create a fake packs source dir with cpu and cu12 lockfiles.
    packs_src = tmp_path / "packs_src"
    locks_dir = packs_src / "myengine" / "locks"
    locks_dir.mkdir(parents=True)
    os_name = "windows" if os.name == "nt" else "linux"
    for accel, backend in (("cpu", "cpu"), ("cu12", "cu126")):
        (locks_dir / f"{os_name}-{accel}.txt").write_text(
            f"# skald-backend: {backend}\n# skald-required-bytes: 100\ntorch==2.14.1\n",
            encoding="utf-8",
        )

    _write_catalog_cache(
        [
            _make_model(
                "m1",
                pack="myengine",
                hardware={
                    "cpu": {"min_ram_gb": 1.0, "rtf_reference": None},
                    "cuda": {"min_vram_gb": 4.0, "min_ram_gb": 1.0, "rtf_reference": 0.2},
                },
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [_make_file_entry("m.onnx", content)])],
                    }
                ],
            ),
            _make_model(
                "m2",
                pack="myengine",
                hardware={"cpu": {"min_ram_gb": 1.0, "rtf_reference": None}, "cuda": None},
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [_make_file_entry("m.onnx", content)])],
                    }
                ],
            ),
        ]
    )

    pm = PackManager(storage_dir=tmp_path / "storage", packs_source_dir=packs_src)
    install_calls: list[tuple[str, str | None, Path | None]] = []
    remove_calls: list[str] = []

    def fake_pack_install(
        ctx: Any,
        family: str,
        *,
        accel: str | None = None,
        worker_wheel: Path | None = None,
        **_kw: Any,
    ) -> dict[str, Any]:
        install_calls.append((family, accel, worker_wheel))
        lock_path = pm.resolve_lockfile(family, accel=accel)
        lock_info = parse_lockfile(lock_path)
        pdir = pm.pack_dir_for(family, lock_info)
        pdir.mkdir(parents=True, exist_ok=True)
        meta = PackMetadata(
            family=family,
            os=os_name,
            accel=lock_info.accel,
            backend=lock_info.backend,
            lock_sha256=lock_info.sha256,
            lock_hash8=lock_info.hash8,
            packages=list(lock_info.packages),
            base_python_dir=str(tmp_path / "storage" / "python" / "3.12"),
            python_version="Python 3.12.16",
            uv_version="uv 0.13.8",
            created_at="2026-11-26T00:00:00Z",
        )
        (pdir / "pack.json").write_text(meta.model_dump_json(), encoding="utf-8")
        return {"pack_dir": str(pdir), "metadata": meta.model_dump(mode="json")}

    def fake_pack_remove(family: str, **_kw: Any) -> dict[str, Any]:
        remove_calls.append(family)
        return {"removed_packs": [family], "removed_python_dirs": [], "cache_cleaned": "none"}

    monkeypatch.setattr(pm, "install_job", fake_pack_install)
    monkeypatch.setattr(pm, "remove", fake_pack_remove)

    cuda_hw = HardwareInfo(
        os="Linux",
        cpu_model="CPU",
        physical_cores=4,
        logical_cores=8,
        ram_total_bytes=16 * 1024**3,
        ram_free_bytes=8 * 1024**3,
        disk_free_bytes=100 * 1024**3,
        gpus=[
            GpuInfo(
                name="T4",
                memory_total_mb=16384,
                driver_version="560.28.03",
                compute_cap="7.5",
                bfloat16_capable=False,
            )
        ],
    )

    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        with _run_server(_make_file_server({"m.onnx": content})) as base_url:
            _patch_file_urls(monkeypatch, base_url)

            # 1. m1 with CUDA fit installs cu12 pack with worker_wheel=None.
            j1 = submit_model_install(
                jm, "m1", "cp1", adapters_path=adapters, hardware=cuda_hw, pack_manager=pm
            )
            fin1 = notifier.wait_finished(j1)
            assert fin1["status"] == "succeeded"
            assert install_calls == [("myengine", "cu12", None)]

            # 2. m2 with CPU fit installs cpu pack.
            j2 = submit_model_install(
                jm, "m2", "cp1", adapters_path=adapters, hardware=cuda_hw, pack_manager=pm
            )
            fin2 = notifier.wait_finished(j2)
            assert fin2["status"] == "succeeded"
            assert install_calls == [("myengine", "cu12", None), ("myengine", "cpu", None)]

            # 3. Re-installing a new revision on m1 skips pack install because cu12 pack exists.
            shutil.rmtree(models_dir() / "m1" / "cp1" / "r1")
            j1b = submit_model_install(
                jm, "m1", "cp1", adapters_path=adapters, hardware=cuda_hw, pack_manager=pm
            )
            fin1b = notifier.wait_finished(j1b)
            assert fin1b["status"] == "succeeded"
            assert len(install_calls) == 2

            # 4. Removing m1 does NOT remove pack because m2 still uses myengine.
            jr1 = submit_model_remove(
                jm, "m1", "cp1", "r1", adapters_path=adapters, hardware=cuda_hw, pack_manager=pm
            )
            fr1 = notifier.wait_finished(jr1)
            assert fr1["status"] == "succeeded"
            assert remove_calls == []

            # 5. Removing m2 DOES remove pack because no installed revision uses myengine anymore.
            jr2 = submit_model_remove(
                jm, "m2", "cp1", "r1", adapters_path=adapters, hardware=cuda_hw, pack_manager=pm
            )
            fr2 = notifier.wait_finished(jr2)
            assert fr2["status"] == "succeeded"
            assert remove_calls == ["myengine"]
            assert fr2["result"]["removed_packs"] == ["myengine"]

            # 6. Surface PackManager's own "already in progress" SkaldError unchanged.
            def busy_pack_install(*_a: Any, **_kw: Any) -> dict[str, Any]:
                raise SkaldError(
                    "pack_install_failed",
                    "Pack operation for 'myengine' is already in progress.",
                    hint="Another operation for this pack is already in progress.",
                )

            shutil.rmtree(tmp_path / "storage" / "packs")
            monkeypatch.setattr(pm, "install_job", busy_pack_install)
            j_busy = submit_model_install(
                jm, "m1", "cp1", adapters_path=adapters, hardware=cuda_hw, pack_manager=pm
            )
            f_busy = notifier.wait_finished(j_busy)
            assert f_busy["status"] == "failed"
            assert f_busy["error"]["data"]["kind"] == "pack_install_failed"
            assert "already in progress" in f_busy["error"]["data"]["hint"].lower()
    finally:
        jm.shutdown(timeout=2.0)


def test_replace_dir_retries_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "r1.part"
    dst = tmp_path / "r1"
    src.mkdir()
    (src / ".complete").write_text("{}", encoding="utf-8")

    real_replace = os.replace
    attempts = {"n": 0}

    def flaky_replace(s: Path | str, d: Path | str) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise PermissionError("Simulated Windows indexer lock")
        real_replace(s, d)

    monkeypatch.setattr(os, "replace", flaky_replace)
    installer._replace_dir_with_retry(src, dst, retry_delays=(0.0, 0.0))
    assert attempts["n"] == 2
    assert (dst / ".complete").is_file()
    assert not src.exists()


def test_multi_file_resume_skips_already_verified_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f1 = b"file-one-contents"
    f2 = b"file-two-contents"
    requests_seen: list[str] = []
    fail_second = {"flag": True}

    class PartialMultiFileHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            rel = self.path.lstrip("/")
            requests_seen.append(rel)
            if rel == "a.onnx":
                self.send_response(200)
                self.send_header("Content-Length", str(len(f1)))
                self.end_headers()
                self.wfile.write(f1)
                return
            if rel == "b.onnx" and fail_second["flag"]:
                self.send_response(404)
                self.end_headers()
                return
            if rel == "b.onnx":
                self.send_response(200)
                self.send_header("Content-Length", str(len(f2)))
                self.end_headers()
                self.wfile.write(f2)
                return
            self.send_response(404)
            self.end_headers()

    adapters = _write_adapters(tmp_path / "adapters.py", {"kokoro": "1.0.0"})
    _write_catalog_cache(
        [
            _make_model(
                "demo",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [
                            _make_revision(
                                "r1",
                                [
                                    _make_file_entry("a.onnx", f1),
                                    _make_file_entry("b.onnx", f2),
                                ],
                            )
                        ],
                    }
                ],
            )
        ]
    )

    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        with _run_server(PartialMultiFileHandler) as base_url:
            _patch_file_urls(monkeypatch, base_url)
            j1 = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            fin1 = notifier.wait_finished(j1)
            assert fin1["status"] == "failed"
            assert fin1["error"]["data"]["kind"] == "http_not_found"
            assert (models_dir() / "demo" / "cp1" / "r1.part" / "a.onnx").is_file()

            requests_seen.clear()
            fail_second["flag"] = False
            j2 = submit_model_install(jm, "demo", "cp1", adapters_path=adapters)
            fin2 = notifier.wait_finished(j2)
            assert fin2["status"] == "succeeded"
            assert requests_seen == ["b.onnx"]
    finally:
        jm.shutdown(timeout=2.0)

    rev_dir = models_dir() / "demo" / "cp1" / "r1"
    assert (rev_dir / "a.onnx").read_bytes() == f1
    assert (rev_dir / "b.onnx").read_bytes() == f2


def test_rpc_param_validation_errors(tmp_path: Path) -> None:
    _write_catalog_cache(
        [
            _make_model(
                "nc",
                commercial=False,
                license_name="CC-BY-NC-4.0",
                license_url="https://example.com/nc",
                acknowledgement="Personal only",
                checkpoints=[
                    {
                        "id": "cp1",
                        "max_chars": 400,
                        "default_revision": "r1",
                        "revisions": [_make_revision("r1", [_make_file_entry("m.onnx", b"x")])],
                    }
                ],
            )
        ]
    )
    server = RpcServer(stdin=io.BytesIO(), stdout=io.BytesIO())
    manager = register_all(server)
    try:
        bad_requests = [
            {
                "method": "models.install",
                "params": {"model_id": "../evil", "checkpoint_id": "cp1"},
            },
            {
                "method": "models.update",
                "params": {"model_id": "nc", "checkpoint_id": "a/b"},
            },
            {
                "method": "models.remove",
                "params": {
                    "model_id": "nc",
                    "checkpoint_id": "cp1",
                    "revision_id": "r1",
                    "force": "yes",
                },
            },
            {
                "method": "models.list_installed",
                "params": {"unexpected": 1},
            },
            {
                "method": "license.accept",
                "params": {"model_id": "unknown", "license_url": "https://example.com/nc"},
            },
            {
                "method": "license.accept",
                "params": {"model_id": "nc", "license_url": "https://example.com/wrong"},
            },
        ]
        for idx, req in enumerate(bad_requests, start=1):
            resp = server.handle_line(json.dumps({"jsonrpc": "2.0", "id": idx, **req}))
            assert resp is not None
            assert resp["error"]["code"] == -32602, req
    finally:
        manager.shutdown(timeout=2.0)
