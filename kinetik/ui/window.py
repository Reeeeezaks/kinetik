# SPDX-License-Identifier: GPL-3.0-or-later
"""Main window: sidebar (pages + filters), screen picker, Library / Discover / Playlists / Settings."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from PySide6.QtCore import QFileSystemWatcher, QPointF, QProcess, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, engine, library, paths, plasma
from ..library import Item, human_size
from ..settings import AUDIO_CHOICES, BLUR_CHOICES, PAUSE_CHOICES, ItemOptions, Playlist, Store
from ..sources import SOURCES, UA, Result, Workshop
from .arrangement import ScreenPicker
from .details import ItemPanel, ResultPanel
from .grid import ACTIVE, DATA, FAV, THUMB, Thumbs, WallGrid
from .widgets import Group, Segmented, SliderRow, Switch, SwitchRow, Toast, flat_button, label

PAGES = (("Library", ("folder-pictures", "folder-videos", "folder")),
         ("Discover", ("internet-web-browser", "globe", "applications-internet")),
         ("Playlists", ("view-media-playlist", "media-playlist-repeat", "view-list-details")),
         ("Settings", ("configure", "preferences-system", "preferences-other")))
FILTERS = (("All wallpapers", lambda i, f: True), ("Favourites", lambda i, f: i.key in f),
           ("Videos", lambda i, f: i.kind == "video"), ("GIFs", lambda i, f: i.kind == "gif"),
           ("Images", lambda i, f: i.kind == "image"),
           ("Wallpaper Engine: Scenes", lambda i, f: i.kind == "scene"),
           ("Wallpaper Engine: Videos", lambda i, f: i.kind == "we-video"),
           ("Wallpaper Engine: Web", lambda i, f: i.kind == "web"))
SORTS = ("Newest first", "Name", "Largest first", "Type")


def _icon(names) -> QIcon:
    for n in names:
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return QIcon()


def _gif_cache(path: Path) -> Path:
    return paths.cache_dir() / "gif" / (hashlib.sha1(str(path).encode()).hexdigest() + ".mp4")


def _row(title: str, subtitle: str, widget: QWidget) -> QWidget:
    w = QWidget()
    r = QHBoxLayout(w)
    r.setContentsMargins(14, 8, 10, 8)
    t = QVBoxLayout()
    t.setSpacing(0)
    t.addWidget(label(title))
    if subtitle:
        t.addWidget(label(subtitle, "Subtitle", wrap=True))
    r.addLayout(t, 1)
    r.addWidget(widget)
    return w


def _combo(items, current: int, on_change: Callable[[int], None]) -> QComboBox:
    c = QComboBox()
    c.addItems(list(items))
    c.setCurrentIndex(current)
    c.currentIndexChanged.connect(on_change)
    return c


class MainWindow(QMainWindow):
    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store
        self.s = store.settings
        self.items: List[Item] = []
        self.by_key: Dict[str, Item] = {}
        self.monitors: List[plasma.Monitor] = []
        self.active: Dict[str, Set[str]] = {}      # item key -> monitor keys showing it
        self.screen_item: Dict[str, str] = {}      # monitor key -> item key
        self.nam = QNetworkAccessManager(self)
        self.thumbs = Thumbs(self)
        self.thumbs.ready.connect(self._thumb_ready)
        self.detail_html: Dict[str, str] = {}
        self.downloads = 0
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon.fromTheme("kinetik", QIcon(str(Path(__file__).resolve().parent.parent / "assets" / "kinetik.svg"))))
        self.resize(1360, 920)
        self.setMinimumSize(1080, 700)
        self.setAcceptDrops(True)
        self._build()
        self.toast = Toast(self.centralWidget())

        self.push_timer = self._timer(350, self._push_settings)
        self.opt_timer = self._timer(250, self._push_item_options)
        self._pending_opts = None
        self.lib_timer = self._timer(1500, self.refresh_library)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self.lib_timer.start())
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self._focus_search())
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_all)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._escape)

        self.refresh_monitors()
        self.refresh_library()
        QTimer.singleShot(400, self.search)

    def _timer(self, ms: int, slot) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(ms)
        t.timeout.connect(slot)
        return t

    # ================================================================== layout
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 16, 20, 12)
        col.setSpacing(12)
        frame = QFrame()
        frame.setObjectName("View")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(10, 6, 10, 6)
        self.picker = ScreenPicker()
        self.picker.changed.connect(self._screens_changed)
        fl.addWidget(self.picker)
        frame.setFixedHeight(260)
        col.addWidget(frame)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._page_library())
        self.pages.addWidget(self._page_discover())
        self.pages.addWidget(self._page_playlists())
        self.pages.addWidget(self._page_settings())
        col.addWidget(self.pages, 1)
        outer.addWidget(content, 1)
        self.nav.setCurrentRow(0)

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(264)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 14, 12, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label(APP_NAME, "Heading"), 1)
        mb = QToolButton()
        mb.setObjectName("Flat")
        mb.setIcon(_icon(("open-menu-symbolic", "application-menu", "open-menu")))
        if mb.icon().isNull():
            mb.setText("☰")
        mb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction("Refresh screens && library", self.refresh_all)
        menu.addAction("Open library folder", self._open_library)
        menu.addAction("Restart Plasma (fixes a black scene)", self._restart_plasma)
        menu.addSeparator()
        menu.addAction("About", self._about)
        mb.setMenu(menu)
        top.addWidget(mb)
        lay.addLayout(top)
        status = QHBoxLayout()
        ver = plasma.plasma_version()
        self.pill = label(f"● Live · Plasma {ver or ''}".strip(), "PillLive")
        self.pill.setToolTip("Wallpapers change on your screens right away")
        status.addWidget(self.pill)
        self.we_pill = label("", "PillWarn")
        status.addWidget(self.we_pill)
        status.addStretch(1)
        lay.addLayout(status)
        lay.addSpacing(6)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        for title, icons in PAGES:
            QListWidgetItem(_icon(icons), title, self.nav)
        self.nav.setFixedHeight(4 * 42 + 6)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.currentRowChanged.connect(self._page_changed)
        lay.addWidget(self.nav)
        lay.addSpacing(10)
        self.show_label = label("Show", "GroupTitle")
        lay.addWidget(self.show_label)
        self.filter_list = QListWidget()
        for name, _f in FILTERS:
            QListWidgetItem(name, self.filter_list)
        self.filter_list.setCurrentRow(0)
        self.filter_list.currentRowChanged.connect(lambda _r: self._fill_grid())
        lay.addWidget(self.filter_list, 1)
        self.side_spacer = QWidget()  # takes the filters' space on other pages
        self.side_spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.side_spacer.hide()
        lay.addWidget(self.side_spacer, 1)
        self.dl_label = label("", "Subtitle", wrap=True)
        self.dl_bar = QProgressBar()
        self.dl_bar.setTextVisible(False)
        self.dl_bar.setFixedHeight(6)
        for w in (self.dl_label, self.dl_bar):
            w.hide()
            lay.addWidget(w)
        return side

    # ---------------------------------------------------------------- library page
    def _page_library(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        bar = QHBoxLayout()
        self.lib_search = QLineEdit()
        self.lib_search.setPlaceholderText("Search your wallpapers…")
        self.lib_search.setClearButtonEnabled(True)
        self.lib_search.textChanged.connect(lambda _t: self._fill_grid())
        bar.addWidget(self.lib_search, 1)
        self.sort = _combo(SORTS, self.s.sort, self._sort_changed)
        bar.addWidget(self.sort)
        add = QPushButton("Add files…")
        add.clicked.connect(self._add_files)
        bar.addWidget(add)
        v.addLayout(bar)
        body = QHBoxLayout()
        body.setSpacing(14)
        self.grid = WallGrid()
        self.grid.itemSelectionChanged.connect(self._lib_selected)
        self.grid.itemDoubleClicked.connect(lambda it: self.apply_item(it.data(DATA)))
        self.grid.customContextMenuRequested.connect(self._lib_menu)
        body.addWidget(self.grid, 1)
        self.panel = ItemPanel()
        self.panel.default_volume = self.s.volume
        self.panel.apply.connect(lambda: self.panel.item and self.apply_item(self.panel.item))
        self.panel.options_changed.connect(self._options_changed)
        self.panel.favorite.connect(self._set_fav)
        self.panel.more.clicked.connect(lambda: self.panel.item and self._item_menu(
            self.panel.item, self.panel.more.mapToGlobal(self.panel.more.rect().bottomLeft())))
        self.panel_box = self._side_scroll(self.panel)
        self.panel_box.hide()  # pops out when a wallpaper is clicked
        body.addWidget(self.panel_box)
        v.addLayout(body, 1)
        self.lib_hint = label("", "Subtitle")
        v.addWidget(self.lib_hint)
        return w

    def _side_scroll(self, w: QWidget) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        s.setWidget(w)
        s.setFixedWidth(384)
        return s

    # ---------------------------------------------------------------- discover page
    def _page_discover(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        bar = QHBoxLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItem(_icon(("globe", "internet-web-browser")), "All sources")
        for src in SOURCES:
            self.src_combo.addItem(src.short)
            self.src_combo.setItemData(self.src_combo.count() - 1, src.name, Qt.ItemDataRole.ToolTipRole)
        self.src_combo.setToolTip("Where to search")
        self.src_combo.currentIndexChanged.connect(lambda _i: self.search())
        bar.addWidget(self.src_combo)
        self.on_search = QLineEdit()
        self.on_search.setPlaceholderText("Search (empty: newest / trending)…")
        self.on_search.setClearButtonEnabled(True)
        self.on_search.returnPressed.connect(self.search)
        bar.addWidget(self.on_search, 1)
        self.quality = _combo(["HD (lighter)", "Best (4K when available)"], self.s.quality, self._quality_changed)
        self.quality.setToolTip("MotionBGs download quality")
        bar.addWidget(self.quality)
        self.safe_box = QWidget()
        sb = QHBoxLayout(self.safe_box)
        sb.setContentsMargins(6, 0, 0, 0)
        sb.addWidget(label("Safe only"))
        self.safe = Switch()
        self.safe.setChecked(self.s.safe)
        self.safe.setToolTip("Workshop: only show items rated “Everyone”")
        self.safe.toggled.connect(self._safe_changed)
        sb.addWidget(self.safe)
        bar.addWidget(self.safe_box)
        v.addLayout(bar)
        body = QHBoxLayout()
        body.setSpacing(14)
        self.on_grid = WallGrid()
        self.on_grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.on_grid.itemSelectionChanged.connect(self._result_selected)
        self.on_grid.itemDoubleClicked.connect(lambda it: self._result_primary(it.data(DATA)))
        self.on_grid.customContextMenuRequested.connect(self._result_menu)
        body.addWidget(self.on_grid, 1)
        self.rpanel = ResultPanel()
        self.rpanel.primary.connect(self._result_primary)
        self.rpanel.secondary.connect(lambda r: self._download(r, apply_after=False))
        self.rpanel.open_page.connect(lambda r: QDesktopServices.openUrl(QUrl(r.page)))
        self.rpanel_box = self._side_scroll(self.rpanel)
        self.rpanel_box.hide()
        body.addWidget(self.rpanel_box)
        v.addLayout(body, 1)
        low = QHBoxLayout()
        self.on_hint = label("", "Subtitle")
        low.addWidget(self.on_hint, 1)
        self.more_btn = QPushButton("Load more")
        self.more_btn.clicked.connect(self._load_more)
        low.addWidget(self.more_btn)
        v.addLayout(low)
        self.on_page, self.on_query, self.on_sources, self.on_gen = 1, "", list(SOURCES), 0
        self.on_more: List = []
        return w

    # ---------------------------------------------------------------- playlists page
    def _page_playlists(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(label("Playlists", "GroupTitle"))
        self.pl_list = QListWidget()
        self.pl_list.setFixedWidth(230)
        self.pl_list.currentRowChanged.connect(self._pl_selected)
        left.addWidget(self.pl_list, 1)
        row = QHBoxLayout()
        row.addWidget(flat_button("New…", "Create a playlist", self._pl_new))
        row.addStretch(1)
        row.addWidget(flat_button("Delete", "Delete the selected playlist", self._pl_delete))
        left.addLayout(row)
        h.addLayout(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 6, 0)
        rv.setSpacing(16)
        self.pl_title = label("", "Heading")
        rv.addWidget(self.pl_title)
        g = Group("Wallpapers", "Videos, GIFs and Wallpaper Engine videos. Add them from the Library "
                                "(right-click → Add to playlist). Drag to reorder.")
        self.pl_items = QListWidget()
        self.pl_items.setIconSize(QSize(96, 54))
        self.pl_items.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.pl_items.setMinimumHeight(220)
        self.pl_items.model().rowsMoved.connect(lambda *_: self._pl_save_order())
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(6, 6, 6, 6)
        hl.addWidget(self.pl_items)
        rm = QHBoxLayout()
        rm.addStretch(1)
        rm.addWidget(flat_button("Remove selected", "", self._pl_remove))
        hl.addLayout(rm)
        g.add_row(holder)
        rv.addWidget(g)
        g2 = Group("Rotation")
        self.pl_mode = Segmented(["When the video ends", "On a timer"])
        self.pl_mode.changed.connect(lambda _i: self._pl_edit())
        g2.add_row(_row("Change wallpaper", "", self.pl_mode))
        self.pl_minutes = SliderRow("Every", "Minutes between wallpapers", 1, 240, 10, suffix=" min", log=True)
        self.pl_minutes.changed.connect(lambda _v: self._pl_edit())
        g2.add_row(self.pl_minutes)
        self.pl_shuffle = SwitchRow("Shuffle", "Random order")
        self.pl_shuffle.toggled.connect(lambda _v: self._pl_edit())
        g2.add_row(self.pl_shuffle)
        rv.addWidget(g2)
        self.pl_apply = QPushButton("Play on selected screens")
        self.pl_apply.setObjectName("Suggested")
        self.pl_apply.clicked.connect(self._pl_play)
        rv.addWidget(self.pl_apply, 0, Qt.AlignmentFlag.AlignLeft)
        rv.addStretch(1)
        self.pl_right = right
        h.addWidget(self._plain_scroll(right), 1)
        self._pl_refresh()
        return w

    def _plain_scroll(self, w: QWidget) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        s.setWidget(w)
        return s

    # ---------------------------------------------------------------- settings page
    def _page_settings(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 6, 4)
        lay.setSpacing(18)
        s = self.s

        def setter(attr):
            def f(v):
                setattr(s, attr, v)
                self._settings_changed(attr)
            return f

        g = Group("Performance", "Saves CPU/GPU while you work or play. Applies to all screens.")
        g.add_row(_row("Pause the wallpaper", "When to stop animating", _combo(PAUSE_CHOICES, s.pause, setter("pause"))))
        fps = SliderRow("Frame rate", "Wallpaper Engine scenes", 5, 144, 30, suffix=" fps")
        fps.set_value(s.fps)
        fps.changed.connect(lambda v: setter("fps")(int(v)))
        g.add_row(fps)
        mi = SwitchRow("Mouse interaction", "Scenes that react to your cursor")
        mi.set_checked(s.mouse_input)
        mi.toggled.connect(setter("mouse_input"))
        g.add_row(mi)
        g.add_row(_row("Video decoder", "For Wallpaper Engine scene/web videos",
                       _combo(["Qt Multimedia", "mpv (recommended)"], s.video_backend, setter("video_backend"))))
        lay.addWidget(g)

        g = Group("Audio")
        g.add_row(_row("Sound", "Wallpaper Engine scenes only know on/off: anything but “Always muted” plays sound",
                       _combo(AUDIO_CHOICES, s.audio, setter("audio"))))
        vol = SliderRow("Default volume", "Per wallpaper you can override it", 0, 100, 60, suffix=" %")
        vol.set_value(s.volume)
        vol.changed.connect(lambda v: (setter("volume")(int(v)), setattr(self.panel, "default_volume", int(v))))
        g.add_row(vol)
        lay.addWidget(g)

        g = Group("Look")
        g.add_row(_row("Blur the wallpaper", "Videos: soften the desktop behind windows",
                       _combo(BLUR_CHOICES, s.blur, setter("blur"))))
        br = SliderRow("Blur strength", "", 4, 128, 32)
        br.set_value(s.blur_radius)
        br.changed.connect(lambda v: setter("blur_radius")(int(v)))
        g.add_row(br)
        cf = SwitchRow("Crossfade", "Fade between videos in playlists")
        cf.set_checked(s.crossfade)
        cf.toggled.connect(setter("crossfade"))
        g.add_row(cf)
        cd = SliderRow("Crossfade length", "", 200, 5000, 1000, suffix=" ms", step=100)
        cd.set_value(s.crossfade_ms)
        cd.changed.connect(lambda v: setter("crossfade_ms")(int(v)))
        g.add_row(cd)
        bg = _combo(["Black", "Dark grey", "Plasma blue"],
                    {"#000000": 0, "#1d1d20": 1, "#1d99f3": 2}.get(s.background, 0),
                    lambda i: setter("background")(["#000000", "#1d1d20", "#1d99f3"][i]))
        g.add_row(_row("Background colour", "Shows around “Fit” wallpapers", bg))
        rl = SwitchRow("Resume where it left off", "After login, continue the video instead of restarting")
        rl.set_checked(s.resume_last)
        rl.toggled.connect(setter("resume_last"))
        g.add_row(rl)
        lay.addWidget(g)

        g = Group("Wallpaper Engine")
        self.we_status = label("", wrap=True)
        sw = QWidget()
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(14, 10, 10, 10)
        sl.addWidget(self.we_status, 1)
        self.we_install = QPushButton("Install in Steam")
        self.we_install.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("steam://install/431960")))
        sl.addWidget(self.we_install)
        g.add_row(sw)
        rnd = SwitchRow("Random scene", "Switch to a random Wallpaper Engine wallpaper on a timer")
        rnd.set_checked(s.we_random)
        rnd.toggled.connect(setter("we_random"))
        g.add_row(rnd)
        rm = SliderRow("Every", "", 1, 240, 30, suffix=" min", log=True)
        rm.set_value(s.we_random_minutes)
        rm.changed.connect(lambda v: setter("we_random_minutes")(int(v)))
        g.add_row(rm)
        lay.addWidget(g)

        g = Group("Library")
        self.lib_path_label = label(s.library, "Subtitle", wrap=True)
        lw = QWidget()
        ll = QHBoxLayout(lw)
        ll.setContentsMargins(14, 8, 10, 8)
        t = QVBoxLayout()
        t.setSpacing(0)
        t.addWidget(label("Library folder"))
        t.addWidget(self.lib_path_label)
        ll.addLayout(t, 1)
        ch = QPushButton("Change…")
        ch.clicked.connect(self._change_library)
        ll.addWidget(ch)
        g.add_row(lw)
        cl = QPushButton("Clear")
        cl.clicked.connect(self._clear_cache)
        g.add_row(_row("Thumbnail cache", "Previews and converted GIFs", cl))
        lay.addWidget(g)
        lay.addStretch(1)
        return self._plain_scroll(page)

    # ================================================================== screens
    def refresh_monitors(self) -> None:
        self.monitors = plasma.monitors()
        self.picker.set_monitors(self.monitors, set(self.s.selected_screens))
        self._screens_changed(self.picker.selected(), save=False)
        self.refresh_current()

    def _screens_changed(self, sel, save: bool = True) -> None:
        if save:
            self.s.selected_screens = sorted(sel)
            self.store.save()
        self.panel.set_apply_text(len(sel))
        names = ", ".join(m.short for m in self.monitors if m.key in sel)
        self.pl_apply.setText(f"Play on {names}" if names else "Pick a screen first")

    def targets(self) -> List[int]:
        sel = self.picker.selected()
        t = [m.screen for m in self.monitors if m.key in sel]
        if not t:
            self.toast.show_message("Pick a screen at the top first")
        return t

    def refresh_current(self) -> None:
        cur = plasma.current()
        self.active.clear()
        self.screen_item.clear()
        gif_map = {str(_gif_cache(i.path)): i.key for i in self.items if i.kind == "gif"}
        for m in self.monitors:
            info = cur.get(m.screen)
            if not info:
                continue
            src = QUrl(info.get("source", "")).toLocalFile()
            key = ""
            if info["plugin"] == plasma.WE_PLUGIN and src:
                key = f"we:{Path(src).parent.name}"
            elif src:
                key = gif_map.get(src) or next((i.key for i in self.items if str(i.media) == src), "")
            caption = ""
            if key and key in self.by_key:
                it = self.by_key[key]
                self.active.setdefault(key, set()).add(m.key)
                self.screen_item[m.key] = key
                caption = it.title + (" (playlist)" if info.get("count", 1) > 1 else "")
                pm = self._item_thumb(it)
            elif src:
                caption = Path(src).name
                video = info["plugin"] == plasma.SMART_VIDEO
                pm = self.thumbs.local("screen:" + src, Path(src), video) if Path(src).exists() else None
            else:
                pm = None
            self.picker.set_thumb(m.key, pm or QPixmap(), caption)
        self._update_active_badges()

    def _update_active_badges(self) -> None:
        by_mon = {m.key: m.short for m in self.monitors}
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            mons = self.active.get(it.data(DATA).key, set())
            text = "" if not mons else ("▶ " + by_mon.get(next(iter(mons)), "") if len(mons) == 1
                                        else f"▶ {len(mons)} screens")
            it.setData(ACTIVE, text)

    # ================================================================== library
    def refresh_all(self) -> None:
        self.refresh_monitors()
        self.refresh_library()

    def refresh_library(self) -> None:
        lib = self.s.library_path
        lib.mkdir(parents=True, exist_ok=True)
        self.items = library.scan(lib)
        self.by_key = {i.key: i for i in self.items}
        dirs = [str(lib)] + [str(d) for d in library.workshop_dirs()]
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.watcher.addPaths(dirs)
        self._update_counts()
        self._fill_grid()
        self._update_we_status()
        if self.monitors:
            self.refresh_current()

    def _update_counts(self) -> None:
        for row, (name, f) in enumerate(FILTERS):
            n = sum(1 for i in self.items if f(i, self.store.favorites))
            self.filter_list.item(row).setText(f"{name}  ({n})" if n else name)

    def _sorted(self, items: List[Item]) -> List[Item]:
        key = [lambda i: -i.mtime, lambda i: i.title.lower(), lambda i: -i.size, lambda i: (i.kind, i.title.lower())]
        return sorted(items, key=key[self.s.sort])

    def _fill_grid(self) -> None:
        sel_key = self.panel.item.key if self.panel.item else ""
        q = self.lib_search.text().lower().strip()
        f = FILTERS[max(0, self.filter_list.currentRow())][1]
        shown = [i for i in self._sorted(self.items) if f(i, self.store.favorites)
                 and (not q or q in i.title.lower() or any(q in t.lower() for t in i.tags))]
        self.grid.clear()
        for i in shown:
            sub = f"{i.label} · {human_size(i.size)}"
            w = self.grid.add(i.title, i, badge=i.label, sub=sub, fav=i.key in self.store.favorites,
                              pixmap=self._item_thumb(i))
            if i.key == sel_key:
                w.setSelected(True)
        self._update_active_badges()
        n_we = sum(i.is_we for i in self.items)
        self.lib_hint.setText(f"{len(shown)} shown  ·  {len(self.items) - n_we} in your folder, {n_we} from the "
                              "Workshop  ·  double-click to apply  ·  drop files here to add them")
        if not sel_key:
            self._close_panel()

    def _item_thumb(self, i: Item) -> Optional[QPixmap]:
        if i.is_we:
            return self.thumbs.local(i.key, i.preview, False) if i.preview else None
        return self.thumbs.local(i.key, i.path, i.kind == "video")

    def _thumb_ready(self, key: str, pm: QPixmap) -> None:
        for grid in (self.grid, self.on_grid):
            for n in range(grid.count()):
                it = grid.item(n)
                d = it.data(DATA)
                k = d.key if isinstance(d, Item) else d.thumb
                if k == key:
                    it.setData(Qt.ItemDataRole.DecorationRole, pm)
        if key.startswith("screen:"):
            self.refresh_current_thumbs(key, pm)
        elif key in self.active:
            for mk in self.active[key]:
                self.picker.set_thumb(mk, pm, self.by_key[key].title)
        if self.panel.item and self.panel.item.key == key and self.panel.item.kind not in ("video", "we-video", "gif"):
            self.panel.preview.still(pm)
        if self.rpanel.result and self.rpanel.result.thumb == key and not self.rpanel.preview.player.source().isValid():
            self.rpanel.preview.still(pm)

    def refresh_current_thumbs(self, key: str, pm: QPixmap) -> None:
        src = key[len("screen:"):]
        for mk, cap in list(self.picker.view.captions.items()):
            if cap == Path(src).name:
                self.picker.set_thumb(mk, pm, cap)

    def _close_panel(self) -> None:
        self.panel.set_item(None)
        self.panel_box.hide()

    def _close_rpanel(self) -> None:
        self.rpanel.set_result(None)
        self.rpanel_box.hide()

    def _escape(self) -> None:
        if self.pages.currentIndex() == 0:
            self.grid.clearSelection()
            self._close_panel()
        elif self.pages.currentIndex() == 1:
            self.on_grid.clearSelection()
            self._close_rpanel()

    def _lib_selected(self) -> None:
        sel = self.grid.selectedItems()
        if not sel:
            self._close_panel()
            return
        self.panel_box.show()
        it: Item = sel[-1].data(DATA)
        note = ""
        if it.kind in ("scene", "web") and not library.we_install_library():
            note = "Needs Wallpaper Engine installed in Steam (Settings → Wallpaper Engine)."
        if len(sel) > 1:
            note = f"{len(sel)} selected - right-click to add them all to a playlist."
        self.panel.set_item(it, self.store.item_options(it.key), self._item_thumb(it),
                            it.key in self.store.favorites, note)

    def _sort_changed(self, i: int) -> None:
        self.s.sort = i
        self.store.save()
        self._fill_grid()

    def _focus_search(self) -> None:
        (self.lib_search if self.pages.currentIndex() == 0 else self.on_search).setFocus()

    def _page_changed(self, row: int) -> None:
        self.pages.setCurrentIndex(max(row, 0))
        for w in (self.show_label, self.filter_list):  # filters only make sense in the Library
            w.setVisible(row == 0)
        self.side_spacer.setVisible(row != 0)
        if row != 0:
            self.panel.preview.clear()
        elif self.panel.item:
            self._lib_selected()
        if row != 1:
            self.rpanel.preview.player.stop()
        if row == 2:
            self._pl_refresh()

    def _lib_menu(self, pos) -> None:
        it = self.grid.itemAt(pos)
        if it:
            self._item_menu(it.data(DATA), self.grid.mapToGlobal(pos))

    def _item_menu(self, item: Item, at) -> None:
        sel = [x.data(DATA) for x in self.grid.selectedItems()] or [item]
        m = QMenu(self)
        m.addAction("Apply", lambda: self.apply_item(item))
        fav = item.key in self.store.favorites
        m.addAction("Remove from favourites" if fav else "Add to favourites", lambda: self._set_fav(item, not fav))
        playable = [x for x in sel if x.video_capable]
        if playable:
            sub = m.addMenu(f"Add to playlist ({len(playable)})" if len(playable) > 1 else "Add to playlist")
            for p in self.store.playlists:
                sub.addAction(p.name, lambda p=p: self._pl_add(p, playable))
            sub.addSeparator()
            sub.addAction("New playlist…", lambda: self._pl_new(playable))
        m.addSeparator()
        m.addAction("Show in folder", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(item.path if item.is_we else item.path.parent))))
        if item.is_we:
            m.addAction("Workshop page (unsubscribe there)",
                        lambda: QDesktopServices.openUrl(QUrl(f"steam://url/CommunityFilePage/{item.wid}")))
        else:
            m.addAction("Delete…", lambda: self._delete(sel))
        m.exec(at)

    def _set_fav(self, item: Item, on: bool) -> None:
        (self.store.favorites.add if on else self.store.favorites.discard)(item.key)
        self.store.save()
        for n in range(self.grid.count()):
            if self.grid.item(n).data(DATA).key == item.key:
                self.grid.item(n).setData(FAV, on)
        self._update_counts()
        if self.panel.item and self.panel.item.key == item.key:
            self.panel.fav.setChecked(on)

    def _delete(self, items: List[Item]) -> None:
        items = [i for i in items if not i.is_we]
        if not items:
            return
        names = items[0].title if len(items) == 1 else f"{len(items)} wallpapers"
        if QMessageBox.question(self, APP_NAME, f"Delete {names} from your library folder?") != \
                QMessageBox.StandardButton.Yes:
            return
        for i in items:
            i.path.unlink(missing_ok=True)
        self._close_panel()
        self.refresh_library()

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add wallpapers", str(Path.home()),
            "Wallpapers (*.mp4 *.webm *.mkv *.mov *.m4v *.gif *.jpg *.jpeg *.png *.webp *.avif)")
        self._import([Path(f) for f in files])

    def _import(self, files: List[Path]) -> None:
        n = 0
        exts = library.VIDEO_EXT | library.GIF_EXT | library.IMAGE_EXT
        for f in files:
            if f.is_file() and f.suffix.lower() in exts:
                dst = self.s.library_path / f.name
                if dst.resolve() != f.resolve():
                    shutil.copy2(f, dst)
                n += 1
        if n:
            self.toast.show_message(f"Added {n} wallpaper{'s' if n > 1 else ''} to your library")
            self.nav.setCurrentRow(0)
            self.refresh_library()

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        self._import([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])

    # ================================================================== apply
    def apply_item(self, item: Item, screens: Optional[List[int]] = None) -> None:
        t = screens or self.targets()
        if not t:
            return
        o = self.store.item_options(item.key)
        try:
            if item.kind in ("video", "we-video"):
                plasma.apply(t, plasma.SMART_VIDEO,
                             engine.video_config(self.s, [(engine.file_url(item.media), o)]))
            elif item.kind == "gif":
                self._as_video(item, lambda mp4: self._apply_cfg(
                    t, plasma.SMART_VIDEO, engine.video_config(self.s, [(engine.file_url(mp4), o)]), item))
                return
            elif item.kind == "image":
                plasma.apply(t, plasma.IMAGE, engine.image_config(self.s, item, o))
            else:
                lib = library.we_install_library()
                if not lib:
                    if QMessageBox.question(
                            self, APP_NAME, "Wallpaper Engine scenes need Wallpaper Engine installed in Steam "
                            "(only for its shared files - you never have to open it).\n\nOpen the Steam install "
                            "dialog now?") == QMessageBox.StandardButton.Yes:
                        QDesktopServices.openUrl(QUrl("steam://install/431960"))
                    return
                engine.write_we_item_options(item.wid, engine.we_item_options(self.s, o))
                plasma.apply(t, plasma.WE_PLUGIN, engine.we_config(self.s, item, o, lib))
        except plasma.PlasmaError as exc:
            QMessageBox.warning(self, APP_NAME, f"Plasma refused the wallpaper:\n{exc}")
            return
        self._applied(item, len(t))

    def _apply_cfg(self, t, plugin, cfg, item: Item) -> None:
        try:
            plasma.apply(t, plugin, cfg)
        except plasma.PlasmaError as exc:
            QMessageBox.warning(self, APP_NAME, f"Plasma refused the wallpaper:\n{exc}")
            return
        self._applied(item, len(t))

    def _applied(self, item: Item, n: int) -> None:
        self.toast.show_message(f"“{item.title}” is now your wallpaper" + (f" on {n} screens" if n > 1 else ""))
        QTimer.singleShot(600, self.refresh_current)

    def _as_video(self, item: Item, then: Callable[[Path], None]) -> None:
        out = _gif_cache(item.path)
        if out.exists() and out.stat().st_mtime >= item.path.stat().st_mtime:
            then(out)
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        self.toast.show_message("Converting the GIF to a video (lighter to play)…")
        proc = QProcess(self)

        def done(code, _status):
            proc.deleteLater()
            if code == 0 and out.exists():
                then(out)
            else:
                QMessageBox.warning(self, APP_NAME, "Could not convert the GIF (ffmpeg failed).")
        proc.finished.connect(done)
        proc.start("ffmpeg", ["-v", "error", "-y", "-i", str(item.path), "-movflags", "+faststart",
                              "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                              "-c:v", "libx264", "-crf", "18", str(out)])

    def _options_changed(self, item: Item, o: ItemOptions) -> None:
        self.store.set_item_options(item.key, o)
        if item.key in self.active:
            self._pending_opts = (item, o)
            self.opt_timer.start()

    def _push_item_options(self) -> None:
        if not self._pending_opts:
            return
        item, o = self._pending_opts
        screens = [m.screen for m in self.monitors if m.key in self.active.get(item.key, set())]
        try:
            if item.is_we and item.kind in ("scene", "web"):
                engine.write_we_item_options(item.wid, engine.we_item_options(self.s, o))
            for plugin, keys in engine.current_options_update(item, self.s, o).items():
                plasma.apply(screens, plugin, keys, switch=False)
            if item.kind in ("scene", "web"):  # make the WE plugin re-read its per-wallpaper file
                plasma.evaluate("var T=%s;desktops().forEach(function(d){if(T.indexOf(d.screen)<0)return;"
                                "d.currentConfigGroup=['Wallpaper','%s','General'];"
                                "d.writeConfig('PerOptChanged',d.readConfig('PerOptChanged')!='true');});"
                                % (json.dumps(screens), plasma.WE_PLUGIN))
        except plasma.PlasmaError as exc:
            self.toast.show_message(f"Could not update the wallpaper: {exc}")

    # ================================================================== settings
    def _settings_changed(self, attr: str) -> None:
        self.store.save()
        self.push_timer.start()

    def _push_settings(self) -> None:
        try:
            engine.push_settings(self.s, [m.screen for m in self.monitors])
        except plasma.PlasmaError as exc:
            self.toast.show_message(f"Could not update the wallpapers: {exc}")
            return
        for key, mons in self.active.items():
            it = self.by_key.get(key)
            if it and it.kind in ("scene", "web"):
                engine.write_we_item_options(it.wid, engine.we_item_options(self.s, self.store.item_options(key)))
        self.toast.show_message("Settings applied", 1.5)

    def _update_we_status(self) -> None:
        lib = library.we_install_library()
        n = sum(i.kind in ("scene", "web", "we-video") for i in self.items)
        if lib:
            self.we_status.setText(f"Installed in {lib}  ·  {n} Workshop wallpapers")
            self.we_pill.hide()
        else:
            self.we_status.setText("Not installed. Scenes need it for their shared files (you never have to open it). "
                                   "Video wallpapers work without it.")
            self.we_pill.setText("WE not installed")
            self.we_pill.setToolTip("Wallpaper Engine scenes need Wallpaper Engine installed in Steam")
            self.we_pill.setVisible(n > 0)
        self.we_install.setVisible(not lib)

    def _change_library(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Library folder", self.s.library)
        if d:
            self.s.library = d
            self.lib_path_label.setText(d)
            self.store.save()
            self.refresh_library()

    def _clear_cache(self) -> None:
        shutil.rmtree(paths.cache_dir(), ignore_errors=True)
        self.thumbs.cache.clear()
        paths.thumbs_dir().mkdir(parents=True, exist_ok=True)
        self.refresh_library()
        self.toast.show_message("Cache cleared")

    def _open_library(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.s.library))

    def _restart_plasma(self) -> None:
        if QMessageBox.question(self, APP_NAME, "Restart the Plasma desktop shell? Your panels and wallpapers "
                                "reload; open windows stay.") == QMessageBox.StandardButton.Yes:
            QProcess.startDetached("systemctl", ["--user", "restart", "plasma-plasmashell"])

    def _about(self) -> None:
        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME} {__version__}</b><br>Live wallpapers for KDE Plasma."
                          "<br><br>Videos & GIFs play with <i>Smart Video Wallpaper Reborn</i>, Wallpaper Engine "
                          "scenes with <i>Wallpaper Engine for KDE</i>.")

    # ================================================================== discover
    def _quality_changed(self, i: int) -> None:
        self.s.quality = i
        self.store.save()

    def _safe_changed(self, on: bool) -> None:
        self.s.safe = on
        self.store.save()
        self.search()

    def _get(self, url: str, cb: Callable[[QNetworkReply], None], referer: str = "") -> None:
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", UA.encode())
        if referer:
            req.setRawHeader(b"Referer", referer.encode())
        r = self.nam.get(req)
        r.finished.connect(lambda: (cb(r), r.deleteLater()))

    def search(self) -> None:
        i = self.src_combo.currentIndex()
        self.on_sources = list(SOURCES) if i <= 0 else [SOURCES[i - 1]]
        self.on_query = self.on_search.text().strip()
        self.on_page = 1
        Workshop.safe = self.s.safe
        has_ws = any(isinstance(x, Workshop) for x in self.on_sources)
        self.quality.setVisible(any(not isinstance(x, Workshop) for x in self.on_sources))
        self.safe_box.setVisible(has_ws)
        self.on_grid.clear()
        self._close_rpanel()
        self._fetch(self.on_sources)

    def _load_more(self) -> None:
        self.on_page += 1
        self._fetch(self.on_more)

    def _fetch(self, sources: List) -> None:
        """Query each source in parallel; when all answered, add the results interleaved."""
        self.on_gen += 1
        gen, q, page = self.on_gen, self.on_query, self.on_page
        self.more_btn.setEnabled(False)
        names = ", ".join(x.short for x in sources)
        self.on_hint.setText(f"Searching {names}…")
        got: Dict[str, List[Result]] = {}
        errors: List[str] = []

        def finish() -> None:
            lists = [got.get(x.name, []) for x in sources]
            for n in range(max((len(l) for l in lists), default=0)):   # round-robin mix
                for lst in lists:
                    if n < len(lst):
                        res = lst[n]
                        src = next(x for x in SOURCES if x.name == res.source)
                        self.on_grid.add(res.title, res, badge=res.badge, sub=src.short,
                                         pixmap=self.thumbs.remote(res.thumb, res.page))
            ws = [r for x in sources if isinstance(x, Workshop) for r in got.get(x.name, [])]
            if ws:
                self._workshop_details(ws)
            self.on_more = [x for x in sources if got.get(x.name) and (x.paged_search or not q)]
            self.more_btn.setEnabled(bool(self.on_more))
            n = self.on_grid.count()
            hint = f"{n} results  ·  double-click to " + (
                "subscribe in Steam" if all(isinstance(x, Workshop) for x in sources) else "download & apply"
                + (" (Workshop: subscribe in Steam)" if len(sources) > 1 else "")) if n else "Nothing found"
            if errors:
                hint += "  ·  ⚠ " + "; ".join(errors)
            self.on_hint.setText(hint)

        def done_for(src):
            def done(r: QNetworkReply) -> None:
                if gen != self.on_gen:
                    return
                if r.error() != QNetworkReply.NetworkError.NoError:
                    errors.append(f"{src.short}: {r.errorString()}")
                    got[src.name] = []
                else:
                    try:
                        got[src.name] = src.parse(bytes(r.readAll()).decode("utf-8", "ignore"))
                    except Exception as exc:  # a site redesign must not break the others
                        errors.append(f"{src.short}: {exc}")
                        got[src.name] = []
                if len(got) == len(sources):
                    finish()
            return done

        for src in sources:
            self._get(src.url(q, page), done_for(src))

    def _workshop_details(self, results: List[Result]) -> None:
        req = QNetworkRequest(QUrl(Workshop.DETAILS_API))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/x-www-form-urlencoded")
        r = self.nam.post(req, Workshop.details_body([x.rid for x in results]))

        def done():
            try:
                Workshop.apply_details(results, json.loads(bytes(r.readAll())))
            except ValueError:
                pass
            r.deleteLater()
            for n in range(self.on_grid.count()):
                it = self.on_grid.item(n)
                res = it.data(DATA)
                if res in results:
                    it.setData(Qt.ItemDataRole.UserRole + 1, res.badge)
                    it.setData(Qt.ItemDataRole.UserRole + 4,
                               f"Workshop · {res.badge} · {res.size / 1e6:.0f} MB" if res.size else f"Workshop · {res.badge}")
            if self.rpanel.result in results:
                self._result_selected()
        r.finished.connect(done)

    def _result_selected(self) -> None:
        sel = self.on_grid.selectedItems()
        if not sel:
            self._close_rpanel()
            return
        self.rpanel_box.show()
        res: Result = sel[0].data(DATA)
        src = next(s for s in SOURCES if s.name == res.source)
        ws = isinstance(src, Workshop)
        self.rpanel.set_result(res, self.thumbs.cache.get(res.thumb), workshop=ws)
        if ws:
            if res.preview:
                pm = self.thumbs.remote(res.preview)
                if pm:
                    self.rpanel.preview.still(pm)
            return
        if res.preview:
            self.rpanel.show_preview_video(res.preview, self.thumbs.cache.get(res.thumb))
            return

        def got(r: QNetworkReply) -> None:
            page = bytes(r.readAll()).decode("utf-8", "ignore")
            self.detail_html[res.page] = page
            src.detail(res, page)
            if res.preview and self.rpanel.result is res:
                self.rpanel.show_preview_video(res.preview, self.thumbs.cache.get(res.thumb))
        self._get(res.page, got)

    def _result_menu(self, pos) -> None:
        it = self.on_grid.itemAt(pos)
        if not it:
            return
        res = it.data(DATA)
        m = QMenu(self)
        if res.source == Workshop.name:
            m.addAction("Subscribe in Steam", lambda: self._result_primary(res))
        else:
            m.addAction("Download && apply", lambda: self._download(res, True))
            m.addAction("Download only", lambda: self._download(res, False))
        m.addAction("Open page in browser", lambda: QDesktopServices.openUrl(QUrl(res.page)))
        m.exec(self.on_grid.mapToGlobal(pos))

    def _result_primary(self, res: Result) -> None:
        if res.source == Workshop.name:
            QDesktopServices.openUrl(QUrl(f"steam://url/CommunityFilePage/{res.rid}"))
            self.toast.show_message("Opened in Steam: press Subscribe. It appears in your Library once downloaded.", 6)
        else:
            self._download(res, True)

    def _download(self, res: Result, apply_after: bool) -> None:
        src = next(s for s in SOURCES if s.name == res.source)
        best = self.s.quality == 1
        if src.needs_detail and res.page not in self.detail_html:
            self._get(res.page, lambda r: (self.detail_html.__setitem__(
                res.page, bytes(r.readAll()).decode("utf-8", "ignore")), self._download(res, apply_after)))
            return
        url = src.download_url(res, best, self.detail_html.get(res.page, ""))
        if not url:
            QMessageBox.warning(self, APP_NAME, "Couldn't find the download link (the site may have changed).")
            return
        safe = "".join(c for c in res.title if c.isalnum() or c in " -_()[]").strip()[:90] or "wallpaper"
        dest = self.s.library_path / f"{safe}.mp4"
        if dest.exists():
            self.toast.show_message("Already in your library")
            if apply_after:
                self.refresh_library()
                if str(dest) in self.by_key:
                    self.apply_item(self.by_key[str(dest)])
            return
        part = dest.with_suffix(".part")
        fh = open(part, "wb")
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", UA.encode())
        req.setRawHeader(b"Referer", res.page.encode())
        reply = self.nam.get(req)
        self.downloads += 1
        self.dl_label.setText(f"Downloading “{res.title}”…")
        self.dl_label.show()
        self.dl_bar.show()
        self.dl_bar.setValue(0)
        reply.readyRead.connect(lambda: fh.write(bytes(reply.readAll())))
        reply.downloadProgress.connect(lambda a, b: (self.dl_bar.setMaximum(max(b, 1)), self.dl_bar.setValue(a)))

        def done():
            fh.write(bytes(reply.readAll()))
            fh.close()
            self.downloads -= 1
            if not self.downloads:
                self.dl_label.hide()
                self.dl_bar.hide()
            ctype = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or "")
            ok = reply.error() == QNetworkReply.NetworkError.NoError and part.stat().st_size > 100_000 \
                and "text/html" not in ctype
            err = reply.errorString()
            reply.deleteLater()
            if not ok:
                part.unlink(missing_ok=True)
                QMessageBox.warning(self, APP_NAME, f"Download failed: {err or 'not a video file'}")
                return
            final = dest.with_suffix(".webm") if "webm" in ctype else dest
            part.rename(final)
            self.refresh_library()
            if apply_after and str(final) in self.by_key:
                self.apply_item(self.by_key[str(final)])
            else:
                self.toast.show_message(f"Saved “{res.title}” to your library")
        reply.finished.connect(done)

    # ================================================================== playlists
    def _pl_refresh(self) -> None:
        row = self.pl_list.currentRow()
        self.pl_list.blockSignals(True)
        self.pl_list.clear()
        for p in self.store.playlists:
            QListWidgetItem(f"{p.name}  ({len(p.items)})", self.pl_list)
        self.pl_list.blockSignals(False)
        if self.store.playlists:
            self.pl_list.setCurrentRow(min(max(row, 0), len(self.store.playlists) - 1))
            self._pl_selected(self.pl_list.currentRow())
        else:
            self.pl_right.setEnabled(False)
            self.pl_title.setText("No playlists yet - click “New…”")
            self.pl_items.clear()

    def _pl_current(self) -> Optional[Playlist]:
        r = self.pl_list.currentRow()
        return self.store.playlists[r] if 0 <= r < len(self.store.playlists) else None

    def _pl_selected(self, _row: int) -> None:
        p = self._pl_current()
        self.pl_right.setEnabled(p is not None)
        if not p:
            return
        self.pl_title.setText(p.name)
        self.pl_items.clear()
        for key in p.items:
            it = self.by_key.get(key)
            li = QListWidgetItem(it.title if it else f"(missing) {Path(key).name}")
            li.setData(DATA, key)
            pm = self._item_thumb(it) if it else None
            if pm:
                li.setIcon(QIcon(pm))
            self.pl_items.addItem(li)
        for w in (self.pl_mode, self.pl_minutes, self.pl_shuffle):
            w.blockSignals(True)
        self.pl_mode.group.button(0 if p.mode == "end" else 1).setChecked(True)
        self.pl_minutes.set_value(p.minutes)
        self.pl_shuffle.set_checked(p.shuffle)
        for w in (self.pl_mode, self.pl_minutes, self.pl_shuffle):
            w.blockSignals(False)
        self.pl_minutes.setEnabled(p.mode == "timer")

    def _pl_new(self, items: Optional[List[Item]] = None) -> None:
        name, ok = QInputDialog.getText(self, "New playlist", "Name:", text=f"Playlist {len(self.store.playlists) + 1}")
        if not ok or not name.strip():
            return
        p = Playlist(name.strip(), [i.key for i in (items or []) if i.video_capable])
        self.store.playlists.append(p)
        self.store.save()
        self._pl_refresh()
        self.pl_list.setCurrentRow(len(self.store.playlists) - 1)
        if items:
            self.toast.show_message(f"Created “{p.name}” with {len(p.items)} wallpapers")

    def _pl_add(self, p: Playlist, items: List[Item]) -> None:
        new = [i.key for i in items if i.video_capable and i.key not in p.items]
        p.items += new
        self.store.save()
        self.toast.show_message(f"Added {len(new)} to “{p.name}”")
        self._pl_refresh()

    def _pl_delete(self) -> None:
        p = self._pl_current()
        if p and QMessageBox.question(self, APP_NAME, f"Delete the playlist “{p.name}”? The wallpapers stay.") == \
                QMessageBox.StandardButton.Yes:
            self.store.playlists.remove(p)
            self.store.save()
            self._pl_refresh()

    def _pl_remove(self) -> None:
        p = self._pl_current()
        if not p:
            return
        gone = {li.data(DATA) for li in self.pl_items.selectedItems()}
        p.items = [k for k in p.items if k not in gone]
        self.store.save()
        self._pl_refresh()

    def _pl_save_order(self) -> None:
        p = self._pl_current()
        if p:
            p.items = [self.pl_items.item(i).data(DATA) for i in range(self.pl_items.count())]
            self.store.save()

    def _pl_edit(self) -> None:
        p = self._pl_current()
        if not p:
            return
        p.mode = "end" if self.pl_mode.current() == 0 else "timer"
        p.minutes = int(self.pl_minutes.value())
        p.shuffle = self.pl_shuffle.switch.isChecked()
        self.pl_minutes.setEnabled(p.mode == "timer")
        self.store.save()

    def _pl_play(self) -> None:
        p = self._pl_current()
        t = self.targets()
        if not p or not t:
            return
        items = [self.by_key[k] for k in p.items if k in self.by_key and self.by_key[k].video_capable]
        if not items:
            self.toast.show_message("This playlist has no playable wallpapers")
            return
        resolved: List[tuple] = []

        def step(i: int) -> None:
            if i == len(items):
                cfg = engine.video_config(self.s, resolved, p)
                self._apply_cfg(t, plasma.SMART_VIDEO, cfg, Item(p.name, "video", p.name, Path(p.name)))
                return
            it = items[i]
            o = self.store.item_options(it.key)
            if it.kind == "gif":
                self._as_video(it, lambda mp4: (resolved.append((engine.file_url(mp4), o)), step(i + 1)))
            else:
                resolved.append((engine.file_url(it.media), o))
                step(i + 1)
        step(0)
