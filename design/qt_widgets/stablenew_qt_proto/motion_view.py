"""Motion & Video workspace: Quick Clip, Storyboard and Movie Clips over one MotionSession.

Widgets render and modify the isolated mock session. Nothing here queues a job, calls a backend or
writes a file; every result is labelled as simulated.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .components import (
    Disclosure,
    FormTextEdit,
    NoticeBanner,
    NoWheelUnlessFocused,
    ResponsiveGrid,
    StatusChip,
    fit_segment,
    guard_wheel,
    stacked_label,
)
from .edit_domain import Replacement
from .motion_components import (
    GOVERNANCE_LEVEL,
    STATUS_LEVEL,
    AssemblyRow,
    ClipAssemblyList,
    ElidedLabel,
    MotionActionStrip,
    MotionSourceSelector,
    QualityRatingPanel,
    SequenceReadinessPanel,
    ShotCardData,
    ShotStrip,
    ShotTimeline,
    SimulatedClipViewer,
    TimelineRow,
    WorkflowCapabilityBadge,
)
from .motion_domain import (
    AUDIO,
    KIND_MOVIE,
    KIND_QUICK,
    KIND_STORY,
    MAX_SHOTS,
    MAX_VARIANTS,
    PROFILES,
    TRANSITIONS,
    MotionRefused,
    MotionSession,
    PlaybackPlan,
    PlaybackSegment,
    SeedIntent,
    StaleSave,
    Status,
    anchor_basis,
    diff_runs,
    effective_frames,
    effective_prompt,
    motion_for,
    offered_workflows,
    plan_for_clip,
    plan_for_movie,
    plan_for_run,
    resume_eligibility,
    usable_image,
    workflow_for,
)
from .tokens import SPACE

MODES = ((KIND_QUICK, "Quick Clip"), (KIND_STORY, "Storyboard"), (KIND_MOVIE, "Movie Clips"))
LAYOUTS = (("strip", "A · Shot strip"), ("timeline", "B · Timeline"))
SIMULATE_TEXT = {
    KIND_QUICK: "Simulate Clip",
    KIND_STORY: "Simulate Sequence",
    KIND_MOVIE: "Simulate Assembly",
}
COMPACT_HEIGHT = 470
VIEWER_MIN_HEIGHT = 200
WIDE_CONTEXT = 1000


def _label(text: str = "", role: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if role != "body":
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


def _combo(name: str) -> QComboBox:
    combo = QComboBox()
    combo.setAccessibleName(name)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(10)
    return combo


def _spin(name: str, low: int, high: int, suffix: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setSuffix(suffix)
    spin.setAccessibleName(name)
    spin.setKeyboardTracking(False)
    return spin


def _blocked(*widgets: QWidget) -> ExitStack:
    stack = ExitStack()
    for widget in widgets:
        stack.enter_context(QSignalBlocker(widget))
    return stack


@dataclass
class MotionUi:
    """View state that survives a theme rebuild. Authoring state lives in MotionSession."""

    mode: str = KIND_QUICK
    layout: str = "strip"
    shot: str | None = None


def wf_token(key: tuple[str, str]) -> str:
    """Qt item data round-trips tuples as lists; a string token keeps (id, version) exact."""
    return f"{key[0]}@{key[1]}"


def wf_key(token: str) -> tuple[str, str]:
    workflow_id, _, version = token.rpartition("@")
    return (workflow_id, version)


def seed_combo() -> QComboBox:
    combo = _combo("Seed intent")
    for text, kind in (
        ("Random (drawn at admission)", "random"),
        ("Inherit", "inherit"),
        ("Explicit", "explicit"),
    ):
        combo.addItem(text, kind)
    return combo


def _seed_intent(combo: QComboBox, spin: QSpinBox) -> SeedIntent:
    kind = combo.currentData()
    return SeedIntent(kind, spin.value() if kind == "explicit" else None)


def _load_seed(combo: QComboBox, spin: QSpinBox, intent: SeedIntent) -> None:
    combo.setCurrentIndex(max(0, combo.findData(intent.kind)))
    spin.setEnabled(intent.kind == "explicit")
    if intent.kind == "explicit" and intent.value is not None and intent.value <= spin.maximum():
        spin.setValue(intent.value)


# ------------------------------------------------------------------------------- Quick Clip
class QuickPanel(QSplitter):
    def __init__(self, owner: MotionView):
        super().__init__(Qt.Orientation.Horizontal)
        self.owner = owner
        self.setChildrenCollapsible(False)
        guard = owner._wheel_guard
        self.form_scroll, form = _scroll()
        self.source = MotionSourceSelector(owner.session.catalog)
        self.source_info = _label()
        self.accept_media = QPushButton("Accept Current Media")
        self.workflow = _combo("Workflow and version")
        for wf in offered_workflows():
            suffix = f" · {wf.governance.value}"
            self.workflow.addItem(wf.label + suffix, wf_token(wf.key))
        self.badge = WorkflowCapabilityBadge()
        self.prompt = FormTextEdit()
        self.prompt.setAccessibleName("Motion prompt")
        self.prompt.setPlaceholderText("Describe the motion, e.g. slow push toward the ridge")
        self.prompt.setFixedHeight(64)
        self.prompt_hint = _label()
        self.frames = _spin("Native frames", 1, 200, " f")
        self.frames_info = _label()
        self.use_default = QPushButton("Use workflow default frames")
        self.consent = QCheckBox("I consent to this experimental workflow for this submission only")
        self.consent_note = _label()
        self.advanced = Disclosure("Advanced controls")
        self.seed_kind, self.seed_value = seed_combo(), _spin("Explicit seed", 0, 2**31 - 1)
        self.variants = _spin("Variants", 1, MAX_VARIANTS)
        self.reference = MotionSourceSelector(owner.session.catalog, kind="motion-reference")
        self.bucket = _spin("Motion bucket", 0, 300)
        self.bucket.setSpecialValueText("Not set")
        self.bucket_hint = _label()
        self.drill = _combo("Fixture drill: fail variant")
        self.drill.addItem("No failure", None)
        for n in range(1, MAX_VARIANTS + 1):
            self.drill.addItem(f"Fail variant {n}", n)
        for widget in (
            stacked_label("Source image fixture", self.source),
            self.source_info,
            self.accept_media,
            stacked_label("Workflow and version", self.workflow),
            self.badge,
            stacked_label("Motion prompt", self.prompt),
            self.prompt_hint,
            stacked_label("Native frames", self.frames),
            self.frames_info,
            self.use_default,
            self.consent,
            self.consent_note,
            self.advanced,
        ):
            form.addWidget(widget)
        row = QHBoxLayout()
        row.addWidget(stacked_label("Seed intent", self.seed_kind))
        row.addWidget(stacked_label("Seed", self.seed_value))
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in (
            holder,
            stacked_label("Variants (independent candidates)", self.variants),
            stacked_label("Motion reference (optional)", self.reference),
            stacked_label("Motion bucket (SVD only)", self.bucket),
            self.bucket_hint,
            stacked_label("Fixture drill", self.drill),
        ):
            self.advanced.add(widget)
        form.addStretch(1)
        for editor in (self.source, self.workflow, self.frames, self.seed_kind, self.seed_value,
                       self.variants, self.reference, self.bucket, self.drill):  # fmt: skip
            guard_wheel(editor, guard)
        self.addWidget(self.form_scroll)

        self.review_scroll, review = _scroll()
        self.readiness = SequenceReadinessPanel()
        self.viewer = SimulatedClipViewer(owner.session.catalog)
        self.run_combo = _combo("Simulated run")
        self.clip_combo = _combo("Simulated clip or variant")
        self.compare_combo = _combo("Compare with run")
        self.compare_text = _label()
        self.rating = QualityRatingPanel()
        for widget in (
            self.readiness,
            self.viewer,
            stacked_label("Simulated run", self.run_combo),
            stacked_label("Clip / variant", self.clip_combo),
            stacked_label("Compare with", self.compare_combo),
            self.compare_text,
            self.rating,
        ):
            review.addWidget(widget)
        self.viewer.setMinimumHeight(250)
        review.addStretch(1)
        for combo in (self.run_combo, self.clip_combo, self.compare_combo):
            guard_wheel(combo, guard)
        self.addWidget(self.review_scroll)
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 1)
        self._connect()

    # ---------------------------------------------------------------------------- wiring
    def _connect(self) -> None:
        o = self.owner
        self.source.activated.connect(lambda _i: o.pick_source(self.source.key()))
        self.workflow.activated.connect(
            lambda _i: o.change_quick(workflow=wf_key(self.workflow.currentData()))
        )
        self.prompt.textChanged.connect(lambda: o.change_quick(prompt=self.prompt.toPlainText()))
        self.frames.valueChanged.connect(lambda v: o.change_quick(frames=v))
        self.use_default.clicked.connect(self._default_frames)
        self.accept_media.clicked.connect(lambda: o.accept_media(KIND_QUICK))
        self.consent.toggled.connect(lambda on: o.set_consent(KIND_QUICK, on))
        self.seed_kind.activated.connect(lambda _i: self._seed())
        self.seed_value.valueChanged.connect(lambda _v: self._seed())
        self.variants.valueChanged.connect(lambda v: o.change_quick(variants=v))
        self.reference.activated.connect(
            lambda _i: o.change_quick(reference_key=self.reference.key())
        )
        self.bucket.valueChanged.connect(lambda v: o.change_quick(motion_bucket=v or None))
        self.drill.activated.connect(
            lambda _i: o.change_quick(drill_fail_variant=self.drill.currentData())
        )
        self.run_combo.activated.connect(lambda _i: self.load_run())
        self.clip_combo.activated.connect(lambda _i: self.load_clip())
        self.compare_combo.activated.connect(lambda _i: self._compare())
        self.rating.rated.connect(self._rate)

    def _default_frames(self) -> None:
        draft = self.owner.session.quick.draft
        if draft:
            self.owner.change_quick(frames=workflow_for(draft.workflow).policy.default)

    def _seed(self) -> None:
        self.owner.change_quick(seed=_seed_intent(self.seed_kind, self.seed_value))

    def _rate(self, stars: int, note: str) -> None:
        clip_id = self.clip_combo.currentData()
        if not clip_id:
            return
        try:
            if stars:
                self.owner.session.rate(clip_id, stars, note)
            self.owner.banner.hide()
        except MotionRefused as exc:
            self.owner.warn("Rating refused", str(exc))

    # ---------------------------------------------------------------------------- results
    def current_run(self):
        run_id = self.run_combo.currentData()
        return next((r for r in self.owner.session.runs if r.run_id == run_id), None)

    def load_run(self) -> None:
        run = self.current_run()
        with QSignalBlocker(self.clip_combo):
            self.clip_combo.clear()
            if run:
                for clip in run.clips:
                    mark = "" if clip.completed else " · FAILED"
                    self.clip_combo.addItem(f"{clip.clip_id} · {clip.label}{mark}", clip.clip_id)
        self._fill_compare(run)
        self.load_clip()

    def _fill_compare(self, run) -> None:
        with QSignalBlocker(self.compare_combo):
            self.compare_combo.clear()
            self.compare_combo.addItem("Nothing selected", None)
            for other in self.owner.session.runs:
                if run and other.kind == "quick" and other.run_id != run.run_id:
                    self.compare_combo.addItem(other.run_id, other.run_id)
        self.compare_text.setText("")

    def _compare(self) -> None:
        run, other_id = self.current_run(), self.compare_combo.currentData()
        if not run or not other_id:
            self.compare_text.setText("")
            return
        other = self.owner.session.run(other_id)
        self.compare_text.setText("\n".join(diff_runs(run, other)))

    def load_clip(self) -> None:
        session = self.owner.session
        clip_id = self.clip_combo.currentData()
        clip = session.clips.get(clip_id) if clip_id else None
        try:
            self.viewer.set_plan(plan_for_clip(clip) if clip else None)
        except MotionRefused as exc:
            self.viewer.set_plan(None)
            self.viewer.title.setText(str(exc))
        self.rating.set_clip(clip, session.ratings.get(clip_id) if clip_id else None)

    def show_latest(self) -> None:
        run = self.owner.session.latest_run(KIND_QUICK)
        self._sync_runs(prefer=run.run_id if run else None)

    def _sync_runs(self, prefer: str | None = None) -> None:
        runs = [r for r in self.owner.session.runs if r.kind == "quick"]
        ids = tuple(r.run_id for r in runs)
        known = tuple(self.run_combo.itemData(i) for i in range(self.run_combo.count()))
        if ids != known or prefer:
            current = prefer or self.run_combo.currentData()
            with QSignalBlocker(self.run_combo):
                self.run_combo.clear()
                for r in runs:
                    self.run_combo.addItem(f"{r.run_id} · {r.state}", r.run_id)
                self.run_combo.setCurrentIndex(max(0, self.run_combo.findData(current)))
            self.load_run()
        self.run_combo.setEnabled(bool(runs))
        self.clip_combo.setEnabled(bool(runs))

    # -------------------------------------------------------------------------- sync
    def sync(self) -> None:
        s = self.owner.session
        draft = s.quick.draft
        have = draft is not None
        self.form_scroll.setEnabled(have)
        self.accept_media.setVisible(False)
        if have:
            wf = workflow_for(draft.workflow)
            with _blocked(self.source, self.workflow, self.prompt, self.frames, self.seed_kind,
                          self.seed_value, self.variants, self.reference, self.bucket, self.drill):  # fmt: skip
                self.source.select_key(draft.source_key)
                self.workflow.setCurrentIndex(
                    max(0, self.workflow.findData(wf_token(draft.workflow)))
                )
                if self.prompt.toPlainText() != draft.prompt:
                    self.prompt.setPlainText(draft.prompt)
                self.frames.setValue(draft.frames)
                _load_seed(self.seed_kind, self.seed_value, draft.seed)
                self.variants.setValue(draft.variants)
                self.reference.select_key(draft.reference_key)
                self.bucket.setValue(draft.motion_bucket or 0)
                self.drill.setCurrentIndex(max(0, self.drill.findData(draft.drill_fail_variant)))
            self.badge.set_workflow(wf)
            source = s.catalog.get(draft.source_key)
            changed = draft.source_digest != source.digest
            self.source_info.setText(
                f"{source.key} · {source.availability} · identity {source.digest}"
                f"\nOrigin: {s.origin.get(KIND_QUICK, 'picker')}"
                + ("\nSource media changed since selection." if changed else "")
            )
            self.accept_media.setVisible(changed and source.available)
            self.prompt_hint.setText(
                "" if "prompt" in wf.controls
                else f"{wf.label} declares no motion prompt: leave this empty (a value is refused, never dropped)."
            )  # fmt: skip
            legal = wf.policy.is_legal(draft.frames)
            self.frames_info.setText(
                f"{'Legal' if legal else 'NOT legal'}: {wf.policy.describe()} · {draft.frames} f = "
                f"{draft.frames / wf.policy.fps:.2f} s"
            )
            self.bucket_hint.setText(
                "" if "motion_bucket" in wf.controls
                else "Not declared by this workflow: a value is refused, never dropped."
            )  # fmt: skip
            required = s.consent_required(KIND_QUICK)
            self.consent.setVisible(required)
            self.consent_note.setVisible(required)
            with QSignalBlocker(self.consent):
                self.consent.setChecked(s.consent_valid(KIND_QUICK))
            self.consent_note.setText(
                "Consent applies to this exact draft only. Any edit clears it; a saved draft or "
                "earlier result never grants it."
            )
            parts = [f"seed {draft.seed.describe()}", f"variants {draft.variants}"]
            if draft.reference_key:
                parts.append(f"reference {draft.reference_key}")
            self.advanced.set_summary(" · ".join(parts))
        else:
            self.source_info.setText("Select an available source image fixture to begin.")
            self.badge.set_workflow(None)
        self.readiness.set_state(
            s.status(KIND_QUICK), s.previews[KIND_QUICK], s.issues(KIND_QUICK), s.quick.revision
        )
        self._sync_runs()


# --------------------------------------------------------------------------------- Storyboard
class StoryPanel(QWidget):
    """Layout A (strip) or B (timeline) over the same widgets and the same session."""

    def __init__(self, owner: MotionView, layout_design: str):
        super().__init__()
        self.owner, self.layout_design = owner, layout_design
        self.compact = False
        session = owner.session
        guard = owner._wheel_guard
        self.tools = ResponsiveGrid(min_column_width=92)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in (("add", "Add Shot"), ("duplicate", "Duplicate"), ("remove", "Remove"),
                          ("earlier", "Move Up"), ("later", "Move Down"), ("undo", "Undo"), ("redo", "Redo")):  # fmt: skip
            button = QPushButton(text)
            button.setToolTip(
                {
                    "add": "Add a shot after the selected one",
                    "duplicate": "Duplicate the selected shot",
                    "remove": "Remove the selected shot (a Storyboard keeps at least one)",
                    "earlier": "Move the selected shot earlier (Alt+Left)",
                    "later": "Move the selected shot later (Alt+Right)",
                    "undo": "Undo (Alt+Z)",
                    "redo": "Redo (Alt+Y)",
                }[key]
            )
            self.buttons[key] = button
            self.tools.add(button)
        self.strip = ShotStrip(session.catalog)
        self.timeline = ShotTimeline()
        self.viewer = SimulatedClipViewer(session.catalog)
        self.viewer.setMinimumHeight(VIEWER_MIN_HEIGHT)
        self.inspector = QTabWidget()
        self.inspector.setAccessibleName("Storyboard inspector")
        self.inspector.setMinimumWidth(300)
        self._build_board_tab(guard)
        self._build_shot_tab(guard)
        self._build_review_tabs(guard)
        if layout_design == "timeline":
            self._arrange_timeline()
        else:
            self._arrange_strip()
        self._connect()

    # ------------------------------------------------------------------------ tabs
    def _build_board_tab(self, guard) -> None:
        s = self.owner.session
        self.board_scroll, lay = _scroll()
        self.title = QLineEdit()
        self.title.setAccessibleName("Storyboard title")
        self.saved_note = _label()
        self.source = MotionSourceSelector(s.catalog)
        self.source_info = _label()
        self.accept_source = QPushButton("Accept Current Media")
        self.workflow = _combo("Storyboard workflow and version")
        for wf in offered_workflows():
            self.workflow.addItem(f"{wf.label} · {wf.governance.value}", wf_token(wf.key))
        self.badge = WorkflowCapabilityBadge()
        self.prompt = QLineEdit()
        self.prompt.setAccessibleName("Storyboard motion prompt")
        self.frames_inherit = QCheckBox("Use workflow default frames")
        self.frames = _spin("Default native frames", 1, 200, " f")
        self.seed_kind, self.seed_value = seed_combo(), _spin("Storyboard seed", 0, 2**31 - 1)
        self.consent = QCheckBox("I consent to this experimental workflow for this submission only")
        self.consent_note = _label(
            "Consent is bound to this exact draft and is never saved with it."
        )
        self.save_row = ResponsiveGrid(min_column_width=96)
        self.save_btn = QPushButton("Save (mock)")
        self.save_as_btn = QPushButton("Save As (mock)")
        self.dup_btn = QPushButton("Duplicate (mock)")
        self.new_btn = QPushButton("New Storyboard")
        for button in (self.save_btn, self.save_as_btn, self.dup_btn, self.new_btn):
            self.save_row.add(button)
        self.open_combo = _combo("Saved mock Storyboards")
        self.open_btn = QPushButton("Open saved")
        self.other_btn = QPushButton("Fixture: another session saves")
        self.advanced = Disclosure("Advanced · fixture drills")
        self.fail_shot = _combo("Fixture drill: fail at shot")
        self.advanced.add(stacked_label("Fail simulation at shot", self.fail_shot))
        self.advanced.add(self.other_btn)
        for widget in (
            stacked_label("Title", self.title), self.saved_note, stacked_label("Source (shot 1)", self.source),
            self.source_info, self.accept_source, stacked_label("Workflow and version", self.workflow),
            self.badge, stacked_label("Storyboard prompt (inherited by blank shots)", self.prompt),
            self.frames_inherit, stacked_label("Default native frames", self.frames),
            self.consent, self.consent_note, self.save_row,
            stacked_label("Saved mock drafts", self.open_combo), self.open_btn, self.advanced,
        ):  # fmt: skip
            lay.addWidget(widget)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(stacked_label("Storyboard seed intent", self.seed_kind))
        row.addWidget(stacked_label("Seed", self.seed_value))
        holder = QWidget()
        holder.setLayout(row)
        lay.insertWidget(lay.indexOf(self.frames_inherit), holder)
        lay.addStretch(1)
        for editor in (self.source, self.workflow, self.frames, self.seed_kind, self.seed_value,
                       self.open_combo, self.fail_shot):  # fmt: skip
            guard_wheel(editor, guard)
        self.inspector.addTab(self.board_scroll, "Storyboard")

    def _build_shot_tab(self, guard) -> None:
        s = self.owner.session
        self.shot_scroll, lay = _scroll()
        self.shot_info = _label()
        self.shot_label = QLineEdit()
        self.shot_label.setAccessibleName("Shot label")
        self.prompt_inherit = QCheckBox("Inherit Storyboard prompt")
        self.shot_prompt = QLineEdit()
        self.shot_prompt.setAccessibleName("Shot motion prompt")
        self.shot_frames_inherit = QCheckBox("Inherit default frames")
        self.shot_frames = _spin("Shot native frames", 1, 200, " f")
        self.shot_seed_kind, self.shot_seed = seed_combo(), _spin("Shot seed", 0, 2**31 - 1)
        self.shot_seed_kind.clear()
        for text, kind in (
            ("Inherit", "inherit"),
            ("Random (at admission)", "random"),
            ("Explicit", "explicit"),
        ):
            self.shot_seed_kind.addItem(text, kind)
        self.anchor = MotionSourceSelector(s.catalog, anchors=True)
        self.anchor_info = _label()
        self.accept_anchor = QPushButton("Accept Current Media")
        for widget in (
            self.shot_info, stacked_label("Label", self.shot_label), self.prompt_inherit,
            stacked_label("Motion prompt", self.shot_prompt), self.shot_frames_inherit,
            stacked_label("Native frames", self.shot_frames),
            stacked_label("Seed intent", self.shot_seed_kind), stacked_label("Seed", self.shot_seed),
            stacked_label("Authored anchor (shot 2 onward)", self.anchor), self.anchor_info, self.accept_anchor,
        ):  # fmt: skip
            lay.addWidget(widget)
        lay.addStretch(1)
        for editor in (self.shot_frames, self.shot_seed_kind, self.shot_seed, self.anchor):
            guard_wheel(editor, guard)
        self.inspector.addTab(self.shot_scroll, "Shot")

    def _build_review_tabs(self, guard) -> None:
        self.readiness_scroll, lay = _scroll()
        self.readiness = SequenceReadinessPanel()
        lay.addWidget(self.readiness)
        lay.addStretch(1)
        self.inspector.addTab(self.readiness_scroll, "Readiness")
        self.results_scroll, lay = _scroll()
        self.run_combo = _combo("Viewer content")
        self.clip_info = _label()
        self.compare_combo = _combo("Compare with sequence")
        self.compare_text = _label()
        self.resume_text = _label()
        self.reopen = QPushButton("Open as new Storyboard draft")
        self.rating = QualityRatingPanel()
        self.rating_clip = _combo("Rated segment")
        for widget in (
            stacked_label("Viewer shows", self.run_combo), self.clip_info,
            stacked_label("Compare with", self.compare_combo), self.compare_text, self.resume_text,
            self.reopen, stacked_label("Rate segment", self.rating_clip), self.rating,
        ):  # fmt: skip
            lay.addWidget(widget)
        lay.addStretch(1)
        for combo in (self.run_combo, self.compare_combo, self.rating_clip):
            guard_wheel(combo, guard)
        self.inspector.addTab(self.results_scroll, "Results")

    # ---------------------------------------------------------------------- arrangement
    def _arrange_strip(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self.tools)
        self.strip_scroll = QScrollArea()
        self.strip_scroll.setWidgetResizable(True)
        self.strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip_scroll.setWidget(self.strip)
        self.strip_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.strip_scroll)
        self.timeline.set_detailed(False)
        lay.addWidget(self.timeline)
        self.body = QSplitter(Qt.Orientation.Horizontal)
        self.body.setChildrenCollapsible(False)
        self.view_box = QWidget()
        view_lay = QVBoxLayout(self.view_box)
        view_lay.setContentsMargins(0, 0, 0, 0)
        view_lay.addWidget(self.viewer)
        self.body.addWidget(self.view_box)
        self.body.addWidget(self.inspector)
        self.body.setStretchFactor(0, 3)
        self.body.setStretchFactor(1, 2)
        lay.addWidget(self.body, 1)

    def _arrange_timeline(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE.sm)
        lay.addWidget(self.tools)
        self.body = QSplitter(Qt.Orientation.Vertical)
        self.body.setChildrenCollapsible(False)
        self.body.setAccessibleName("Preview and timeline")
        top = QSplitter(Qt.Orientation.Horizontal)
        top.setChildrenCollapsible(False)
        top.addWidget(self.viewer)
        top.addWidget(self.inspector)
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 2)
        self.top_split = top
        self.body.addWidget(top)
        bottom = QWidget()
        blay = QVBoxLayout(bottom)
        blay.setContentsMargins(0, 0, 0, 0)
        blay.setSpacing(SPACE.xs)
        self.timeline.set_detailed(True)
        blay.addWidget(self.timeline)
        self.strip_scroll = QScrollArea()
        self.strip_scroll.setWidgetResizable(True)
        self.strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip_scroll.setWidget(self.strip)
        self.strip.set_compact(True)
        blay.addWidget(self.strip_scroll, 1)
        self.body.addWidget(bottom)
        self.bottom = bottom
        self.body.setStretchFactor(0, 3)
        self.body.setStretchFactor(1, 2)
        lay.addWidget(self.body, 1)

    # --------------------------------------------------------------------------- wiring
    def _connect(self) -> None:
        o = self.owner
        b = self.buttons
        b["add"].clicked.connect(o.add_shot)
        b["duplicate"].clicked.connect(o.duplicate_shot)
        b["remove"].clicked.connect(o.remove_shot)
        b["earlier"].clicked.connect(lambda: o.move_shot(-1))
        b["later"].clicked.connect(lambda: o.move_shot(1))
        b["undo"].clicked.connect(lambda: o.undo())
        b["redo"].clicked.connect(lambda: o.redo())
        self.strip.shotSelected.connect(o.select_shot)
        self.timeline.shotSelected.connect(o.select_shot)
        self.title.textEdited.connect(lambda t: o.change_story(title=t))
        self.source.activated.connect(lambda _i: o.change_story_source(self.source.key()))
        self.accept_source.clicked.connect(lambda: o.accept_media(KIND_STORY))
        self.workflow.activated.connect(
            lambda _i: o.change_story(workflow=wf_key(self.workflow.currentData()))
        )
        self.prompt.textEdited.connect(lambda t: o.change_story(default_prompt=t))
        self.frames_inherit.toggled.connect(self._default_frames)
        self.frames.valueChanged.connect(lambda v: o.change_story(default_frames=v))
        self.seed_kind.activated.connect(lambda _i: self._seed())
        self.seed_value.valueChanged.connect(lambda _v: self._seed())
        self.consent.toggled.connect(lambda on: o.set_consent(KIND_STORY, on))
        self.save_btn.clicked.connect(o.save_story)
        self.save_as_btn.clicked.connect(lambda: o.save_story_as(" — Save As"))
        self.dup_btn.clicked.connect(lambda: o.save_story_as(None))
        self.new_btn.clicked.connect(o.new_story)
        self.open_btn.clicked.connect(o.open_saved)
        self.other_btn.clicked.connect(o.other_session_saves)
        self.fail_shot.activated.connect(
            lambda _i: o.change_story(drill_fail_shot=self.fail_shot.currentData())
        )
        self.shot_label.textEdited.connect(lambda t: o.change_shot(label=t))
        self.prompt_inherit.toggled.connect(lambda on: o.change_shot(prompt=None if on else ""))
        self.shot_prompt.textEdited.connect(lambda t: o.change_shot(prompt=t))
        self.shot_frames_inherit.toggled.connect(self._shot_frames_inherit)
        self.shot_frames.valueChanged.connect(lambda v: o.change_shot(frames=v))
        self.shot_seed_kind.activated.connect(lambda _i: self._shot_seed())
        self.shot_seed.valueChanged.connect(lambda _v: self._shot_seed())
        self.anchor.activated.connect(lambda _i: o.change_shot(anchor_key=self.anchor.key()))
        self.accept_anchor.clicked.connect(o.accept_anchor)
        self.run_combo.activated.connect(lambda _i: self.load_view())
        self.compare_combo.activated.connect(lambda _i: self._compare())
        self.reopen.clicked.connect(o.reopen_run)
        self.rating_clip.activated.connect(lambda _i: self._rating_target())
        self.rating.rated.connect(self._rate)

    def _default_frames(self, inherit: bool) -> None:
        draft = self.owner.session.story.draft
        if draft:
            default = workflow_for(draft.workflow).policy.default
            self.owner.change_story(
                default_frames=None if inherit else (draft.default_frames or default)
            )

    def _seed(self) -> None:
        self.owner.change_story(seed=_seed_intent(self.seed_kind, self.seed_value))

    def _shot_frames_inherit(self, inherit: bool) -> None:
        self.owner.change_shot(frames=None if inherit else self.shot_frames.value())

    def _shot_seed(self) -> None:
        self.owner.change_shot(seed=_seed_intent(self.shot_seed_kind, self.shot_seed))

    def _rate(self, stars: int, note: str) -> None:
        clip_id = self.rating_clip.currentData()
        if clip_id and stars:
            try:
                self.owner.session.rate(clip_id, stars, note)
                self.owner.banner.hide()
            except MotionRefused as exc:
                self.owner.warn("Rating refused", str(exc))

    def _rating_target(self) -> None:
        clip_id = self.rating_clip.currentData()
        session = self.owner.session
        clip = session.clips.get(clip_id) if clip_id else None
        self.rating.set_clip(clip, session.ratings.get(clip_id) if clip_id else None)

    # ----------------------------------------------------------------------------- viewer
    def _draft_plan(self) -> PlaybackPlan | None:
        s = self.owner.session
        draft, shot_id = s.story.draft, self.owner.ui.shot
        if draft is None or shot_id is None:
            return None
        position = next((i for i, x in enumerate(draft.shots) if x.shot_id == shot_id), None)
        if position is None:
            return None
        shot = draft.shots[position]
        wf = workflow_for(draft.workflow)
        key = shot.anchor_key if position > 0 and shot.anchor_key else draft.source_key
        if not key or usable_image(s.catalog, key):
            return None
        frames = effective_frames(draft, shot, wf)
        frames = frames if wf.policy.is_legal(frames) else wf.policy.default
        prompt = effective_prompt(draft, shot) or ""
        seg = PlaybackSegment(shot.label, "draft", key, motion_for(prompt, None), frames,
                              wf.policy.fps, 0, frames)  # fmt: skip
        return PlaybackPlan(f"Draft illustration · shot {position + 1} (not a result)", (seg,))

    def load_view(self) -> None:
        s = self.owner.session
        run_id = self.run_combo.currentData()
        run = next((r for r in s.runs if r.run_id == run_id), None) if run_id else None
        try:
            plan = plan_for_run(run) if run else self._draft_plan()
        except MotionRefused as exc:
            plan = None
            self.clip_info.setText(str(exc))
        if (
            plan is None or plan != self.viewer.plan
        ):  # a sync must not rewind a playing illustration
            self.viewer.set_plan(plan)
        with QSignalBlocker(self.compare_combo):
            self.compare_combo.clear()
            self.compare_combo.addItem("Nothing selected", None)
            for other in s.runs:
                if run and other.kind == "sequence" and other.run_id != run.run_id:
                    self.compare_combo.addItem(other.run_id, other.run_id)
        self.compare_text.setText("")
        with QSignalBlocker(self.rating_clip):
            self.rating_clip.clear()
            if run:
                for clip in run.clips:
                    self.rating_clip.addItem(f"{clip.clip_id} · {clip.label}", clip.clip_id)
        self._rating_target()
        if run:
            ok, why = resume_eligibility(run, s.story.draft)
            self.clip_info.setText(
                f"{run.run_id} · {run.state} · {len(run.clips)} segment(s) · origin {run.origin}\n"
                f"Frozen plan {run.plan_fingerprint}. Source {run.snapshot.source_key}."
            )
            self.resume_text.setText(f"Strict resume (fixture explanation only): {why}")
        else:
            self.resume_text.setText("")
            self.clip_info.setText(
                "Draft illustration of the selected shot. Simulate Sequence for a result."
            )
        self.reopen.setEnabled(run is not None)

    def _compare(self) -> None:
        s = self.owner.session
        run = next((r for r in s.runs if r.run_id == self.run_combo.currentData()), None)
        other_id = self.compare_combo.currentData()
        if run and other_id:
            self.compare_text.setText("\n".join(diff_runs(run, s.run(other_id))))
        else:
            self.compare_text.setText("")

    def show_latest(self) -> None:
        run = self.owner.session.latest_run(KIND_STORY)
        self._sync_runs(prefer=run.run_id if run else None)
        if run:
            self.inspector.setCurrentWidget(self.results_scroll)

    def _sync_runs(self, prefer: str | None = None) -> None:
        runs = [r for r in self.owner.session.runs if r.kind == "sequence"]
        known = tuple(self.run_combo.itemData(i) for i in range(self.run_combo.count()))
        ids = (None, *(r.run_id for r in runs))
        if ids != known or prefer:
            current = prefer or self.run_combo.currentData()
            with QSignalBlocker(self.run_combo):
                self.run_combo.clear()
                self.run_combo.addItem("Draft illustration of the selected shot", None)
                for r in runs:
                    self.run_combo.addItem(f"{r.run_id} · {r.title} · {r.state}", r.run_id)
                self.run_combo.setCurrentIndex(max(0, self.run_combo.findData(current)))
            self.load_view()
        elif self.run_combo.currentData() is None:
            self.load_view()

    # ------------------------------------------------------------------------------- sync
    def sync(self) -> None:
        o, s = self.owner, self.owner.session
        draft = s.ensure_storyboard()
        preview = s.previews[KIND_STORY]
        current = preview is not None and s.status(KIND_STORY) not in (
            Status.STALE,
            Status.NOT_REVIEWED,
        )
        wf = workflow_for(draft.workflow)
        ids = [x.shot_id for x in draft.shots]
        if o.ui.shot not in ids:
            o.ui.shot = ids[0]
        cards, rows = [], []
        for position, shot in enumerate(draft.shots):
            frames = effective_frames(draft, shot, wf)
            basis = anchor_basis(position, shot)
            info = preview.shots[position] if current and position < len(preview.shots) else None
            issues = len(info.errors) if info else -1
            key = shot.anchor_key if position > 0 and shot.anchor_key else draft.source_key
            text = f"{frames} f" if wf.policy.is_legal(frames) else f"{frames} f (illegal)"
            cards.append(ShotCardData(shot.shot_id, position + 1, shot.label,
                                      text, basis, issues, key))  # fmt: skip
            rows.append(TimelineRow(shot.shot_id, position + 1, shot.label,
                                    frames if wf.policy.is_legal(frames) else 1, basis, issues > 0))  # fmt: skip
        self.strip.set_compact(self.compact or self.layout_design == "timeline")
        self.strip.set_shots(cards, o.ui.shot)
        self.timeline.set_rows(rows, o.ui.shot)
        self._sync_board(draft, wf)
        self._sync_shot(draft, wf)
        b = self.buttons
        count, index = len(ids), ids.index(o.ui.shot)
        b["add"].setEnabled(count < MAX_SHOTS)
        b["duplicate"].setEnabled(count < MAX_SHOTS)
        b["remove"].setEnabled(count > 1)
        b["earlier"].setEnabled(index > 0)
        b["later"].setEnabled(index < count - 1)
        b["undo"].setEnabled(s.story.can_undo)
        b["redo"].setEnabled(s.story.can_redo)
        self.readiness.set_state(
            s.status(KIND_STORY), preview, s.issues(KIND_STORY), s.story.revision
        )
        self._sync_runs()
        self._fit_strip()
        QTimer.singleShot(
            0, self, self._fit_strip
        )  # again once the stylesheet has polished the cards

    def _fit_strip(self) -> None:
        """Layout A: the strip is as tall as its wrapped cards (capped). Layout B: the lower pane
        keeps at least one full row of cards beside the timeline."""
        row = self.strip.row_height()
        if self.layout_design == "timeline":
            self.bottom.setMinimumHeight(self.timeline.height() + row + 2 * SPACE.xs + 4)
            self.strip_scroll.setMinimumHeight(row + 2)
        else:
            cap = row * 2 + SPACE.sm + 2
            self.strip_scroll.setFixedHeight(min(self.strip.needed_height() + 2, cap))

    def _sync_board(self, draft, wf) -> None:
        s = self.owner.session
        with _blocked(self.title, self.source, self.workflow, self.prompt, self.frames,
                      self.frames_inherit, self.seed_kind, self.seed_value, self.fail_shot,
                      self.open_combo, self.consent):  # fmt: skip
            if self.title.text() != draft.title:
                self.title.setText(draft.title)
            self.source.select_key(draft.source_key)
            self.workflow.setCurrentIndex(max(0, self.workflow.findData(wf_token(draft.workflow))))
            if self.prompt.text() != draft.default_prompt:
                self.prompt.setText(draft.default_prompt)
            self.frames_inherit.setChecked(draft.default_frames is None)
            self.frames.setEnabled(draft.default_frames is not None)
            self.frames.setValue(
                draft.default_frames if draft.default_frames is not None else wf.policy.default
            )
            _load_seed(self.seed_kind, self.seed_value, draft.seed)
            self.fail_shot.clear()
            self.fail_shot.addItem("No failure", None)
            for x in draft.shots:
                self.fail_shot.addItem(f"{x.label} ({x.shot_id})", x.shot_id)
            self.fail_shot.setCurrentIndex(max(0, self.fail_shot.findData(draft.drill_fail_shot)))
            self.open_combo.clear()
            for sid, title, revisions in s.store.list():
                self.open_combo.addItem(f"{title} · {sid} · r{revisions}", sid)
            self.consent.setChecked(s.consent_valid(KIND_STORY))
        self.badge.set_workflow(wf)
        required = s.consent_required(KIND_STORY)
        self.consent.setVisible(required)
        self.consent_note.setVisible(required)
        source = s.catalog.get(draft.source_key) if draft.source_key else None
        changed = source is not None and draft.source_digest != source.digest
        self.source_info.setText(
            "Select a source image for shot 1." if source is None
            else f"{source.key} · {source.availability} · identity {source.digest}"
            + ("\nSource media changed since it was recorded." if changed else "")
        )  # fmt: skip
        self.accept_source.setVisible(bool(changed and source.available))
        saved = f"saved revision {draft.base_revision}" if draft.base_revision else "never saved"
        self.saved_note.setText(
            f"{draft.storyboard_id} · {saved} · "
            + ("UNSAVED CHANGES" if s.story.dirty else "no unsaved changes")
            + " · in-memory mock, no file written"
        )
        self.open_btn.setEnabled(self.open_combo.count() > 0)
        self.other_btn.setEnabled(draft.base_revision > 0)

    def _sync_shot(self, draft, wf) -> None:
        o, s = self.owner, self.owner.session
        position = next(i for i, x in enumerate(draft.shots) if x.shot_id == o.ui.shot)
        shot = draft.shots[position]
        first = position == 0
        with _blocked(self.shot_label, self.prompt_inherit, self.shot_prompt, self.shot_frames_inherit,
                      self.shot_frames, self.shot_seed_kind, self.shot_seed, self.anchor):  # fmt: skip
            if self.shot_label.text() != shot.label:
                self.shot_label.setText(shot.label)
            self.prompt_inherit.setChecked(shot.prompt is None)
            self.shot_prompt.setEnabled(shot.prompt is not None)
            text = shot.prompt if shot.prompt is not None else draft.default_prompt
            if self.shot_prompt.text() != text:
                self.shot_prompt.setText(text)
            self.shot_frames_inherit.setChecked(shot.frames is None)
            self.shot_frames.setEnabled(shot.frames is not None)
            self.shot_frames.setValue(effective_frames(draft, shot, wf))
            _load_seed(self.shot_seed_kind, self.shot_seed, shot.seed)
            self.anchor.select_key(shot.anchor_key)
            self.anchor.setEnabled(not first)
        basis = anchor_basis(position, shot)
        anchor_text = {
            "source": "Shot 1 starts from the Storyboard source.",
            "carried": "Carries the previous shot's exact last frame (1 overlap frame).",
            "provided": "Authored anchor: hard cut, no overlap frame.",
        }[basis]
        if first and shot.anchor_key:
            anchor_text = (
                "Shot 1 has an authored anchor but uses the main source: clear it or move it back."
            )
        self.shot_info.setText(
            f"Shot {position + 1} of {len(draft.shots)} · identity {shot.shot_id}\n{anchor_text}"
        )
        anchor_changed = False
        if shot.anchor_key:
            try:
                anchor_changed = s.catalog.get(shot.anchor_key).digest != shot.anchor_digest
            except MotionRefused:
                pass
        self.accept_anchor.setVisible(anchor_changed)
        self.anchor_info.setText(
            "Anchor media changed since it was recorded." if anchor_changed else ""
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        compact = self.height() < COMPACT_HEIGHT
        if compact != self.compact:
            self.compact = compact
            self.owner.sync()
        else:
            self._fit_strip()


# ---------------------------------------------------------------------------------- Movie Clips
class MoviePanel(QSplitter):
    def __init__(self, owner: MotionView):
        super().__init__(Qt.Orientation.Horizontal)
        self.owner = owner
        self.setChildrenCollapsible(False)
        guard = owner._wheel_guard
        self.left_scroll, left = _scroll()
        self.library = QListWidgetCompat()
        self.add_btn = QPushButton("Add to Assembly")
        self.library_note = _label(
            "Simulated clips only. Selected clips are added in the order listed here; reorder afterwards."
        )
        self.assembly = ClipAssemblyList()
        self.inspect_btn = QPushButton("Inspect selected clip source")
        self.source_note = _label()
        for widget in (_label("Simulated clip library", "section"), self.library_note, self.library,
                       self.add_btn, _label("Assembly order", "section"), self.assembly,
                       self.source_note):  # fmt: skip
            left.addWidget(widget)
        left.addStretch(1)
        self.addWidget(self.left_scroll)
        self.right_scroll, right = _scroll()
        self.title = QLineEdit()
        self.title.setAccessibleName("Mock movie title")
        self.transition = _combo("Transition illustration")
        for key, (text, _s) in TRANSITIONS.items():
            self.transition.addItem(text, key)
        self.audio = _combo("Imported audio fixture")
        self.audio.addItem("No audio", None)
        for key, title, seconds, availability in AUDIO:
            suffix = "" if availability.value == "Available" else f" · {availability}"
            self.audio.addItem(f"{title} ({seconds:.0f} s){suffix}", key)
        self.profile = _combo("Export profile")
        for key, p in PROFILES.items():
            self.profile.addItem(p.label, key)
        self.drill = QCheckBox("Fixture drill: simulate an assembly failure")
        self.readiness = SequenceReadinessPanel()
        self.viewer = SimulatedClipViewer(owner.session.catalog)
        self.viewer.setMinimumHeight(220)
        self.result_combo = _combo("Mock movie result")
        self.result_info = _label()
        for widget in (stacked_label("Title", self.title), stacked_label("Transition (illustrated)", self.transition),
                       stacked_label("Audio (imported fixture; no generated audio)", self.audio),
                       stacked_label("Export profile", self.profile), self.drill, self.readiness,
                       stacked_label("Mock movie result", self.result_combo), self.result_info,
                       self.viewer):  # fmt: skip
            right.addWidget(widget)
        right.addStretch(1)
        for editor in (self.transition, self.audio, self.profile, self.result_combo):
            guard_wheel(editor, guard)
        self.addWidget(self.right_scroll)
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 1)
        o = owner
        self.add_btn.clicked.connect(self._add)
        self.assembly.moveRequested.connect(o.move_item)
        self.assembly.removeRequested.connect(o.remove_item)
        self.assembly.trimChanged.connect(o.set_trim)
        self.assembly.itemSelected.connect(self._selected)
        self.title.textEdited.connect(lambda t: o.change_assembly(title=t))
        self.transition.activated.connect(
            lambda _i: o.change_assembly(transition=self.transition.currentData())
        )
        self.audio.activated.connect(
            lambda _i: o.change_assembly(audio_key=self.audio.currentData())
        )
        self.profile.activated.connect(
            lambda _i: o.change_assembly(profile=self.profile.currentData())
        )
        self.drill.toggled.connect(lambda on: o.change_assembly(drill_failure=on))
        self.result_combo.activated.connect(lambda _i: self.load_result())

    def _add(self) -> None:
        ids = self.library.selected_clip_ids()
        if not ids:
            self.owner.warn(
                "Nothing selected", "Select one or more eligible simulated clips first."
            )
            return
        self.owner.add_clips(ids)

    def _selected(self, item_id: str) -> None:
        s = self.owner.session
        item = next((i for i in s.ensure_assembly().items if i.item_id == item_id), None)
        if item:
            clip = s.clip(item.clip_id)
            src = s.catalog.get(clip.source_key)
            self.source_note.setText(
                f"{clip.clip_id} ← run {clip.run_id} · {clip.origin}\nSource {src.key} · {src.availability}"
                f" · {clip.workflow[0]} {clip.workflow[1]} · seed {clip.seed} ({clip.seed_origin})"
            )

    def load_result(self) -> None:
        s = self.owner.session
        movie_id = self.result_combo.currentData()
        movie = next((m for m in s.movies if m.movie_id == movie_id), None)
        if movie is None:
            self.viewer.set_plan(None)
            self.result_info.setText(
                "No mock movie result yet. Simulate Assembly for an illustration."
            )
            return
        info = (f"{movie.movie_id} (assembly {movie.assembly_id}) · {movie.status} · ≈{movie.seconds:.2f} s · "
                f"{PROFILES[movie.profile].label}\nClips {' → '.join(movie.clip_ids)}\n"
                "Simulated illustration: no FFmpeg ran and no encoded file exists.")  # fmt: skip
        if movie.status != "completed":
            self.viewer.set_plan(None)
            info += f"\nFAILED: {movie.failure}"
        else:
            self.viewer.set_plan(plan_for_movie(s, movie))
        self.result_info.setText(info)

    def show_latest(self) -> None:
        s = self.owner.session
        movie = s.movies[-1] if s.movies else None
        self._sync_results(prefer=movie.movie_id if movie else None)

    def _sync_results(self, prefer: str | None = None) -> None:
        movies = self.owner.session.movies
        ids = tuple(m.movie_id for m in movies)
        known = tuple(self.result_combo.itemData(i) for i in range(self.result_combo.count()))
        if ids != known or prefer:
            current = prefer or self.result_combo.currentData()
            with QSignalBlocker(self.result_combo):
                self.result_combo.clear()
                for m in movies:
                    self.result_combo.addItem(f"{m.movie_id} · {m.status}", m.movie_id)
                self.result_combo.setCurrentIndex(max(0, self.result_combo.findData(current)))
            self.load_result()
        self.result_combo.setEnabled(bool(movies))

    def sync(self) -> None:
        s = self.owner.session
        draft = s.ensure_assembly()
        self.library.set_clips(s)
        rows = []
        preview = s.previews[KIND_MOVIE]
        for position, item in enumerate(draft.items):
            clip = s.clips.get(item.clip_id)
            problem = ""
            if clip is None:
                problem = "unknown clip"
            else:
                ok, reason = s.clip_eligibility(clip)
                problem = "" if ok else reason.removeprefix("Not eligible: ")
                if any(i.clip_id == item.clip_id for i in draft.items[:position]):
                    problem = (problem + " Duplicate source.").strip()
            text = (f"{item.clip_id} · {clip.label} · {clip.frames} f ({clip.seconds:.2f} s)"
                    if clip else item.clip_id)  # fmt: skip
            rows.append(AssemblyRow(item.item_id, text, clip.frames if clip else 0,
                                    item.trim_start, item.trim_end, problem))  # fmt: skip
        selected = self.assembly.current_id()
        self.assembly.set_items(rows, selected)
        with _blocked(self.title, self.transition, self.audio, self.profile, self.drill):
            if self.title.text() != draft.title:
                self.title.setText(draft.title)
            self.transition.setCurrentIndex(max(0, self.transition.findData(draft.transition)))
            self.audio.setCurrentIndex(max(0, self.audio.findData(draft.audio_key)))
            self.profile.setCurrentIndex(max(0, self.profile.findData(draft.profile)))
            self.drill.setChecked(draft.drill_failure)
        self.readiness.set_state(
            s.status(KIND_MOVIE), preview, s.issues(KIND_MOVIE), s.assembly.revision
        )
        self._sync_results()
        if selected:
            self._selected(selected)


class QListWidgetCompat(QWidget):
    """Multi-select library list of simulated clips (ineligible clips stay visible with their reason)."""

    def __init__(self):
        super().__init__()
        from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

        self._item_cls = QListWidgetItem
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setProperty("role", "nav")
        self.list.setAccessibleName("Simulated clip library")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setMinimumHeight(130)
        self.list.setWordWrap(True)
        lay.addWidget(self.list)
        self._ids: tuple = ()

    def set_clips(self, session: MotionSession) -> None:
        clips = list(session.clips.values())
        signature = tuple((c.clip_id, session.clip_eligibility(c)[0]) for c in clips)
        if signature == self._ids:
            return
        self._ids = signature
        selected = set(self.selected_clip_ids())
        self.list.clear()
        for clip in clips:
            ok, reason = session.clip_eligibility(clip)
            text = f"{clip.clip_id} · {clip.label} · {clip.frames} f · {clip.origin}"
            if not ok:
                text += f"\n{reason}"
            item = self._item_cls(text)
            item.setData(Qt.ItemDataRole.UserRole, clip.clip_id)
            if not ok:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list.addItem(item)
            if clip.clip_id in selected:
                item.setSelected(True)

    def selected_clip_ids(self) -> list[str]:
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        return [self.list.item(r).data(Qt.ItemDataRole.UserRole) for r in rows]


class ContextCard(QFrame):
    """Source / workflow summary with status chips. One row when wide, two when narrow."""

    def __init__(self):
        super().__init__()
        self.setProperty("role", "card")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(SPACE.md, SPACE.xs, SPACE.md, SPACE.xs)
        self._grid.setSpacing(SPACE.sm)
        self._chips = QWidget()
        self._chip_row = QHBoxLayout(self._chips)
        self._chip_row.setContentsMargins(0, 0, 0, 0)
        self._chip_row.setSpacing(SPACE.sm)
        self._stacked: bool | None = None
        self._source: QWidget | None = None
        self._workflow: QWidget | None = None

    def place(self, source: QWidget, workflow: QWidget, chips) -> None:
        self._source, self._workflow = source, workflow
        for chip in chips:
            self._chip_row.addWidget(chip)
        self._chip_row.addStretch(1)
        self._layout(stacked=False)

    def _layout(self, *, stacked: bool) -> None:
        if stacked == self._stacked or self._source is None:
            return
        self._stacked = stacked
        for widget in (self._source, self._workflow, self._chips):
            self._grid.removeWidget(widget)
        self._grid.addWidget(self._source, 0, 0)
        self._grid.addWidget(self._workflow, 0, 1)
        if stacked:
            self._grid.addWidget(self._chips, 1, 0, 1, 2)
        else:
            self._grid.addWidget(self._chips, 0, 2)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        self._grid.setColumnStretch(2, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._layout(stacked=self.width() < WIDE_CONTEXT)


# -------------------------------------------------------------------------------- the workspace
class MotionView(QWidget):
    """Motion & Video workspace. Reuses ActionStrip/StatusChip/NoticeBanner and the theme tokens."""

    def __init__(
        self,
        session: MotionSession | None = None,
        layout_design: str = "strip",
        ui: MotionUi | None = None,
    ):
        super().__init__()
        self.session = session or MotionSession()
        self.ui = ui or MotionUi(layout=layout_design)
        self._wheel_guard = NoWheelUnlessFocused(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.sm, 0, 0, 0)
        root.setSpacing(SPACE.sm)
        head = QHBoxLayout()
        head.setSpacing(SPACE.sm)
        head.addWidget(_label("Motion & Video", "heading"))
        head.addStretch(1)
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, text in MODES:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("role", "segment")
            button.setAccessibleName(f"Motion mode: {text}")
            fit_segment(button)
            button.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            self.mode_buttons[key] = button
            head.addWidget(button)
        self.layout_combo = _combo("Storyboard layout")
        for key, text in LAYOUTS:
            self.layout_combo.addItem(text, key)
        self.layout_combo.activated.connect(
            lambda _i: self.set_layout_design(self.layout_combo.currentData())
        )
        guard_wheel(self.layout_combo, self._wheel_guard)
        head.addWidget(self.layout_combo)
        root.addLayout(head)
        context = ContextCard()
        self.context = context
        self.context_source = ElidedLabel()
        self.context_workflow = ElidedLabel()
        self.governance_chip = StatusChip("Governance", "info")
        self.status_chip = StatusChip(Status.NOT_REVIEWED.value, "info")
        self.mock_chip = StatusChip("MOCK ONLY · NO VIDEO", "warning")
        context.place(
            self.context_source,
            self.context_workflow,
            (self.governance_chip, self.status_chip, self.mock_chip),
        )
        context.setAccessibleName("Motion context")
        root.addWidget(context)
        self.banner = NoticeBanner()
        self.banner.hide()
        root.addWidget(self.banner)
        self.stack = QStackedWidget()
        self.quick_panel = QuickPanel(self)
        self.stack.addWidget(self.quick_panel)
        self.story_panel = StoryPanel(self, self.ui.layout)
        self.stack.addWidget(self.story_panel)
        self.movie_panel = MoviePanel(self)
        self.stack.addWidget(self.movie_panel)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_scroll.setAccessibleName("Motion workspace")
        self.page_scroll.setWidget(self.stack)
        root.addWidget(self.page_scroll, 1)
        self.actions = MotionActionStrip()
        root.addWidget(self.actions)
        self.actions.review.clicked.connect(self.review)
        self.actions.simulate.clicked.connect(self.simulate)
        self.actions.inspect.clicked.connect(self.inspect_results)
        self.actions.send.clicked.connect(self.send_to_movie)
        self._shortcuts()
        self.set_mode(self.ui.mode)

    # ----------------------------------------------------------------------- plumbing
    def _shortcuts(self) -> None:
        for name, seq, callback in (
            ("Undo Motion edit", "Alt+Z", self.undo),
            ("Redo Motion edit", "Alt+Y", self.redo),
            ("Review Motion readiness", "Ctrl+Return", self.review),
            ("Move shot earlier", "Alt+Left", lambda: self.move_shot(-1)),
            ("Move shot later", "Alt+Right", lambda: self.move_shot(1)),
        ):
            action = QAction(name, self)
            action.setShortcut(seq)
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def warn(self, title: str, message: str, level: str = "warning") -> None:
        self.banner.set_message(title, message, level)
        self.banner.show()

    def _guard(self, action) -> bool:
        try:
            action()
        except MotionRefused as exc:
            self.warn("Refused", str(exc))
            return False
        self.banner.hide()
        return True

    def set_mode(self, mode: str) -> None:
        self.ui.mode = mode
        for key, button in self.mode_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(key == mode)
        self.stack.setCurrentIndex({KIND_QUICK: 0, KIND_STORY: 1, KIND_MOVIE: 2}[mode])
        self.layout_combo.setVisible(mode == KIND_STORY)
        with QSignalBlocker(self.layout_combo):
            self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(self.ui.layout)))
        self.sync()

    def set_layout_design(self, design: str) -> None:
        """Rebuild only the Storyboard arrangement; every piece of state is in the session."""
        if design == self.ui.layout and self.story_panel.layout_design == design:
            return
        self.ui.layout = design
        old = self.story_panel
        old.viewer.pause()
        index = self.stack.indexOf(old)
        self.story_panel = StoryPanel(self, design)
        self.stack.insertWidget(index, self.story_panel)
        self.stack.removeWidget(old)
        old.hide()
        old.deleteLater()
        self.set_mode(self.ui.mode)

    def restyle(self) -> None:
        self.sync()

    def shutdown(self) -> None:
        for viewer in (self.quick_panel.viewer, self.story_panel.viewer, self.movie_panel.viewer):
            viewer.pause()

    # --------------------------------------------------------------------------- sync
    def sync(self) -> None:
        s, mode = self.session, self.ui.mode
        if mode == KIND_QUICK:
            self.quick_panel.sync()
            draft = s.quick.draft
            source = (
                f"Source · {draft.source_key} · {s.catalog.get(draft.source_key).availability}"
                if draft
                else "Source · none selected"
            )
            wf = workflow_for(draft.workflow) if draft else None
        elif mode == KIND_STORY:
            self.story_panel.sync()
            draft = s.story.draft
            source = f"Source · {draft.source_key or 'none'} · {draft.title}"
            wf = workflow_for(draft.workflow)
        else:
            self.movie_panel.sync()
            draft = s.assembly.draft
            source = f"Assembly · {len(draft.items)} clip(s) in authored order"
            wf = None
        self.context_source.set_full_text(source)
        if wf:
            self.context_workflow.set_full_text(f"Workflow · {wf.label} · {wf.route.value}")
            self.governance_chip.set_status(
                wf.governance.value.upper(), GOVERNANCE_LEVEL[wf.governance]
            )
        else:
            self.context_workflow.set_full_text("Assembly · separate simulated CPU operation")
            self.governance_chip.set_status("NOT A GENERATION", "info")
        status = s.status(mode)
        self.status_chip.set_status(status.value, STATUS_LEVEL[status])
        self.actions.status.setText(f"{status.value} · mock simulation only · nothing queued")
        self.actions.simulate.setText(SIMULATE_TEXT[mode])
        self.actions.simulate.setEnabled(status in (Status.READY, Status.SIMULATED))
        self.actions.review.setEnabled(
            (mode == KIND_MOVIE) or (s.quick.draft is not None if mode == KIND_QUICK else True)
        )
        self.actions.send.setVisible(mode != KIND_MOVIE)
        run = s.latest_run(mode) if mode != KIND_MOVIE else None
        self.actions.send.setEnabled(bool(run and any(c.completed for c in run.clips)))
        self.actions.inspect.setEnabled(
            bool(s.movies)
            if mode == KIND_MOVIE
            else any(r.kind == ("quick" if mode == KIND_QUICK else "sequence") for r in s.runs)
        )

    # ---------------------------------------------------------------------- actions
    def review(self) -> None:
        mode = self.ui.mode
        if mode == KIND_MOVIE:
            self.session.ensure_assembly()
        if self._guard(lambda: self.session.review(mode)):
            self.sync()

    def simulate(self) -> None:
        mode = self.ui.mode
        call = {KIND_QUICK: self.session.simulate_quick, KIND_STORY: self.session.simulate_storyboard,
                KIND_MOVIE: self.session.simulate_assembly}[mode]  # fmt: skip
        if self._guard(call):
            self.sync()
            self.inspect_results()

    def inspect_results(self) -> None:
        mode = self.ui.mode
        if mode == KIND_QUICK:
            self.quick_panel.show_latest()
            self.quick_panel.review_scroll.verticalScrollBar().setValue(0)
        elif mode == KIND_STORY:
            self.story_panel.show_latest()
        else:
            self.movie_panel.show_latest()

    def send_to_movie(self) -> None:
        run = self.session.latest_run(self.ui.mode)
        if run:
            self.add_clips([c.clip_id for c in run.clips if c.completed])

    def add_clips(self, clip_ids: list[str]) -> None:
        added = False
        try:
            self.session.add_clips(clip_ids)
            added = True
        except MotionRefused as exc:
            self.warn("Not added", str(exc))
        if added:
            self.banner.hide()
        self.set_mode(KIND_MOVIE)

    # ----------------------------------------------------------------- quick handlers
    def change_quick(self, **changes) -> None:
        if self.session.quick.draft is None:
            return
        if self._guard(lambda: self.session.update_quick(**changes)):
            self.sync()

    def pick_source(self, key: str | None) -> None:
        if key and self._guard(lambda: self._select(key, "picker")):
            self.sync()
        else:
            self.sync()

    def _select(self, key: str, origin: str) -> bool:
        ok = self.session.select_source(key, origin=origin)
        if not ok:
            if self._confirm_replacement(key) == Replacement.REPLACE:
                self.session.select_source(key, Replacement.REPLACE, origin=origin)
                return True
        return ok

    def receive_source(self, key: str, origin: str) -> bool:
        """H4. Returns whether the caller should navigate to Motion."""
        try:
            selected = self.session.receive_source(key, origin)
            if not selected:
                if self._confirm_replacement(key) != Replacement.REPLACE:
                    return False
                selected = self.session.receive_source(key, origin, Replacement.REPLACE)
        except MotionRefused as exc:
            self.warn("Source refused", str(exc))
            return False
        self.banner.hide()
        self.set_mode(KIND_QUICK)
        return selected

    def _confirm_replacement(self, key: str) -> Replacement:
        box = QMessageBox(self)
        box.setWindowTitle("Replace Motion draft?")
        box.setTextFormat(Qt.TextFormat.PlainText)
        current = self.session.quick.draft.source_key if self.session.quick.draft else "none"
        box.setText(f"Open {key} in Motion? The current Motion draft ({current}) will be replaced.")
        box.setInformativeText(
            "Cancel keeps your draft exactly as it is. Replace starts a fresh draft: preview "
            "approval and experimental consent are never carried over."
        )
        cancel = box.addButton(Replacement.CANCEL, QMessageBox.ButtonRole.RejectRole)
        replace_button = box.addButton(Replacement.REPLACE, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return Replacement.REPLACE if box.clickedButton() is replace_button else Replacement.CANCEL

    def accept_media(self, kind: str) -> None:
        if self._guard(lambda: self.session.accept_source_media(kind)):
            self.sync()

    def set_consent(self, kind: str, on: bool) -> None:
        def apply() -> None:
            if on:
                self.session.grant_consent(kind)
            else:
                self.session.revoke_consent(kind)

        self._guard(apply)
        self.sync()

    # ------------------------------------------------------------- storyboard handlers
    def change_story(self, **changes) -> None:
        if self._guard(lambda: self.session.update_story(**changes)):
            self.sync()

    def change_story_source(self, key: str | None) -> None:
        if key is None:
            return
        problems = usable_image(self.session.catalog, key)
        if problems:
            self.warn("Source refused", problems[0])
            self.sync()
            return
        digest = self.session.catalog.get(key).digest
        self.change_story(source_key=key, source_digest=digest)

    def select_shot(self, shot_id: str) -> None:
        self.ui.shot = shot_id
        self.sync()
        self.story_panel.strip.focus_card(shot_id)

    def change_shot(self, **changes) -> None:
        if self.ui.shot and self._guard(lambda: self.session.update_shot(self.ui.shot, **changes)):
            self.sync()

    def add_shot(self) -> None:
        shot = None

        def apply() -> None:
            nonlocal shot
            shot = self.session.add_shot(after=self.ui.shot)

        if self._guard(apply):
            self.ui.shot = shot.shot_id
            self.sync()

    def duplicate_shot(self) -> None:
        copy = None

        def apply() -> None:
            nonlocal copy
            copy = self.session.duplicate_shot(self.ui.shot)

        if self._guard(apply):
            self.ui.shot = copy.shot_id
            self.sync()

    def remove_shot(self) -> None:
        draft = self.session.story.draft
        ids = [s.shot_id for s in draft.shots]
        index = ids.index(self.ui.shot)
        if self._guard(lambda: self.session.remove_shot(self.ui.shot)):
            self.ui.shot = None
            neighbours = [s.shot_id for s in self.session.story.draft.shots]
            self.ui.shot = neighbours[min(index, len(neighbours) - 1)]
            self.sync()

    def move_shot(self, delta: int) -> None:
        if self.ui.mode == KIND_STORY and self.ui.shot:
            self.session.move_shot(self.ui.shot, delta)
            self.sync()

    def accept_anchor(self) -> None:
        if self.ui.shot and self._guard(lambda: self.session.accept_anchor_media(self.ui.shot)):
            self.sync()

    def save_story(self) -> None:
        try:
            self.session.save_storyboard()
        except StaleSave as exc:
            self.warn("Stale save refused", str(exc), "blocked")
            self.sync()
            return
        self.banner.set_message(
            "Saved (mock)",
            "In-memory revision recorded. No file was written and no consent was saved.",
            "success",
        )
        self.banner.show()
        self.sync()

    def save_story_as(self, suffix: str | None) -> None:
        title = self.session.ensure_storyboard().title
        new = f"Copy of {title}" if suffix is None else f"{title}{suffix}"
        if self._guard(lambda: self.session.save_storyboard_as(new)):
            self.ui.shot = None
            self.sync()

    def new_story(self) -> None:
        if not self.session.new_storyboard(None):
            if self._confirm_story("Start a new Storyboard") != Replacement.REPLACE:
                return
            self.session.new_storyboard(None, Replacement.REPLACE)
        self.ui.shot = None
        self.sync()

    def open_saved(self) -> None:
        sid = self.story_panel.open_combo.currentData()
        if not sid:
            return
        if not self.session.open_storyboard(sid):
            if self._confirm_story(f"Open {sid}") != Replacement.REPLACE:
                return
            self.session.open_storyboard(sid, Replacement.REPLACE)
        self.ui.shot = None
        self.sync()

    def other_session_saves(self) -> None:
        draft = self.session.story.draft
        if draft and self._guard(lambda: self.session.store.external_save(draft.storyboard_id)):
            self.warn(
                "Fixture",
                "Another session saved first. Your next Save will be refused as stale.",
                "info",
            )

    def reopen_run(self) -> None:
        run_id = self.story_panel.run_combo.currentData()
        if not run_id:
            return
        try:
            if not self.session.storyboard_from_run(run_id):
                if self._confirm_story(f"Reopen {run_id}") != Replacement.REPLACE:
                    return
                self.session.storyboard_from_run(run_id, Replacement.REPLACE)
        except MotionRefused as exc:
            self.warn("Cannot reopen", str(exc))
            return
        self.banner.set_message(
            "New draft",
            f"{run_id} reopened as a NEW Storyboard draft. The simulated result is unchanged.",
            "info",
        )
        self.banner.show()
        self.ui.shot = None
        self.sync()

    def _confirm_story(self, what: str) -> Replacement:
        box = QMessageBox(self)
        box.setWindowTitle("Replace Storyboard draft?")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"{what}? The current Storyboard draft has unsaved changes.")
        box.setInformativeText(
            "Cancel keeps it. Replace discards the unsaved edits (simulated results stay)."
        )
        cancel = box.addButton(Replacement.CANCEL, QMessageBox.ButtonRole.RejectRole)
        replace_button = box.addButton(Replacement.REPLACE, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return Replacement.REPLACE if box.clickedButton() is replace_button else Replacement.CANCEL

    def undo(self) -> None:
        mode = self.ui.mode
        {
            KIND_QUICK: self.session.quick,
            KIND_STORY: self.session.story,
            KIND_MOVIE: self.session.assembly,
        }[mode].undo()
        self.sync()

    def redo(self) -> None:
        mode = self.ui.mode
        {
            KIND_QUICK: self.session.quick,
            KIND_STORY: self.session.story,
            KIND_MOVIE: self.session.assembly,
        }[mode].redo()
        self.sync()

    # ----------------------------------------------------------------- movie handlers
    def change_assembly(self, **changes) -> None:
        if self._guard(lambda: self.session.update_assembly(**changes)):
            self.sync()

    def move_item(self, item_id: str, delta: int) -> None:
        if self._guard(lambda: self.session.move_item(item_id, delta)):
            self.sync()

    def remove_item(self, item_id: str) -> None:
        if self._guard(lambda: self.session.remove_item(item_id)):
            self.sync()

    def set_trim(self, item_id: str, start: int, end: int) -> None:
        if self._guard(lambda: self.session.set_trim(item_id, start, end)):
            self.sync()
