# SPDX-License-Identifier: GPL-3.0-or-later
"""Wallpaper grid (rounded tiles, type badge, favourite star) and the thumbnail service."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QModelIndex, QObject, QPointF, QProcess, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImageReader, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QAbstractItemView, QListView, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem)

from .. import paths
from ..sources import UA

THUMB = QSize(224, 126)
DATA = Qt.ItemDataRole.UserRole
BADGE = Qt.ItemDataRole.UserRole + 1
FAV = Qt.ItemDataRole.UserRole + 2
ACTIVE = Qt.ItemDataRole.UserRole + 3
SUB = Qt.ItemDataRole.UserRole + 4

BADGE_COLORS = {"Video": "#3584e4", "GIF": "#9141ac", "Image": "#6f8396", "Scene": "#e66100",
                "WE Video": "#c64600", "Web": "#2190a4", "4K": "#26a269", "HD": "#3584e4",
                "Workshop": "#e66100",
                "⚠ Partly works": "#9c6e03", "⚠ Won't look right": "#c01c28", "✖ May crash": "#a51d2d"}


def cover(pm: QPixmap, size: QSize) -> QPixmap:
    if pm.isNull():
        return pm
    pm = pm.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    return pm.copy((pm.width() - size.width()) // 2, (pm.height() - size.height()) // 2, size.width(), size.height())


class TileDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        view = self.parent()
        grid = view.gridSize() if view is not None else QSize()
        return grid - QSize(2, 2) if grid.isValid() else QSize(THUMB.width() + 16, THUMB.height() + 56)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = option.palette
        fg = pal.color(QPalette.ColorRole.WindowText)
        accent = pal.color(QPalette.ColorRole.Highlight)
        r = QRectF(option.rect).adjusted(6, 6, -6, -6)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if sel or hover:
            bg = QColor(fg)
            bg.setAlphaF(0.12 if sel else 0.06)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), 12, 12)
        img = QRectF(r.left(), r.top(), r.width(), r.width() * 9 / 16)
        path = QPainterPath()
        path.addRoundedRect(img, 9, 9)
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        p.save()
        p.setClipPath(path)
        if isinstance(pm, QPixmap) and not pm.isNull():
            p.drawPixmap(img.toRect(), cover(pm, img.size().toSize()))
        else:
            ph = QColor(fg)
            ph.setAlphaF(0.07)
            p.fillRect(img, ph)
        p.restore()
        if sel:
            p.setPen(QColor(accent))
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = p.pen()
            pen.setWidthF(2.5)
            p.setPen(pen)
            p.drawPath(path)
        small = QFont(option.font)
        small.setPointSizeF(max(7.0, small.pointSizeF() * 0.78))
        small.setBold(True)
        fm = QFontMetrics(small)
        x = img.left() + 7
        for badge in [b for b in (index.data(BADGE) or "").split("|") if b]:
            w = fm.horizontalAdvance(badge) + 12
            box = QRectF(x, img.top() + 7, w, 18)
            p.setPen(Qt.PenStyle.NoPen)
            c = QColor(BADGE_COLORS.get(badge, "#4a4a50"))
            c.setAlphaF(0.92)
            p.setBrush(c)
            p.drawRoundedRect(box, 9, 9)
            p.setPen(QColor("#ffffff"))
            p.setFont(small)
            p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), badge)
            x += w + 4
        if index.data(FAV):
            p.setPen(QColor("#f6d32d"))
            star = QFont(option.font)
            star.setPointSizeF(star.pointSizeF() * 1.25)
            p.setFont(star)
            p.drawText(QRectF(img.right() - 28, img.top() + 3, 24, 24), int(Qt.AlignmentFlag.AlignCenter), "★")
        if index.data(ACTIVE):
            box = QRectF(img.left() + 7, img.bottom() - 25, 0, 18)
            text = index.data(ACTIVE)
            box.setWidth(fm.horizontalAdvance(text) + 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(38, 162, 105, 235))
            p.drawRoundedRect(box, 9, 9)
            p.setPen(QColor("#ffffff"))
            p.setFont(small)
            p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        title = QFont(option.font)
        title.setWeight(QFont.Weight.DemiBold)
        p.setFont(title)
        p.setPen(fg)
        t_rect = QRectF(r.left() + 2, img.bottom() + 6, r.width() - 4, 18)
        p.drawText(t_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   QFontMetrics(title).elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                                                  Qt.TextElideMode.ElideRight, int(t_rect.width())))
        sub = index.data(SUB)
        if sub:
            dim = QColor(fg)
            dim.setAlphaF(0.55)
            p.setPen(dim)
            f = QFont(option.font)
            f.setPointSizeF(f.pointSizeF() * 0.88)
            p.setFont(f)
            s_rect = QRectF(t_rect.left(), t_rect.bottom(), t_rect.width(), 16)
            p.drawText(s_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetrics(f).elidedText(sub, Qt.TextElideMode.ElideRight, int(s_rect.width())))
        p.restore()


class WallGrid(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Grid")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setMouseTracking(True)
        self.setItemDelegate(TileDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setStyleSheet("QListWidget#Grid::item{background:transparent;padding:0;margin:0;}"
                           "QListWidget#Grid::item:selected,QListWidget#Grid::item:hover{background:transparent;}")

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Stretch tiles so each row fills the width evenly (no ragged gap on the right)."""
        super().resizeEvent(event)
        # always reserve the scrollbar's width, else showing it re-wraps the grid into fewer columns
        sb = 0 if self.verticalScrollBar().isVisible() else self.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent) + 4
        avail = self.viewport().width() - sb - 8
        base = THUMB.width() + 16
        cols = max(1, avail // base)
        w = avail // cols
        size = QSize(w, round((w - 12) * 9 / 16) + 62)
        if self.gridSize() != size:
            self.setGridSize(size)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()  # click on empty space closes the details panel
        super().mousePressEvent(event)

    def add(self, title: str, data, badge: str = "", sub: str = "", fav: bool = False,
            pixmap: Optional[QPixmap] = None) -> QListWidgetItem:
        it = QListWidgetItem(title)
        it.setData(DATA, data)
        it.setData(BADGE, badge)
        it.setData(SUB, sub)
        it.setData(FAV, fav)
        if pixmap is not None:
            it.setData(Qt.ItemDataRole.DecorationRole, pixmap)
        it.setToolTip(title)
        self.addItem(it)
        return it


class Thumbs(QObject):
    """Thumbnails for local files (images, GIF first frame, ffmpeg frame of videos) and URLs."""

    ready = Signal(str, QPixmap)   # key, pixmap

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.cache: Dict[str, QPixmap] = {}
        self.queue: List[tuple] = []
        self.running = 0
        self.nam = QNetworkAccessManager(self)
        self.pending: Dict[str, List[Callable]] = {}
        paths.thumbs_dir().mkdir(parents=True, exist_ok=True)

    def _done(self, key: str, pm: QPixmap) -> None:
        if not pm.isNull():
            pm = cover(pm, THUMB * 1.5)
        self.cache[key] = pm
        self.ready.emit(key, pm)

    def local(self, key: str, path: Path, video: bool) -> Optional[QPixmap]:
        """Returns the pixmap now if cached/cheap, else None and emits `ready` later."""
        if key in self.cache:
            return self.cache[key]
        if not video:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            img = reader.read()
            pm = QPixmap.fromImage(img) if not img.isNull() else QPixmap()
            pm = cover(pm, THUMB * 1.5) if not pm.isNull() else pm
            self.cache[key] = pm
            return pm
        out = paths.thumbs_dir() / (hashlib.sha1(str(path).encode()).hexdigest() + ".jpg")
        try:
            fresh = out.exists() and out.stat().st_mtime >= path.stat().st_mtime
        except OSError:
            fresh = False
        if fresh:
            pm = cover(QPixmap(str(out)), THUMB * 1.5)
            self.cache[key] = pm
            return pm
        self.queue.append((key, path, out))
        self._run()
        return None

    def _run(self) -> None:
        while self.running < 3 and self.queue:
            key, src, out = self.queue.pop(0)
            proc = QProcess(self)
            self.running += 1
            proc.finished.connect(lambda *_a, k=key, o=out, pr=proc: self._ffmpeg_done(k, o, pr))
            proc.start("ffmpeg", ["-v", "error", "-y", "-ss", "1.5", "-i", str(src), "-frames:v", "1",
                                  "-vf", "scale=512:-2", str(out)])

    def _ffmpeg_done(self, key: str, out: Path, proc: QProcess) -> None:
        self.running -= 1
        proc.deleteLater()
        self._done(key, QPixmap(str(out)) if out.exists() else QPixmap())
        self._run()

    def remote(self, url: str, referer: str = "") -> Optional[QPixmap]:
        if url in self.cache:
            return self.cache[url]
        if url in self.pending:
            return None
        self.pending[url] = []
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", UA.encode())
        if referer:
            req.setRawHeader(b"Referer", referer.encode())
        reply = self.nam.get(req)

        def finished():
            pm = QPixmap()
            if reply.error() == QNetworkReply.NetworkError.NoError:
                pm.loadFromData(bytes(reply.readAll()))
            reply.deleteLater()
            self.pending.pop(url, None)
            self._done(url, pm)
        reply.finished.connect(finished)
        return None
