# SPDX-License-Identifier: GPL-3.0-or-later
"""Online wallpaper sources: MotionBGs, MoeWalls and the Steam Workshop.

The two video sites have no API, so their pages are parsed. If a site redesigns,
only the regexes in its class need updating (tests/test_sources.py covers them).
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
WE_APPID = "431960"


@dataclass
class Result:
    source: str
    title: str
    thumb: str
    page: str
    rid: str = ""
    badge: str = ""
    preview: str = ""       # animated preview (video URL) once known
    size: int = 0
    tags: tuple = ()


class Source:
    name = ""
    short = ""
    paged_search = True
    needs_detail = False    # download link (and preview) only on the detail page
    downloads = True        # False: handled by Steam

    def url(self, query: str, page: int) -> str:
        raise NotImplementedError

    def parse(self, page_html: str) -> List[Result]:
        raise NotImplementedError

    def detail(self, result: Result, page_html: str) -> None:
        """Fill result.preview from the detail page (optional)."""

    def download_url(self, result: Result, best: bool, detail_html: str = "") -> Optional[str]:
        raise NotImplementedError


class MotionBGs(Source):
    name, short = "MotionBGs", "MotionBGs"
    base = "https://motionbgs.com"
    paged_search = False
    needs_detail = False

    def url(self, query, page):
        if query:
            return f"{self.base}/search?q={urllib.parse.quote(query)}"
        return self.base + "/" if page == 1 else f"{self.base}/{page}/"

    def parse(self, page_html):
        out = []
        for m in re.finditer(r'<a title="([^"]+)" href=(/[^ >]+)>\s*<figure>(.*?)</a>', page_html, re.S):
            title, href, body = html.unescape(m.group(1)), m.group(2), m.group(3)
            img = re.search(r"src=(/i/c/[^ >]+)", body)
            mid = re.search(r"/media/(\d+)/", body)
            frm = re.search(r"class=frm>\s*([^<]+?)\s*<", body)
            if not (img and mid):
                continue
            out.append(Result(self.name, re.sub(r"\s+live wallpaper$", "", title, flags=re.I),
                              self.base + img.group(1), self.base + href, mid.group(1),
                              frm.group(1).strip() if frm else "HD"))
        return out

    def detail(self, result, page_html):
        m = re.search(r"src=(/media/[^ >]+\.mp4)", page_html)
        if m:
            result.preview = self.base + m.group(1)

    def download_url(self, result, best, detail_html=""):
        q = "4k" if best and "4k" in result.badge.lower() else "hd"
        return f"{self.base}/dl/{q}/{result.rid}/"


class MoeWalls(Source):
    name, short = "MoeWalls", "MoeWalls"
    base = "https://moewalls.com"
    needs_detail = True

    def url(self, query, page):
        pre = self.base + ("/" if page == 1 else f"/page/{page}/")
        return pre + (f"?s={urllib.parse.quote(query)}" if query else "")

    def parse(self, page_html):
        out = []
        for m in re.finditer(r'<a title="([^"]+)" class="g1-frame" href="([^"]+)"><div class="g1-frame-inner">'
                             r'<img[^>]*?src="([^"]+)"', page_html):
            title = re.sub(r"\s+live wallpaper$", "", html.unescape(m.group(1)), flags=re.I)
            out.append(Result(self.name, title, m.group(3), m.group(2), "", "Video"))
        return out

    def detail(self, result, page_html):
        m = re.search(r'src="(/wp-content/uploads/preview/[^"]+\.(?:webm|mp4))"', page_html)
        if m:
            result.preview = self.base + m.group(1)

    def download_url(self, result, best, detail_html=""):
        m = re.search(r'id="moe-download"[^>]*?data-url="([^"]+)"', detail_html or "")
        return "https://go.moewalls.com/download.php?video=" + m.group(1) if m else None


class Workshop(Source):
    name, short = "Steam Workshop (Wallpaper Engine)", "Workshop"
    downloads = False
    safe = True
    DETAILS_API = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"

    def url(self, query, page):
        p = [("appid", WE_APPID), ("browsesort", "trend"), ("actualsort", "trend"),
             ("section", "readytouseitems"), ("days", "-1" if query else "7"), ("p", str(page))]
        if query:
            p.append(("searchtext", query))
        if self.safe:
            p.append(("requiredtags[]", "Everyone"))
        return "https://steamcommunity.com/workshop/browse/?" + urllib.parse.urlencode(p)

    def parse(self, page_html):
        out, seen = [], set()
        for wid, img, title in re.findall(r'filedetails/\?id=(\d+)"[^>]*><img src="([^"]+)" alt="([^"]*)"',
                                          page_html):
            if wid not in seen:
                seen.add(wid)
                out.append(Result(self.name, html.unescape(title), html.unescape(img),
                                  f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}", wid, "Workshop"))
        return out

    @staticmethod
    def details_body(ids: List[str]) -> bytes:
        body = [("itemcount", str(len(ids)))] + [(f"publishedfileids[{i}]", x) for i, x in enumerate(ids)]
        return urllib.parse.urlencode(body).encode()

    @staticmethod
    def apply_details(results: List[Result], data: dict) -> None:
        det = {d.get("publishedfileid"): d for d in data.get("response", {}).get("publishedfiledetails", [])}
        for r in results:
            d = det.get(r.rid)
            if not d:
                continue
            tags = tuple(t.get("tag", "") for t in d.get("tags", []))
            r.badge = next((t for t in tags if t in ("Scene", "Video", "Web", "Application")), "Workshop")
            r.size = int(d.get("file_size") or 0)
            r.tags = tags
            r.preview = d.get("preview_url", "") or r.preview

    def download_url(self, result, best, detail_html=""):
        return None


SOURCES: List[Source] = [MotionBGs(), MoeWalls(), Workshop()]
