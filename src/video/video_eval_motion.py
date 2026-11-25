"""Case-level driving-motion binding for video eval suites (PR-VID-MOTION-410).

A *motion case* is an ordinary eval case (one source image, prompts) that also binds one driving-motion reference and
says what the intended subject is expected to do. The binding lives on the case, not on an arm, so one motion asset can
be evaluated against many source images and every arm of a suite sees the same driver without duplicating arms.

This module is pure vocabulary, validation and fact extraction. It builds no NJR, queues nothing, starts no runtime and
decodes no video: the production builders (``VideoWorkflowNjrBuilder``) still compile every job, and the only media
operation here is hashing the bound files. Three honesty rules shape it:

* a local driving video is a local driving video. It is never described as a Motion Library asset or as the output of a
  known job unless the case carries an explicit library binding whose SHA-256 equals the bound file's;
* a driving reference is never dropped to make an arm queueable. An arm whose workflow takes no driving video refuses the
  motion case (``driving_support_error``);
* different arms may legitimately need different prepared derivatives (workflow, version and length are part of the
  preparation contract). Each is recorded and disclosed; a derivative is shared across arms only when the contract is
  identical.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MOTION_BLOCK = "motion"
#: A suite that carries a motion case is ``stablenew.video-eval-suite.v2``; v1 readers refuse it instead of ignoring it.
MOTION_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("head_turn", "Head turn"),
    ("hand_wave", "Right-hand wave"),
    ("raise_arms", "Raise both arms"),
    ("sit_down", "Sit down"),
    ("turn_around", "Turn around"),
    ("walk_forward", "Walk forward"),
    ("other", "Other"),
)
MOTION_CATEGORY_KEYS = tuple(key for key, _label in MOTION_CATEGORIES)
MOTION_CATEGORY_LABELS = dict(MOTION_CATEGORIES)

PREP_AS_IS = "as_is"
PREP_WORKFLOW = "workflow_prepared"
PREPARATION_MODES = (PREP_AS_IS, PREP_WORKFLOW)
FPS_CONVERSIONS = ("none", "workflow_rate")
SOURCE_LIBRARY = "library_asset"
SOURCE_LOCAL = "local_video"

DRIVING_SUFFIXES = frozenset({".mp4", ".webm", ".mov", ".mkv"})
#: Form keys a motion case owns. An arm may not set them: the driver comes from the case.
CASE_OWNED_FORM_KEYS = ("pose_video_path", "motion_library_asset", "prepared_motion_source")
CASE_OWNED_CONTROLS = ("pose_prompt",)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TEXT_LIMIT = 600
_SHORT_LIMIT = 80
_MAX_PHASES = 8
_MAX_COMPAT = 12
_HASH_CHUNK = 1024 * 1024


def as_mapping(value: Any) -> Mapping[str, Any]:
    """``value`` when it is a mapping, else an empty one (typed replacement for ``x if isinstance(x, Mapping) else {}``)."""

    return value if isinstance(value, Mapping) else {}


def as_mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


class MotionBindingError(ValueError):
    """The motion block of a case does not describe a usable, verifiable driving reference."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MotionBindingError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any, what: str, *, required: bool = False, limit: int = _TEXT_LIMIT) -> str:
    text = " ".join(str(value or "").split())
    _require(not required or bool(text), f"{what} is required")
    _require(len(text) <= limit, f"{what} is longer than {limit} characters")
    return text


def _frame(value: Any, what: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{what} must be a whole frame number (0 or more)",
    )
    return int(value)


