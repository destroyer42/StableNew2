"""Test-only synthetic workflow fixtures for generic video-backend contract behavior.

The production catalog contains only real, evidence-backed workflows (Wan2.2 TI2V-5B and
Wan-Animate-2).  Generic compiler, dependency-probe and Comfy-backend tests still need a
multi-anchor workflow with optional intermediate anchors and depth/camera conditioning inputs, so
this module builds two EXPLICITLY SYNTHETIC specs.  They name no real model, claim no runtime
evidence, and are registered only in the private registries built here; they never reach the
production registry or any operator-facing surface.

``synthetic_disabled_video_v1`` has the same shape as a retired or not-yet-implemented
workflow and exists to exercise the disabled-workflow rule: offerable lists exclude it and
execution lookup rejects it.
"""

from __future__ import annotations

from src.video.workflow_contracts import (
    WORKFLOW_CAP_CAMERA_INTENT,
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
    WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
    WORKFLOW_CAP_SEGMENT_STITCHABLE,
    WORKFLOW_GOVERNANCE_DISABLED,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)
from src.video.workflow_registry import WorkflowRegistry

SYNTHETIC_ANCHOR_ID = "synthetic_anchor_video_v1"
SYNTHETIC_CONDITIONED_ID = "synthetic_anchor_video_v1_conditioned"
SYNTHETIC_DISABLED_ID = "synthetic_disabled_video_v1"


def _build_synthetic_anchor_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="synthetic_anchor_video_v1",
        workflow_version="1.0.0",
        backend_id="comfy",
        display_name="Synthetic Anchor Video v1",
        description="Synthetic test-only multi-anchor image-to-video contract (not a real model).",
        capability_tags=(
            WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
            WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
            WORKFLOW_CAP_SEGMENT_STITCHABLE,
        ),
        input_bindings=(
            WorkflowInputBinding(
                binding_name="start_anchor",
                source_field="input_image_path",
                backend_key="start_anchor",
                description="Primary starting frame for the workflow.",
            ),
            WorkflowInputBinding(
                binding_name="end_anchor",
                source_field="end_anchor_path",
                backend_key="end_anchor",
                description="Required ending frame anchor.",
            ),
            WorkflowInputBinding(
                binding_name="mid_anchors",
                source_field="mid_anchor_paths",
                backend_key="mid_anchors",
                required=False,
                description="Optional intermediate anchor frames.",
            ),
            WorkflowInputBinding(
                binding_name="prompt",
                source_field="prompt",
                backend_key="prompt",
                required=False,
                description="Optional positive prompt guidance.",
            ),
            WorkflowInputBinding(
                binding_name="negative_prompt",
                source_field="negative_prompt",
                backend_key="negative_prompt",
                required=False,
                description="Optional negative prompt guidance.",
            ),
            WorkflowInputBinding(
                binding_name="motion_profile",
                source_field="motion_profile",
                backend_key="motion_profile",
                required=False,
                description="StableNew motion profile selector.",
            ),
        ),
        output_bindings=(
            WorkflowOutputBinding(
                binding_name="output_dir",
                source_field="output_dir",
                backend_key="output_dir",
                required=True,
                artifact_type="directory",
                description="Final output directory owned by StableNew.",
            ),
            WorkflowOutputBinding(
                binding_name="output_name",
                source_field="image_name",
                backend_key="output_name",
                required=False,
                artifact_type="video",
                description="Preferred output basename when one is provided.",
            ),
        ),
        dependency_specs=(
            WorkflowDependencySpec(
                dependency_id="synthetic_model",
                dependency_kind="checkpoint",
                locator="synthetic_video",
                description="Synthetic checkpoint locator expected by the fixture.",
            ),
            WorkflowDependencySpec(
                dependency_id="synthetic_nodes",
                dependency_kind="custom_node",
                locator="SyntheticAnchorBridge",
                description="Synthetic bridge node required by the fixture.",
            ),
        ),
        governance_state="approved",
        pinned_revision="synthetic:synthetic_anchor_video_v1@1.0.0",
        governance_notes="Synthetic test fixture; never part of a production catalog.",
        backend_defaults={
            "workflow_family": "synthetic",
            "transport": "managed_local_comfy",
            "prompt_template": {
                "1": {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": "{{input.start_anchor}}",
                    },
                },
                "2": {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": "{{input.end_anchor}}",
                    },
                },
                "3": {
                    "class_type": "SyntheticAnchorBridge",
                    "inputs": {
                        "start_anchor": ["1", 0],
                        "end_anchor": ["2", 0],
                        "mid_anchors": "{{input.mid_anchors}}",
                        "prompt": "{{input.prompt}}",
                        "negative_prompt": "{{input.negative_prompt}}",
                        "motion_profile": "{{input.motion_profile}}",
                    },
                },
                "4": {
                    "class_type": "StableNewSaveVideo",
                    "inputs": {
                        "images": ["3", 0],
                        "output_dir": "{{output.output_dir}}",
                        "filename_prefix": "{{output.output_name}}",
                    },
                },
            },
        },
    )


