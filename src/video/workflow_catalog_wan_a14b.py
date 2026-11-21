"""Wan2.2 I2V-A14B lightx2v 4-step workflow spec (VID-CLIP-370; approved by VID-CLIP-372).

The stock-node graph frozen in ``tools/qualification/wan321f/plan.py`` and run three times on the
target host (``docs/Subsystems/Video/PR-VID-WAN-321F_Feasibility.md``): two scaled-fp8 A14B experts
(high-noise and low-noise), each with its lightx2v 4-step LoRA at strength 1.0 and ``ModelSamplingSD3``
shift 5, a CPU UMT5 text encoder, the Wan 2.1 VAE, ``WanImageToVideo``, and two ``KSamplerAdvanced``
passes (four Euler/simple steps in total at CFG 1: steps [0, 2) on the high-noise expert, adding noise
and returning leftover noise; steps [2, 4) on the low-noise expert with no added noise).  The output is
lossless PNG frames (``SaveImage``) that StableNew encodes, like TI2V-5B 1.3.0, at the model's native
16 fps.

It was an eval candidate (VID-CLIP-370) and is now ``approved`` by the owner's recorded GO decision of
2026-11-18 (``docs/Subsystems/Video/PR-VID-CLIP-371_Three_Engine_Eval.md``): the promoted human-motion
engine and the Make Video default.  Approval is governance only; the graph is byte-for-byte the 321F
graph.  It is not QUALIFIED by the qualification ledger: the 321F session ended with an INCONCLUSIVE
frozen verdict (teardown was not verified) and the 371 evidence rests on the owner's own ratings.  It
still runs only after the execution-time GPU guard and only on a managed ComfyUI launched with
``--disable-pinned-memory``.  The readiness floors below are derived from the 321F session's numbers;
they are a guard, not a qualification.  StableNew binds the same inputs it binds for TI2V-5B (source image,
prompt, negative prompt, seed, frozen geometry, frozen frame count) and nothing else: there is no LoRA
control and no first/last-frame input.
"""

from __future__ import annotations

from typing import Any

from src.video.workflow_contracts import (
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
    WORKFLOW_GOVERNANCE_APPROVED,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)

WAN_A14B_ID = "wan22_i2v_a14b_4step_v1"
WAN_A14B_VERSION = "1.0.0"
WAN_A14B_REPACKAGED_REPO = "Comfy-Org/Wan-2.2"
WAN_A14B_REPACKAGED_REVISION = "ee6f4a40737a995bf5818954cfce6d59443b0f04"
WAN_A14B_LORA_REPO = "lightx2v/Wan2.2-Distill-Loras"
WAN_A14B_LORA_REVISION = "57adea585d1d21085e2dfc91ce3c7b646cdd9345"
WAN_A14B_HIGH_UNET = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
WAN_A14B_LOW_UNET = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
WAN_A14B_TEXT_ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
WAN_A14B_VAE = "wan_2.1_vae.safetensors"
WAN_A14B_HIGH_LORA = "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors"
WAN_A14B_LOW_LORA = "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors"