@dataclass(frozen=True)
class MotionBinding:
    """One case's driving reference, intended action and expectations. Frozen; JSON-plain via ``to_record``."""

    driving_path: Path
    driving_sha256: str
    source: str
    action: str
    motion_prompt: str
    category: str
    expected_outcome: str
    #: ``{"asset_id", "sha256", "derived_from"?}``: the explicit Motion Library binding, or ``None``.
    library_asset: Mapping[str, Any] | None = None
    direction: str = ""
    phases: tuple[str, ...] = ()
    #: Frames of the bound driving file the workflow should consume (``end_frame`` exclusive; ``None`` = to the end).
    window_start: int = 0
    window_end: int | None = None
    preparation_mode: str = PREP_AS_IS
    fps_conversion: str = "none"
    framing: str = ""
    viewpoint: str = ""
    compatibility: tuple[str, ...] = ()
    source_compatibility: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @property
    def verified_library_asset(self) -> bool:
        return self.library_asset is not None

    @property
    def provenance_label(self) -> str:
        if self.library_asset is not None:
            return f"Motion Library asset {self.library_asset.get('asset_id')}"
        return "local driving video (provenance not verified)"

    @property
    def identity(self) -> str:
        """What makes two cases the *same motion*: driver bytes, window, prompt and category.

        Cases with equal identity but different source images form a cross-subject group."""

        return record_identity(self.to_record())

    def to_record(self) -> dict[str, Any]:
        """The suite/manifest form (``driving.path`` is absolute once the suite is published)."""

        driving: dict[str, Any] = {"path": str(self.driving_path), "sha256": self.driving_sha256}
        if self.library_asset is not None:
            driving["library_asset"] = json.loads(json.dumps(dict(self.library_asset)))
        record: dict[str, Any] = {
            "driving": driving,
            "source": self.source,
            "action": self.action,
            "motion_prompt": self.motion_prompt,
            "category": self.category,
            "expected_outcome": self.expected_outcome,
            "window": {"start_frame": self.window_start, "end_frame": self.window_end},
            "preparation": {"mode": self.preparation_mode, "fps_conversion": self.fps_conversion},
            "annotations": {
                "framing": self.framing,
                "viewpoint": self.viewpoint,
                "compatibility": list(self.compatibility),
                "source_compatibility": self.source_compatibility,
            },
        }
        if self.direction:
            record["direction"] = self.direction
        if self.phases:
            record["phases"] = list(self.phases)
        return record


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def record_identity(record: Mapping[str, Any]) -> str:
    """The *same-motion* identity of a manifest/suite motion record (see ``MotionBinding.identity``)."""

    driving = as_mapping(record.get("driving"))
    window = as_mapping(record.get("window"))
    prep = as_mapping(record.get("preparation"))
    return canonical_sha256(
        {
            "driver": driving.get("sha256"),
            "window": [window.get("start_frame"), window.get("end_frame")],
            "prep": [prep.get("mode"), prep.get("fps_conversion")],
            "prompt": record.get("motion_prompt"),
            "category": record.get("category"),
        }
    )


def _load_library_asset(raw: Any, driving_sha: str) -> dict[str, Any] | None:
    if raw in (None, {}):
        return None
    _require(isinstance(raw, Mapping), "driving.library_asset must be an object")
    asset_id = str(raw.get("asset_id") or "").strip()
    claimed = str(raw.get("sha256") or "").strip().lower()
    _require(bool(asset_id), "driving.library_asset needs an asset_id")
    _require(
        claimed == driving_sha,
        "driving.library_asset.sha256 does not match the bound driving video; a library "
        "binding is only accepted for the exact clip it names",
    )
    binding: dict[str, Any] = {"asset_id": asset_id, "sha256": claimed}
    derived = raw.get("derived_from")
    if isinstance(derived, Mapping):
        original = str(derived.get("original_sha256") or "")
        start, end = derived.get("start_frame"), derived.get("end_frame")
        if (
            _SHA256.match(original)
            and isinstance(start, int)
            and isinstance(end, int)
            and not isinstance(start, bool)
            and not isinstance(end, bool)
        ):
            binding["derived_from"] = {
                "original_sha256": original,
                "start_frame": start,
                "end_frame": end,
                "cadence": str(derived.get("cadence") or "")[:20],
            }
    return binding