def _build_synthetic_conditioned_anchor_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="synthetic_anchor_video_v1_conditioned",
        workflow_version="1.0.0",
        backend_id="comfy",
        display_name="Synthetic Conditioned Anchor Video v1",
        description="Synthetic test-only multi-anchor contract with depth and camera conditioning inputs (not a real model).",
        capability_tags=(
            WORKFLOW_CAP_CAMERA_INTENT,
            WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
            WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
            WORKFLOW_CAP_SEGMENT_STITCHABLE,
        ),
        input_bindings=(
            WorkflowInputBinding(
                binding_name="start_anchor",
                source_field="input_image_path",
                backend_key="start_anchor",
                description="Primary starting frame for the workflow.",
            ),
            WorkflowInputBinding(
                binding_name="end_anchor",
                source_field="end_anchor_path",
                backend_key="end_anchor",
                description="Required ending frame anchor.",
            ),
            WorkflowInputBinding(
                binding_name="depth_map",
                source_field="stage_config.depth_input.resolved_path",
                backend_key="depth_map",
                description="Resolved depth conditioning image generated locally or supplied by the operator.",
            ),
            WorkflowInputBinding(
                binding_name="mid_anchors",
                source_field="mid_anchor_paths",
                backend_key="mid_anchors",
                required=False,
                description="Optional intermediate anchor frames.",
            ),
            WorkflowInputBinding(
                binding_name="prompt",
                source_field="prompt",
                backend_key="prompt",
                required=False,
                description="Optional positive prompt guidance.",
            ),
            WorkflowInputBinding(
                binding_name="negative_prompt",
                source_field="negative_prompt",
                backend_key="negative_prompt",
                required=False,
                description="Optional negative prompt guidance.",
            ),
            WorkflowInputBinding(
                binding_name="motion_profile",
                source_field="motion_profile",
                backend_key="motion_profile",
                required=False,
                description="StableNew motion profile selector.",
            ),
            WorkflowInputBinding(
                binding_name="camera_preset",
                source_field="stage_config.camera_intent.preset",
                backend_key="camera_preset",
                required=False,
                description="Structured camera intent preset.",
            ),
            WorkflowInputBinding(
                binding_name="camera_strength",
                source_field="stage_config.camera_intent.strength",
                backend_key="camera_strength",
                required=False,
                description="Strength scalar for camera intent propagation.",
            ),
            WorkflowInputBinding(
                binding_name="controlnet_model",
                source_field="stage_config.controlnet.model",
                backend_key="controlnet_model",
                required=False,
                description="StableNew ControlNet model selector for depth conditioning.",
            ),
            WorkflowInputBinding(
                binding_name="controlnet_weight",
                source_field="stage_config.controlnet.weight",
                backend_key="controlnet_weight",
                required=False,
                description="ControlNet conditioning weight.",
            ),
            WorkflowInputBinding(
                binding_name="guidance_start",
                source_field="stage_config.controlnet.guidance_start",
                backend_key="guidance_start",
                required=False,
                description="ControlNet guidance start ratio.",
            ),
            WorkflowInputBinding(
                binding_name="guidance_end",
                source_field="stage_config.controlnet.guidance_end",
                backend_key="guidance_end",
                required=False,
                description="ControlNet guidance end ratio.",
            ),
        ),
        output_bindings=(
            WorkflowOutputBinding(
                binding_name="output_dir",
                source_field="output_dir",
                backend_key="output_dir",
                required=True,
                artifact_type="directory",
                description="Final output directory owned by StableNew.",
            ),
            WorkflowOutputBinding(
                binding_name="output_name",
                source_field="image_name",
                backend_key="output_name",
                required=False,
                artifact_type="video",
                description="Preferred output basename when one is provided.",
            ),
        ),
        dependency_specs=(
            WorkflowDependencySpec(
                dependency_id="synthetic_model",
                dependency_kind="checkpoint",
                locator="synthetic_video",
                description="Synthetic checkpoint locator expected by the fixture.",
            ),
            WorkflowDependencySpec(
                dependency_id="synthetic_conditioned_nodes",
                dependency_kind="custom_node",
                locator="SyntheticConditionedBridge",
                description="Synthetic conditioned bridge node required by the fixture.",
            ),
            WorkflowDependencySpec(
                dependency_id="depth_control_model",
                dependency_kind="checkpoint",
                locator="depth",
                description="A depth-capable ControlNet checkpoint visible to ComfyUI.",
            ),
        ),
        governance_state="approved",
        pinned_revision="synthetic:synthetic_anchor_video_v1_conditioned@1.0.0",
        governance_notes="Synthetic test fixture; never part of a production catalog.",
        backend_defaults={
            "workflow_family": "synthetic",
            "transport": "managed_local_comfy",
            "prompt_template": {
                "1": {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": "{{input.start_anchor}}",
                    },
                },
                "2": {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": "{{input.end_anchor}}",
                    },
                },
                "3": {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": "{{input.depth_map}}",
                    },
                },
                "4": {
                    "class_type": "SyntheticConditionedBridge",
                    "inputs": {
                        "start_anchor": ["1", 0],
                        "end_anchor": ["2", 0],
                        "depth_map": ["3", 0],
                        "mid_anchors": "{{input.mid_anchors}}",
                        "prompt": "{{input.prompt}}",
                        "negative_prompt": "{{input.negative_prompt}}",
                        "motion_profile": "{{input.motion_profile}}",
                        "camera_preset": "{{input.camera_preset}}",
                        "camera_strength": "{{input.camera_strength}}",
                        "controlnet_model": "{{input.controlnet_model}}",
                        "controlnet_weight": "{{input.controlnet_weight}}",
                        "guidance_start": "{{input.guidance_start}}",
                        "guidance_end": "{{input.guidance_end}}",
                    },
                },
                "5": {
                    "class_type": "StableNewSaveVideo",
                    "inputs": {
                        "images": ["4", 0],
                        "output_dir": "{{output.output_dir}}",
                        "filename_prefix": "{{output.output_name}}",
                    },
                },
            },
        },
    )


