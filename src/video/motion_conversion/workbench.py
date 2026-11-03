"""The operator-level facade over inventory, Blender conversion, library import and conditioning preview (PR-VID-MOTION-354).

One small object the controller can delegate to, so the controller stays a coordinator.  Every method is an explicit
operator action, blocking (the view runs it on a worker) and cancellable; none builds a job, queues work, starts a model
runtime, talks to a network or uses a GPU.  The chosen Blender executable is remembered in a per-user pointer file next to the
Motion Library pointer, never in the repository.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.video import resolve_ffmpeg_executable
from src.utils.atomic_io import atomic_write_json
from src.video.driving_video_inspection import inspect_driving_video
from src.video.motion_conversion import conditioning_preview as cond
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion import diagnostics as diag
from src.video.motion_conversion.blender import (
    BlenderInstall,
    BlenderProblem,
    discover_blender,
    verify_blender,
)
from src.video.motion_conversion.conversion_service import (
    PURPOSE_ACCEPTED,
    PURPOSE_PREVIEW,
    ConversionResult,
    MotionConverter,
    ProbeError,
    preview_plan,
    sweep_stale_work,
)
from src.video.motion_conversion.fbx_scan import scan_fbx
from src.video.motion_conversion.inventory import (
    ROUTE_BVH_SKELETON,
    ROUTE_FBX_CHARACTER,
    ROUTE_FBX_SKELETON,
    STATE_READY,
    classify_fbx,
    sha256_file,
)
from src.video.motion_conversion.library_bridge import accept_conversion
from src.video.motion_conversion.rig_compat import BindingPlan, identify_rig, plan_binding
from src.video.motion_library.config import config_path
from src.video.motion_library.importer import ImportOutcome
from src.video.motion_library.store import MotionLibraryStore

SETTINGS_NAME = "motion_conversion.json"
BLENDER_KEY = "blender_executable"
CONVERSIONS_DIRNAME = "conversions"
CONVERTIBLE_SUFFIXES = (".fbx", ".bvh")

_ROUTE_BY_INVENTORY = {
    ROUTE_FBX_CHARACTER: cp.SOURCE_FBX_CHARACTER,
    ROUTE_FBX_SKELETON: cp.SOURCE_FBX_SKELETON,
    ROUTE_BVH_SKELETON: cp.SOURCE_BVH,
}


def settings_path() -> Path:
    return config_path().with_name(SETTINGS_NAME)


def load_blender_setting() -> str:
    try:
        payload = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = payload.get(BLENDER_KEY) if isinstance(payload, dict) else ""
    return value.strip() if isinstance(value, str) else ""


def save_blender_setting(executable: str | Path) -> None:
    atomic_write_json(
        settings_path(),
        {
            "schema": "stablenew.motion-conversion-settings",
            "version": 1,
            BLENDER_KEY: str(executable),
        },
        indent=2,
    )


@dataclass(frozen=True, slots=True)
class SourceFacts:
    """What a chosen animation file is, from the bounded header scan (no Blender, no import)."""

    path: str
    sha256: str
    kind: str  # "fbx" | "bvh"
    route: str  # a conversion_plan SOURCE_* route, or "" when it cannot be converted
    ready: bool
    reason: str
    has_mesh: bool
    has_skin: bool
    bone_names: tuple[str, ...]
    rig_family: str
    rig_fingerprint: str


class ConversionWorkbench:
    def __init__(
        self,
        *,
        library_root: str | Path,
        blender: BlenderInstall | None = None,
        ffmpeg: str | Path | None = None,
        converter_factory: Callable[[BlenderInstall, Path, str], MotionConverter] | None = None,
        diagnostics_dir: str | Path | None = None,
    ) -> None:
        self._output_root = Path(library_root) / CONVERSIONS_DIRNAME
        self._diagnostics_dir = Path(diagnostics_dir) if diagnostics_dir else None
        self._last_diagnostic = ""
        self._blender = blender
        self._ffmpeg = str(ffmpeg) if ffmpeg else ""
        self._factory = converter_factory

    # ------------------------------------------------------------------ tools

    def ffmpeg(self) -> str:
        if not self._ffmpeg:
            found = resolve_ffmpeg_executable()
            if found is None:
                raise BlenderProblem("FFmpeg was not found, so converted frames cannot be encoded.")
            self._ffmpeg = str(found)
        return self._ffmpeg

    def blender(self) -> BlenderInstall | None:
        return self._blender

    def select_blender(
        self, executable: str | Path = "", cancel: threading.Event | None = None
    ) -> BlenderInstall:
        """Verify an explicit executable (or search the usual places) and remember it.  Raises ``BlenderProblem``."""

        install = (
            verify_blender(executable, cancel=cancel)
            if executable
            else discover_blender(cancel=cancel)
        )
        if install is None:
            raise BlenderProblem(
                "Blender was not found. Install Blender 4.2 or newer yourself and choose its blender.exe; "
                "StableNew never downloads or installs it."
            )
        save_blender_setting(install.executable)
        self._blender = install
        return install

    def remembered_blender(self, cancel: threading.Event | None = None) -> BlenderInstall | None:
        saved = load_blender_setting()
        if not saved:
            return None
        try:
            self._blender = verify_blender(saved, cancel=cancel)
        except BlenderProblem:
            return None
        return self._blender

    def _converter(self) -> MotionConverter:
        if self._blender is None:
            raise BlenderProblem("Choose a Blender executable first.")
        if self._factory is not None:
            return self._factory(self._blender, self._output_root, self.ffmpeg())
        return MotionConverter(
            self._blender,
            self._output_root,
            ffmpeg=self.ffmpeg(),
            diagnostics_dir=self._diagnostics_dir or diag.default_directory(),
        )

    def output_root(self) -> Path:
        """Where converted clips are published (the Motion Library's ``conversions`` folder)."""

        return self._output_root

    def prepare_batch(self) -> int:
        """Remove work folders an interrupted run left behind (only ones carrying this application's marker)."""

        return sweep_stale_work(self._output_root)

    def last_diagnostic(self) -> str:
        """The redacted report of the most recent failed Blender step this workbench ran (empty when it succeeded)."""

        return self._last_diagnostic

    @staticmethod
    def diagnostic_text(path: str | Path) -> str:
        return diag.report_text(path)

    # ------------------------------------------------------------------ inspect

    def describe_source(
        self, path: str | Path, cancel: threading.Event | None = None
    ) -> SourceFacts:
        target = Path(path)
        kind = target.suffix.lower().lstrip(".")
        if target.suffix.lower() not in CONVERTIBLE_SUFFIXES or not target.is_file():
            return SourceFacts(
                str(target),
                "",
                kind,
                "",
                False,
                "Choose an existing .fbx or .bvh file.",
                False,
                False,
                (),
                "",
                "",
            )
        digest = sha256_file(target, cancel)
        if kind == "bvh":
            head = target.read_bytes()[:4096].decode("utf-8", "replace").lstrip("﻿ \t\r\n")
            valid = head.upper().startswith("HIERARCHY") and "ROOT" in head.upper()
            return SourceFacts(
                str(target),
                digest,
                kind,
                cp.SOURCE_BVH if valid else "",
                valid,
                "BVH skeleton animation: rendered as a skeleton (no character mesh)."
                if valid
                else "Not a valid BVH file.",
                False,
                False,
                (),
                "",
                "",
            )
        scan = scan_fbx(target)
        state, reason, route = classify_fbx(scan)
        rig = identify_rig(scan.bone_names)
        return SourceFacts(
            str(target),
            digest,
            kind,
            _ROUTE_BY_INVENTORY.get(route, ""),
            state == STATE_READY,
            reason,
            scan.has_mesh,
            scan.has_skin,
            scan.bone_names,
            rig.family if scan.bone_names else "",
            rig.fingerprint if scan.bone_names else "",
        )

    def probe(self, facts: SourceFacts, cancel: threading.Event | None = None) -> cp.AnimationProbe:
        """One bounded Blender child reading the animation's rate, range and bones (explicit operator action)."""

        self._last_diagnostic = ""
        try:
            return self._converter().probe(
                facts.path, facts.kind, transform=dict(cp.IMPORT_TRANSFORM), cancel=cancel
            )
        except ProbeError as exc:
            self._last_diagnostic = exc.result.diagnostic_path if exc.result is not None else ""
            raise

    def check_character(
        self, facts: SourceFacts, character_path: str | Path
    ) -> tuple[SourceFacts, BindingPlan]:
        """Bone compatibility between an animation-only skeleton and a reference character; never guesses."""

        character = self.describe_source(character_path)
        return character, plan_binding(facts.bone_names, character.bone_names)

    # ------------------------------------------------------------------ plan and convert

    def build_plan(
        self,
        facts: SourceFacts,
        probe: cp.AnimationProbe,
        *,
        workflow_spec: Any | None = None,
        **options: Any,
    ) -> cp.ConversionPlan:
        if not facts.ready or not facts.route:
            raise cp.ConversionPlanError(facts.reason or "This file cannot be converted.")
        return cp.build_plan(
            source_path=facts.path,
            source_sha256=facts.sha256,
            source_route=options.pop("route", facts.route),
            probe=probe,
            rig_fingerprint=facts.rig_fingerprint,
            workflow_spec=workflow_spec,
            **options,
        )

    def plan_from_request(
        self,
        facts: SourceFacts,
        probe: cp.AnimationProbe,
        workflow_spec: Any | None,
        request: dict[str, Any],
        default_frames: int,
        character_state: tuple[SourceFacts | None, BindingPlan | None] = (None, None),
    ) -> cp.ConversionPlan:
        """Pure: turn the dialog's choices into a frozen plan (or raise ``ConversionPlanError``)."""

        options = dict(request)
        options["output_frames"] = options.get("output_frames") or default_frames
        character, binding = character_state
        if (
            character is not None
            and binding is not None
            and binding.can_apply
            and facts.route == cp.SOURCE_FBX_SKELETON
        ):
            options.update(
                route=cp.SOURCE_FBX_ON_CHARACTER,
                character_path=character.path,
                character_sha256=character.sha256,
                binding=binding,
            )
        return self.build_plan(facts, probe, workflow_spec=workflow_spec, **options)

    def convert(
        self,
        plan: cp.ConversionPlan,
        *,
        preview: bool = False,
        cancel: threading.Event | None = None,
        warnings: tuple[str, ...] = (),
    ) -> ConversionResult:
        converter = self._converter()
        if preview:
            result = converter.convert(preview_plan(plan), purpose=PURPOSE_PREVIEW, cancel=cancel)
        else:
            result = converter.convert(
                plan, purpose=PURPOSE_ACCEPTED, cancel=cancel, warnings=warnings
            )
        self._last_diagnostic = result.diagnostic_path
        return result

    # ------------------------------------------------------------------ library and conditioning

    def accept(
        self,
        store: MotionLibraryStore,
        result_directory: str | Path,
        *,
        name: str = "",
        tags: tuple[str, ...] = (),
        usage_terms: str = "",
        cancel: threading.Event | None = None,
    ) -> ImportOutcome:
        return accept_conversion(
            store,
            result_directory,
            name=name,
            extra_tags=tags,
            usage_terms=usage_terms,
            inspect=lambda p, c: inspect_driving_video(p, cancel=c),
            cancel=cancel,
        )

    def conditioning_preview(
        self,
        video: str | Path,
        *,
        target_size: tuple[int, int],
        video_sha256: str = "",
        derivative_of_sha256: str = "",
        window_start: int = 0,
        window_frames: int = 0,
        cancel: threading.Event | None = None,
    ) -> cond.ConditioningPreview:
        inspection = inspect_driving_video(video, frame_count=0, cancel=cancel)
        if inspection.facts is None:
            return cond.ConditioningPreview(
                cond.EXACTNESS_APPROXIMATE,
                cond.EXACTNESS_REASON,
                str(video),
                video_sha256,
                derivative_of_sha256,
                None,
                0,
                0,
                0,
                target_size[0],
                target_size[1],
                window_start,
                window_frames,
                error=inspection.issues[0].message
                if inspection.issues
                else "The video could not be inspected.",
            )
        return cond.build_preview(
            video,
            ffmpeg=self.ffmpeg(),
            facts=inspection.facts,
            target_size=target_size,
            video_sha256=video_sha256,
            derivative_of_sha256=derivative_of_sha256,
            window_start=window_start,
            window_frames=window_frames,
            cancel=cancel,
        )
