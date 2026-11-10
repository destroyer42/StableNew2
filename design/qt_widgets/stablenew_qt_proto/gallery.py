"""Executable component catalog plus the Theme Studio for native PySide6 Widgets."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .components import (
    ActionStrip,
    Disclosure,
    FormTextEdit,
    IssueList,
    NoticeBanner,
    ResponsiveGrid,
    ResultGallery,
    SectionCard,
    SettingField,
    StatusChip,
    fit_segment,
    stacked_label,
)
from .domain import ResultTile
from .theme import Theme, contrast_checks
from .theme_store import ThemeLibrary
from .theme_studio import ThemeStudio
from .tokens import COLORS, RADIUS, SPACE, active_theme, contrast_ratio

PAGE_COMPONENTS = "components"
PAGE_STUDIO = "studio"


class ComponentsPage(QScrollArea):
    """Static catalog of every reusable component, rebuilt whenever the applied theme changes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rebuild()

    def rebuild(self) -> None:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(SPACE.gutter, SPACE.gutter, SPACE.gutter, SPACE.gutter)
        root.setSpacing(SPACE.md)
        theme = active_theme()
        hint = QLabel(
            f"Active theme: {theme.name} ({theme.kind}, fingerprint {theme.fingerprint()[:10]}). "
            "Prototype-only, source-owned components. Changes here do not affect production StableNew or Figma."
        )
        hint.setProperty("role", "muted")
        hint.setTextFormat(Qt.TextFormat.PlainText)  # the theme name may come from an imported file
        hint.setWordWrap(True)
        root.addWidget(hint)

        card = SectionCard(
            "Theme tokens",
            "Values come from the active JSON theme. Ratios are computed (WCAG 2.x).",
        )
        swatches = ResponsiveGrid(min_column_width=150)
        for name in (
            "background",
            "surface",
            "field",
            "selected",
            "border",
            "strong_border",
            "accent",
            "danger",
            "success",
            "danger_fill",
        ):
            value = getattr(COLORS, name)
            tile = QLabel(f"{name}\n{value}")
            tile.setMinimumHeight(54)
            on = (
                COLORS.on_accent
                if contrast_ratio(COLORS.on_accent, value) > contrast_ratio(COLORS.text, value)
                else COLORS.text
            )
            tile.setStyleSheet(
                f"background: {value}; color: {on}; border: 1px solid {COLORS.strong_border}; "
                f"border-radius: {RADIUS.control}px; padding: 6px 10px;"
            )
            swatches.add(tile)
        card.add(swatches)
        checks = contrast_checks(theme)
        ratios = QLabel(
            "\n".join(
                f"{c.label}: {c.ratio:.1f}:1 (needs {c.minimum:g}:1) {'PASS' if c.passed else 'FAIL'}"
                for c in checks
            )
        )
        ratios.setProperty("role", "muted")
        ratios.setWordWrap(True)
        card.add(ratios)
        radii = QLabel(
            f"Radii (px): control {RADIUS.control} · button {RADIUS.button} · card {RADIUS.card} · chip {RADIUS.chip}"
        )
        radii.setProperty("role", "muted")
        card.add(radii)
        root.addWidget(card)

        card = SectionCard(
            "Cards and labeled inputs", "Reusable `SectionCard` and `stacked_label` primitives."
        )
        text = QLineEdit("Example value")
        card.add(
            stacked_label(
                "Example label",
                text,
                help_text="Visible guidance survives when tooltips are unavailable.",
            )
        )
        combo = QComboBox()
        combo.addItems(["Model default (fixture)", "Learning-informed (fixture)"])
        card.add(stacked_label("Example choice", combo))
        card.add(
            stacked_label("Example multi-line text", FormTextEdit("Rounded, focus-ringed editor"))
        )
        root.addWidget(card)

        card = SectionCard(
            "Setting field and responsive grid",
            "Lock, reset-to-recommended, a visible recommendation and its origin; columns reflow with width and never clip.",
        )
        grid = ResponsiveGrid(min_column_width=190)
        steps = QSpinBox()
        steps.setRange(1, 150)
        steps.setValue(40)
        field = SettingField("steps", "Steps", steps)
        field.set_state(locked=False, differs=True, recommended="28", origin="manual")
        field.resetRequested.connect(
            lambda: (
                steps.setValue(28),
                field.set_state(locked=field.lock.isChecked(), differs=False, recommended="28"),
            )
        )
        grid.add(field)
        cfg = QDoubleSpinBox()
        cfg.setValue(7.0)
        other = SettingField("cfg", "CFG", cfg)
        other.set_state(locked=True, differs=False, recommended="7", origin="locked")
        grid.add(other)
        grid.add(SettingField("sampler", "Disabled example", _disabled_combo()))
        card.add(grid)
        root.addWidget(card)

        card = SectionCard(
            "Notifications and status", "Every status includes words, not color alone."
        )
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
        for text_, level in (
            ("NOT BUILT", "info"),
            ("STALE", "warning"),
            ("BLOCKED", "blocked"),
            ("CURRENT · READY", "success"),
        ):
            row.addWidget(StatusChip(text_, level))
        row.addStretch(1)
        card.add(chips)
        issues = IssueList()
        issues.set_issues(
            ("Prompt is empty.",), ("Size is outside the fixture's characterization.",)
        )
        card.add(issues)
        root.addWidget(card)

        card = SectionCard(
            "Progressive disclosure", "The collapsed heading must identify what remains available."
        )
        disclosure = Disclosure(
            "More details · 1 optional stage enabled",
            "Example of optional controls, with keyboard-accessible expansion.",
        )
        disclosure.add(QCheckBox("Enable optional mock stage"))
        disclosure.add(stacked_label("Additional notes", FormTextEdit()))
        card.add(disclosure)
        root.addWidget(card)

        card = SectionCard(
            "Action hierarchy",
            "A fixed action strip keeps essential actions reachable; one primary per region; danger only for destructive actions.",
        )
        actions = ActionStrip()
        secondary = actions.add_action("Review")
        destructive = actions.add_action("Delete saved")
        destructive.setProperty("role", "danger")
        primary = actions.add_action("Primary action", primary=True)
        primary.setEnabled(False)
        secondary.clicked.connect(
            lambda: (
                actions.status.setText("Review clicked (gallery demo only)"),
                primary.setEnabled(True),
            )
        )
        card.add(actions)
        root.addWidget(card)

        card = SectionCard(
            "Mock result gallery",
            "Placeholder tiles from a simulated admission; they are labels, never generated images.",
        )
        gallery = ResultGallery()
        gallery.set_tiles(
            tuple(
                ResultTile(i, f"MOCK IMAGE {i} OF 3", "1024 × 1024", str(1000 + i))
                for i in (1, 2, 3)
            )
        )
        card.add(gallery)
        root.addWidget(card)
        root.addStretch(1)
        self.setWidget(body)