# (dependency id, file name, loader input that must list the file, sha256, upstream repo, revision).
# The digests are the ones recorded in tools/qualification/wan321f/plan.py (ASSETS); a test keeps the
# two in step.
WAN_A14B_MODEL_FILES = (
    (
        "wan_a14b_high_noise_unet",
        WAN_A14B_HIGH_UNET,
        "UNETLoader.unet_name",
        "6122e79d55e0f235698d11d657f3b196c5273c830da00b2b013c5a048d5e6a42",
        WAN_A14B_REPACKAGED_REPO,
        WAN_A14B_REPACKAGED_REVISION,
    ),
    (
        "wan_a14b_low_noise_unet",
        WAN_A14B_LOW_UNET,
        "UNETLoader.unet_name",
        "5471a457b6ac404202a5fbe6c11595a3d5641fc766b00f38763f72303fffc21e",
        WAN_A14B_REPACKAGED_REPO,
        WAN_A14B_REPACKAGED_REVISION,
    ),
    (
        "wan_a14b_text_encoder",
        WAN_A14B_TEXT_ENCODER,
        "CLIPLoader.clip_name",
        "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
        WAN_A14B_REPACKAGED_REPO,
        WAN_A14B_REPACKAGED_REVISION,
    ),
    (
        "wan_a14b_vae",
        WAN_A14B_VAE,
        "VAELoader.vae_name",
        "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
        WAN_A14B_REPACKAGED_REPO,
        WAN_A14B_REPACKAGED_REVISION,
    ),
    (
        "wan_a14b_high_noise_lora",
        WAN_A14B_HIGH_LORA,
        "LoraLoaderModelOnly.lora_name",
        "887c3bdeb74e83859c920438e16ca31f39ab18ce189abc5f0e36f8348c5bbb19",
        WAN_A14B_LORA_REPO,
        WAN_A14B_LORA_REVISION,
    ),
    (
        "wan_a14b_low_noise_lora",
        WAN_A14B_LOW_LORA,
        "LoraLoaderModelOnly.lora_name",
        "8833bd4fd7c8eabebf0bc8ee5cfaf47f4f310ce116928a02c1adf8941dd4b0f1",
        WAN_A14B_LORA_REPO,
        WAN_A14B_LORA_REVISION,
    ),
)
WAN_A14B_STOCK_NODES = (
    "UNETLoader",
    "LoraLoaderModelOnly",
    "ModelSamplingSD3",
    "CLIPLoader",
    "VAELoader",
    "LoadImage",
    "CLIPTextEncode",
    "WanImageToVideo",
    "KSamplerAdvanced",
    "VAEDecode",
    "SaveImage",
)
# The 321F negative prompt.  At CFG 1.0 it has no effect on sampling; it is kept as frozen.
WAN_A14B_DEFAULT_NEGATIVE = "static, blurry, deformed hands, extra limbs, watermark, subtitles"
# 81 frames (about 5 s at 16 fps) is the only length measured in 321F.  The Wan VAE compresses time by 4,
# so a legal length is 4n+1; 17 (about 1 s) is the shortest the shared envelope offers.
WAN_A14B_FRAME_COUNT_POLICY = {
    "default": 81,
    "minimum": 17,
    "maximum": 81,
    "step": 4,
    "offset": 1,
    "fps": 16,
}
WAN_A14B_REQUIRED_LAUNCH_FLAGS = ("--disable-pinned-memory",)
# VID-WARM-373 (owner request 2026-11-21): after a successful job the StableNew-owned ComfyUI stays warm for this
# many seconds of idle time, so the next A14B job skips the cold start and the two-expert load (321F: 125 s cold
# versus 91-92 s warm prompt time in one process). Any other job, a failure or cancellation, or the grace passing
# still releases it. The graph's ModelSamplingSD3 shift is a constant, so a reused process never sees another one.
WAN_A14B_KEEP_WARM_SECONDS = 120
# 321F: peak whole-GPU VRAM 9,596 MiB of 12,282 with 1,420 MiB in use before the run, i.e. a footprint of
# about 8,176 MiB; the floor adds ~5 % margin.  The host-RAM figure is advisory only: the session started
# with 16.4 GiB free and dipped to 4.8 GiB while loading about 36 GB of weights.
WAN_A14B_RESOURCE_READINESS = {
    "policy": "wan22_i2v_a14b_4step",
    "min_available_to_comfy_vram_mib": 8600,
    "min_available_ram_gb": 16.0,
}


