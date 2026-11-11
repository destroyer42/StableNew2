"""One runnable, completely mocked Create workflow using reusable Qt Widgets.

No production imports. Every action is local to a CreateSession demo draft.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .components import (
    ActionStrip,
    Disclosure,
    FormTextEdit,
    IssueList,
    NoticeBanner,
    NoWheelUnlessFocused,
    ResponsiveGrid,
    ResultGallery,
    SectionCard,
    SettingField,
    StatusChip,
    guard_wheel,
    reveal,
    stacked_label,
)
from .domain import (
    ADVANCED_SETTINGS,
    BASIC_SETTINGS,
    MODEL_BY_KEY,
    MODELS,
    PACKS,
    PROFILES,
    SETTING_FIELDS,
    SETTING_LABELS,
    SETTING_RANGES,
    SOURCE_FREE,
    CreateSession,
    expand_prompt,
    format_setting,
    referenced_slots,
)
from .edit_domain import CREATE_SOURCE
from .tokens import SPACE

LAYOUT_SCROLL = "scroll"  # design A: one vertically scrolling column, preview/result last
LAYOUT_SPLIT = "split"  # design B: authoring column + persistent summary/preview/result pane
LAYOUT_DESIGNS = (LAYOUT_SCROLL, LAYOUT_SPLIT)
THREE_PANE_WIDTH = 930


def _scroll_area() -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


class CreateView(QWidget):
    """Mock Create operator journey: author → review → simulated receipt.

    The receipt does not enqueue a job or generate a result, even when its
    button says 'Simulate'. The app never contacts or imports StableNew.
    """

    stateSynced = (
        Signal()
    )  # emitted after every view/session synchronization (Output Display listens)
    editRequested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        session: CreateSession | None = None,
        layout_design: str = LAYOUT_SPLIT,
    ):
        super().__init__(parent)
        if layout_design not in LAYOUT_DESIGNS:
            raise ValueError(f"Unknown layout design: {layout_design}")
        self.session = session or CreateSession()
        self._design = LAYOUT_SPLIT
        self._updating = False
        self._size_model_key: str | None = None
        self._draft_issues: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        self._wheel_guard = NoWheelUnlessFocused(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        root.setSpacing(SPACE.sm)

        head = QHBoxLayout()
        title = QLabel("Create Image")
        title.setProperty("role", "heading")
        head.addWidget(title)
        self.preview_chip = StatusChip("NOT BUILT", "info")
        head.addWidget(self.preview_chip)
        head.addStretch(1)
        root.addLayout(head)

        self.banner = NoticeBanner()
        self.banner.set_message(
            "DEMO ONLY",
            "Models, profiles, Preview and results are mock fixtures.",
        )
        root.addWidget(self.banner)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        self.form_scroll = _scroll_area()
        form_body = QWidget()
        self.form_layout = QVBoxLayout(form_body)
        self.form_layout.setContentsMargins(0, 0, SPACE.xs, SPACE.xs)
        self.form_layout.setSpacing(SPACE.sm)
        self._build_prompt_section()
        self.form_scroll.setMinimumWidth(284)
        self._build_settings_section()
        self._build_advanced_section()
        self.form_layout.addWidget(self.advanced_card)
        self.form_layout.addStretch(1)
        self.form_scroll.setWidget(form_body)
        split.addWidget(self.form_scroll)

        self.settings_scroll = _scroll_area()
        self.settings_scroll.setMinimumWidth(270)
        settings_body = QWidget()
        self.settings_layout = QVBoxLayout(settings_body)
        self.settings_layout.setContentsMargins(0, 0, SPACE.xs, SPACE.xs)
        self.settings_layout.addStretch(1)
        self.settings_scroll.setWidget(settings_body)
        split.addWidget(self.settings_scroll)
        self._build_review_panel(split)
        self.split = split
        self._panes: str | None = None

        self.actions = ActionStrip()
        self.undo_button = self.actions.add_action("Undo")
        self.redo_button = self.actions.add_action("Redo")
        self.reset_button = self.actions.add_action("Reset draft")
        self.preview_button = self.actions.add_action("Build Preview")
        self.admit_button = self.actions.add_action("Simulate admission", primary=True)
        self.undo_button.setToolTip("Undo the last draft change (Alt+Z)")
        self.redo_button.setToolTip("Redo (Alt+Y)")
        self.preview_button.setToolTip("Build the display-only preview (Ctrl+Enter)")
        self.admit_button.setToolTip(
            "Simulate admission of a current, ready preview (Ctrl+Shift+Enter)"
        )
        root.addWidget(self.actions)
        self.undo_button.clicked.connect(self._undo)
        self.redo_button.clicked.connect(self._redo)
        self.reset_button.clicked.connect(self._reset)
        self.preview_button.clicked.connect(self._build_preview)
        self.admit_button.clicked.connect(self._simulate_admission)
        self._add_shortcuts()
        self._sync_view()
        self.set_layout_design(layout_design)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)

    # ------------------------------------------------------------- layout design
    @property
    def layout_design(self) -> str:
        return self._design

    def set_layout_design(self, design: str) -> None:
        """Switch between the scrolling-form and split-workspace designs without losing state."""
        if design not in LAYOUT_DESIGNS:
            raise ValueError(f"Unknown layout design: {design}")
        self._design = design
        self._arrange_panes()
        self.stateSynced.emit()

    @property
    def scroll_areas(self) -> tuple[QScrollArea, ...]:
        return self.form_scroll, self.settings_scroll, self.review_scroll

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._arrange_panes()

    def _arrange_panes(self) -> None:
        if self._design == LAYOUT_SCROLL:
            panes = "vertical"
        else:
            panes = "wide" if self.width() >= THREE_PANE_WIDTH else "compact"
        if panes == self._panes:
            return
        focus = QApplication.focusWidget()
        self._panes = panes
        self.form_layout.removeWidget(self.settings_card)
        self.settings_layout.removeWidget(self.settings_card)
        if panes == "wide":
            self.settings_layout.insertWidget(0, self.settings_card)
        else:
            self.form_layout.insertWidget(1, self.settings_card)
        self.settings_scroll.setVisible(panes == "wide")
        self.settings_card.show()
        if panes == "vertical":
            self.review_scroll.takeWidget()
            self.review_scroll.hide()
            self.form_layout.insertWidget(self.form_layout.count() - 1, self.review)
            self.review.show()
        else:
            self.form_layout.removeWidget(self.review)
            self.review_scroll.setWidget(self.review)
            self.review_scroll.show()
            self.split.setSizes([350, 335, 315] if panes == "wide" else [570, 0, 350])
        self._set_tab_order()
        if focus is not None and self.isAncestorOf(focus) and focus.isVisibleTo(self):
            focus.setFocus()

    def _set_tab_order(self) -> None:
        # Reparenting moves a pane to the end of Qt's focus chain. Restore visual order.
        fields = []
        for name in (*BASIC_SETTINGS, *ADVANCED_SETTINGS):
            if name == ADVANCED_SETTINGS[0]:
                fields.append(self.advanced_settings.toggle)
            field = self.setting_fields[name]
            fields.extend((field.lock, field.editor, field.reset_button))
        channels = (
            self.channels_disclosure.toggle,
            self.global_text,
            self.adetailer_check,
            self.adetailer_text,
            self.lora_text,
            self.embedding_text,
        )
        advanced_start = len(BASIC_SETTINGS) * 3
        settings = (
            self.size_combo,
            *fields[:advanced_start],
            self.reset_unlocked_button,
            *fields[advanced_start:],
        )
        order = (
            self.source_combo,
            self.prompt_text,
            self.model_combo,
            self.profile_combo,
            self.prompt_details.toggle,
            self.pack_name,
            self.resolved_text,
            self.negative_text,
            self.slots,
            self.add_slot_button,
            self.remove_slot_button,
            self.change_log.toggle,
            self.change_log_view,
            *(channels + settings if self._panes == "wide" else settings + channels),
            self.preview_text,
            self.undo_button,
            self.redo_button,
            self.reset_button,
            self.preview_button,
            self.admit_button,
        )
        for earlier, later in zip(order, order[1:], strict=False):
            QWidget.setTabOrder(earlier, later)

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        """Keyboard focus must never land on a control that is scrolled out of view."""
        if new is None or not self.isAncestorOf(new):
            return
        for scroll in self.scroll_areas:
            body = scroll.widget()
            if body is not None and body.isAncestorOf(new) and scroll.isVisible():
                reveal(scroll, new)

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

    def _reveal_disclosure(self, opened: bool) -> None:
        if opened:
            # Settle the layout before the newly opened section receives keyboard focus.
            QTimer.singleShot(
                0, self, lambda: self._on_focus_changed(None, QApplication.focusWidget())
            )

    @staticmethod
    def _card(title: str) -> SectionCard:
        card = SectionCard(title)
        card.content.setSpacing(SPACE.sm)
        card.content.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        return card

    def _build_prompt_section(self) -> None:
        card = self._card("Prompt")
        self.prompt_details = Disclosure("Prompt details and slots")
        self.prompt_details.toggle.toggled.connect(self._reveal_disclosure)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Free prompt (no pack)", SOURCE_FREE)
        for pack in PACKS:
            self.source_combo.addItem(pack.label, pack.key)
        self.source_combo.setAccessibleName("Prompt source")
        guard_wheel(self.source_combo, self._wheel_guard)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.source_combo.setToolTip(
            "Choosing a fixture pack replaces the working text. Undo restores it."
        )
        card.add(stacked_label("Prompt source", self.source_combo))
        self.pack_name = QLineEdit()
        self.pack_name.setPlaceholderText("Working draft name")
        self.pack_name.setAccessibleName("Pack name")
        self.pack_name.textChanged.connect(lambda value: self._set_text("pack_name", value))
        self.prompt_details.add(stacked_label("Pack name · unsaved", self.pack_name))

        self.prompt_text = FormTextEdit()
        self.prompt_text.setMinimumHeight(88)
        self.prompt_text.setMaximumHeight(104)
        self.prompt_text.setPlaceholderText("Describe your subject, composition and intent")
        self.prompt_text.setAccessibleName("Main prompt")
        self.prompt_text.textChanged.connect(
            lambda: self._set_text("prompt", self.prompt_text.toPlainText())
        )
        card.add(stacked_label("Main prompt", self.prompt_text))
        self.prompt_meta = QLabel("")
        self.prompt_meta.setProperty("role", "muted")
        self.prompt_meta.setWordWrap(True)
        self.prompt_details.add(self.prompt_meta)
        self.resolved_text = FormTextEdit()
        self.resolved_text.setReadOnly(True)
        self.resolved_text.setMinimumHeight(52)
        self.resolved_text.setMaximumHeight(80)
        self.resolved_text.setAccessibleName("Resolved prompt (read-only)")
        self.prompt_details.add(stacked_label("Resolved prompt", self.resolved_text))

        self.negative_text = FormTextEdit()
        self.negative_text.setMinimumHeight(52)
        self.negative_text.setMaximumHeight(80)
        self.negative_text.setAccessibleName("Negative prompt")
        self.negative_text.textChanged.connect(
            lambda: self._set_text("negative", self.negative_text.toPlainText())
        )
        self.prompt_details.add(stacked_label("Negative prompt", self.negative_text))

        self.slots = QTableWidget(0, 2)
        self.slots.setHorizontalHeaderLabels(["Slot", "Value"])
        self.slots.horizontalHeader().setStretchLastSection(True)
        self.slots.setMinimumHeight(120)
        self.slots.setMaximumHeight(170)
        self.slots.setAccessibleName("PromptPack structured slots")
        self.slots.itemChanged.connect(self._slots_changed)
        self.slots.setToolTip("Reference a slot from the prompt with {slot_name}.")
        self.prompt_details.add(stacked_label("PromptPack slots", self.slots))
        slot_actions = QWidget()
        row = QHBoxLayout(slot_actions)
        row.setContentsMargins(0, 0, 0, 0)
        self.add_slot_button = QPushButton("Add slot")
        self.remove_slot_button = QPushButton("Remove selected")
        row.addWidget(self.add_slot_button)
        row.addWidget(self.remove_slot_button)
        row.addStretch(1)
        self.add_slot_button.clicked.connect(self._add_slot)
        self.remove_slot_button.clicked.connect(self._remove_slot)
        self.prompt_details.add(slot_actions)
        self._build_model_controls(card)
        self.prompt_card = card
        self.form_layout.addWidget(card)

    def _build_model_controls(self, card: SectionCard) -> None:
        selectors = ResponsiveGrid(min_column_width=148, column_gap=SPACE.sm)
        self.model_combo = QComboBox()
        for model in MODELS:
            self.model_combo.addItem(model.label.split(" example", 1)[0], model.key)
        self.model_combo.setAccessibleName("Selected model")
        guard_wheel(self.model_combo, self._wheel_guard)
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        selectors.add(stacked_label("Model fixture", self.model_combo))
        self.profile_combo = QComboBox()
        for profile in PROFILES:
            self.profile_combo.addItem(profile.removesuffix(" (fixture)"), profile)
        self.profile_combo.setAccessibleName("Settings source")
        guard_wheel(self.profile_combo, self._wheel_guard)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.profile_combo.setToolTip("Learning-informed uses an invented recommendation.")
        selectors.add(stacked_label("Profile fixture", self.profile_combo))
        card.add(selectors)
        card.add(self.prompt_details)
        self.change_detail = QLabel("No model/profile changes to review.")
        self.change_detail.setProperty("role", "muted")
        self.change_detail.setWordWrap(True)
        log = Disclosure("Change log")
        self.change_log = log
        log.toggle.toggled.connect(self._reveal_disclosure)
        log.add(self.change_detail)
        self.change_log_view = FormTextEdit()
        self.change_log_view.setReadOnly(True)
        self.change_log_view.setMinimumHeight(110)
        self.change_log_view.setMaximumHeight(160)
        self.change_log_view.setAccessibleName("Change log")
        log.add(self.change_log_view)
        card.add(log)

    def _make_editor(self, name: str) -> QWidget:
        if name in ("sampler", "scheduler"):
            editor = QComboBox()
            editor.currentIndexChanged.connect(
                lambda index, field=name, combo=editor: self._setting_changed(
                    field, combo.itemData(index)
                )
            )
        elif name == "cfg":
            editor = QDoubleSpinBox()
            low, high = SETTING_RANGES[name]
            editor.setRange(low, high)
            editor.setDecimals(1)
            editor.setSingleStep(0.5)
            editor.valueChanged.connect(
                lambda value, field=name: self._setting_changed(field, value)
            )
        else:
            editor = QSpinBox()
            low, high = SETTING_RANGES[name]
            editor.setRange(int(low), int(high))
            editor.setSingleStep(64 if name in ("width", "height") else 1)
            if name == "seed":
                editor.setSpecialValueText("Random")
            editor.valueChanged.connect(
                lambda value, field=name: self._setting_changed(field, value)
            )
        guard_wheel(editor, self._wheel_guard)
        editor.setAccessibleName(SETTING_LABELS[name])
        return editor

    def _build_settings_section(self) -> None:
        card = self._card("Generation settings")
        self.size_combo = QComboBox()
        self.size_combo.setAccessibleName("Size preset")
        guard_wheel(self.size_combo, self._wheel_guard)
        self.size_combo.currentIndexChanged.connect(self._size_preset_changed)
        card.add(stacked_label("Size preset", self.size_combo))
        self.reset_unlocked_button = QPushButton("Reset unlocked settings")
        self.reset_unlocked_button.setToolTip(
            "Return unlocked values to the fixture recommendation."
        )
        self.reset_unlocked_button.clicked.connect(self._reset_unlocked)

        self.setting_inputs: dict[str, QWidget] = {}
        self.lock_inputs: dict[str, QCheckBox] = {}
        self.setting_fields: dict[str, SettingField] = {}

        def make_grid(names: tuple[str, ...], min_width: int) -> ResponsiveGrid:
            grid = ResponsiveGrid(min_column_width=min_width, column_gap=SPACE.sm)
            for name in names:
                editor = self._make_editor(name)
                field = SettingField(name, SETTING_LABELS[name], editor)
                field.lockToggled.connect(
                    lambda checked, field_name=name: self._lock_changed(field_name, checked)
                )
                field.resetRequested.connect(
                    lambda field_name=name: self._reset_setting(field_name)
                )
                self.setting_inputs[name] = editor
                self.lock_inputs[name] = field.lock
                self.setting_fields[name] = field
                grid.add(field)
            return grid

        self.settings_grid = make_grid(BASIC_SETTINGS, 139)
        card.add(self.settings_grid)
        self.advanced_settings = Disclosure(
            "Advanced settings",
        )
        self.advanced_settings.toggle.toggled.connect(self._reveal_disclosure)
        self.advanced_grid = make_grid(ADVANCED_SETTINGS, 218)
        self.advanced_settings.add(self.advanced_grid)
        card.add(self.reset_unlocked_button)
        card.add(self.advanced_settings)
        self.settings_card = card

    def _build_advanced_section(self) -> None:
        card = self._card("Additional prompt channels")
        self.advanced_summary = QLabel(
            "Global: off · ADetailer: off · LoRA: none · Embeddings: none"
        )
        self.advanced_summary.setProperty("role", "muted")
        self.advanced_summary.setWordWrap(True)
        card.add(self.advanced_summary)
        advanced = Disclosure("Advanced prompt channels")
        advanced.toggle.toggled.connect(self._reveal_disclosure)
        self.global_text = FormTextEdit()
        self.global_text.setFixedHeight(62)
        self.global_text.setAccessibleName("Global prompt")
        self.global_text.textChanged.connect(
            lambda: self._set_text("global_prompt", self.global_text.toPlainText())
        )
        advanced.add(stacked_label("Global prompt", self.global_text))
        self.adetailer_check = QCheckBox("Enable ADetailer (demo only)")
        self.adetailer_check.toggled.connect(self._adetailer_changed)
        advanced.add(self.adetailer_check)
        self.adetailer_text = FormTextEdit()
        self.adetailer_text.setFixedHeight(62)
        self.adetailer_text.setAccessibleName("ADetailer prompt")
        self.adetailer_text.textChanged.connect(
            lambda: self._set_text("adetailer_prompt", self.adetailer_text.toPlainText())
        )
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
        self.channels_disclosure = advanced
        self.advanced_card = card

    def _build_review_panel(self, split: QSplitter) -> None:
        self.review_scroll = _scroll_area()
        self.review_scroll.setMinimumWidth(247)
        self.review = QFrame()
        self.review.setProperty("role", "card")
        self.review_layout = QVBoxLayout(self.review)
        self.review_layout.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        self.review_layout.setSpacing(SPACE.sm)
        review_title = QLabel("Review & results")
        review_title.setProperty("role", "section")
        self.review_layout.addWidget(review_title)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setAccessibleName("Effective settings summary")
        self.review_layout.addWidget(self.summary_label)
        self.review_state = QLabel("Preview state: Not built")
        self.review_state.setWordWrap(True)
        self.review_layout.addWidget(self.review_state)
        self.stale_label = QLabel("")
        self.stale_label.setProperty("role", "muted")
        self.stale_label.setProperty("level", "warning")
        self.stale_label.setWordWrap(True)
        self.review_layout.addWidget(self.stale_label)
        self.issue_list = IssueList()
        self.review_layout.addWidget(self.issue_list)
        review_guide = QLabel(
            "Preview is a display-only snapshot. It is NOT the compiler's NJR Preview and grants no execution authority."
        )
        review_guide.setProperty("role", "muted")
        review_guide.setWordWrap(True)
        self.review_layout.addWidget(review_guide)
        self.preview_text = FormTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(106)
        self.preview_text.setMaximumHeight(188)
        self.preview_text.setAccessibleName("Mock preview and effective setting summary")
        self.review_layout.addWidget(self.preview_text)
        self.result_card = SectionCard("Mock result", "No real image generated, no job ID issued.")
        self.result_text = QLabel(
            "This panel will display the simulated admission acknowledgement."
        )
        self.result_text.setWordWrap(True)
        self.result_card.add(self.result_text)
        self.result_gallery = ResultGallery()
        self.result_card.add(self.result_gallery)
        self.edit_result = QPushButton("Edit linked fixture")
        self.edit_result.setToolTip(
            "Open the linked Ridge study fixture from the mock Create gallery."
        )
        self.edit_result.hide()
        self.edit_result.clicked.connect(lambda: self.editRequested.emit(CREATE_SOURCE))
        self.result_card.add(self.edit_result)
        self.review_layout.addWidget(self.result_card)
        self.review_scroll.setWidget(self.review)
        split.addWidget(self.review_scroll)

    # --------------------------------------------------------------- handlers
    def _set_text(self, field: str, value: str) -> None:
        if self._updating:
            return
        self.session.set_text(field, value)
        self._sync_view()

    def _setting_changed(self, field: str, value: object) -> None:
        if self._updating or value is None:
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

    def _source_changed(self, index: int) -> None:
        if self._updating or index < 0:
            return
        self.session.select_source(self.source_combo.itemData(index))
        self._sync_view()

    def _model_changed(self, index: int) -> None:
        if self._updating or index < 0:
            return
        self.session.switch_model(self.model_combo.itemData(index))
        self._sync_view()

    def _profile_changed(self, index: int) -> None:
        if self._updating:
            return
        self.session.set_profile_source(self.profile_combo.itemData(index))
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
            self._sync_view()
            self.banner.set_message(
                "DUPLICATE SLOT", "Slot names must be unique; the edit was not applied.", "blocked"
            )
            return
        try:
            self.session.replace_slots(new_slots)
        except ValueError as exc:
            self._sync_view()
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
            self.banner.set_message(
                "SELECT SLOT", "Select a row before removing a slot from the mock draft.", "warning"
            )
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
        if self.session.demo_receipt is not None:
            self._show_result()
            return
        self._show_review_start()
        if preview.errors:
            self.banner.set_message("MOCK PREVIEW REFUSED", preview.errors[0], "blocked")
        else:
            self.banner.set_message(
                "MOCK PREVIEW READY",
                "Review the snapshot before simulated admission.",
                "success",
            )

    def _show_review_start(self) -> None:
        if self.review_scroll.isVisible():
            self.review_scroll.verticalScrollBar().setValue(0)
        else:
            reveal(self.form_scroll, self.summary_label)

    def _simulate_admission(self) -> None:
        if self.session.demo_receipt is not None:
            return
        try:
            receipt = self.session.simulate_admission()
        except RuntimeError as exc:
            self.banner.set_message("SIMULATION REFUSED", str(exc), "blocked")
            return
        self._sync_view()
        self.banner.set_message(
            "SIMULATED ONLY", receipt.message.removeprefix("DEMO ONLY: "), "success"
        )
        self._show_result()

    def _show_result(self) -> None:
        """Bring the simulated result into view: it is the last block of whichever column holds it.

        The tile grid reflows after its width is known, which grows the content once more, so the
        view stays pinned to the bottom while the scroll range settles. Any user scroll releases it.
        """
        scroll = self.review_scroll if self.review_scroll.isVisible() else self.form_scroll
        bar = scroll.verticalScrollBar()

        def pin(*_range: int) -> None:
            try:
                if self.session.demo_receipt is not None:
                    bar.setValue(bar.maximum())
            except RuntimeError:  # the window was closed first
                pass

        def release(*_action: int) -> None:
            try:
                bar.rangeChanged.disconnect(pin)
                bar.actionTriggered.disconnect(release)
            except (RuntimeError, TypeError):  # already released, or the window was closed
                pass

        bar.rangeChanged.connect(pin)
        bar.actionTriggered.connect(release)  # only user input triggers actions
        QTimer.singleShot(0, self, pin)
        QTimer.singleShot(500, self, release)

    def _reset(self) -> None:
        # Undoable, so no modal confirmation is needed (and nothing can hang a test run).
        self.session.reset()
        self._sync_view()
        self.banner.set_message(
            "DEMO RESET",
            "The local mock draft has been reset; use Undo to restore it. Nothing was persisted.",
            "warning",
        )

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
        index = next(
            (i for i in range(self.size_combo.count()) if self.size_combo.itemData(i) == wanted),
            self.size_combo.count() - 1,
        )
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
            self.source_combo.setCurrentIndex(
                next(
                    i
                    for i in range(self.source_combo.count())
                    if self.source_combo.itemData(i) == d.source_key
                )
            )
            self.model_combo.setCurrentIndex(
                next(
                    i
                    for i in range(self.model_combo.count())
                    if self.model_combo.itemData(i) == d.model_key
                )
            )
            self.profile_combo.setCurrentIndex(self.profile_combo.findData(d.profile_source))
            self._refresh_size_presets()
            recommended = self.session.recommended
            for name, widget in self.setting_inputs.items():
                val = getattr(d.settings, name)
                if isinstance(widget, QComboBox):
                    fixture = MODEL_BY_KEY[d.model_key]
                    supported = fixture.samplers if name == "sampler" else fixture.schedulers
                    options = list(supported)
                    if val not in supported:
                        options.append(val)
                    if options != [widget.itemData(i) for i in range(widget.count())]:
                        widget.clear()
                        for option in options:
                            label = option if option in supported else f"{option} (unsupported)"
                            widget.addItem(label, option)
                    widget.setCurrentIndex(widget.findData(val))
                elif widget.value() != val:
                    widget.setValue(val)
                self.setting_fields[name].set_state(
                    locked=name in d.locked_fields,
                    differs=val != getattr(recommended, name),
                    recommended=format_setting(name, getattr(recommended, name)),
                    origin=self.session.setting_origin(name),
                )
            self.reset_unlocked_button.setEnabled(
                any(
                    self.session.differs_from_recommended(n)
                    for n in SETTING_FIELDS
                    if n not in d.locked_fields
                )
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
            resolved, unresolved = expand_prompt(d.prompt, d.slots)
            if self.resolved_text.toPlainText() != resolved:
                self.resolved_text.setPlainText(resolved)
            used = len(referenced_slots(d.prompt) & set(d.slots))
            self.prompt_meta.setText(
                f"{words} words · {used} of {len(d.slots)} slots used"
                + (
                    f" · unresolved: {', '.join('{' + n + '}' for n in unresolved)}"
                    if unresolved
                    else ""
                )
            )
            log = self.session.change_log
            self.change_detail.setText(
                "\n".join(self.session.change_notes) or "No changes to review yet."
            )
            material_changes = [
                note
                for note in self.session.change_notes
                if note.startswith(("Suggested ", "Preserved ", "Negative prompt is unsupported"))
            ]
            self.change_log.set_title(
                f"Change log · {len(material_changes)} changes"
                if material_changes
                else "Change log"
            )
            self.change_log_view.setPlainText(
                "\n".join(f"r{rev} · {note}" for rev, note in reversed(log))
            )
            self.prompt_details.set_summary(
                " · ".join(
                    note
                    for enabled, note in (
                        (bool(d.negative.strip()), "Negative set"),
                        (bool(d.slots), f"{len(d.slots)} slots"),
                    )
                    if enabled
                )
            )
            self.advanced_summary.setText(
                f"Global: {'set' if d.global_prompt else 'off'} · ADetailer: {'on' if d.adetailer_enabled else 'off'} · "
                f"LoRA: {'noted' if d.loras else 'none'} · Embeddings: {'noted' if d.embeddings else 'none'}"
            )
            hidden_diffs = [
                n for n in ADVANCED_SETTINGS if self.session.differs_from_recommended(n)
            ]
            self.advanced_settings.set_summary(
                f"{d.settings.sampler} / {d.settings.scheduler} · {d.settings.width} × {d.settings.height}"
                + (
                    f" · {len(hidden_diffs)} differ from recommended"
                    if hidden_diffs
                    else " · all as recommended"
                )
            )
            model = next(m for m in MODELS if m.key == d.model_key)
            overrides = sorted(d.manual_fields)
            locks = ", ".join(sorted(d.locked_fields)) if d.locked_fields else "none"
            self.summary_label.setText(
                f"Source: {self.session.source_label}\n{model.label} · {d.profile_source}\n"
                f"{d.settings.width} × {d.settings.height} · {d.settings.steps} steps · CFG {d.settings.cfg:g} · "
                f"seed {format_setting('seed', d.settings.seed)} · batch {d.settings.batch}\n"
                f"Overrides: {', '.join(overrides) if overrides else 'none'} · Locks: {locks}"
            )
            stale = self.session.stale_reasons()
            self.stale_label.setText(
                "Stale because the draft changed: "
                + ", ".join(name.removeprefix("settings.") for name in stale)
                if stale
                else ""
            )
            self.stale_label.setVisible(bool(stale))
            self.result_card.setVisible(self.session.demo_receipt is not None)
            self.result_gallery.set_tiles(
                self.session.demo_receipt.tiles if self.session.demo_receipt else ()
            )
            self.edit_result.setVisible(self.session.demo_receipt is not None)
            preview = self.session.preview
            if preview is None:
                self.preview_text.setPlainText(
                    "Not previewed yet.\n\nEdit the mock draft, then choose Build mock preview.\n\nThere is no real model or backend in this assessment."
                )
                self.review_state.setText("Preview state: Not built")
                self.preview_chip.set_status("NOT BUILT", "info")

            else:
                if self.preview_text.toPlainText() != preview.text:
                    self.preview_text.setPlainText(preview.text)
                current = self.session.is_preview_current
                state = "STALE" if not current else "BLOCKED" if preview.errors else "CURRENT"
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
            issues = self.session.validation()
            if issues != self._draft_issues:
                self._draft_issues = issues
                self.issue_list.set_issues(*issues, empty="No mock issues found")
            if self.session.demo_receipt is not None:
                self.preview_chip.set_status("SIMULATED · RECEIPT", "success")
            self.admit_button.setEnabled(self.session.can_simulate_admission)
            if self.session.demo_receipt is None:
                if issues[0]:
                    self.banner.set_message("DRAFT ISSUE", issues[0][0], "blocked")
                elif stale:
                    self.banner.set_message(
                        "STALE PREVIEW", "Build Preview again to review changes.", "warning"
                    )
                else:
                    self.banner.set_message(
                        "DEMO ONLY", "Models, profiles, Preview and results are mock fixtures."
                    )
            self.undo_button.setEnabled(self.session.can_undo)
            self.redo_button.setEnabled(self.session.can_redo)
            warning_count = len(issues[1])
            self.actions.status.setText(
                f"Mock draft · r{self.session.revision}"
                + (f" · {warning_count} warning(s)" if warning_count else "")
            )
            self.actions.status.setToolTip(
                "Mock only: no production queue, job or image is involved."
            )
            if self.session.demo_receipt:
                self.result_text.setText(
                    f"Draft r{self.session.demo_receipt.revision} · {model.label} · {d.profile_source}"
                    f"\n\n{self.session.demo_receipt.message}"
                )
            else:
                self.result_text.setText("No simulated receipt. No image has been created.")
        finally:
            self._updating = False
        self.stateSynced.emit()