class ComponentGallery(QWidget):
    """Component catalog and Theme Studio behind one header toggle."""

    def __init__(
        self,
        library: ThemeLibrary | None = None,
        theme: Theme | None = None,
        apply_callback: Callable[[Theme], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.library = library or ThemeLibrary()
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.gutter, SPACE.gutter, SPACE.gutter, 0)
        root.setSpacing(SPACE.sm)
        head = QHBoxLayout()
        title = QLabel("Qt Widgets — Component Library")
        title.setProperty("role", "heading")
        head.addWidget(title)
        head.addStretch(1)
        self.group = QButtonGroup(self)
        self.page_buttons: dict[str, QPushButton] = {}
        for key, label in ((PAGE_COMPONENTS, "Components"), (PAGE_STUDIO, "Theme Studio")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("role", "segment")
            fit_segment(button)
            button.setAccessibleName(f"Library page: {label}")
            self.group.addButton(button)
            self.page_buttons[key] = button
            head.addWidget(button)
            button.clicked.connect(lambda _c=False, k=key: self.show_page(k))
        root.addLayout(head)
        self.stack = QStackedWidget()
        self.components_page = ComponentsPage()
        self.studio = ThemeStudio(self.library, theme or active_theme(), apply_callback)
        self.stack.addWidget(self.components_page)
        self.stack.addWidget(self.studio)
        root.addWidget(self.stack, 1)
        self.show_page(PAGE_COMPONENTS)

    def show_page(self, key: str) -> None:
        self.page_buttons[key].setChecked(True)
        self.stack.setCurrentIndex(0 if key == PAGE_COMPONENTS else 1)

    def rebuild_components(self) -> None:
        """Re-create the catalog after the applied theme changed (spacing is read at build time)."""
        self.components_page.rebuild()


def _disabled_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("Not available")
    combo.setEnabled(False)
    return combo