def _prompt_template() -> dict[str, Any]:
    def node(kind: str, **inputs: Any) -> dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    sampler = {
        "steps": 4,
        "cfg": 1.0,
        "sampler_name": "euler",
        "scheduler": "simple",
        "noise_seed": "{{input.seed}}",
        "positive": ["10", 0],
        "negative": ["10", 1],
    }
    return {
        "1": node("UNETLoader", unet_name=WAN_A14B_HIGH_UNET, weight_dtype="default"),
        "2": node("UNETLoader", unet_name=WAN_A14B_LOW_UNET, weight_dtype="default"),
        "3": node(
            "LoraLoaderModelOnly",
            model=["1", 0],
            lora_name=WAN_A14B_HIGH_LORA,
            strength_model=1.0,
        ),
        "4": node(
            "LoraLoaderModelOnly",
            model=["2", 0],
            lora_name=WAN_A14B_LOW_LORA,
            strength_model=1.0,
        ),
        "5": node("ModelSamplingSD3", model=["3", 0], shift=5.0),
        "6": node("ModelSamplingSD3", model=["4", 0], shift=5.0),
        "7": node("CLIPLoader", clip_name=WAN_A14B_TEXT_ENCODER, type="wan", device="cpu"),
        "8": node("VAELoader", vae_name=WAN_A14B_VAE),
        "9": node("LoadImage", image="{{input.source_image}}"),
        "10": node(
            "WanImageToVideo",
            positive=["11", 0],
            negative=["12", 0],
            vae=["8", 0],
            width="{{input.target_width}}",
            height="{{input.target_height}}",
            length="{{input.frame_count}}",
            batch_size=1,
            start_image=["9", 0],
        ),
        "11": node("CLIPTextEncode", clip=["7", 0], text="{{input.prompt}}"),
        "12": node("CLIPTextEncode", clip=["7", 0], text="{{input.negative_prompt}}"),
        "13": node(
            "KSamplerAdvanced",
            **sampler,
            model=["5", 0],
            latent_image=["10", 2],
            add_noise="enable",
            start_at_step=0,
            end_at_step=2,
            return_with_leftover_noise="enable",
        ),
        "14": node(
            "KSamplerAdvanced",
            **sampler,
            model=["6", 0],
            latent_image=["13", 0],
            add_noise="disable",
            start_at_step=2,
            end_at_step=4,
            return_with_leftover_noise="disable",
        ),
        "15": node("VAEDecode", samples=["14", 0], vae=["8", 0]),
        "16": node(
            "SaveImage",
            images=["15", 0],
            filename_prefix="stablenew/wan_a14b_{{request.job_id}}",
        ),
    }


