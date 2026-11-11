"""Edit workspace. Widgets render and modify the isolated EditSession."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .components import (
    ActionStrip,
    Disclosure,
    NoticeBanner,
    NoWheelUnlessFocused,
    StatusChip,
    guard_wheel,
    stacked_label,
)
from .edit_components import CompareViewer, ImageCanvas, SourcePicker, ZoomControls, fixture_image
from .edit_components import illustration as candidate_illustration
from .edit_domain import (
    PROFILES,
    REGIONS,
    Availability,
    Candidate,
    EditPreview,
    EditRefused,
    EditSession,
    Mode,
    Replacement,
    evaluate,
    require_available,
    source_for,
    suggest_mask,
)
from .tokens import SPACE


def _label(text: str = "", role: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("role", role)
    label.setWordWrap(True)
    return label


def _scroll() -> tuple[QScrollArea, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
    layout.setSpacing(SPACE.sm)
    scroll.setWidget(body)
    return scroll, layout


def _combo(name: str, items=()) -> QComboBox:
    combo = QComboBox()
    combo.setAccessibleName(name)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(10)
    combo.addItems(list(items))
    return combo


def _spin(name: str, minimum: int, maximum: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setAccessibleName(name)
    spin.setKeyboardTracking(False)
    return spin


def _dimensions(size: tuple[int, int] | None) -> str:
    return f"{size[0]} × {size[1]} px" if size else "Unavailable"


def _effective(preview: EditPreview) -> dict[str, str]:
    draft = preview.draft
    region = draft.region
    source = source_for(draft.source_key)
    settings = {
        "Mode": draft.mode.value,
        "Profile fixture": draft.profile,
        "Region": region.name,
        "Prompt": region.prompt,
        "Output": _dimensions(preview.output_size),
    }
    if source.negative_supported:
        settings["Negative prompt"] = region.negative or "None"
    if draft.mode != Mode.EXTEND:
        settings["Edit strength"] = f"{region.strength}%"
    if draft.mode == Mode.MASKED:
        settings["Mask coverage"] = f"{region.mask.count(255):,} source pixels"
        settings["Feather illustration"] = f"{region.feather} px"
    if draft.mode == Mode.EXTEND:
        geometry = draft.geometry
        settings["Margins L/T/R/B"] = (
            f"{geometry.left} / {geometry.top} / {geometry.right} / {geometry.bottom} px"
        )
    return settings


def _setting_changes(before: EditPreview, after: EditPreview) -> list[str]:
    old, new = _effective(before), _effective(after)
    changes = [
        f"{key} · {old.get(key, 'Excluded')} → {new.get(key, 'Excluded')}"
        for key in dict.fromkeys([*old, *new])
        if old.get(key) != new.get(key)
    ]
    if (
        before.draft.mode == after.draft.mode == Mode.MASKED
        and before.draft.region.mask != after.draft.region.mask
    ):
        changes.append("Mask pixels changed.")
    return changes


class EditView(QWidget):
    """Canvas-first editor with a hideable inspector and a separate comparison surface."""

    motionRequested = Signal(str)

    def __init__(self, layout_design: str = "editor"):
        super().__init__()
        self.session = EditSession()
        self.layout_design = layout_design
        self._wheel_guard = NoWheelUnlessFocused(self)
        self._suggestion: tuple[int, bytes] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.sm, 0, 0, 0)
        root.setSpacing(SPACE.sm)
        heading = QHBoxLayout()
        heading.addWidget(_label("Edit & Improve", "heading"), 1)
        self.inspector_toggle = QPushButton("Inspector")
        self.inspector_toggle.setCheckable(True)
        self.inspector_toggle.setChecked(True)
        self.picker = SourcePicker()
        self.mode = _combo("Editing mode", Mode)
        if layout_design == "editor":
            heading.addWidget(self.picker, 2)
            heading.addWidget(self.mode)
        heading.addWidget(self.inspector_toggle)
        root.addLayout(heading)
        self.banner = NoticeBanner()
        self.banner.hide()
        root.addWidget(self.banner)

        self.body = QSplitter(Qt.Orientation.Horizontal)
        self.body.setChildrenCollapsible(False)
        self.body.setAccessibleName("Edit workspace panels")
        root.addWidget(self.body, 1)
        if layout_design == "inspector":
            rail = QWidget()
            rail.setMaximumWidth(220)
            source_layout = QVBoxLayout(rail)
            source_layout.setContentsMargins(0, 0, SPACE.sm, 0)
            source_layout.addWidget(stacked_label("Source fixture", self.picker))
            source_layout.addWidget(stacked_label("Editing mode", self.mode))
            source_layout.addStretch(1)
            self.body.addWidget(rail)
        self.stage = QStackedWidget()
        self._build_canvas()
        self.compare = CompareViewer()
        self.stage.addWidget(self.compare)
        self.body.addWidget(self.stage)

        self.inspector = QTabWidget()
        self.inspector.setAccessibleName("Edit inspector")
        self.inspector.setMinimumWidth(254)
        self.inspector.setMaximumWidth(385)
        self._build_settings()
        self._build_review()
        self.body.addWidget(self.inspector)
        self.body.setStretchFactor(self.body.indexOf(self.stage), 1)
        self.inspector_toggle.toggled.connect(self.inspector.setVisible)

        self.actions = ActionStrip()
        self.preview_button = self.actions.add_action("Build Preview")
        self.admit_button = self.actions.add_action("Simulate Admission", primary=True)
        self.compare_button = self.actions.add_action("Compare")
        root.addWidget(self.actions)
        self._connect_controls()
        self.sync()

    def _build_canvas(self) -> None:
        editor = QWidget()
        layout = QVBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.sm)
        self.canvas = ImageCanvas()
        self.zoom = ZoomControls(self.canvas)
        layout.addWidget(self.zoom)
        self.mask_toolbar = QWidget()
        toolbar = QHBoxLayout(self.mask_toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(SPACE.xs)
        self.tool = _combo("Canvas tool", ("Brush", "Erase", "Pan"))
        self.tool.setMinimumContentsLength(5)
        self.brush = _spin("Brush radius in source pixels", 1, 64, " px")
        self.brush.setValue(self.canvas.brush_radius)
        self.clear_mask = QPushButton("Clear Mask")
        self.undo = QPushButton("Undo")
        self.redo = QPushButton("Redo")
        toolbar.addWidget(self.tool)
        toolbar.addWidget(_label("Radius"))
        toolbar.addWidget(self.brush)
        toolbar.addStretch(1)
        for button in (self.undo, self.redo, self.clear_mask):
            toolbar.addWidget(button)
        layout.addWidget(self.mask_toolbar)

        self.suggestion_controls = QWidget()
        suggestions = QHBoxLayout(self.suggestion_controls)
        suggestions.setContentsMargins(0, 0, 0, 0)
        self.accept_suggestion = QPushButton("Accept suggestion")
        self.reject_suggestion = QPushButton("Reject")
        suggestions.addWidget(_label("Simulated suggestion · inspect or paint"), 1)
        suggestions.addWidget(self.accept_suggestion)
        suggestions.addWidget(self.reject_suggestion)
        layout.addWidget(self.suggestion_controls)
        self.image_note = _label()
        layout.addWidget(self.image_note)
        layout.addWidget(self.canvas, 1)
        readouts = QHBoxLayout()
        self.coverage = _label()
        self.coordinates = QLabel("Outside image")
        self.coordinates.setMinimumWidth(
            self.coordinates.fontMetrics().horizontalAdvance("x 639 · y 399")
        )
        self.zoom_readout = QLabel("100%")
        self.zoom_readout.setMinimumWidth(
            self.zoom_readout.fontMetrics().horizontalAdvance("1600%")
        )
        readouts.addWidget(self.coverage, 1)
        readouts.addWidget(self.coordinates)
        readouts.addWidget(self.zoom_readout)
        layout.addLayout(readouts)
        self.stage.addWidget(editor)

    def _build_settings(self) -> None:
        self.settings_scroll, form = _scroll()
        self.inspector.addTab(self.settings_scroll, "Settings")
        self.region = _combo("Named edit region", REGIONS)
        self.prompt = QLineEdit()
        self.prompt.setAccessibleName("Edit prompt")
        self.negative = QLineEdit()
        self.negative.setAccessibleName("Negative prompt")
        self.negative_field = stacked_label("Negative prompt", self.negative)
        self.profile = _combo("Model profile fixture", PROFILES)
        self.compatibility = _label()
        self.source_info = _label()
        self.region_scope = _label("One region per simulation. Multi-region execution is proposed.")
        self.advanced = Disclosure("Advanced settings")
        self.strength = _spin("Edit strength", 0, 100, "%")
        self.feather = _spin("Feather illustration radius", 0, 32, " px")
        self.strength_field = stacked_label("Edit strength", self.strength)
        self.feather_field = stacked_label("Feather illustration", self.feather)
        self.advanced.add(self.strength_field)
        self.advanced.add(self.feather_field)
        self.assist = QPushButton("Try simulated suggestion")
        self.advanced.add(self.assist)
        for widget in (
            self.source_info,
            stacked_label("Model profile fixture", self.profile),
            self.compatibility,
            stacked_label("Region", self.region),
            self.region_scope,
            stacked_label("Edit prompt", self.prompt),
            self.negative_field,
        ):
            form.addWidget(widget)
        self.margin_panel = QWidget()
        margins = QGridLayout(self.margin_panel)
        margins.setContentsMargins(0, 0, 0, 0)
        self.margins = {}
        for i, name in enumerate(("left", "top", "right", "bottom")):
            spin = _spin(f"{name.capitalize()} extension", 0, 512, " px")
            self.margins[name] = spin
            margins.addWidget(stacked_label(name.capitalize(), spin), i // 2, i % 2)
            guard_wheel(spin, self._wheel_guard)
        form.addWidget(self.margin_panel)
        form.addWidget(self.advanced)
        form.addStretch(1)
        for editor in (
            self.region,
            self.profile,
            self.strength,
            self.feather,
            self.brush,
            self.tool,
            self.picker,
            self.mode,
        ):
            guard_wheel(editor, self._wheel_guard)

    def _build_review(self) -> None:
        self.review_scroll, review = _scroll()
        self.inspector.addTab(self.review_scroll, "Preview")
        self.status = StatusChip("Not built", "info")
        review.addWidget(self.status)
        self.preview_summary = _label()
        review.addWidget(self.preview_summary)
        self.recorded_parent = QPushButton("Inspect recorded source parent")
        review.addWidget(self.recorded_parent)
        self.animate = QPushButton("Animate in Motion")
        self.animate.setToolTip(
            "Hand this source to Motion & Video as a Quick Clip draft. Nothing is queued."
        )
        review.addWidget(self.animate)
        review.addStretch(1)
        self.candidate_scroll, candidates = _scroll()
        self.inspector.addTab(self.candidate_scroll, "Candidates")
        self.candidate_picker = _combo("Recorded mock candidate")
        self.peer_picker = _combo("Compare candidate against")
        candidates.addWidget(stacked_label("Recorded candidate", self.candidate_picker))
        candidates.addWidget(stacked_label("Compare with", self.peer_picker))
        self.baseline = QPushButton("Set Working Baseline")
        candidates.addWidget(self.baseline)
        self.baseline_note = _label("Preferred / Final has no selection in this prototype.")
        candidates.addWidget(self.baseline_note)
        self.candidate_summary = _label()
        candidates.addWidget(self.candidate_summary)
        candidates.addStretch(1)
        guard_wheel(self.candidate_picker, self._wheel_guard)
        guard_wheel(self.peer_picker, self._wheel_guard)

    def _connect_controls(self) -> None:
        self.picker.activated.connect(self._pick)
        self.mode.currentIndexChanged.connect(lambda i: self._change(mode=tuple(Mode)[i]))
        self.profile.currentTextChanged.connect(lambda text: self._change(profile=text))
        self.region.currentIndexChanged.connect(lambda i: self._change(active_region=i))
        self.prompt.textEdited.connect(lambda text: self._change_region(prompt=text))
        self.negative.textEdited.connect(lambda text: self._change_region(negative=text))
        self.strength.valueChanged.connect(lambda value: self._change_region(strength=value))
        self.feather.valueChanged.connect(lambda value: self._change_region(feather=value))
        for name, spin in self.margins.items():
            spin.valueChanged.connect(lambda value, edge=name: self._set_margin(edge, value))
        self.tool.currentTextChanged.connect(self._set_tool)
        self.brush.valueChanged.connect(self._set_brush)
        self.canvas.maskCommitted.connect(self._commit_mask)
        self.canvas.pixelChanged.connect(self.coordinates.setText)
        self.canvas.zoomChanged.connect(self.zoom_readout.setText)
        self.clear_mask.clicked.connect(self._clear_mask)
        self.assist.clicked.connect(self._suggest)
        self.accept_suggestion.clicked.connect(self._accept_suggestion)
        self.reject_suggestion.clicked.connect(self._discard_suggestion)
        self.undo.clicked.connect(self._undo)
        self.redo.clicked.connect(self._redo)
        self.preview_button.clicked.connect(self._preview)
        self.admit_button.clicked.connect(self._admit)
        self.compare_button.clicked.connect(self._toggle_compare)
        self.recorded_parent.clicked.connect(self._inspect_parent)
        self.animate.clicked.connect(self._animate)
        self.candidate_picker.currentIndexChanged.connect(self._candidate_changed)
        self.peer_picker.currentIndexChanged.connect(self._show_candidate)
        self.baseline.clicked.connect(self._set_baseline)
        for name, sequence, callback in (
            ("Undo Edit", "Alt+Z", self._undo),
            ("Redo Edit", "Alt+Y", self._redo),
            ("Build Edit Preview", "Ctrl+Return", self._preview),
        ):
            action = QAction(name, self)
            action.setShortcut(sequence)
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def _animate(self) -> None:
        draft = self.session.draft
        if draft is None:
            self._warn("Nothing to animate", "Select a source image first.")
            return
        self.motionRequested.emit(draft.source_key)

    def _warn(self, title: str, message: str) -> None:
        self.banner.set_message(title, message, "warning")
        self.banner.show()

    def _pick(self, index: int) -> None:
        if key := self.picker.itemData(index):
            self.select_source(key)
        self.sync()

    def select_source(self, key: str) -> bool:
        """Return whether navigation should go to Edit. Keep opens the existing draft."""
        previous = self.session.draft
        try:
            image = fixture_image(key) if previous is None or previous.source_key != key else None
            selected = self.session.select(key)
        except EditRefused as exc:
            self._warn("Source refused", str(exc))
            return False
        if not selected:
            choice = self._confirm_replacement(key)
            if choice != Replacement.REPLACE:
                return choice == Replacement.KEEP
            self.session.select(key, choice)
        if image is not None:
            self.canvas.set_image(image)
        self.banner.hide()
        self._show_editor()
        self.sync()
        return True

    def adopt_session_source(self) -> None:
        """Show the draft a Library placement already selected in ``session`` (consent was given there)."""
        draft = self.session.draft
        if draft is None:
            return
        self.canvas.set_image(fixture_image(draft.source_key))
        self.banner.hide()
        self._show_editor()
        self.sync()

    def _confirm_replacement(self, key: str) -> Replacement:
        box = QMessageBox(self)
        box.setWindowTitle("Replace edit draft?")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"Open {key}? The current edit draft has changes.")
        box.setInformativeText(
            "Keep returns to your current draft. Recorded candidates remain available."
        )
        keep = box.addButton(Replacement.KEEP, QMessageBox.ButtonRole.ActionRole)
        cancel = box.addButton(Replacement.CANCEL, QMessageBox.ButtonRole.RejectRole)
        replace_button = box.addButton(Replacement.REPLACE, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is replace_button:
            return Replacement.REPLACE
        if box.clickedButton() is keep:
            return Replacement.KEEP
        return Replacement.CANCEL

    def _change(self, **values) -> None:
        if self.session.draft:
            self.session.update(**values)
            self.sync()

    def _change_region(self, **values) -> None:
        if self.session.draft:
            self.session.update_region(**values)
            self.sync()

    def _set_margin(self, edge: str, value: int) -> None:
        if draft := self.session.draft:
            self._change(geometry=replace(draft.geometry, **{edge: value}))

    def _set_tool(self, tool: str) -> None:
        self.canvas.tool = tool

    def _set_brush(self, radius: int) -> None:
        self.canvas.brush_radius = radius

    def _commit_mask(self, revision: int, mask: bytes) -> None:
        if self._suggestion and self._suggestion[0] == revision:
            self._suggestion = (revision, mask)
            self.sync()
        elif self.session.commit_mask(revision, mask):
            self.sync()

    def _clear_mask(self) -> None:
        if self._suggestion:
            self._suggestion = (self.session.revision, bytes(len(self._suggestion[1])))
            self.sync()
        else:
            self._change_region(mask=b"")

    def _suggest(self) -> None:
        if draft := self.session.draft:
            try:
                mask = suggest_mask(draft.source_key)
            except EditRefused as exc:
                self._warn("Assisted suggestion", str(exc))
                return
            self._suggestion = (self.session.revision, mask)
            self.banner.hide()
            self.sync()

    def _accept_suggestion(self) -> None:
        if self._suggestion:
            revision, mask = self._suggestion
            self._suggestion = None
            self._commit_mask(revision, mask)

    def _discard_suggestion(self) -> None:
        self.canvas.cancel_gesture()
        self._suggestion = None
        self.sync()

    def _undo(self) -> None:
        if not self._suggestion:
            self.session.undo()
            self.sync()

    def _redo(self) -> None:
        if not self._suggestion:
            self.session.redo()
            self.sync()

    def _open_inspector(self, page: QScrollArea) -> None:
        self.inspector_toggle.setChecked(True)
        self.inspector.setCurrentWidget(page)

    def _preview(self) -> None:
        if self.session.draft is None or self._suggestion:
            return
        self.canvas.cancel_gesture()
        self.banner.hide()
        self.session.build_preview()
        self._open_inspector(self.review_scroll)
        self.sync()

    def _admit(self) -> None:
        if self._suggestion:
            return
        self.canvas.cancel_gesture()
        try:
            candidate = self.session.admit()
        except EditRefused as exc:
            self._warn("Admission refused", str(exc))
            return
        if self.candidate_picker.findData(candidate.key) == -1:
            self.candidate_picker.addItem(candidate.key, candidate.key)
        self.candidate_picker.setCurrentIndex(self.candidate_picker.findData(candidate.key))
        self._open_inspector(self.candidate_scroll)
        self._show_candidate()
        self.sync()

    def _candidate(self, key: str | None = None) -> Candidate | None:
        key = key or self.candidate_picker.currentData()
        return next(
            (candidate for candidate in self.session.candidates if candidate.key == key), None
        )

    def _candidate_changed(self) -> None:
        with QSignalBlocker(self.peer_picker):
            self.peer_picker.clear()
            self.peer_picker.addItem("Recorded source")
            candidate = self._candidate()
            if candidate:
                for peer in self.session.candidates:
                    if peer.key != candidate.key and peer.parent == candidate.parent:
                        self.peer_picker.addItem(peer.key, peer.key)
        if self.stage.currentWidget() == self.compare:
            self._show_candidate()
        self._sync_candidate()

    def _show_editor(self) -> None:
        self.stage.setCurrentIndex(0)
        self.compare_button.setText("Compare")
        self.inspector.setCurrentWidget(self.settings_scroll)

    def _toggle_compare(self) -> None:
        if self.stage.currentWidget() == self.compare:
            self._show_editor()
            self.sync()
        else:
            self._open_inspector(self.candidate_scroll)
            self._show_candidate()

    def _show_candidate(self) -> None:
        candidate = self._candidate()
        if candidate is None:
            return
        peer_key = self.peer_picker.currentData()
        peer = self._candidate(peer_key) if peer_key else None
        try:
            source = require_available(candidate.parent)
            if peer is None:
                left = fixture_image(source.key)
                left_label = f"Recorded direct source · {source.key}"
            else:
                left = candidate_illustration(peer)
                left_label = f"Mock candidate · {peer.key}"
            right = candidate_illustration(candidate)
        except EditRefused as exc:
            self.compare.set_pair(QImage(), QImage(), "Unavailable source", "Unavailable result")
            self._warn("Comparison refused", str(exc))
            return
        self.compare.set_pair(left, right, left_label, f"Illustrated result · {candidate.key}")
        self._show_comparison()
        self._sync_candidate()

    def _inspect_parent(self) -> None:
        draft = self.session.draft
        if draft is None:
            return
        source = source_for(draft.source_key)
        if not source.parent:
            return
        try:
            left = fixture_image(source.parent)
            right = fixture_image(source.key)
        except EditRefused as exc:
            self.compare.set_pair(QImage(), QImage(), "Unavailable parent", "Unavailable child")
            self._warn("Comparison refused", str(exc))
            return
        self.compare.set_pair(
            left,
            right,
            f"Verified fixture parent · {source.parent}",
            f"Fixture child · {source.key}",
        )
        self._show_comparison()

    def _show_comparison(self) -> None:
        self.stage.setCurrentWidget(self.compare)
        self.compare_button.setText("Back to Draft")
        self.compare_button.setEnabled(True)

    def _set_baseline(self) -> None:
        if candidate := self._candidate():
            self.session.set_baseline(candidate)
            self._sync_candidate()

    def _sync_candidate(self) -> None:
        candidate = self._candidate()
        self.candidate_picker.setEnabled(candidate is not None)
        self.peer_picker.setEnabled(self.peer_picker.count() > 1)
        self.baseline.setEnabled(candidate is not None)
        self.compare_button.setEnabled(
            candidate is not None or self.stage.currentWidget() == self.compare
        )
        if candidate is None:
            self.candidate_summary.setText("No mock candidates recorded.")
            return
        peer_key = self.peer_picker.currentData()
        peer = self._candidate(peer_key) if peer_key else None
        lines = [f"{candidate.key} ← {candidate.parent}", "Illustration only · no generated image."]
        if peer is None:
            lines.extend(f"{key} · {value}" for key, value in _effective(candidate.preview).items())
        else:
            lines.append(f"Effective settings compared with {peer.key}")
            lines.extend(
                _setting_changes(peer.preview, candidate.preview)
                or ["No effective settings changed."]
            )
        self.candidate_summary.setText("\n".join(lines))
        baseline = self.session.baselines.get(candidate.parent, "none")
        self.baseline_note.setText(f"Working Baseline · {baseline}\nPreferred / Final · none")

    def sync(self) -> None:
        draft = self.session.draft
        key = draft.source_key if draft else None
        if self._suggestion and self._suggestion[0] != self.session.revision:
            self._suggestion = None
        masked = draft is not None and draft.mode == Mode.MASKED
        extend = draft is not None and draft.mode == Mode.EXTEND
        self.mask_toolbar.setVisible(masked)
        self.margin_panel.setVisible(extend)
        self.strength_field.setVisible(not extend)
        self.advanced.setVisible(not extend)
        self.feather_field.setVisible(masked)
        self.assist.setVisible(masked)
        self.suggestion_controls.setVisible(self._suggestion is not None)
        self.settings_scroll.setEnabled(draft is not None)
        self.mode.setEnabled(draft is not None)
        with QSignalBlocker(self.picker):
            self.picker.setCurrentIndex(max(0, self.picker.findData(key)))
        if draft:
            self._sync_draft(draft)
        else:
            self.source_info.setText("Select an available image fixture to begin.")
            self.image_note.setText("No source selected")
            self.recorded_parent.hide()
        self._sync_preview()
        self._sync_candidate()

    def _sync_draft(self, draft) -> None:
        source = source_for(draft.source_key)
        region = draft.region
        masked = draft.mode == Mode.MASKED
        extend = draft.mode == Mode.EXTEND
        geometry = None
        target = source.size
        if extend:
            try:
                target = draft.geometry.output_size(source.size)
                geometry = draft.geometry
            except EditRefused:
                target = None
        with ExitStack() as stack:
            for editor in (
                self.mode,
                self.profile,
                self.region,
                self.prompt,
                self.negative,
                self.strength,
                self.feather,
                *self.margins.values(),
            ):
                stack.enter_context(QSignalBlocker(editor))
            self.mode.setCurrentText(draft.mode)
            self.profile.setCurrentText(draft.profile)
            self.region.setCurrentIndex(draft.active_region)
            if self.prompt.text() != region.prompt:
                self.prompt.setText(region.prompt)
            if self.negative.text() != region.negative:
                self.negative.setText(region.negative)
            self.strength.setValue(region.strength)
            self.feather.setValue(region.feather)
            for edge, spin in self.margins.items():
                spin.setValue(getattr(draft.geometry, edge))
        self.negative_field.setVisible(source.negative_supported)
        compatible = draft.mode in PROFILES[draft.profile]
        compatibility = (
            "Compatible fixture" if compatible else "Blocked · profile excludes this mode"
        )
        if not source.negative_supported:
            compatibility += " · negative prompt excluded"
        self.compatibility.setText(compatibility)
        lineage = (
            f"Recorded parent · {source.parent}" if source.parent else "Source ancestry unknown"
        )
        self.source_info.setText(f"{source.key} · {source.availability}\n{lineage}")
        self.recorded_parent.setVisible(source.parent is not None)
        size_note = f"Source {_dimensions(source.size)} · Output {_dimensions(target)}"
        if geometry:
            size_note += f" · Source at ({geometry.left}, {geometry.top})"
        if extend:
            size_note += "\nGeometry illustration · no generated output"
        self.image_note.setText(size_note)
        mask = self._suggestion[1] if self._suggestion else region.mask
        pixels = mask.count(255)
        percentage = pixels / (source.size[0] * source.size[1]) * 100
        self.coverage.setText(
            f"{'Suggestion' if self._suggestion else 'Mask'} · {pixels:,} px ({percentage:.1f}%)"
            if masked
            else "Pan image · Ctrl+wheel zoom"
        )
        self.canvas.tool = self.tool.currentText() if masked else "Pan"
        self.canvas.set_edit_state(
            self.session.revision,
            mask if masked else b"",
            region.feather if masked and self._suggestion is None else 0,
            geometry,
        )
        self.clear_mask.setEnabled(pixels > 0)
        self.advanced.set_summary(
            f"Strength {region.strength}% · Feather {region.feather} px"
            if masked
            else f"Strength {region.strength}%"
        )

    def _sync_preview(self) -> None:
        status = self.session.status
        levels = {"Not built": "info", "Blocked": "blocked", "Stale": "warning"}
        self.status.set_status(status, levels.get(status, "success"))
        self.actions.status.setText(status)
        pending = self._suggestion is not None
        self.preview_button.setEnabled(self.session.draft is not None and not pending)
        self.admit_button.setEnabled(status == "Current / ready" and not pending)
        self.undo.setEnabled(self.session.can_undo and not pending)
        self.redo.setEnabled(self.session.can_redo and not pending)
        draft = self.session.draft
        if draft is None:
            self.preview_summary.setText("Select a source and choose an edit mode.")
            return
        preview = self.session.preview
        lines = [f"Draft revision {self.session.revision} · {draft.source_key}"]
        if pending:
            lines.append("Accept or reject the simulated suggestion to continue.")
        if preview is None or status == "Stale":
            if preview:
                lines.append(f"Preview revision {preview.revision} is stale.")
                current = evaluate(draft, self.session.revision)
                lines.extend(_setting_changes(preview, current))
            lines.append("Build Preview to review effective settings.")
        else:
            lines.append(f"Preview revision {preview.revision} · {Availability.AVAILABLE}")
            lines.extend(preview.errors)
            lines.extend(f"{key} · {value}" for key, value in _effective(preview).items())
            if preview.draft.mode == Mode.MASKED:
                lines.append("Only the selected region is used. Feathering is illustrated.")
            if not source_for(draft.source_key).negative_supported:
                lines.append("Excluded · negative prompt unsupported by fixture.")
            if preview.draft.mode == Mode.EXTEND:
                lines.append("Placement is illustrative. No pixel-preservation result is measured.")
        self.preview_summary.setText("\n".join(lines))

    def restyle(self) -> None:
        self.canvas.restyle()
        self.compare.left.restyle()
        self.compare.right.restyle()
