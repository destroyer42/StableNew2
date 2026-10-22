"""The single Video Workflow NJR construction path (PR-VID-194).

Both a normal Video Workflow submission and every arm of a one-variable experiment build their
immutable NJR here, so the two can never drift apart.  Construction has two steps:

1. ``freeze_inputs`` validates the form and freezes everything that must be identical for the
   lifetime of one admission: the concrete seed, the driving-video path and SHA-256, the declared
   source preparation and the source content hash.
2. ``build_job`` turns the form plus those frozen inputs into one immutable NJR.

Nothing here executes anything, builds a backend payload or touches the queue; the compiler binds
the frozen intent to the graph and ``JobService`` owns admission.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.controller.ports.runtime_ports import WorkflowRegistryPort
from src.pipeline.job_models_v2 import LearningJobContext, NormalizedJobRecord
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.state.output_routing import (
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_TESTING,
)
from src.video.continuity_models import normalize_continuity_link
from src.video.motion_source_plan import motion_source_contract
from src.video.motion_source_preparation import validate_prepared_record
from src.video.rife_runtime import default_rife_multiplier, find_rife_executable
from src.video.video_execution_resolver import VIDEO_EXECUTION_KEY
from src.video.video_interpolation import normalize_interpolation_request
from src.video.video_workflow_intent import (
    EXPERIMENTAL_OPT_IN_FIELD,
    build_video_execution_block,
    capability_errors,
    default_negative_prompt,
    mid_anchor_list,
    parse_seed_input,
)
from src.video.workflow_controls import resolve_operator_controls
from src.video.workflow_frame_count import (
    approximate_seconds,
    frame_count_policy,
    parse_frame_count,
)
from src.video.workflow_source_preparation import prepare_declared_workflow_source

_DRIVING_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
# Optional form key: the record ``prepare_motion_source`` returned (PR-VID-MOTION-210).  Absent
# means the clip is used exactly as it always was.
PREPARED_MOTION_SOURCE_FIELD = "prepared_motion_source"
# Optional form key set by an operator surface whose preparation is running, failed, was cancelled
# or is out of date: its text is refused as-is, so a job never silently falls back to the
# unprepared clip the operator meant to replace.
MOTION_SOURCE_BLOCKED_FIELD = "motion_source_preparation_blocked"
_DEFAULT_OUTPUT_ROUTES = (
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_TESTING,
)
_VALID_DEPTH_INPUT_MODES = {"none", "auto", "upload"}
_VALID_CAMERA_PRESETS = {
    "none",
    "dolly_in",
    "dolly_out",
    "truck_left",
    "truck_right",
    "orbit_left",
    "orbit_right",
    "tilt_up",
    "tilt_down",
}


HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    """Standard SHA-256 of a file, read in bounded chunks (a driving video can be large)."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _parse_float(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field_name} must be <= {maximum}")
    return parsed