def parse_motion(raw: Any, case_id: str, suite_dir: Path | None) -> MotionBinding:
    """Validate a case's ``motion`` object and verify the bound driving file by SHA-256.

    ``suite_dir`` resolves a relative driving path (``None`` accepts absolute paths only)."""

    label = f"case {case_id}: motion"
    _require(isinstance(raw, Mapping), f"{label} must be an object")
    unknown = sorted(
        set(raw)
        - {
            "driving",
            "action",
            "motion_prompt",
            "category",
            "expected_outcome",
            "direction",
            "phases",
            "window",
            "preparation",
            "annotations",
            "source",
        }
    )
    _require(not unknown, f"{label}: unknown field(s) {', '.join(unknown)}")
    driving = raw.get("driving")
    _require(isinstance(driving, Mapping), f"{label}.driving is required")
    text = str(driving.get("path") or "").strip()
    _require(bool(text), f"{label}.driving.path is required")
    path = Path(text).expanduser()
    if not path.is_absolute():
        _require(suite_dir is not None, f"{label}.driving.path must be absolute")
        path = (suite_dir or Path()) / path
    _require(
        path.suffix.lower() in DRIVING_SUFFIXES,
        f"{label}.driving.path must be a video ({', '.join(sorted(DRIVING_SUFFIXES))})",
    )
    _require(path.is_file(), f"{label}: driving video not found: {path}")
    try:
        actual = file_sha256(path)
    except OSError as exc:
        raise MotionBindingError(f"{label}: cannot read the driving video: {exc}") from exc
    pinned = str(driving.get("sha256") or "").strip().lower()
    if pinned:
        _require(bool(_SHA256.match(pinned)), f"{label}.driving.sha256 is not a SHA-256")
        _require(
            pinned == actual,
            f"{label}: {path.name} changed since the suite pinned it "
            f"(expected {pinned[:12]}..., found {actual[:12]}...)",
        )
    library = _load_library_asset(driving.get("library_asset"), actual)
    source = SOURCE_LIBRARY if library is not None else SOURCE_LOCAL
    declared = str(raw.get("source") or "").strip()
    _require(
        not declared or declared == source,
        f"{label}.source says {declared!r} but the binding is {source!r}; a local video "
        "is not a library asset without a verified library binding",
    )

    category = str(raw.get("category") or "").strip()
    _require(
        category in MOTION_CATEGORY_KEYS,
        f"{label}.category must be one of {', '.join(MOTION_CATEGORY_KEYS)}",
    )
    window = as_mapping(raw.get("window"))
    start = _frame(window.get("start_frame", 0), f"{label}.window.start_frame")
    end = _frame(window.get("end_frame"), f"{label}.window.end_frame", allow_none=True)
    _require(
        end is None or (start is not None and end > start),
        f"{label}.window.end_frame must be after start_frame",
    )
    prep = as_mapping(raw.get("preparation"))
    mode = str(prep.get("mode") or PREP_AS_IS)
    _require(
        mode in PREPARATION_MODES, f"{label}.preparation.mode must be one of {PREPARATION_MODES}"
    )
    conversion = str(prep.get("fps_conversion") or "none")
    _require(
        conversion in FPS_CONVERSIONS,
        f"{label}.preparation.fps_conversion must be one of {FPS_CONVERSIONS}",
    )
    _require(
        mode == PREP_WORKFLOW or (conversion == "none" and start == 0 and end is None),
        f"{label}: a window or rate conversion needs preparation.mode {PREP_WORKFLOW!r}; "
        "an unprepared driving video is used exactly as bound",
    )
    notes = as_mapping(raw.get("annotations"))
    phases = raw.get("phases") or []
    _require(
        isinstance(phases, list) and len(phases) <= _MAX_PHASES,
        f"{label}.phases must be a list of at most {_MAX_PHASES} phases",
    )
    compat = notes.get("compatibility") or []
    _require(
        isinstance(compat, list) and len(compat) <= _MAX_COMPAT,
        f"{label}.annotations.compatibility must be a short list",
    )
    return MotionBinding(
        driving_path=path.resolve(),
        driving_sha256=actual,
        source=source,
        library_asset=library,
        action=_text(raw.get("action"), f"{label}.action", required=True),
        motion_prompt=_text(raw.get("motion_prompt"), f"{label}.motion_prompt", required=True),
        category=category,
        expected_outcome=_text(
            raw.get("expected_outcome"), f"{label}.expected_outcome", required=True
        ),
        direction=_text(raw.get("direction"), f"{label}.direction", limit=_SHORT_LIMIT),
        phases=tuple(_text(item, f"{label}.phases[]", limit=_SHORT_LIMIT) for item in phases),
        window_start=int(start or 0),
        window_end=end,
        preparation_mode=mode,
        fps_conversion=conversion,
        framing=_text(notes.get("framing"), f"{label}.annotations.framing", limit=_SHORT_LIMIT),
        viewpoint=_text(
            notes.get("viewpoint"), f"{label}.annotations.viewpoint", limit=_SHORT_LIMIT
        ),
        compatibility=tuple(
            _text(item, f"{label}.annotations.compatibility[]", limit=_SHORT_LIMIT)
            for item in compat
        ),
        source_compatibility=_text(
            notes.get("source_compatibility"),
            f"{label}.annotations.source_compatibility",
            limit=_SHORT_LIMIT,
        ),
    )


