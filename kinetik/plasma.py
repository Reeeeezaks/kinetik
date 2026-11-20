# SPDX-License-Identifier: GPL-3.0-or-later
"""Screens (kscreen + EDID names) and Plasma desktop wallpaper scripting."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from . import edid

SMART_VIDEO = "luisbocanegra.smart.video.wallpaper.reborn"
WE_PLUGIN = "com.github.catsout.wallpaperEngineKde"
IMAGE = "org.kde.image"
ROTATION_NONE, ROTATION_LEFT, ROTATION_INVERTED, ROTATION_RIGHT = 1, 2, 4, 8


class PlasmaError(RuntimeError):
    pass


@dataclass
class Monitor:
    key: str                       # connector name, e.g. "DP-1"
    connector: str
    label: str                     # "HKC OVERSEAS LIMITED 27E1QA"
    screen: int                    # Plasma screen index (desktops()[i].screen)
    geometry: Tuple[int, int, int, int]
    mode: Tuple[int, int]
    scale: float = 1.0
    rotation: int = ROTATION_NONE
    primary: bool = False
    usable: bool = True
    reason: str = ""
    hdr: bool = False
    wcg: bool = False

    @property
    def detail(self) -> str:
        text = f"{self.mode[0]} × {self.mode[1]}"
        if abs(self.scale - 1.0) > 1e-3:
            text += f", {round(self.scale * 100)}%"
        return f"({text})"

    @property
    def short(self) -> str:
        """Model name only ('27E1QA'), for compact places."""
        return self.label.rsplit(" ", 1)[-1] if " " in self.label else self.label


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}


def evaluate(script: str) -> str:
    try:
        r = subprocess.run(["busctl", "--user", "call", "org.kde.plasmashell", "/PlasmaShell",
                            "org.kde.PlasmaShell", "evaluateScript", "s", script],
                           capture_output=True, text=True, timeout=20, env=_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlasmaError(f"plasmashell did not answer: {exc}") from exc
    if r.returncode != 0:
        raise PlasmaError(r.stderr.strip() or "plasmashell did not answer")
    out = r.stdout.strip()
    return json.loads(out[2:]) if out.startswith("s ") else out


def monitors() -> List[Monitor]:
    try:
        ks = json.loads(subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True,
                                       timeout=10, env=_env()).stdout)["outputs"]
        ds = json.loads(evaluate('var o=[];desktops().forEach(function(d){var g=screenGeometry(d.screen);'
                                 'o.push({s:d.screen,x:g.x,y:g.y});});print(JSON.stringify(o));'))
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, PlasmaError):
        return []
    out = []
    for o in ks:
        if not (o.get("enabled") and o.get("connected", True)):
            continue
        x, y = o["pos"]["x"], o["pos"]["y"]
        screen = next((d["s"] for d in ds if d["x"] == x and d["y"] == y), None)
        if screen is None:
            continue
        mode = next((m for m in o.get("modes", []) if m["id"] == o.get("currentModeId")), None)
        size = (mode["size"]["width"], mode["size"]["height"]) if mode else (o["size"]["width"], o["size"]["height"])
        info = edid.for_connector(o["name"])
        label = info.display_name if info else o["name"]
        if label.startswith("Invalid Vendor Codename - "):
            label = label.split(" - ", 1)[1]
        out.append(Monitor(
            key=o["name"], connector=o["name"], label=label, screen=screen,
            geometry=(x, y, round(o["size"]["width"] / o["scale"]), round(o["size"]["height"] / o["scale"])),
            mode=size, scale=o["scale"], rotation=o.get("rotation", 1), primary=o.get("priority") == 1))
    return out


def current() -> Dict[int, dict]:
    """screen index -> {plugin, source} where source is a file URL (first video / WE source / image)."""
    script = (
        "var o={};desktops().forEach(function(d){var p=d.wallpaperPlugin;"
        "d.currentConfigGroup=['Wallpaper',p,'General'];var s='';"
        f"if(p=='{SMART_VIDEO}'){{s=d.readConfig('VideoUrls');}}"
        f"else if(p=='{WE_PLUGIN}'){{s=d.readConfig('WallpaperSource');}}"
        "else{s=d.readConfig('Image');}"
        "o[d.screen]={plugin:p,source:''+s};});print(JSON.stringify(o));")
    try:
        raw = json.loads(evaluate(script))
    except (ValueError, PlasmaError):
        return {}
    out = {}
    for k, v in raw.items():
        src = v.get("source", "")
        if v.get("plugin") == SMART_VIDEO:
            try:
                vids = [x.get("filename", "") for x in json.loads(src or "[]") if x.get("enabled", True)]
                src = vids[0] if vids else ""
                v["count"] = len(vids)
            except ValueError:
                src = ""
        elif v.get("plugin") == WE_PLUGIN:
            src = src.rsplit("+", 1)[0]
        v["source"] = src
        out[int(k)] = v
    return out


def apply(screens: Sequence[int], plugin: str, cfg: dict, switch: bool = True) -> None:
    """Set plugin + config on the given Plasma screens. switch=False only updates screens already on `plugin`."""
    script = (
        "var T=%s,P=%s,C=%s,S=%s;"
        "desktops().forEach(function(d){if(T.indexOf(d.screen)<0)return;"
        "if(!S&&d.wallpaperPlugin!=P)return;"
        "d.wallpaperPlugin=P;d.currentConfigGroup=['Wallpaper',P,'General'];"
        "for(var k in C){d.writeConfig(k,C[k]);}"
        "if(d.reloadConfig)d.reloadConfig();});"
    ) % (json.dumps(list(screens)), json.dumps(plugin), json.dumps(cfg), "true" if switch else "false")
    evaluate(script)


def plasma_version() -> Optional[str]:
    try:
        r = subprocess.run(["plasmashell", "--version"], capture_output=True, text=True, timeout=5, env=_env())
        return r.stdout.strip().split()[-1] if r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None
