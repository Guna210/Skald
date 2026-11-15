"""Tests for catalog schema, JSON Schema export, and catalog validator."""

from __future__ import annotations

import copy
import hashlib
import http.server
import json
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from skald_core import net
from skald_core.catalog import validate as catalog_validate
from skald_core.catalog.schema import (
    COMMERCIAL_LICENSE_ALLOWLIST,
    Catalog,
    CatalogSource,
    build_file_url,
    export_catalog_schema,
    parse_semver,
)
from skald_core.catalog.validate import load_adapter_versions, validate_catalog

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


@pytest.fixture
def local_net_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear proxy env vars and zero backoff for local HTTP server tests."""
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


def _make_model(
    model_id: str = "kokoro",
    *,
    status: str = "active",
    family_adapter: str = "kokoro",
    min_adapter_version: str = "1.0.0",
    license_name: str = "Apache-2.0",
    commercial: bool = True,
    acknowledgement: str | None = None,
    file_format: str = "onnx",
    approved_exception: str | None = None,
    sha256: str = _VALID_SHA256,
    size: int = 128,
) -> dict[str, Any]:
    license_obj: dict[str, Any] = {
        "name": license_name,
        "url": "https://example.com/license",
        "commercial": commercial,
    }
    if acknowledgement is not None:
        license_obj["acknowledgement"] = acknowledgement

    file_obj: dict[str, Any] = {
        "path": f"{model_id}.bin",
        "format": file_format,
        "size": size,
        "sha256": sha256,
    }
    if approved_exception is not None:
        file_obj["approved_exception"] = approved_exception

    return {
        "id": model_id,
        "name": model_id.title(),
        "status": status,
        "family_adapter": family_adapter,
        "pack": None if family_adapter == "kokoro" else f"{family_adapter}-cpu",
        "summary": "Test model summary.",
        "license": license_obj,
        "languages": ["en-us"],
        "capabilities": ["presets"],
        "hardware": {"cpu": {"min_ram_gb": 4, "rtf_reference": None}, "cuda": None},
        "notes": {"watermark": None},
        "checkpoints": [
            {
                "id": f"{model_id}-cp1",
                "max_chars": 400,
                "default_revision": "r1",
                "revisions": [
                    {
                        "id": "r1",
                        "bundled": family_adapter == "kokoro",
                        "min_adapter_version": min_adapter_version,
                        "source": {
                            "host": "huggingface",
                            "repo": "example/model",
                            "ref": _VALID_HF_REF,
                        },
                        "files": [file_obj],
                        "changelog": "Initial release.",
                    }
                ],
            }
        ],
    }


def _make_catalog(models: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "min_app_version": "0.1.0",
        "updated_at": "2026-11-14",
        "models": models,
    }


def _write_adapters(tmp_path: Path, versions: dict[str, str]) -> Path:
    adapters_file = tmp_path / "adapters" / "__init__.py"
    adapters_file.parent.mkdir(parents=True, exist_ok=True)
    adapters_file.write_text(f"ADAPTER_VERSIONS = {versions!r}\n", encoding="utf-8")
    return adapters_file


def _write_cards(tmp_path: Path, model_ids: list[str]) -> Path:
    docs_dir = tmp_path / "docs" / "models"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for model_id in model_ids:
        (docs_dir / f"{model_id}.md").write_text(f"# {model_id}\n", encoding="utf-8")
    return docs_dir


def test_committed_catalog_schema_json_has_no_diff(tmp_path: Path) -> None:
    committed = (_REPO_ROOT / "catalog" / "catalog.schema.json").read_text(encoding="utf-8")
    regenerated_path = export_catalog_schema(tmp_path / "catalog.schema.json")
    assert regenerated_path.read_text(encoding="utf-8") == committed


def test_repo_catalog_json_validates_dev_and_fails_release() -> None:
    catalog_path = _REPO_ROOT / "catalog" / "catalog.json"
    assert validate_catalog(catalog_path) == []

    release_errors = validate_catalog(catalog_path, release=True)
    assert any("at least 3 active models" in err for err in release_errors)


def test_parse_semver() -> None:
    assert parse_semver("0.0.0") == (0, 0, 0)
    assert parse_semver("1.2.3") == (1, 2, 3)
    assert parse_semver("10.20.30") == (10, 20, 30)
    assert parse_semver("1.10.0") > parse_semver("1.2.0")

    for bad in ("1.2", "v1.0.0", "1.0.0-alpha", "01.0.0", "1.0.0+build", ""):
        with pytest.raises(ValueError):
            parse_semver(bad)


def test_build_file_url_and_source_validation() -> None:
    hf = CatalogSource(host="huggingface", repo="hexgrad/Kokoro-82M", ref=_VALID_HF_REF)
    assert build_file_url(hf, "weights/model.safetensors") == (
        f"https://huggingface.co/hexgrad/Kokoro-82M/resolve/{_VALID_HF_REF}/weights/model.safetensors"
    )

    gh = CatalogSource(
        host="github-release",
        repo="thewh1teagle/kokoro-onnx",
        ref="model-files-v1.1",
    )
    assert build_file_url(gh, "kokoro-v1.0.onnx") == (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
        "model-files-v1.1/kokoro-v1.0.onnx"
    )

    with pytest.raises(ValueError):
        CatalogSource(host="huggingface", repo="hexgrad/Kokoro-82M", ref="main")


def test_load_adapter_versions_missing_and_present(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist" / "__init__.py"
    assert load_adapter_versions(missing) == {}

    adapters_file = _write_adapters(tmp_path, {"kokoro": "1.0.0", "qwen": "0.2.1"})
    assert load_adapter_versions(adapters_file) == {"kokoro": "1.0.0", "qwen": "0.2.1"}


def test_valid_catalog_with_active_retired_noncommercial_and_pickle_exception(
    tmp_path: Path,
) -> None:
    models = [
        _make_model("kokoro", family_adapter="kokoro", license_name="Apache-2.0", commercial=True),
        _make_model("m2", family_adapter="m2", license_name="MIT", commercial=True),
        _make_model(
            "m3",
            family_adapter="m3",
            license_name="Research-Only-1.0",
            commercial=False,
            acknowledgement="Personal non-commercial use only.",
            file_format="pickle",
            approved_exception="Approved by Orchestrator; loaded with weights_only=True.",
        ),
        _make_model(
            "retired_old",
            status="retired",
            family_adapter="kokoro",
            license_name="BSD-3-Clause",
            commercial=True,
        ),
    ]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(_make_catalog(models)), encoding="utf-8")

    adapters_file = _write_adapters(tmp_path, {"kokoro": "1.0.0", "m2": "1.0.0", "m3": "1.2.0"})
    docs_dir = _write_cards(tmp_path, ["kokoro", "m2", "m3"])  # retired_old needs no card

    errors = validate_catalog(
        catalog_path,
        release=True,
        adapters_path=adapters_file,
        models_doc_dir=docs_dir,
        use_git_diff=False,
    )
    assert errors == []


def test_commercial_allowlist_exact_names() -> None:
    assert COMMERCIAL_LICENSE_ALLOWLIST == {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "NVIDIA Open Model License",
    }


def _mutate_six_active() -> dict[str, Any]:
    return _make_catalog([_make_model(f"m{i}") for i in range(6)])


def _mutate_wrong_commercial_true_for_noncommercial() -> dict[str, Any]:
    return _make_catalog([_make_model("m0", license_name="CC-BY-NC-4.0", commercial=True)])


def _mutate_wrong_commercial_false_for_allowlisted() -> dict[str, Any]:
    return _make_catalog(
        [_make_model("m0", license_name="MIT", commercial=False, acknowledgement="Ack")]
    )


def _mutate_noncommercial_missing_ack() -> dict[str, Any]:
    return _make_catalog(
        [_make_model("m0", license_name="CC-BY-NC-4.0", commercial=False, acknowledgement=None)]
    )


def _mutate_duplicate_model_id() -> dict[str, Any]:
    return _make_catalog([_make_model("dup"), _make_model("dup")])


def _mutate_duplicate_checkpoint_id() -> dict[str, Any]:
    m = _make_model("m0")
    m["checkpoints"].append(copy.deepcopy(m["checkpoints"][0]))
    return _make_catalog([m])


def _mutate_duplicate_revision_id() -> dict[str, Any]:
    m = _make_model("m0")
    cp = m["checkpoints"][0]
    cp["revisions"].append(copy.deepcopy(cp["revisions"][0]))
    return _make_catalog([m])


def _mutate_missing_default_revision() -> dict[str, Any]:
    m = _make_model("m0")
    m["checkpoints"][0]["default_revision"] = "r999"
    return _make_catalog([m])


def _mutate_pickle_without_exception() -> dict[str, Any]:
    return _make_catalog([_make_model("m0", file_format="pickle", approved_exception=None)])


def _mutate_pickle_blank_exception() -> dict[str, Any]:
    return _make_catalog([_make_model("m0", file_format="pickle", approved_exception="   ")])


@pytest.mark.parametrize(
    ("case_name", "payload_fn", "adapters", "cards", "release", "expected_substr"),
    [
        (
            "6_active_models",
            _mutate_six_active,
            {"kokoro": "1.0.0"},
            [f"m{i}" for i in range(6)],
            False,
            "maximum allowed is 5",
        ),
        (
            "wrong_commercial_true_for_noncommercial",
            _mutate_wrong_commercial_true_for_noncommercial,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "requires commercial=False",
        ),
        (
            "wrong_commercial_false_for_allowlisted",
            _mutate_wrong_commercial_false_for_allowlisted,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "requires commercial=True",
        ),
        (
            "noncommercial_missing_ack",
            _mutate_noncommercial_missing_ack,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "acknowledgement",
        ),
        (
            "missing_model_card",
            lambda: _make_catalog([_make_model("m0")]),
            {"kokoro": "1.0.0"},
            [],
            False,
            "missing model card",
        ),
        (
            "unknown_adapter",
            lambda: _make_catalog([_make_model("m0", family_adapter="nonexistent")]),
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "unknown family_adapter",
        ),
        (
            "adapter_version_too_low",
            lambda: _make_catalog(
                [_make_model("m0", family_adapter="kokoro", min_adapter_version="2.0.0")]
            ),
            {"kokoro": "1.5.0"},
            ["m0"],
            False,
            ">= 2.0.0",
        ),
        (
            "duplicate_model_id",
            _mutate_duplicate_model_id,
            {"kokoro": "1.0.0"},
            ["dup"],
            False,
            "Duplicate model id",
        ),
        (
            "duplicate_checkpoint_id",
            _mutate_duplicate_checkpoint_id,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "Duplicate checkpoint id",
        ),
        (
            "duplicate_revision_id",
            _mutate_duplicate_revision_id,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "Duplicate revision id",
        ),
        (
            "missing_default_revision",
            _mutate_missing_default_revision,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "default_revision",
        ),
        (
            "pickle_without_exception",
            _mutate_pickle_without_exception,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "approved_exception",
        ),
        (
            "pickle_blank_exception",
            _mutate_pickle_blank_exception,
            {"kokoro": "1.0.0"},
            ["m0"],
            False,
            "approved_exception",
        ),
        (
            "release_fewer_than_3_active",
            lambda: _make_catalog(
                [_make_model("m0"), _make_model("m1"), _make_model("m2", status="retired")]
            ),
            {"kokoro": "1.0.0"},
            ["m0", "m1"],
            True,
            "at least 3 active models",
        ),
    ],
)
def test_invalid_catalogs_table(
    tmp_path: Path,
    case_name: str,
    payload_fn: Any,
    adapters: dict[str, str],
    cards: list[str],
    release: bool,
    expected_substr: str,
) -> None:
    catalog_path = tmp_path / f"{case_name}.json"
    catalog_path.write_text(json.dumps(payload_fn()), encoding="utf-8")
    adapters_file = _write_adapters(tmp_path, adapters)
    docs_dir = _write_cards(tmp_path, cards)

    errors = validate_catalog(
        catalog_path,
        release=release,
        adapters_path=adapters_file,
        models_doc_dir=docs_dir,
        use_git_diff=False,
    )
    assert errors, f"Expected errors for {case_name}"
    assert any(expected_substr in err for err in errors), f"{case_name}: {errors}"


def test_network_bad_hash_and_changed_only_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_net_env: None,
) -> None:
    good_bytes = b"valid-model-weights"
    good_sha = hashlib.sha256(good_bytes).hexdigest()
    bad_sha = "0" * 64

    unchanged_bytes = b"unchanged-model-weights"
    unchanged_sha = hashlib.sha256(unchanged_bytes).hexdigest()

    requests_seen: list[tuple[str, str]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_for_path(self, send_body: bool) -> None:
            if self.path == "/unchanged.bin":
                payload = unchanged_bytes
            elif self.path == "/changed.bin":
                payload = good_bytes
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)

        def do_HEAD(self) -> None:
            requests_seen.append(("HEAD", self.path))
            self._send_for_path(send_body=False)

        def do_GET(self) -> None:
            requests_seen.append(("GET", self.path))
            self._send_for_path(send_body=True)

    with _run_server(Handler) as base_url:
        monkeypatch.setattr(
            catalog_validate,
            "build_file_url",
            lambda _src, path: f"{base_url}/{path}",
        )

        unchanged_model = _make_model("unchanged", sha256=unchanged_sha, size=len(unchanged_bytes))
        base_catalog = Catalog.model_validate(_make_catalog([unchanged_model]))

        # Case 1: changed entry has bad hash -> fails download verification; unchanged only HEADed.
        bad_changed_model = _make_model("changed", sha256=bad_sha, size=len(good_bytes))
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(_make_catalog([unchanged_model, bad_changed_model])),
            encoding="utf-8",
        )
        adapters_file = _write_adapters(tmp_path, {"kokoro": "1.0.0"})
        docs_dir = _write_cards(tmp_path, ["unchanged", "changed"])

        errors = validate_catalog(
            catalog_path,
            network=True,
            adapters_path=adapters_file,
            models_doc_dir=docs_dir,
            base_catalog=base_catalog,
            use_git_diff=False,
        )
        assert len(errors) == 1
        assert "Download verification failed" in errors[0]
        assert ("HEAD", "/unchanged.bin") in requests_seen
        assert ("GET", "/unchanged.bin") not in requests_seen
        assert ("HEAD", "/changed.bin") in requests_seen
        assert ("GET", "/changed.bin") in requests_seen

        # Case 2: changed entry has good hash -> passes.
        requests_seen.clear()
        good_changed_model = _make_model("changed", sha256=good_sha, size=len(good_bytes))
        catalog_path.write_text(
            json.dumps(_make_catalog([unchanged_model, good_changed_model])),
            encoding="utf-8",
        )
        errors_ok = validate_catalog(
            catalog_path,
            network=True,
            adapters_path=adapters_file,
            models_doc_dir=docs_dir,
            base_catalog=base_catalog,
            use_git_diff=False,
        )
        assert errors_ok == []

        # Case 3: unreachable URL (404) -> fails URL reachability check.
        missing_model = _make_model("missing", sha256=good_sha, size=len(good_bytes))
        catalog_path.write_text(json.dumps(_make_catalog([missing_model])), encoding="utf-8")
        docs_dir_missing = _write_cards(tmp_path, ["missing"])
        errors_404 = validate_catalog(
            catalog_path,
            network=True,
            adapters_path=adapters_file,
            models_doc_dir=docs_dir_missing,
            base_catalog=base_catalog,
            use_git_diff=False,
        )
        assert len(errors_404) == 1
        assert "URL unreachable" in errors_404[0]


def test_changed_revision_keys_diff_cases() -> None:
    base_model = _make_model("m1", sha256="a" * 64, size=100)
    base_catalog = Catalog.model_validate(_make_catalog([base_model]))

    # (a) unchanged -> not in changed keys
    same_catalog = Catalog.model_validate(_make_catalog([copy.deepcopy(base_model)]))
    assert catalog_validate._changed_revision_keys(same_catalog, base_catalog) == set()

    # (b) same revision id with different sha256 -> in changed keys
    diff_sha_model = _make_model("m1", sha256="b" * 64, size=100)
    diff_sha_catalog = Catalog.model_validate(_make_catalog([diff_sha_model]))
    assert catalog_validate._changed_revision_keys(diff_sha_catalog, base_catalog) == {
        ("m1", "m1-cp1", "r1")
    }

    # (c) same revision id with different size -> in changed keys
    diff_size_model = _make_model("m1", sha256="a" * 64, size=200)
    diff_size_catalog = Catalog.model_validate(_make_catalog([diff_size_model]))
    assert catalog_validate._changed_revision_keys(diff_size_catalog, base_catalog) == {
        ("m1", "m1-cp1", "r1")
    }

    # (d) new revision id in existing checkpoint -> only new revision in changed keys
    new_rev_model = copy.deepcopy(base_model)
    new_rev = copy.deepcopy(new_rev_model["checkpoints"][0]["revisions"][0])
    new_rev["id"] = "r2"
    new_rev_model["checkpoints"][0]["revisions"].append(new_rev)
    new_rev_catalog = Catalog.model_validate(_make_catalog([new_rev_model]))
    assert catalog_validate._changed_revision_keys(new_rev_catalog, base_catalog) == {
        ("m1", "m1-cp1", "r2")
    }

    # (e) new model -> in changed keys
    new_model = _make_model("m2", sha256="c" * 64, size=50)
    new_model_catalog = Catalog.model_validate(
        _make_catalog([copy.deepcopy(base_model), new_model])
    )
    assert catalog_validate._changed_revision_keys(new_model_catalog, base_catalog) == {
        ("m2", "m2-cp1", "r1")
    }


def test_load_base_catalog_from_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path = tmp_path / "catalog.json"
    sample_json = json.dumps(_make_catalog([]))

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout=sample_json, stderr=""
        ),
    )
    loaded = catalog_validate._load_base_catalog_from_git(catalog_path)
    assert loaded is not None
    assert loaded.models == []

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=128, stdout="", stderr="fatal: not found"
        ),
    )
    assert catalog_validate._load_base_catalog_from_git(catalog_path) is None

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="{not-valid", stderr=""
        ),
    )
    assert catalog_validate._load_base_catalog_from_git(catalog_path) is None


def test_network_warns_and_checks_all_when_base_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    local_net_env: None,
) -> None:
    payload = b"fallback-weights"
    payload_sha = hashlib.sha256(payload).hexdigest()
    requests_seen: list[tuple[str, str]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle(self, send_body: bool) -> None:
            requests_seen.append((self.command, self.path))
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)

        def do_HEAD(self) -> None:
            self._handle(send_body=False)

        def do_GET(self) -> None:
            self._handle(send_body=True)

    with _run_server(Handler) as base_url:
        monkeypatch.setattr(
            catalog_validate,
            "build_file_url",
            lambda _src, path: f"{base_url}/{path}",
        )
        monkeypatch.setattr(
            catalog_validate,
            "_load_base_catalog_from_git",
            lambda _path: None,
        )

        model = _make_model("m1", sha256=payload_sha, size=len(payload))
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog([model])), encoding="utf-8")
        adapters_file = _write_adapters(tmp_path, {"kokoro": "1.0.0"})
        docs_dir = _write_cards(tmp_path, ["m1"])

        errors = validate_catalog(
            catalog_path,
            network=True,
            adapters_path=adapters_file,
            models_doc_dir=docs_dir,
            use_git_diff=True,
        )
        assert errors == []
        captured = capsys.readouterr()
        assert (
            "origin/master catalog not available; treating all entries as changed" in captured.err
        )
        assert ("HEAD", "/m1.bin") in requests_seen
        assert ("GET", "/m1.bin") in requests_seen


def test_active_model_cap_boundaries(tmp_path: Path) -> None:
    adapters_file = _write_adapters(tmp_path, {"kokoro": "1.0.0"})
    docs_dir = _write_cards(tmp_path, [f"a{i}" for i in range(5)])

    # Exactly 5 active passes
    five_active = [_make_model(f"a{i}") for i in range(5)]
    p5 = tmp_path / "five.json"
    p5.write_text(json.dumps(_make_catalog(five_active)), encoding="utf-8")
    assert (
        validate_catalog(
            p5,
            adapters_path=adapters_file,
            models_doc_dir=docs_dir,
            use_git_diff=False,
        )
        == []
    )

    # 5 active + 2 retired passes
    five_plus_two = five_active + [
        _make_model("r0", status="retired"),
        _make_model("r1", status="retired"),
    ]
    p5_2 = tmp_path / "five_plus_two.json"
    p5_2.write_text(json.dumps(_make_catalog(five_plus_two)), encoding="utf-8")
    assert (
        validate_catalog(
            p5_2,
            adapters_path=adapters_file,
            models_doc_dir=docs_dir,
            use_git_diff=False,
        )
        == []
    )


def test_trailing_newline_rejected_in_patterns() -> None:
    with pytest.raises(ValueError):
        parse_semver("1.0.0\n")

    bad_sha_catalog = _make_catalog([_make_model("m0", sha256=f"{_VALID_SHA256}\n")])
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad_sha_catalog)

    bad_hf_catalog = _make_catalog([_make_model("m0")])
    bad_hf_catalog["models"][0]["checkpoints"][0]["revisions"][0]["source"]["ref"] = (
        f"{_VALID_HF_REF}\n"
    )
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad_hf_catalog)

    bad_date_catalog = _make_catalog([])
    bad_date_catalog["updated_at"] = "2026-11-14\n"
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad_date_catalog)


def test_extra_forbid_rejects_typo_keys() -> None:
    payload = _make_catalog([_make_model("m0")])
    payload["models"][0]["license"]["comercial"] = True
    with pytest.raises(ValidationError):
        Catalog.model_validate(payload)


def test_whitespace_and_updated_at_format_and_duplicate_file_paths() -> None:
    # Whitespace-only license url
    bad_url = _make_catalog([_make_model("m0")])
    bad_url["models"][0]["license"]["url"] = "   "
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad_url)

    # Whitespace-only file path
    bad_path = _make_catalog([_make_model("m0")])
    bad_path["models"][0]["checkpoints"][0]["revisions"][0]["files"][0]["path"] = "   "
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad_path)

    # Compact YYYYMMDD updated_at rejected
    bad_updated = _make_catalog([])
    bad_updated["updated_at"] = "20261114"
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad_updated)

    # Duplicate file paths within one revision rejected
    dup_files = _make_catalog([_make_model("m0")])
    rev = dup_files["models"][0]["checkpoints"][0]["revisions"][0]
    rev["files"].append(copy.deepcopy(rev["files"][0]))
    with pytest.raises(ValidationError):
        Catalog.model_validate(dup_files)
