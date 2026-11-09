"""Prototype-only semantic style tokens (blue theme, rounded geometry).

Derived from the merged UX-850-C token *roles*, re-skinned on an owner-requested
blue background with rounded corners. Isolated from the production Tk theme:
production Qt migration MUST re-evaluate token ownership and may not introduce an
independent runtime source of truth. No external Figma library or remote
resources are required; arrow/check glyphs are static SVG files in ``assets/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent / "assets"
ASSET_FILES = ("arrow_up.svg", "arrow_down.svg", "chevron_down.svg", "check.svg")


@dataclass(frozen=True)
class Palette:
    background: str = "#0E2A55"   # window / page
    surface: str = "#163F7C"      # cards, nav, footer
    field: str = "#0A2147"        # inset inputs and notices
    selected: str = "#1E5AA8"     # buttons, selected rows
    border: str = "#3E70B8"
    strong_border: str = "#8FB4E8"
    text: str = "#FFFFFF"
    muted: str = "#C6D8F2"
    disabled: str = "#9DB5D6"
    accent: str = "#FFC805"       # focus, primary action, warnings
    on_accent: str = "#0A1A33"
    danger: str = "#FF8A91"
    success: str = "#7EE0A8"


@dataclass(frozen=True)
class Metrics:
    xs: int = 4
    sm: int = 8
    md: int = 12
    gutter: int = 16
    xl: int = 24
    control_min_height: int = 32


@dataclass(frozen=True)
class Radius:
    control: int = 8   # inputs, nav items, tool buttons
    button: int = 10   # push buttons
    card: int = 14     # cards, nav panel, notices
    chip: int = 12     # status chips and capsules


COLORS = Palette()
SPACE = Metrics()
RADIUS = Radius()


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio between two ``#RRGGBB`` colors."""
    a, b = luminance(foreground), luminance(background)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# (label, foreground, background, minimum ratio) — asserted by tests and shown in the gallery.
CONTRAST_PAIRS: tuple[tuple[str, str, str, float], ...] = (
    ("Text on background", COLORS.text, COLORS.background, 4.5),
    ("Text on surface", COLORS.text, COLORS.surface, 4.5),
    ("Text on field", COLORS.text, COLORS.field, 4.5),
    ("Text on selected", COLORS.text, COLORS.selected, 4.5),
    ("Muted on surface", COLORS.muted, COLORS.surface, 4.5),
    ("Muted on selected", COLORS.muted, COLORS.selected, 4.5),
    ("Primary action label", COLORS.on_accent, COLORS.accent, 7.0),
    ("Accent on surface", COLORS.accent, COLORS.surface, 3.0),
    ("Accent on field", COLORS.accent, COLORS.field, 3.0),
    ("Strong border on surface", COLORS.strong_border, COLORS.surface, 3.0),
    ("Strong border on field", COLORS.strong_border, COLORS.field, 3.0),
    ("Danger on field", COLORS.danger, COLORS.field, 4.5),
    ("Success on field", COLORS.success, COLORS.field, 4.5),
    ("Disabled text on selected", COLORS.disabled, COLORS.selected, 3.0),
)


def asset_url(name: str, directory: Path = ASSET_DIR) -> str:
    return 'url("' + (directory / name).as_posix() + '")'