def build_wan_a14b_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=WAN_A14B_ID,
        workflow_version=WAN_A14B_VERSION,
        backend_id="comfy",
        display_name="Wan2.2 I2V-A14B 4-step",
        description=(
            "Prompt-directed image-to-video with the Wan2.2 I2V-A14B high-noise and low-noise "
            "experts and the lightx2v 4-step LoRAs, on stock ComfyUI nodes. One source image and "
            "a prompt; no anchors, control video or pose video. Native 16 fps. The owner-promoted "
            "engine for human motion and the Make Video default; it needs a managed ComfyUI "
            "launched with --disable-pinned-memory and a host with RAM headroom for its two experts."
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
                description="Negative prompt (the 321F default is applied when empty; no effect at CFG 1).",
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
                    description=f"{filename} (sha256 {digest[:16]}..., {repo}@{revision[:12]})",
                )
                for dependency_id, filename, loader_input, digest, repo, revision in (
                    WAN_A14B_MODEL_FILES
                )
            ),
            *(
                WorkflowDependencySpec(
                    dependency_id=f"node_{node.lower()}",
                    dependency_kind="stock_node",
                    locator=node,
                    description=f"Stock ComfyUI node {node}",
                )
                for node in WAN_A14B_STOCK_NODES
            ),
        ),
        governance_state=WORKFLOW_GOVERNANCE_APPROVED,
        pinned_revision=f"catalog:{WAN_A14B_ID}@{WAN_A14B_VERSION}",
        governance_notes=(
            "APPROVED by the owner's decision of 2026-11-18 (VID-CLIP-371 eval record: 80-generation "
            "human-motion evaluation, 8/8 action achieved in both stages, no identity breaks, owner "
            "means 5/5) as the promoted engine and the Make Video default (VID-CLIP-372). Governance "
            "only: the graph is the PR-VID-WAN-321F frozen stock-node graph, unchanged. Not QUALIFIED "
            "by the qualification ledger (321F verdict INCONCLUSIVE; eval ratings are the owner's, "
            "saturated, with no host-commit telemetry). Runs only on a StableNew-managed ComfyUI "
            "launched with --disable-pinned-memory (applied at launch or the job is blocked); the "
            "owned runtime is released after every job. The GPU readiness floor is derived from the "
            "321F session and gates execution; host RAM is advisory. Qualified on ComfyUI 0.38.0: "
            "another runtime version runs with a warning. No LoRA control, no first/last-frame input."
        ),
        backend_defaults={
            "workflow_family": "wan22_i2v_a14b",
            "transport": "local_comfy",
            "output_transport": "comfy_view",
            "default_negative_prompt": WAN_A14B_DEFAULT_NEGATIVE,
            # 321F prompt times were 91-125 s for 81 frames and the VID-CLIP-371 clips took 140-176 s
            # wall (cold load of two experts included); 1200 s keeps about 7x headroom for a slow load
            # on a 32 GB host without abandoning a clip Comfy is still producing.
            "history_timeout_seconds": 1200,
            # The owner's decision (2026-11-18): the engine Make Video preselects among approved ones.
            "make_video_default": True,
            "frame_count_policy": dict(WAN_A14B_FRAME_COUNT_POLICY),
            "output_policy": {"mode": "frames", "fps": WAN_A14B_FRAME_COUNT_POLICY["fps"]},
            "runtime_policy": {
                "release_owned_runtime_after_job": True,
                "keep_warm_between_jobs_seconds": WAN_A14B_KEEP_WARM_SECONDS,
                "required_launch_flags": list(WAN_A14B_REQUIRED_LAUNCH_FLAGS),
            },
            "provenance": {
                "qualification": (
                    "PR-VID-WAN-321F feasibility session (frozen verdict INCONCLUSIVE) and the "
                    "VID-CLIP-371 owner evaluation (GO 2026-11-18); not QUALIFIED by the ledger"
                ),
                "comfyui_version": "0.38.0",
                "comfyui_revision": "6b747c0428c343e1417219641db93a4fb7cb69ae",
                "upstream_repo": WAN_A14B_REPACKAGED_REPO,
                "upstream_revision": WAN_A14B_REPACKAGED_REVISION,
                "lora_repo": WAN_A14B_LORA_REPO,
                "lora_revision": WAN_A14B_LORA_REVISION,
                "license": "Apache-2.0",
                "files": {
                    name: digest for _id, name, _hint, digest, _repo, _rev in WAN_A14B_MODEL_FILES
                },
            },
            "resource_readiness": dict(WAN_A14B_RESOURCE_READINESS),
            "source_preparation": {
                "resize_policy": "cover_resize_center_crop",
                "portrait_target": {"width": 480, "height": 832},
                "landscape_target": {"width": 832, "height": 480},
                "square_orientation": "portrait",
            },
            "operator_projection": {
                "fixed_settings": {
                    "fps": 16,
                    "steps": "4 total (2 high-noise, 2 low-noise)",
                    "cfg": 1,
                    "sampler": "euler",
                    "scheduler": "simple",
                    "shift": 5,
                    "lora": "lightx2v 4-step, strength 1.0 on each expert (fixed)",
                    "geometry": "source-aware: portrait 480x832; landscape 832x480; square uses portrait",
                    "workflow_identity": "stock ComfyUI Wan2.2 I2V-A14B two-expert, catalog-pinned",
                    "output": (
                        "lossless PNG frames from Comfy; StableNew encodes the clip (CRF 16, BT.709) "
                        "and can smooth it"
                    ),
                    "hardware": (
                        "321F feasibility (INCONCLUSIVE) and the VID-CLIP-371 evaluation; "
                        "RTX 4070 Ti 12 GB, 32 GB RAM; not QUALIFIED by the ledger"
                    ),
                },
            },
            "prompt_template": _prompt_template(),
        },
    )


__all__ = [
    "WAN_A14B_FRAME_COUNT_POLICY",
    "WAN_A14B_ID",
    "WAN_A14B_KEEP_WARM_SECONDS",
    "WAN_A14B_MODEL_FILES",
    "WAN_A14B_STOCK_NODES",
    "WAN_A14B_VERSION",
    "build_wan_a14b_spec",
]
