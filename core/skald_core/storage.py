"""Model storage directory resolution (SPEC B9, Decision F1)."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def get_data_dir() -> Path:
    """Resolve the `<userData>` directory.

    1. ``SKALD_DATA_DIR`` if set and non-empty (passed by Electron main process).
    2. ``SKALD_DEV_DATA`` if set and non-empty (dev environment).
    3. Platform default matching Electron userData: Windows ``%APPDATA%\\Skald``,
       Linux ``$XDG_CONFIG_HOME/Skald`` (default ``~/.config/Skald``).
    """
    explicit = os.environ.get("SKALD_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit)

    dev_data = os.environ.get("SKALD_DEV_DATA", "").strip()
    if dev_data:
        return Path(dev_data)

    if platform.system().lower() == "windows":
        app_data = os.environ.get("APPDATA", "").strip()
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
        return base / "Skald"

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / "Skald"


def get_storage_dir() -> Path:
    """Resolve the `<storage>` directory following Decision F1 precedence.

    1. ``SKALD_STORAGE_DIR`` if set and non-empty (user-chosen storage folder).
    2. ``<SKALD_DEV_DATA>/storage`` if ``SKALD_DEV_DATA`` is set and non-empty.
    3. Platform default: Windows ``%LOCALAPPDATA%\\Skald``,
       Linux ``$XDG_DATA_HOME/Skald`` (default ``~/.local/share/Skald``).
    """
    explicit = os.environ.get("SKALD_STORAGE_DIR", "").strip()
    if explicit:
        return Path(explicit)

    dev_data = os.environ.get("SKALD_DEV_DATA", "").strip()
    if dev_data:
        return Path(dev_data) / "storage"

    if platform.system().lower() == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "Skald"

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "Skald"


def packs_dir(storage_dir: Path | None = None) -> Path:
    """Return `<storage>/packs`."""
    return (get_storage_dir() if storage_dir is None else storage_dir) / "packs"


def models_dir(storage_dir: Path | None = None) -> Path:
    """Return `<storage>/models`."""
    return (get_storage_dir() if storage_dir is None else storage_dir) / "models"


def uv_cache_dir(storage_dir: Path | None = None) -> Path:
    """Return `<storage>/uv-cache`."""
    return (get_storage_dir() if storage_dir is None else storage_dir) / "uv-cache"


def python_dir(storage_dir: Path | None = None) -> Path:
    """Return `<storage>/python`."""
    return (get_storage_dir() if storage_dir is None else storage_dir) / "python"
