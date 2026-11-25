"""HunyuanVideo 1.5 480p image-to-video, step-distilled FP8: an EXPERIMENTAL eval candidate (VID-CAND-382).

A stock-node graph on the managed ComfyUI 0.38.0 (``comfy_extras/nodes_hunyuan.py``, ``nodes.py``): the Comfy-Org
repack of Tencent's step-distilled 480p I2V diffusion model (FP8 scaled), the Qwen2.5-VL 7B text encoder and the
ByT5 glyph encoder loaded together by ``DualCLIPLoader`` (type ``hunyuan_video_15``), the HunyuanVideo 1.5 VAE, the
SigCLIP vision tower encoding the source image, ``HunyuanVideo15ImageToVideo`` and one ``KSampler`` (Euler/simple, CFG 1).
The output is lossless PNG frames (``SaveImage``) that StableNew encodes, like TI2V-5B 1.3.0 and A14B, at the model's
native 24 fps.  No ``ModelSamplingSD3`` node is added: the model carries its own flow shift of 7.0
(``comfy/supported_models.py::HunyuanVideo15.sampling_settings``).

It exists to be compared with the approved Wan2.2 I2V-A14B 4-step 1.0.0 in an owner-rated evaluation
(``docs/Subsystems/Video/PR-VID-CAND-382_HunyuanVideo15_Candidate_Eval.md``).  Two workflow ids differ
only in the sampler step count: the 8-step id runs 8 steps and the 12-step id runs 12 (the range the model card gives for the
step-distilled build).  Both are ``experimental``: they need the job's own recorded opt-in, are never the Make Video
default and are never preselected.  They are NOT QUALIFIED: nothing here has run on the target host.  The sampler values,
the resource floors and the keep-warm grace are frozen from the stock-node convention and the published figures, not
measured; the evaluation's stage 0 measures them and any change is a new version.

Licence: the Tencent HunyuanVideo-1.5 community licence excludes the EU, the UK and South Korea; the owner must accept it
for this host before any file is downloaded (STATUS open decision; precedent: the Ideogram licence).  Nothing downloads
the files: the tuples below pin them by name, digest and ``repo@revision`` so a later download can be verified.
"""

from __future__ import annotations

from typing import Any

from src.video.workflow_contracts import (
    WORKFLOW_CAP_LOCAL_PROCESS_REQUIRED,
    WORKFLOW_GOVERNANCE_EXPERIMENTAL,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)

# Two workflow ids, not two versions of one: an experimental-only id would present its newest version as the entry, and
# neither step count may be positioned as the default.  Each id has its own pinned 1.0.0 and its own warm hold.
HUNYUAN15_ID = "hunyuan_video15_i2v_480p_8step_v1"
HUNYUAN15_12_STEP_ID = "hunyuan_video15_i2v_480p_12step_v1"
HUNYUAN15_VERSION = "1.0.0"
HUNYUAN15_STEPS = {HUNYUAN15_ID: 8, HUNYUAN15_12_STEP_ID: 12}
HUNYUAN15_IDS = tuple(HUNYUAN15_STEPS)

# Hugging Face repack.  The Hub now reports this repository as ``Comfy-Org/Hunyuan-Video-1.5``; the former name
# ``Comfy-Org/HunyuanVideo_1.5_repackaged`` still resolves.  Revision read from the Hub API on 2026-11-25.
HUNYUAN15_REPO = "Comfy-Org/Hunyuan-Video-1.5"
HUNYUAN15_REVISION = "1405a2b738c29b890cf6d03fc038d8d3e92eeed7"
HUNYUAN15_UNET = "hunyuanvideo1.5_480p_i2v_step_distilled_fp8_scaled.safetensors"
HUNYUAN15_QWEN_ENCODER = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
HUNYUAN15_BYT5_ENCODER = "byt5_small_glyphxl_fp16.safetensors"
HUNYUAN15_VAE = "hunyuanvideo15_vae_fp16.safetensors"
HUNYUAN15_CLIP_VISION = "sigclip_vision_patch14_384.safetensors"
HUNYUAN15_CLIP_TYPE = "hunyuan_video_15"