# ------------------------------------------------------------------------------------------- arm compatibility


def check_arm_form(arm_id: str, form: Mapping[str, Any]) -> None:
    """A motion suite takes its driver from the cases; an arm that also names one is ambiguous, so it is refused."""

    for key in CASE_OWNED_FORM_KEYS:
        _require(
            key not in form,
            f"arm {arm_id}: form.{key} comes from each motion case's driving reference",
        )
    controls = form.get("operator_controls")
    if isinstance(controls, Mapping):
        for key in CASE_OWNED_CONTROLS:
            _require(
                key not in controls,
                f"arm {arm_id}: form.operator_controls.{key} comes from each motion case's motion prompt",
            )


def driving_support_error(spec: Any, binding: MotionBinding | None = None) -> str | None:
    """Why ``spec`` cannot honestly run a motion case, or ``None``.

    The driving reference is never removed to make an arm queueable; a prompt-only comparator would be a different
    conditioning mode and is not offered here."""

    if "pose_video" in tuple(getattr(spec, "declared_input_names", ()) or ()):
        return None
    name = getattr(spec, "display_name", None) or getattr(spec, "workflow_id", "this workflow")
    return (
        f"'{name}' takes no driving video, so it cannot reproduce a driving-motion reference. "
        "The reference is not dropped to make the arm queueable; choose a driving-video workflow "
        "(for example Wan-Animate-2 Driving Video Motion)."
    )


