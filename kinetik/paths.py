# SPDX-License-Identifier: GPL-3.0-or-later
"""XDG base directories."""

from __future__ import annotations

import os
from pathlib import Path

from . import APP_ID


def _base(var: str, fallback: str) -> Path:
    base = os.environ.get(var, "")
    return Path(base) if base and os.path.isabs(base) else Path.home() / fallback


def config_dir() -> Path:
    return _base("XDG_CONFIG_HOME", ".config") / APP_ID


def cache_dir() -> Path:
    return _base("XDG_CACHE_HOME", ".cache") / APP_ID


def thumbs_dir() -> Path:
    return cache_dir() / "thumbs"


def wekde_config_dir() -> Path:
    """Per-wallpaper options of the Wallpaper Engine KDE plugin (its pyext.py uses this)."""
    return _base("XDG_CONFIG_HOME", ".config") / "wekde" / "wallpaper"


LEGACY_APP_IDS = ("livewall",)


def migrate_legacy() -> None:
    """Move settings from the pre-release name (Livewall) once; drop its cache."""
    import shutil
    for old in LEGACY_APP_IDS:
        src, dst = _base("XDG_CONFIG_HOME", ".config") / old, config_dir()
        if src.is_dir() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
        shutil.rmtree(_base("XDG_CACHE_HOME", ".cache") / old, ignore_errors=True)


def default_library() -> Path:
    return Path.home() / "Videos" / "Live Wallpapers"
