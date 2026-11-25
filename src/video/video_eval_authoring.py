"""Edit incomplete video eval suites, then validate and publish a fresh runnable suite."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from ntpath import isreserved
from pathlib import Path, PureWindowsPath
from typing import Any, cast

from PIL import Image

from src.utils.atomic_io import atomic_publish_json
from src.video.sequence_admission import workflow_segment_errors
from src.video.sequence_plan import MAX_SEED_WORKFLOW
from src.video.storyboard_readiness import unsupported_controls
from src.video.svd_config import SVDConfig
from src.video.svd_models import resolve_svd_model_spec
from src.video.svd_postprocess import validate_svd_postprocess_config
from src.video.svd_preprocess import SVD_SUPPORTED_IMAGE_SUFFIXES
from src.video.video_eval_import import is_private_suite
from src.video.video_eval_motion import (
    DRIVING_SUFFIXES,
    MOTION_BLOCK,
    PREP_WORKFLOW,
    check_arm_form,
    driving_support_error,
    file_sha256,
    motion_form,
    parse_motion,
)
from src.video.video_eval_suite import (
    ARM_BACKEND_SVD,
    ARM_BACKEND_WORKFLOW,
    MAX_EVAL_JOBS,
    SUITE_SCHEMA,
    SUITE_SCHEMA_V2,
    SUITE_SCHEMAS,
    EvalArm,
    EvalSegment,
    EvalSuiteError,
    _identifier,
    _load_arm,
    _load_segments,
    parse_eval_suite,
)
from src.video.video_workflow_intent import capability_errors, mid_anchor_list
from src.video.video_workflow_njr_builder import (
    PREPARED_MOTION_SOURCE_FIELD,
    VideoWorkflowNjrBuilder,
)
from src.video.workflow_contracts import WorkflowSpec
from src.video.workflow_frame_count import frame_count_policy, parse_frame_count
from src.video.workflow_input_integrity import requires_exact_motion
from src.video.workflow_registry import (
    WorkflowLookupError,
    WorkflowRegistry,
    build_default_workflow_registry,
    latest_spec_per_workflow,
)

_MAX_SUITE_BYTES = 1024 * 1024
_TOOL_PATH_KEYS = {
    "executable_path",
    "model_dir",
    "cache_dir",
    "facelib_model_root",
    "model_path",
    "model_path_x2",
    "codeformer_weight_path",
    "gfpgan_weight_path",
}
_INPUT_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvalSuiteError(f"Duplicate JSON field {key!r}")
        result[key] = value
    return result


def _invalid_number(value: str) -> None:
    raise EvalSuiteError(f"Invalid JSON number {value!r}")


def _local_path(path: Path) -> Path:
    """Reject remote paths, devices and alternate streams before accessing a source."""
    expanded = path.expanduser()
    windows = PureWindowsPath(expanded)
    if windows.drive.startswith("\\\\") or (
        os.name == "nt"
        and (
            windows.drive
            and not windows.is_absolute()
            or any(isreserved(part) for part in windows.parts if part != windows.anchor)
        )
    ):
        raise EvalSuiteError(f"Choose a local file: {path}")
    return expanded


def _inspect_image(path: Path, pin: Any = None) -> tuple[Path, str]:
    path = _local_path(_local_path(path).resolve())
    if not path.is_file():
        raise EvalSuiteError(f"Source image not found or not a regular file: {path}")
    try:
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
            pinned = str(pin or "").strip().lower()
            if pinned and pinned != actual:
                raise EvalSuiteError(
                    f"{path.name} changed or its SHA-256 is invalid. Rebind it to accept the current image."
                )
            stream.seek(0)
            with Image.open(stream) as image:
                image.verify()
            stream.seek(0)
            with Image.open(stream) as image:
                image.load()
    except EvalSuiteError:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise EvalSuiteError(f"Cannot read image {path.name}: {exc}") from exc
    return path, actual


def bind_source(path: Path) -> dict[str, str]:
    """Explicitly bind a selected file, recording the bytes the operator selected."""
    source, digest = _inspect_image(path)
    return {"image": str(source), "image_sha256": digest}


def bind_driving_video(path: Path) -> dict[str, Any]:
    """Bind a local driving video and record the bytes selected.

    The result is a local video with *no* library or job provenance: it is never described as anything else unless
    ``bind_library_asset`` supplies a verified Motion Library binding for these exact bytes."""

    local = _local_path(_local_path(path).resolve())
    if local.suffix.lower() not in DRIVING_SUFFIXES:
        raise EvalSuiteError(
            f"Choose a video file ({', '.join(sorted(DRIVING_SUFFIXES))}): {local.name}"
        )
    if not local.is_file():
        raise EvalSuiteError(f"Driving video not found or not a regular file: {local}")
    try:
        digest = file_sha256(local)
    except OSError as exc:
        raise EvalSuiteError(f"Cannot read driving video {local.name}: {exc}") from exc
    return {"driving": {"path": str(local), "sha256": digest}}


def bind_library_asset(store: Any, asset_id: str, cancel: Any = None) -> dict[str, Any]:
    """Bind a verified Motion Library clip: its bytes are hashed now and must equal the catalogued SHA-256.

    Returns the ``motion`` fields the library can supply (the driving file, its library binding, a harvested asset's
    original and window, and the asset's own framing, viewpoint and direction notes) for the operator to review. Nothing
    is queued and the library is not modified."""

    from src.video.motion_library.verification import FILE_OK, verify_content

    asset = store.get(asset_id)
    if asset is None:
        raise EvalSuiteError(f"No Motion Library asset {asset_id!r}.")
    path = store.asset_path(asset)
    check = verify_content(asset, path, cancel)
    if check.state != FILE_OK:
        raise EvalSuiteError(f"{asset.display_name}: {check.message}")
    binding: dict[str, Any] = {"asset_id": asset.asset_id, "sha256": asset.sha256}
    harvest = getattr(asset, "harvest", None)
    if harvest is not None:
        binding["derived_from"] = {
            "original_sha256": harvest.original_sha256,
            "start_frame": harvest.start_frame,
            "end_frame": harvest.end_frame,
            "cadence": harvest.cadence,
        }
    notes = {
        key: value
        for key, value in (
            ("framing", getattr(asset, "framing", "")),
            ("viewpoint", getattr(asset, "viewpoint", "")),
        )
        if value and value != "unknown"
    }
    suggested: dict[str, Any] = {
        "driving": {"path": str(path), "sha256": asset.sha256, "library_asset": binding},
        "annotations": notes,
    }
    if getattr(asset, "motion_direction", ""):
        suggested["direction"] = asset.motion_direction
    label = asset.effective_motion_label
    if label:
        suggested["action"] = label
    return suggested


@dataclass
class EvalSuiteDraft:
    data: dict[str, Any]
    source: Path | None = None

    @classmethod
    def new(cls) -> EvalSuiteDraft:
        draft = cls({"schema": SUITE_SCHEMA, "suite_id": "", "seed": 0, "cases": [], "arms": []})
        draft.add_case()
        draft.data["baseline_arm"] = draft.add_arm()["arm_id"]
        return draft

    @classmethod
    def open(cls, path: Path) -> EvalSuiteDraft:
        if is_private_suite(path):
            raise EvalSuiteError("Private suite skipped. Review it in its original location.")
        source = _local_path(_local_path(path).resolve(strict=True))
        if is_private_suite(source) or not source.is_file():
            raise EvalSuiteError(
                "Choose a regular eval suite JSON file that is not a private sidecar."
            )
        with source.open("rb") as stream:
            raw = stream.read(_MAX_SUITE_BYTES + 1)
        if len(raw) > _MAX_SUITE_BYTES:
            raise EvalSuiteError("Eval suite JSON exceeds 1 MiB.")
        data = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_number
        )
        if not isinstance(data, dict) or data.get("schema") not in SUITE_SCHEMAS:
            raise EvalSuiteError(
                f"Expected an eval suite with schema {' or '.join(SUITE_SCHEMAS)}."
            )
        for key in ("cases", "arms"):
            items = data.setdefault(key, [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise EvalSuiteError(f"'{key}' must be an array of objects.")
        return cls(data, source)

    @property
    def cases(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.data["cases"])

    @property
    def arms(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.data["arms"])

    @property
    def job_count(self) -> int:
        return len(self.cases) * len(self.arms)

    def add_case(self) -> dict[str, Any]:
        case = {"case_id": _next_id(self.cases, "case"), "image": "", "prompt": ""}
        self.cases.append(case)
        return case

    def add_arm(self, original: dict[str, Any] | None = None) -> dict[str, Any]:
        arm = deepcopy(original) if original is not None else {"backend": ARM_BACKEND_WORKFLOW}
        arm["arm_id"] = _next_id(self.arms, "arm")
        self.arms.append(arm)
        return arm

    def add_motion_case(self, motion: dict[str, Any] | None = None) -> dict[str, Any]:
        """A new case that carries a driving-motion block (an empty one is completed by the editor)."""

        case = self.add_case()
        case[MOTION_BLOCK] = deepcopy(motion) if motion is not None else {}
        return case

    def duplicate_case_for_source(
        self, index: int, image: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Copy case ``index`` for another source image: the driving reference and every expectation are kept.

        The copy gets a fresh id and its own image binding (or none yet, which validation refuses until it is bound),
        and never inherits the original's image digest. No arm is added: arms stay shared across all cases."""

        copy = deepcopy(self.cases[index])
        copy["case_id"] = _next_id(self.cases, "case")
        copy.pop("image_sha256", None)
        copy["image"] = ""
        motion = copy.get(MOTION_BLOCK)
        if isinstance(motion, dict):
            # PR-VID-MOTION-420: an alignment belongs to one source image and one driver; another subject must be
            # aligned for itself, never inherit these numbers.
            motion.pop("alignment", None)
        if image:
            copy.update(image)
        self.cases.append(copy)
        return copy

    @property
    def has_motion(self) -> bool:
        return any(MOTION_BLOCK in case for case in self.cases)


def _next_id(items: list[dict[str, Any]], kind: str) -> str:
    existing = {str(item.get(f"{kind}_id") or "").strip() for item in items}
    return next(
        f"{kind}_{index}" for index in range(1, len(items) + 2) if f"{kind}_{index}" not in existing
    )


class EvalWorkflowCatalog:
    """Exact offerable identities, with the existing picker rule for legacy omitted versions."""

    def __init__(self, registry: WorkflowRegistry | None = None) -> None:
        self._registry = registry if registry is not None else build_default_workflow_registry()
        self.specs = self._registry.list_offerable_specs("comfy")
        self._latest = {
            spec.workflow_id: spec.workflow_version for spec in latest_spec_per_workflow(self.specs)
        }

    def get(self, workflow_id: str, workflow_version: str | None = None) -> WorkflowSpec:
        spec = self._registry.get_offerable(workflow_id, workflow_version)
        if spec.backend_id != "comfy":
            raise WorkflowLookupError(f"{workflow_id} is not an offerable Comfy workflow.")
        return spec

    def inherited_version(self, workflow_id: str) -> str | None:
        return self._latest.get(workflow_id)

    def list_specs_for_backend(self, backend_id: str) -> list[WorkflowSpec]:
        return self._registry.list_offerable_specs(backend_id)


@dataclass(frozen=True)
class EvalDraftValidation:
    errors: tuple[str, ...]
    record: dict[str, Any] | None


def _problem(errors: list[str], label: str, exc: BaseException) -> None:
    errors.append(f"{label}: {exc}" if label else str(exc))


def _validate_case(
    case: dict[str, Any], source_dir: Path, errors: list[str], *, inspect_source: bool
) -> tuple[EvalSegment, ...]:
    label = f"Case {case.get('case_id') or '(unnamed)'}"
    try:
        image = str(case.get("image") or "").strip()
        if not image:
            raise EvalSuiteError("Choose a source image.")
        path = _local_path(Path(image))
        if not path.is_absolute():
            path = source_dir / path
        if inspect_source:
            absolute, sha = _inspect_image(path, case.get("image_sha256"))
            case.update(image=str(absolute), image_sha256=sha)
    except _INPUT_ERRORS as exc:
        _problem(errors, label, exc)
    segments: tuple[EvalSegment, ...] = ()
    try:
        segments = _load_segments(case.get("segments"), str(case.get("case_id") or "(unnamed)"))
        prompt = str(case.get("prompt") or "").strip()
        if segments and prompt:
            raise EvalSuiteError(
                "A sequence needs a prompt per segment. Clear the single-clip prompt."
            )
        if not segments and not prompt:
            raise EvalSuiteError("Enter a motion prompt.")
    except _INPUT_ERRORS as exc:
        _problem(errors, label, exc)
    if MOTION_BLOCK in case:
        try:
            if segments:
                raise EvalSuiteError(
                    f"{label}: a driving-motion case is a single clip; ordered segments are not supported with it."
                )
            raw_driver = (
                (case[MOTION_BLOCK].get("driving") or {})
                if isinstance(case[MOTION_BLOCK], dict)
                else {}
            )
            if isinstance(raw_driver, dict) and str(raw_driver.get("path") or "").strip():
                _local_path(Path(str(raw_driver["path"]).strip()))
            binding = parse_motion(
                case[MOTION_BLOCK], str(case.get("case_id") or "(unnamed)"), source_dir
            )
            if (
                inspect_source
            ):  # the verified absolute path and bytes, exactly as the suite will pin them
                case[MOTION_BLOCK] = binding.to_record()
        except _INPUT_ERRORS as exc:
            _problem(errors, "", exc)
    if case.get("tags") is not None and not isinstance(case["tags"], list):
        errors.append(f"{label}: tags must be a list.")
    return segments


def _validate_workflow(
    arm: EvalArm,
    case: dict[str, Any],
    segments: tuple[EvalSegment, ...],
    seed: int,
    builder: VideoWorkflowNjrBuilder,
) -> list[str]:
    form = dict(arm.overrides)
    form.update(
        prompt=segments[0].prompt if segments else str(case.get("prompt") or "").strip(),
        negative_prompt=str(case.get("negative_prompt") or "").strip(),
        seed=str(seed),
    )
    spec = builder.spec_for(form)
    prepared_by_case = False
    if case.get(MOTION_BLOCK) is not None:
        # The case's driving reference is applied exactly as the production preview applies it; a workflow that takes
        # no driving video refuses the case instead of silently running without it.
        binding = parse_motion(case[MOTION_BLOCK], str(case.get("case_id") or ""), None)
        problem = driving_support_error(spec, binding)
        if problem:
            return [problem]
        check_arm_form(arm.arm_id, arm.overrides)
        form = motion_form(binding, form)
        prepared_by_case = binding.preparation_mode == PREP_WORKFLOW
    for key in ("camera_intent", "controlnet", "depth_input", "interpolation", "operator_controls"):
        if form.get(key) is not None and not isinstance(form[key], dict):
            raise EvalSuiteError(f"{key} must be an object.")
    if (
        "frame_count" in form
        and frame_count_policy(spec) is None
        and form["frame_count"] not in ("", None)
    ):
        raise EvalSuiteError(f"'{spec.display_name}' does not accept a frame count.")
    errors = capability_errors(spec, form, prompt_per_segment=bool(segments))
    if (
        requires_exact_motion(spec)
        and not form.get(PREPARED_MOTION_SOURCE_FIELD)
        and not prepared_by_case
    ):
        errors.append(
            "This workflow requires an accepted Prepare Motion Source record in the suite "
            "(or a motion case whose preparation mode is workflow_prepared)."
        )
    if segments and segments[0].frame_count is not None:
        form["frame_count"] = segments[0].frame_count
    valid, reason = builder.validate_form_data(form, prompt_per_segment=bool(segments))
    if not valid and reason and reason not in errors:
        errors.append(reason)
    if segments:
        errors.extend(unsupported_controls(form))
        policy = frame_count_policy(spec)
        for index, segment in enumerate(segments, start=1):
            if seed + index - 1 > MAX_SEED_WORKFLOW:
                errors.append(
                    f"Segment {index}: the shared seed plus the segment offset exceeds {MAX_SEED_WORKFLOW}."
                )
            count = segment.frame_count
            if count is None and policy is not None:
                count = parse_frame_count(spec, arm.overrides.get("frame_count"))
            problems = workflow_segment_errors(
                spec,
                spec,
                count or 0,
                int(policy["fps"]) if policy else 0,
                experimental_opt_in=form.get("experimental_opt_in") is True,
            )
            errors.extend(f"Segment {index}: {problem}" for problem in problems)
    return errors


def configured_tool_paths(
    overrides: Mapping[str, Any], prefix: str = ""
) -> Iterator[tuple[str, str]]:
    """Paths with execution significance that the queue confirmation should make visible."""
    for key, value in overrides.items():
        setting = f"{prefix}{key}"
        if isinstance(value, Mapping):
            yield from configured_tool_paths(value, f"{setting}.")
        elif value and key in _TOOL_PATH_KEYS:
            yield setting, str(value)


def _check_arm_paths(overrides: Mapping[str, Any]) -> None:
    """Check imported paths before consulting a backend validator that may access them."""
    for key, value in overrides.items():
        if isinstance(value, dict):
            _check_arm_paths(value)
        elif key == "mid_anchor_paths":
            for item in mid_anchor_list(value):
                _local_path(Path(item))
        elif value and (key == "path" or key in _TOOL_PATH_KEYS or key.endswith(("_path", "_dir"))):
            _local_path(Path(str(value).strip()))


def _validate_backend(
    arm: EvalArm,
    cases: list[dict[str, Any]],
    segments: list[tuple[EvalSegment, ...]],
    seed: int,
    builder: VideoWorkflowNjrBuilder,
    errors: list[str],
) -> None:
    label = f"Arm {arm.arm_id}"
    _check_arm_paths(arm.overrides)
    if arm.backend == ARM_BACKEND_SVD:
        if any(segments):
            errors.append(f"{label}: native SVD cannot run sequence cases.")
        for case in cases:
            if case.get(MOTION_BLOCK) is not None:
                errors.append(
                    f"{label} × {case.get('case_id') or '(unnamed)'}: native SVD takes no driving video, so it "
                    "cannot run a driving-motion case (the reference is not dropped to make the arm queueable)."
                )
        for case in cases:
            image = str(case.get("image") or "").strip()
            if image and Path(image).suffix.lower() not in SVD_SUPPORTED_IMAGE_SUFFIXES:
                errors.append(
                    f"{label} × {case.get('case_id')}: native SVD does not support this image type."
                )
        config = SVDConfig.from_dict(dict(arm.overrides))
        spec = resolve_svd_model_spec(config.inference.model_id)
        if config.inference.num_frames > spec.max_num_frames:
            errors.append(
                f"{label}: {spec.display_name} supports at most {spec.max_num_frames} frames."
            )
        valid, reason = validate_svd_postprocess_config(config)
        if not valid:
            errors.append(f"{label}: {reason}")
        return
    # Resolve even when there are no cases. A typo must never be replaced by a different revision.
    builder.spec_for(arm.overrides)
    if "experimental_opt_in" in arm.overrides and not isinstance(
        arm.overrides["experimental_opt_in"], bool
    ):
        errors.append(f"{label}: experimental opt-in must be a boolean.")
    for case, shots in zip(cases, segments, strict=True):
        case_label = f"{label} × {case.get('case_id') or '(unnamed)'}"
        try:
            errors.extend(
                f"{case_label}: {problem}"
                for problem in _validate_workflow(arm, case, shots, seed, builder)
            )
        except _INPUT_ERRORS as exc:
            _problem(errors, case_label, exc)


def validate_draft(draft: EvalSuiteDraft, catalog: EvalWorkflowCatalog) -> EvalDraftValidation:
    """Check a detached snapshot. Asset/runtime readiness is checked again at canonical Preview."""
    errors: list[str] = []
    record = deepcopy(draft.data)
    try:
        record["suite_id"] = _identifier(record.get("suite_id"), "suite_id")
    except EvalSuiteError as exc:
        _problem(errors, "", exc)
    try:
        seed = int(str(record.get("seed", 0)).strip())
        if not 0 <= seed < 2**32:
            raise ValueError
        record["seed"] = seed
    except (TypeError, ValueError):
        errors.append("Shared seed must be a whole number in 0..2^32-1.")
        seed = 0

    ids: dict[str, list[str]] = {}
    for kind, plural in (("case", "cases"), ("arm", "arms")):
        items = record[plural]
        ids[kind] = [str(item.get(f"{kind}_id") or "").strip() for item in items]
        if not items:
            errors.append(f"Add at least one {kind}.")
        for value, count in Counter(ids[kind]).items():
            try:
                _identifier(value, f"{kind}_id")
            except EvalSuiteError as exc:
                _problem(errors, "", exc)
            if count > 1:
                errors.append(f"Duplicate {kind} ID: {value!r}.")
    baseline = str(record.get("baseline_arm") or (ids["arm"][0] if ids["arm"] else "")).strip()
    if baseline not in ids["arm"] or not baseline:
        errors.append("Choose an existing arm as the baseline.")
    record["baseline_arm"] = baseline
    over_limit = draft.job_count > MAX_EVAL_JOBS
    if over_limit:
        errors.append(f"{draft.job_count} jobs exceeds the limit of {MAX_EVAL_JOBS}.")

    base = draft.source.parent if draft.source is not None else Path.cwd()
    cases = record["cases"]
    segments = [_validate_case(case, base, errors, inspect_source=not over_limit) for case in cases]
    if any(MOTION_BLOCK in case for case in cases):
        # A motion case needs the v2 schema; v1 readers then refuse the file instead of ignoring the driver. The saved
        # draft is a new version file: no existing plan is rewritten.
        record["schema"] = SUITE_SCHEMA_V2
    builder = VideoWorkflowNjrBuilder(workflow_registry=catalog, output_dir_provider=lambda: None)
    for item in record["arms"]:
        try:
            arm = _load_arm(item)
            if arm.backend == ARM_BACKEND_WORKFLOW and "workflow_version" not in arm.overrides:
                workflow = str(arm.overrides["workflow_id"]).strip()
                version = catalog.inherited_version(workflow)
                arm = EvalArm(
                    arm.arm_id,
                    arm.label,
                    arm.backend,
                    {**arm.overrides, "workflow_version": version},
                )
            _validate_backend(
                arm,
                [] if over_limit else cases,
                [] if over_limit else segments,
                seed,
                builder,
                errors,
            )
        except _INPUT_ERRORS as exc:
            _problem(errors, f"Arm {item.get('arm_id') or '(unnamed)'}", exc)

    # The executable parser has the final word, including rechecking every pinned source.
    if not errors:
        try:
            parse_eval_suite(base / "draft.suite.json", _encode(record))
        except _INPUT_ERRORS as exc:
            _problem(errors, "", exc)
    return EvalDraftValidation(tuple(dict.fromkeys(errors)), None if errors else record)


def _encode(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > _MAX_SUITE_BYTES:
        raise EvalSuiteError("Eval suite JSON exceeds 1 MiB.")
    return raw


def publish_validated_suite(
    validation: EvalDraftValidation, plan_root: Path, *, day: date | None = None
) -> Path:
    """Publish a validated snapshot as a new date-stamped version without replacing any file."""
    record = validation.record
    if record is None or validation.errors:
        raise EvalSuiteError("Resolve validation errors before saving the suite.")
    root = _local_path(_local_path(plan_root).resolve())
    folder = root / "video"
    if folder.resolve() != folder or folder.is_symlink():
        raise EvalSuiteError(
            "The Evaluation Plans video folder must be inside the configured root."
        )
    raw = _encode(record)
    stem = f"{day or date.today():%Y%m%d}_{_identifier(record['suite_id'], 'suite_id')}"
    parse_eval_suite(folder / f"{stem}.suite.json", raw)
    for version in range(1, 1000):
        target = folder / f"{stem}_v{version:03d}.suite.json"
        if os.path.lexists(target):
            continue
        try:
            return atomic_publish_json(
                target, record, indent=2, ensure_ascii=False, allow_nan=False
            )
        except FileExistsError:
            continue
    raise EvalSuiteError("All 999 versions for this suite ID and date already exist.")
