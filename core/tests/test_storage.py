"""Tests for Decision F1 storage directory resolution."""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from skald_core.storage import (
    get_data_dir,
    get_storage_dir,
    models_dir,
    packs_dir,
    python_dir,
    uv_cache_dir,
)


def test_storage_precedence_skald_storage_dir_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "custom-storage"
    monkeypatch.setenv("SKALD_STORAGE_DIR", str(explicit))
    monkeypatch.setenv("SKALD_DEV_DATA", str(tmp_path / "devdata"))

    assert get_storage_dir() == explicit
    assert packs_dir() == explicit / "packs"
    assert models_dir() == explicit / "models"
    assert uv_cache_dir() == explicit / "uv-cache"
    assert python_dir() == explicit / "python"


def test_storage_falls_back_to_skald_dev_data_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev_data = tmp_path / "devdata"
    monkeypatch.delenv("SKALD_STORAGE_DIR", raising=False)
    monkeypatch.setenv("SKALD_DEV_DATA", str(dev_data))

    assert get_storage_dir() == dev_data / "storage"


def test_storage_platform_defaults_linux_and_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SKALD_STORAGE_DIR", raising=False)
    monkeypatch.delenv("SKALD_DEV_DATA", raising=False)

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    xdg = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    assert get_storage_dir() == xdg / "Skald"

    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert get_storage_dir() == Path.home() / ".local" / "share" / "Skald"

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    local_app = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app))
    assert get_storage_dir() == local_app / "Skald"


def test_data_dir_precedence_and_platform_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "electron-userdata"
    dev_data = tmp_path / "devdata"
    monkeypatch.setenv("SKALD_DATA_DIR", str(explicit))
    monkeypatch.setenv("SKALD_DEV_DATA", str(dev_data))
    assert get_data_dir() == explicit

    monkeypatch.delenv("SKALD_DATA_DIR", raising=False)
    assert get_data_dir() == dev_data

    monkeypatch.delenv("SKALD_DEV_DATA", raising=False)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    xdg_cfg = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_cfg))
    assert get_data_dir() == xdg_cfg / "Skald"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert get_data_dir() == Path.home() / ".config" / "Skald"

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    app_data = tmp_path / "AppDataRoaming"
    monkeypatch.setenv("APPDATA", str(app_data))
    assert get_data_dir() == app_data / "Skald"

    monkeypatch.delenv("APPDATA", raising=False)
    assert get_data_dir() == Path.home() / "AppData" / "Roaming" / "Skald"
