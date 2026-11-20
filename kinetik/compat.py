# SPDX-License-Identifier: GPL-3.0-or-later
"""How well a Wallpaper Engine item works with the KDE renderer ("Wallpaper Engine for KDE").

Three sources of evidence:
1. Static scan of the scene package. The renderer only builds image, particle, sound and light
   objects; text layers, shapes, 3D models and camera paths are skipped, SceneScript does not
   run and shadows are not drawn (WPSceneParser.cpp).
2. The renderer's own log: errors it printed after loading a scene (journal).
3. Crashes: plasmashell crashes inside the renderer within a few seconds of loading a scene.
   Only crashes *after* the current plugin build count; older ones were the reload race fixed by
   patches/wallpaper-engine-kde-plugin-node-guard.patch, which any scene could trigger.
Results are cached/remembered in ~/.config/kinetik/compat.json.
"""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import paths

PLUGIN_SO = Path("/usr/lib64/qt6/qml/com/github/catsout/wallpaperEngineKde/libWallpaperEngineKde.so")
OK, PARTIAL, BROKEN, CRASH = "ok", "partial", "broken", "crash"
RANK = {OK: 0, PARTIAL: 1, BROKEN: 2, CRASH: 3}
LABELS = {PARTIAL: "Partly works", BROKEN: "Won't look right", CRASH: "May crash"}
CRASH_WINDOW_S = 6          # a crash this soon after loading a scene is blamed on it
IGNORE_ERRORS = re.compile(r"glExtra\.cpp|ShaderValue: .* not found")   # harmless, logged for most scenes
ERROR_HINTS = [             # renderer log line -> human explanation ({0} = first regex group)
    (re.compile(r"_rt_shadowAtlas|lightCookie"), "Shadows/lighting effects are not drawn"),
    (re.compile(r"effect '([^']+)' failed to load"), "Effect “{0}” failed to load"),
    (re.compile(r"parse puppet failed|puppet has no bones|mdl wrong bone"), "An animated character (puppet) does not work"),
    (re.compile(r"CustomShaderPass.*parse tex"), "An effect texture failed to load"),
    (re.compile(r"stage ref not available"), "A render stage failed"),
    (re.compile(r"not found .* in vfs"), "Some of its files could not be found"),
]
AMBIGUOUS_S = 2             # two scenes loading this close together: errors can't be attributed


@dataclass
class Compat:
    level: str = OK
    issues: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS.get(self.level, "")

    def raise_to(self, level: str, issue: str) -> None:
        if RANK[level] > RANK[self.level]:
            self.level = level
        if issue not in self.issues:
            self.issues.append(issue)


# ---------------------------------------------------------------- 1. static scan
def read_pkg(path: Path) -> Dict[str, bytes]:
    """Wallpaper Engine .pkg: 'PKGVxxxx', file count, [name, offset, length]*, data."""
    b = path.read_bytes()
    o = 0

    def string() -> str:
        nonlocal o
        n = struct.unpack_from("<i", b, o)[0]
        o += 4
        s = b[o:o + n].decode("utf-8", "replace")
        o += n
        return s

    if not string().startswith("PKGV"):
        raise ValueError("not a scene package")
    count = struct.unpack_from("<i", b, o)[0]
    o += 4
    entries = []
    for _ in range(count):
        name = string()
        off, ln = struct.unpack_from("<ii", b, o)
        o += 8
        entries.append((name, off, ln))
    return {n: b[o + off:o + off + ln] for n, off, ln in entries}


def _scene_json(folder: Path) -> Optional[dict]:
    pkg = folder / "scene.pkg"
    try:
        raw = read_pkg(pkg).get("scene.json") if pkg.exists() else (folder / "scene.json").read_bytes()
        return json.loads(raw) if raw else None
    except (OSError, ValueError, struct.error):
        return None


def scan_scene(scene: dict) -> Compat:
    c = Compat()
    objs = [o for o in scene.get("objects", []) if isinstance(o, dict)]
    counts = {"text": 0, "model": 0, "shape": 0, "camera": 0, "shadow": 0}
    drawn = 0
    for o in objs:
        if o.get("visible") is False:
            continue
        if any(o.get(k) is not None for k in ("image", "particle")):
            drawn += 1
        elif o.get("text") is not None:
            counts["text"] += 1
        elif o.get("model") is not None:
            counts["model"] += 1
        elif o.get("shape") is not None:
            counts["shape"] += 1
        elif o.get("camera") is not None or o.get("path") is not None:
            counts["camera"] += 1
        if o.get("castshadow"):
            counts["shadow"] += 1
    scripts = json.dumps(scene).count('"script"')
    if counts["model"]:
        c.raise_to(BROKEN if counts["model"] >= 3 else PARTIAL, f"{counts['model']} 3D model(s) are not shown")
    if counts["text"]:
        c.raise_to(PARTIAL, f"{counts['text']} text layer(s) (clocks, labels) are not shown")
    if counts["shape"]:
        c.raise_to(PARTIAL, f"{counts['shape']} shape(s) are not shown")
    if counts["camera"]:
        c.raise_to(PARTIAL, "Camera movement is not supported")
    if counts["shadow"]:
        c.raise_to(PARTIAL, "Shadows are not drawn")
    if scripts:
        c.raise_to(PARTIAL, "Scripted behaviour (SceneScript) does not run")
    missing = sum(counts[k] for k in ("text", "model", "shape"))
    if missing and missing > drawn:  # more is missing than what is drawn
        c.raise_to(BROKEN, "Most of the scene uses features the KDE renderer lacks")
    return c


