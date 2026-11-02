"""Toolkit-neutral state of the "Convert Motion" dialog (PR-VID-MOTION-354).

Walks the operator through Inspect -> choose profile -> Preview -> Convert -> Add to Motion Library, plus Preview
Conditioning.  It imports no Tk and starts no process of its own: every Blender, FFmpeg, hashing or disk call is an injected
port run on the injected ``BackgroundWorkRunner``; results return on the UI thread and are dropped when a newer request
superseded them or the dialog closed.  Nothing here builds a job, queues, prepares a motion source or edits the Video
Workflow form: after a clip is added to the Motion Library the operator uses the library's existing *Use as Driving Video* and
*Prepare Motion Source*.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.blender import BlenderInstall
from src.video.motion_conversion.conditioning_preview import ConditioningPreview
from src.video.motion_conversion.conversion_service import ConversionResult
from src.video.motion_conversion.ports import ConversionPorts
from src.video.motion_conversion.workbench import SourceFacts
from src.video.motion_library.importer import ImportOutcome

NEXT_STEP_TEXT = (
    "Added to the Motion Library. Select it there, choose Use as Driving Video, then Prepare Motion Source "
    "and Preview the job as usual."
)
SKELETON_NOTE = "A skeleton render is a visual motion reference, not an OpenPose map."


@dataclass
class ConversionOptions:
    profile: str = cp.PROFILE_CHARACTER
    camera: str = cp.CAMERA_FRONT
    camera_mode: str = cp.CAMERA_STATIC
    root_motion: str = cp.ROOT_PRESERVE
    start_seconds: str = "0"
    frames: str = ""
    orientation: str = "portrait"
    character_path: str = ""

    def size(self) -> tuple[int, int]:
        return (
            (cp.DEFAULT_HEIGHT, cp.DEFAULT_WIDTH)
            if self.orientation == "landscape"
            else (cp.DEFAULT_WIDTH, cp.DEFAULT_HEIGHT)
        )


@dataclass(frozen=True)
class ConversionView:
    busy: bool
    status: str
    blender_text: str
    source_lines: tuple[str, ...]
    plan_lines: tuple[str, ...]
    plan_error: str
    result_lines: tuple[str, ...]
    conditioning: ConditioningPreview | None
    can_choose_source: bool
    can_inspect: bool
    can_preview: bool
    can_convert: bool
    can_accept: bool
    can_condition: bool
    allowed_profiles: tuple[str, ...]
    legal_frames: tuple[int, ...]
    next_step: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _rational_text(value: Fraction) -> str:
    return f"{float(value):g}"


class MotionConversionSession:
    def __init__(
        self,
        *,
        ports: ConversionPorts,
        runner: BackgroundWorkRunner,
        on_change: Callable[[], None] | None = None,
        on_accepted: Callable[[str], None] | None = None,
    ) -> None:
        self._ports = ports
        self._runner = runner
        self._on_change = on_change
        self._on_accepted = on_accepted
        self._closed = False
        self._tokens: dict[str, int] = {}
        self._cancels: dict[str, threading.Event] = {}
        self.options = ConversionOptions()
        self.install: BlenderInstall | None = None
        self.facts: SourceFacts | None = None
        self.probe: cp.AnimationProbe | None = None
        self.plan: cp.ConversionPlan | None = None
        self.plan_error = ""
        self.preview_result: ConversionResult | None = None
        self.result: ConversionResult | None = None
        self.accepted: ImportOutcome | None = None
        self.conditioning: ConditioningPreview | None = None
        self.binding: Any = None
        self.character: SourceFacts | None = None
        self.busy = False
        self.status = "Choose Blender and an animation file (.fbx or .bvh)."

    # ------------------------------------------------------------------ plumbing

    def _next(self, kind: str) -> int:
        self._tokens[kind] = self._tokens.get(kind, 0) + 1
        previous = self._cancels.pop(kind, None)
        if previous is not None:
            previous.set()
        self._cancels[kind] = threading.Event()
        return self._tokens[kind]

    def _live(self, kind: str, token: int) -> bool:
        return not self._closed and self._tokens.get(kind) == token

    def _notify(self) -> None:
        if self._on_change is not None and not self._closed:
            self._on_change()

    def _run(
        self,
        kind: str,
        work: Callable[[threading.Event], Any],
        finish: Callable[[Any], None],
        busy_text: str,
    ) -> None:
        token = self._next(kind)
        cancel = self._cancels[kind]
        self.busy = True
        self.status = busy_text
        self._notify()

        def done(outcome: WorkOutcome) -> None:
            if not self._live(kind, token):
                return
            self.busy = False
            if outcome.error:
                self.status = f"{busy_text.rstrip('.')} failed: {outcome.error}"
                self._notify()
                return
            finish(outcome.value)

        self._runner.start(
            f"motion-conversion-{kind}", lambda: WorkOutcome(value=work(cancel)), done
        )

    def cancel_work(self) -> None:
        for event in self._cancels.values():
            event.set()

    def close(self) -> None:
        self._closed = True
        self.cancel_work()
        self._on_change = None
        self._on_accepted = None

    # ------------------------------------------------------------------ steps

    def load_remembered_blender(self) -> None:
        def finished(install: BlenderInstall | None) -> None:
            self.install = install
            if install is None:
                self.status = (
                    "Blender is not selected. Choose its blender.exe (StableNew never installs it)."
                )
            self._notify()

        self._run(
            "blender", lambda c: self._ports.remembered_blender(c), finished, "Checking Blender..."
        )

    def choose_blender(self, executable: str) -> None:
        def finished(install: BlenderInstall) -> None:
            self.install = install
            self.status = f"Using {install.version_text or 'Blender'} (CPU rendering only)."
            self._notify()

        self._run(
            "blender",
            lambda c: self._ports.select_blender(executable, c),
            finished,
            "Verifying Blender...",
        )

    def choose_source(self, path: str) -> None:
        def finished(facts: SourceFacts) -> None:
            self.facts, self.probe, self.plan, self.result, self.accepted = (
                facts,
                None,
                None,
                None,
                None,
            )
            self.preview_result = None
            self.conditioning = None
            self.plan_error = ""
            self.binding = None
            self.character = None
            self.options.character_path = ""
            self.options.profile = (
                cp.PROFILE_CHARACTER if facts.has_mesh and facts.ready else cp.PROFILE_SKELETON
            )
            self.status = facts.reason
            self._notify()

        self._run(
            "describe", lambda c: self._ports.describe(path, c), finished, "Reading the file..."
        )

    def inspect(self) -> None:
        facts = self.facts
        if facts is None or not facts.ready:
            self.status = "Choose a convertible animation file first."
            self._notify()
            return
        if self.install is None:
            self.status = "Choose Blender first; it reads the animation's length and frame rate."
            self._notify()
            return

        def finished(probe: cp.AnimationProbe) -> None:
            self.probe = probe
            self.status = (
                f"Animation: {_rational_text(probe.duration_seconds)} s at {_rational_text(probe.fps)} fps; "
                f"{len(probe.bone_names)} bones."
            )
            self._refresh_plan()

        self._run(
            "probe",
            lambda c: self._ports.probe(facts, c),
            finished,
            "Inspecting the animation in Blender...",
        )

    def check_character(self, character_path: str) -> None:
        facts = self.facts
        if facts is None:
            return

        def finished(value: tuple[SourceFacts, Any]) -> None:
            character, binding = value
            self.binding, self.character = binding, character
            self.options.character_path = character.path if binding.compatible else ""
            self.status = (
                "The character's bones match the animation exactly; it can be used."
                if binding.compatible
                else f"Automated retargeting is refused: {binding.reason}"
            )
            self._refresh_plan()

        self._run(
            "character",
            lambda c: self._ports.check_character(facts, character_path),
            finished,
            "Checking bones...",
        )

    def set_options(self, **changes: Any) -> None:
        for key, value in changes.items():
            if hasattr(self.options, key):
                setattr(self.options, key, value)
        self.result = self.preview_result = self.accepted = None
        self._refresh_plan()

    def _refresh_plan(self) -> None:
        self.plan = None
        self.plan_error = ""
        facts, probe = self.facts, self.probe
        if facts is not None and probe is not None and facts.ready:
            options = self.options
            width, height = options.size()
            request = {
                "profile": options.profile,
                "camera": options.camera,
                "camera_mode": options.camera_mode,
                "root_motion": options.root_motion,
                "start_seconds": options.start_seconds,
                "output_frames": options.frames,
                "width": width,
                "height": height,
            }
            try:
                self.plan = self._ports.build_plan(
                    facts, probe, self._ports.workflow(), request, (self.character, self.binding)
                )
            except cp.ConversionPlanError as exc:
                self.plan_error = str(exc)
        self._notify()

    def render_preview(self) -> None:
        self._convert(True)

    def convert(self) -> None:
        self._convert(False)

    def _convert(self, preview: bool) -> None:
        plan = self.plan
        if plan is None or self.install is None:
            self.status = "Inspect the animation and fix the settings first."
            self._notify()
            return

        def finished(result: ConversionResult) -> None:
            if preview:
                self.preview_result = result
            else:
                self.result, self.accepted = result, None
            self.status = (
                ("Preview ready." if preview else "Converted and verified.")
                if result.ok
                else f"Not converted: {result.reason}"
            )
            self._notify()

        self._run(
            "preview" if preview else "convert",
            lambda c: self._ports.convert(plan, preview, c),
            finished,
            "Rendering a short preview in Blender (CPU)..."
            if preview
            else "Converting in Blender (CPU)...",
        )

    def accept(self, name: str, tags: tuple[str, ...], usage_terms: str) -> None:
        result = self.result
        if result is None or not result.ok:
            self.status = "Convert the clip first; only a full, verified conversion can be added."
            self._notify()
            return

        def finished(outcome: ImportOutcome) -> None:
            self.accepted = outcome
            if outcome.status == "failed":
                self.status = f"Not added: {outcome.reason}"
            else:
                self.status = NEXT_STEP_TEXT
                if self._on_accepted is not None and outcome.asset_id:
                    self._on_accepted(outcome.asset_id)
            self._notify()

        self._run(
            "accept",
            lambda c: self._ports.accept(result.directory, name, tags, usage_terms, c),
            finished,
            "Adding to the Motion Library...",
        )

    def preview_conditioning(self) -> None:
        result = self.result or self.preview_result
        plan = self.plan
        if result is None or not result.ok or plan is None:
            self.status = "Convert or preview a clip first."
            self._notify()
            return

        def finished(value: ConditioningPreview) -> None:
            self.conditioning = value
            self.status = (
                "Conditioning preview ready (approximate, advisory)." if value.ok else value.error
            )
            self._notify()

        size = (plan.width, plan.height)
        self._run(
            "conditioning",
            lambda c: self._ports.conditioning(
                result.video_path, result.output_sha256, plan.source_sha256, size, c
            ),
            finished,
            "Building the conditioning preview...",
        )

    # ------------------------------------------------------------------ view

    def view(self) -> ConversionView:
        workflow = self._ports.workflow()
        facts, plan, probe = self.facts, self.plan, self.probe
        source_lines: tuple[str, ...] = ()
        if facts is not None:
            source_lines = (
                f"File: {facts.path}",
                f"Type: {facts.kind.upper()}"
                + (f", SHA-256 {facts.sha256}" if facts.sha256 else ""),
                facts.reason,
            )
            if facts.rig_family:
                source_lines += (f"Rig: {facts.rig_family} ({len(facts.bone_names)} bones)",)
            if probe is not None:
                source_lines += (
                    f"Length {_rational_text(probe.duration_seconds)} s at {_rational_text(probe.fps)} fps",
                )
        plan_lines: tuple[str, ...] = ()
        if plan is not None:
            plan_lines = (
                f"{cp.PROFILE_LABELS[plan.profile]}; {plan.camera.replace('_', '-')} view; "
                f"{'camera follows the subject' if plan.camera_mode == cp.CAMERA_TRACKING else 'static camera'}",
                "Original root motion is kept."
                if plan.root_motion == cp.ROOT_PRESERVE
                else "Root translation is REMOVED (in place).",
                f"{plan.output_frames} frames at {plan.target_fps} fps, {plan.width}x{plan.height}, from "
                f"{_rational_text(plan.start_seconds)} s"
                + (" (resampled in real time from the file's rate)" if plan.retimed else ""),
                f"Target workflow: {workflow.display_name or 'none selected (generic length rule)'}",
                f"Plan digest {plan.digest[:16]}",
            )
            if plan.profile == cp.PROFILE_SKELETON:
                plan_lines += (SKELETON_NOTE,)
        result_lines: tuple[str, ...] = ()
        shown = self.result or self.preview_result
        if shown is not None:
            result_lines = (
                (f"Reason: {shown.reason}",)
                if not shown.ok
                else (
                    f"{'Preview' if shown is self.preview_result and shown is not self.result else 'Converted'} video: {shown.video_path}",
                    f"{shown.frame_count} frames, SHA-256 {shown.output_sha256}",
                    f"Record: {shown.provenance_path}",
                )
            )
        profiles = [cp.PROFILE_SKELETON]
        bound = self.binding is not None and self.binding.compatible and self.character is not None
        if facts is not None and facts.ready and (facts.has_mesh or bound):
            profiles = [cp.PROFILE_CHARACTER, cp.PROFILE_SILHOUETTE, cp.PROFILE_SKELETON]
        ready_to_plan = (
            facts is not None and facts.ready and self.install is not None and not self.busy
        )
        return ConversionView(
            busy=self.busy,
            status=self.status,
            blender_text=(
                f"{self.install.version_text} - {self.install.executable}"
                if self.install
                else "Blender: not selected"
            ),
            source_lines=source_lines,
            plan_lines=plan_lines,
            plan_error=self.plan_error,
            result_lines=result_lines,
            conditioning=self.conditioning,
            can_choose_source=not self.busy,
            can_inspect=bool(ready_to_plan),
            can_preview=plan is not None and not self.busy and self.install is not None,
            can_convert=plan is not None and not self.busy and self.install is not None,
            can_accept=self.result is not None
            and self.result.ok
            and not self.busy
            and (self.accepted is None or self.accepted.status == "failed"),
            can_condition=(
                self.result is not None
                and self.result.ok
                or self.preview_result is not None
                and self.preview_result.ok
            )
            and plan is not None
            and not self.busy,
            allowed_profiles=tuple(profiles),
            legal_frames=workflow.legal_frames,
            next_step=NEXT_STEP_TEXT
            if self.accepted is not None and self.accepted.status != "failed"
            else "",
            warnings=self.conditioning.warnings if self.conditioning is not None else (),
        )
