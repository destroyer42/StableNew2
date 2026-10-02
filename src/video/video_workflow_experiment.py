"""One-variable operator experiments for Video Workflow (PR-VID-194).

"Keep this exact setup fixed; compare ONE declared control at these values."  The service

1. freezes one baseline once (concrete seed, source and driving-video hashes, prepared source);
2. builds every arm's immutable NJR through the SAME ``VideoWorkflowNjrBuilder`` a normal
   submission uses, stamping the existing ``LearningJobContext`` into each NJR's provenance;
3. proves, fail-closed, that the arms differ ONLY in the selected control; and
4. hands all NJRs to ``ExperimentAdmissionService`` which crosses ``JobService.submit_njrs``
   exactly once.

It owns no durable state: the plan is a transient value, and queue/history remain the only
lifecycle and result authority.  The control list, validation and fallback semantics all come from
the selected workflow spec through ``src.video.workflow_controls``; nothing here branches on a
workflow, backend or model.  There is no search, scoring or winner selection by design.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.learning.experiment_execution import (
    ExperimentAdmissionService,
    freeze_snapshot,
    snapshot_digest,
    thaw_snapshot,
)
from src.pipeline.job_models_v2 import (
    LearningJobContext,
    NormalizedJobRecord,
    SourceKind,
    WorkloadKind,
)
from src.pipeline.njr_core_v26 import thaw_json
from src.video.video_execution_resolver import VIDEO_EXECUTION_KEY
from src.video.video_workflow_intent import EXPERIMENTAL_OPT_IN_FIELD
from src.video.video_workflow_njr_builder import FrozenVideoInputs, VideoWorkflowNjrBuilder
from src.video.workflow_controls import (
    OPERATOR_CONTROLS_KEY,
    operator_controls,
    resolve_operator_controls,
)

MAX_CANDIDATES = 3
ARM_LABELS = ("A", "B", "C", "D")
_MASK = "<variable under test>"


class ExperimentRefused(ValueError):
    """The experiment cannot be built or admitted; no job was submitted."""


@dataclass(frozen=True)
class ExperimentArm:
    label: str
    index: int
    value: Any  # the resolved effective value of the variable under test
    njr: NormalizedJobRecord


@dataclass(frozen=True)
class ExperimentPlan:
    """A previewed, fully built, proven one-variable experiment (nothing is queued yet)."""

    experiment_id: str
    experiment_name: str
    variable_name: str
    variable_label: str
    arms: tuple[ExperimentArm, ...]
    common_seed: int | None
    requires_opt_in: bool
    frozen: FrozenVideoInputs
    snapshot_json: str
    snapshot_digest: str

    @property
    def statement(self) -> str:
        return f"Only {self.variable_label} changes across these jobs."

    def fixed_inputs(self) -> list[tuple[str, str]]:
        """What stays identical, read back from the frozen snapshot (not from the live form)."""

        snap = thaw_snapshot(self.snapshot_json)
        rows = [
            ("Workflow", str(snap["workflow"])),
            ("Source", f"{snap['source']['path']} (sha256 {snap['source']['sha256'][:12]})"),
        ]
        driving = snap.get("driving_video")
        if driving:
            rows.append(("Driving video", f"{driving['path']} (sha256 {driving['sha256'][:12]})"))
        rows.append(("Seed", "n/a" if snap["seed"] is None else str(snap["seed"])))
        if snap.get("frame_count") is not None:
            rows.append(("Frames", str(snap["frame_count"])))
        rows.append(("Prompt", str(snap["prompt"])))
        rows.append(("Negative", str(snap["negative_prompt"])))
        for name, value in snap["fixed_controls"].items():
            rows.append((name, str(value)))
        rows.append(("Output route", str(snap["output_route"])))
        return rows


@dataclass(frozen=True)
class ExperimentAdmissionResult:
    experiment_id: str
    variable_name: str
    arms: tuple[tuple[str, Any, str], ...]  # (label, value, job_id)

    @property
    def job_ids(self) -> list[str]:
        return [job_id for _label, _value, job_id in self.arms]


def _mask_variable(node: Any, name: str, hits: list[Any]) -> Any:
    """Copy ``node`` with every ``operator_controls[name]`` replaced by a placeholder."""

    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == OPERATOR_CONTROLS_KEY and isinstance(value, dict) and name in value:
                hits.append(value[name])
                value = {**value, name: _MASK}
            out[key] = _mask_variable(value, name, hits)
        return out
    if isinstance(node, list):
        return [_mask_variable(item, name, hits) for item in node]
    return node


def _first_difference(left: Any, right: Any, path: str = "") -> str | None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{path}/{key}" if path else str(key)
            found = _first_difference(left[key], right[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return path or "/"
        for position, (a, b) in enumerate(zip(left, right, strict=True)):
            found = _first_difference(a, b, f"{path}[{position}]")
            if found:
                return found
        return None
    return None if left == right and type(left) is type(right) else (path or "/")


def assert_one_variable(
    arms: Sequence[ExperimentArm],
    *,
    variable_name: str,
    variable_label: str,
    experiment_id: str,
    experiment_name: str,
) -> None:
    """Fail closed unless the arms differ only in identity, bookkeeping and the selected control."""

    if len(arms) < 2:
        raise ExperimentRefused("An experiment needs a baseline and at least one candidate.")
    normalized: list[dict[str, Any]] = []
    for arm in arms:
        njr = arm.njr
        if njr.source.kind is not SourceKind.VIDEO_WORKFLOW or njr.workload_kind is not (
            WorkloadKind.VIDEO
        ):
            raise ExperimentRefused(f"Arm {arm.label} is not a Video Workflow video job.")
        context = njr.learning_context
        expected = (experiment_id, experiment_name, arm.index, variable_name)
        if (
            context is None
            or (
                context.experiment_id,
                context.experiment_name,
                context.variant_index,
                context.variable_under_test,
            )
            != expected
            or thaw_json(context.variant_value) != arm.value
        ):
            raise ExperimentRefused(f"Arm {arm.label} does not carry this experiment's identity.")
        payload = njr.to_dict()
        payload.pop("job_id", None)
        payload["provenance"].pop("learning_context", None)
        hits: list[Any] = []
        payload = _mask_variable(payload, variable_name, hits)
        if not hits or any(hit != arm.value for hit in hits):
            raise ExperimentRefused(
                f"Arm {arm.label} does not record {variable_label} = {arm.value!r} consistently."
            )
        normalized.append(payload)
    if len({arm.njr.job_id for arm in arms}) != len(arms):
        raise ExperimentRefused("Experiment arms must have distinct job identities.")
    baseline = json.dumps(normalized[0], sort_keys=True)
    for arm, payload in zip(arms[1:], normalized[1:], strict=True):
        if json.dumps(payload, sort_keys=True) != baseline:
            where = _first_difference(normalized[0], payload)
            raise ExperimentRefused(
                f"Arm {arm.label} differs from arm A outside {variable_label} "
                f"(at {where}); the whole experiment is refused and nothing was queued."
            )


def _snapshot_payload(
    arms: Sequence[ExperimentArm], variable_name: str, frozen: FrozenVideoInputs
) -> dict[str, Any]:
    njr = arms[0].njr
    block = thaw_json(njr.config)["video_workflow"]
    controls = dict(block.get(OPERATOR_CONTROLS_KEY) or {})
    controls.pop(variable_name, None)
    return {
        "workflow": f"{block['workflow_id']}@{block['workflow_version']}",
        "backend_id": block["backend_id"],
        "source": {
            "path": frozen.source_image_path,
            "sha256": frozen.source_sha256,
            "prepared_path": frozen.prepared_source_path,
            "prepared_sha256": frozen.prepared_source_sha256,
        },
        "driving_video": dict(frozen.driving_video) if frozen.driving_video else None,
        "seed": frozen.seed,
        "frame_count": block.get("frame_count"),
        "prompt": block.get("prompt", ""),
        "negative_prompt": block.get("negative_prompt", ""),
        "output_route": thaw_json(njr.config)["pipeline"]["output_route"],
        "experimental_opt_in": block[VIDEO_EXECUTION_KEY].get(EXPERIMENTAL_OPT_IN_FIELD, False),
        "variable": variable_name,
        "values": [arm.value for arm in arms],
        "fixed_controls": controls,
    }


class VideoWorkflowExperimentService:
    """Preview and admit a one-variable comparison without owning any lifecycle state."""

    def __init__(
        self,
        builder: VideoWorkflowNjrBuilder,
        *,
        admission: ExperimentAdmissionService | None = None,
    ) -> None:
        self._builder = builder
        self._admission = admission or ExperimentAdmissionService()

    # ------------------------------------------------------------------ baseline

    def resolve_variable(
        self, form_data: Mapping[str, Any], variable_name: str, raw_value: Any = None
    ) -> Any:
        """Resolved effective value of one declared control (``raw_value=None``: the form's own)."""

        spec = self._builder.spec_for(form_data)
        if variable_name not in {c["name"] for c in operator_controls(spec)}:
            raise ExperimentRefused(
                f"'{getattr(spec, 'display_name', spec.workflow_id)}' does not declare a "
                f"control named '{variable_name}'."
            )
        candidate = dict(form_data)
        if raw_value is not None:
            candidate[OPERATOR_CONTROLS_KEY] = {
                **dict(form_data.get(OPERATOR_CONTROLS_KEY) or {}),
                variable_name: raw_value,
            }
        resolved = resolve_operator_controls(spec, candidate) or {}
        return resolved[variable_name]

    # ------------------------------------------------------------------ preview

    def preview(
        self,
        source_image_path: str,
        form_data: Mapping[str, Any],
        variable_name: str,
        candidates: Sequence[Any],
        *,
        experiment_name: str | None = None,
    ) -> ExperimentPlan:
        if not 1 <= len(candidates) <= MAX_CANDIDATES:
            raise ExperimentRefused(
                f"Provide 1 to {MAX_CANDIDATES} candidate values "
                f"(2 to {MAX_CANDIDATES + 1} jobs including the baseline)."
            )
        spec = self._builder.spec_for(form_data)
        control = next((c for c in operator_controls(spec) if c["name"] == variable_name), None)
        if control is None:
            raise ExperimentRefused(
                f"'{getattr(spec, 'display_name', spec.workflow_id)}' does not declare a "
                f"control named '{variable_name}'."
            )
        label = control["label"]
        try:
            baseline = self.resolve_variable(form_data, variable_name)
        except ValueError as exc:
            raise ExperimentRefused(f"Baseline {label}: {exc}") from exc

        arm_forms: list[tuple[Any, dict[str, Any]]] = [(baseline, dict(form_data))]
        for position, raw in enumerate(candidates, start=1):
            try:
                value = self.resolve_variable(form_data, variable_name, str(raw))
            except ValueError as exc:
                raise ExperimentRefused(f"Candidate {position} ({label}): {exc}") from exc
            for earlier_value, _form in arm_forms:
                if value == earlier_value:
                    other = "the baseline" if earlier_value == baseline else "another candidate"
                    raise ExperimentRefused(
                        f"Candidate {position} resolves to {value!r}, the same as {other}; "
                        "every arm must be a distinct value."
                    )
            variant_form = dict(form_data)
            variant_form[OPERATOR_CONTROLS_KEY] = {
                **dict(form_data.get(OPERATOR_CONTROLS_KEY) or {}),
                variable_name: str(raw),
            }
            arm_forms.append((value, variant_form))

        try:
            frozen = self._builder.freeze_inputs(source_image_path, form_data)
        except ValueError as exc:
            raise ExperimentRefused(str(exc)) from exc
        experiment_id = uuid.uuid4().hex
        name = experiment_name or f"Video experiment: {label}"
        arms: list[ExperimentArm] = []
        for index, (value, variant_form) in enumerate(arm_forms):
            try:
                built = self._builder.build_job(
                    variant_form,
                    frozen,
                    learning_context=LearningJobContext(
                        experiment_id=experiment_id,
                        experiment_name=name,
                        variant_index=index,
                        variable_under_test=variable_name,
                        variant_value=value,
                    ),
                )
            except ValueError as exc:
                raise ExperimentRefused(f"Arm {ARM_LABELS[index]}: {exc}") from exc
            arms.append(
                ExperimentArm(label=ARM_LABELS[index], index=index, value=value, njr=built.njr)
            )
        assert_one_variable(
            arms,
            variable_name=variable_name,
            variable_label=label,
            experiment_id=experiment_id,
            experiment_name=name,
        )
        snapshot = freeze_snapshot(_snapshot_payload(arms, variable_name, frozen))
        return ExperimentPlan(
            experiment_id=experiment_id,
            experiment_name=name,
            variable_name=variable_name,
            variable_label=label,
            arms=tuple(arms),
            common_seed=frozen.seed,
            requires_opt_in=bool(getattr(spec, "is_experimental", False)),
            frozen=frozen,
            snapshot_json=snapshot,
            snapshot_digest=snapshot_digest(snapshot),
        )

    # ------------------------------------------------------------------ admission

    def admit(self, plan: ExperimentPlan, job_service: Any) -> ExperimentAdmissionResult:
        """Re-verify the frozen inputs, then cross ``JobService.submit_njrs`` exactly once."""

        if snapshot_digest(plan.snapshot_json) != plan.snapshot_digest:
            raise ExperimentRefused("The experiment snapshot no longer matches its digest.")
        try:
            self._builder.verify_unchanged(plan.frozen)
        except ValueError as exc:
            raise ExperimentRefused(f"{exc}. Build the preview again; nothing was queued.") from exc
        assert_one_variable(
            plan.arms,
            variable_name=plan.variable_name,
            variable_label=plan.variable_label,
            experiment_id=plan.experiment_id,
            experiment_name=plan.experiment_name,
        )
        if plan.requires_opt_in and not all(
            arm.njr.config["video_workflow"][VIDEO_EXECUTION_KEY].get(EXPERIMENTAL_OPT_IN_FIELD)
            is True
            for arm in plan.arms
        ):
            raise ExperimentRefused("This experimental workflow needs its explicit per-job opt-in.")
        admission = self._admission.compile_all(list(plan.arms), lambda arm: arm.njr)
        job_ids = self._admission.submit(admission, job_service)
        if len(job_ids) != len(plan.arms):
            raise RuntimeError("Experiment admission did not return one job id per arm")
        return ExperimentAdmissionResult(
            experiment_id=plan.experiment_id,
            variable_name=plan.variable_name,
            arms=tuple(
                (arm.label, arm.value, job_id)
                for arm, job_id in zip(plan.arms, job_ids, strict=True)
            ),
        )


__all__ = [
    "ARM_LABELS",
    "MAX_CANDIDATES",
    "ExperimentAdmissionResult",
    "ExperimentArm",
    "ExperimentPlan",
    "ExperimentRefused",
    "VideoWorkflowExperimentService",
    "assert_one_variable",
]
