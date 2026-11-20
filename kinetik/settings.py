# SPDX-License-Identifier: GPL-3.0-or-later
"""App settings, per-wallpaper options, favourites and playlists (JSON in ~/.config/kinetik)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, List

from . import paths

# --- choices shared by the UI and the engine ------------------------------------------------
PAUSE_CHOICES = ["Fullscreen or maximized window", "Any window focused", "Any window visible", "Never"]
AUDIO_CHOICES = ["Always muted", "Muted while a window is maximized", "Muted while a window is focused",
                 "Muted while a window is visible", "Never muted"]
BLUR_CHOICES = ["Never", "Window maximized or fullscreen", "Window focused", "Window visible",
                "Wallpaper paused", "Always"]
SCALING = ["fill", "fit", "stretch"]
SCALING_LABELS = ["Fill", "Fit", "Stretch"]
SCALING_TIPS = ["Cover the whole screen, cropping the edges", "Show everything, with bars around it",
                "Stretch to the screen, ignoring proportions"]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


@dataclass
class Settings:
    # performance
    pause: int = 0                 # PAUSE_CHOICES index
    fps: int = 30                  # Wallpaper Engine scenes
    mouse_input: bool = True       # scenes react to the mouse
    video_backend: int = 1         # WE videos: 0 Qt Multimedia, 1 mpv
    # audio
    audio: int = 0                 # AUDIO_CHOICES index
    volume: int = 60               # default volume %
    # look
    blur: int = 0                  # BLUR_CHOICES index
    blur_radius: int = 32
    crossfade: bool = True
    crossfade_ms: int = 1000
    background: str = "#000000"
    resume_last: bool = True
    # wallpaper engine
    we_random: bool = False
    we_random_minutes: int = 30
    # library / downloads
    library: str = str(paths.default_library())
    quality: int = 0               # 0 HD, 1 best (4K)
    safe: bool = True              # Workshop: only "Everyone"
    sort: int = 0                  # library sort: 0 newest, 1 name, 2 size
    selected_screens: List[str] = field(default_factory=list)

    @property
    def library_path(self) -> Path:
        return Path(self.library).expanduser()


@dataclass
class ItemOptions:
    """Per-wallpaper options, like Wallpaper Engine's properties panel."""
    scaling: str = "fill"
    blur_fill: bool = True         # blurred background behind "fit"
    speed: float = 1.0
    volume: int = -1               # -1: use the default volume
    rotation: int = 0              # WE only: 0/90/180/270

    def is_default(self) -> bool:
        return self == ItemOptions()


@dataclass
class Playlist:
    name: str
    items: List[str] = field(default_factory=list)   # library keys
    mode: str = "timer"            # "end" (next when the video ends) | "timer"
    minutes: int = 10
    shuffle: bool = False


class Store:
    def __init__(self, base: Path | None = None) -> None:
        self.base = base or paths.config_dir()
        raw = _read_json(self.base / "settings.json", {})
        known = {f.name for f in fields(Settings)}
        self.settings = Settings(**{k: v for k, v in raw.items() if k in known})
        self.options: Dict[str, ItemOptions] = {
            k: ItemOptions(**{a: b for a, b in v.items() if a in {f.name for f in fields(ItemOptions)}})
            for k, v in _read_json(self.base / "items.json", {}).items()}
        self.favorites: set = set(_read_json(self.base / "favorites.json", []))
        self.playlists: List[Playlist] = [Playlist(**p) for p in _read_json(self.base / "playlists.json", [])
                                          if isinstance(p, dict) and p.get("name")]

    def save(self) -> None:
        _write_json(self.base / "settings.json", asdict(self.settings))
        _write_json(self.base / "items.json", {k: asdict(v) for k, v in self.options.items() if not v.is_default()})
        _write_json(self.base / "favorites.json", sorted(self.favorites))
        _write_json(self.base / "playlists.json", [asdict(p) for p in self.playlists])

    def item_options(self, key: str) -> ItemOptions:
        return self.options.get(key) or ItemOptions()

    def set_item_options(self, key: str, opts: ItemOptions) -> None:
        self.options[key] = opts
        self.save()
