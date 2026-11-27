"""Translate bounded phone intent into the native Video Workflow and eval planners."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from typing import Any

from PIL import Image

from src.app.site_media_files import SiteOutputError, inside
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_phone_admission import PhonePreviewInput
from src.controller.job_service import JobService
from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.policy_warnings import SURFACE_PHONE
from src.video.video_eval_run import (
    EVAL_OUTPUT_FOLDER,
    BuiltEvalJob,
    EvalJobPlan,
    VideoEvalRunService,
)
from src.video.video_eval_suite import (
    ARM_BACKEND_WORKFLOW,
    MAX_EVAL_JOBS,
    EvalArm,
    EvalCase,
    EvalSuite,
)
from src.video.video_workflow_intent import WARNING_SURFACE_FIELD, default_negative_prompt
from src.video.video_workflow_njr_builder import FrozenVideoInputs, VideoWorkflowNjrBuilder
from src.video.workflow_contracts import WorkflowSpec
from src.video.workflow_frame_count import frame_count_policy, legal_frame_counts, parse_frame_count
from src.video.workflow_registry import latest_spec_per_workflow
from src.video.workflow_source_preparation import (
    prepared_source_destination,
    resolve_declared_target,
)

_PHONE_INPUTS = frozenset(
    {"source_image", "prompt", "seed", "target_width", "target_height", "frame_count"}
)
_DIGEST = re.compile(r"[a-f0-9]{64}")
_MAX_SOURCES = 16
_MAX_ARMS = 4


def _public_workflow(spec: WorkflowSpec) -> dict[str, Any]:
    frames = frame_count_policy(spec)
    assert frames is not None
    return {
        "workflow_id": spec.workflow_id,
        "workflow_version": spec.workflow_version,
        "label": spec.display_name,
        "experimental": spec.is_experimental,
        "graph_revision": spec.pinned_revision,
        "models": [
            PureWindowsPath(dep.locator).name
            for dep in spec.dependency_specs
            if dep.dependency_kind == "model_file"
        ],
        "default_frames": frames["default"],
        "frame_counts": legal_frame_counts(spec),
        "fps": frames["fps"],
    }


def _unlinked_destination(root: Path, path: Path) -> None:
    # Existing components must stay beneath the approved folder. A nonexistent
    # tail can be created by the native preparation or eval manifest writer.
    while True:
        try:
            inside(root, path)
        except FileNotFoundError:
            if path == root:
                raise
            path = path.parent
            continue
        return


def _phone_specs(registry: DefaultWorkflowRegistryPort) -> dict[tuple[str, str], WorkflowSpec]:
    """The Comfy workflows a phone can fill: only the bounded phone inputs, with source preparation and frames."""

    return {
        spec.registry_key: spec
        for spec in registry.list_specs_for_backend("comfy")
        if set(spec.required_input_names) <= _PHONE_INPUTS
        and _PHONE_INPUTS | {"negative_prompt"} <= set(spec.declared_input_names)
        and spec.backend_defaults.get("source_preparation")
        and frame_count_policy(spec) is not None
    }


def make_video_spec(specs: dict[tuple[str, str], WorkflowSpec]) -> WorkflowSpec | None:
    """The recommended Make Video workflow (the approved ``make_video_default``, today Wan2.2 I2V-A14B 4-step)."""

    return next(
        (
            spec
            for spec in latest_spec_per_workflow(list(specs.values()))
            if not spec.is_experimental and spec.backend_defaults.get("make_video_default")
        ),
        None,
    )


def gateway_make_video(
    root: Path,
    path: Path,
    digest: str,
    prompt: str,
    seed: int,
    *,
    registry: DefaultWorkflowRegistryPort | None = None,
) -> tuple[WorkflowSpec, PhonePreviewInput]:
    """RG-140 slice 2: the desktop's Make Video hand-off, compiled without the Video Workflow tab.

    The image at ``path`` (already re-hashed as ``digest``) is the source of the recommended approved workflow, at its
    default frame count and default negative prompt, with ``prompt`` and ``seed``. The prepared source is frozen under
    ``root`` exactly as the desktop does; nothing is queued here. Refusals are closed ``SiteOutputError`` codes.
    """

    registry = registry or DefaultWorkflowRegistryPort()
    specs = _phone_specs(registry)
    spec = make_video_spec(specs)
    if spec is None:
        raise SiteOutputError("video_unavailable")
    frames = frame_count_policy(spec)
    assert frames is not None
    form = {
        "workflow_id": spec.workflow_id,
        "workflow_version": spec.workflow_version,
        "experimental_opt_in": False,
        "frame_count": frames["default"],
        # N1: a phone Queue records its accepted warnings as accepted on the phone.
        WARNING_SURFACE_FIELD: SURFACE_PHONE,
        "prompt": prompt,
        "negative_prompt": "",
        "seed": seed,
    }
    builder = VideoWorkflowNjrBuilder(
        workflow_registry=registry, output_dir_provider=lambda: str(root)
    )
    try:
        with Image.open(path) as image:
            width, height = image.size
        # The native preparer applies EXIF before choosing a target: guard both axis orders against links.
        for dimensions in ((width, height), (height, width)):
            _orientation, target, _rule = resolve_declared_target(
                spec.backend_defaults["source_preparation"], *dimensions
            )
            _unlinked_destination(root, prepared_source_destination(root, digest, target))
        frozen = builder.freeze_inputs(path, form)
        if frozen.source_sha256 != digest:
            raise SiteOutputError("source_changed")
        inside(root, Path(frozen.prepared_source_path))
        built = builder.build_job(form, frozen, lineage={"source_artifact_id": f"sha256:{digest}"})
    except SiteOutputError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise SiteOutputError("video_preview_failed") from exc

    def require_current() -> None:
        inside(root, Path(frozen.source_image_path))
        inside(root, Path(frozen.prepared_source_path))
        builder.verify_unchanged(frozen)

    return spec, PhonePreviewInput(spec.display_name, (built.njr,), require_current)


class PhoneVideo:
    def __init__(
        self, jobs: JobService, *, registry: DefaultWorkflowRegistryPort | None = None
    ) -> None:
        self._jobs = jobs
        self._registry = registry or DefaultWorkflowRegistryPort()

    def _supported(self) -> dict[tuple[str, str], WorkflowSpec]:
        return _phone_specs(self._registry)

    def options(self) -> dict[str, Any]:
        specs = list(self._supported().values())
        preferred = make_video_spec(self._supported())
        return {
            "workflows": [_public_workflow(spec) for spec in specs],
            "default": list(preferred.registry_key) if preferred else None,
        }

    def preview(
        self, catalog: SiteOutputCatalog, body: dict[str, Any], *, evaluation: bool
    ) -> PhonePreviewInput:
        expected = {
            "kind",
            "scope",
            "sources",
            "arms",
            "prompt",
            "negative_prompt",
            "seed",
            "frames",
        }
        if set(body) != expected or body.get("scope") != catalog.scope:
            raise SiteOutputError("invalid_video_preview")
        sources, arms = body["sources"], body["arms"]
        prompt, negative_prompt, seed, frames = (
            body["prompt"],
            body["negative_prompt"],
            body["seed"],
            body["frames"],
        )
        if not (
            isinstance(sources, list)
            and 1 <= len(sources) <= _MAX_SOURCES
            and isinstance(arms, list)
            and (2 <= len(arms) <= _MAX_ARMS if evaluation else len(arms) == 1)
            and len(sources) * len(arms) <= MAX_EVAL_JOBS
            and isinstance(prompt, str)
            and 1 <= len(prompt.strip()) <= 2000
            and isinstance(negative_prompt, str)
            and len(negative_prompt) <= 1000
            and type(seed) is int
            and 0 <= seed < 2**31
            and type(frames) is int
        ):
            raise SiteOutputError("invalid_video_preview")
        supported = self._supported()
        selected = self._select_arms(arms, supported, frames)
        if evaluation and not negative_prompt.strip():
            baseline = supported[(arms[0]["workflow_id"], arms[0]["workflow_version"])]
            defaults = {
                default_negative_prompt(supported[(arm["workflow_id"], arm["workflow_version"])])
                for arm in arms
            }
            if len(defaults) != 1:
                raise SiteOutputError("controlled_negative_prompt_required")
            negative_prompt = default_negative_prompt(baseline)
        cases, sizes = self._select_sources(
            catalog, sources, prompt.strip(), negative_prompt.strip()
        )
        return self._build(catalog, cases, sizes, selected, supported, seed, evaluation=evaluation)

    def followup_workflow(self, workflow: tuple[str, str]) -> WorkflowSpec:
        spec = self._supported().get(workflow)
        if spec is None or spec.governance_state != "approved":
            raise SiteOutputError("followup_workflow_unavailable")
        return spec

    def followup(
        self,
        catalog: SiteOutputCatalog,
        case: EvalCase,
        size: tuple[int, int],
        spec: WorkflowSpec,
        seed: int,
        frames: tuple[int, int],
    ) -> PhonePreviewInput:
        if frames[0] == frames[1] or any(value not in legal_frame_counts(spec) for value in frames):
            raise SiteOutputError("invalid_followup_value")
        arms = [
            EvalArm(
                f"arm-{index}",
                f"{spec.display_name} · {count} frames",
                ARM_BACKEND_WORKFLOW,
                {
                    "workflow_id": spec.workflow_id,
                    "workflow_version": spec.workflow_version,
                    "experimental_opt_in": False,
                    "frame_count": count,
                },
            )
            for index, count in enumerate(frames, 1)
        ]
        draft = self._build(
            catalog,
            [case],
            {case.case_id: size},
            arms,
            {spec.registry_key: spec},
            seed,
            evaluation=True,
        )
        return replace(
            draft,
            label="Video frame count follow-up",
            job_details=tuple(
                {key: value for key, value in details.items() if key != "negative_prompt"}
                for details in draft.job_details
            ),
        )

    def _build(
        self,
        catalog: SiteOutputCatalog,
        cases: list[EvalCase],
        sizes: dict[str, tuple[int, int]],
        selected: list[EvalArm],
        supported: dict[tuple[str, str], WorkflowSpec],
        seed: int,
        *,
        evaluation: bool,
    ) -> PhonePreviewInput:
        root = catalog.library.root
        builder = VideoWorkflowNjrBuilder(
            workflow_registry=self._registry, output_dir_provider=lambda: str(root)
        )
        frozen_inputs: list[FrozenVideoInputs] = []
        details: list[dict[str, Any]] = []

        def build(case: EvalCase, arm: EvalArm, fixed_seed: int) -> BuiltEvalJob:
            spec = supported[(arm.overrides["workflow_id"], arm.overrides["workflow_version"])]
            form = dict(
                arm.overrides,
                prompt=case.prompt,
                negative_prompt=case.negative_prompt,
                seed=fixed_seed,
            )
            # The native preparer applies EXIF before choosing a target. Guard
            # both axis orders against links before handing it the source.
            width, height = sizes[case.case_id]
            for dimensions in ((width, height), (height, width)):
                _orientation, target, _rule = resolve_declared_target(
                    spec.backend_defaults["source_preparation"], *dimensions
                )
                _unlinked_destination(
                    root, prepared_source_destination(root, case.image_sha256, target)
                )
            catalog.require_active()
            frozen = builder.freeze_inputs(case.image_path, form)
            if frozen.source_sha256 != case.image_sha256:
                raise SiteOutputError("media_changed")
            inside(root, Path(frozen.prepared_source_path))
            built = builder.build_job(
                form, frozen, lineage={"source_artifact_id": f"sha256:{case.image_sha256}"}
            )
            frozen_inputs.append(frozen)
            details.append(
                {
                    **_public_workflow(spec),
                    "case": case.case_id,
                    "source": case.image_path.name,
                    "arm": arm.arm_id,
                    **built.source_preparation["target_dimensions"],
                    "frames": built.frame_count,
                    "seed": built.seed,
                    "negative_prompt": builder.resolved_negative_prompt(spec, form),
                }
            )
            return BuiltEvalJob(built.njr, built.seed, built.frame_count)

        def require_current() -> None:
            for frozen in frozen_inputs:
                inside(root, Path(frozen.source_image_path))
                inside(root, Path(frozen.prepared_source_path))
                builder.verify_unchanged(frozen)
            if evaluation:
                _unlinked_destination(root, root / EVAL_OUTPUT_FOLDER / plan.run_id / "run.json")
            catalog.require_active()

        if not evaluation:
            try:
                jobs = tuple(build(case, selected[0], seed).njr for case in cases)
            except (OSError, ValueError, RuntimeError) as exc:
                raise SiteOutputError("video_preview_failed") from exc
            return PhonePreviewInput("Video Workflow", jobs, require_current, tuple(details))

        # The suite is inline in the run manifest. The phone never provides a suite filename.
        definition = {
            "cases": [
                {
                    "id": case.case_id,
                    "sha256": case.image_sha256,
                    "prompt": case.prompt,
                    "negative_prompt": case.negative_prompt,
                }
                for case in cases
            ],
            "arms": [dict(arm.overrides) for arm in selected],
            "seed": seed,
        }
        suite = EvalSuite(
            "phone-eval",
            None,
            hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest(),
            "Operator Site evaluation",
            tuple(cases),
            tuple(selected),
            seed,
            selected[0].arm_id,
        )
        service = VideoEvalRunService(builders={ARM_BACKEND_WORKFLOW: build})
        plan = service.plan(suite)
        if not plan.eligible:
            raise SiteOutputError("video_preview_failed")

        def admit(records: tuple[NormalizedJobRecord, ...]) -> None:
            identified = replace(
                plan,
                jobs=tuple(
                    EvalJobPlan(
                        case_id=job.case_id,
                        arm_id=job.arm_id,
                        backend=job.backend,
                        job_id=record.job_id,
                        seed=job.seed,
                        frame_count=job.frame_count,
                        njr=record,
                    )
                    for job, record in zip(plan.jobs, records, strict=True)
                ),
            )
            service.admit(
                identified, self._jobs, output_root=root, require_active=catalog.require_active
            )

        return PhonePreviewInput(
            "Controlled video evaluation",
            tuple(job.njr for job in plan.jobs),
            require_current,
            tuple(details),
            admit,
            plan.run_id,
        )

    @staticmethod
    def _select_arms(
        arms: list[Any], supported: dict[tuple[str, str], WorkflowSpec], frames: int
    ) -> list[EvalArm]:
        selected: list[EvalArm] = []
        identities: set[tuple[str, str]] = set()
        for number, arm in enumerate(arms, 1):
            if not (
                isinstance(arm, dict)
                and set(arm) == {"workflow_id", "workflow_version", "experimental_opt_in"}
                and isinstance(arm["workflow_id"], str)
                and isinstance(arm["workflow_version"], str)
                and type(arm["experimental_opt_in"]) is bool
            ):
                raise SiteOutputError("invalid_video_preview")
            key = arm["workflow_id"], arm["workflow_version"]
            spec = supported.get(key)
            if spec is None or key in identities:
                raise SiteOutputError("incompatible_video_workflow")
            if spec.is_experimental != arm["experimental_opt_in"]:
                raise SiteOutputError("experimental_opt_in_required")
            try:
                parse_frame_count(spec, frames)
            except ValueError as exc:
                raise SiteOutputError("invalid_video_frame_count") from exc
            identities.add(key)
            selected.append(
                EvalArm(
                    f"arm-{number}",
                    f"{spec.display_name} {spec.workflow_version}",
                    ARM_BACKEND_WORKFLOW,
                    # N1: a phone Queue records its accepted warnings as accepted on the phone.
                    {**arm, "frame_count": frames, WARNING_SURFACE_FIELD: SURFACE_PHONE},
                )
            )
        return selected

    @staticmethod
    def _select_sources(
        catalog: SiteOutputCatalog, sources: list[Any], prompt: str, negative_prompt: str
    ) -> tuple[list[EvalCase], dict[str, tuple[int, int]]]:
        cases: list[EvalCase] = []
        sizes: dict[str, tuple[int, int]] = {}
        digests: set[str] = set()
        for number, source in enumerate(sources, 1):
            if not (
                isinstance(source, dict)
                and set(source) == {"id", "digest"}
                and isinstance(source["digest"], str)
                and _DIGEST.fullmatch(source["digest"])
                and source["digest"] not in digests
            ):
                raise SiteOutputError("invalid_video_preview")
            catalog.require_active()
            item, _raw, digest = catalog.library.image(source["id"])
            if digest != source["digest"]:
                raise SiteOutputError("media_changed")
            case_id = f"case-{number}"
            cases.append(
                EvalCase(case_id, catalog.library.path_for(item), digest, prompt, negative_prompt)
            )
            sizes[case_id] = (item.width, item.height)
            digests.add(digest)
        return cases, sizes