# (dependency id, file name, loader input that must list the file, sha256 (the Hub's LFS object id), upstream repo,
# revision).  Files sit under ``split_files/<folder>/`` in the repository.
HUNYUAN15_MODEL_FILES = (
    (
        "hunyuan15_i2v_480p_step_distilled_unet",
        HUNYUAN15_UNET,
        "UNETLoader.unet_name",
        "302636263ad01e2659a18b78e96e95f44433b92def7cae1dab29b5105eeb63b1",
        HUNYUAN15_REPO,
        HUNYUAN15_REVISION,
    ),
    (
        "hunyuan15_qwen25_vl_7b_text_encoder",
        HUNYUAN15_QWEN_ENCODER,
        "DualCLIPLoader.clip_name1",
        "cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4",
        HUNYUAN15_REPO,
        HUNYUAN15_REVISION,
    ),
    (
        "hunyuan15_byt5_glyph_text_encoder",
        HUNYUAN15_BYT5_ENCODER,
        "DualCLIPLoader.clip_name2",
        "516910bb4c9b225370290e40585d1b0e6c8cd3583690f7eec2f7fb593990fb48",
        HUNYUAN15_REPO,
        HUNYUAN15_REVISION,
    ),
    (
        "hunyuan15_vae",
        HUNYUAN15_VAE,
        "VAELoader.vae_name",
        "e7c3091949c27e2d55ae6d5df917b99dadfebbf308e5a50d0ade0d16c90297ae",
        HUNYUAN15_REPO,
        HUNYUAN15_REVISION,
    ),
    (
        "hunyuan15_sigclip_vision",
        HUNYUAN15_CLIP_VISION,
        "CLIPVisionLoader.clip_name",
        "1fee501deabac72f0ed17610307d7131e3e9d1e838d0363aa3c2b97a6e03fb33",
        HUNYUAN15_REPO,
        HUNYUAN15_REVISION,
    ),
)
# Upstream file sizes in bytes (Hub metadata, same revision); recorded for download verification, never fetched here.
HUNYUAN15_FILE_BYTES = {
    HUNYUAN15_UNET: 8335127098,
    HUNYUAN15_QWEN_ENCODER: 9384670680,
    HUNYUAN15_BYT5_ENCODER: 438643184,
    HUNYUAN15_VAE: 2521292758,
    HUNYUAN15_CLIP_VISION: 856505640,
}
HUNYUAN15_STOCK_NODES = (
    "UNETLoader",
    "DualCLIPLoader",
    "VAELoader",
    "CLIPVisionLoader",
    "LoadImage",
    "CLIPVisionEncode",
    "CLIPTextEncode",
    "HunyuanVideo15ImageToVideo",
    "KSampler",
    "VAEDecode",
    "SaveImage",
)
HUNYUAN15_DEFAULT_NEGATIVE = "static, blurry, deformed hands, extra limbs, watermark, subtitles"
# 121 frames at 24 fps is 5.04 s, the same clip duration as A14B's 81 frames at 16 fps (5.06 s).  The latent
# compresses time by 4, so a legal length is 4n+1.  The maximum is the 121 frames the model card publishes.
HUNYUAN15_FRAME_COUNT_POLICY = {
    "default": 121,
    "minimum": 17,
    "maximum": 121,
    "step": 4,
    "offset": 1,
    "fps": 24,
}
# No launch flag is claimed beyond A14B's: the A14B qualification found pinned host memory unsafe on this host with
# two large experts.  Stage 0 measures whether this single-expert graph needs it; until then the same flag is required
# (it is the managed runtime's own launch policy), so the arms run in comparable processes.
HUNYUAN15_REQUIRED_LAUNCH_FLAGS = ("--disable-pinned-memory",)
HUNYUAN15_KEEP_WARM_SECONDS = 120
# Conservative starting floor from the published fit (12 GB VRAM) and the A14B precedent (8,600 MiB there, from a
# measured 8,176 MiB footprint): this graph's footprint is UNMEASURED, so the floor is set above A14B's.  Stage 0
# replaces it with a measured figure in a new version.  Host RAM is advisory only, as for A14B: ~17.8 GB of weights
# (8.3 GB model + 9.4 GB encoder) pass through a 32 GB host.
HUNYUAN15_RESOURCE_READINESS = {
    "policy": "hunyuan_video15_i2v_480p_step_distilled",
    "min_available_to_comfy_vram_mib": 9500,
    "min_available_ram_gb": 16.0,
}
# Hunyuan's latent grid is 16 px, so both edges must be multiples of 16.  848x480 is the node's own default (the
# model's native 480p 16:9 bucket); A14B runs 832x480, so Hunyuan carries 1.9 % more pixels per frame.  The plan records
# this difference rather than hiding it.
HUNYUAN15_PORTRAIT_TARGET = {"width": 480, "height": 848}
HUNYUAN15_LANDSCAPE_TARGET = {"width": 848, "height": 480}


