"""Re-run with tweaks: the intent snapshot of a finished clip and the typed tweak vocabulary (V1-2, section 5.9 / 7).

Tk-free and shared by the desktop (Recent outputs and Job History, *Re-run with tweaks...*) and the phone actions
(RG-140), so a phone tweak and a desktop edit resolve to the same Video Workflow form and therefore the same NJR:

- :func:`intent_snapshot` reconstructs what the operator asked for from a completed job's frozen NJR and its
  ``motion_intent`` provenance (older jobs without it reconstruct with the preset *none* and the duration from frames).
- :func:`parse_tweaks` validates an untrusted ``{name: value}`` mapping against the bounded vocabulary
  (``prompt``, ``motion``, ``preset``, ``duration_seconds``, ``seed``, ``more_motion``, ``less_motion``).
- :func:`apply_tweaks` returns the tweaked snapshot; :func:`rerun_form_state` the saved-form shape the tab restores;
  :func:`rerun_submission_form` the submission form ``VideoWorkflowNjrBuilder`` takes, with the re-run lineage.
- :func:`driver_rerun_plan` decides whether a driving-video job reuses its frozen prepared clip, re-prepares from the
  original driver (its bytes still verify) or refuses the tweak with the reason.

A re-run is a new NJR through the normal builder whose source is ``HISTORY_REPLAY`` lineage to the parent with a
content-free variation marker (the tweaked field names only); the parent NJR is never mutated.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final

from src.pipeline.history_variation_marker import VARIATION_SCHEMA
from src.pipeline.njr_core_v26 import thaw_json
from src.video.motion_intent import (
    MOTION_INTENT_FIELD,
    MOTION_PHRASE_MAX,
    LengthPolicy,
    choice_for_frames,
    compose_prompt,
    frames_for_duration,
    motion_intent_record,
    split_composed_prompt,
)
from src.video.motion_presets import (
    DURATION_ENGINE_MAX,
    DURATION_WHOLE_MOVEMENT,
    INTENT_FOLLOW_DRIVER,
    INTENT_PROMPT_ONLY,
    MOTION_PROMPT_CONTROL,
    NO_PRESET_ID,
    ladder_step,
    preset_by_id,
    preset_is_modified,
)

STAGE_VIDEO_WORKFLOW: Final = "video_workflow"
TASK_ANIMATE: Final = "animate"
TASK_FOLLOW_CLIP: Final = "follow_clip"

#: The form key a re-run submission carries its lineage under (``VideoWorkflowNjrBuilder`` turns it into the source).
RERUN_LINEAGE_FIELD: Final = "rerun_lineage"
RERUN_KIND: Final = "video_rerun_with_tweaks"

PROMPT_MAX: Final = 2000
DURATION_MAX_SECONDS: Final = 60.0
SEED_MAX: Final = 2**31
SEED_RANDOM: Final = "random"
SEED_SAME: Final = "same"
TWEAK_NAMES: Final[tuple[str, ...]] = (
    "prompt",
    "motion",
    "preset",
    "duration_seconds",
    "seed",
    "more_motion",
    "less_motion",
)
_JOB_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
#: Saved-form fields a re-run compares to tell which values the operator changed (the variation marker's names).
_COMPARED_FIELDS: Final[tuple[str, ...]] = (
    "workflow_id",
    "prompt",
    "motion_phrase",
    "motion_preset",
    "frame_count",
    "seed",
    "negative_prompt",
    "operator_controls",
    "interpolation",
    "pose_video_path",
)


class RerunRefused(ValueError):
    """The job cannot be re-run with tweaks; the message says why."""


class TweakError(ValueError):
    """A tweak is outside the vocabulary or its bounds; nothing was applied."""


# ---------------------------------------------------------------- the snapshot


@dataclass(frozen=True)
class DriverBinding:
    """The driving video a job froze, and its prepared derivative when it had one."""

    path: str
    sha256: str
    prepared: Mapping[str, Any] | None = None

    @property
    def aligned(self) -> bool:
        return isinstance((self.prepared or {}).get("alignment"), Mapping)

    @property
    def settings(self) -> Mapping[str, Any]:
        settings = (self.prepared or {}).get("settings")
        return settings if isinstance(settings, Mapping) else {}


@dataclass(frozen=True)
class IntentSnapshot:
    """What a finished clip's job asked for, in the form's own terms."""

    job_id: str
    original_source_kind: str
    intent: str
    workflow_id: str
    workflow_version: str
    source_image_path: str
    prompt: str
    motion_phrase: str
    preset_id: str
    preset_version: int | None
    frame_count: int | None
    fps: int | None
    seed: int | None
    negative_prompt: str
    output_route: str
    smoothing: bool
    operator_controls: Mapping[str, Any] = field(default_factory=dict)
    driver: DriverBinding | None = None
    experimental_opt_in: bool = False
    has_provenance: bool = False

    @property
    def duration_seconds(self) -> float | None:
        if self.frame_count is None or not self.fps:
            return None
        return round(self.frame_count / self.fps, 1)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def intent_snapshot(njr: Any) -> IntentSnapshot:
    """The intent behind one single-clip Video Workflow NJR.  Raises :class:`RerunRefused` otherwise."""

    stages = {stage.stage_type: stage for stage in getattr(njr, "stage_chain", ())}
    if STAGE_VIDEO_WORKFLOW not in stages:
        raise RerunRefused("Re-run with tweaks needs a Comfy video workflow clip.")
    stage: dict[str, Any] = dict(thaw_json(stages[STAGE_VIDEO_WORKFLOW].extra) or {})
    if stage.get("sequence_metadata"):
        raise RerunRefused(
            "Re-run with tweaks covers single clips; use Replay or Continue in Storyboard for a sequence."
        )
    workflow_id = str(stage.get("workflow_id") or "")
    if not workflow_id:
        raise RerunRefused("The job does not record which video workflow it ran.")
    metadata = _mapping(thaw_json(getattr(njr, "extra_metadata", {}) or {}))
    video_meta = _mapping(metadata.get("video_workflow"))
    record = _mapping(video_meta.get(MOTION_INTENT_FIELD))
    preparation = _mapping(stage.get("source_preparation"))
    inputs = tuple(getattr(njr, "input_image_paths", ()) or ())
    source = str(preparation.get("original_source_path") or (inputs[0] if inputs else ""))
    driver = None
    if stage.get("pose_video_path"):
        prepared = stage.get("motion_source_preparation")
        driver = DriverBinding(
            path=str(stage["pose_video_path"]),
            sha256=str(stage.get("pose_video_sha256") or ""),
            prepared=dict(prepared) if isinstance(prepared, Mapping) else None,
        )
    recorded_phrase = str(record.get("motion_phrase") or "")
    prompt, phrase = split_composed_prompt(stage.get("prompt") or "", recorded_phrase)
    preset = _mapping(record.get("preset"))
    known = preset_by_id(preset.get("id"))
    intent = str(record.get("intent") or "") or (TASK_FOLLOW_CLIP if driver else TASK_ANIMATE)
    execution = _mapping(stage.get("video_execution"))
    controls = _mapping(stage.get("operator_controls"))
    source_kind = getattr(getattr(njr, "source", None), "kind", None)
    return IntentSnapshot(
        job_id=str(getattr(njr, "job_id", "") or ""),
        original_source_kind=str(getattr(source_kind, "value", source_kind) or ""),
        intent=intent,
        workflow_id=workflow_id,
        workflow_version=str(stage.get("workflow_version") or ""),
        source_image_path=source,
        prompt=prompt,
        motion_phrase=phrase,
        preset_id=known.preset_id if known is not None else NO_PRESET_ID,
        preset_version=known.version if known is not None else None,
        frame_count=_int_or_none(stage.get("frame_count")),
        fps=_int_or_none(stage.get("fps")),
        seed=_int_or_none(stage.get("seed")),
        negative_prompt=str(stage.get("negative_prompt") or ""),
        output_route=str(video_meta.get("output_route") or ""),
        smoothing=bool(_mapping(stage.get("interpolation")).get("enabled")),
        operator_controls=dict(controls),
        driver=driver,
        experimental_opt_in=execution.get("experimental_opt_in") is True,
        has_provenance=bool(record),
    )


def load_snapshot(repository: Any, job_id: str) -> IntentSnapshot:
    """Read a finished job from the canonical repository and reconstruct its intent (worker-thread safe)."""

    text = str(job_id or "").strip()
    if not _JOB_ID.match(text):
        raise RerunRefused("That is not a job id.")
    if repository is None:
        raise RerunRefused("The job repository is not available.")
    job = repository.get_job_model(text)
    if job is None:
        raise RerunRefused(f"Job {text} was not found.")
    status = str(getattr(job.status, "value", job.status) or "")
    if status != "completed":
        raise RerunRefused(
            f"Job {text} has not completed (it is {status}); re-run a finished clip."
        )
    njr = getattr(job, "_normalized_record", None)
    if njr is None:
        raise RerunRefused(f"Job {text} has no frozen job record to re-run.")
    return intent_snapshot(njr)


# ---------------------------------------------------------------- the tweak vocabulary


@dataclass(frozen=True)
class Tweaks:
    """A validated set of tweaks; ``None`` means "keep".  The seed is a new random one unless one is given."""

    prompt: str | None = None
    motion: str | None = None
    preset: str | None = None
    duration_seconds: float | None = None
    seed: int | str = SEED_RANDOM
    more_motion: bool = False
    less_motion: bool = False

    def names(self) -> tuple[str, ...]:
        given = []
        for name in TWEAK_NAMES:
            value = getattr(self, name)
            if name == "seed":
                if value != SEED_RANDOM:
                    given.append(name)
            elif value not in (None, False):
                given.append(name)
        return tuple(given)


def _text_tweak(name: str, value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise TweakError(f"{name} must be text.")
    if len(value) > limit:
        raise TweakError(f"{name} is longer than {limit} characters.")
    return value.strip()


def parse_tweaks(value: Any) -> Tweaks:
    """Validate untrusted tweaks (the phone sends the same mapping).  Unknown names and bad values are refused."""

    if value is None:
        return Tweaks()
    if not isinstance(value, Mapping):
        raise TweakError("Tweaks must be a mapping of names to values.")
    unknown = sorted(str(name) for name in value if name not in TWEAK_NAMES)
    if unknown:
        raise TweakError(f"Unknown tweak: {', '.join(unknown)}.")
    parsed: dict[str, Any] = {}
    if "prompt" in value:
        parsed["prompt"] = _text_tweak("prompt", value["prompt"], PROMPT_MAX)
    if "motion" in value:
        parsed["motion"] = _text_tweak("motion", value["motion"], MOTION_PHRASE_MAX)
    if "preset" in value:
        preset = str(value["preset"] or "").strip().lower()
        if preset != NO_PRESET_ID and preset_by_id(preset) is None:
            raise TweakError(f"Unknown preset {value['preset']!r}.")
        parsed["preset"] = preset
    if "duration_seconds" in value:
        seconds = value["duration_seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, int | float):
            raise TweakError("duration_seconds must be a number.")
        if not math.isfinite(float(seconds)) or not 0 < float(seconds) <= DURATION_MAX_SECONDS:
            raise TweakError(
                f"duration_seconds must be more than 0 and at most {DURATION_MAX_SECONDS:g}."
            )
        parsed["duration_seconds"] = float(seconds)
    if "seed" in value:
        seed = value["seed"]
        if seed in (SEED_RANDOM, SEED_SAME):
            parsed["seed"] = seed
        elif isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed < SEED_MAX:
            parsed["seed"] = seed
        else:
            raise TweakError(
                f"seed must be 'random', 'same' or a whole number from 0 to {SEED_MAX - 1}."
            )
    for name in ("more_motion", "less_motion"):
        if name in value:
            if not isinstance(value[name], bool):
                raise TweakError(f"{name} must be true or false.")
            parsed[name] = value[name]
    tweaks = Tweaks(**parsed)
    if tweaks.more_motion and tweaks.less_motion:
        raise TweakError("Choose more motion or less motion, not both.")
    if (tweaks.more_motion or tweaks.less_motion) and tweaks.preset is not None:
        raise TweakError("A preset and a motion step cannot be combined.")
    return tweaks


def _preset_frames(
    duration: float | str, policy: LengthPolicy | None, current: int | None
) -> int | None:
    if policy is None:
        return current
    if duration == DURATION_ENGINE_MAX:
        return policy.maximum
    if duration == DURATION_WHOLE_MOVEMENT:
        return current  # the driver's window decides; a re-run keeps the frozen length
    return frames_for_duration(float(duration), policy).frames


def apply_tweaks(
    snapshot: IntentSnapshot, tweaks: Tweaks, policy: LengthPolicy | None
) -> tuple[IntentSnapshot, list[str]]:
    """The tweaked snapshot and a note per tweak that could not move (e.g. already the most motion)."""

    notes: list[str] = []
    side_intent = (
        INTENT_FOLLOW_DRIVER if snapshot.intent == TASK_FOLLOW_CLIP else INTENT_PROMPT_ONLY
    )
    changes: dict[str, Any] = {}
    phrase = snapshot.motion_phrase
    frames = snapshot.frame_count
    controls = dict(snapshot.operator_controls)
    preset_id = snapshot.preset_id
    step = 1 if tweaks.more_motion else -1 if tweaks.less_motion else 0
    if step:
        preset_id, note = ladder_step(snapshot.preset_id, step)
        if note:
            notes.append(note)
    elif tweaks.preset is not None:
        preset_id = tweaks.preset
    preset = preset_by_id(preset_id)
    if preset is not None and preset_id != snapshot.preset_id:
        side = preset.side(side_intent)
        if side_intent == INTENT_PROMPT_ONLY:
            phrase = side.motion_phrase
        else:
            if MOTION_PROMPT_CONTROL in controls:
                controls[MOTION_PROMPT_CONTROL] = side.motion_phrase
            for name, number in side.controls.items():
                if name in controls:
                    controls[name] = number
        # A motion step changes the phrase (and, for a driver, its strengths) only; a chosen preset also its length.
        if not step:
            frames = _preset_frames(side.duration, policy, frames)
    if tweaks.motion is not None:
        phrase = tweaks.motion
    if tweaks.duration_seconds is not None:
        if policy is None:
            notes.append("This engine has a fixed length; the duration tweak was skipped.")
        else:
            frames = frames_for_duration(tweaks.duration_seconds, policy).frames
    if tweaks.prompt is not None:
        changes["prompt"] = tweaks.prompt
    if tweaks.seed == SEED_SAME:
        seed: int | None = snapshot.seed
    elif tweaks.seed == SEED_RANDOM:
        seed = None
    else:
        seed = int(tweaks.seed)
    known = preset_by_id(preset_id)
    changes.update(
        motion_phrase=phrase,
        frame_count=frames,
        operator_controls=controls,
        preset_id=NO_PRESET_ID if known is None else known.preset_id,
        preset_version=None if known is None else known.version,
        seed=seed,
    )
    return replace(snapshot, **changes), notes


# ---------------------------------------------------------------- driver re-runs


DRIVER_REUSE: Final = "reuse"
DRIVER_REPREPARE: Final = "reprepare"
DRIVER_REFUSE: Final = "refuse"

FileVerifier = Callable[[str, str], bool]


@dataclass(frozen=True)
class DriverPlan:
    action: str
    reason: str
    prepared: Mapping[str, Any] | None = None
    request: Mapping[str, Any] | None = None


def _prepare_request(binding: DriverBinding) -> dict[str, Any]:
    """The Prepare Motion Source request that reproduces the frozen window (start, end, frame-rate conversion)."""

    settings = binding.settings
    requested = _mapping(settings.get("requested"))
    start = requested.get("start")
    return {
        "start": float(start)
        if isinstance(start, int | float) and not isinstance(start, bool)
        else 0.0,
        "end": requested.get("end") if isinstance(requested.get("end"), int | float) else None,
        "unit": "seconds",
        "fps_conversion": str(settings.get("fps_conversion") or "none"),
    }


def driver_rerun_plan(
    snapshot: IntentSnapshot, frame_count: int | None, *, verify: FileVerifier
) -> DriverPlan | None:
    """How a re-run supplies its driving video: reuse the frozen prepared clip, re-prepare it, or refuse.

    ``verify(path, sha256)`` says whether a file still holds exactly those bytes (the caller hashes, off the Tk
    thread).  ``None`` for a job without a driving video."""

    binding = snapshot.driver
    if binding is None:
        return None
    prepared = binding.prepared
    original_ok = bool(binding.sha256) and verify(binding.path, binding.sha256)
    if prepared is None:
        if original_ok:
            return DriverPlan(DRIVER_REUSE, "The driving video is used as it was.")
        return DriverPlan(
            DRIVER_REFUSE,
            f"The driving video changed or is missing since the job ran: {binding.path}",
        )
    derived = _mapping(prepared.get("derived"))
    same_window = frame_count == snapshot.frame_count
    if same_window and verify(str(derived.get("path") or ""), str(derived.get("sha256") or "")):
        return DriverPlan(
            DRIVER_REUSE, "The prepared driving clip is reused unchanged.", prepared=prepared
        )
    if binding.aligned:
        return DriverPlan(
            DRIVER_REFUSE,
            "This job used an aligned driving clip; a changed or missing clip is re-aligned in Align Motion, "
            "not re-prepared automatically.",
        )
    if original_ok:
        why = "the length changed" if not same_window else "the prepared clip is missing"
        return DriverPlan(
            DRIVER_REPREPARE,
            f"The driving video is prepared again from the original ({why}).",
            request=_prepare_request(binding),
        )
    return DriverPlan(
        DRIVER_REFUSE,
        f"The original driving video changed or is missing, so it cannot be prepared again: {binding.path}",
    )


# ---------------------------------------------------------------- forms


def rerun_form_state(snapshot: IntentSnapshot) -> dict[str, Any]:
    """The saved Video Workflow form a re-run restores (every value the operator's own, a seed only when kept)."""

    form: dict[str, Any] = {
        "task": snapshot.intent,
        "workflow_id": snapshot.workflow_id,
        "workflow_version": snapshot.workflow_version,
        "source_image_path": snapshot.source_image_path,
        "prompt": snapshot.prompt,
        "motion_phrase": snapshot.motion_phrase,
        "motion_preset": snapshot.preset_id,
        "negative_prompt": snapshot.negative_prompt,
        "seed": "" if snapshot.seed is None else str(snapshot.seed),
    }
    if snapshot.frame_count is not None:
        form["frame_count"] = snapshot.frame_count
    if snapshot.output_route:
        form["output_route"] = snapshot.output_route
    if snapshot.smoothing:
        form["interpolation"] = {"enabled": True}
    if snapshot.operator_controls:
        form["operator_controls"] = dict(snapshot.operator_controls)
    if snapshot.driver is not None:
        form["pose_video_path"] = snapshot.driver.path
    return form


def _control_value(value: Any) -> Any:
    """A control's value for comparison: numbers by value (the form holds text), text trimmed."""

    text = str(value if value is not None else "").strip()
    try:
        return float(text)
    except ValueError:
        return text


def _comparable(form: Mapping[str, Any], name: str) -> Any:
    value = form.get(name)
    if name == "frame_count":
        return _int_or_none(value)
    if name == "interpolation":
        return bool(_mapping(value).get("enabled"))
    if name == "operator_controls":
        return {key: _control_value(item) for key, item in _mapping(value).items()}
    if name == "motion_preset":
        return str(value or NO_PRESET_ID)
    return str(value if value is not None else "").strip()


def rerun_edits(parent: IntentSnapshot, form: Mapping[str, Any]) -> tuple[str, ...]:
    """The names of the form values that differ from what the parent job asked for (content-free)."""

    base = rerun_form_state(parent)
    base["seed"] = "" if parent.seed is None else str(parent.seed)
    return tuple(
        name for name in _COMPARED_FIELDS if _comparable(base, name) != _comparable(form, name)
    )


def rerun_lineage(parent: IntentSnapshot, edited_fields: tuple[str, ...]) -> dict[str, Any]:
    """The lineage a re-run submission carries: the parent, its source kind and the edited field names."""

    return {
        "parent_job_id": parent.job_id,
        "original_source_kind": parent.original_source_kind,
        "edited_fields": list(edited_fields),
    }


def normalize_rerun_lineage(value: Any) -> dict[str, Any] | None:
    """The lineage as the builder trusts it: a well-formed parent id, a source kind and known field names."""

    if not isinstance(value, Mapping):
        return None
    parent = str(value.get("parent_job_id") or "").strip()
    if not _JOB_ID.match(parent):
        return None
    kind = str(value.get("original_source_kind") or "").strip()[:64]
    fields = [str(name) for name in value.get("edited_fields") or () if name in _COMPARED_FIELDS]
    return {"parent_job_id": parent, "original_source_kind": kind, "edited_fields": fields}


def variation_marker(lineage: Mapping[str, Any]) -> dict[str, Any]:
    """The content-free ``history_variation`` block (PR-HISTORY-610A precedent) that marks an edited re-run."""

    return {
        "schema": VARIATION_SCHEMA,
        "kind": RERUN_KIND,
        "parent_job_id": lineage["parent_job_id"],
        "edited_fields": list(lineage.get("edited_fields") or ()),
        "origin": {"source_kind": lineage.get("original_source_kind") or ""},
    }


def rerun_submission_form(
    parent: IntentSnapshot,
    tweaked: IntentSnapshot,
    policy: LengthPolicy | None,
    *,
    driver: DriverPlan | None = None,
    experimental_opt_in: bool = False,
) -> dict[str, Any]:
    """The submission form for a re-run, exactly as the desktop form submits it after the same edits.

    ``experimental_opt_in`` is the caller's: only a surface that showed the workflow's warning may set it."""

    if driver is not None and driver.action == DRIVER_REFUSE:
        raise RerunRefused(driver.reason)
    form = rerun_form_state(tweaked)
    edits = rerun_edits(parent, form)
    phrase = str(form.pop("motion_phrase") or "").strip()
    preset_id = form.pop("motion_preset")
    task = form.pop("task")
    if task == TASK_ANIMATE:
        form["prompt"] = compose_prompt(form["prompt"], phrase)
        preset = preset_by_id(preset_id)
        frames = tweaked.frame_count
        duration = None if policy is None or frames is None else choice_for_frames(frames, policy)
        modified = preset is not None and preset_is_modified(
            preset,
            INTENT_PROMPT_ONLY,
            {
                "form_visibility": {"frame_count": policy is not None},
                "frame_count": _projection(policy),
            },
            {"frame_count": frames, "motion_phrase": phrase},
        )
        form[MOTION_INTENT_FIELD] = motion_intent_record(
            intent=task,
            preset=preset,
            preset_modified=modified,
            motion_phrase=phrase,
            duration=duration,
            basis=dict.fromkeys(("workflow_id", "frame_count", "motion_phrase"), "Your choice."),
        )
    if driver is not None and driver.action == DRIVER_REUSE and driver.prepared is not None:
        from src.video.video_workflow_njr_builder import PREPARED_MOTION_SOURCE_FIELD

        form[PREPARED_MOTION_SOURCE_FIELD] = dict(driver.prepared)
    form["experimental_opt_in"] = bool(experimental_opt_in)
    form[RERUN_LINEAGE_FIELD] = rerun_lineage(parent, edits)
    return form


@dataclass(frozen=True)
class RerunOpening:
    """What a desktop *Re-run with tweaks...* opens: the parent's intent, the form to restore and the driver plan."""

    snapshot: IntentSnapshot
    form: Mapping[str, Any]
    driver: DriverPlan | None


def sha256_verifier(path: str, sha256: str) -> bool:
    """Whether ``path`` still holds exactly the bytes with this SHA-256 (reads the file; never on the Tk thread)."""

    from pathlib import Path

    from src.video.video_workflow_njr_builder import sha256_file

    if not path or not sha256 or not Path(path).is_file():
        return False
    try:
        return sha256_file(path) == sha256
    except OSError:
        return False


def open_rerun(
    repository: Any, job_id: str, *, verify: FileVerifier = sha256_verifier
) -> RerunOpening:
    """Load a finished clip's job for re-running: its snapshot, the form (every value kept, a new random seed) and how
    its driving video is supplied.  Raises :class:`RerunRefused` with the reason (worker-thread safe)."""

    snapshot = load_snapshot(repository, job_id)
    driver = driver_rerun_plan(snapshot, snapshot.frame_count, verify=verify)
    if driver is not None and driver.action == DRIVER_REFUSE:
        raise RerunRefused(driver.reason)
    return RerunOpening(snapshot, rerun_form_state(replace(snapshot, seed=None)), driver)


def _projection(policy: LengthPolicy | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "default": policy.default,
        "minimum": policy.minimum,
        "maximum": policy.maximum,
        "step": policy.step,
        "offset": policy.offset,
        "fps": policy.fps,
    }


__all__ = [
    "DRIVER_REFUSE",
    "DRIVER_REPREPARE",
    "DRIVER_REUSE",
    "DURATION_MAX_SECONDS",
    "PROMPT_MAX",
    "RERUN_KIND",
    "RERUN_LINEAGE_FIELD",
    "SEED_RANDOM",
    "SEED_SAME",
    "TWEAK_NAMES",
    "DriverBinding",
    "DriverPlan",
    "IntentSnapshot",
    "RerunOpening",
    "RerunRefused",
    "TweakError",
    "Tweaks",
    "apply_tweaks",
    "driver_rerun_plan",
    "intent_snapshot",
    "load_snapshot",
    "normalize_rerun_lineage",
    "open_rerun",
    "parse_tweaks",
    "rerun_edits",
    "rerun_form_state",
    "rerun_lineage",
    "rerun_submission_form",
    "sha256_verifier",
    "variation_marker",
]
