# SPDX-License-Identifier: GPL-3.0-or-later
"""Adwaita-like look for Qt: libadwaita colours, rounded cards, slim sliders.

Follows the system light/dark preference (Qt 6.5+ colour scheme hint).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication

from .. import paths


@dataclass(frozen=True)
class Theme:
    dark: bool
    window: str
    sidebar: str
    view: str
    card: str
    fg: str
    dim: str
    border: str
    separator: str
    accent: str       # accent background (buttons, slider fill, selection)
    accent_fg: str    # accent used as text colour
    button: str
    button_hover: str
    button_active: str
    trough: str
    destructive: str
    destructive_fg: str
    success: str
    warning: str
    toast: str


DARK = Theme(
    dark=True, window="#222226", sidebar="#2e2e32", view="#1d1d20", card="#303034", fg="#ffffff", dim="#9a9a9d",
    border="#3c3c41", separator="#3a3a3e", accent="#3584e4", accent_fg="#78aeed",
    button="rgba(255,255,255,0.10)", button_hover="rgba(255,255,255,0.15)", button_active="rgba(255,255,255,0.28)",
    trough="rgba(255,255,255,0.20)", destructive="#c01c28", destructive_fg="#ff7b63",
    success="#26a269", warning="#cd9309", toast="#4a4a50",
)
LIGHT = Theme(
    dark=False, window="#fafafb", sidebar="#ebebed", view="#ffffff", card="#ffffff", fg="#2e2e32", dim="#77777c",
    border="#dcdce0", separator="#e6e6ea", accent="#3584e4", accent_fg="#1c71d8",
    button="rgba(0,0,6,0.08)", button_hover="rgba(0,0,6,0.12)", button_active="rgba(0,0,6,0.24)",
    trough="rgba(0,0,6,0.15)", destructive="#e01b24", destructive_fg="#c01c28",
    success="#2ec27e", warning="#e5a50a", toast="#323236",
)


def current_theme() -> Theme:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", lambda: Qt.ColorScheme.Unknown)()
    if scheme == Qt.ColorScheme.Dark:
        return DARK
    if scheme == Qt.ColorScheme.Light:
        return LIGHT
    return DARK if QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128 else LIGHT


def _arrow_icon(t: Theme) -> str:
    """Draw a small chevron PNG once (QSS needs a file for the combo box arrow)."""
    path = paths.cache_dir() / f"chevron-{'dark' if t.dark else 'light'}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        img = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(t.fg), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(4, 7.5), QPointF(10, 13.5), QPointF(16, 7.5)])
        p.end()
        img.save(str(path))
    return path.as_posix()


def stylesheet(t: Theme) -> str:
    arrow = _arrow_icon(t)
    return f"""
    QWidget {{ color: {t.fg}; font-size: 10pt; }}
    QMainWindow, QDialog, QWidget#Root {{ background: {t.window}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QToolTip {{ background: {t.toast}; color: #ffffff; border: none; padding: 5px 8px; border-radius: 6px; }}

    QLabel#Dim, QLabel#Subtitle {{ color: {t.dim}; }}
    QLabel#Subtitle {{ font-size: 9pt; }}
    QLabel#GroupTitle {{ font-weight: 700; font-size: 10pt; }}
    QLabel#Heading {{ font-weight: 800; font-size: 13pt; }}
    QLabel#Pill {{ background: {t.button}; border-radius: 10px; padding: 2px 10px; font-size: 9pt; font-weight: 600; }}
    QLabel#PillLive {{ background: rgba(38,162,105,0.22); color: {t.success if not t.dark else '#8ff0a4'};
                      border-radius: 10px; padding: 2px 10px; font-size: 9pt; font-weight: 700; }}
    QLabel#PillWarn {{ background: rgba(229,165,10,0.22); border-radius: 10px; padding: 2px 10px;
                      font-size: 9pt; font-weight: 700; }}
    QLabel#Toast {{ background: {t.toast}; color: #ffffff; border-radius: 18px; padding: 9px 18px; }}

    QFrame#Sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 0px; color: {t.fg}; }}
    QListWidget::item:hover {{ background: {t.button}; }}
    QListWidget::item:selected {{ background: {t.button_active}; color: {t.fg}; }}
    QListWidget#Nav::item {{ padding: 10px 10px; font-weight: 600; }}
    QFrame#Card {{ background: {t.card}; border: 1px solid {t.border}; border-radius: 12px; }}
    QFrame#Separator {{ background: {t.separator}; border: none; max-height: 1px; min-height: 1px; }}
    QFrame#Banner {{ background: rgba(53,132,228,0.20); border-radius: 12px; }}
    QFrame#View {{ background: {t.view}; border: 1px solid {t.border}; border-radius: 12px; }}

    QPushButton, QToolButton {{
        background: {t.button}; border: none; border-radius: 6px; padding: 7px 14px; font-weight: 600;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {t.button_hover}; }}
    QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{ background: {t.button_active}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t.dim}; background: {t.button}; }}
    QPushButton#Suggested {{ background: {t.accent}; color: #ffffff; }}
    QPushButton#Suggested:hover {{ background: #4a90e8; }}
    QPushButton#Suggested:pressed {{ background: #2a6fc4; }}
    QPushButton#Destructive {{ color: {t.destructive_fg}; }}
    QPushButton#Flat, QToolButton#Flat {{ background: transparent; }}
    QPushButton#Flat:hover, QToolButton#Flat:hover {{ background: {t.button_hover}; }}
    QToolButton#Reset {{ background: transparent; padding: 4px; border-radius: 13px; }}
    QToolButton#Reset:hover {{ background: {t.button_hover}; }}
    QToolButton#Segment {{ border-radius: 0px; padding: 5px 12px; background: transparent; }}
    QToolButton#Segment:checked {{ background: {t.button_active}; }}
    QToolButton#Segment[pos="first"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
    QToolButton#Segment[pos="last"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
    QWidget#Segmented {{ background: {t.button}; border-radius: 6px; }}
    QToolButton#Tab {{ background: transparent; border-radius: 8px; padding: 6px 12px; font-weight: 600; }}
    QToolButton#Tab:hover {{ background: {t.button}; }}
    QToolButton#Tab:checked {{ background: {t.button_active}; }}

    QComboBox {{
        background: {t.button}; border: none; border-radius: 6px; padding: 6px 12px; font-weight: 600; min-width: 9em;
    }}
    QComboBox:hover {{ background: {t.button_hover}; }}
    QComboBox::drop-down {{ border: none; background: transparent; width: 26px; }}
    QComboBox::down-arrow {{ image: url({arrow}); width: 10px; height: 10px; }}
    QToolButton::menu-indicator {{ image: none; width: 0px; }}
    QComboBox QAbstractItemView {{
        background: {t.card}; border: 1px solid {t.border}; selection-background-color: {t.accent};
        selection-color: #ffffff; outline: none; padding: 4px;
    }}

    QDoubleSpinBox, QLineEdit {{
        background: {t.button}; border: 2px solid transparent; border-radius: 6px; padding: 3px 6px;
        selection-background-color: {t.accent}; selection-color: #ffffff;
    }}
    QDoubleSpinBox:focus, QLineEdit:focus {{ border: 2px solid {t.accent}; }}

    QSlider {{ min-height: 26px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.trough}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ height: 4px; background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: #ffffff; border: 1px solid rgba(0,0,0,0.25); width: 18px; height: 18px;
        margin: -8px 0; border-radius: 10px;
    }}
    QSlider::handle:horizontal:hover {{ border: 1px solid {t.accent}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {t.trough}; }}
    QSlider::handle:horizontal:disabled {{ background: {t.button_active}; border: none; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.button_active}; border-radius: 3px; min-height: 30px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.button_active}; border-radius: 3px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; width: 0; }}

    QMenu {{ background: {t.card}; border: 1px solid {t.border}; padding: 6px; }}
    QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {t.button_hover}; }}
    QMenu::separator {{ height: 1px; background: {t.separator}; margin: 5px 4px; }}
    QPlainTextEdit {{ background: {t.view}; border: 1px solid {t.border}; border-radius: 8px; padding: 6px; }}
    """


def palette(t: Theme) -> QPalette:
    pal = QPalette()
    fg, window, card, view = QColor(t.fg), QColor(t.window), QColor(t.card), QColor(t.view)
    for role, color in (
        (QPalette.ColorRole.Window, window), (QPalette.ColorRole.WindowText, fg),
        (QPalette.ColorRole.Base, view), (QPalette.ColorRole.AlternateBase, card),
        (QPalette.ColorRole.Text, fg), (QPalette.ColorRole.Button, card),
        (QPalette.ColorRole.ButtonText, fg), (QPalette.ColorRole.ToolTipBase, QColor(t.toast)),
        (QPalette.ColorRole.ToolTipText, QColor("#ffffff")), (QPalette.ColorRole.Highlight, QColor(t.accent)),
        (QPalette.ColorRole.HighlightedText, QColor("#ffffff")), (QPalette.ColorRole.Link, QColor(t.accent_fg)),
        (QPalette.ColorRole.PlaceholderText, QColor(t.dim)),
    ):
        pal.setColor(role, color)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.dim))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t.dim))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.dim))
    return pal


def apply(app: QApplication) -> Theme:
    theme = current_theme()
    app.setStyle("Fusion")
    app.setPalette(palette(theme))
    app.setStyleSheet(stylesheet(theme))
    return theme
