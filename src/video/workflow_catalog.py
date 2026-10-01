from __future__ import annotations

from typing import Any

from src.video.workflow_contracts import (
    WORKFLOW_CAP_CAMERA_INTENT,
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
    WORKFLOW_CAP_MULTI_FRAME_ANCHOR_VIDEO,
    WORKFLOW_CAP_SEGMENT_STITCHABLE,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)


def build_builtin_workflow_specs() -> tuple[WorkflowSpec, ...]:
    return (
        _build_ltx_multiframe_anchor_v1(),
        _build_ltx_multiframe_anchor_v1_conditioned(),
        _build_wan22_ti2v_5b_i2v_v1(),
        _build_wan22_ti2v_5b_i2v_v1_1(),
    )


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
        governance_state="disabled",
        pinned_revision="catalog:ltx_multiframe_anchor_v1@1.0.0",
        governance_notes=(
            "DISABLED: required StableNewLTXAnchorBridge implementation and accepted runtime evidence are absent. "
            "Contract metadata is retained for future qualification; this workflow is not operator-offerable or runnable."
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


def _build_ltx_multiframe_anchor_v1_conditioned() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="ltx_multiframe_anchor_v1_conditioned",
        workflow_version="1.0.0",
        backend_id="comfy",
        display_name="LTX Multi-Frame Anchor v1 Conditioned",
        description=(
            "Pinned StableNew metadata contract for a managed Comfy/LTX multi-anchor "
            "workflow with depth-guided ControlNet conditioning and camera-intent propagation."
        ),
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
                dependency_id="ltx_model",
                dependency_kind="checkpoint",
                locator="ltx_video",
                description="Pinned LTX model family expected by the workflow.",
            ),
            WorkflowDependencySpec(
                dependency_id="comfy_ltx_depth_nodes",
                dependency_kind="custom_node",
                locator="StableNewLTXDepthControlBridge",
                description="StableNew conditioned LTX bridge nodes required to execute the pinned workflow.",
            ),
            WorkflowDependencySpec(
                dependency_id="depth_control_model",
                dependency_kind="checkpoint",
                locator="depth",
                description="A depth-capable ControlNet checkpoint visible to ComfyUI.",
            ),
        ),
        governance_state="disabled",
        pinned_revision="catalog:ltx_multiframe_anchor_v1_conditioned@1.0.0",
        governance_notes=(
            "DISABLED: required StableNewLTXDepthControlBridge implementation and accepted runtime evidence are absent. "
            "Contract metadata is retained for future qualification; this workflow is not operator-offerable or runnable."
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
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": "{{input.depth_map}}",
                    },
                },
                "4": {
                    "class_type": "StableNewLTXDepthControlBridge",
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


__all__ = ["build_builtin_workflow_specs"]


# --- Wan2.2 TI2V-5B prompt-directed image-to-video (PR-VID-130, EXPERIMENTAL) -----------------
# Promoted unchanged from the graph qualified in PR-VID-110 (tools/qualification/vid110/
# workflows.py::build_lane_a, operator-media geometry).  Stock ComfyUI 0.3.65 nodes only; the
# three model files are pinned by name, upstream revision and sha256.  Prompt-directed I2V only:
# no end/mid anchors, no control or pose video, and no identity-preservation claim.
WAN22_UPSTREAM_REPO = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"
WAN22_UPSTREAM_REVISION = "c4f60d30c55a624e35427060fdd217579a6c1d77"
WAN22_MODEL_FILES = (
    (
        "wan22_unet",
        "wan2.2_ti2v_5B_fp16.safetensors",
        "UNETLoader.unet_name",
        "456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e",
    ),
    (
        "wan22_text_encoder",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "CLIPLoader.clip_name",
        "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    ),
    (
        "wan22_vae",
        "wan2.2_vae.safetensors",
        "VAELoader.vae_name",
        "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
    ),
)
WAN22_STOCK_NODES = (
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "ModelSamplingSD3",
    "CLIPTextEncode",
    "LoadImage",
    "Wan22ImageToVideoLatent",
    "KSampler",
    "VAEDecode",
    "CreateVideo",
    "SaveVideo",
)
WAN22_DEFAULT_NEGATIVE = (
    "static, still image, blurry, low quality, worst quality, extra limbs, extra fingers, "
    "deformed hands, distorted body, cropped, watermark, subtitles"
)


# Frame-length envelope for the variable-length TI2V-5B revision.  Wan's VAE compresses time by
# 4, so a legal length is 4n+1.  49 is the PR-VID-110 qualified length; the maximum is the
# longest length accepted on the target workstation in PR-VID-190 real acceptance.  FPS stays
# fixed at the qualified 24 and is not an operator knob.
WAN22_FRAME_COUNT_POLICY = {
    "default": 49,
    "minimum": 17,
    "maximum": 81,
    "step": 4,
    "offset": 1,
    "fps": 24,
}
# Release the StableNew-owned Comfy after every job so the next queued job starts from a fresh
# runtime instead of failing resource readiness against a resident one (PR-VID-190).  Only a
# process StableNew launched and still owns is ever stopped, through ComfyProcessManager.stop().
WAN22_RUNTIME_POLICY = {"release_owned_runtime_after_job": True}


def _build_wan22_ti2v_5b_i2v_v1() -> WorkflowSpec:
    """The PR-VID-110 qualified revision, unchanged: fixed 49 frames, runtime left resident.
    Kept registered so existing jobs replay against their exact pinned graph."""

    return _build_wan22_ti2v_5b_i2v(workflow_version="1.0.0")


def _build_wan22_ti2v_5b_i2v_v1_1() -> WorkflowSpec:
    """Same qualified graph and files; the latent length is the operator's frozen frame count
    and the owned runtime is released after each job (PR-VID-190)."""

    return _build_wan22_ti2v_5b_i2v(
        workflow_version="1.1.0",
        frame_count_policy=WAN22_FRAME_COUNT_POLICY,
        runtime_policy=WAN22_RUNTIME_POLICY,
    )


def _build_wan22_ti2v_5b_i2v(
    *,
    workflow_version: str,
    frame_count_policy: dict[str, int] | None = None,
    runtime_policy: dict[str, Any] | None = None,
) -> WorkflowSpec:
    variable_length = frame_count_policy is not None
    frame_count_bindings = (
        (
            WorkflowInputBinding(
                binding_name="frame_count",
                source_field="stage_config.frame_count",
                backend_key="frame_count",
                description="Generated frame count, frozen at admission (a legal 4n+1 length).",
            ),
        )
        if variable_length
        else ()
    )
    fixed_settings: dict[str, Any] = {
        "frames": 49,
        "fps": 24,
        "steps": 20,
        "cfg": 5,
        "sampler": "uni_pc",
        "scheduler": "simple",
        "geometry": "source-aware: portrait 480x832; landscape 832x480; square uses portrait",
        "workflow_identity": "stock ComfyUI Wan2.2 TI2V-5B, catalog-pinned",
    }
    extra_defaults: dict[str, Any] = {}
    governance_notes = (
        "EXPERIMENTAL: runs only with an explicit per-job opt-in. Qualified in PR-VID-110 "
        "(CONDITIONAL); qualification-derived resource readiness applies before dispatch."
    )
    if frame_count_policy is not None:
        fixed_settings.pop("frames")
        extra_defaults["frame_count_policy"] = dict(frame_count_policy)
    if runtime_policy is not None:
        extra_defaults["runtime_policy"] = dict(runtime_policy)
        governance_notes += (
            " The StableNew-owned ComfyUI is released after every job (PR-VID-190)."
        )
    return WorkflowSpec(
        workflow_id="wan22_ti2v_5b_i2v_v1",
        workflow_version=workflow_version,
        backend_id="comfy",
        display_name="Wan2.2 TI2V-5B Prompt-Directed I2V (Experimental)",
        description=(
            "Experimental prompt-directed image-to-video with stock ComfyUI nodes and the "
            "PR-VID-110 qualified Wan2.2 TI2V-5B files. One source image and a prompt; no "
            "anchors, control video or pose video. Near the 12 GB VRAM ceiling; identity "
            "preservation is observed, not guaranteed."
        ),
        capability_tags=(WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,),
        input_bindings=(
            WorkflowInputBinding(
                binding_name="source_image",
                source_field="input_image_path",
                backend_key="source_image",
                description="Source image the motion is generated from (required).",
            ),
            WorkflowInputBinding(
                binding_name="prompt",
                source_field="prompt",
                backend_key="prompt",
                description="Prompt describing the motion (required).",
            ),
            WorkflowInputBinding(
                binding_name="negative_prompt",
                source_field="negative_prompt",
                backend_key="negative_prompt",
                required=False,
                description="Negative prompt (the qualified default is applied when empty).",
            ),
            WorkflowInputBinding(
                binding_name="seed",
                source_field="stage_config.seed",
                backend_key="seed",
                description="Sampler seed recorded in the immutable job for exact replay.",
            ),
            WorkflowInputBinding(
                binding_name="target_width",
                source_field="stage_config.source_preparation.target_dimensions.width",
                backend_key="target_width",
                description="Frozen source-aware target width selected before queue admission.",
            ),
            WorkflowInputBinding(
                binding_name="target_height",
                source_field="stage_config.source_preparation.target_dimensions.height",
                backend_key="target_height",
                description="Frozen source-aware target height selected before queue admission.",
            ),
            *frame_count_bindings,
        ),
        output_bindings=(
            WorkflowOutputBinding(
                binding_name="output_dir",
                source_field="output_dir",
                backend_key="output_dir",
                required=True,
                artifact_type="directory",
                description="Run directory owned by StableNew; Comfy output is fetched into it.",
            ),
        ),
        dependency_specs=(
            *(
                WorkflowDependencySpec(
                    dependency_id=dependency_id,
                    dependency_kind="model_file",
                    locator=filename,
                    version_hint=loader_input,
                    description=(
                        f"{filename} (sha256 {digest[:16]}..., {WAN22_UPSTREAM_REPO}"
                        f"@{WAN22_UPSTREAM_REVISION[:12]})"
                    ),
                )
                for dependency_id, filename, loader_input, digest in WAN22_MODEL_FILES
            ),
            *(
                WorkflowDependencySpec(
                    dependency_id=f"node_{node.lower()}",
                    dependency_kind="stock_node",
                    locator=node,
                    description=f"Stock ComfyUI node {node}",
                )
                for node in WAN22_STOCK_NODES
            ),
        ),
        governance_state="experimental",
        pinned_revision=f"catalog:wan22_ti2v_5b_i2v_v1@{workflow_version}",
        governance_notes=governance_notes,
        backend_defaults={
            **extra_defaults,
            "workflow_family": "wan22",
            "transport": "local_comfy",
            "output_transport": "comfy_view",
            "default_negative_prompt": WAN22_DEFAULT_NEGATIVE,
            "provenance": {
                "qualification": "PR-VID-110",
                "comfyui_version": "0.3.65",
                "upstream_repo": WAN22_UPSTREAM_REPO,
                "upstream_revision": WAN22_UPSTREAM_REVISION,
                "license": "Apache-2.0",
                "files": {name: digest for _id, name, _hint, digest in WAN22_MODEL_FILES},
            },
            "resource_readiness": {
                "policy": "wan22_ti2v_5b",
                "min_available_to_comfy_vram_mib": 10000,
                "min_available_ram_gb": 16.0,
            },
            "source_preparation": {
                "resize_policy": "cover_resize_center_crop",
                "portrait_target": {"width": 480, "height": 832},
                "landscape_target": {"width": 832, "height": 480},
                "square_orientation": "portrait",
            },
            "operator_projection": {"fixed_settings": fixed_settings},
            "prompt_template": {
                "1": {
                    "class_type": "UNETLoader",
                    "inputs": {
                        "unet_name": "wan2.2_ti2v_5B_fp16.safetensors",
                        "weight_dtype": "default",
                    },
                },
                "2": {
                    "class_type": "CLIPLoader",
                    "inputs": {
                        "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                        "type": "wan",
                    },
                },
                "3": {
                    "class_type": "VAELoader",
                    "inputs": {"vae_name": "wan2.2_vae.safetensors"},
                },
                "4": {
                    "class_type": "ModelSamplingSD3",
                    "inputs": {"model": ["1", 0], "shift": 8.0},
                },
                "5": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "{{input.prompt}}", "clip": ["2", 0]},
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "{{input.negative_prompt}}", "clip": ["2", 0]},
                },
                "7": {"class_type": "LoadImage", "inputs": {"image": "{{input.source_image}}"}},
                "8": {
                    "class_type": "Wan22ImageToVideoLatent",
                    "inputs": {
                        "vae": ["3", 0],
                        "width": "{{input.target_width}}",
                        "height": "{{input.target_height}}",
                        "length": "{{input.frame_count}}" if variable_length else 49,
                        "batch_size": 1,
                        "start_image": ["7", 0],
                    },
                },
                "9": {
                    "class_type": "KSampler",
                    "inputs": {
                        "model": ["4", 0],
                        "seed": "{{input.seed}}",
                        "steps": 20,
                        "cfg": 5.0,
                        "sampler_name": "uni_pc",
                        "scheduler": "simple",
                        "positive": ["5", 0],
                        "negative": ["6", 0],
                        "latent_image": ["8", 0],
                        "denoise": 1.0,
                    },
                },
                "10": {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": ["9", 0], "vae": ["3", 0]},
                },
                "11": {
                    "class_type": "CreateVideo",
                    "inputs": {"images": ["10", 0], "fps": 24.0},
                },
                "12": {
                    "class_type": "SaveVideo",
                    "inputs": {
                        "video": ["11", 0],
                        "filename_prefix": "stablenew/wan22_{{request.job_id}}",
                        "format": "auto",
                        "codec": "auto",
                    },
                },
            },
        },
    )
