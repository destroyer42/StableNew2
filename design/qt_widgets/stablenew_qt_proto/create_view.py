"""One runnable, completely mocked Create workflow using reusable Qt Widgets.

No production imports. Every action is local to a CreateSession demo draft.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .components import (
    ActionStrip, Disclosure, IssueList, NoWheelUnlessFocused, NoticeBanner,
    ResponsiveGrid, SectionCard, SettingField, StatusChip, guard_wheel, stacked_label,
)
from .domain import (
    MODELS, PROFILES, SAMPLERS, SCHEDULERS, SETTING_FIELDS, SETTING_LABELS, SETTING_RANGES,
    CreateSession, expand_prompt, format_setting, referenced_slots,
)
from .tokens import SPACE


def _scroll_area() -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


class CreateView(QWidget):
    """Mock Create operator journey: author → review → simulated receipt.

    The receipt does not enqueue a job or generate a result, even when its
    button says 'Simulate'. The app never contacts or imports StableNew.
    """

    stateSynced = Signal()  # emitted after every view/session synchronization (Output Display listens)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = CreateSession()
        self._updating = False
        self._size_model_key: str | None = None
        self._wheel_guard = NoWheelUnlessFocused(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        root.setSpacing(SPACE.sm)

        title = QLabel("Create Image  /  Mock operator journey")
        title.setProperty("role", "heading")
        root.addWidget(title)

        self.banner = NoticeBanner()
        self.banner.set_message("DEMO ONLY", "No model is loaded. Preview and admission are simulated; nothing is persisted.")
        root.addWidget(self.banner)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        self.form_scroll = _scroll_area()
        form_body = QWidget()
        self.form_layout = QVBoxLayout(form_body)
        self.form_layout.setContentsMargins(SPACE.sm, SPACE.xs, SPACE.sm, SPACE.xl)
        self.form_layout.setSpacing(SPACE.md)
        self._build_prompt_section()
        self._build_model_section()
        self._build_settings_section()
        self._build_advanced_section()
        self.form_layout.addStretch(1)
        self.form_scroll.setWidget(form_body)
        split.addWidget(self.form_scroll)

        self._build_review_panel(split)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        split.setSizes([810, 400])

        self.actions = ActionStrip()
        self.undo_button = self.actions.add_action("Undo")
        self.redo_button = self.actions.add_action("Redo")
        self.reset_button = self.actions.add_action("Reset demo draft")
        self.preview_button = self.actions.add_action("Build mock preview")
        self.admit_button = self.actions.add_action("Simulate admission", primary=True)
        self.undo_button.setToolTip("Undo the last draft change (Alt+Z)")
        self.redo_button.setToolTip("Redo (Alt+Y)")
        self.preview_button.setToolTip("Build the display-only preview (Ctrl+Enter)")
        self.admit_button.setToolTip("Simulate admission of a current, ready preview (Ctrl+Shift+Enter)")
        root.addWidget(self.actions)
        self.undo_button.clicked.connect(self._undo)
        self.redo_button.clicked.connect(self._redo)
        self.reset_button.clicked.connect(self._reset)
        self.preview_button.clicked.connect(self._build_preview)
        self.admit_button.clicked.connect(self._simulate_admission)
        self._add_shortcuts()
        self._sync_view()

    # ------------------------------------------------------------ construction
    def _add_shortcuts(self) -> None:
        for label, keys, slot in (
            ("Undo draft change", "Alt+Z", self._undo),
            ("Redo draft change", "Alt+Y", self._redo),
            ("Build mock preview", "Ctrl+Return", self._build_preview),
            ("Simulate admission", "Ctrl+Shift+Return", self._simulate_admission),
        ):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(keys))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(slot)
            self.addAction(action)

    def _build_prompt_section(self) -> None:
        card = SectionCard(
            "01 · Author your PromptPack",
            "Reference slots in prompts as {slot_name}. Nothing is saved to a real pack store.",
        )
        self.pack_name = QLineEdit()
        self.pack_name.setPlaceholderText("Working draft name")
        self.pack_name.setAccessibleName("Pack name")
        self.pack_name.textChanged.connect(lambda value: self._set_text("pack_name", value))
        card.add(stacked_label("Pack name · unsaved demo draft", self.pack_name))

        self.prompt_text = QPlainTextEdit()
        self.prompt_text.setMinimumHeight(88)
        self.prompt_text.setMaximumHeight(120)
        self.prompt_text.setPlaceholderText("Describe your subject, composition and intent")
        self.prompt_text.setAccessibleName("Main prompt")
        self.prompt_text.textChanged.connect(lambda: self._set_text("prompt", self.prompt_text.toPlainText()))
        card.add(stacked_label("Main prompt", self.prompt_text))
        self.prompt_meta = QLabel("")
        self.prompt_meta.setProperty("role", "muted")
        self.prompt_meta.setWordWrap(True)
        card.add(self.prompt_meta)

        self.negative_text = QPlainTextEdit()
        self.negative_text.setMinimumHeight(52)
        self.negative_text.setMaximumHeight(80)
        self.negative_text.setAccessibleName("Negative prompt")
        self.negative_text.textChanged.connect(lambda: self._set_text("negative", self.negative_text.toPlainText()))
        card.add(stacked_label("Negative prompt (availability depends on model fixture)", self.negative_text))

        self.slots = QTableWidget(0, 2)
        self.slots.setHorizontalHeaderLabels(["Slot", "Value"])
        self.slots.horizontalHeader().setStretchLastSection(True)
        self.slots.setMinimumHeight(120)
        self.slots.setMaximumHeight(170)
        self.slots.setAccessibleName("PromptPack structured slots")
        self.slots.itemChanged.connect(self._slots_changed)
        card.add(stacked_label("PromptPack slots · edit names and values", self.slots))
        slot_actions = QWidget()
        row = QHBoxLayout(slot_actions)
        row.setContentsMargins(0, 0, 0, 0)
        self.add_slot_button = QPushButton("Add slot")
        self.remove_slot_button = QPushButton("Remove selected slot")
        row.addWidget(self.add_slot_button)
        row.addWidget(self.remove_slot_button)
        row.addStretch(1)
        self.add_slot_button.clicked.connect(self._add_slot)
        self.remove_slot_button.clicked.connect(self._remove_slot)
        card.add(slot_actions)
        self.form_layout.addWidget(card)

    def _build_model_section(self) -> None:
        card = SectionCard("02 · Model and settings source", "Fixture profiles demonstrate recommendation and override behavior; they do not assert model capabilities.")
        self.model_combo = QComboBox()
        for model in MODELS:
            self.model_combo.addItem(model.label, model.key)
        self.model_combo.setAccessibleName("Selected model")
        guard_wheel(self.model_combo, self._wheel_guard)
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        card.add(stacked_label("Selected model", self.model_combo))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(PROFILES)
        self.profile_combo.setAccessibleName("Settings source")
        guard_wheel(self.profile_combo, self._wheel_guard)
        self.profile_combo.currentTextChanged.connect(self._profile_changed)
        card.add(stacked_label(
            "Settings source", self.profile_combo,
            help_text="Learning-informed is a selectable state illustration, not a real qualified recommendation.",
        ))
        self.change_detail = QLabel("No model/profile changes to review.")
        self.change_detail.setProperty("role", "muted")
        self.change_detail.setWordWrap(True)
        card.add(self.change_detail)
        log = Disclosure("Change log", "Every draft change this session, newest first. In memory only.")
        self.change_log_view = QPlainTextEdit()
        self.change_log_view.setReadOnly(True)
        self.change_log_view.setMinimumHeight(110)
        self.change_log_view.setMaximumHeight(160)
        self.change_log_view.setAccessibleName("Change log")
        log.add(self.change_log_view)
        card.add(log)
        self.form_layout.addWidget(card)

    def _make_editor(self, name: str) -> QWidget:
        if name in ("sampler", "scheduler"):
            editor = QComboBox()
            editor.addItems(SAMPLERS if name == "sampler" else SCHEDULERS)
            editor.currentTextChanged.connect(lambda value, field=name: self._setting_changed(field, value))
        elif name == "cfg":
            editor = QDoubleSpinBox()
            low, high = SETTING_RANGES[name]
            editor.setRange(low, high)
            editor.setDecimals(1)
            editor.setSingleStep(0.5)
            editor.valueChanged.connect(lambda value, field=name: self._setting_changed(field, value))
        else:
            editor = QSpinBox()
            low, high = SETTING_RANGES[name]
            editor.setRange(int(low), int(high))
            editor.setSingleStep(64 if name in ("width", "height") else 1)
            if name == "seed":
                editor.setSpecialValueText("Random")
            editor.valueChanged.connect(lambda value, field=name: self._setting_changed(field, value))
        guard_wheel(editor, self._wheel_guard)
        editor.setAccessibleName(SETTING_LABELS[name])
        return editor

    def _build_settings_section(self) -> None:
        card = SectionCard(
            "03 · Effective settings",
            "Lock a value to keep it when the model or source changes. ↺ returns one value to the recommendation.",
        )
        top = ResponsiveGrid(min_column_width=250)  # wraps instead of clipping when narrow
        self.size_combo = QComboBox()
        self.size_combo.setAccessibleName("Size preset")
        guard_wheel(self.size_combo, self._wheel_guard)
        self.size_combo.currentIndexChanged.connect(self._size_preset_changed)
        top.add(stacked_label("Size preset (characterized sizes)", self.size_combo))
        button_cell = QWidget()
        button_col = QVBoxLayout(button_cell)
        button_col.setContentsMargins(0, 0, 0, 0)
        button_col.addStretch(1)
        self.reset_unlocked_button = QPushButton("Reset unlocked to recommended")
        button_col.addWidget(self.reset_unlocked_button)
        self.reset_unlocked_button.clicked.connect(self._reset_unlocked)
        top.add(button_cell)
        card.add(top)

        grid = ResponsiveGrid(min_column_width=190, column_gap=SPACE.xl)
        self.setting_inputs: dict[str, QWidget] = {}
        self.lock_inputs: dict[str, QCheckBox] = {}
        self.setting_fields: dict[str, SettingField] = {}
        for name in SETTING_FIELDS:
            editor = self._make_editor(name)
            field = SettingField(name, SETTING_LABELS[name], editor)
            field.lockToggled.connect(lambda checked, field_name=name: self._lock_changed(field_name, checked))
            field.resetRequested.connect(lambda field_name=name: self._reset_setting(field_name))
            self.setting_inputs[name] = editor
            self.lock_inputs[name] = field.lock
            self.setting_fields[name] = field
            grid.add(field)
        self.settings_grid = grid
        card.add(grid)
        self.form_layout.addWidget(card)

    def _build_advanced_section(self) -> None:
        card = SectionCard("04 · Additional prompt channels", "Advanced details remain available without obscuring the primary Create action.")
        self.advanced_summary = QLabel("Global: off · ADetailer: off · LoRA: none · Embeddings: none")
        self.advanced_summary.setProperty("role", "muted")
        self.advanced_summary.setWordWrap(True)
        card.add(self.advanced_summary)
        advanced = Disclosure("Advanced prompt channels", "These are authoring demonstrations, not compiled production stages.")
        self.global_text = QPlainTextEdit()
        self.global_text.setFixedHeight(62)
        self.global_text.setAccessibleName("Global prompt")
        self.global_text.textChanged.connect(lambda: self._set_text("global_prompt", self.global_text.toPlainText()))
        advanced.add(stacked_label("Global prompt", self.global_text))
        self.adetailer_check = QCheckBox("Enable ADetailer (demo only)")
        self.adetailer_check.toggled.connect(self._adetailer_changed)
        advanced.add(self.adetailer_check)
        self.adetailer_text = QPlainTextEdit()
        self.adetailer_text.setFixedHeight(62)
        self.adetailer_text.setAccessibleName("ADetailer prompt")
        self.adetailer_text.textChanged.connect(lambda: self._set_text("adetailer_prompt", self.adetailer_text.toPlainText()))
        advanced.add(stacked_label("ADetailer prompt", self.adetailer_text))
        self.lora_text = QLineEdit()
        self.lora_text.setPlaceholderText("LoRA references, not resolved")
        self.lora_text.textChanged.connect(lambda s: self._set_text("loras", s))
        advanced.add(stacked_label("LoRA notes", self.lora_text))
        self.embedding_text = QLineEdit()
        self.embedding_text.setPlaceholderText("Embedding references, not resolved")
        self.embedding_text.textChanged.connect(lambda s: self._set_text("embeddings", s))
        advanced.add(stacked_label("Embedding notes", self.embedding_text))
        card.add(advanced)
        self.form_layout.addWidget(card)

    def _build_review_panel(self, split: QSplitter) -> None:
        self.review_scroll = _scroll_area()
        self.review = QWidget()
        self.review_layout = QVBoxLayout(self.review)
        self.review_layout.setContentsMargins(SPACE.md, SPACE.sm, SPACE.md, SPACE.sm)
        self.review_layout.setSpacing(SPACE.md)
        review_title = QLabel("Effective settings / Preview")
        review_title.setProperty("role", "section")
        self.review_layout.addWidget(review_title)
        review_guide = QLabel("Preview is a display-only snapshot. It is NOT the compiler's NJR Preview and grants no execution authority.")
        review_guide.setProperty("role", "muted")
        review_guide.setWordWrap(True)
        self.review_layout.addWidget(review_guide)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(200)
        self.preview_text.setAccessibleName("Mock preview and effective setting summary")
        self.review_layout.addWidget(self.preview_text, 1)
        chip_row = QHBoxLayout()
        self.preview_chip = StatusChip("NOT BUILT", "info")
        chip_row.addWidget(self.preview_chip)
        chip_row.addStretch(1)
        self.review_layout.addLayout(chip_row)
        self.review_state = QLabel("Preview state: Not built")
        self.review_state.setWordWrap(True)
        self.review_layout.addWidget(self.review_state)
        self.issue_list = IssueList()
        self.review_layout.addWidget(self.issue_list)
        self.result_card = SectionCard("Mock result", "No real image generated, no job ID issued.")
        self.result_text = QLabel("This panel will display the simulated admission acknowledgement.")
        self.result_text.setWordWrap(True)
        self.result_card.add(self.result_text)
        self.review_layout.addWidget(self.result_card)
        self.review_layout.addStretch(0)
        self.review_scroll.setWidget(self.review)
        # Never let the splitter squeeze the review panel below its content (it would clip, not scroll).
        self.review_scroll.setMinimumWidth(self.review.minimumSizeHint().width() + 24)
        split.addWidget(self.review_scroll)

    # --------------------------------------------------------------- handlers
    def _set_text(self, field: str, value: str) -> None:
        if self._updating:
            return
        self.session.set_text(field, value)
        self._sync_view()

    def _setting_changed(self, field: str, value: object) -> None:
        if self._updating:
            return
        self.session.set_setting(field, value)
        self._sync_view()

    def _lock_changed(self, field: str, checked: bool) -> None:
        if self._updating:
            return
        self.session.toggle_lock(field, checked)
        self._sync_view()

    def _reset_setting(self, field: str) -> None:
        self.session.reset_setting(field)
        self._sync_view()

    def _reset_unlocked(self) -> None:
        self.session.reset_unlocked_settings()
        self._sync_view()

    def _size_preset_changed(self, index: int) -> None:
        if self._updating or index < 0:
            return
        data = self.size_combo.itemData(index)
        if data:
            width, height = (int(part) for part in str(data).split("x"))
            self.session.apply_size(width, height)
            self._sync_view()

    def _model_changed(self, index: int) -> None:
        if self._updating or index < 0:
            return
        self.session.switch_model(self.model_combo.itemData(index))
        self._sync_view()

    def _profile_changed(self, value: str) -> None:
        if self._updating:
            return
        self.session.set_profile_source(value)
        self._sync_view()

    def _adetailer_changed(self, checked: bool) -> None:
        if self._updating:
            return
        self.session.set_adetailer_enabled(checked)
        self._sync_view()

    def _slots_changed(self, _item: QTableWidgetItem) -> None:
        if self._updating:
            return
        names: list[str] = []
        new_slots: dict[str, str] = {}
        for row in range(self.slots.rowCount()):
            name_item, value_item = self.slots.item(row, 0), self.slots.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            value = value_item.text() if value_item else ""
            if name:
                names.append(name)
                new_slots[name] = value
        if len(names) != len(set(names)):
            self.banner.set_message("DUPLICATE SLOT", "Slot names must be unique; the edit was not applied.", "blocked")
            return
        try:
            self.session.replace_slots(new_slots)
        except ValueError as exc:
            self.banner.set_message("SLOT REFUSED", str(exc), "blocked")
            return
        self._sync_view()

    def _add_slot(self) -> None:
        name = f"slot_{len(self.session.draft.slots) + 1}"
        while name in self.session.draft.slots:
            name += "_new"
        self.session.set_slot(name, "value")
        self._sync_view()

    def _remove_slot(self) -> None:
        row = self.slots.currentRow()
        if row < 0:
            self.banner.set_message("SELECT SLOT", "Select a row before removing a slot from the mock draft.", "warning")
            return
        item = self.slots.item(row, 0)
        if item:
            self.session.remove_slot(item.text())
        self._sync_view()

    def _undo(self) -> None:
        if self.session.undo():
            self._sync_view()
            self.banner.set_message("UNDO", "Restored the previous draft state.")

    def _redo(self) -> None:
        if self.session.redo():
            self._sync_view()
            self.banner.set_message("REDO", "Re-applied the undone draft state.")

    def _build_preview(self) -> None:
        preview = self.session.build_preview()
        self._sync_view()
        if preview.errors:
            self.banner.set_message("MOCK PREVIEW REFUSED", "; ".join(preview.errors), "blocked")
        else:
            self.banner.set_message("MOCK PREVIEW READY", "This is a display-only summary. No NJR has been compiled.", "success")

    def _simulate_admission(self) -> None:
        try:
            receipt = self.session.simulate_admission()
        except RuntimeError as exc:
            self.banner.set_message("SIMULATION REFUSED", str(exc), "blocked")
            return
        self._sync_view()
        self.banner.set_message("SIMULATED ONLY", receipt.message, "success")
        self.review_scroll.ensureWidgetVisible(self.result_card)

    def _reset(self) -> None:
        # Undoable, so no modal confirmation is needed (and nothing can hang a test run).
        self.session.reset()
        self._sync_view()
        self.banner.set_message("DEMO RESET", "The local mock draft has been reset; use Undo to restore it. Nothing was persisted.", "warning")

    # ------------------------------------------------------------------- sync
    def _refresh_size_presets(self) -> None:
        model = next(m for m in MODELS if m.key == self.session.draft.model_key)
        if self._size_model_key != model.key:
            self.size_combo.clear()
            for width, height in model.characterized_sizes:
                self.size_combo.addItem(f"{width} × {height}", f"{width}x{height}")
            self.size_combo.addItem("Custom size", "")
            self._size_model_key = model.key
        s = self.session.draft.settings
        wanted = f"{s.width}x{s.height}"
        index = next((i for i in range(self.size_combo.count()) if self.size_combo.itemData(i) == wanted), self.size_combo.count() - 1)
        self.size_combo.setCurrentIndex(index)

    def _sync_view(self) -> None:
        self._updating = True
        try:
            d = self.session.draft
            # Synchronize values without triggering model/field signal handlers.
            for widget, value in (
                (self.pack_name, d.pack_name),
                (self.prompt_text, d.prompt),
                (self.negative_text, d.negative),
                (self.global_text, d.global_prompt),
                (self.adetailer_text, d.adetailer_prompt),
                (self.lora_text, d.loras),
                (self.embedding_text, d.embeddings),
            ):
                if isinstance(widget, QPlainTextEdit):
                    if widget.toPlainText() != value:
                        widget.setPlainText(value)
                else:
                    if widget.text() != value:
                        widget.setText(value)
            self.adetailer_check.setChecked(d.adetailer_enabled)
            self.model_combo.setCurrentIndex(next(i for i in range(self.model_combo.count()) if self.model_combo.itemData(i) == d.model_key))
            self.profile_combo.setCurrentText(d.profile_source)
            self._refresh_size_presets()
            recommended = self.session.recommended
            for name, widget in self.setting_inputs.items():
                val = getattr(d.settings, name)
                if isinstance(widget, QComboBox):
                    if widget.currentText() != str(val):
                        widget.setCurrentText(str(val))
                elif widget.value() != val:
                    widget.setValue(val)
                self.setting_fields[name].set_state(
                    locked=name in d.locked_fields,
                    differs=val != getattr(recommended, name),
                    recommended=format_setting(name, getattr(recommended, name)),
                )
            self.reset_unlocked_button.setEnabled(
                any(self.session.differs_from_recommended(n) for n in SETTING_FIELDS if n not in d.locked_fields)
            )
            current_slots = [
                (
                    self.slots.item(i, 0).text() if self.slots.item(i, 0) else "",
                    self.slots.item(i, 1).text() if self.slots.item(i, 1) else "",
                )
                for i in range(self.slots.rowCount())
            ]
            if current_slots != list(d.slots.items()):
                self.slots.setRowCount(len(d.slots))
                for row, (key, value) in enumerate(d.slots.items()):
                    self.slots.setItem(row, 0, QTableWidgetItem(key))
                    self.slots.setItem(row, 1, QTableWidgetItem(value))
            words = len(d.prompt.split())
            unresolved = expand_prompt(d.prompt, d.slots)[1]
            used = len(referenced_slots(d.prompt) & set(d.slots))
            self.prompt_meta.setText(
                f"{words} words · {used} of {len(d.slots)} slots used"
                + (f" · unresolved: {', '.join('{' + n + '}' for n in unresolved)}" if unresolved else "")
            )
            log = self.session.change_log
            self.change_detail.setText(
                f"Latest change (r{log[-1][0]}): {log[-1][1]}" if log else "No model/profile changes to review."
            )
            self.change_log_view.setPlainText("\n".join(f"r{rev} · {note}" for rev, note in reversed(log)))
            self.advanced_summary.setText(
                f"Global: {'set' if d.global_prompt else 'off'} · ADetailer: {'on' if d.adetailer_enabled else 'off'} · "
                f"LoRA: {'noted' if d.loras else 'none'} · Embeddings: {'noted' if d.embeddings else 'none'}"
            )
            preview = self.session.preview
            if preview is None:
                self.preview_text.setPlainText("Not previewed yet.\n\nEdit the mock draft, then choose Build mock preview.\n\nThere is no real model or backend in this assessment.")
                self.review_state.setText("Preview state: Not built")
                self.preview_chip.set_status("NOT BUILT", "info")
                self.issue_list.set_issues((), (), empty="Build a preview to run the mock checks")
            else:
                self.preview_text.setPlainText(preview.text)
                current = self.session.is_preview_current
                state = "CURRENT" if current else "STALE — draft has changed"
                errors = " | ".join(preview.errors) if preview.errors else "none"
                warnings = " | ".join(preview.warnings) if preview.warnings else "none"
                self.review_state.setText(f"Preview state: {state}")
                self.review_state.setToolTip(f"Errors: {errors}\nWarnings: {warnings}")
                if not current:
                    self.preview_chip.set_status("STALE", "warning")
                elif preview.errors:
                    self.preview_chip.set_status("BLOCKED", "blocked")
                else:
                    self.preview_chip.set_status("CURRENT · READY", "success")
                self.issue_list.set_issues(preview.errors, preview.warnings, empty="No mock issues found")
            self.admit_button.setEnabled(self.session.can_simulate_admission)
            self.undo_button.setEnabled(self.session.can_undo)
            self.redo_button.setEnabled(self.session.can_redo)
            self.actions.status.setText(
                f"Revision {self.session.revision} · "
                + ("Mock preview current" if self.session.is_preview_current else "Preview needed")
            )
            self.actions.status.setToolTip("Mock only: no production queue, job or image is involved.")
            if self.session.demo_receipt:
                self.result_text.setText(self.session.demo_receipt.message + "\n\nThis is NOT a persisted job or gallery artifact.")
            else:
                self.result_text.setText("No simulated receipt. No image has been created.")
        finally:
            self._updating = False
        self.stateSynced.emit()
