"""Theme Studio: edit, preview, diagnose, save, export and import design themes.

The Studio edits a *draft* (``ThemeEditor``). The live preview is styled by the draft alone
(a widget-scoped stylesheet), so a bad edit can never make the rest of the prototype unreadable;
"Apply to prototype" is the only action that restyles the whole window, and it is refused while a
contrast check fails. Shipped reference presets are read-only: the first edit produces a user copy.
Nothing here touches StableNew production settings or the production Tk theme.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .components import (
    Disclosure,
    FormTextEdit,
    NoticeBanner,
    SectionCard,
    SettingField,
    StatusChip,
    fit_segment,
    repolish,
    stacked_label,
)
from .theme import (
    COLOR_ROLES,
    DENSITIES,
    RANGES,
    STATE_DEFAULTS,
    WEIGHTS,
    Theme,
    ThemeEditor,
    ThemeError,
    build_stylesheet,
    contrast_checks,
    failing_checks,
    slugify,
)
from .theme_store import ThemeLibrary, ThemeStoreError
from .tokens import ASSET_DIR, preview_theme

STATE_COLUMNS = ("Default", "Hover", "Focus", "Pressed", "Disabled")
MIN_COLUMN = 340
COMPACT_BELOW = 2 * MIN_COLUMN + 100  # narrower than this shows one column at a time


class ThemePreview(QFrame):
    """Representative components rendered with a draft theme (and only that theme)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "preview-surface")
        self._layout = QVBoxLayout(self)
        self.theme: Theme | None = None
        self.matrix_widgets: dict[tuple[str, str], QWidget] = {}

    def rebuild(self, theme: Theme) -> None:
        self.theme = theme
        self.setStyleSheet(build_stylesheet(theme, ASSET_DIR))
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                _delete_layout(item.layout())
        self.matrix_widgets = {}
        with preview_theme(theme):
            m = theme.metrics()
            self._layout.setContentsMargins(m.gutter, m.gutter, m.gutter, m.gutter)
            self._layout.setSpacing(m.md)
            self._build(theme)

    def _build(self, theme: Theme) -> None:
        heading = QLabel(f"{theme.name} · live preview")
        heading.setProperty("role", "heading")
        self._layout.addWidget(heading)
        muted = QLabel(
            "Supporting text uses the muted role. Preview styling comes only from the draft theme."
        )
        muted.setProperty("role", "muted")
        muted.setWordWrap(True)
        self._layout.addWidget(muted)

        card = SectionCard(
            "Card · inputs and actions",
            "A reusable section card with a labelled input and action hierarchy.",
        )
        card.add(
            stacked_label(
                "Text input",
                QLineEdit("Example value"),
                help_text="Guidance stays visible without a tooltip.",
            )
        )
        combo = QComboBox()
        combo.addItems(["First choice", "Second choice"])
        card.add(stacked_label("Choice", combo))
        steps = QSpinBox()
        steps.setRange(1, 150)
        steps.setValue(28)
        field = SettingField("steps", "Setting field", steps)
        field.set_state(locked=False, differs=True, recommended="20", origin="manual")
        card.add(field)
        row = QWidget()
        buttons = QHBoxLayout(row)
        buttons.setContentsMargins(0, 0, 0, 0)
        for text, role in (("Secondary", None), ("Primary", "primary"), ("Danger", "danger")):
            button = QPushButton(text)
            if role:
                button.setProperty("role", role)
            buttons.addWidget(button)
        off = QPushButton("Disabled")
        off.setEnabled(False)
        buttons.addWidget(off)
        buttons.addStretch(1)
        card.add(row)
        self._layout.addWidget(card)

        notices = SectionCard("Status · words, not colour alone")
        for status, text, level in (
            ("INFO", "Informational notice.", "info"),
            ("WARNING", "Attention needed.", "warning"),
            ("BLOCKED", "Cannot proceed.", "blocked"),
            ("OK", "Ready.", "success"),
        ):
            banner = NoticeBanner()
            banner.set_message(status, text, level)
            notices.add(banner)
        chips = QWidget()
        chip_row = QHBoxLayout(chips)
        chip_row.setContentsMargins(0, 0, 0, 0)
        for text, level in (
            ("NOT BUILT", "info"),
            ("STALE", "warning"),
            ("BLOCKED", "blocked"),
            ("READY", "success"),
        ):
            chip_row.addWidget(StatusChip(text, level))
        chip_row.addStretch(1)
        notices.add(chips)
        disclosure = Disclosure("Disclosure header · collapsed", "Optional detail stays reachable.")
        notices.add(disclosure)
        self._layout.addWidget(notices)

        matrix = SectionCard(
            "Component states",
            "Hover, focus and pressed are forced so every state can be inspected at once.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.metrics().sm)
        for col, name in enumerate(STATE_COLUMNS, start=1):
            label = QLabel(name)
            label.setProperty("role", "muted")
            grid.addWidget(label, 0, col)
        rows = (
            ("Button", None),
            ("Primary", "primary"),
            ("Danger", "danger"),
            ("Input", "input"),
            ("Checkbox", "check"),
        )
        for r_index, (title, kind) in enumerate(rows, start=1):
            grid.addWidget(QLabel(title), r_index, 0)
            for c_index, state in enumerate(STATE_COLUMNS, start=1):
                if kind in ("input", "check") and state == "Pressed":
                    continue
                widget = self._state_widget(title, kind, state)
                self.matrix_widgets[(title, state)] = widget
                grid.addWidget(widget, r_index, c_index)
        holder = QWidget()
        holder.setLayout(grid)
        matrix.add(holder)
        self._layout.addWidget(matrix)
        self._layout.addStretch(1)

    @staticmethod
    def _state_widget(title: str, kind: str | None, state: str) -> QWidget:
        from PySide6.QtWidgets import QCheckBox  # local: keeps the module header short

        if kind == "input":
            widget: QWidget = QLineEdit("Text")
        elif kind == "check":
            widget = QCheckBox("Check")
        else:
            widget = QPushButton(title)
            if kind:
                widget.setProperty("role", kind)
        if state == "Disabled":
            widget.setEnabled(False)
        elif state != "Default":
            widget.setProperty("state", state.lower())
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the matrix is a display, not a tab stop
        widget.setAccessibleName(f"{title} {state} state sample")
        return widget


def _delete_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()


class ThemeStudio(QWidget):
    def __init__(
        self,
        library: ThemeLibrary,
        applied: Theme,
        apply_callback: Callable[[Theme], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.library = library
        self.applied_theme = applied
        self.apply_callback = apply_callback
        self.editor = ThemeEditor(applied)
        self._syncing = False
        self._pending_overwrite: str | None = None
        self.fields: dict[tuple[str, str], QWidget] = {}
        self.color_swatches: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        # Narrow windows show one column at a time (Edit / Preview); wide windows show both side by side.
        self.mode_bar = QWidget()
        mode_row = QHBoxLayout(self.mode_bar)
        mode_row.setContentsMargins(0, 0, 0, 0)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, label in (("edit", "Edit values"), ("preview", "Live preview and diagnostics")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("role", "segment")
            fit_segment(button)
            self.mode_group.addButton(button)
            self.mode_buttons[key] = button
            mode_row.addWidget(button)
            button.clicked.connect(lambda _c=False, k=key: self._set_mode(k))
        mode_row.addStretch(1)
        self.mode_buttons["edit"].setChecked(True)
        root.addWidget(self.mode_bar)
        self._mode = "edit"
        self.compact = False
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split)
        self.editor_column = self._build_editor_column()
        self.preview_column = self._build_preview_column()
        self.editor_column.setMinimumWidth(MIN_COLUMN)
        self.preview_column.setMinimumWidth(MIN_COLUMN + 60)
        split.addWidget(self.editor_column)
        split.addWidget(self.preview_column)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([420, 620])
        self.splitter = split
        self._reload_presets()
        self._sync_widgets()
        self._refresh()

    # ----------------------------------------------------------------- layout
    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self.mode_buttons[mode].setChecked(True)
        self._apply_mode()

    def _apply_mode(self) -> None:
        self.mode_bar.setVisible(self.compact)
        self.editor_column.setVisible(not self.compact or self._mode == "edit")
        self.preview_column.setVisible(not self.compact or self._mode == "preview")

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        compact = self.width() < COMPACT_BELOW
        if compact != self.compact:
            self.compact = compact
            self._apply_mode()

    def _scroll(self, body: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        return scroll

    def _build_editor_column(self) -> QWidget:
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(8, 8, 8, 16)
        col.setSpacing(12)

        head = SectionCard(
            "Theme",
            "Pick a preset, edit values below, then Apply, Save As or Export. Shipped presets are read-only.",
        )
        self.preset_combo = QComboBox()
        self.preset_combo.setAccessibleName("Theme preset")
        self.preset_combo.activated.connect(self._preset_activated)
        head.add(stacked_label("Preset", self.preset_combo))
        self.notice = NoticeBanner()
        head.add(self.notice)
        self.contrast_chip = StatusChip("CONTRAST", "info")
        head.add(self.contrast_chip)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name for Save As")
        self.name_edit.setAccessibleName("Theme name for Save As")
        self.name_edit.textEdited.connect(lambda _t: self.name_edit.setProperty("auto", "false"))
        head.add(stacked_label("Save As name", self.name_edit))
        actions = QWidget()
        grid = QGridLayout(actions)
        grid.setContentsMargins(0, 0, 0, 0)
        self.apply_button = QPushButton("Apply to prototype")
        self.apply_button.setProperty("role", "primary")
        self.revert_button = QPushButton("Revert edits")
        self.reset_button = QPushButton("Reset to preset")
        self.save_button = QPushButton("Save As…")
        self.export_button = QPushButton("Export…")
        self.import_button = QPushButton("Import…")
        self.delete_button = QPushButton("Delete saved")
        for index, button in enumerate(
            (
                self.apply_button,
                self.revert_button,
                self.reset_button,
                self.save_button,
                self.export_button,
                self.import_button,
                self.delete_button,
            )
        ):
            grid.addWidget(button, index // 2, index % 2)
        head.add(actions)
        self.apply_button.clicked.connect(self.apply)
        self.revert_button.clicked.connect(self.revert)
        self.reset_button.clicked.connect(self.reset_to_preset)
        self.save_button.clicked.connect(lambda: self.save_as())
        self.export_button.clicked.connect(self._export_clicked)
        self.import_button.clicked.connect(self._import_clicked)
        self.delete_button.clicked.connect(self.delete_selected)
        col.addWidget(head)

        colors = SectionCard(
            "Semantic colours", "#RRGGBB. Each role feeds the stylesheet; contrast is checked live."
        )
        for role in COLOR_ROLES:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            name = QLabel(role.replace("_", " "))
            name.setMinimumWidth(110)
            swatch = QLabel("")
            swatch.setFixedSize(28, 20)
            edit = QLineEdit()
            edit.setMaxLength(7)
            edit.setAccessibleName(f"Colour {role}")
            edit.setMinimumWidth(96)
            edit.textEdited.connect(lambda text, r=role: self._edit("colors", r, text))
            pick = QPushButton("Pick…")
            pick.setAccessibleName(f"Pick colour for {role}")
            pick.clicked.connect(lambda _c=False, r=role: self._pick_color(r))
            name.setBuddy(edit)
            for widget in (name, swatch, edit, pick):
                lay.addWidget(widget)
            lay.addStretch(1)
            self.fields[("colors", role)] = edit
            self.color_swatches[role] = swatch
            colors.add(row)
        col.addWidget(colors)

        typo = SectionCard("Typography")
        self.family_combo = QComboBox()
        self.family_combo.setAccessibleName("Font family")
        self.family_combo.activated.connect(
            lambda _i: self._edit("typography", "family", self.family_combo.currentText())
        )
        typo.add(stacked_label("Font family", self.family_combo))
        self.fields[("typography", "family")] = self.family_combo
        for key, title in (
            ("body_pt", "Body size (pt)"),
            ("small_pt", "Small size (pt)"),
            ("section_pt", "Section heading size (pt)"),
            ("heading_pt", "Page heading size (pt)"),
        ):
            typo.add(stacked_label(title, self._spin("typography", key)))
        weight = QComboBox()
        weight.addItems(WEIGHTS)
        weight.setAccessibleName("Emphasis weight")
        weight.activated.connect(
            lambda _i: self._edit("typography", "emphasis_weight", weight.currentText())
        )
        self.fields[("typography", "emphasis_weight")] = weight
        typo.add(stacked_label("Emphasis weight", weight))
        col.addWidget(typo)

        spacing = SectionCard(
            "Spacing and density",
            "Compact density scales layout gaps by 0.75; the control minimum height is never reduced by density.",
        )
        for key, title in (
            ("xs", "Extra small gap"),
            ("sm", "Small gap"),
            ("md", "Medium gap"),
            ("gutter", "Page gutter"),
            ("xl", "Extra large gap"),
            ("control_min_height", "Control minimum height"),
        ):
            spacing.add(stacked_label(f"{title} (px)", self._spin("spacing", key)))
        density = QComboBox()
        density.addItems(DENSITIES)
        density.setAccessibleName("Density")
        density.activated.connect(lambda _i: self._edit("", "density", density.currentText()))
        self.fields[("", "density")] = density
        spacing.add(stacked_label("Density", density))
        col.addWidget(spacing)

        shape = SectionCard("Borders and corner radius")
        for section, key, title in (
            ("borders", "control_width", "Control border width (px)"),
            ("borders", "card_width", "Card border width (px)"),
            ("radius", "control", "Control radius (px)"),
            ("radius", "button", "Button radius (px)"),
            ("radius", "card", "Card radius (px)"),
            ("radius", "chip", "Chip radius (px)"),
        ):
            shape.add(stacked_label(title, self._spin(section, key)))
        col.addWidget(shape)

        states = Disclosure(
            "Component state appearance",
            "Which colour role each state uses. Pick a role, not a literal colour.",
        )
        for key in STATE_DEFAULTS:
            combo = QComboBox()
            combo.addItems(COLOR_ROLES)
            combo.setAccessibleName(f"State {key}")
            combo.activated.connect(
                lambda _i, k=key, c=combo: self._edit("states", k, c.currentText())
            )
            self.fields[("states", key)] = combo
            states.add(stacked_label(key.replace("_", " "), combo))
        col.addWidget(states)
        col.addStretch(1)
        self.states_disclosure = states

        families = [f for f in QFontDatabase.families() if _safe_family(f)][:400]
        self.family_combo.addItems(families)
        self.setMinimumWidth(0)
        return self._scroll(body)

    def _build_preview_column(self) -> QWidget:
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(8, 8, 8, 16)
        col.setSpacing(12)
        self.preview = ThemePreview()
        col.addWidget(self.preview)
        diag = SectionCard(
            "Contrast diagnostics",
            "WCAG 2.x ratios of the draft. Targets: text 4.5:1 (primary label 7:1), outlines and focus edges 3:1.",
        )
        self.diagnostics = FormTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMinimumHeight(230)
        self.diagnostics.setAccessibleName("Contrast diagnostics")
        diag.add(self.diagnostics)
        col.addWidget(diag)
        col.addStretch(1)
        return self._scroll(body)

    def _spin(self, section: str, key: str) -> QSpinBox:
        low, high = RANGES[section][key]
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setAccessibleName(f"{section} {key}")
        spin.valueChanged.connect(lambda value, s=section, k=key: self._edit(s, k, value))
        self.fields[(section, key)] = spin
        return spin

    # -------------------------------------------------------------- editing
    @property
    def draft(self) -> Theme:
        return self.editor.draft

    def _edit(self, section: str, key: str, value: object) -> bool:
        if self._syncing:
            return False
        self._pending_overwrite = None
        ok = self.editor.set(section, key, value)
        widget = self.fields.get((section, key))
        if widget is not None:
            widget.setProperty("invalid", "false" if ok else "true")
            repolish(widget)
        if ok:
            self._invalidate_other_fields()
        self._refresh()
        return ok

    def edit(self, section: str, key: str, value: object) -> bool:
        """Programmatic edit (what a widget edit does); also mirrors the value into the widget."""
        widget = self.fields.get((section, key))
        self._syncing = True
        try:
            if isinstance(widget, QLineEdit):
                widget.setText(str(value))
            elif isinstance(widget, QSpinBox) and isinstance(value, int):
                widget.setValue(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
        finally:
            self._syncing = False
        return self._edit(section, key, value)

    def _invalidate_other_fields(self) -> None:
        for widget in self.fields.values():
            if widget.property("invalid") == "true":
                widget.setProperty("invalid", "false")
                repolish(widget)

    def _pick_color(self, role: str) -> None:
        current = QColor(getattr(self.draft.palette, role))
        chosen = QColorDialog.getColor(current, self, f"Colour for {role}")
        if chosen.isValid():
            self.edit("colors", role, chosen.name().upper())

    # ----------------------------------------------------- state -> widgets
    def _sync_widgets(self) -> None:
        d = self.draft
        self._syncing = True
        try:
            for role in COLOR_ROLES:
                value = getattr(d.palette, role)
                self.fields[("colors", role)].setText(value)
                self.color_swatches[role].setStyleSheet(
                    f"background: {value}; border: 1px solid {d.palette.strong_border}; border-radius: 4px;"
                )
            index = self.family_combo.findText(d.typography.family)
            if index < 0:
                self.family_combo.addItem(d.typography.family)
                index = self.family_combo.findText(d.typography.family)
            self.family_combo.setCurrentIndex(index)
            for section in ("typography", "spacing", "borders", "radius"):
                for key in RANGES[section]:
                    self.fields[(section, key)].setValue(getattr(getattr(d, section), key))
            self.fields[("typography", "emphasis_weight")].setCurrentText(
                d.typography.emphasis_weight
            )
            self.fields[("", "density")].setCurrentText(d.density)
            for key in STATE_DEFAULTS:
                self.fields[("states", key)].setCurrentText(getattr(d.states, key))
            for widget in self.fields.values():
                widget.setProperty("invalid", "false")
                repolish(widget)
        finally:
            self._syncing = False

    def _reload_presets(self, select: str | None = None) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for theme in self.library.references.values():
            self.preset_combo.addItem(f"{theme.name} · reference (read-only)", theme.id)
        for theme in self.library.user_themes().values():
            self.preset_combo.addItem(f"{theme.name} · saved", theme.id)
        target = select or self.editor.base.id
        index = next(
            (
                i
                for i in range(self.preset_combo.count())
                if self.preset_combo.itemData(i) == target
            ),
            0,
        )
        self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

    def _preset_activated(self, index: int) -> None:
        self.select_preset(self.preset_combo.itemData(index))

    def _say(self, status: str, text: str, level: str = "info") -> None:
        self.notice.set_message(status, text, level)

    def _refresh(self) -> None:
        ed, d = self.editor, self.editor.draft
        self._sync_color_swatches()
        if ed.errors:
            self._say(
                "INVALID EDIT",
                "; ".join(ed.errors) + " — the preview still shows the last valid draft.",
                "blocked",
            )
        failing = failing_checks(d)
        checks = contrast_checks(d)
        self.diagnostics.setPlainText(
            "\n".join(
                f"{'PASS' if c.passed else 'FAIL'}  {c.label}: {c.ratio:.1f}:1 (needs {c.minimum:g}:1)  {c.foreground} on {c.background}"
                for c in checks
            )
        )
        if failing:
            self.contrast_chip.set_status(f"CONTRAST · {len(failing)} FAIL", "blocked")
        else:
            self.contrast_chip.set_status(f"CONTRAST · ALL {len(checks)} PASS", "success")
        blocked = bool(failing) or bool(ed.errors)
        self.preview.rebuild(d)
        dirty = ed.is_dirty
        self.apply_button.setEnabled(not blocked)
        self.save_button.setEnabled(not blocked)
        self.export_button.setEnabled(not blocked)
        self.revert_button.setEnabled(dirty)
        self.reset_button.setEnabled(dirty or d.base_id is not None)
        self.delete_button.setEnabled(
            d.kind == "user" and d.id in self.library.user_themes() and not dirty
        )
        if not ed.errors:
            if ed.base.kind == "reference" and not dirty:
                self._say(
                    "REFERENCE",
                    f"{d.name} is a shipped read-only preset. Editing creates an unsaved user copy.",
                    "info",
                )
            elif dirty:
                self._say(
                    "UNSAVED EDITS",
                    f"'{d.name}' has unsaved changes"
                    + (
                        f" ({len(failing)} contrast check(s) fail: Apply, Save As and Export are blocked)."
                        if failing
                        else "."
                    ),
                    "warning",
                )
            else:
                self._say("SAVED THEME", f"{d.name} matches its saved file.", "success")
        if not self.name_edit.text().strip() or self.name_edit.property("auto") == "true":
            self.name_edit.setText(d.name if d.kind == "user" else f"{d.name} copy")
            self.name_edit.setProperty("auto", "true")

    def _sync_color_swatches(self) -> None:
        d = self.draft
        for role, swatch in self.color_swatches.items():
            swatch.setStyleSheet(
                f"background: {getattr(d.palette, role)}; border: 1px solid {d.palette.strong_border}; border-radius: 4px;"
            )

    # ---------------------------------------------------------------- actions
    def select_preset(self, theme_id: str, *, discard: bool = False) -> bool:
        if self.editor.is_dirty and not discard:
            self._say(
                "UNSAVED EDITS",
                "Save As or Revert before switching presets (or switch with discard).",
                "warning",
            )
            self._reload_presets()
            return False
        self.editor.load(self.library.get(theme_id))
        self._pending_overwrite = None
        self.name_edit.setText("")
        self._reload_presets(theme_id)
        self._sync_widgets()
        self._refresh()
        return True

    def revert(self) -> None:
        self.editor.revert()
        self._sync_widgets()
        self._refresh()

    def reset_to_preset(self) -> None:
        """Return to the reference preset this draft derives from (or the loaded theme if none)."""
        base_id = self.draft.base_id if self.draft.kind == "user" else self.editor.base.id
        if base_id in self.library.references:
            self.editor.load(self.library.references[base_id])
            self._reload_presets(base_id)
        else:
            self.editor.revert()
        self._sync_widgets()
        self._refresh()

    def apply(self) -> bool:
        failing = failing_checks(self.draft)
        if self.editor.errors or failing:
            self._say(
                "APPLY REFUSED",
                "Fix the invalid values or failing contrast checks first: "
                + ", ".join(c.label for c in failing[:3]),
                "blocked",
            )
            return False
        self.applied_theme = self.draft
        if self.apply_callback is not None:
            self.apply_callback(self.draft)
        try:
            self.library.set_active(self.draft)
            self._say(
                "APPLIED", f"{self.draft.name} applied and remembered for next launch.", "success"
            )
        except ThemeStoreError:
            self._say(
                "APPLIED · SESSION ONLY",
                f"{self.draft.name} is applied to this session; Save As to restore it next launch.",
                "warning",
            )
        return True

    def save_as(self, name: str | None = None, *, overwrite: bool = False) -> Theme | None:
        name = (name if name is not None else self.name_edit.text()).strip()
        if self.editor.errors or failing_checks(self.draft):
            self._say(
                "SAVE REFUSED",
                "Fix invalid values or failing contrast checks before saving.",
                "blocked",
            )
            return None
        slug = slugify(name)
        try:
            saved = self.library.save_as(
                self.draft, name, overwrite=overwrite or self._pending_overwrite == slug
            )
        except ThemeStoreError as exc:
            if "already exists" in str(exc):
                self._pending_overwrite = slug
                self._say(
                    "CONFIRM OVERWRITE", f"{exc} Press Save As again to overwrite.", "warning"
                )
            else:
                self._say("SAVE REFUSED", str(exc), "blocked")
            return None
        self._pending_overwrite = None
        self.editor.load(saved)
        self.name_edit.setText("")
        self._reload_presets(saved.id)
        self._sync_widgets()
        self._refresh()
        self._say(
            "SAVED",
            f"Saved '{saved.name}' as {self.library.path_for(saved.id).name}. It is not applied until you press Apply.",
            "success",
        )
        return saved

    def export_to(self, path: Path) -> bool:
        if self.editor.errors or failing_checks(self.draft):
            self._say(
                "EXPORT REFUSED",
                "Fix invalid values or failing contrast checks before exporting.",
                "blocked",
            )
            return False
        try:
            self.library.export_to(self.draft, Path(path))
        except ThemeStoreError as exc:
            self._say("EXPORT REFUSED", str(exc), "blocked")
            return False
        self._say(
            "EXPORTED", f"Wrote {Path(path).name}. Production settings were not touched.", "success"
        )
        return True

    def import_from(self, path: Path) -> bool:
        """Load a theme file into the draft (validated, never auto-saved or applied)."""
        if self.editor.is_dirty:
            self._say(
                "UNSAVED EDITS", "Save As or Revert before importing over unsaved edits.", "warning"
            )
            return False
        try:
            theme = self.library.import_from(Path(path))
        except ThemeError as exc:
            self._say(
                "IMPORT REFUSED",
                "; ".join(exc.errors[:4]) + (" …" if len(exc.errors) > 4 else ""),
                "blocked",
            )
            return False
        self.editor.load(theme)
        self._sync_widgets()
        self._refresh()
        self._say(
            "IMPORTED",
            f"'{theme.name}' was validated and loaded as an unsaved draft. Use Save As to keep it.",
            "success",
        )
        return True

    def delete_selected(self) -> bool:
        try:
            self.library.delete(self.draft.id)
        except ThemeStoreError as exc:
            self._say("DELETE REFUSED", str(exc), "blocked")
            return False
        self.editor.load(self.library.references["blue-modern"])
        self._reload_presets()
        self._sync_widgets()
        self._refresh()
        self._say("DELETED", "The saved theme file was removed.", "success")
        return True

    def _export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export theme", f"{self.draft.id}.json", "Theme JSON (*.json)"
        )
        if path:
            self.export_to(Path(path))

    def _import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import theme", "", "Theme JSON (*.json)")
        if path:
            self.import_from(Path(path))


def _safe_family(name: str) -> bool:
    from .theme import _FAMILY

    return bool(_FAMILY.match(name))