def _prompt_template(steps: int) -> dict[str, Any]:
    def node(kind: str, **inputs: Any) -> dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    return {
        "1": node("UNETLoader", unet_name=HUNYUAN15_UNET, weight_dtype="default"),
        "2": node(
            "DualCLIPLoader",
            clip_name1=HUNYUAN15_QWEN_ENCODER,
            clip_name2=HUNYUAN15_BYT5_ENCODER,
            type=HUNYUAN15_CLIP_TYPE,
            device="default",
        ),
        "3": node("VAELoader", vae_name=HUNYUAN15_VAE),
        "4": node("CLIPVisionLoader", clip_name=HUNYUAN15_CLIP_VISION),
        "5": node("LoadImage", image="{{input.source_image}}"),
        "6": node("CLIPVisionEncode", clip_vision=["4", 0], image=["5", 0], crop="center"),
        "7": node("CLIPTextEncode", clip=["2", 0], text="{{input.prompt}}"),
        "8": node("CLIPTextEncode", clip=["2", 0], text="{{input.negative_prompt}}"),
        "9": node(
            "HunyuanVideo15ImageToVideo",
            positive=["7", 0],
            negative=["8", 0],
            vae=["3", 0],
            width="{{input.target_width}}",
            height="{{input.target_height}}",
            length="{{input.frame_count}}",
            batch_size=1,
            start_image=["5", 0],
            clip_vision_output=["6", 0],
        ),
        "10": node(
            "KSampler",
            model=["1", 0],
            seed="{{input.seed}}",
            steps=steps,
            cfg=1.0,
            sampler_name="euler",
            scheduler="simple",
            positive=["9", 0],
            negative=["9", 1],
            latent_image=["9", 2],
            denoise=1.0,
        ),
        "11": node("VAEDecode", samples=["10", 0], vae=["3", 0]),
        "12": node(
            "SaveImage",
            images=["11", 0],
            filename_prefix="stablenew/hunyuan15_{{request.job_id}}",
        ),
    }


def _dependency_specs() -> tuple[WorkflowDependencySpec, ...]:
    return (
        *(
            WorkflowDependencySpec(
                dependency_id=dependency_id,
                dependency_kind="model_file",
                locator=filename,
                version_hint=loader_input,
                description=f"{filename} (sha256 {digest[:16]}..., {repo}@{revision[:12]})",
            )
            for dependency_id, filename, loader_input, digest, repo, revision in (
                HUNYUAN15_MODEL_FILES
            )
        ),
        *(
            WorkflowDependencySpec(
                dependency_id=f"node_{node.lower()}",
                dependency_kind="stock_node",
                locator=node,
                description=f"Stock ComfyUI node {node}",
            )
            for node in HUNYUAN15_STOCK_NODES
        ),
        # A runtime without the HunyuanVideo 1.5 loader recipe, or whose image-to-video node lacks the vision input,
        # would reject or silently mis-condition the graph; refuse before dispatch instead.
        WorkflowDependencySpec(
            dependency_id="option_dualcliploader_hunyuan_video_15",
            dependency_kind="node_option",
            locator=HUNYUAN15_CLIP_TYPE,
            version_hint="DualCLIPLoader.type",
            description="DualCLIPLoader must offer the hunyuan_video_15 text-encoder recipe",
        ),
        WorkflowDependencySpec(
            dependency_id="input_hunyuanvideo15imagetovideo_clip_vision_output",
            dependency_kind="node_input",
            locator="clip_vision_output",
            version_hint="HunyuanVideo15ImageToVideo",
            description="HunyuanVideo15ImageToVideo must accept the SigCLIP vision output",
        ),
    )


_NOT_QUALIFIED = (
    "NOT QUALIFIED: offline catalog, graph and readiness tests only; nothing has run on the target host. The sampler "
    "values, the VRAM floor and the keep-warm grace are frozen from stock-node convention and published figures, not "
    "measured; the evaluation's stage 0 measures them and a change is a new version."
)