def make_stylesheet(asset_dir: Path = ASSET_DIR) -> str:
    """Returns reusable widget styles without accessing the GUI environment.

    Plain widgets are transparent so labels and containers never paint opaque
    rectangles over cards; only top-level windows, cards and inputs get fills.
    Every interactive control keeps a constant 2px border and only changes its
    colour on hover/focus, so focus never shifts layout.
    """
    c, r = COLORS, RADIUS
    up, down = asset_url("arrow_up.svg", asset_dir), asset_url("arrow_down.svg", asset_dir)
    chevron, check = asset_url("chevron_down.svg", asset_dir), asset_url("check.svg", asset_dir)
    return f"""
    QWidget {{ color: {c.text}; background: transparent; font-family: 'Segoe UI', Arial; font-size: 10pt; }}
    QMainWindow, QDialog, QMessageBox {{ background: {c.background}; }}
    QToolTip {{ color: {c.text}; background: {c.field}; border: 2px solid {c.strong_border}; border-radius: {r.control}px; padding: 4px 6px; }}

    QFrame[role='card'] {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: {r.card}px; }}
    QFrame[role='notice'] {{ background: {c.field}; border: 2px solid {c.strong_border}; border-radius: {r.card - 2}px; }}
    QFrame[role='notice'][level='warning'] {{ border-color: {c.accent}; }}
    QFrame[role='notice'][level='blocked'] {{ border-color: {c.danger}; }}
    QFrame[role='notice'][level='success'] {{ border-color: {c.success}; }}

    QLabel[role='muted'] {{ color: {c.muted}; }}
    QLabel[role='muted'][level='warning'] {{ color: {c.accent}; }}
    QLabel[role='heading'] {{ font-size: 12pt; font-weight: bold; }}
    QLabel[role='section'] {{ font-size: 11pt; font-weight: bold; }}
    QLabel[role='capsule'] {{ font-size: 9pt; font-weight: bold; color: {c.accent}; border: 1px solid {c.accent}; border-radius: {r.chip}px; padding: 3px 12px; }}
    QLabel[role='chip'] {{ font-weight: bold; background: {c.field}; border: 2px solid {c.strong_border}; border-radius: {r.chip}px; padding: 2px 12px; }}
    QLabel[role='chip'][level='warning'] {{ border-color: {c.accent}; color: {c.accent}; }}
    QLabel[role='chip'][level='blocked'] {{ border-color: {c.danger}; color: {c.danger}; }}
    QLabel[role='chip'][level='success'] {{ border-color: {c.success}; color: {c.success}; }}

    QPushButton {{ min-height: 32px; background: {c.selected}; border: 2px solid {c.strong_border}; border-radius: {r.button}px; padding: 2px 14px; }}
    QPushButton:hover {{ border-color: {c.accent}; }}
    QPushButton:pressed {{ background: {c.surface}; }}
    QPushButton:focus {{ border-color: {c.accent}; }}
    QPushButton:disabled {{ color: {c.disabled}; background: {c.surface}; border-color: {c.border}; }}
    QPushButton[role='primary'] {{ background: {c.accent}; color: {c.on_accent}; border-color: {c.accent}; font-weight: bold; }}
    QPushButton[role='primary']:hover {{ border-color: {c.text}; }}
    QPushButton[role='primary']:focus {{ border-color: {c.text}; }}
    QPushButton[role='primary']:disabled {{ color: {c.disabled}; background: {c.surface}; border-color: {c.border}; }}

    QToolButton {{ background: transparent; border: 2px solid transparent; border-radius: {r.control}px; padding: 2px 8px; }}
    QToolButton:hover, QToolButton:focus {{ border-color: {c.accent}; }}
    QToolButton:disabled {{ color: {c.disabled}; }}
    QToolButton[role='reset'] {{ font-size: 13pt; padding: 0 6px; }}
    QPushButton[role='disclosure'] {{ background: {c.field}; border-color: {c.border}; padding: 4px 12px; font-weight: bold; text-align: left; }}
    QPushButton[role='disclosure']:hover, QPushButton[role='disclosure']:focus {{ border-color: {c.accent}; }}
    QPushButton[role='disclosure']:checked {{ border-color: {c.strong_border}; }}

    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget {{
        background: {c.field}; border: 2px solid {c.border}; border-radius: {r.control}px; padding: 3px 8px;
        selection-background-color: {c.accent}; selection-color: {c.on_accent}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ min-height: 32px; }}
    QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c.strong_border}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTableWidget:focus {{ border-color: {c.accent}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c.disabled}; border-color: {c.border}; }}
    QPlainTextEdit[readOnly='true'] {{ background: {c.field}; border-color: {c.border}; }}

    QSpinBox, QDoubleSpinBox {{ padding-right: 26px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 22px; margin: 2px 2px 0 0; border: none; border-top-right-radius: {r.control - 2}px; background: {c.selected}; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; margin: 0 2px 2px 0; border: none; border-bottom-right-radius: {r.control - 2}px; background: {c.selected}; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c.border}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: {up}; width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: {down}; width: 10px; height: 10px; }}

    QComboBox {{ padding-right: 30px; }}
    QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: center right; width: 28px; border: none; }}
    QComboBox::down-arrow {{ image: {chevron}; width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {c.surface}; border: 2px solid {c.strong_border}; border-radius: {r.control}px; padding: 4px; outline: 0; selection-background-color: {c.selected}; selection-color: {c.text}; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 2px solid {c.strong_border}; border-radius: 6px; background: {c.field}; }}
    QCheckBox::indicator:hover {{ border-color: {c.accent}; }}
    QCheckBox::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; image: {check}; }}
    QCheckBox::indicator:disabled {{ border-color: {c.border}; }}
    QCheckBox:focus {{ color: {c.accent}; }}

    QTableWidget {{ gridline-color: {c.border}; padding: 2px; }}
    QTableWidget::item {{ padding: 4px; }}
    QTableWidget::item:selected {{ background: {c.selected}; color: {c.text}; }}
    QTableCornerButton::section {{ background: {c.surface}; border: none; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: {c.surface}; color: {c.text}; border: none; border-bottom: 1px solid {c.border}; padding: 6px; font-weight: bold; }}

    QListWidget[role='nav'] {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: {r.card}px; padding: 6px; outline: 0; }}
    QListWidget[role='nav']:focus {{ border-color: {c.accent}; }}
    QListWidget[role='nav']::item {{ padding: 10px 12px; margin: 2px 0; border: 2px solid transparent; border-radius: {r.control}px; }}
    QListWidget[role='nav']::item:hover {{ background: {c.selected}; }}
    QListWidget[role='nav']::item:selected {{ background: {c.selected}; color: {c.text}; border-color: {c.accent}; font-weight: bold; }}

    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c.strong_border}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:horizontal {{ background: {c.strong_border}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {c.accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QPushButton[role='segment'] {{ min-height: 28px; background: {c.field}; border-color: {c.border}; padding: 2px 10px; }}
    QPushButton[role='segment']:hover {{ border-color: {c.accent}; }}
    QPushButton[role='segment']:checked {{ background: {c.selected}; border-color: {c.accent}; font-weight: bold; }}
    QToolButton[role='zoom'] {{ background: {c.selected}; border: 2px solid {c.strong_border}; border-radius: {r.button}px; min-width: 28px; min-height: 24px; padding: 2px 8px; font-weight: bold; }}
    QToolButton[role='zoom']:hover, QToolButton[role='zoom']:focus {{ border-color: {c.accent}; }}
    QToolButton[role='zoom']:checked {{ border-color: {c.accent}; background: {c.surface}; }}
    QToolButton[glyph='true'] {{ font-size: 13pt; padding: 0 8px; }}
    QToolButton[role='zoom']:disabled {{ color: {c.disabled}; background: {c.surface}; border-color: {c.border}; }}
    QSlider::groove:horizontal {{ height: 6px; background: {c.field}; border: 1px solid {c.border}; border-radius: 4px; }}
    QSlider::sub-page:horizontal {{ background: {c.selected}; border-radius: 4px; }}
    QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; background: {c.accent}; border: 2px solid {c.on_accent}; border-radius: 9px; }}
    QSlider::handle:horizontal:hover, QSlider::handle:horizontal:focus {{ border-color: {c.text}; }}
    QFrame[role='dockbar'] {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: {r.card}px; }}
    QGraphicsView[role='viewer'] {{ background: {c.field}; border: 2px solid {c.border}; border-radius: {r.control}px; }}
    QGraphicsView[role='viewer']:focus {{ border-color: {c.accent}; }}
    QDockWidget {{ background: {c.background}; }}
    QMainWindow::separator {{ background: transparent; width: 8px; height: 8px; }}
    QMainWindow::separator:hover {{ background: {c.accent}; border-radius: 3px; }}
    QSplitter::handle {{ background: {c.border}; border-radius: 2px; margin: 4px 2px; }}
    QSplitter::handle:hover {{ background: {c.accent}; }}
    QStatusBar {{ color: {c.muted}; }}
    QStatusBar::item {{ border: none; }}
    QSizeGrip {{ background: transparent; }}
    """
