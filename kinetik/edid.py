# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal EDID parsing for human-readable monitor names (matches KDE's labels)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

HEADER = bytes([0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0])
PNP_IDS = (Path("/usr/share/hwdata/pnp.ids"), Path("/usr/share/misc/pnp.ids"))
SYSFS_DRM = Path("/sys/class/drm")


@dataclass(frozen=True)
class EdidInfo:
    vendor_code: str
    vendor_name: str
    model: str
    product_code: int

    @property
    def display_name(self) -> str:
        return f"{self.vendor_name} {self.model}".strip()


def _text(raw: bytes) -> str:
    raw = raw.split(b"\n")[0]
    return "".join(ch for ch in raw.decode("cp437", "replace") if ch.isprintable()).strip()


@lru_cache(maxsize=1)
def _vendor_table() -> Dict[str, str]:
    for path in PNP_IDS:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        table = {}
        for line in lines:
            code, _, name = line.partition("\t")
            if len(code) == 3 and name:
                table[code] = name.strip()
        return table
    return {}


def parse(data: bytes, vendors: Optional[Dict[str, str]] = None) -> Optional[EdidInfo]:
    if len(data) < 128 or data[:8] != HEADER:
        return None
    raw = int.from_bytes(data[8:10], "big")
    code = "".join(chr(((raw >> shift) & 0x1F) + 64) for shift in (10, 5, 0))
    product = int.from_bytes(data[10:12], "little")
    strings: Dict[int, str] = {}
    for offset in (54, 72, 90, 108):
        block = data[offset:offset + 18]
        if block[:3] == b"\0\0\0" and block[4] == 0:
            text = _text(block[5:18])
            if text:
                strings.setdefault(block[3], text)
    # monitor name, then alphanumeric string, then serial text (KDE falls back the same way)
    model = strings.get(0xFC) or strings.get(0xFE) or strings.get(0xFF) or f"0x{product:04X}"
    table = _vendor_table() if vendors is None else vendors
    return EdidInfo(code, table.get(code, code), model, product)


def for_connector(connector: str, sysfs: Path = SYSFS_DRM) -> Optional[EdidInfo]:
    for path in sorted(sysfs.glob(f"card*-{connector}/edid")):
        try:
            info = parse(path.read_bytes())
        except OSError:
            continue
        if info:
            return info
    return None