# ---------------------------------------------------------------- persistence
def _db_path() -> Path:
    return paths.config_dir() / "compat.json"


def _load_db() -> dict:
    try:
        return json.loads(_db_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_db(db: dict) -> None:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=1))
    os.replace(tmp, p)


# ---------------------------------------------------------------- 2+3. journal evidence
_LOAD = re.compile(r"loading scene: (.*?/431960/(\d+))/")


def _journal_entries(since_us: int) -> List[dict]:
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-o", "json", "--no-pager", f"--since=@{since_us // 1_000_000}",
             "--grep", r"loading scene:|^ERROR |KCrash: Application 'plasmashell'", "_COMM=plasmashell"],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        msg = e.get("MESSAGE")
        if isinstance(msg, list):  # binary-ish messages come as byte arrays
            msg = bytes(msg).decode("utf-8", "replace")
        rows.append({"t": int(e.get("__REALTIME_TIMESTAMP", 0)), "pid": e.get("_PID", ""), "msg": msg or ""})
    return rows


def update_from_journal() -> dict:
    """Read new journal lines since last time; returns the db {"errors": {wid: [...]}, "crashes": {wid: [t..]}}."""
    db = _load_db()
    errors: Dict[str, List[str]] = db.setdefault("errors", {})
    crashes: Dict[str, List[int]] = db.setdefault("crashes", {})
    since = int(db.get("journal_seen_us", 0)) or 0
    try:
        fix_us = int(PLUGIN_SO.stat().st_mtime * 1_000_000)
    except OSError:
        fix_us = 0
    rows = _journal_entries(max(since, 1))
    loads = [(r["pid"], r["t"], m.group(2)) for r in rows for m in [_LOAD.search(r["msg"])] if m]
    # a load is "alone" if no other scene started loading in the same process within AMBIGUOUS_S
    alone = {(pid, t) for pid, t, _w in loads
             if not any(p2 == pid and t2 != t and abs(t2 - t) <= AMBIGUOUS_S * 1_000_000 for p2, t2, _x in loads)}
    current: Dict[str, tuple] = {}               # pid -> (wid, t) of the latest load
    for r in rows:
        m = _LOAD.search(r["msg"])
        if m:
            current[r["pid"]] = (m.group(2), r["t"])
            continue
        if r["msg"].startswith("ERROR "):
            if IGNORE_ERRORS.search(r["msg"]) or r["pid"] not in current:
                continue
            wid, t = current[r["pid"]]
            if (r["pid"], t) not in alone:
                continue
            for rx, hint in ERROR_HINTS:
                hm = rx.search(r["msg"])
                if hm:
                    text = hint.format(*hm.groups())
                    if text not in errors.setdefault(wid, []):
                        errors[wid].append(text)
                    break
        elif "KCrash: Application 'plasmashell'" in r["msg"] and "WallpaperEngineKde" in r["msg"] \
                and r["t"] > fix_us:
            for pid, t, wid in loads:
                if pid == r["pid"] and 0 <= r["t"] - t <= CRASH_WINDOW_S * 1_000_000 \
                        and r["t"] not in crashes.setdefault(wid, []):
                    crashes[wid].append(r["t"])
    if rows:
        db["journal_seen_us"] = max(r["t"] for r in rows) + 1
    _save_db(db)
    return db


def clear(wid: str) -> None:
    """User says it's fine: forget recorded errors/crashes for this item."""
    db = _load_db()
    for k in ("errors", "crashes"):
        db.get(k, {}).pop(wid, None)
    db.setdefault("dismissed", [])
    if wid not in db["dismissed"]:
        db["dismissed"].append(wid)
    _save_db(db)


# ---------------------------------------------------------------- public
def check(folder: Path, kind: str, wid: str, db: Optional[dict] = None, cache: Optional[dict] = None) -> Compat:
    """Compatibility of one Workshop item. `cache` maps folder -> (mtime, Compat) for the static part."""
    if kind == "we-video":
        return Compat()
    if kind == "web":
        c = Compat()
        if not Path("/usr/lib64/qt6/qml/QtWebEngine").exists():
            c.raise_to(BROKEN, "Needs Qt WebEngine (qt6-qtwebengine) for web wallpapers")
        return c
    key = str(folder)
    try:
        mtime = max(p.stat().st_mtime for p in (folder / "project.json", folder / "scene.pkg") if p.exists())
    except ValueError:
        mtime = 0
    if cache is not None and key in cache and cache[key][0] == mtime:
        base = cache[key][1]
    else:
        scene = _scene_json(folder)
        base = scan_scene(scene) if scene else Compat(BROKEN, ["The scene file could not be read"])
        if cache is not None:
            cache[key] = (mtime, base)
    c = Compat(base.level, list(base.issues))
    db = db if db is not None else _load_db()
    dismissed = wid in db.get("dismissed", [])
    for hint in db.get("errors", {}).get(wid, []):
        c.raise_to(PARTIAL, f"Renderer: {hint}")
    n = len(db.get("crashes", {}).get(wid, []))
    if n and not dismissed:
        c.raise_to(CRASH, f"Plasma crashed {n}× right after loading it")
    return c
