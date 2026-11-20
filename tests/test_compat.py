"""Wallpaper Engine compatibility checks."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetik import compat


def make_pkg(files: dict) -> bytes:
    def s(x: str) -> bytes:
        b = x.encode()
        return struct.pack("<i", len(b)) + b
    head, data = s("PKGV0022") + struct.pack("<i", len(files)), b""
    for name, blob in files.items():
        head += s(name) + struct.pack("<ii", len(data), len(blob))
        data += blob
    return head + data


class CompatTests(unittest.TestCase):
    def test_read_pkg_and_scan(self):
        scene = {"objects": [{"image": "a.json"}, {"particle": "p.json"}, {"text": {"value": "12:00"}},
                             {"model": "m.json", "castshadow": True}],
                 "general": {}}
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "scene.pkg").write_bytes(make_pkg({"scene.json": json.dumps(scene).encode(), "x.tex": b"\0"}))
            self.assertIn("scene.json", compat.read_pkg(d / "scene.pkg"))
            c = compat.check(d, "scene", "1", db={})
        self.assertEqual(c.level, compat.PARTIAL)
        self.assertTrue(any("text layer" in i for i in c.issues))
        self.assertTrue(any("3D model" in i for i in c.issues))
        self.assertTrue(any("Shadows" in i for i in c.issues))

    def test_mostly_unsupported_is_broken(self):
        scene = {"objects": [{"image": "a"}] + [{"model": f"m{i}"} for i in range(4)]}
        self.assertEqual(compat.scan_scene(scene).level, compat.BROKEN)

    def test_simple_scene_ok_and_videos_ok(self):
        self.assertEqual(compat.scan_scene({"objects": [{"image": "a"}, {"sound": ["s.mp3"]}]}).level, compat.OK)
        self.assertEqual(compat.check(Path("/nope"), "we-video", "1", db={}).level, compat.OK)

    def test_journal_attribution(self):
        s = 1_000_000
        rows = [
            # two scenes loading together (Plasma start): their errors must not be attributed
            {"t": 100 * s, "pid": "1", "msg": "INFO loading scene: /x/431960/111/scene.json"},
            {"t": 100 * s + 5, "pid": "1", "msg": "INFO loading scene: /x/431960/222/scene.json"},
            {"t": 101 * s, "pid": "1", "msg": 'ERROR WPSceneParser.cpp:244 unknown tex "_rt_shadowAtlas"'},
            # a scene loaded alone: its errors count, harmless GL noise is ignored
            {"t": 200 * s, "pid": "1", "msg": "INFO loading scene: /x/431960/333/scene.json"},
            {"t": 200 * s + 9, "pid": "1", "msg": "ERROR glExtra.cpp:142 GL_INVALID_ENUM(1280) at genExTexture"},
            {"t": 201 * s, "pid": "1", "msg": "ERROR WPSceneParser.cpp:885 effect 'Bars' failed to load"},
            # crash 2 s after loading 444 (after the fix) -> blamed; crash before the fix -> ignored
            {"t": 300 * s, "pid": "1", "msg": "INFO loading scene: /x/431960/444/scene.json"},
            {"t": 302 * s, "pid": "1", "msg": "KCrash: Application 'plasmashell' crashing... WallpaperEngineKde"},
            {"t": 40 * s, "pid": "0", "msg": "INFO loading scene: /x/431960/555/scene.json"},
            {"t": 41 * s, "pid": "0", "msg": "KCrash: Application 'plasmashell' crashing... WallpaperEngineKde"},
        ]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(compat, "_db_path", return_value=Path(tmp) / "c.json"), \
                mock.patch.object(compat, "_journal_entries", return_value=sorted(rows, key=lambda r: r["t"])), \
                mock.patch.object(compat, "PLUGIN_SO", mock.Mock(**{"stat.return_value.st_mtime": 50})):
            db = compat.update_from_journal()
        self.assertNotIn("111", db["errors"])
        self.assertNotIn("222", db["errors"])
        self.assertEqual(db["errors"]["333"], ["Effect “Bars” failed to load"])
        self.assertEqual(list(db["crashes"]), ["444"])


if __name__ == "__main__":
    unittest.main()
