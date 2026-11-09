"""Executable style and component catalog for native PySide6 Widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .components import (
    ActionStrip, Disclosure, IssueList, NoticeBanner, ResponsiveGrid, SectionCard,
    SettingField, StatusChip, stacked_label,
)
from .tokens import COLORS, CONTRAST_PAIRS, RADIUS, SPACE, contrast_ratio


class ComponentGallery(QScrollArea):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(SPACE.gutter, SPACE.gutter, SPACE.gutter, SPACE.gutter)
        root.setSpacing(SPACE.md)
        title = QLabel("Qt Widgets — Component Library")
        title.setProperty("role", "heading")
        root.addWidget(title)
        hint = QLabel("Prototype-only, source-owned components. Changes here do not affect production StableNew or Figma.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        card = SectionCard("Theme tokens", "Blue theme with rounded geometry. Ratios are computed from the token values (WCAG 2.x).")
        swatches = ResponsiveGrid(min_column_width=150)
        for name in ("background", "surface", "field", "selected", "border", "strong_border", "accent", "danger", "success"):
            value = getattr(COLORS, name)
            tile = QLabel(f"{name}\n{value}")
            tile.setMinimumHeight(54)
            on = COLORS.on_accent if contrast_ratio(COLORS.on_accent, value) > contrast_ratio(COLORS.text, value) else COLORS.text
            tile.setStyleSheet(
                f"background: {value}; color: {on}; border: 1px solid {COLORS.strong_border}; "
                f"border-radius: {RADIUS.control}px; padding: 6px 10px;"
            )
            swatches.add(tile)
        card.add(swatches)
        ratios = QLabel(
            "\n".join(
                f"{label}: {contrast_ratio(fg, bg):.1f}:1 (needs {need:g}:1) {'PASS' if contrast_ratio(fg, bg) >= need else 'FAIL'}"
                for label, fg, bg, need in CONTRAST_PAIRS
            )
        )
        ratios.setProperty("role", "muted")
        ratios.setWordWrap(True)
        card.add(ratios)
        radii = QLabel(f"Radii (px): control {RADIUS.control} · button {RADIUS.button} · card {RADIUS.card} · chip {RADIUS.chip}")
        radii.setProperty("role", "muted")
        card.add(radii)
        root.addWidget(card)

        card = SectionCard("Cards and labeled inputs", "Reusable `SectionCard` and `stacked_label` primitives.")
        text = QLineEdit("Example value")
        card.add(stacked_label("Example label", text, help_text="Visible guidance survives when tooltips are unavailable."))
        combo = QComboBox()
        combo.addItems(["Model default (fixture)", "Learning-informed (fixture)"])
        card.add(stacked_label("Example choice", combo))
        card.add(stacked_label("Example multi-line text", QPlainTextEdit("Rounded, focus-ringed editor")))
        root.addWidget(card)

        card = SectionCard("Setting field and responsive grid", "Lock, reset-to-recommended and a visible recommendation; columns reflow with width and never clip.")
        grid = ResponsiveGrid(min_column_width=190)
        steps = QSpinBox()
        steps.setRange(1, 150)
        steps.setValue(40)
        field = SettingField("steps", "Steps", steps)
        field.set_state(locked=False, differs=True, recommended="28")
        field.resetRequested.connect(lambda: (steps.setValue(28), field.set_state(locked=field.lock.isChecked(), differs=False, recommended="28")))
        grid.add(field)
        cfg = QDoubleSpinBox()
        cfg.setValue(7.0)
        other = SettingField("cfg", "CFG", cfg)
        other.set_state(locked=True, differs=False, recommended="7")
        grid.add(other)
        grid.add(SettingField("sampler", "Disabled example", _disabled_combo()))
        card.add(grid)
        root.addWidget(card)

        card = SectionCard("Notifications and status", "Every status includes words, not color alone.")
        for heading, message, level in (
            ("INFO", "Fixture settings are illustrative, not qualified.", "info"),
            ("WARNING", "A displayed summary could be stale after editing.", "warning"),
            ("BLOCKED", "An incompatible mock condition cannot proceed to simulation.", "blocked"),
            ("OK", "The mock preview is current and ready.", "success"),
        ):
            notice = NoticeBanner()
            notice.set_message(heading, message, level)
            card.add(notice)
        chips = QWidget()
        row = QHBoxLayout(chips)
        row.setContentsMargins(0, 0, 0, 0)
        for text_, level in (("NOT BUILT", "info"), ("STALE", "warning"), ("BLOCKED", "blocked"), ("CURRENT · READY", "success")):
            row.addWidget(StatusChip(text_, level))
        row.addStretch(1)
        card.add(chips)
        issues = IssueList()
        issues.set_issues(("Prompt is empty.",), ("Size is outside the fixture's characterization.",))
        card.add(issues)
        root.addWidget(card)

        card = SectionCard("Progressive disclosure", "The collapsed heading must identify what remains available.")
        disclosure = Disclosure("More details", "Example of optional controls, with keyboard-accessible expansion.")
        disclosure.add(QCheckBox("Enable optional mock stage"))
        disclosure.add(stacked_label("Additional notes", QPlainTextEdit()))
        card.add(disclosure)
        root.addWidget(card)

        card = SectionCard("Action hierarchy", "A fixed action strip keeps essential actions reachable.")
        actions = ActionStrip()
        secondary = actions.add_action("Review")
        primary = actions.add_action("Primary action", primary=True)
        primary.setEnabled(False)
        secondary.clicked.connect(lambda: (actions.status.setText("Review clicked (gallery demo only)"), primary.setEnabled(True)))
        card.add(actions)
        root.addWidget(card)
        root.addStretch(1)
        self.setWidget(body)


def _disabled_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("Not available")
    combo.setEnabled(False)
    return combo
