"""Parsers against small hand-written snippets shaped like the real pages (no network)."""
import unittest

from kinetik.sources import MoeWalls, MotionBGs, Workshop

MBG = ('<a title="Rainy Forest live wallpaper" href=/rainy-forest> <figure><picture>'
       '<img alt="x" src=/i/c/364x205/media/3510/rainy-forest.jpg width=364></picture></figure>'
       ' <span class=ttl>Rainy Forest</span> <span class=frm> 4K </span> </a>')
MBG_DETAIL = '<video src=/media/3510/rainy-forest.960x540.mp4></video><a href=/dl/4k/3510>'
MOE = ('<a title="Spider Tears Live Wallpaper" class="g1-frame" href="https://moewalls.com/movies/spider/">'
       '<div class="g1-frame-inner"><img width="364" height="205" src="https://moewalls.com/t.jpg" class="a" />')
MOE_DETAIL = ('<source src="/wp-content/uploads/preview/2026/spider-preview.webm" type="video/webm">'
              '<a id="moe-download" data-id ="21754" data-url="tts%2FAbC" rel="nofollow">')
WS = ('<a href="https://steamcommunity.com/sharedfiles/filedetails/?id=1252146600" class="x">'
      '<img src="https://images.steamusercontent.com/ugc/1/A/?ima=fit&amp;imw=322" alt="Empirical Rain 4k" '
      'loading="lazy"/></a>')


class SourceTests(unittest.TestCase):
    def test_motionbgs(self):
        src = MotionBGs()
        [r] = src.parse(MBG)
        self.assertEqual((r.title, r.rid, r.badge), ("Rainy Forest", "3510", "4K"))
        self.assertEqual(src.download_url(r, best=True), "https://motionbgs.com/dl/4k/3510/")
        self.assertEqual(src.download_url(r, best=False), "https://motionbgs.com/dl/hd/3510/")
        src.detail(r, MBG_DETAIL)
        self.assertTrue(r.preview.endswith("rainy-forest.960x540.mp4"))
        self.assertIn("search?q=a%20b", src.url("a b", 1))
        self.assertEqual(src.url("", 3), "https://motionbgs.com/3/")

    def test_moewalls(self):
        src = MoeWalls()
        [r] = src.parse(MOE)
        self.assertEqual(r.title, "Spider Tears")
        self.assertEqual(src.download_url(r, False, MOE_DETAIL),
                         "https://go.moewalls.com/download.php?video=tts%2FAbC")
        src.detail(r, MOE_DETAIL)
        self.assertTrue(r.preview.endswith("spider-preview.webm"))
        self.assertEqual(src.url("x", 2), "https://moewalls.com/page/2/?s=x")

    def test_workshop(self):
        src = Workshop()
        [r] = src.parse(WS)
        self.assertEqual((r.rid, r.title), ("1252146600", "Empirical Rain 4k"))
        self.assertIn("&imw=322", r.thumb)
        Workshop.apply_details([r], {"response": {"publishedfiledetails": [
            {"publishedfileid": "1252146600", "file_size": "5000000", "tags": [{"tag": "Scene"}, {"tag": "Everyone"}]}]}})
        self.assertEqual((r.badge, r.size), ("Scene", 5000000))
        Workshop.safe = True
        self.assertIn("requiredtags%5B%5D=Everyone", src.url("", 1))


if __name__ == "__main__":
    unittest.main()
