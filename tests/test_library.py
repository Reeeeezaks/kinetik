"""Library scanning and settings persistence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kinetik import library
from kinetik.settings import ItemOptions, Playlist, Store


class LibraryTests(unittest.TestCase):
    def test_scan_local_and_workshop(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib, ws = Path(tmp) / "lib", Path(tmp) / "ws"
            lib.mkdir()
            for name in ("a.mp4", "b.gif", "c.png", "notes.txt"):
                (lib / name).write_bytes(b"x")
            (ws / "123").mkdir(parents=True)
            (ws / "123" / "project.json").write_text(json.dumps(
                {"title": "Scene!", "type": "Scene", "file": "scene.json", "tags": ["Anime"],
                 "contentrating": "Everyone"}))
            with mock.patch.object(library, "workshop_dirs", return_value=[ws]):
                items = {i.key: i for i in library.scan(lib)}
            kinds = sorted(i.kind for i in items.values())
            self.assertEqual(kinds, ["gif", "image", "scene", "video"])
            we = items["we:123"]
            self.assertEqual((we.title, we.wid, we.we_file, we.tags), ("Scene!", "123", "scene.json", ["Anime"]))
            self.assertFalse(we.video_capable)

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = Store(Path(tmp))
            st.settings.volume = 33
            st.favorites.add("k")
            st.playlists.append(Playlist("p", ["k"]))
            st.set_item_options("k", ItemOptions(scaling="fit"))
            st.set_item_options("d", ItemOptions())  # defaults are not stored
            again = Store(Path(tmp))
            self.assertEqual(again.settings.volume, 33)
            self.assertEqual(again.favorites, {"k"})
            self.assertEqual(again.playlists[0].items, ["k"])
            self.assertEqual(again.item_options("k").scaling, "fit")
            self.assertNotIn("d", json.loads((Path(tmp) / "items.json").read_text()))


if __name__ == "__main__":
    unittest.main()
