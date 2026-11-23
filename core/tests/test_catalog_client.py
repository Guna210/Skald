"""Tests for catalog fetch, cache, bundled fallback, compatibility, and RPC."""

from __future__ import annotations

import http.server
import io
import json
import logging
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import requests
from pydantic import BaseModel

from skald_core import __version__, net
from skald_core.catalog import client as catalog_client
from skald_core.catalog.client import (
    DEFAULT_CATALOG_URL,
    MAX_CATALOG_BYTES,
    _is_safe_id_segment,
    annotate_catalog,
    get_adapters_path,
    get_bundled_catalog_path,
    get_catalog,
    get_catalog_cache_path,
    get_resource_root,
    parse_catalog_json,
    resolve_catalog_url,
    submit_catalog_refresh,
)
from skald_core.catalog.schema import Catalog
from skald_core.jobs import JobManager
from skald_core.rpc import RpcServer, SkaldError
from skald_core.rpc.methods import register_all

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VALID_SHA256 = "a" * 64
_VALID_HF_REF = "0123456789abcdef0123456789abcdef01234567"

_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@pytest.fixture(autouse=True)
def _isolated_catalog_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests never read or write outside temporary directories."""
    data_dir = tmp_path / "userdata"
    storage_dir = tmp_path / "storage"
    data_dir.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SKALD_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SKALD_STORAGE_DIR", str(storage_dir))
    monkeypatch.delenv("SKALD_CATALOG_URL", raising=False)
    for var in _PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net, "BACKOFF_SECONDS", 0.0)


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
                ev = self.finished_events.setdefault(payload["job_id"], threading.Event())
                ev.set()

    def wait_finished(self, job_id: str, timeout: float = 5.0) -> dict[str, Any]:
        with self._lock:
            ev = self.finished_events.setdefault(job_id, threading.Event())
        assert ev.wait(timeout=timeout), f"Timed out waiting for job.finished on {job_id}"
        with self._lock:
            matches = [p for m, p in self.events if m == "job.finished" and p["job_id"] == job_id]
        assert len(matches) == 1
        return matches[0]

    def logs_for(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [p for m, p in self.events if m == "job.log" and p["job_id"] == job_id]


def _make_revision(
    rev_id: str = "r1",
    *,
    min_adapter_version: str = "1.0.0",
    bundled: bool = False,
) -> dict[str, Any]:
    return {
        "id": rev_id,
        "bundled": bundled,
        "min_adapter_version": min_adapter_version,
        "source": {
            "host": "huggingface",
            "repo": "example/model",
            "ref": _VALID_HF_REF,
        },
        "files": [
            {
                "path": f"{rev_id}.onnx",
                "format": "onnx",
                "size": 128,
                "sha256": _VALID_SHA256,
            }
        ],
        "changelog": f"Release {rev_id}",
    }


def _make_checkpoint(
    cp_id: str = "cp1",
    *,
    default_revision: str = "r1",
    revisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": cp_id,
        "max_chars": 400,
        "default_revision": default_revision,
        "revisions": [_make_revision(default_revision)] if revisions is None else revisions,
    }


def _make_model(
    model_id: str = "kokoro",
    *,
    family_adapter: str = "kokoro",
    checkpoints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": model_id.title(),
        "status": "active",
        "family_adapter": family_adapter,
        "pack": None if family_adapter == "kokoro" else f"{family_adapter}-cpu",
        "summary": f"{model_id} summary",
        "license": {
            "name": "Apache-2.0",
            "url": "https://example.com/license",
            "commercial": True,
        },
        "languages": ["en-us"],
        "capabilities": ["presets"],
        "hardware": {"cpu": {"min_ram_gb": 4.0, "rtf_reference": None}, "cuda": None},
        "notes": {"watermark": None},
        "checkpoints": [_make_checkpoint()] if checkpoints is None else checkpoints,
    }


def _make_catalog(
    models: list[dict[str, Any]] | None = None,
    *,
    min_app_version: str = "0.1.0",
    updated_at: str = "2026-11-15",
    schema_version: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "min_app_version": min_app_version,
        "updated_at": updated_at,
        "models": [] if models is None else models,
    }


def _write_adapters(path: Path, versions: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"ADAPTER_VERSIONS = {versions!r}\n", encoding="utf-8")
    return path


def _mark_installed(
    models_root: Path,
    model_id: str,
    checkpoint_id: str,
    revision_id: str,
) -> Path:
    marker = models_root / model_id / checkpoint_id / revision_id / ".complete"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    return marker


def test_url_resolution_and_resource_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        DEFAULT_CATALOG_URL
        == "https://raw.githubusercontent.com/Guna210/Skald/master/catalog/catalog.json"
    )
    assert MAX_CATALOG_BYTES == 5 * 1024 * 1024
    assert resolve_catalog_url() == DEFAULT_CATALOG_URL

    monkeypatch.setenv("SKALD_CATALOG_URL", "https://example.invalid/dev-catalog.json")
    assert resolve_catalog_url() == "https://example.invalid/dev-catalog.json"
    assert (
        resolve_catalog_url("https://example.invalid/arg-catalog.json")
        == "https://example.invalid/arg-catalog.json"
    )

    assert get_resource_root() == _REPO_ROOT
    assert get_bundled_catalog_path() == _REPO_ROOT / "catalog" / "catalog.json"
    assert (
        get_adapters_path() == _REPO_ROOT / "worker" / "skald_worker" / "adapters" / "__init__.py"
    )

    frozen_root = tmp_path / "frozen_bundle"
    (frozen_root / "catalog").mkdir(parents=True)
    (frozen_root / "catalog" / "catalog.json").write_text(
        json.dumps(_make_catalog([_make_model("frozen_m")], updated_at="2026-11-20")),
        encoding="utf-8",
    )
    _write_adapters(
        frozen_root / "worker" / "skald_worker" / "adapters" / "__init__.py", {"kokoro": "1.0.0"}
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)

    assert get_resource_root() == frozen_root
    view = get_catalog()
    assert view.source == "bundled"
    assert view.updated_at == "2026-11-20"
    assert len(view.models) == 1
    assert view.models[0].compatible is True


def test_first_offline_launch_serves_bundled_copy_when_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_offline(*_args: Any, **_kwargs: Any) -> Any:
        raise requests.ConnectionError("Simulated offline network")

    monkeypatch.setattr(requests.Session, "request", raise_offline)

    notifier = _RecordingNotifier()
    manager = JobManager(max_workers=1, notify_fn=notifier)
    try:
        job_id = submit_catalog_refresh(manager)
        finished = notifier.wait_finished(job_id)
        assert finished["status"] == "failed"
        assert finished["error"]["data"]["kind"] == "offline"
    finally:
        manager.shutdown(timeout=2.0)

    assert not get_catalog_cache_path().exists()
    view = get_catalog()
    assert view.source == "bundled"
    bundled_raw = json.loads(get_bundled_catalog_path().read_text(encoding="utf-8"))
    assert view.updated_at == bundled_raw["updated_at"]
    assert len(view.models) == len(bundled_raw["models"])


def test_valid_refresh_updates_cache_and_ignores_missing_adapters_and_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Remote catalog contains an adapter the app lacks and has no model card files on disk.
    remote_payload = _make_catalog(
        [
            _make_model("kokoro", family_adapter="kokoro"),
            _make_model("future_tts", family_adapter="future_family"),
        ],
        updated_at="2026-11-21",
    )
    body = json.dumps(remote_payload).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    adapters_file = _write_adapters(tmp_path / "adapters" / "__init__.py", {"kokoro": "1.0.0"})

    with _run_server(Handler) as base_url:
        monkeypatch.setenv("SKALD_CATALOG_URL", f"{base_url}/catalog.json")
        notifier = _RecordingNotifier()
        manager = JobManager(max_workers=1, notify_fn=notifier)
        try:
            job_id = submit_catalog_refresh(manager, adapters_path=adapters_file)
            finished = notifier.wait_finished(job_id)
            assert finished["status"] == "succeeded"
            assert finished["result"]["updated_at"] == "2026-11-21"
            assert finished["result"]["model_count"] == 2
            assert finished["result"]["source"] == "cache"
        finally:
            manager.shutdown(timeout=2.0)

    assert get_catalog_cache_path().is_file()
    view = get_catalog(adapters_path=adapters_file)
    assert view.source == "cache"
    assert view.updated_at == "2026-11-21"
    by_id = {m.id: m for m in view.models}
    assert by_id["kokoro"].compatible is True
    assert by_id["kokoro"].reason is None
    assert by_id["future_tts"].compatible is False
    assert by_id["future_tts"].reason == "adapter_missing"


@pytest.mark.parametrize(
    ("case_name", "payload_bytes", "expected_reason"),
    [
        ("malformed_json", b"{not-valid-json", None),
        ("deep_recursion", (('{"a":' * 15000) + "1" + ("}" * 15000)).encode("utf-8"), None),
        ("non_object_root", b"[1, 2, 3]", None),
        (
            "schema_validation_error",
            json.dumps({**_make_catalog([]), "unexpected_field": True}).encode("utf-8"),
            None,
        ),
        (
            "schema_too_new",
            json.dumps({**_make_catalog([], schema_version=99), "future_only_field": "abc"}).encode(
                "utf-8"
            ),
            "schema_too_new",
        ),
    ],
)
def test_invalid_remote_catalog_preserves_cache_and_logs_warning(
    case_name: str,
    payload_bytes: bytes,
    expected_reason: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_cache = _make_catalog([_make_model("cached_model")], updated_at="2026-11-10")
    cache_path = get_catalog_cache_path()
    cache_text = json.dumps(existing_cache, indent=2) + "\n"
    cache_path.write_text(cache_text, encoding="utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload_bytes)))
            self.end_headers()
            self.wfile.write(payload_bytes)

    with _run_server(Handler) as base_url:
        monkeypatch.setenv("SKALD_CATALOG_URL", f"{base_url}/catalog.json")
        notifier = _RecordingNotifier()
        manager = JobManager(max_workers=1, notify_fn=notifier)
        try:
            job_id = submit_catalog_refresh(manager)
            finished = notifier.wait_finished(job_id)
            assert finished["status"] == "failed", case_name
            err = finished["error"]
            assert err["data"]["kind"] == "catalog_invalid", case_name
            if expected_reason is not None:
                assert err["data"]["details"]["reason"] == expected_reason
                assert err["data"]["hint"] and "update" in err["data"]["hint"].lower()
            logs = notifier.logs_for(job_id)
            assert any(entry["level"] == "warning" and entry["message"] for entry in logs)
        finally:
            manager.shutdown(timeout=2.0)

    # Cache file must remain untouched.
    assert cache_path.read_text(encoding="utf-8") == cache_text
    view = get_catalog()
    assert view.source == "cache"
    assert view.updated_at == "2026-11-10"


def test_remote_catalog_over_5mib_cap_fails_with_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = get_catalog_cache_path()
    cache_text = json.dumps(_make_catalog([], updated_at="2026-11-11")) + "\n"
    cache_path.write_text(cache_text, encoding="utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(MAX_CATALOG_BYTES + 1))
            self.end_headers()

    with _run_server(Handler) as base_url:
        monkeypatch.setenv("SKALD_CATALOG_URL", f"{base_url}/catalog.json")
        notifier = _RecordingNotifier()
        manager = JobManager(max_workers=1, notify_fn=notifier)
        try:
            job_id = submit_catalog_refresh(manager)
            finished = notifier.wait_finished(job_id)
            assert finished["status"] == "failed"
            assert finished["error"]["data"]["kind"] == "http_error"
        finally:
            manager.shutdown(timeout=2.0)

    assert cache_path.read_text(encoding="utf-8") == cache_text


def test_network_error_kinds_preserved_on_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/missing":
                self.send_response(404)
                self.end_headers()
            else:
                self.send_response(503)
                self.end_headers()

    with _run_server(Handler) as base_url:
        notifier = _RecordingNotifier()
        manager = JobManager(max_workers=1, notify_fn=notifier)
        try:
            j404 = submit_catalog_refresh(manager, url=f"{base_url}/missing")
            f404 = notifier.wait_finished(j404)
            assert f404["status"] == "failed"
            assert f404["error"]["data"]["kind"] == "http_not_found"

            j503 = submit_catalog_refresh(manager, url=f"{base_url}/down")
            f503 = notifier.wait_finished(j503)
            assert f503["status"] == "failed"
            assert f503["error"]["data"]["kind"] == "http_error"
        finally:
            manager.shutdown(timeout=2.0)


def test_corrupt_cache_logs_warning_and_falls_back_to_bundled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache_path = get_catalog_cache_path()
    cache_path.write_text("{corrupt-cache", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="skald_core.catalog.client"):
        view = get_catalog()

    assert view.source == "bundled"
    assert any("falling back to bundled catalog" in rec.message for rec in caplog.records)


def test_compatibility_and_update_matrix(tmp_path: Path) -> None:
    models_root = tmp_path / "models"

    # 1. Compatibility reason precedence: adapter_missing > adapter_too_old > app_too_old > ok
    # Tested with app_version="0.1.0" and catalog min_app_version="0.2.0" (so app is too old).
    catalog_app_old = Catalog.model_validate(
        _make_catalog(
            [
                _make_model("m_missing", family_adapter="missing_adapter"),
                _make_model(
                    "m_too_old",
                    family_adapter="chatterbox",
                    checkpoints=[
                        _make_checkpoint(
                            "cp1",
                            default_revision="r1",
                            revisions=[_make_revision("r1", min_adapter_version="2.0.0")],
                        )
                    ],
                ),
                _make_model(
                    "m_app_old",
                    family_adapter="kokoro",
                    checkpoints=[
                        _make_checkpoint(
                            "cp1",
                            default_revision="r1",
                            revisions=[_make_revision("r1", min_adapter_version="1.0.0")],
                        )
                    ],
                ),
            ],
            min_app_version="0.2.0",
        )
    )
    view_old_app = annotate_catalog(
        catalog_app_old,
        source="cache",
        adapter_versions={"kokoro": "1.0.0", "chatterbox": "1.5.0"},
        app_version="0.1.0",
        models_root=models_root,
    )
    by_id_old = {m.id: m for m in view_old_app.models}
    assert by_id_old["m_missing"].compatible is False
    assert by_id_old["m_missing"].reason == "adapter_missing"
    assert by_id_old["m_too_old"].compatible is False
    assert by_id_old["m_too_old"].reason == "adapter_too_old"
    assert by_id_old["m_app_old"].compatible is False
    assert by_id_old["m_app_old"].reason == "app_too_old"

    # 2. Checkpoint default revision vs non-default revision compatibility,
    #    Model compatibility across multiple checkpoints,
    #    Installed & update_available at all 3 levels,
    #    Parent-scoped non-globally-unique checkpoint/revision IDs.
    catalog_matrix = Catalog.model_validate(
        _make_catalog(
            [
                # Model A: shared_cp has r1 installed and r2 (default) compatible -> update;
                #          cp_incompat_default has r1 installed, r2 adapter_too_old -> no update
                _make_model(
                    "model_a",
                    family_adapter="kokoro",
                    checkpoints=[
                        _make_checkpoint(
                            "shared_cp",
                            default_revision="r2",
                            revisions=[
                                _make_revision("r1", min_adapter_version="1.0.0"),
                                _make_revision("r2", min_adapter_version="1.0.0"),
                            ],
                        ),
                        _make_checkpoint(
                            "cp_incompat_default",
                            default_revision="r2",
                            revisions=[
                                _make_revision("r1", min_adapter_version="1.0.0"),
                                _make_revision("r2", min_adapter_version="9.0.0"),
                            ],
                        ),
                        _make_checkpoint(
                            "cp_both_installed",
                            default_revision="r2",
                            revisions=[
                                _make_revision("r1", min_adapter_version="1.0.0"),
                                _make_revision("r2", min_adapter_version="1.0.0"),
                            ],
                        ),
                        _make_checkpoint(
                            "cp_none_installed",
                            default_revision="r2",
                            revisions=[
                                _make_revision("r1", min_adapter_version="1.0.0"),
                                _make_revision("r2", min_adapter_version="1.0.0"),
                            ],
                        ),
                    ],
                ),
                # Model B shares shared_cp and r1/r2 IDs, but nothing is installed ->
                # must not leak installed/update state from model_a.
                _make_model(
                    "model_b",
                    family_adapter="kokoro",
                    checkpoints=[
                        _make_checkpoint(
                            "shared_cp",
                            default_revision="r2",
                            revisions=[
                                _make_revision("r1", min_adapter_version="1.0.0"),
                                _make_revision("r2", min_adapter_version="1.0.0"),
                            ],
                        )
                    ],
                ),
                # Model C: default revision incompatible, non-default compatible.
                _make_model(
                    "model_c",
                    family_adapter="kokoro",
                    checkpoints=[
                        _make_checkpoint(
                            "cp1",
                            default_revision="r2",
                            revisions=[
                                _make_revision("r1", min_adapter_version="1.0.0"),
                                _make_revision("r2", min_adapter_version="3.0.0"),
                            ],
                        )
                    ],
                ),
            ],
            min_app_version="0.1.0",
        )
    )

    _mark_installed(models_root, "model_a", "shared_cp", "r1")
    _mark_installed(models_root, "model_a", "cp_incompat_default", "r1")
    _mark_installed(models_root, "model_a", "cp_both_installed", "r1")
    _mark_installed(models_root, "model_a", "cp_both_installed", "r2")

    view = annotate_catalog(
        catalog_matrix,
        source="cache",
        adapter_versions={"kokoro": "1.0.0"},
        app_version=__version__,
        models_root=models_root,
    )
    models = {m.id: m for m in view.models}

    ma = models["model_a"]
    assert ma.compatible is True
    assert ma.reason is None
    assert ma.installed is True
    assert ma.update_available is True
    assert ma.fit is None

    cps_a = {cp.id: cp for cp in ma.checkpoints}
    # shared_cp: r1 installed, default r2 compatible & not installed -> update_available!
    cp_upd = cps_a["shared_cp"]
    assert cp_upd.compatible is True
    assert cp_upd.reason is None
    assert cp_upd.installed is True
    assert cp_upd.update_available is True
    assert cp_upd.fit is None
    revs_upd = {r.id: r for r in cp_upd.revisions}
    assert revs_upd["r1"].installed is True
    assert revs_upd["r1"].update_available is True
    assert revs_upd["r2"].installed is False
    assert revs_upd["r2"].update_available is False

    # cp_incompat_default: r1 installed, default r2 incompatible -> no update!
    cp_inc = cps_a["cp_incompat_default"]
    assert cp_inc.compatible is False
    assert cp_inc.reason == "adapter_too_old"
    assert cp_inc.installed is True
    assert cp_inc.update_available is False
    revs_inc = {r.id: r for r in cp_inc.revisions}
    assert revs_inc["r1"].compatible is True
    assert revs_inc["r1"].update_available is False
    assert revs_inc["r2"].compatible is False
    assert revs_inc["r2"].reason == "adapter_too_old"

    # cp_both_installed: r1 and r2 installed -> no update!
    cp_both = cps_a["cp_both_installed"]
    assert cp_both.installed is True
    assert cp_both.update_available is False
    assert all(not r.update_available for r in cp_both.revisions)

    # cp_none_installed: nothing installed -> no update!
    cp_none = cps_a["cp_none_installed"]
    assert cp_none.installed is False
    assert cp_none.update_available is False
    assert all(not r.update_available for r in cp_none.revisions)

    # model_b: same shared_cp/r1/r2 IDs as model_a, but nothing installed
    mb = models["model_b"]
    assert mb.installed is False
    assert mb.update_available is False
    assert mb.checkpoints[0].installed is False
    assert mb.checkpoints[0].update_available is False

    # model_c: default revision incompatible -> checkpoint & model incompatible
    mc = models["model_c"]
    assert mc.compatible is False
    assert mc.reason == "adapter_too_old"
    assert mc.checkpoints[0].compatible is False
    assert mc.checkpoints[0].reason == "adapter_too_old"
    assert mc.checkpoints[0].revisions[0].compatible is True


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ("", False),
        (".", False),
        ("..", False),
        ("a/b", False),
        ("a\\b", False),
        ("a\x00b", False),
        ("kokoro-v1.0", True),
    ],
)
def test_is_safe_id_segment(segment: str, expected: bool) -> None:
    assert _is_safe_id_segment(segment) is expected


def test_parse_catalog_json_deep_recursion_and_unsafe_id_segments(tmp_path: Path) -> None:
    deep = ("{" * 15000) + "}" * 15000
    with pytest.raises(SkaldError) as exc_info:
        parse_catalog_json(deep)
    assert exc_info.value.kind == "catalog_invalid"

    # Unsafe path segments never reach Path(...) (a NUL byte would raise ValueError if probed).
    outside_marker = tmp_path / "outside" / "cp1" / "r1" / ".complete"
    outside_marker.parent.mkdir(parents=True)
    outside_marker.write_text("", encoding="utf-8")
    models_root = tmp_path / "models"
    models_root.mkdir()

    tricky_catalog = Catalog.model_validate(
        _make_catalog([_make_model("../outside"), _make_model("a\x00b")])
    )
    view = annotate_catalog(
        tricky_catalog,
        source="cache",
        adapter_versions={"kokoro": "1.0.0"},
        models_root=models_root,
    )
    assert all(not m.installed for m in view.models)
    assert all(not cp.revisions[0].installed for m in view.models for cp in m.checkpoints)


def test_rpc_catalog_get_and_refresh_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    remote_payload = _make_catalog([_make_model("kokoro")], updated_at="2026-11-22")
    body = json.dumps(remote_payload).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    notifier = _RecordingNotifier()

    class _CapturingServer(RpcServer):
        def notify(self, method: str, params: Any = None) -> None:
            notifier(method, params)
            super().notify(method, params)

    stdin = io.BytesIO()
    stdout = io.BytesIO()
    server = _CapturingServer(stdin=stdin, stdout=stdout)
    manager = register_all(server)
    try:
        # 1. Before refresh, catalog.get serves bundled.
        resp_get_1 = server.handle_line('{"jsonrpc":"2.0","id":1,"method":"catalog.get"}')
        assert resp_get_1 is not None
        assert resp_get_1["result"]["source"] == "bundled"

        # 2. Invalid params rejected with -32602.
        resp_bad = server.handle_line(
            '{"jsonrpc":"2.0","id":2,"method":"catalog.refresh","params":{"extra":1}}'
        )
        assert resp_bad is not None
        assert resp_bad["error"]["code"] == -32602

        # 3. catalog.refresh submits job and populates cache.
        with _run_server(Handler) as base_url:
            monkeypatch.setenv("SKALD_CATALOG_URL", f"{base_url}/catalog.json")
            resp_refresh = server.handle_line('{"jsonrpc":"2.0","id":3,"method":"catalog.refresh"}')
            assert resp_refresh is not None
            job_id = resp_refresh["result"]["job_id"]
            finished = notifier.wait_finished(job_id)
            assert finished["status"] == "succeeded"

        # 4. Subsequent catalog.get serves cache.
        resp_get_2 = server.handle_line('{"jsonrpc":"2.0","id":4,"method":"catalog.get"}')
        assert resp_get_2 is not None
        assert resp_get_2["result"]["source"] == "cache"
        assert resp_get_2["result"]["updated_at"] == "2026-11-22"
    finally:
        manager.shutdown(timeout=2.0)
        # Keep reference to catalog_client used by register_all.
        assert catalog_client.CATALOG_CACHE_FILENAME == "catalog.cache.json"
