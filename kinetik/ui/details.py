# SPDX-License-Identifier: GPL-3.0-or-later
"""Right-hand panels: live preview + info + per-wallpaper properties (like Wallpaper Engine)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QElapsedTimer, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from ..library import Item, human_size
from ..settings import SCALING, SCALING_LABELS, SCALING_TIPS, ItemOptions
from ..sources import Result
from .grid import cover
from .widgets import Group, Segmented, SliderRow, SwitchRow, label

PREVIEW = QSize(352, 198)


class Preview(QFrame):
    """Still image, animated GIF or a muted looping video.

    Video frames are painted into a plain QLabel through a QVideoSink. QVideoWidget is avoided on
    purpose: it creates a native child window the first time it is shown, which makes Qt re-create
    the whole main window (the app visibly jumps/resizes on the first click).
    """

    FRAME_MS = 33   # ~30 fps is plenty for a 352 px preview

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("View")
        self.setFixedSize(PREVIEW + QSize(2, 2))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(PREVIEW)
        lay.addWidget(self.image)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._frame)
        self.player.setVideoOutput(self.sink)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.movie: Optional[QMovie] = None
        self._clock = QElapsedTimer()
        self._clock.start()
        self._playing = False

    def clear(self) -> None:
        self._playing = False
        self.player.stop()
        self.player.setSource(QUrl())
        if self.movie:
            self.movie.stop()
            self.movie = None
        self.image.clear()

    def still(self, pm: Optional[QPixmap]) -> None:
        self.clear()
        if pm and not pm.isNull():
            self.image.setPixmap(cover(pm, PREVIEW))

    def gif(self, path: str) -> None:
        self.clear()
        self.movie = QMovie(path)
        self.movie.setScaledSize(PREVIEW)
        self.image.setMovie(self.movie)
        self.movie.start()

    def play(self, url: QUrl, poster: Optional[QPixmap] = None) -> None:
        self.still(poster)
        self._playing = True
        self.player.setSource(url)
        self.player.play()

    def _frame(self, frame: QVideoFrame) -> None:
        if not self._playing or not frame.isValid() or self._clock.elapsed() < self.FRAME_MS:
            return
        self._clock.restart()
        img = frame.toImage()
        if img.isNull():
            return
        dpr = self.devicePixelRatioF()
        target = QSize(round(PREVIEW.width() * dpr), round(PREVIEW.height() * dpr))
        img = img.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
        img = img.copy((img.width() - target.width()) // 2, (img.height() - target.height()) // 2,
                       target.width(), target.height())
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        self.image.setPixmap(pm)


def _scroll(widget: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    s.setWidget(widget)
    s.setFixedWidth(PREVIEW.width() + 30)
    return s


class ItemPanel(QWidget):
    """Details + properties of a library item."""

    apply = Signal()
    options_changed = Signal(object, object)     # item, ItemOptions
    favorite = Signal(object, bool)
    action = Signal(str, object)                 # "folder" | "workshop" | "delete" | "playlist", item

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(PREVIEW.width() + 10)
        self.item: Optional[Item] = None
        self.default_volume = 60
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(14)
        self.preview = Preview()
        lay.addWidget(self.preview)
        head = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(1)
        self.title = label("", "Heading", wrap=True)
        self.meta = label("", "Subtitle", wrap=True)
        names.addWidget(self.title)
        names.addWidget(self.meta)
        head.addLayout(names, 1)
        self.fav = QToolButton()
        self.fav.setObjectName("Flat")
        self.fav.setCheckable(True)
        self.fav.setText("☆")
        self.fav.setToolTip("Favourite")
        self.fav.toggled.connect(self._fav)
        head.addWidget(self.fav, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self.tags = label("", "Subtitle", wrap=True)
        lay.addWidget(self.tags)

        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("Suggested")
        self.apply_btn.clicked.connect(self.apply)
        btns.addWidget(self.apply_btn, 1)
        self.more = QPushButton("⋯")
        self.more.setToolTip("More")
        btns.addWidget(self.more)
        lay.addLayout(btns)
        self.note = label("", "Subtitle", wrap=True)
        lay.addWidget(self.note)

        disp = Group("Display")
        seg_row = QWidget()
        r = QHBoxLayout(seg_row)
        r.setContentsMargins(14, 8, 10, 8)
        t = QVBoxLayout()
        t.setSpacing(0)
        t.addWidget(label("Scaling"))
        t.addWidget(label("How it fills the screen", "Subtitle"))
        r.addLayout(t, 1)
        self.scaling = Segmented(SCALING_LABELS, SCALING_TIPS)
        self.scaling.changed.connect(self._changed)
        r.addWidget(self.scaling)
        disp.add_row(seg_row)
        self.blur_fill = SwitchRow("Blurred background", "Fill the bars of “Fit” with a blurred copy")
        self.blur_fill.toggled.connect(self._changed)
        disp.add_row(self.blur_fill)
        rot_row = QWidget()
        r2 = QHBoxLayout(rot_row)
        r2.setContentsMargins(14, 8, 10, 8)
        r2.addWidget(label("Rotation"), 1)
        self.rotation = Segmented(["0°", "90°", "180°", "270°"])
        self.rotation.changed.connect(self._changed)
        r2.addWidget(self.rotation)
        self.rot_row = disp.add_row(rot_row)
        lay.addWidget(disp)
        self.disp = disp

        play = Group("Playback")
        self.speed = SliderRow("Speed", "Playback speed", 0.25, 3.0, 1.0, decimals=2, suffix="×", log=True, step=0.05)
        self.speed.changed.connect(self._changed)
        play.add_row(self.speed)
        self.volume = SliderRow("Volume", "When sound is allowed (Settings → Audio)", 0, 100, 60, suffix=" %")
        self.volume.changed.connect(self._changed)
        play.add_row(self.volume)
        for row in (self.speed, self.volume):  # Kolorful's rows reserve 205 px for the title: too wide here
            row.layout().itemAt(0).widget().setFixedWidth(118)
            row.layout().setContentsMargins(12, 8, 6, 8)
            row.spin.setFixedWidth(64)
        lay.addWidget(play)
        self.play_group = play
        lay.addStretch(1)
        self.empty = label("Pick a wallpaper to see its details", "Subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        self._loading = False
        self.set_item(None)

    def set_item(self, item: Optional[Item], opts: Optional[ItemOptions] = None, pixmap: Optional[QPixmap] = None,
                 fav: bool = False, note: str = "") -> None:
        self.item = item
        has = item is not None
        for w in (self.preview, self.title, self.meta, self.tags, self.apply_btn, self.more, self.fav,
                  self.disp, self.play_group, self.note):
            w.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            self.preview.clear()
            return
        self._loading = True
        self.title.setText(item.title)
        bits = [item.label, human_size(item.size)]
        if item.rating:
            bits.append(item.rating)
        self.meta.setText("  ·  ".join(bits))
        self.tags.setText("  ".join(f"#{t}" for t in item.tags[:8]))
        self.tags.setVisible(bool(item.tags))
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.fav.setChecked(fav)
        self.fav.setText("★" if fav else "☆")
        o = opts or ItemOptions()
        self.scaling.group.button(SCALING.index(o.scaling) if o.scaling in SCALING else 0).setChecked(True)
        self.blur_fill.set_checked(o.blur_fill)
        self.disp.card.set_row_visible(self.blur_fill, item.video_capable and o.scaling == "fit")
        self.disp.card.set_row_visible(self.rot_row, item.kind in ("scene", "web"))
        self.rotation.group.button([0, 90, 180, 270].index(o.rotation) if o.rotation in (0, 90, 180, 270)
                                   else 0).setChecked(True)
        self.play_group.setVisible(item.kind != "image")
        self.speed.set_value(o.speed)
        self.volume.default = self.default_volume
        self.volume.set_value(o.volume if o.volume >= 0 else self.default_volume)
        self._loading = False
        # preview
        if item.kind == "gif":
            self.preview.gif(str(item.path))
        elif item.kind in ("video", "we-video"):
            self.preview.play(QUrl.fromLocalFile(str(item.media)), pixmap)
        elif item.is_we and item.preview and item.preview.suffix.lower() == ".gif":
            self.preview.gif(str(item.preview))
        else:
            self.preview.still(pixmap)

    def options(self) -> ItemOptions:
        vol = round(self.volume.value())
        return ItemOptions(
            scaling=SCALING[max(0, self.scaling.current())], blur_fill=self.blur_fill.switch.isChecked(),
            speed=round(self.speed.value(), 2), volume=-1 if vol == self.default_volume else vol,
            rotation=[0, 90, 180, 270][max(0, self.rotation.current())])

    def _changed(self, *_a) -> None:
        if self._loading or not self.item:
            return
        o = self.options()
        self.disp.card.set_row_visible(self.blur_fill, self.item.video_capable and o.scaling == "fit")
        self.options_changed.emit(self.item, o)

    def _fav(self, on: bool) -> None:
        self.fav.setText("★" if on else "☆")
        if not self._loading and self.item:
            self.favorite.emit(self.item, on)

    def set_apply_text(self, n: int) -> None:
        self.apply_btn.setText("Apply" if n <= 1 else f"Apply to {n} screens")
        self.apply_btn.setEnabled(n > 0)


class ResultPanel(QWidget):
    """Details of an online result."""

    primary = Signal(object)      # download & apply / subscribe
    secondary = Signal(object)    # download only
    open_page = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(PREVIEW.width() + 10)
        self.result: Optional[Result] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(14)
        self.preview = Preview()
        lay.addWidget(self.preview)
        self.title = label("", "Heading", wrap=True)
        self.meta = label("", "Subtitle", wrap=True)
        lay.addWidget(self.title)
        lay.addWidget(self.meta)
        self.p_btn = QPushButton()
        self.p_btn.setObjectName("Suggested")
        self.p_btn.clicked.connect(lambda: self.result and self.primary.emit(self.result))
        self.s_btn = QPushButton("Download only")
        self.s_btn.clicked.connect(lambda: self.result and self.secondary.emit(self.result))
        self.o_btn = QPushButton("Open page")
        self.o_btn.clicked.connect(lambda: self.result and self.open_page.emit(self.result))
        lay.addWidget(self.p_btn)
        row = QHBoxLayout()
        row.addWidget(self.s_btn)
        row.addWidget(self.o_btn)
        lay.addLayout(row)
        self.note = label("", "Subtitle", wrap=True)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.empty = label("Pick a wallpaper to preview it", "Subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        self.set_result(None)

    def set_result(self, r: Optional[Result], pixmap: Optional[QPixmap] = None, workshop: bool = False) -> None:
        self.result = r
        has = r is not None
        for w in (self.preview, self.title, self.meta, self.p_btn, self.s_btn, self.o_btn, self.note):
            w.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            self.preview.clear()
            return
        self.title.setText(r.title)
        bits = [r.source.split(" (")[0], r.badge]
        if r.size:
            bits.append(f"{r.size / 1e6:.0f} MB")
        self.meta.setText("  ·  ".join(b for b in bits if b))
        self.p_btn.setText("Subscribe in Steam" if workshop else "Download && apply")
        self.s_btn.setVisible(not workshop)
        self.note.setText("Steam downloads it, then it shows up in your Library automatically." if workshop else
                          "Saved to your library folder.")
        self.preview.still(pixmap)

    def show_preview_video(self, url: str, pixmap: Optional[QPixmap]) -> None:
        self.preview.play(QUrl(url), pixmap)
