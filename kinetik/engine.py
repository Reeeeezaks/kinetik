# SPDX-License-Identifier: GPL-3.0-or-later
"""Translate Kinetik settings + per-wallpaper options into each Plasma plugin's config keys.

Videos/GIFs/WE videos -> Smart Video Wallpaper Reborn, WE scenes/web -> Wallpaper Engine for KDE,
images -> Plasma's own image wallpaper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QUrl

from . import paths, plasma
from .library import Item
from .settings import ItemOptions, Playlist, Settings

SV_PAUSE = [0, 1, 2, 3]            # MaximizedOrFullScreen, ActiveWindowPresent, WindowVisible, Never
WE_PAUSE = [2, 3, 1, 0]            # WE enum: Never 0, Any 1, Max 2, Focus 3, FocusOrMax 4, FullScreen 5
SV_MUTE = [5, 0, 1, 2, 4]          # Always, Maximized, Active, Visible, Never
SV_BLUR = [5, 0, 1, 2, 3, 4]       # Never, Maximized, Active, Visible, Paused, Always
SV_FILL = {"fill": 2, "fit": 1, "stretch": 0}       # Qt VideoOutput fill modes
IMG_FILL = {"fill": 2, "fit": 1, "stretch": 0}      # Plasma image wallpaper (same Qt enum)
WE_DISPLAY = {"fit": 0, "fill": 1, "stretch": 2}    # WE: Aspect, Crop, Scale


def file_url(path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


def plugin_for(item: Item) -> str:
    if item.kind in ("scene", "web"):
        return plasma.WE_PLUGIN
    if item.kind == "image":
        return plasma.IMAGE
    return plasma.SMART_VIDEO


# ---- settings that apply to every screen using a plugin -------------------------------------
def video_settings(s: Settings) -> dict:
    return {
        "PauseMode": SV_PAUSE[s.pause], "MuteMode": SV_MUTE[s.audio], "Volume": round(s.volume / 100, 2),
        "BlurMode": SV_BLUR[s.blur], "BlurRadius": s.blur_radius,
        "CrossfadeEnabled": s.crossfade, "CrossfadeDuration": s.crossfade_ms,
        "BackgroundColor": s.background, "ResumeLastVideo": s.resume_last,
    }


def we_settings(s: Settings) -> dict:
    return {
        "PauseMode": WE_PAUSE[s.pause], "Fps": s.fps, "MouseInput": s.mouse_input,
        "VideoBackend": s.video_backend, "MuteAudio": s.audio == 0, "Volume": s.volume,
        "BackgroundColor": s.background, "RandomizeWallpaper": s.we_random, "SwitchTimer": s.we_random_minutes,
    }


def image_settings(s: Settings) -> dict:
    return {"Color": s.background}


def settings_for(plugin: str, s: Settings) -> dict:
    return {plasma.SMART_VIDEO: video_settings, plasma.WE_PLUGIN: we_settings,
            plasma.IMAGE: image_settings}[plugin](s)


# ---- one wallpaper ---------------------------------------------------------------------------
def _video_entry(url: str, o: ItemOptions, loop: bool) -> dict:
    return {"filename": url, "enabled": True, "duration": 0, "customDuration": 0,
            "playbackRate": 0.0 if abs(o.speed - 1) < 1e-3 else round(o.speed, 2),
            "alternativePlaybackRate": 0.0, "loop": loop}


def video_config(s: Settings, entries: Sequence[Tuple[str, ItemOptions]], playlist: Optional[Playlist] = None) -> dict:
    """entries: (file url, options) - one for a single wallpaper, several for a playlist."""
    first = entries[0][1]
    cfg = video_settings(s)
    cfg.update({
        "FillMode": SV_FILL.get(first.scaling, 2), "FillBlur": first.blur_fill,
        "PlaybackRate": round(first.speed, 2) if not playlist else 1.0,
        "VideoUrls": json.dumps([_video_entry(u, o, loop=playlist is None) for u, o in entries]),
        "LastVideo": entries[0][0], "LastVideoPosition": 0,
    })
    if first.volume >= 0 and not playlist:
        cfg["Volume"] = round(first.volume / 100, 2)
    if playlist:
        cfg.update({"ChangeWallpaperMode": 1 if playlist.mode == "end" else 2, "RandomMode": playlist.shuffle,
                    "ChangeWallpaperTimerHours": playlist.minutes // 60,
                    "ChangeWallpaperTimerMinutes": playlist.minutes % 60, "ChangeWallpaperTimerSeconds": 0})
    else:
        cfg.update({"ChangeWallpaperMode": 0, "RandomMode": False})
    return cfg


def we_config(s: Settings, item: Item, o: ItemOptions, library: Path) -> dict:
    cfg = we_settings(s)
    cfg.update({
        "SteamLibraryPath": file_url(library), "WallpaperWorkShopId": item.wid,
        "WallpaperSource": f"{file_url(item.path)}/{item.we_file}+{item.kind}",
        "DisplayMode": WE_DISPLAY.get(o.scaling, 1), "Speed": round(o.speed, 2), "Rotation": o.rotation,
    })
    if o.volume >= 0:
        cfg["Volume"] = o.volume
    return cfg


def we_item_options(s: Settings, o: ItemOptions) -> dict:
    """What the WE plugin stores per wallpaper (overrides its global keys) - keep it in sync."""
    return {"display_mode": WE_DISPLAY.get(o.scaling, 1), "speed": round(o.speed, 2), "rotation": o.rotation,
            "volume": o.volume if o.volume >= 0 else s.volume, "mute_audio": s.audio == 0}


def write_we_item_options(wid: str, values: dict) -> None:
    f = paths.wekde_config_dir() / f"{wid}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        cur = json.loads(f.read_text())
    except (OSError, ValueError):
        cur = {}
    cur.update(values)
    f.write_text(json.dumps(cur))


def image_config(s: Settings, item: Item, o: ItemOptions) -> dict:
    return {"Image": file_url(item.path), "FillMode": IMG_FILL.get(o.scaling, 2), **image_settings(s)}


def push_settings(s: Settings, screens: List[int]) -> None:
    """Re-apply global settings to screens that already use one of our plugins (no wallpaper change)."""
    for plugin in (plasma.SMART_VIDEO, plasma.WE_PLUGIN):
        plasma.apply(screens, plugin, settings_for(plugin, s), switch=False)


def current_options_update(item: Item, s: Settings, o: ItemOptions) -> Dict[str, dict]:
    """Config keys to rewrite live when only an item's options changed (plugin -> keys)."""
    if item.kind in ("scene", "web"):
        keys = {"DisplayMode": WE_DISPLAY.get(o.scaling, 1), "Speed": round(o.speed, 2), "Rotation": o.rotation,
                "Volume": o.volume if o.volume >= 0 else s.volume}
        return {plasma.WE_PLUGIN: keys}
    if item.kind == "image":
        return {plasma.IMAGE: {"FillMode": IMG_FILL.get(o.scaling, 2)}}
    return {plasma.SMART_VIDEO: {"FillMode": SV_FILL.get(o.scaling, 2), "FillBlur": o.blur_fill,
                                 "PlaybackRate": round(o.speed, 2),
                                 "Volume": round((o.volume if o.volume >= 0 else s.volume) / 100, 2)}}