def motion_form(
    binding: MotionBinding,
    form: Mapping[str, Any],
    *,
    prepared_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The arm's form with this case's driving reference applied (a new dict; ``form`` is not modified)."""

    merged = dict(form)
    merged["pose_video_path"] = str(binding.driving_path)
    if binding.library_asset is not None:
        merged["motion_library_asset"] = json.loads(json.dumps(dict(binding.library_asset)))
    controls = (
        dict(merged["operator_controls"])
        if isinstance(merged.get("operator_controls"), Mapping)
        else {}
    )
    controls["pose_prompt"] = binding.motion_prompt
    merged["operator_controls"] = controls
    if prepared_record is not None:
        merged["prepared_motion_source"] = json.loads(json.dumps(dict(prepared_record)))
    return merged


# ------------------------------------------------------------------------------------------------ preparation

#: ``(spec, form, request, output_root) -> PreparationOutcome`` (``prepare_for_form``); injectable for tests.
Preparer = Callable[[Any, Mapping[str, Any], Mapping[str, Any], Any], Any]


class MotionPreparationCache:
    """One verified derivative per identical contract within a preview, so arms share it when they may.

    The key is the driver bytes, the window, the rate conversion and the workflow's exact id, version and length.
    Two arms with different workflow versions or lengths get distinct derivatives and the difference is recorded."""

    def __init__(self) -> None:
        self._records: dict[str, Mapping[str, Any]] = {}

    def prepare(
        self,
        binding: MotionBinding,
        spec: Any,
        form: Mapping[str, Any],
        output_root: Any,
        preparer: Preparer,
    ) -> Mapping[str, Any]:
        key = canonical_sha256(
            [
                binding.driving_sha256,
                binding.window_start,
                binding.window_end,
                binding.fps_conversion,
                str(getattr(spec, "workflow_id", "")),
                str(getattr(spec, "workflow_version", "")),
                str(form.get("frame_count") or ""),
            ]
        )
        cached = self._records.get(key)
        if cached is not None:
            return cached
        request = {
            "start": binding.window_start,
            "end": binding.window_end,
            "unit": "frames",
            "fps_conversion": binding.fps_conversion,
        }
        outcome = preparer(
            spec, {**form, "pose_video_path": str(binding.driving_path)}, request, output_root
        )
        record: Mapping[str, Any] | None = getattr(outcome, "record", None)
        if not getattr(outcome, "prepared", False) or record is None:
            message = getattr(outcome, "message", "") or "preparation failed"
            raise MotionBindingError(f"Prepare Motion Source did not complete: {message}")
        self._records[key] = record
        return record


# ---------------------------------------------------------------------------------------------- frozen facts


@dataclass(frozen=True)
class MotionFacts:
    """What an admitted job froze about its driving context, read from the NJR (never from labels)."""

    workflow_id: str
    workflow_version: str
    frame_count: int | None
    fps: int | None
    seed: int | None
    driver_effective_path: str
    driver_effective_sha256: str
    driver_original_path: str
    driver_original_sha256: str
    prepared: bool
    preparation_settings: Mapping[str, Any] | None
    ordered_frames_sha256: str
    library_asset: Mapping[str, Any] | None
    controls: Mapping[str, Any]
    interpolation: bool

    @property
    def motion_prompt(self) -> str:
        return str(self.controls.get("pose_prompt") or "")

    def settings(self) -> dict[str, Any]:
        """The comparable frozen settings: workflow identity, length, rate, seed, controls and driver identity."""

        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "frame_count": self.frame_count,
            "fps": self.fps,
            "seed": self.seed,
            "driver_original_sha256": self.driver_original_sha256,
            "driver_effective_sha256": self.driver_effective_sha256,
            "ordered_frames_sha256": self.ordered_frames_sha256,
            "preparation_settings": dict(self.preparation_settings or {}),
            "interpolation": self.interpolation,
            "controls": {key: self.controls[key] for key in sorted(self.controls)},
        }

    def to_record(self) -> dict[str, Any]:
        record = self.settings()
        record.update(
            driver_effective_path=self.driver_effective_path,
            driver_original_path=self.driver_original_path,
            prepared=self.prepared,
            library_asset=dict(self.library_asset) if self.library_asset else None,
        )
        return record


def motion_facts_from_config(
    workflow: Mapping[str, Any], extra_metadata: Mapping[str, Any] | None = None
) -> MotionFacts | None:
    """Facts from a frozen ``config["video_workflow"]`` block, or ``None`` when the job had no driving video."""

    effective = str(workflow.get("pose_video_path") or "")
    effective_sha = str(workflow.get("pose_video_sha256") or "")
    if not effective:
        return None
    preparation = workflow.get("motion_source_preparation")
    prepared = isinstance(preparation, Mapping) and bool(preparation)
    original = (
        preparation.get("original") if prepared and isinstance(preparation, Mapping) else None
    )
    derived = preparation.get("derived") if prepared and isinstance(preparation, Mapping) else None
    controls = workflow.get("operator_controls")
    meta = (extra_metadata or {}).get("video_workflow")
    library = meta.get("motion_library_asset") if isinstance(meta, Mapping) else None
    seed = workflow.get("seed")
    frames = workflow.get("frame_count")
    fps = workflow.get("fps")
    interpolation = workflow.get("interpolation")
    return MotionFacts(
        workflow_id=str(workflow.get("workflow_id") or ""),
        workflow_version=str(workflow.get("workflow_version") or ""),
        frame_count=frames if isinstance(frames, int) and not isinstance(frames, bool) else None,
        fps=fps if isinstance(fps, int) and not isinstance(fps, bool) else None,
        seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        driver_effective_path=effective,
        driver_effective_sha256=effective_sha,
        driver_original_path=str((original or {}).get("path") or effective),
        driver_original_sha256=str((original or {}).get("sha256") or effective_sha),
        prepared=prepared,
        preparation_settings=dict(preparation.get("settings") or {})
        if prepared and isinstance(preparation, Mapping)
        else None,
        ordered_frames_sha256=str((derived or {}).get("frames_md5_sha256") or ""),
        library_asset=dict(library) if isinstance(library, Mapping) else None,
        controls=dict(controls) if isinstance(controls, Mapping) else {},
        interpolation=isinstance(interpolation, Mapping) and bool(interpolation.get("enabled")),
    )


def motion_facts_from_njr(njr: Any) -> MotionFacts | None:
    from src.pipeline.njr_core_v26 import thaw_json

    config = thaw_json(njr.config)
    block = config.get("video_workflow") if isinstance(config, Mapping) else None
    if not isinstance(block, Mapping):
        return None
    return motion_facts_from_config(block, thaw_json(getattr(njr, "extra_metadata", {}) or {}))


def driving_context_sha256(
    *,
    source_sha256: str,
    driver_original_sha256: str,
    driver_effective_sha256: str,
    facts_settings: Mapping[str, Any],
    motion_prompt: str,
) -> str:
    """Digest of the effective driving context a motion judgment is about.

    Current file digests go in, so a replaced driver, prepared derivative or source image changes it. Controls and
    seed are job-level frozen facts (the job id pins them) and are not part of it."""

    return canonical_sha256(
        {
            "source": source_sha256,
            "driver_original": driver_original_sha256,
            "driver_effective": driver_effective_sha256,
            "workflow": [facts_settings.get("workflow_id"), facts_settings.get("workflow_version")],
            "length": [facts_settings.get("frame_count"), facts_settings.get("fps")],
            "preparation": facts_settings.get("preparation_settings"),
            "ordered_frames": facts_settings.get("ordered_frames_sha256"),
            "motion_prompt": motion_prompt,
        }
    )


__all__ = [
    "CASE_OWNED_CONTROLS",
    "CASE_OWNED_FORM_KEYS",
    "DRIVING_SUFFIXES",
    "FPS_CONVERSIONS",
    "MOTION_BLOCK",
    "MOTION_CATEGORIES",
    "MOTION_CATEGORY_KEYS",
    "MOTION_CATEGORY_LABELS",
    "PREPARATION_MODES",
    "PREP_AS_IS",
    "PREP_WORKFLOW",
    "SOURCE_LIBRARY",
    "SOURCE_LOCAL",
    "MotionBinding",
    "MotionBindingError",
    "MotionFacts",
    "MotionPreparationCache",
    "canonical_sha256",
    "check_arm_form",
    "driving_context_sha256",
    "driving_support_error",
    "file_sha256",
    "motion_facts_from_config",
    "motion_facts_from_njr",
    "motion_form",
    "parse_motion",
    "as_mapping",
    "as_mapping_or_none",
    "record_identity",
]
