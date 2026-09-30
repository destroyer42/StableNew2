"""Wan-Animate-2 experimental workflow specs (PR-VID-190 part 2).

For real-world testing on the StableNew-managed ComfyUI v0.37.0 runtime.  Built node-for-node from
the PR-VID-184R/S qualified flat graph (sha256 ``9ef8dae4...``): the same four pinned files,
``WanAnimate2ToVideo``, lcm/simple, 10 steps, shift 5, cfg 1 and the stock Wan negative prompt, with
``WanAnimate2Cache`` and context windows off, exactly as qualified.  StableNew binds the reference
image, prompt, seed, frozen geometry and frozen frame count; output is encoded with stock
``CreateVideo``/``SaveVideo`` (mp4), like the TI2V workflow.

Two declarative specs rather than one spec with a conditional branch, so the generic compiler never
needs workflow-specific logic:

* **prompt motion** - reference image + prompt; the node's optional ``pose_video`` is left
  unconnected.  This mode was not part of the PR-VID-184 qualification; it is exposed precisely so
  the owner can evaluate it.
* **driving video** - adds a raw human driving video whose body motion is transferred (the
  qualified mode).  ``WanAnimate2ToVideo`` VAE-encodes the frames directly; no pose preprocessing.

The qualified launch policy (``--disable-pinned-memory``) is a declared runtime requirement, and the
StableNew-owned runtime is released after every job.

Versions (PR-VID-192): ``1.0.0`` is the exact PR-VID-191 graph, kept registered unchanged so its
jobs replay against the identical pinned graph.  ``1.1.0`` binds the controls the pinned ComfyUI
v0.37.0 ``WanAnimate2ToVideo`` node actually honors (see ``docs/Subsystems/Video/
PR-VID-192_Animate2_Control_Truth.md``): a distinct Motion Prompt wired to ``positive_pose``, pose
strength, the pose window and reference-image strength, plus an honest description of prompt mode.
Every control default equals the node's own default, and generic ``motion_profile`` is not declared
by either version because no node input honors it.
"""

from __future__ import annotations

from typing import Any

from src.video.workflow_contracts import (
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
    WORKFLOW_CAP_POSE_VIDEO,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)
from src.video.workflow_controls import OPERATOR_CONTROLS_KEY, ORDERED_PAIRS_KEY

