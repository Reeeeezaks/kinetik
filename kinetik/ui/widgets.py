# SPDX-License-Identifier: GPL-3.0-or-later
"""Small Adwaita-style building blocks."""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QButtonGroup, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSlider, QStyle, QStyleOptionSlider, QToolButton, QVBoxLayout, QWidget,
)

SLIDER_STEPS = 1000


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


class Card(QFrame):
    """Rounded 'boxed list': rows separated by thin lines."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._rows: List[QWidget] = []

    def add_row(self, row: QWidget) -> QWidget:
        if self._rows:
            sep = QFrame()
            sep.setObjectName("Separator")
            row.setProperty("separator", sep)
            self._layout.addWidget(sep)
        self._rows.append(row)
        self._layout.addWidget(row)
        return row

    def set_row_visible(self, row: QWidget, visible: bool) -> None:
        row.setVisible(visible)
        sep = row.property("separator")
        if sep is not None:
            sep.setVisible(visible)


class Group(QWidget):
    """Preferences group: bold title (+ optional widget on the right) above a Card."""

    def __init__(self, title: str, description: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 0, 0)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label(title, "GroupTitle"))
        if description:
            titles.addWidget(label(description, "Subtitle", wrap=True))
        head.addLayout(titles, 1)
        self.header = head
        outer.addLayout(head)
        self.card = Card()
        outer.addWidget(self.card)

    def add_row(self, row: QWidget) -> QWidget:
        return self.card.add_row(row)

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget, 0, Qt.AlignmentFlag.AlignBottom)


class Mapping:
    """Display value <-> slider position, linear or logarithmic (neutral value mid-track)."""

    def __init__(self, minimum: float, maximum: float, log: bool = False) -> None:
        self.minimum, self.maximum, self.log = minimum, maximum, log

    def to_pos(self, value: float) -> int:
        value = min(max(value, self.minimum), self.maximum)
        if self.log:
            frac = math.log(value / self.minimum) / math.log(self.maximum / self.minimum)
        else:
            frac = (value - self.minimum) / (self.maximum - self.minimum)
        return round(frac * SLIDER_STEPS)

    def from_pos(self, pos: int) -> float:
        frac = pos / SLIDER_STEPS
        if self.log:
            return self.minimum * (self.maximum / self.minimum) ** frac
        return self.minimum + frac * (self.maximum - self.minimum)


class MarkedSlider(QSlider):
    """Slider with a small tick under the default value (like an Adwaita scale mark).

    Arrow keys don't move the (non-linear) slider position; they emit `nudged` so the row
    can step the *value* by exactly one unit.
    """

    nudged = Signal(int)
    KEYS = {Qt.Key.Key_Left: -1, Qt.Key.Key_Down: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: 1,
            Qt.Key.Key_PageDown: -10, Qt.Key.Key_PageUp: 10}

    def keyPressEvent(self, event) -> None:  # noqa: N802
        step = self.KEYS.get(event.key())
        if step is None:
            super().keyPressEvent(event)
        else:
            self.nudged.emit(step)
            event.accept()

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.mark: Optional[int] = None
        self.setRange(0, SLIDER_STEPS)
        self.setPageStep(SLIDER_STEPS // 20)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.mark is not None:
            p = QPainter(self)
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                                 QStyle.SubControl.SC_SliderHandle, self)
            span = self.width() - handle.width()
            x = handle.width() / 2 + span * (self.mark - self.minimum()) / max(1, self.maximum() - self.minimum())
            color = self.palette().color(QPalette.ColorRole.WindowText)
            color.setAlphaF(0.35)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x - 1, self.height() / 2 + 6, 2, 5), 1, 1)
            p.end()
        super().paintEvent(event)


class SliderRow(QWidget):
    """Title/subtitle, slider, value box and a reset button. Works in display units."""

    changed = Signal(float)

    def __init__(self, title: str, subtitle: str, minimum: float, maximum: float, default: float,
                 decimals: int = 0, suffix: str = "", log: bool = False, step: float = 1.0,
                 snap: float = 0.0, snap_radius: float = 0.0) -> None:
        super().__init__()
        self.default = default
        self.snap, self.snap_radius = snap, snap_radius
        self.mapping = Mapping(minimum, maximum, log)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 10, 8)
        row.setSpacing(12)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        self.title = label(title)
        self.subtitle = label(subtitle, "Subtitle", wrap=True)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        box = QWidget()
        box.setLayout(titles)
        box.setFixedWidth(205)
        row.addWidget(box)

        self.slider = MarkedSlider()
        self.slider.setAccessibleName(title)
        row.addWidget(self.slider, 1)

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(84)
        self.spin.setAccessibleName(f"{title} value")
        row.addWidget(self.spin)

        self.reset = QToolButton()
        self.reset.setObjectName("Reset")
        self.reset.setToolTip(f"Reset {title.lower()}")
        self.reset.setAutoRaise(True)
        self.reset.setText("↺")
        policy = self.reset.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.reset.setSizePolicy(policy)
        row.addWidget(self.reset)

        self.set_range(minimum, maximum)
        self.slider.valueChanged.connect(self._from_slider)
        self.slider.nudged.connect(self._nudge)
        self.spin.valueChanged.connect(self._from_spin)
        self.reset.clicked.connect(lambda: self._emit(self.default))
        self.set_value(default)

    def set_range(self, minimum: float, maximum: float) -> None:
        value = self.value()
        self.mapping = Mapping(minimum, maximum, self.mapping.log)
        self.spin.blockSignals(True)
        self.spin.setRange(minimum, maximum)
        self.spin.blockSignals(False)
        self.slider.mark = self.mapping.to_pos(self.default)
        self.set_value(min(max(value, minimum), maximum))

    def value(self) -> float:
        return self.spin.value()

    def set_value(self, value: float) -> None:
        """Update without emitting `changed`."""
        for w in (self.slider, self.spin):
            w.blockSignals(True)
        self.spin.setValue(value)
        self.slider.setValue(self.mapping.to_pos(value))
        for w in (self.slider, self.spin):
            w.blockSignals(False)
        self.reset.setVisible(abs(value - self.default) > 10 ** -(self.spin.decimals() + 1))
        self.slider.update()

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def _emit(self, value: float) -> None:
        self.set_value(value)
        self.changed.emit(self.value())

    def _from_slider(self, pos: int) -> None:
        value = self.mapping.from_pos(pos)
        step = self.spin.singleStep()
        if step >= 1:  # snap to whole steps, but let the neutral value be hit exactly
            value = round(value / step) * step
        if abs(self.mapping.to_pos(self.default) - pos) <= 2:
            value = self.default
        if self.snap:  # magnetic round numbers when dragging: 290..310 -> 300, 274 stays 274
            nearest = round(value / self.snap) * self.snap
            if abs(value - nearest) <= self.snap_radius:
                value = nearest
        self._emit(min(max(value, self.mapping.minimum), self.mapping.maximum))

    def _nudge(self, units: int) -> None:
        """Arrow keys: exactly one step per press, no snapping."""
        value = self.value() + units * self.spin.singleStep()
        self._emit(min(max(value, self.mapping.minimum), self.mapping.maximum))

    def _from_spin(self, value: float) -> None:
        self._emit(value)


class Switch(QAbstractButton):
    """Adwaita-style toggle switch."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(48, 26)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - keep the knob in sync without animation
        super().setChecked(checked)
        self._anim.stop()
        self._set_knob(1.0 if checked else 0.0)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, (self.height() - 24) / 2, 46, 24)
        off = self.palette().color(QPalette.ColorRole.WindowText)
        off.setAlphaF(0.18)
        on = self.palette().color(QPalette.ColorRole.Highlight)
        track = QColor(
            round(off.red() + (on.red() - off.red()) * self._pos),
            round(off.green() + (on.green() - off.green()) * self._pos),
            round(off.blue() + (on.blue() - off.blue()) * self._pos),
            round(255 * (off.alphaF() + (1 - off.alphaF()) * self._pos)),
        )
        if not self.isEnabled():
            track.setAlphaF(track.alphaF() * 0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 12, 12)
        knob = QRectF(r.left() + 2 + self._pos * 22, r.top() + 2, 20, 20)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(knob.adjusted(0, 1, 0, 1))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(knob)
        if self.hasFocus():
            focus = QColor(self.palette().color(QPalette.ColorRole.Highlight))
            focus.setAlphaF(0.5)
            p.setPen(focus)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 13, 13)
        p.end()


