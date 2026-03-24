from __future__ import annotations

from src.video.workflow_contracts import (
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
    WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
    WORKFLOW_CAP_SEGMENT_STITCHABLE,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)


def build_builtin_workflow_specs() -> tuple[WorkflowSpec, ...]:
    return (_build_ltx_multiframe_anchor_v1(),)


def _build_ltx_multiframe_anchor_v1() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="ltx_multiframe_anchor_v1",
        workflow_version="1.0.0",
        backend_id="comfy",
        display_name="LTX Multi-Frame Anchor v1",
        description=(
            "Pinned StableNew metadata contract for a managed Comfy/LTX multi-anchor "
            "image-to-video workflow."
        ),
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
                dependency_id="ltx_model",
                dependency_kind="checkpoint",
                locator="ltx_video",
                description="Pinned LTX model family expected by the workflow.",
            ),
            WorkflowDependencySpec(
                dependency_id="comfy_ltx_nodes",
                dependency_kind="custom_node",
                locator="StableNewLTXAnchorBridge",
                description="StableNew LTX bridge nodes required to execute the pinned workflow.",
            ),
        ),
        backend_defaults={
            "workflow_family": "ltx",
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
                    "class_type": "StableNewLTXAnchorBridge",
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


__all__ = ["build_builtin_workflow_specs"]