WAN_ANIMATE2_PROMPT_ID = "wan_animate2_prompt_i2v_v1"
WAN_ANIMATE2_DRIVE_ID = "wan_animate2_drive_i2v_v1"
WAN_ANIMATE2_QUALIFIED_GRAPH_SHA256 = (
    "9ef8dae44d330e5af05c70fccd02d86d0855b4fb983d1913f8f7f8a012c3928c"
)
WAN_ANIMATE2_MODEL_FILES = (
    (
        "wan_animate2_unet",
        "wan_animate_2_distill_int8_convrot.safetensors",
        "UNETLoader.unet_name",
        "d2e566ecac3f164cb1a6b63dc7d868d6678c9affa49fbceb3abe4f9458f89c8a",
    ),
    (
        "wan_animate2_text_encoder",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "CLIPLoader.clip_name",
        "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    ),
    (
        "wan_animate2_vae",
        "Wan2_1_VAE_bf16.safetensors",
        "VAELoader.vae_name",
        "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9",
    ),
    (
        "wan_animate2_clip_vision",
        "clip_vision_h.safetensors",
        "CLIPVisionLoader.clip_name",
        "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161",
    ),
)
WAN_ANIMATE2_BASE_NODES = (
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "CLIPVisionLoader",
    "CLIPVisionEncode",
    "CLIPTextEncode",
    "LoadImage",
    "ModelSamplingSD3",
    "WanAnimate2ToVideo",
    "BasicScheduler",
    "KSamplerSelect",
    "SamplerCustom",
    "TrimVideoLatent",
    "VAEDecode",
    "CreateVideo",
    "SaveVideo",
)
WAN_ANIMATE2_DRIVE_NODES = ("LoadVideo", "GetVideoComponents", "ResizeImageMaskNode", "ImageFromBatch")
# The stock Wan negative prompt, verbatim from the qualified graph.
WAN_ANIMATE2_DEFAULT_NEGATIVE = (
    "色调艳丽，过曝，静态，细节"
    "模糊不清，字幕，风格，作品"
    "，画作，画面，静止，整体发"
    "灰，最差质量，低质量，JPEG压"
    "缩残留，丑陋的，残缺的，多"
    "余的手指，画得不好的手部，"
    "画得不好的脸部，畸形的，毁"
    "容的，形态畸形的肢体，手指"
    "融合，静止不动的画面，杂乱"
    "的背景，三条腿，背景人很多"
    "，倒着走"
)
# 41 frames is the qualified length; the maximum is the longest length accepted on the target
# workstation in PR-VID-190 real acceptance.
WAN_ANIMATE2_FRAME_COUNT_POLICY = {
    "default": 41,
    "minimum": 17,
    "maximum": 81,
    "step": 4,
    "offset": 1,
    "fps": 24,
}
WAN_ANIMATE2_REQUIRED_LAUNCH_FLAGS = ("--disable-pinned-memory",)
WAN_ANIMATE2_BASELINE_VERSION = "1.0.0"
WAN_ANIMATE2_CONTROLS_VERSION = "1.1.0"

# Operator controls bound to real ``WanAnimate2ToVideo`` inputs on the pinned ComfyUI v0.37.0.  Ranges
# and defaults are the node's own (comfy_extras/nodes_wan.py, revision 73c9bad4); help paraphrases its
# tooltips.  ``pose_prompt`` maps to ``positive_pose`` ("describes the motion rather than the
# character; defaults to positive"), so an empty Motion Prompt is frozen as the appearance prompt --
# exactly the node's own default, but now explicit in the immutable job.
_REFERENCE_STRENGTH_CONTROL: dict[str, Any] = {
    "name": "reference_image_strength",
    "kind": "number",
    "label": "Reference Image Strength",
    "default": 1.0,
    "minimum": 0.0,
    "maximum": 10.0,
    "step": 0.01,
    "help": (
        "How strongly generated frames attend to the reference image. 1.0 is the trained behavior; "
        "below 1.0 loosens identity/appearance adherence, above tightens it against drift."
    ),
}
_DRIVE_CONTROLS: tuple[dict[str, Any], ...] = (
    {
        "name": "pose_prompt",
        "kind": "text",
        "label": "Motion Prompt",
        "fallback_field": "prompt",
        "help": (
            "Describes ONLY the motion to transfer (feeds the model's positive_pose branch). Leave "
            "empty to reuse the appearance/background prompt, which is the runtime default."
        ),
    },
    {
        "name": "pose_strength",
        "kind": "number",
        "label": "Pose Strength",
        "default": 1.0,
        "minimum": 0.0,
        "maximum": 10.0,
        "step": 0.01,
        "help": (
            "Scales the driving video's influence on motion. 1.0 is the trained behavior; below "
            "weakens adherence, above amplifies. 0.0 mutes it but does not fully remove it."
        ),
    },
    {
        "name": "pose_start_percent",
        "kind": "number",
        "label": "Pose Start %",
        "default": 0.0,
        "minimum": 0.0,
        "maximum": 1.0,
        "step": 0.01,
        "help": "Fraction of sampling at which the driving-video influence starts (0-1).",
    },
    {
        "name": "pose_end_percent",
        "kind": "number",
        "label": "Pose End %",
        "default": 1.0,
        "minimum": 0.0,
        "maximum": 1.0,
        "step": 0.01,
        "help": (
            "Fraction of sampling at which the driving-video influence ends (0-1). Motion is mostly "
            "established early, so e.g. 0.7 can loosen fine detail while keeping the choreography."
        ),
    },
    _REFERENCE_STRENGTH_CONTROL,
)
_PROMPT_CONTROLS: tuple[dict[str, Any], ...] = (_REFERENCE_STRENGTH_CONTROL,)


def _prompt_template(*, driving_video: bool, controlled: bool = False) -> dict[str, Any]:
    animate_inputs: dict[str, Any] = {
        "positive": ["5", 0],
        "negative": ["6", 0],
        "vae": ["3", 0],
        "reference_image": ["7", 0],
        "clip_vision_output": ["8", 0],
        "width": "{{input.target_width}}",
        "height": "{{input.target_height}}",
        "length": "{{input.frame_count}}",
        "batch_size": 1,
        "video_frame_offset": 0,
        "pose_strength": 1.0,
        "pose_start_percent": 0.0,
        "pose_end_percent": 1.0,
        "reference_image_strength": 1.0,
    }
    template: dict[str, Any] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan_animate_2_distill_int8_convrot.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "type": "wan",
                "device": "default",
            },
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "Wan2_1_VAE_bf16.safetensors"}},
        "4": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{input.prompt}}", "clip": ["2", 0]}},
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "{{input.negative_prompt}}", "clip": ["2", 0]},
        },
        "7": {"class_type": "LoadImage", "inputs": {"image": "{{input.source_image}}"}},
        "8": {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["4", 0], "image": ["7", 0], "crop": "none"},
        },
        "9": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 5.0}},
        "10": {"class_type": "WanAnimate2ToVideo", "inputs": animate_inputs},
        # As qualified: sigmas come from the unshifted model; sampling uses the shifted one.
        "11": {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 10, "denoise": 1.0},
        },
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "lcm"}},
        "13": {
            "class_type": "SamplerCustom",
            "inputs": {
                "model": ["9", 0],
                "positive": ["10", 0],
                "negative": ["10", 1],
                "sampler": ["12", 0],
                "sigmas": ["11", 0],
                "latent_image": ["10", 2],
                "add_noise": True,
                "noise_seed": "{{input.seed}}",
                "cfg": 1.0,
            },
        },
        "14": {
            "class_type": "TrimVideoLatent",
            "inputs": {"samples": ["13", 0], "trim_amount": ["10", 3]},
        },
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["3", 0]}},
        "16": {"class_type": "CreateVideo", "inputs": {"images": ["15", 0], "fps": 24.0}},
        "17": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["16", 0],
                "filename_prefix": "stablenew/wan_animate2_{{request.job_id}}",
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    if driving_video:
        template["18"] = {"class_type": "LoadVideo", "inputs": {"file": "{{input.pose_video}}"}}
        template["19"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["18", 0]}}
        template["20"] = {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": ["19", 0],
                "resize_type": "scale dimensions",
                "resize_type.width": "{{input.target_width}}",
                "resize_type.height": "{{input.target_height}}",
                "resize_type.crop": "center",
                "scale_method": "area",
            },
        }
        template["21"] = {
            "class_type": "ImageFromBatch",
            "inputs": {"image": ["20", 0], "batch_index": 0, "length": 1},
        }
        template["22"] = {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["4", 0], "image": ["21", 0], "crop": "none"},
        }
        animate_inputs["pose_video"] = ["20", 0]
        animate_inputs["clip_vision_output_pose"] = ["22", 0]
    if controlled:
        animate_inputs["reference_image_strength"] = "{{input.reference_image_strength}}"
        if driving_video:
            # A distinct motion-only prompt for the pose branch (the node otherwise reuses `positive`).
            template["23"] = {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "{{input.pose_prompt}}", "clip": ["2", 0]},
            }
            animate_inputs["positive_pose"] = ["23", 0]
            animate_inputs["pose_strength"] = "{{input.pose_strength}}"
            animate_inputs["pose_start_percent"] = "{{input.pose_start_percent}}"
            animate_inputs["pose_end_percent"] = "{{input.pose_end_percent}}"
    return template


