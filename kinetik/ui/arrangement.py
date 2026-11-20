# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen picker (from Kolorful): your real desktop layout, each screen showing its wallpaper.

Click a screen to pick it, Ctrl+click to pick several. Name tabs above stay in sync.
"""

from __future__ import annotations

from typing import Dict, List, Set

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QIcon, QLinearGradient, QMouseEvent, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from ..plasma import ROTATION_INVERTED, ROTATION_LEFT, ROTATION_RIGHT, Monitor
from .widgets import label

GAP = 4.0
MARGIN = 14.0
EDGE = 6.0


def tab_text(text: str) -> str:
    if len(text) <= 22 or " " not in text:
        return text
    head, _, tail = text.rpartition(" ")
    if len(head) > 30:
        spaces = [i for i, c in enumerate(text) if c == " "]
        cut = min(spaces, key=lambda i: abs(i - len(text) // 2))
        head, tail = text[:cut], text[cut + 1:]
    return f"{head}\n{tail}"


def _ctrl() -> bool:
    return bool(QApplication.keyboardModifiers() & (Qt.KeyboardModifier.ControlModifier |
                                                    Qt.KeyboardModifier.ShiftModifier))


class ArrangementView(QWidget):
    clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.monitors: List[Monitor] = []
        self.selected: Set[str] = set()
        self.thumbs: Dict[str, QPixmap] = {}
        self.captions: Dict[str, str] = {}
        self._hover = ""
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Screen layout")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, 220)

    def rects(self) -> Dict[str, QRectF]:
        if not self.monitors:
            return {}
        left = min(m.geometry[0] for m in self.monitors)
        top = min(m.geometry[1] for m in self.monitors)
        right = max(m.geometry[0] + m.geometry[2] for m in self.monitors)
        bottom = max(m.geometry[1] + m.geometry[3] for m in self.monitors)
        avail = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        scale = min(avail.width() / max(1, right - left), avail.height() / max(1, bottom - top))
        ox = avail.left() + (avail.width() - (right - left) * scale) / 2
        oy = avail.top() + (avail.height() - (bottom - top) * scale) / 2
        out = {}
        for m in self.monitors:
            x, y, w, h = m.geometry
            r = QRectF(ox + (x - left) * scale, oy + (y - top) * scale, w * scale, h * scale)
            out[m.key] = r.adjusted(GAP, GAP, -GAP, -GAP)
        return out

    def _key_at(self, pos: QPointF) -> str:
        return next((k for k, r in self.rects().items() if r.contains(pos)), "")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        key = self._key_at(event.position())
        if key:
            self.clicked.emit(key)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        key = self._key_at(event.position())
        if key != self._hover:
            self._hover = key
            mon = next((m for m in self.monitors if m.key == key), None)
            self.setToolTip(f"{mon.label}\n{mon.connector} {mon.detail}\n{self.captions.get(key, '')}".strip()
                            if mon else "")
            self.setCursor(Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hover = ""
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pal = self.palette()
        fg = pal.color(QPalette.ColorRole.WindowText)
        accent = pal.color(QPalette.ColorRole.Highlight)
        for m in self.monitors:
            r = self.rects()[m.key]
            sel, hover = m.key in self.selected, m.key == self._hover
            path = QPainterPath()
            path.addRoundedRect(r, 7, 7)
            pm = self.thumbs.get(m.key)
            p.save()
            p.setClipPath(path)
            if pm and not pm.isNull():
                scaled = pm.scaled(r.size().toSize() + QSize(2, 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(QPointF(r.center().x() - scaled.width() / 2, r.center().y() - scaled.height() / 2), scaled)
                if not sel:
                    p.fillRect(r, QColor(0, 0, 0, 70 if hover else 110))
            else:
                fill = QColor(accent) if sel else QColor(fg)
                fill.setAlphaF(0.16 if sel else 0.10 if hover else 0.06)
                p.fillPath(path, fill)
            # caption strip
            strip = QRectF(r.left(), r.bottom() - min(46, r.height() * 0.55), r.width(), min(46, r.height() * 0.55))
            grad = QLinearGradient(strip.topLeft(), strip.bottomLeft())
            grad.setColorAt(0, QColor(0, 0, 0, 0))
            grad.setColorAt(1, QColor(0, 0, 0, 170))
            p.fillRect(strip, grad)
            # KDE-style bottom-edge bar (follows rotation)
            bar = {ROTATION_LEFT: QRectF(r.left(), r.top(), EDGE, r.height()),
                   ROTATION_RIGHT: QRectF(r.right() - EDGE, r.top(), EDGE, r.height()),
                   ROTATION_INVERTED: QRectF(r.left(), r.top(), r.width(), EDGE)}.get(
                m.rotation, QRectF(r.left(), r.bottom() - EDGE, r.width(), EDGE))
            edge = QColor(accent) if sel else QColor(255, 255, 255)
            edge.setAlphaF(0.95 if sel else 0.22)
            p.fillRect(bar, edge)
            p.restore()

            border = QColor(accent) if sel else QColor(fg)
            if not sel:
                border.setAlphaF(0.35 if hover else 0.18)
            p.setPen(QPen(border, 2.5 if sel else 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            # name
            inner = r.adjusted(EDGE + 4, 4, -(EDGE + 4), -(EDGE + 4))
            f = QFont(self.font())
            f.setWeight(QFont.Weight.DemiBold)
            fm = QFontMetricsF(f)
            while f.pointSizeF() > 6.5 and fm.horizontalAdvance(m.short) > inner.width():
                f.setPointSizeF(f.pointSizeF() - 0.5)
                fm = QFontMetricsF(f)
            p.setFont(f)
            p.setPen(QColor("#ffffff") if (pm or sel) else fg)
            p.drawText(inner, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom), m.short)
            if sel:  # check badge
                c = QPointF(r.right() - 13 - (EDGE if m.rotation == ROTATION_RIGHT else 0), r.top() + 13)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent)
                p.drawEllipse(c, 8, 8)
                pen = QPen(QColor("#ffffff"), 2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawPolyline([c + QPointF(-3.5, 0), c + QPointF(-1, 2.5), c + QPointF(3.5, -2.5)])
        if not self.monitors:
            p.setPen(fg)
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No screens found")
        p.end()


class ScreenPicker(QWidget):
    """Name tabs + layout view. `changed` fires with the set of selected monitor keys."""

    changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        tabs_widget = QWidget()
        self._tabs = QHBoxLayout(tabs_widget)
        self._tabs.setContentsMargins(0, 0, 0, 0)
        self._tabs.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidget(tabs_widget)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(74)
        outer.addWidget(scroll)
        self.view = ArrangementView()
        outer.addWidget(self.view, 1)
        self.hint = label("Click a screen to pick it  ·  Ctrl+click to pick several", "Subtitle")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.hint)
        self._buttons: Dict[str, QToolButton] = {}
        self.view.clicked.connect(self._click)

    @property
    def monitors(self) -> List[Monitor]:
        return self.view.monitors

    def selected(self) -> Set[str]:
        return set(self.view.selected)

    def set_monitors(self, monitors: List[Monitor], selected: Set[str]) -> None:
        for b in self._buttons.values():
            b.deleteLater()
        self._buttons.clear()
        while self._tabs.count():
            item = self._tabs.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._tabs.addStretch(1)
        icon = QIcon.fromTheme("video-display", QIcon.fromTheme("computer"))
        for m in sorted(monitors, key=lambda m: (m.geometry[0], m.geometry[1])):
            b = QToolButton()
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setIcon(icon)
            b.setIconSize(QSize(18, 18))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setText(tab_text(m.label) + ("  ★" if m.primary else ""))
            b.setToolTip(f"{m.connector} {m.detail}")
            b.clicked.connect(lambda _=False, k=m.key: self._click(k))
            self._buttons[m.key] = b
            self._tabs.addWidget(b)
        all_btn = QToolButton()
        all_btn.setObjectName("Tab")
        all_btn.setIcon(QIcon.fromTheme("view-fullscreen", QIcon.fromTheme("computer")))
        all_btn.setIconSize(QSize(18, 18))
        all_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        all_btn.setText("All screens")
        all_btn.clicked.connect(self.select_all)
        self._tabs.addWidget(all_btn)
        self._tabs.addStretch(1)
        self.view.monitors = monitors
        keys = {m.key for m in monitors}
        sel = selected & keys or {next((m.key for m in monitors if m.primary), monitors[0].key if monitors else "")}
        self._set(sel - {""}, emit=False)

    def set_thumb(self, key: str, pixmap: QPixmap, caption: str = "") -> None:
        self.view.thumbs[key] = pixmap
        self.view.captions[key] = caption
        self.view.update()

    def select_all(self) -> None:
        self._set({m.key for m in self.monitors})

    def _click(self, key: str) -> None:
        sel = set(self.view.selected)
        if _ctrl():
            sel ^= {key}
            if not sel:
                sel = {key}
        else:
            sel = {key}
        self._set(sel)

    def _set(self, sel: Set[str], emit: bool = True) -> None:
        self.view.selected = sel
        for k, b in self._buttons.items():
            b.setChecked(k in sel)
        self.view.update()
        if emit:
            self.changed.emit(set(sel))
