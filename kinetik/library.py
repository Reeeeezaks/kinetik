# SPDX-License-Identifier: GPL-3.0-or-later
"""Local library: your own videos/GIFs/images plus Wallpaper Engine Workshop items."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi"}
GIF_EXT = {".gif"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".jxl", ".bmp"}
WE_APPID = "431960"
KIND_LABELS = {"video": "Video", "gif": "GIF", "image": "Image",
               "scene": "Scene", "we-video": "WE Video", "web": "Web"}


@dataclass
class Item:
    key: str                  # stable id: absolute path, or "we:<workshop id>"
    kind: str                 # video | gif | image | scene | we-video | web
    title: str
    path: Path                # the file, or the Workshop folder
    preview: Optional[Path] = None
    size: int = 0
    mtime: float = 0.0
    wid: str = ""             # Workshop id
    we_file: str = ""         # project.json "file"
    tags: List[str] = field(default_factory=list)
    rating: str = ""          # Workshop content rating

    @property
    def is_we(self) -> bool:
        return self.key.startswith("we:")

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def media(self) -> Path:
        """The file a video player would open."""
        return self.path / self.we_file if self.is_we else self.path

    @property
    def video_capable(self) -> bool:
        """Can be played by the video plugin (and used in playlists)."""
        return self.kind in ("video", "gif", "we-video")


def steam_roots() -> List[Path]:
    return [Path.home() / ".local/share/Steam", Path.home() / ".steam/steam",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]


def steam_libraries() -> List[Path]:
    libs: List[Path] = []
    for root in steam_roots():
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            libs += [Path(m) for m in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore"))]
        libs.append(root)
    out, seen = [], set()
    for lib in libs:
        try:
            real = lib.resolve()
        except OSError:
            continue
        if real not in seen and (lib / "steamapps").is_dir():
            seen.add(real)
            out.append(lib)
    return out


def we_install_library() -> Optional[Path]:
    for lib in steam_libraries():
        if (lib / "steamapps/common/wallpaper_engine/assets").is_dir():
            return lib
    return None


def workshop_dirs() -> List[Path]:
    return [d for d in (lib / "steamapps/workshop/content" / WE_APPID for lib in steam_libraries()) if d.is_dir()]


def _dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _local(folder: Path) -> List[Item]:
    items = []
    if not folder.is_dir():
        return items
    for f in folder.iterdir():
        ext = f.suffix.lower()
        if not f.is_file():
            continue
        kind = "video" if ext in VIDEO_EXT else "gif" if ext in GIF_EXT else "image" if ext in IMAGE_EXT else ""
        if not kind:
            continue
        st = f.stat()
        items.append(Item(key=str(f), kind=kind, title=f.stem, path=f, size=st.st_size, mtime=st.st_mtime))
    return items


def _we_item(d: Path, size_cache: dict) -> Optional[Item]:
    pj = d / "project.json"
    try:
        p = json.loads(pj.read_text(encoding="utf-8-sig", errors="ignore"))
    except (OSError, ValueError):
        return None
    t = str(p.get("type", "")).lower()
    if t not in ("scene", "video", "web") or not p.get("file"):
        return None
    mtime = pj.stat().st_mtime
    key = f"{d}:{mtime}"
    if key not in size_cache:
        size_cache[key] = _dir_size(d)
    prev = d / p["preview"] if p.get("preview") else None
    return Item(key=f"we:{d.name}", kind={"video": "we-video"}.get(t, t), title=str(p.get("title") or d.name),
                path=d, preview=prev if prev and prev.exists() else None, size=size_cache[key], mtime=mtime,
                wid=d.name, we_file=str(p["file"]), tags=[str(x) for x in p.get("tags", []) if x],
                rating=str(p.get("contentrating", "")))


_SIZE_CACHE: dict = {}


def scan(library: Path) -> List[Item]:
    items = _local(library)
    for wd in workshop_dirs():
        for d in wd.iterdir():
            if d.is_dir():
                it = _we_item(d, _SIZE_CACHE)
                if it:
                    items.append(it)
    return items


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