def _bindings(*, driving_video: bool, controlled: bool = False) -> tuple[WorkflowInputBinding, ...]:
    bindings = [
        WorkflowInputBinding(
            binding_name="source_image",
            source_field="input_image_path",
            backend_key="source_image",
            description="Reference image: the character whose appearance is animated (required).",
        ),
        WorkflowInputBinding(
            binding_name="prompt",
            source_field="prompt",
            backend_key="prompt",
            description=(
                (
                    "Appearance / background prompt: the character, background and viewpoint, not "
                    "the action (required)."
                    if driving_video
                    else "Prompt describing the character and scene (required); with no driving "
                    "video it can only weakly influence motion."
                )
                if controlled
                else "Prompt describing the character and the motion (required)."
            ),
        ),
        WorkflowInputBinding(
            binding_name="negative_prompt",
            source_field="negative_prompt",
            backend_key="negative_prompt",
            required=False,
            description="Negative prompt (the qualified stock Wan negative applies when empty).",
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
        WorkflowInputBinding(
            binding_name="frame_count",
            source_field="stage_config.frame_count",
            backend_key="frame_count",
            description="Generated frame count, frozen at admission (a legal 4n+1 length).",
        ),
    ]
    if driving_video:
        bindings.append(
            WorkflowInputBinding(
                binding_name="pose_video",
                source_field="stage_config.pose_video_path",
                backend_key="pose_video",
                description=(
                    "Driving video (required): a raw clip of a person whose body motion is "
                    "transferred to the reference character. No pose preprocessing is needed."
                ),
            )
        )
    if controlled:
        for control in _DRIVE_CONTROLS if driving_video else _PROMPT_CONTROLS:
            bindings.append(
                WorkflowInputBinding(
                    binding_name=control["name"],
                    source_field=f"stage_config.{OPERATOR_CONTROLS_KEY}.{control['name']}",
                    backend_key=control["name"],
                    description=str(control["help"]),
                )
            )
    return tuple(bindings)


def _build(*, workflow_id: str, driving_video: bool, controlled: bool = False) -> WorkflowSpec:
    stock_nodes = WAN_ANIMATE2_BASE_NODES + (WAN_ANIMATE2_DRIVE_NODES if driving_video else ())
    capability_tags = (WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,) + (
        (WORKFLOW_CAP_POSE_VIDEO,) if driving_video else ()
    )
    version = WAN_ANIMATE2_CONTROLS_VERSION if controlled else WAN_ANIMATE2_BASELINE_VERSION
    if controlled:
        mode = "Driving Video Motion" if driving_video else "Reference Image + Prompt"
        display_name = (
            f"Wan-Animate-2 {mode} (Experimental)"
            if driving_video
            else f"Wan-Animate-2 {mode} (Experimental, subtle motion)"
        )
        how = (
            "A driving video supplies the body motion (the PR-VID-184R/S qualified mode). The "
            "appearance/background prompt describes the character and scene; a separate Motion "
            "Prompt describes only the motion. Pose strength, the pose window and reference-image "
            "strength are real model inputs."
            if driving_video
            else "There is no driving video, so the model's pose branch is skipped: motion comes "
            "only from the text prompt and is typically subtle. Wan-Animate-2 is built around a "
            "driving video; this mode is exploratory, not directed animation. Use Driving Video "
            "Motion for directed movement."
        )
    else:
        mode = "Driving Video Motion" if driving_video else "Prompt Motion"
        display_name = f"Wan-Animate-2 {mode} (Experimental)"
        how = (
            "A driving video supplies the body motion (the PR-VID-184R/S qualified mode) and the "
            "prompt describes the scene."
            if driving_video
            else "The prompt describes the motion; no driving video. This mode was not part of the "
            "PR-VID-184 qualification and is exposed for real-world testing."
        )
    return WorkflowSpec(
        workflow_id=workflow_id,
        workflow_version=version,
        backend_id="comfy",
        display_name=display_name,
        description=(
            "Experimental Wan-Animate-2 on the StableNew-managed ComfyUI (v0.37+). The reference "
            f"image sets the character's appearance. {how}"
        ),
        capability_tags=capability_tags,
        input_bindings=_bindings(driving_video=driving_video, controlled=controlled),
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
                    description=f"{filename} (sha256 {digest[:16]}..., PR-VID-184R/S qualified)",
                )
                for dependency_id, filename, loader_input, digest in WAN_ANIMATE2_MODEL_FILES
            ),
            *(
                WorkflowDependencySpec(
                    dependency_id=f"node_{node.lower()}",
                    dependency_kind="stock_node",
                    locator=node,
                    description=f"Stock ComfyUI node {node}",
                )
                for node in stock_nodes
            ),
        ),
        governance_state="experimental",
        pinned_revision=f"catalog:{workflow_id}@{version}",
        governance_notes=(
            "EXPERIMENTAL: runs only with an explicit per-job opt-in, only on a StableNew-managed "
            "ComfyUI launched with --disable-pinned-memory; the owned runtime is released after "
            "every job (PR-VID-190)."
        ),
        backend_defaults={
            "workflow_family": "wan_animate2",
            "transport": "local_comfy",
            "output_transport": "comfy_view",
            "default_negative_prompt": WAN_ANIMATE2_DEFAULT_NEGATIVE,
            # PR-VID-184R: 164 s for 41 frames including a cold load; longer lengths scale up.
            "history_timeout_seconds": 1200,
            "frame_count_policy": dict(WAN_ANIMATE2_FRAME_COUNT_POLICY),
            "runtime_policy": {
                "release_owned_runtime_after_job": True,
                "required_launch_flags": list(WAN_ANIMATE2_REQUIRED_LAUNCH_FLAGS),
            },
            "provenance": {
                "qualification": (
                    "PR-VID-184R/PR-VID-184S graph; PR-VID-192 control bindings (defaults equal the "
                    "pinned node defaults)"
                    if controlled
                    else "PR-VID-184R/PR-VID-184S (driving-video mode)"
                ),
                "qualified_graph_sha256": WAN_ANIMATE2_QUALIFIED_GRAPH_SHA256,
                "comfyui_version": "0.37.0",
                "comfyui_revision": "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
                "files": {name: digest for _id, name, _hint, digest in WAN_ANIMATE2_MODEL_FILES},
            },
            # PR-VID-184S pinned-OFF evidence: ~11.8 GB peak whole-GPU VRAM from a ~1.1 GB
            # baseline and a ~12-14 GB host-memory rise; the same floors as the TI2V workflow.
            "resource_readiness": {
                "policy": "wan_animate2",
                "min_available_to_comfy_vram_mib": 10000,
                "min_available_ram_gb": 16.0,
            },
            "source_preparation": {
                "resize_policy": "cover_resize_center_crop",
                "portrait_target": {"width": 480, "height": 832},
                "landscape_target": {"width": 832, "height": 480},
                "square_orientation": "portrait",
            },
            "operator_projection": {
                "fixed_settings": {
                    "fps": 24,
                    "steps": 10,
                    "cfg": 1,
                    "sampler": "lcm",
                    "scheduler": "simple",
                    "shift": 5,
                    "geometry": "source-aware: portrait 480x832; landscape 832x480",
                    "workflow_identity": "Wan-Animate-2 distilled int8, PR-VID-184R/S graph",
                    **(
                        {"negative_prompt_effect": "none at cfg 1.0 (kept as qualified)"}
                        if controlled
                        else {}
                    ),
                },
                **(
                    {
                        "prompt_label": (
                            "Appearance / Background Prompt" if driving_video else "Prompt"
                        )
                    }
                    if controlled
                    else {}
                ),
            },
            "prompt_template": _prompt_template(driving_video=driving_video, controlled=controlled),
            **(
                {
                    OPERATOR_CONTROLS_KEY: [
                        dict(control) for control in (_DRIVE_CONTROLS if driving_video else _PROMPT_CONTROLS)
                    ],
                    **(
                        {ORDERED_PAIRS_KEY: [["pose_start_percent", "pose_end_percent"]]}
                        if driving_video
                        else {}
                    ),
                }
                if controlled
                else {}
            ),
        },
    )


def build_wan_animate2_specs() -> tuple[WorkflowSpec, ...]:
    return (
        _build(workflow_id=WAN_ANIMATE2_PROMPT_ID, driving_video=False),
        _build(workflow_id=WAN_ANIMATE2_DRIVE_ID, driving_video=True),
        _build(workflow_id=WAN_ANIMATE2_PROMPT_ID, driving_video=False, controlled=True),
        _build(workflow_id=WAN_ANIMATE2_DRIVE_ID, driving_video=True, controlled=True),
    )


__all__ = [
    "WAN_ANIMATE2_BASELINE_VERSION",
    "WAN_ANIMATE2_CONTROLS_VERSION",
    "WAN_ANIMATE2_DEFAULT_NEGATIVE",
    "WAN_ANIMATE2_DRIVE_ID",
    "WAN_ANIMATE2_FRAME_COUNT_POLICY",
    "WAN_ANIMATE2_MODEL_FILES",
    "WAN_ANIMATE2_PROMPT_ID",
    "WAN_ANIMATE2_QUALIFIED_GRAPH_SHA256",
    "build_wan_animate2_specs",
]
