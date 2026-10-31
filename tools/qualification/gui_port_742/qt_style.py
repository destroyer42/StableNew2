"""Proof-only Qt style adapter: renders the shared design values as a Qt stylesheet.

Pure text. It imports no toolkit and defines no color, size or font of its own: every value comes from
``src/gui_v2/design_values.py`` and the semantic ``TOKENS``. It exists only inside qualification tooling and must not
be promoted to production or grow its own palette.
"""

from __future__ import annotations

from src.gui.ui_tokens import NOTICE_KINDS, TOKENS
from src.gui_v2.design_values import Colors, Spacing, Typography


def build_stylesheet() -> str:
    c, t, s = TOKENS.colors, TOKENS.typography, Spacing
    rules = [
        f"QWidget {{ background: {c.surface_primary}; color: {c.text_primary};"
        f" font-family: '{t.family}'; font-size: {t.size_sm}pt; }}",
        f"QLabel[muted='true'] {{ color: {c.text_muted}; }}",
        f"QLabel[heading='true'] {{ color: {c.accent_primary}; font-size: {t.size_lg}pt; font-weight: bold; }}",
        f"QLineEdit, QComboBox, QPlainTextEdit, QTableView, QTreeWidget {{ background: {c.surface_secondary};"
        f" border: 1px solid {c.border_subtle}; padding: {s.XS}px; selection-background-color: {c.surface_selected};"
        f" selection-color: {c.text_primary}; }}",
        f"QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTableView:focus, QTreeWidget:focus"
        f" {{ border: 2px solid {c.focus_ring}; }}",
        f"QLineEdit:disabled, QComboBox:disabled {{ color: {c.text_disabled}; }}",
        f"QPushButton {{ background: {c.border_subtle}; color: {c.text_primary}; border: 1px solid {c.border_subtle};"
        f" padding: {s.SM}px {s.MD}px; }}",
        f"QPushButton:hover {{ background: {Colors.SECONDARY_HOVER}; }}",
        f"QPushButton:focus {{ border: 2px solid {c.focus_ring}; }}",
        f"QPushButton[primary='true'] {{ background: {c.accent_primary}; color: {c.text_on_accent};"
        f" border: 1px solid {c.accent_primary}; }}",
        f"QPushButton[primary='true']:hover {{ background: {c.accent_primary_hover}; }}",
        f"QPushButton[primary='true']:focus {{ border: 2px solid {c.focus_ring_on_accent}; }}",
        f"QHeaderView::section {{ background: {c.surface_primary}; color: {c.text_primary};"
        f" border: 1px solid {c.border_subtle}; padding: {s.SM}px; font-weight: bold; }}",
        f"QTableView::item:hover, QTreeWidget::item:hover {{ background: {c.surface_hover}; }}",
        f"QTableView::item:selected, QTreeWidget::item:selected {{ background: {c.surface_selected};"
        f" color: {c.text_primary}; border-left: 3px solid {c.accent_primary}; }}",
        f"QToolTip {{ background: {c.surface_secondary}; color: {c.text_primary}; border: 1px solid {c.border_subtle}; }}",
    ]
    for kind in NOTICE_KINDS:
        role = TOKENS.notices.role(kind)
        rules.append(
            f"QLabel[noticeKind='{kind}'] {{ background: {role.background}; color: {role.foreground};"
            f" border-left: 4px solid {role.accent}; padding: {s.SM}px {s.MD}px; }}"
        )
    return "\n".join(rules)


def font_point_size() -> int:
    return Typography.SM


__all__ = ["build_stylesheet", "font_point_size"]