def _build_synthetic_disabled_spec() -> WorkflowSpec:
    """A disabled spec: registered for contract metadata, never offerable or runnable."""

    return WorkflowSpec(
        workflow_id=SYNTHETIC_DISABLED_ID,
        workflow_version="1.0.0",
        backend_id="comfy",
        display_name="Synthetic Disabled Video v1",
        description="Synthetic test-only disabled workflow (not a real model).",
        capability_tags=(WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,),
        input_bindings=(WorkflowInputBinding("source", "input_image_path"),),
        output_bindings=(WorkflowOutputBinding("output_dir", "output_dir", required=True),),
        dependency_specs=(
            WorkflowDependencySpec("synthetic_nodes", "custom_node", "SyntheticAnchorBridge"),
        ),
        governance_state=WORKFLOW_GOVERNANCE_DISABLED,
        pinned_revision="synthetic:synthetic_disabled_video_v1@1.0.0",
        governance_notes="DISABLED: synthetic fixture for the disabled-workflow rule.",
    )


def build_synthetic_contract_registry() -> WorkflowRegistry:
    """Private registry: the two approved synthetic anchor specs plus the production specs."""

    from src.video.workflow_catalog import build_builtin_workflow_specs

    registry = WorkflowRegistry()
    for spec in build_builtin_workflow_specs():
        registry.register(spec)
    registry.register(_build_synthetic_anchor_spec())
    registry.register(_build_synthetic_conditioned_anchor_spec())
    return registry


def build_synthetic_disabled_registry() -> WorkflowRegistry:
    """Private registry holding the approved synthetic specs and one disabled synthetic spec."""

    registry = build_synthetic_contract_registry()
    registry.register(_build_synthetic_disabled_spec())
    return registry
