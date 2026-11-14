"""Tests for project folder storage, atomic writes, IDs, migrations, and project.* RPC."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skald_core.project import (
    MAX_BASE_SEED,
    MIGRATIONS,
    ProjectPaths,
    ProjectStore,
    atomic_write_json,
    migrate,
    new_id,
    register,
)
from skald_core.rpc import INVALID_PARAMS, RpcServer, SkaldError
from skald_core.schemas import ProjectManifest


def test_create_open_save_round_trip_and_json_formatting(tmp_path: Path) -> None:
    project_dir = tmp_path / "new_book"
    store = ProjectStore()

    created = store.create(project_dir, "My Book", base_seed=42)
    assert isinstance(created, ProjectManifest)
    assert created.schema_version == 1
    assert created.name == "My Book"
    assert created.base_seed == 42
    assert created.created_at.endswith("Z")
    assert created.updated_at == created.created_at
    assert created.render_ids == []
    assert created.voice_ids == []

    # Directories other than the project root are created on demand, not up front.
    assert list(project_dir.iterdir()) == [project_dir / "skald-project.json"]

    # Mutate in-memory manifest metadata (e.g. render/voice ids) and save.
    assert store.manifest is not None
    store.manifest.render_ids.append("rn_1234abcd")
    store.manifest.voice_ids.append("v_abcd1234")
    saved = store.save()
    assert saved.render_ids == ["rn_1234abcd"]
    assert saved.voice_ids == ["v_abcd1234"]

    raw_bytes = (project_dir / "skald-project.json").read_bytes()
    assert b"\r\n" not in raw_bytes
    assert raw_bytes.endswith(b"\n")
    raw_text = raw_bytes.decode("utf-8")
    assert "\n  " in raw_text

    reopened_store = ProjectStore()
    reopened = reopened_store.open(project_dir)
    assert reopened == saved


def test_create_random_base_seed_bounds_and_zero_seed(tmp_path: Path) -> None:
    store = ProjectStore()
    m1 = store.create(tmp_path / "p1", "Random Seed")
    assert 0 <= m1.base_seed < MAX_BASE_SEED

    m_zero = store.create(tmp_path / "p0", "Zero Seed", base_seed=0)
    assert m_zero.base_seed == 0

    with pytest.raises(ValueError):
        store.create(tmp_path / "p_neg", "Bad Seed", base_seed=-1)
    with pytest.raises(ValueError):
        store.create(tmp_path / "p_big", "Bad Seed", base_seed=MAX_BASE_SEED)


def test_non_ascii_and_spaces_in_path_and_name(tmp_path: Path) -> None:
    project_dir = tmp_path / "Bøker og Lyd — Þórsmörk 日本語"
    name = "Saga af Þórsmörk — カフェ 🎙️"

    store = ProjectStore()
    created = store.create(project_dir, name, base_seed=7)
    assert created.name == name

    raw_text = (project_dir / "skald-project.json").read_text(encoding="utf-8")
    # ensure_ascii=False preserves non-ASCII characters directly in UTF-8 JSON.
    assert name in raw_text

    reopened = ProjectStore().open(project_dir)
    assert reopened == created


def test_atomic_write_crash_leaves_old_manifest_and_open_ignores_leftover_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "crash_safe"
    store = ProjectStore()
    initial = store.create(project_dir, "Initial Title", base_seed=100)

    # Simulate a crash during os.replace while saving updated data.
    def boom_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated power loss during os.replace")

    monkeypatch.setattr(os, "replace", boom_replace)
    assert store.manifest is not None
    store.manifest.name = "Partially Saved Title"
    with pytest.raises(OSError, match="simulated power loss"):
        store.save()

    monkeypatch.undo()

    # No orphaned temp file left behind from handled failure, and old manifest is intact.
    assert [p.name for p in project_dir.iterdir()] == ["skald-project.json"]
    assert ProjectStore().open(project_dir) == initial

    # Simulate a hard kill that left a temp file behind in the project folder.
    leftover_tmp = project_dir / ".skald-project.json.hardkill.tmp"
    leftover_tmp.write_text("{corrupt partial write", encoding="utf-8")
    assert ProjectStore().open(project_dir) == initial


def test_atomic_write_json_writes_lf_and_utf8(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "data.json"
    atomic_write_json(target, {"title": "Café — 日本語", "items": [1, 2]})
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    text = raw.decode("utf-8")
    assert "Café — 日本語" in text
    assert json.loads(text) == {"title": "Café — 日本語", "items": [1, 2]}


def test_create_folder_not_empty_and_existing_project_hint(tmp_path: Path) -> None:
    non_empty = tmp_path / "has_file"
    non_empty.mkdir()
    (non_empty / "notes.txt").write_text("hello", encoding="utf-8")

    store = ProjectStore()
    with pytest.raises(SkaldError) as exc_info:
        store.create(non_empty, "Book")
    assert exc_info.value.kind == "folder_not_empty"

    # Existing Skald project gets folder_not_empty with the specific hint.
    existing_project = tmp_path / "existing_proj"
    store.create(existing_project, "Existing", base_seed=1)
    with pytest.raises(SkaldError) as exc_existing:
        store.create(existing_project, "Duplicate")
    assert exc_existing.value.kind == "folder_not_empty"
    assert (
        exc_existing.value.hint == "This folder already contains a Skald project; open it instead."
    )

    # A regular file at the target path is also rejected with folder_not_empty.
    file_target = tmp_path / "regular_file"
    file_target.write_text("not a dir", encoding="utf-8")
    with pytest.raises(SkaldError) as exc_file:
        store.create(file_target, "File Target")
    assert exc_file.value.kind == "folder_not_empty"


def test_create_ignores_os_junk_files(tmp_path: Path) -> None:
    junk_dir = tmp_path / "os_junk"
    junk_dir.mkdir()
    for name in ("desktop.ini", "Thumbs.db", ".DS_Store", "Desktop.ini"):
        (junk_dir / name).write_text("junk", encoding="utf-8")

    manifest = ProjectStore().create(junk_dir, "Clean Enough", base_seed=9)
    assert manifest.name == "Clean Enough"
    assert (junk_dir / "skald-project.json").is_file()


def test_open_project_invalid_cases(tmp_path: Path) -> None:
    store = ProjectStore()

    # Missing folder / missing manifest
    with pytest.raises(SkaldError) as missing_dir:
        store.open(tmp_path / "does_not_exist")
    assert missing_dir.value.kind == "project_invalid"

    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(SkaldError) as missing_manifest:
        store.open(empty_dir)
    assert missing_manifest.value.kind == "project_invalid"

    # Malformed JSON
    bad_json_dir = tmp_path / "bad_json"
    bad_json_dir.mkdir()
    (bad_json_dir / "skald-project.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SkaldError) as bad_json:
        store.open(bad_json_dir)
    assert bad_json.value.kind == "project_invalid"

    # Non-object JSON
    list_json_dir = tmp_path / "list_json"
    list_json_dir.mkdir()
    (list_json_dir / "skald-project.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SkaldError) as list_json:
        store.open(list_json_dir)
    assert list_json.value.kind == "project_invalid"

    # Invalid UTF-8
    bad_utf8_dir = tmp_path / "bad_utf8"
    bad_utf8_dir.mkdir()
    (bad_utf8_dir / "skald-project.json").write_bytes(b"\xff\xfe{}")
    with pytest.raises(SkaldError) as bad_utf8:
        store.open(bad_utf8_dir)
    assert bad_utf8.value.kind == "project_invalid"

    # Missing required fields
    incomplete_dir = tmp_path / "incomplete"
    incomplete_dir.mkdir()
    (incomplete_dir / "skald-project.json").write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(SkaldError) as incomplete:
        store.open(incomplete_dir)
    assert incomplete.value.kind == "project_invalid"

    # Newer schema_version
    newer_dir = tmp_path / "newer_version"
    newer_dir.mkdir()
    (newer_dir / "skald-project.json").write_text(
        json.dumps(
            {
                "schema_version": 99,
                "name": "Future Book",
                "created_at": "2027-01-01T00:00:00Z",
                "updated_at": "2027-01-01T00:00:00Z",
                "base_seed": 1,
                "render_ids": [],
                "voice_ids": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SkaldError) as newer:
        store.open(newer_dir)
    assert newer.value.kind == "project_invalid"
    assert newer.value.hint is not None
    assert "newer Skald" in newer.value.hint


def test_migration_hook_noop_and_fake_v0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    v1_raw: dict[str, Any] = {
        "schema_version": 1,
        "name": "Current",
        "created_at": "2026-11-14T00:00:00Z",
        "updated_at": "2026-11-14T00:00:00Z",
        "base_seed": 12,
        "render_ids": [],
        "voice_ids": [],
    }
    assert migrate(v1_raw) == v1_raw

    def fake_v0_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "name": raw["title"],
            "created_at": raw["created"],
            "updated_at": raw["created"],
            "base_seed": raw["seed"],
            "render_ids": [],
            "voice_ids": [],
        }

    v0_raw = {
        "schema_version": 0,
        "title": "Legacy Book",
        "created": "2026-01-01T00:00:00Z",
        "seed": 5,
    }
    migrated = migrate(v0_raw, migrations={0: fake_v0_to_v1})
    assert migrated["schema_version"] == 1
    assert migrated["name"] == "Legacy Book"

    # Without a registered v0 migrator, v0 is rejected as project_invalid.
    with pytest.raises(SkaldError) as unmigrated:
        migrate(v0_raw)
    assert unmigrated.value.kind == "project_invalid"

    # With v0 registered in MIGRATIONS, ProjectStore.open upgrades and validates it.
    monkeypatch.setitem(MIGRATIONS, 0, fake_v0_to_v1)
    v0_dir = tmp_path / "v0_project"
    v0_dir.mkdir()
    (v0_dir / "skald-project.json").write_text(json.dumps(v0_raw), encoding="utf-8")
    opened = ProjectStore().open(v0_dir)
    assert opened.schema_version == 1
    assert opened.name == "Legacy Book"
    assert opened.base_seed == 5


@pytest.mark.parametrize("prefix", ["v_", "rn_", "ch_", "p_"])
def test_new_id_format_and_prefix_validation(prefix: str) -> None:
    pattern = re.compile(rf"^{re.escape(prefix)}[a-z0-9]{{8}}$")
    ids = {new_id(prefix) for _ in range(20)}
    assert all(pattern.match(val) for val in ids)
    assert len(ids) == 20


@pytest.mark.parametrize("bad_prefix", ["", "v", "s_", "ck_", "x_"])
def test_new_id_rejects_unknown_prefixes(bad_prefix: str) -> None:
    with pytest.raises(ValueError):
        new_id(bad_prefix)


def test_project_paths_and_relative_conversion(tmp_path: Path) -> None:
    root = tmp_path / "My Book"
    paths = ProjectPaths(root)

    assert paths.manifest == root / "skald-project.json"
    assert paths.source_file() == root / "source" / "original.epub"
    assert paths.book == root / "book.json"
    assert paths.lexicon == root / "lexicon.json"
    assert paths.assignments == root / "assignments.json"
    assert paths.voices_lock == root / "voices.lock.json"
    assert paths.models_lock == root / "models.lock.json"
    assert paths.chunk_cache("abc123") == root / "cache" / "chunks" / "abc123.flac"
    assert paths.render_record("rn_1234abcd") == root / "renders" / "rn_1234abcd" / "render.json"
    assert (
        paths.render_chapter("rn_1234abcd", 3)
        == root / "renders" / "rn_1234abcd" / "chapters" / "03.flac"
    )
    assert paths.render_qc("rn_1234abcd") == root / "renders" / "rn_1234abcd" / "qc.json"
    assert paths.render_exports_dir("rn_1234abcd") == root / "renders" / "rn_1234abcd" / "exports"

    rel = paths.to_relative(paths.render_chapter("rn_1234abcd", 3))
    assert rel == "renders/rn_1234abcd/chapters/03.flac"
    assert paths.from_relative(rel) == root / "renders" / "rn_1234abcd" / "chapters" / "03.flac"

    with pytest.raises(ValueError):
        paths.to_relative(tmp_path / "outside.txt")
    for bad_rel in ("", "/abs/path", "../escape", "a\\b", "C:drive/file"):
        with pytest.raises(ValueError):
            paths.from_relative(bad_rel)


def test_rpc_project_create_open_save_and_save_without_open(tmp_path: Path) -> None:
    server = RpcServer(stdin=io.BytesIO(), stdout=io.BytesIO())
    store = register(server)

    # project.save with nothing open -> -32602 with kind "internal".
    save_empty = server.handle_line('{"jsonrpc":"2.0","id":1,"method":"project.save"}')
    assert save_empty is not None
    assert save_empty["error"]["code"] == INVALID_PARAMS
    assert save_empty["error"]["data"]["kind"] == "internal"

    proj_a = tmp_path / "Project A"
    create_resp = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "project.create",
                "params": {"path": str(proj_a), "name": "Book A", "base_seed": 11},
            }
        )
    )
    assert create_resp is not None
    assert create_resp["result"]["name"] == "Book A"
    assert create_resp["result"]["base_seed"] == 11

    proj_b = tmp_path / "Project B"
    ProjectStore().create(proj_b, "Book B", base_seed=22)

    open_resp = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "project.open",
                "params": {"path": str(proj_b)},
            }
        )
    )
    assert open_resp is not None
    assert open_resp["result"]["name"] == "Book B"
    assert store.root == proj_b.resolve()

    assert store.manifest is not None
    store.manifest.voice_ids.append("v_0000aaaa")
    save_resp = server.handle_line('{"jsonrpc":"2.0","id":4,"method":"project.save"}')
    assert save_resp is not None
    assert save_resp["result"]["voice_ids"] == ["v_0000aaaa"]
    assert ProjectStore().open(proj_b).voice_ids == ["v_0000aaaa"]


@pytest.mark.timeout(10)
def test_rpc_project_methods_over_stdio_subprocess(tmp_path: Path) -> None:
    project_dir = tmp_path / "Subprocess — Þórsmörk"
    requests = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "project.save"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "project.create",
                "params": {"path": str(project_dir), "name": "Saga 日本語", "base_seed": 77},
            },
            ensure_ascii=False,
        ),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "project.save"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "project.open",
                "params": {"path": str(project_dir)},
            },
            ensure_ascii=False,
        ),
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "system.shutdown"}),
    ]
    env = {**os.environ, "SKALD_LOG_DIR": str(tmp_path / "logs")}
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core"],
        input=("\n".join(requests) + "\n").encode("utf-8"),
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr.decode("utf-8")

    responses = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line]
    assert len(responses) == 5
    assert responses[0]["error"]["code"] == INVALID_PARAMS
    assert responses[0]["error"]["data"]["kind"] == "internal"
    assert responses[1]["result"]["name"] == "Saga 日本語"
    assert responses[1]["result"]["base_seed"] == 77
    assert responses[2]["result"]["name"] == "Saga 日本語"
    assert responses[3]["result"]["name"] == "Saga 日本語"
    assert responses[4] == {"jsonrpc": "2.0", "id": 5, "result": {"ok": True}}