class SwitchRow(QWidget):
    toggled = Signal(bool)

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label(title))
        if subtitle:
            titles.addWidget(label(subtitle, "Subtitle", wrap=True))
        row.addLayout(titles, 1)
        self.switch = Switch()
        self.switch.setAccessibleName(title)
        row.addWidget(self.switch)
        self.switch.toggled.connect(self.toggled)

    def set_checked(self, checked: bool) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(checked)
        self.switch.blockSignals(False)


class Segmented(QWidget):
    """Linked toggle buttons, e.g. [All | R | G | B]."""

    changed = Signal(int)

    def __init__(self, labels: Sequence[str], tooltips: Sequence[str] = ()) -> None:
        super().__init__()
        self.setObjectName("Segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        for i, text in enumerate(labels):
            b = QToolButton()
            b.setObjectName("Segment")
            b.setText(text)
            b.setCheckable(True)
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(labels) - 1 else "mid")
            if i < len(tooltips):
                b.setToolTip(tooltips[i])
            self.group.addButton(b, i)
            row.addWidget(b)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.changed)

    def current(self) -> int:
        return self.group.checkedId()


class Banner(QFrame):
    """Inline banner with a message and up to two buttons."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 8, 8)
        self.text = label("", wrap=True)
        row.addWidget(self.text, 1)
        self.secondary = QPushButton()
        self.primary = QPushButton()
        self.primary.setObjectName("Suggested")
        row.addWidget(self.secondary)
        row.addWidget(self.primary)
        self.hide()


class Toast(QLabel):
    """Short message floating at the bottom of its parent."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, seconds: float = 4.0) -> None:
        self.setText(text)
        parent = self.parentWidget()
        width = min(520, parent.width() - 40)
        self.setFixedWidth(width)
        self.adjustSize()
        self.move((parent.width() - width) // 2, parent.height() - self.height() - 84)
        self.raise_()
        self.show()
        self._timer.start(int(seconds * 1000))


def flat_button(text: str, tooltip: str = "", on_click: Optional[Callable[[], None]] = None) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("Flat")
    if tooltip:
        b.setToolTip(tooltip)
    if on_click:
        b.clicked.connect(on_click)
    b.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return b
