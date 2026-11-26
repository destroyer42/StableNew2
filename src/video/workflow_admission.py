"""Workflow-specific admission constraints at the canonical JobService boundary."""

from types import SimpleNamespace
from typing import Any

from src.video.video_execution_resolver import effective_workflow_identity
from src.video.workflow_input_integrity import requires_exact_motion, verify_exact_dispatch_inputs
from src.video.workflow_registry import build_default_workflow_registry


def require_workflow_admission(record: Any) -> None:
    stage = record.config.get("video_workflow") or {}
    if not stage or "video_workflow" not in record.stage_chain_labels:
        return
    registry = build_default_workflow_registry()
    workflow_id, workflow_version = effective_workflow_identity(stage)
    try:
        spec = registry.get_offerable(workflow_id or "", workflow_version)
    except KeyError:
        # Other/extension workflows retain their existing admission contract.
        # An unknown version of an exact-input workflow must never bypass its policy.
        if any(
            requires_exact_motion(s) and s.workflow_id == workflow_id
            for s in registry.list_offerable_specs("comfy")
        ):
            raise ValueError("Unknown version of the frozen controlled-motion workflow") from None
        return
    intent = stage.get("video_execution") or {}
    if spec.is_experimental and intent.get("experimental_opt_in") is not True:
        # N1 (AGENTS.md section 2): the Queue summary warns and Queue records this job's opt-in; a job that
        # arrives without it is refused here, at Queue, never after it has waited in the queue.
        raise ValueError(
            f"'{spec.display_name}' is experimental and this job has no recorded experimental opt-in. Queue it from a summary "
            "that shows its warning to record the opt-in. Nothing was queued."
        )
    if not requires_exact_motion(spec):
        return
    if not workflow_version:
        raise ValueError("An explicit frozen workflow version is required for controlled motion")
    verify_exact_dispatch_inputs(
        spec,
        SimpleNamespace(
            stage_config=stage,
            input_image_path=record.input_image_paths[0] if record.input_image_paths else None,
        ),
    )
    policy = spec.backend_defaults.get("resource_readiness") or {}
    if policy.get("qualification_status") == "not_qualified":
        raise ValueError(str(policy["reason"]))