def build_hunyuan15_spec(workflow_id: str = HUNYUAN15_ID) -> WorkflowSpec:
    steps = HUNYUAN15_STEPS[workflow_id]
    version = HUNYUAN15_VERSION
    return WorkflowSpec(
        workflow_id=workflow_id,
        workflow_version=version,
        backend_id="comfy",
        display_name=f"HunyuanVideo 1.5 480p I2V {steps}-step (Experimental)",
        description=(
            "Experimental eval candidate: prompt-directed image-to-video with the HunyuanVideo 1.5 480p "
            f"step-distilled FP8 model, {steps} sampler steps, on stock ComfyUI nodes. One source image and a prompt; "
            "no anchors, control video or pose video. Native 24 fps, 121 frames (about 5 s). Offered only for an "
            "owner-rated side-by-side evaluation against the approved Wan2.2 I2V-A14B; the licence excludes the EU, "
            "the UK and South Korea."
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
                description="Negative prompt (a default is applied when empty; no effect at CFG 1).",
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
        dependency_specs=_dependency_specs(),
        governance_state=WORKFLOW_GOVERNANCE_EXPERIMENTAL,
        pinned_revision=f"catalog:{workflow_id}@{version}",
        governance_notes=(
            "EXPERIMENTAL, per-job opt-in only (VID-CAND-382). Never the Make Video default and never preselected. "
            + _NOT_QUALIFIED
            + " Runs only on a StableNew-managed ComfyUI launched with --disable-pinned-memory; the owned runtime is "
            "released after the keep-warm grace. Licence acceptance for this host and the model download are owner "
            "gates (the licence excludes the EU, the UK and South Korea). No LoRA control, no first/last-frame input. "
            "It differs from its sibling workflow id only in the sampler step count (8 or 12)."
        ),
        backend_defaults={
            "workflow_family": "hunyuan_video15_i2v",
            "transport": "local_comfy",
            "output_transport": "comfy_view",
            "default_negative_prompt": HUNYUAN15_DEFAULT_NEGATIVE,
            # A14B uses 1200 s (clips took 140-176 s wall); this graph's time is unmeasured, so the same ceiling
            # keeps headroom for a cold load of ~17.8 GB of weights without abandoning a clip Comfy still produces.
            "history_timeout_seconds": 1200,
            "make_video_default": False,
            "frame_count_policy": dict(HUNYUAN15_FRAME_COUNT_POLICY),
            "output_policy": {"mode": "frames", "fps": HUNYUAN15_FRAME_COUNT_POLICY["fps"]},
            "runtime_policy": {
                "release_owned_runtime_after_job": True,
                "keep_warm_between_jobs_seconds": HUNYUAN15_KEEP_WARM_SECONDS,
                "required_launch_flags": list(HUNYUAN15_REQUIRED_LAUNCH_FLAGS),
            },
            "provenance": {
                "qualification": (
                    "NOT QUALIFIED: VID-CAND-382 eval candidate; offline tests only, pending the "
                    "owner-authorized stages and ratings"
                ),
                "comfyui_version": "0.38.0",
                "comfyui_revision": "6b747c0428c343e1417219641db93a4fb7cb69ae",
                "upstream_repo": HUNYUAN15_REPO,
                "upstream_revision": HUNYUAN15_REVISION,
                "base_model": "tencent/HunyuanVideo-1.5",
                "license": (
                    "Tencent HunyuanVideo-1.5 community licence (HF license: other); excludes the EU, the UK and "
                    "South Korea; owner acceptance required for this host"
                ),
                "files": {
                    name: digest for _id, name, _hint, digest, _repo, _rev in HUNYUAN15_MODEL_FILES
                },
                "file_bytes": dict(HUNYUAN15_FILE_BYTES),
            },
            "resource_readiness": dict(HUNYUAN15_RESOURCE_READINESS),
            "source_preparation": {
                "resize_policy": "cover_resize_center_crop",
                "portrait_target": dict(HUNYUAN15_PORTRAIT_TARGET),
                "landscape_target": dict(HUNYUAN15_LANDSCAPE_TARGET),
                "square_orientation": "portrait",
            },
            "operator_projection": {
                "fixed_settings": {
                    "fps": 24,
                    "steps": f"{steps} (step-distilled)",
                    "cfg": 1,
                    "sampler": "euler",
                    "scheduler": "simple",
                    "shift": "model default 7.0 (no ModelSamplingSD3 node)",
                    "geometry": "source-aware: portrait 480x848; landscape 848x480; square uses portrait",
                    "workflow_identity": "stock ComfyUI HunyuanVideo 1.5 I2V, catalog-pinned",
                    "output": (
                        "lossless PNG frames from Comfy; StableNew encodes the clip (CRF 16, BT.709) "
                        "and can smooth it"
                    ),
                    "hardware": (
                        "NOT QUALIFIED; readiness floors are unmeasured starting values (RTX 4070 Ti 12 GB, "
                        "32 GB RAM host)"
                    ),
                },
            },
            "prompt_template": _prompt_template(steps),
        },
    )


def build_hunyuan15_specs() -> tuple[WorkflowSpec, ...]:
    return tuple(build_hunyuan15_spec(workflow_id) for workflow_id in HUNYUAN15_IDS)


__all__ = [
    "HUNYUAN15_12_STEP_ID",
    "HUNYUAN15_BYT5_ENCODER",
    "HUNYUAN15_FILE_BYTES",
    "HUNYUAN15_FRAME_COUNT_POLICY",
    "HUNYUAN15_ID",
    "HUNYUAN15_MODEL_FILES",
    "HUNYUAN15_REQUIRED_LAUNCH_FLAGS",
    "HUNYUAN15_RESOURCE_READINESS",
    "HUNYUAN15_STEPS",
    "HUNYUAN15_STOCK_NODES",
    "HUNYUAN15_VERSION",
    "HUNYUAN15_IDS",
    "build_hunyuan15_spec",
    "build_hunyuan15_specs",
]
