"""Settings -> plugin config keys."""
import json
import unittest
from pathlib import Path

from kinetik import engine, plasma
from kinetik.library import Item
from kinetik.settings import ItemOptions, Playlist, Settings


class EngineTests(unittest.TestCase):
    def test_video_single(self):
        s = Settings(pause=1, audio=4, volume=40, blur=2)
        cfg = engine.video_config(s, [("file:///a.mp4", ItemOptions(scaling="fit", speed=1.5, volume=80))])
        self.assertEqual(cfg["PauseMode"], 1)
        self.assertEqual(cfg["MuteMode"], 4)          # never muted
        self.assertEqual(cfg["BlurMode"], 1)          # window focused
        self.assertEqual(cfg["FillMode"], 1)          # fit
        self.assertEqual(cfg["PlaybackRate"], 1.5)
        self.assertEqual(cfg["Volume"], 0.8)          # per-item override
        self.assertEqual(cfg["ChangeWallpaperMode"], 0)
        urls = json.loads(cfg["VideoUrls"])
        self.assertEqual(urls[0]["filename"], "file:///a.mp4")
        self.assertTrue(urls[0]["loop"])

    def test_video_playlist(self):
        p = Playlist("p", mode="timer", minutes=75, shuffle=True)
        cfg = engine.video_config(Settings(), [("file:///a.mp4", ItemOptions()), ("file:///b.mp4", ItemOptions())], p)
        self.assertEqual((cfg["ChangeWallpaperMode"], cfg["ChangeWallpaperTimerHours"],
                          cfg["ChangeWallpaperTimerMinutes"], cfg["RandomMode"]), (2, 1, 15, True))
        self.assertEqual(len(json.loads(cfg["VideoUrls"])), 2)

    def test_we_scene(self):
        it = Item("we:1", "scene", "S", Path("/lib/431960/1"), wid="1", we_file="scene.json")
        cfg = engine.we_config(Settings(pause=0, audio=0, fps=60), it, ItemOptions(scaling="stretch", rotation=90),
                               Path("/lib"))
        self.assertEqual(cfg["WallpaperSource"], "file:///lib/431960/1/scene.json+scene")
        self.assertEqual((cfg["DisplayMode"], cfg["Rotation"], cfg["PauseMode"], cfg["Fps"], cfg["MuteAudio"]),
                         (2, 90, 2, 60, True))
        self.assertEqual(engine.plugin_for(it), plasma.WE_PLUGIN)

    def test_image(self):
        it = Item("/x.png", "image", "x", Path("/x.png"))
        self.assertEqual(engine.image_config(Settings(), it, ItemOptions(scaling="fit"))["FillMode"], 1)
        self.assertEqual(engine.plugin_for(it), plasma.IMAGE)


if __name__ == "__main__":
    unittest.main()