def _normalize_camera_intent(form_data: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping_dict(form_data.get("camera_intent"))
    preset = (
        str(payload.get("preset") or form_data.get("camera_preset") or "none").strip().lower()
        or "none"
    )
    if preset not in _VALID_CAMERA_PRESETS:
        allowed = ", ".join(sorted(_VALID_CAMERA_PRESETS))
        raise ValueError(f"camera_intent.preset must be one of: {allowed}")
    strength_value = payload.get("strength", form_data.get("camera_strength", 0.35))
    strength = _parse_float(
        strength_value, field_name="camera_intent.strength", minimum=0.0, maximum=1.0
    )
    return {"preset": preset, "strength": strength}


def _normalize_controlnet(form_data: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping_dict(form_data.get("controlnet"))
    model = (
        str(payload.get("model") or form_data.get("controlnet_model") or "depth").strip() or "depth"
    )
    weight = _parse_float(
        payload.get("weight", form_data.get("controlnet_weight", 1.0)),
        field_name="controlnet.weight",
        minimum=0.0,
    )
    guidance_start = _parse_float(
        payload.get("guidance_start", form_data.get("controlnet_guidance_start", 0.0)),
        field_name="controlnet.guidance_start",
        minimum=0.0,
        maximum=1.0,
    )
    guidance_end = _parse_float(
        payload.get("guidance_end", form_data.get("controlnet_guidance_end", 1.0)),
        field_name="controlnet.guidance_end",
        minimum=0.0,
        maximum=1.0,
    )
    if guidance_end < guidance_start:
        raise ValueError("controlnet.guidance_end must be >= controlnet.guidance_start")
    return {
        "model": model,
        "weight": weight,
        "guidance_start": guidance_start,
        "guidance_end": guidance_end,
    }


def _normalize_depth_input(form_data: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping_dict(form_data.get("depth_input"))
    mode = (
        str(payload.get("mode") or form_data.get("depth_mode") or "none").strip().lower() or "none"
    )
    if mode not in _VALID_DEPTH_INPUT_MODES:
        allowed = ", ".join(sorted(_VALID_DEPTH_INPUT_MODES))
        raise ValueError(f"depth_input.mode must be one of: {allowed}")
    path = str(
        payload.get("path") or payload.get("upload_path") or form_data.get("depth_path") or ""
    ).strip()
    return {"mode": mode, "path": path}


def _continuity_form_supplied(form_data: Mapping[str, Any]) -> bool:
    for key in (
        "continuity_link",
        "continuity_pack",
        "continuity_pack_id",
        "continuity_pack_name",
        "continuity_pack_summary",
    ):
        if form_data.get(key) not in (None, "", [], {}):
            return True
    return False


def _build_continuity_link(form_data: Mapping[str, Any]) -> dict[str, Any] | None:
    for key in ("continuity_link", "continuity_pack"):
        link = normalize_continuity_link(form_data.get(key))
        if link:
            return link

    pack_id = str(form_data.get("continuity_pack_id") or "").strip()
    pack_name = str(form_data.get("continuity_pack_name") or "").strip()
    raw_summary = form_data.get("continuity_pack_summary")
    summary = dict(raw_summary) if isinstance(raw_summary, Mapping) else {}
    if pack_name and "display_name" not in summary:
        summary["display_name"] = pack_name
    candidate_pack_id = pack_id or str(summary.get("pack_id") or "").strip()
    if not candidate_pack_id:
        return None
    payload: dict[str, Any] = {"pack_id": candidate_pack_id}
    if summary:
        summary.setdefault("pack_id", candidate_pack_id)
        payload["pack_summary"] = summary
    return normalize_continuity_link(payload)


@dataclass(frozen=True)
class FrozenVideoInputs:
    """Inputs frozen once per admission and shared by every NJR built from them."""

    source_image_path: str
    source_sha256: str
    seed: int | None
    driving_video: Mapping[str, str] | None  # {"path", "sha256"}
    source_preparation: Mapping[str, Any] | None
    prepared_source_path: str
    prepared_source_sha256: str
    # (label, path, sha256) of file-backed end/mid anchors and an uploaded depth map the workflow
    # actually uses.  Evidence only: re-hashed by ``verify_unchanged``, never stored in the NJR.
    shared_files: tuple[tuple[str, str, str], ...] = ()
    motion_source_preparation: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SharedFrozenInputs:
    """Inputs that do not depend on the source image, frozen once and shared by a whole batch."""

    driving_video: Mapping[str, str] | None  # {"path", "sha256"}; the prepared clip when prepared
    files: tuple[tuple[str, str, str], ...]  # (label, path, sha256)
    motion_source_preparation: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class VideoWorkflowBuild:
    """One immutable NJR plus the admission-time values the operator surface reports."""

    njr: NormalizedJobRecord
    seed: int | None
    frame_count: int | None
    source_preparation: Mapping[str, Any]


class VideoWorkflowNjrBuilder:
    """Validates Video Workflow form data and builds its immutable NJR."""

    def __init__(
        self,
        *,
        workflow_registry: WorkflowRegistryPort,
        output_dir_provider: Callable[[], Any],
    ) -> None:
        self._workflow_registry = workflow_registry
        self._output_dir_provider = output_dir_provider

    def _output_dir(self) -> str:
        return str(self._output_dir_provider() or "output")

    def output_dir(self) -> str:
        """The StableNew output root a job (and its prepared sources) is built against."""

        return self._output_dir()

    def spec_for(self, form_data: Mapping[str, Any]) -> Any:
        workflow_id = str(form_data.get("workflow_id") or "").strip()
        workflow_version = str(form_data.get("workflow_version") or "").strip() or None
        return self._workflow_registry.get(workflow_id, workflow_version)

    # ------------------------------------------------------------------ validation

    @staticmethod
    def validate_source_image(path: str | Path) -> tuple[bool, str | None]:
        source = Path(path)
        if not source.exists() or not source.is_file():
            return False, f"Video workflow source image does not exist: {source}"
        return True, None

    def validate_form_data(self, form_data: Mapping[str, Any]) -> tuple[bool, str | None]:
        workflow_id = str(form_data.get("workflow_id") or "").strip()
        if not workflow_id:
            return False, "Please select a video workflow."
        try:
            spec = self.spec_for(form_data)
        except Exception as exc:
            return False, str(exc)

        try:
            _normalize_camera_intent(form_data)
            _normalize_controlnet(form_data)
            depth_input = _normalize_depth_input(form_data)
            if "seed" in spec.declared_input_names:
                parse_seed_input(form_data.get("seed"))
            if frame_count_policy(spec) is not None:
                parse_frame_count(spec, form_data.get("frame_count"))
            resolve_operator_controls(spec, form_data)
        except ValueError as exc:
            return False, str(exc)

        # Required inputs, accepted controls and experimental opt-in all come from the spec.
        problems = capability_errors(spec, form_data)
        if problems:
            return False, problems[0]
        end_anchor_text = str(form_data.get("end_anchor_path") or "").strip()
        if end_anchor_text:
            end_anchor = Path(end_anchor_text)
            if not end_anchor.exists() or not end_anchor.is_file():
                return False, f"End anchor image does not exist: {end_anchor}"
        for candidate in mid_anchor_list(form_data.get("mid_anchor_paths")):
            path = Path(candidate)
            if not path.exists() or not path.is_file():
                return False, f"Mid anchor image does not exist: {path}"
        driving_text = str(form_data.get("pose_video_path") or "").strip()
        if driving_text:
            driving = Path(driving_text).expanduser()
            if not driving.exists() or not driving.is_file():
                return False, f"Driving video does not exist: {driving}"
            if driving.suffix.lower() not in _DRIVING_VIDEO_SUFFIXES:
                allowed = ", ".join(sorted(_DRIVING_VIDEO_SUFFIXES))
                return False, f"Driving video must be a video file ({allowed}): {driving}"
        input_bindings = getattr(spec, "input_bindings", ()) or ()
        requires_depth_input = any(
            getattr(binding, "source_field", None) == "stage_config.depth_input.resolved_path"
            for binding in input_bindings
        )
        if requires_depth_input and depth_input["mode"] == "none":
            return False, (
                "The selected conditioned workflow requires depth_input.mode to be 'auto' or 'upload'."
            )
        if depth_input["mode"] == "upload":
            depth_path = Path(depth_input["path"])
            if not depth_path.exists() or not depth_path.is_file():
                return False, f"Depth input image does not exist: {depth_path}"
        if _continuity_form_supplied(form_data) and _build_continuity_link(form_data) is None:
            return False, (
                "Continuity pack metadata requires a valid pack_id. Please provide continuity_pack_id or "
                "ensure continuity_pack_summary contains a pack_id."
            )
        return True, None

    def _require_valid(self, source_image_path: str | Path, form_data: Mapping[str, Any]) -> None:
        valid, reason = self.validate_source_image(source_image_path)
        if not valid:
            raise ValueError(reason or "Video workflow source image is invalid")
        valid, reason = self.validate_form_data(form_data)
        if not valid:
            raise ValueError(reason or "Video workflow configuration is invalid")

    # ------------------------------------------------------------------ freezing

    def freeze_shared_inputs(self, form_data: Mapping[str, Any]) -> SharedFrozenInputs:
        """Freeze the source-independent inputs (driving video, anchors, uploaded depth map).

        Hashed once and reusable by every job of a batch, so a large shared clip is not re-read
        per source.  The caller validates the form first (``freeze_inputs`` does)."""

        spec = self.spec_for(form_data)
        declared_inputs = set(spec.declared_input_names)
        driving: dict[str, str] | None = None
        preparation: dict[str, Any] | None = None
        driving_text = str(form_data.get("pose_video_path") or "").strip()
        files: list[tuple[str, str, str]] = []
        blocked = str(form_data.get(MOTION_SOURCE_BLOCKED_FIELD) or "").strip()
        if blocked:
            raise ValueError(blocked)
        prepared = form_data.get(PREPARED_MOTION_SOURCE_FIELD)
        if prepared:
            # An optional, explicit preparation: every byte is re-verified now, and the derived
            # clip (what actually runs) is frozen together with the record of where it came from.
            if "pose_video" not in declared_inputs or not driving_text:
                raise ValueError(
                    "A prepared motion source needs a workflow that takes a driving video and "
                    "the driving video it was prepared from."
                )
            preparation = validate_prepared_record(
                prepared,
                original_path=driving_text,
                contract=motion_source_contract(spec, form_data.get("frame_count")),
                hash_file=sha256_file,
            )
            derived, original = preparation["derived"], preparation["original"]
            driving = {"path": str(derived["path"]), "sha256": str(derived["sha256"])}
            files.append(("original driving video", str(original["path"]), str(original["sha256"])))
        elif "pose_video" in declared_inputs and driving_text:
            # Frozen by path and content hash: the source file is only ever read (staged by the
            # backend as a copy), and provenance records exactly which clip drove the motion.
            driving_path = Path(driving_text).expanduser().resolve()
            driving = {"path": str(driving_path), "sha256": sha256_file(driving_path)}

        def add(label: str, raw_path: str) -> None:
            path = Path(raw_path).expanduser()
            try:
                files.append((label, str(path), sha256_file(path)))
            except OSError as exc:
                raise ValueError(f"The {label} is not readable: {path}") from exc

        end_anchor_text = str(form_data.get("end_anchor_path") or "").strip()
        if "end_anchor" in declared_inputs and end_anchor_text:
            add("end anchor", end_anchor_text)
        if "mid_anchors" in declared_inputs:
            for position, candidate in enumerate(mid_anchor_list(form_data.get("mid_anchor_paths"))):
                add(f"mid anchor {position + 1}", candidate)
        if any(name in declared_inputs for name in ("depth_map", "controlnet_model")):
            depth_input = _normalize_depth_input(form_data)
            if depth_input["mode"] == "upload" and depth_input["path"]:
                add("depth map", depth_input["path"])
        return SharedFrozenInputs(
            driving_video=driving, files=tuple(files), motion_source_preparation=preparation
        )

    def freeze_inputs(
        self,
        source_image_path: str | Path,
        form_data: Mapping[str, Any],
        *,
        shared: SharedFrozenInputs | None = None,
    ) -> FrozenVideoInputs:
        """Validate, then freeze the admission-scoped inputs (a random seed becomes concrete).

        ``shared`` lets a batch reuse one hash of the source-independent inputs for every source;
        omitted, they are frozen here exactly as a single submission always did."""

        self._require_valid(source_image_path, form_data)
        spec = self.spec_for(form_data)
        declared_inputs = set(spec.declared_input_names)
        if shared is None:
            shared = self.freeze_shared_inputs(form_data)

        prepared_source_path = str(Path(source_image_path).expanduser())
        source_preparation: dict[str, Any] | None = None
        preparation_policy = (getattr(spec, "backend_defaults", None) or {}).get(
            "source_preparation"
        )
        if isinstance(preparation_policy, Mapping):
            prepared = prepare_declared_workflow_source(
                source_path=source_image_path,
                output_root=self._output_dir(),
                policy=preparation_policy,
            )
            source_preparation = prepared.to_stage_config()
            prepared_source_path = prepared.prepared_image_path

        seed: int | None = None
        if "seed" in declared_inputs:
            # Recorded in the immutable job so a replay reproduces the same sampler seed.
            seed = parse_seed_input(form_data.get("seed"))
            if seed is None:
                seed = secrets.randbelow(2**31)
        return FrozenVideoInputs(
            source_image_path=str(Path(source_image_path).expanduser()),
            source_sha256=sha256_file(source_image_path),
            seed=seed,
            driving_video=shared.driving_video,
            source_preparation=source_preparation,
            prepared_source_path=prepared_source_path,
            prepared_source_sha256=sha256_file(prepared_source_path),
            shared_files=shared.files,
            motion_source_preparation=shared.motion_source_preparation,
        )

    @staticmethod
    def _verify_files(checks: list[tuple[str, str, str]]) -> None:
        for label, path, expected in checks:
            try:
                actual = sha256_file(path)
            except OSError as exc:
                raise ValueError(f"The {label} is no longer readable: {path}") from exc
            if actual != expected:
                raise ValueError(f"The {label} changed after it was frozen: {path}")

    @staticmethod
    def _shared_checks(
        driving_video: Mapping[str, str] | None, files: tuple[tuple[str, str, str], ...]
    ) -> list[tuple[str, str, str]]:
        checks = list(files)
        if driving_video is not None:
            checks.insert(0, ("driving video", driving_video["path"], driving_video["sha256"]))
        return checks

    @staticmethod
    def verify_unchanged(frozen: FrozenVideoInputs, *, include_shared: bool = True) -> None:
        """Refuse when a frozen input's bytes changed since it was frozen.

        ``include_shared=False`` checks only this source's own files; a batch verifies the shared
        inputs once (``verify_shared_unchanged``) instead of once per job."""

        checks = [
            ("source image", frozen.source_image_path, frozen.source_sha256),
            ("prepared source image", frozen.prepared_source_path, frozen.prepared_source_sha256),
        ]
        if include_shared:
            checks.extend(
                VideoWorkflowNjrBuilder._shared_checks(frozen.driving_video, frozen.shared_files)
            )
        VideoWorkflowNjrBuilder._verify_files(checks)

    @staticmethod
    def verify_shared_unchanged(shared: SharedFrozenInputs) -> None:
        VideoWorkflowNjrBuilder._verify_files(
            VideoWorkflowNjrBuilder._shared_checks(shared.driving_video, shared.files)
        )

    # ------------------------------------------------------------------ building

    def build_job(
        self,
        form_data: Mapping[str, Any],
        frozen: FrozenVideoInputs,
        *,
        learning_context: LearningJobContext | None = None,
        batch: Mapping[str, Any] | None = None,
        lineage: Mapping[str, Any] | None = None,
        sequence_plan: Mapping[str, Any] | None = None,
    ) -> VideoWorkflowBuild:
        """Build one immutable NJR.

        ``batch`` (a ``stablenew.batch.v1`` descriptor) and ``lineage`` (trustworthy source
        job/artifact ids) are additive provenance supplied by a multi-source submission; omitted,
        the job is exactly what it always was."""

        self._require_valid(frozen.source_image_path, form_data)
        spec = self.spec_for(form_data)
        workflow_id = str(form_data.get("workflow_id") or "").strip()
        end_anchor_text = str(form_data.get("end_anchor_path") or "").strip()
        end_anchor_path = str(Path(end_anchor_text).expanduser()) if end_anchor_text else ""
        mid_anchor_paths = mid_anchor_list(form_data.get("mid_anchor_paths"))

        output_route = (
            str(form_data.get("output_route") or OUTPUT_ROUTE_REPROCESS).strip()
            or OUTPUT_ROUTE_REPROCESS
        )
        if output_route not in _DEFAULT_OUTPUT_ROUTES:
            output_route = OUTPUT_ROUTE_REPROCESS

        prompt = str(form_data.get("prompt") or "").strip()
        negative_prompt = str(form_data.get("negative_prompt") or "").strip() or (
            default_negative_prompt(spec) if "negative_prompt" in spec.declared_input_names else ""
        )
        form_with_defaults = {**form_data, "negative_prompt": negative_prompt}
        motion_profile = str(form_data.get("motion_profile") or "").strip()
        camera_intent = _normalize_camera_intent(form_data)
        controlnet = _normalize_controlnet(form_data)
        depth_input = _normalize_depth_input(form_data)
        output_dir = self._output_dir()
        continuity_link = _build_continuity_link(form_data)

        workflow_config: dict[str, Any] = {
            "enabled": True,
            "workflow_id": workflow_id,
            "workflow_version": spec.workflow_version,
            "backend_id": spec.backend_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            # Neutral, explicit execution intent (PR-VID-120 contract); the historical
            # stage-owned bridge is not needed for work compiled here.
            VIDEO_EXECUTION_KEY: build_video_execution_block(
                spec, {**form_with_defaults, "camera_intent": camera_intent}
            ),
        }
        declared_inputs = set(spec.declared_input_names)
        if "end_anchor" in declared_inputs:
            workflow_config["end_anchor_path"] = end_anchor_path
        if "mid_anchors" in declared_inputs:
            workflow_config["mid_anchor_paths"] = mid_anchor_paths
        if "motion_profile" in declared_inputs:
            workflow_config["motion_profile"] = motion_profile
        if "camera_preset" in declared_inputs:
            workflow_config["camera_intent"] = camera_intent
        if any(name in declared_inputs for name in ("depth_map", "controlnet_model")):
            workflow_config["controlnet"] = controlnet
            workflow_config["depth_input"] = depth_input
        driving_provenance = dict(frozen.driving_video) if frozen.driving_video else None
        if driving_provenance is not None:
            workflow_config["pose_video_path"] = driving_provenance["path"]
            workflow_config["pose_video_sha256"] = driving_provenance["sha256"]
        preparation_record = (
            dict(frozen.motion_source_preparation) if frozen.motion_source_preparation else None
        )
        if preparation_record is not None:
            workflow_config["motion_source_preparation"] = preparation_record
        source_preparation = dict(frozen.source_preparation) if frozen.source_preparation else None
        if source_preparation is not None:
            workflow_config["source_preparation"] = source_preparation

        config: dict[str, Any] = {
            "video_workflow": workflow_config,
            "pipeline": {
                "output_route": output_route,
                "video_workflow_enabled": True,
            },
        }
        frozen_seed = frozen.seed if "seed" in declared_inputs else None
        if frozen_seed is not None:
            workflow_config["seed"] = frozen_seed
        frozen_frame_count: int | None = None
        length_policy = frame_count_policy(spec)
        if length_policy is not None:
            # Frozen at admission so the queued job, its artifact and any replay agree on length.
            frozen_frame_count = parse_frame_count(spec, form_data.get("frame_count"))
            workflow_config["frame_count"] = frozen_frame_count
            workflow_config["fps"] = length_policy["fps"]
        # Declared workflow controls (e.g. Animate-2 motion prompt / pose strength) are frozen
        # here, like seed and length; the compiler binds them to the exact graph inputs.
        frozen_controls = resolve_operator_controls(spec, form_data)
        if frozen_controls is not None:
            workflow_config["operator_controls"] = frozen_controls
        # Optional RIFE smoothing of the finished clip (PR-VID-SMOOTH-302). Validated here, so a missing
        # runtime or an unsupported factor is refused at admission, and frozen as resolved values so the queued
        # job and any replay smooth the same way.
        smoothing = normalize_interpolation_request(form_data.get("interpolation"))
        frozen_interpolation: dict[str, Any] | None = None
        if smoothing is not None:
            resolved_executable = find_rife_executable(smoothing.executable_path)
            source_fps = (length_policy or {}).get("fps")
            frozen_interpolation = {
                "enabled": True,
                "multiplier": smoothing.multiplier
                or (default_rife_multiplier(source_fps) if source_fps else None),
                "executable_path": None
                if resolved_executable is None
                else str(resolved_executable),
                "model_dir": smoothing.model_dir,
            }
            workflow_config["interpolation"] = frozen_interpolation
        if sequence_plan is not None:
            # One NJR, N sequential segments (PR-VID-SEQ-330-CORE): the plan was frozen at admission and the
            # runner executes it inside this single job.
            workflow_config["sequence_metadata"] = dict(sequence_plan)
        if continuity_link:
            config["metadata"] = {"continuity": dict(continuity_link)}

        extra_metadata = {
            "video_workflow": {
                "workflow_id": workflow_id,
                "workflow_version": spec.workflow_version,
                "display_name": spec.display_name,
                "backend_id": spec.backend_id,
                "governance_state": spec.governance_state,
                "experimental_opt_in": config["video_workflow"][VIDEO_EXECUTION_KEY][
                    EXPERIMENTAL_OPT_IN_FIELD
                ],
                "output_route": output_route,
            }
        }
        if "camera_intent" in workflow_config:
            extra_metadata["video_workflow"]["camera_intent"] = camera_intent
        if "controlnet" in workflow_config:
            extra_metadata["video_workflow"]["controlnet"] = controlnet
            extra_metadata["video_workflow"]["depth_input"] = depth_input
        if source_preparation:
            extra_metadata["video_workflow"]["source_preparation"] = dict(source_preparation)
        if frozen_seed is not None:
            extra_metadata["video_workflow"]["seed"] = frozen_seed
        if frozen_interpolation is not None:
            extra_metadata["video_workflow"]["interpolation"] = dict(frozen_interpolation)
        if frozen_controls is not None:
            extra_metadata["video_workflow"]["operator_controls"] = dict(frozen_controls)
        if driving_provenance is not None:
            extra_metadata["video_workflow"]["pose_video"] = dict(driving_provenance)
        if preparation_record is not None:
            extra_metadata["video_workflow"]["motion_source_preparation"] = {
                side: {key: preparation_record[side].get(key) for key in ("path", "sha256")}
                for side in ("original", "derived")
            } | {"settings": dict(preparation_record["settings"])}
        if frozen_frame_count is not None and length_policy is not None:
            extra_metadata["video_workflow"].update(
                frame_count=frozen_frame_count,
                fps=length_policy["fps"],
                approximate_seconds=approximate_seconds(frozen_frame_count, length_policy["fps"]),
            )
        if sequence_plan is not None:
            extra_metadata["video_workflow"]["sequence"] = {
                "sequence_id": sequence_plan.get("sequence_id"),
                "segments": len(sequence_plan.get("segments") or ()),
            }
        if continuity_link:
            extra_metadata["continuity_link"] = dict(continuity_link)
        if batch is not None:
            extra_metadata["batch"] = dict(batch)
            identity: dict[str, Any] = {
                "original_path": frozen.source_image_path,
                "original_sha256": frozen.source_sha256,
                "prepared_path": frozen.prepared_source_path,
                "prepared_sha256": frozen.prepared_source_sha256,
                "preparation_policy": str((source_preparation or {}).get("policy") or "none"),
            }
            parent_job = str((lineage or {}).get("source_job_id") or "").strip()
            parent_artifact = str((lineage or {}).get("source_artifact_id") or "").strip()
            if parent_job:
                identity["source_job_id"] = parent_job
                extra_metadata["parent_job_id"] = parent_job
            if parent_artifact:
                identity["source_artifact_id"] = parent_artifact
                extra_metadata["parent_artifact_id"] = parent_artifact
            extra_metadata["video_workflow"]["source_identity"] = identity

        njr = ReprocessJobBuilder().build_reprocess_job(
            input_image_paths=[frozen.prepared_source_path],
            stages=["video_workflow"],
            config=config,
            output_dir=output_dir,
            prompt=prompt,
            negative_prompt=negative_prompt,
            pack_name="Video Workflow",
            source="video_workflow",
            extra_metadata=extra_metadata,
            learning_context=learning_context,
        )
        return VideoWorkflowBuild(
            njr=njr,
            seed=frozen_seed,
            frame_count=frozen_frame_count,
            source_preparation=source_preparation or {},
        )


__all__ = [
    "HASH_CHUNK_BYTES",
    "MOTION_SOURCE_BLOCKED_FIELD",
    "PREPARED_MOTION_SOURCE_FIELD",
    "FrozenVideoInputs",
    "SharedFrozenInputs",
    "VideoWorkflowBuild",
    "VideoWorkflowNjrBuilder",
    "sha256_file",
]
