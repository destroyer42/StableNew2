"""LTX-2.5 22B distilled image-to-video: an EXPERIMENTAL eval candidate (VID-CAND-LTX25).

A stock-node graph on the managed ComfyUI 0.38.0, transcribed from that install's own official template
(``video_ltx2_5_i2v.json``): the Comfy int8 distilled transformer and Gemma 4 12B text encoder, the two-stage recipe
(8 steps at half size, the x2 latent spatial upscaler, 3 more steps at full size, ``euler_ancestral``, CFG 1) and a tiled
video decode.  The source image is already prepared to the full target size at admission, so the template's "scale longer
side to 1536" node is not needed.  The template's optional prompt enhancer (a second Gemma model) is left out.

Two workflow ids differ only in audio:

* **audio off** runs a video-only latent (the model treats a plain video latent as having no audio tokens) and ends in
  ``SaveImage``; StableNew encodes the lossless frames, like every other arm of the comparison;
* **audio on** concatenates an empty audio latent, decodes it with the audio VAE and ends in ``CreateVideo`` and
  ``SaveVideo``, because the frames-out path has no audio.  Comfy encodes that clip, so its picture is not comparable
  with frames-out clips.

Both are ``experimental``: they need the job's own recorded opt-in, are never the Make Video default and are never
preselected.  They are NOT QUALIFIED: nothing here has run on the target host.

Licence: the LTX-2.x Community License (11 Aug 2026) incorporates Lightricks' Acceptable Use Policy, which (updated
3 Nov 2026) forbids generating sexually explicit content.  The owner must read that and accept the gated Hugging Face
terms before any file is downloaded.  Nothing here downloads a file: the tuples below pin each one by name, size, digest
and ``repo@revision`` so a later download can be verified.
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

LTX25_ID = "ltx25_distilled_i2v_v1"
LTX25_AUDIO_ID = "ltx25_distilled_i2v_audio_v1"
LTX25_IDS = (LTX25_ID, LTX25_AUDIO_ID)
LTX25_VERSION = "1.0.0"

# Gated repository (the owner accepts its terms, never an agent); revision read from the Hub API on 2026-11-27.
LTX25_REPO = "Lightricks/LTX-2.5"
LTX25_REVISION = "69ecadd4932572caf956135d41cbcdbd697aa442"
LTX25_TRANSFORMER = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
LTX25_TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
LTX25_VIDEO_VAE = "ltx-2.5-video-vae-bf16.safetensors"
LTX25_AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"
LTX25_UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
LTX25_CLIP_TYPE = "ltxv"

# (dependency id, file name, loader input that must list the file, ComfyUI models folder, bytes, sha256).  Each file sits
# in the folder of the same name in the repository.  The Hub masks digests of a gated repository, so each sha256 was read
# from a public copy and confirmed against the official file's Git LFS pointer id (see the work package section 3).
LTX25_MODEL_FILES = (
    (
        "ltx25_distilled_transformer_int8",
        LTX25_TRANSFORMER,
        "UNETLoader.unet_name",
        "diffusion_models",
        21504034224,
        "c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334",
    ),
    (
        "ltx25_gemma4_12b_text_encoder_int8",
        LTX25_TEXT_ENCODER,
        "CLIPLoader.clip_name",
        "text_encoders",
        15372969374,
        "6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f",
    ),
    (
        "ltx25_video_vae",
        LTX25_VIDEO_VAE,
        "VAELoader.vae_name",
        "vae",
        1472223346,
        "847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3",
    ),
    (
        "ltx25_latent_spatial_upscaler_x2",
        LTX25_UPSCALER,
        "LatentUpscaleModelLoader.model_name",
        "latent_upscale_models",
        995778752,
        "eb5a71fe4068ee87ccdb1c3aa635e547ca76bd2d30ae20ae889f2c325c0677e8",
    ),
    (
        "ltx25_audio_vae",
        LTX25_AUDIO_VAE,
        "VAELoader.vae_name",
        "vae",
        364866540,
        "c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5",
    ),
)
_AUDIO_ONLY_FILES = (LTX25_AUDIO_VAE,)

_COMMON_NODES = (
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "LatentUpscaleModelLoader",
    "LoadImage",
    "LTXVPreprocess",
    "CLIPTextEncode",
    "LTXVConditioning",
    "ComfyMathExpression",
    "EmptyLTXVLatentVideo",
    "LTXVImgToVideoInplace",
    "RandomNoise",
    "KSamplerSelect",
    "ManualSigmas",
    "LTXVDualCFGGuider",
    "SamplerCustomAdvanced",
    "LTXVLatentUpsampler",
    "VAEDecodeTiled",
)
LTX25_STOCK_NODES = (*_COMMON_NODES, "SaveImage")
LTX25_AUDIO_STOCK_NODES = (
    *_COMMON_NODES,
    "LTXVEmptyLatentAudio",
    "LTXVConcatAVLatent",
    "LTXVSeparateAVLatent",
    "LTXVAudioVAEDecode",
    "CreateVideo",
    "SaveVideo",
)

# The template's distilled schedules and fixed second-stage noise seed, verbatim.
LTX25_STAGE1_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
LTX25_STAGE2_SIGMAS = "0.85, 0.7250, 0.4219, 0.0"
LTX25_STAGE2_SEED = 42
LTX25_STAGE1_IMAGE_STRENGTH = 0.7
LTX25_FPS = 24
LTX25_DEFAULT_NEGATIVE = "static, blurry, deformed hands, extra limbs, watermark, subtitles"
# 121 frames at 24 fps is 5.04 s, the clip duration of every arm of the comparison.  The latent compresses time by 8, so
# a legal length is 8n+1.  Longer clips (the model's selling point) are untested here and would be a new version.
LTX25_FRAME_COUNT_POLICY = {
    "default": 121,
    "minimum": 25,
    "maximum": 121,
    "step": 8,
    "offset": 1,
    "fps": LTX25_FPS,
}
# Full output size.  Stage 1 runs at half of it and the latent grid is 32 px, so both edges are multiples of 64.  0.571
# against A14B's 0.577 keeps nearly the same crop of a source; 1.03 MP is the model's natural size class, and its
# 32x/8x latent makes this fewer tokens than A14B's 480x832.  The plan records the pixel difference.
LTX25_PORTRAIT_TARGET = {"width": 768, "height": 1344}
LTX25_LANDSCAPE_TARGET = {"width": 1344, "height": 768}
LTX25_REQUIRED_LAUNCH_FLAGS = ("--disable-pinned-memory",)
LTX25_KEEP_WARM_SECONDS = 120
# UNMEASURED starting values: the 21.5 GB transformer cannot be resident on 12 GB and about 39 GB of weights pass
# through a 48 GB host.  Stage 0 replaces them in a new version.  Host RAM is advisory only, as for A14B.
LTX25_RESOURCE_READINESS = {
    "policy": "ltx25_distilled_i2v",
    "min_available_to_comfy_vram_mib": 9500,
    "min_available_ram_gb": 24.0,
}
# A cold load of ~39 GB of weights is unmeasured; A14B uses 1200 s.
LTX25_HISTORY_TIMEOUT_SECONDS = 2400
LTX25_LICENSE = (
    "LTX-2.x Community License (11 Aug 2026; free below USD 10M revenue) with Attachment A and the Lightricks "
    "Acceptable Use Policy (updated 3 Nov 2026), which forbids sexually explicit content; provenance marks must not "
    "be removed; owner acceptance of the gated terms required. Text encoder base: Gemma 4 12B (Apache-2.0)"
)


LTX25_LICENCE_WARNING = {
    "title": "LTX-2.5's licence forbids sexually explicit content.",
    "why": (
        "The LTX-2.x Community License incorporates Lightricks' Acceptable Use Policy (updated 3 Nov 2026), which "
        "forbids generating sexually explicit content with the model."
    ),
    "fix": "Use LTX-2.5 only for non-explicit clips; for anything else choose another engine.",
}


def _files(audio: bool) -> tuple[tuple[str, str, str, str, int, str], ...]:
    return tuple(row for row in LTX25_MODEL_FILES if audio or row[1] not in _AUDIO_ONLY_FILES)


def _prompt_template(audio: bool) -> dict[str, Any]:
    def node(kind: str, **inputs: Any) -> dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    graph = {
        "1": node("UNETLoader", unet_name=LTX25_TRANSFORMER, weight_dtype="default"),
        "2": node(
            "CLIPLoader", clip_name=LTX25_TEXT_ENCODER, type=LTX25_CLIP_TYPE, device="default"
        ),
        "3": node("VAELoader", vae_name=LTX25_VIDEO_VAE),
        "4": node("LatentUpscaleModelLoader", model_name=LTX25_UPSCALER),
        "5": node("LoadImage", image="{{input.source_image}}"),
        # The template's image "compression" preprocessing, which the model was trained to expect.
        "6": node("LTXVPreprocess", image=["5", 0], img_compression=18),
        "7": node("CLIPTextEncode", clip=["2", 0], text="{{input.prompt}}"),
        "8": node("CLIPTextEncode", clip=["2", 0], text="{{input.negative_prompt}}"),
        "9": node("LTXVConditioning", positive=["7", 0], negative=["8", 0], frame_rate=LTX25_FPS),
        # Stage 1 runs at half the frozen target; the expression's second output is the integer.
        "10": node(
            "ComfyMathExpression", expression="a/2", **{"values.a": "{{input.target_width}}"}
        ),
        "11": node(
            "ComfyMathExpression", expression="a/2", **{"values.a": "{{input.target_height}}"}
        ),
        "12": node(
            "EmptyLTXVLatentVideo",
            width=["10", 1],
            height=["11", 1],
            length="{{input.frame_count}}",
            batch_size=1,
        ),
        "13": node(
            "LTXVImgToVideoInplace",
            vae=["3", 0],
            image=["6", 0],
            latent=["12", 0],
            strength=LTX25_STAGE1_IMAGE_STRENGTH,
            bypass=False,
        ),
        "14": node("KSamplerSelect", sampler_name="euler_ancestral"),
        "15": node("ManualSigmas", sigmas=LTX25_STAGE1_SIGMAS),
        "16": node("RandomNoise", noise_seed="{{input.seed}}"),
        "17": node(
            "LTXVDualCFGGuider",
            model=["1", 0],
            positive=["9", 0],
            negative=["9", 1],
            video_cfg=1.0,
            audio_cfg=1.0,
        ),
        "18": node(
            "SamplerCustomAdvanced",
            noise=["16", 0],
            guider=["17", 0],
            sampler=["14", 0],
            sigmas=["15", 0],
            latent_image=["13", 0],
        ),
        "19": node("LTXVLatentUpsampler", samples=["18", 0], upscale_model=["4", 0], vae=["3", 0]),
        "20": node(
            "LTXVImgToVideoInplace",
            vae=["3", 0],
            image=["6", 0],
            latent=["19", 0],
            strength=1.0,
            bypass=False,
        ),
        "21": node("ManualSigmas", sigmas=LTX25_STAGE2_SIGMAS),
        "22": node("RandomNoise", noise_seed=LTX25_STAGE2_SEED),
        "23": node(
            "SamplerCustomAdvanced",
            noise=["22", 0],
            guider=["17", 0],
            sampler=["14", 0],
            sigmas=["21", 0],
            latent_image=["20", 0],
        ),
        "24": node(
            "VAEDecodeTiled",
            samples=["23", 0],
            vae=["3", 0],
            tile_size=512,
            overlap=64,
            temporal_size=64,
            temporal_overlap=16,
        ),
    }
    if not audio:
        graph["25"] = node(
            "SaveImage", images=["24", 0], filename_prefix="stablenew/ltx25_{{request.job_id}}"
        )
        return graph

    graph.update(
        {
            "30": node("VAELoader", vae_name=LTX25_AUDIO_VAE),
            "31": node(
                "LTXVEmptyLatentAudio",
                frames_number="{{input.frame_count}}",
                frame_rate=LTX25_FPS,
                batch_size=1,
                audio_vae=["30", 0],
            ),
            "32": node("LTXVConcatAVLatent", video_latent=["13", 0], audio_latent=["31", 0]),
            # Between the stages the audio latent is set aside while the video latent is upscaled.
            "33": node("LTXVSeparateAVLatent", av_latent=["18", 0]),
            "34": node("LTXVConcatAVLatent", video_latent=["20", 0], audio_latent=["33", 1]),
            "35": node("LTXVSeparateAVLatent", av_latent=["23", 0]),
            "36": node("LTXVAudioVAEDecode", samples=["35", 1], audio_vae=["30", 0]),
            "37": node("CreateVideo", images=["24", 0], audio=["36", 0], fps=float(LTX25_FPS)),
            "38": node(
                "SaveVideo",
                video=["37", 0],
                filename_prefix="stablenew/ltx25_{{request.job_id}}",
                format="auto",
                codec="auto",
            ),
        }
    )
    graph["18"]["inputs"]["latent_image"] = ["32", 0]
    graph["19"]["inputs"]["samples"] = ["33", 0]
    graph["23"]["inputs"]["latent_image"] = ["34", 0]
    graph["24"]["inputs"]["samples"] = ["35", 0]
    return graph


def _dependency_specs(audio: bool) -> tuple[WorkflowDependencySpec, ...]:
    nodes = LTX25_AUDIO_STOCK_NODES if audio else LTX25_STOCK_NODES
    return (
        *(
            WorkflowDependencySpec(
                dependency_id=dependency_id,
                dependency_kind="model_file",
                locator=filename,
                version_hint=loader_input,
                description=(
                    f"{filename} in Comfy models/{folder} (sha256 {digest[:16]}..., "
                    f"{LTX25_REPO}@{LTX25_REVISION[:12]})"
                ),
            )
            for dependency_id, filename, loader_input, folder, _size, digest in _files(audio)
        ),
        *(
            WorkflowDependencySpec(
                dependency_id=f"node_{node.lower()}",
                dependency_kind="stock_node",
                locator=node,
                description=f"Stock ComfyUI node {node}",
            )
            for node in nodes
        ),
        WorkflowDependencySpec(
            dependency_id="option_cliploader_ltxv",
            dependency_kind="node_option",
            locator=LTX25_CLIP_TYPE,
            version_hint="CLIPLoader.type",
            description="CLIPLoader must offer the ltxv text-encoder recipe",
        ),
    )


_NOT_QUALIFIED = (
    "NOT QUALIFIED: offline catalog, graph and readiness tests only; nothing has run on the target host. The graph "
    "follows the runtime's official template; the size, the VRAM floor and the keep-warm grace are not measured; the "
    "evaluation's stage 0 measures them and a change is a new version."
)


def build_ltx25_spec(workflow_id: str = LTX25_ID) -> WorkflowSpec:
    audio = {LTX25_ID: False, LTX25_AUDIO_ID: True}[workflow_id]
    version = LTX25_VERSION
    output_text = (
        "Video with generated audio, encoded by ComfyUI"
        if audio
        else "Silent video; StableNew encodes the lossless frames"
    )
    backend_defaults: dict[str, Any] = {
        "workflow_family": "ltx25_distilled_i2v",
        "transport": "local_comfy",
        "output_transport": "comfy_view",
        "default_negative_prompt": LTX25_DEFAULT_NEGATIVE,
        "history_timeout_seconds": LTX25_HISTORY_TIMEOUT_SECONDS,
        "make_video_default": False,
        "frame_count_policy": dict(LTX25_FRAME_COUNT_POLICY),
        "runtime_policy": {
            "release_owned_runtime_after_job": True,
            "keep_warm_between_jobs_seconds": LTX25_KEEP_WARM_SECONDS,
            "required_launch_flags": list(LTX25_REQUIRED_LAUNCH_FLAGS),
        },
        "provenance": {
            "qualification": (
                "NOT QUALIFIED: VID-CAND-LTX25 eval candidate; offline tests only, pending the "
                "owner-authorized stages and ratings"
            ),
            "comfyui_version": "0.38.0",
            "comfyui_revision": "6b747c0428c343e1417219641db93a4fb7cb69ae",
            "upstream_repo": LTX25_REPO,
            "upstream_revision": LTX25_REVISION,
            "base_model": "Lightricks/LTX-2.5 (22B distilled)",
            "license": LTX25_LICENSE,
            "files": {row[1]: row[5] for row in _files(audio)},
            "file_bytes": {row[1]: row[4] for row in _files(audio)},
        },
        "resource_readiness": dict(LTX25_RESOURCE_READINESS),
        # Shown beside Queue and recorded on the job (src/video/workflow_warnings.py); a warning, never a block.
        "licence_warning": dict(LTX25_LICENCE_WARNING),
        "source_preparation": {
            "resize_policy": "cover_resize_center_crop",
            "portrait_target": dict(LTX25_PORTRAIT_TARGET),
            "landscape_target": dict(LTX25_LANDSCAPE_TARGET),
            "square_orientation": "portrait",
        },
        "operator_projection": {
            "fixed_settings": {
                "fps": LTX25_FPS,
                "steps": "8 at half size, then 3 at full size (distilled)",
                "cfg": 1,
                "sampler": "euler_ancestral",
                "scheduler": "the template's fixed sigma lists",
                "geometry": "source-aware: portrait 768x1344; landscape 1344x768; square uses portrait",
                "workflow_identity": "ComfyUI 0.38.0 official LTX-2.5 I2V template, catalog-pinned",
                "output": output_text,
                "audio": (
                    "generated with the video; Smooth motion would publish a silent clip, leave it off"
                    if audio
                    else "none"
                ),
                "licence": "no sexually explicit content (Lightricks Acceptable Use Policy)",
                "hardware": "NOT QUALIFIED; readiness floors are unmeasured (RTX 4070 Ti 12 GB, 48 GB RAM host)",
            },
        },
        "prompt_template": _prompt_template(audio),
    }
    if not audio:
        backend_defaults["output_policy"] = {"mode": "frames", "fps": LTX25_FPS}

    return WorkflowSpec(
        workflow_id=workflow_id,
        workflow_version=version,
        backend_id="comfy",
        display_name=(
            "LTX-2.5 distilled I2V with audio (Experimental)"
            if audio
            else "LTX-2.5 distilled I2V (Experimental)"
        ),
        description=(
            "Experimental eval candidate: prompt-directed image-to-video with the LTX-2.5 22B distilled model "
            f"(int8) on stock ComfyUI nodes, two stages (8 + 3 steps). {output_text}. One source image and a "
            "prompt; 24 fps, 121 frames (about 5 s). Offered only for an owner-rated evaluation against Wan2.2 "
            "I2V-A14B and HunyuanVideo 1.5. The licence forbids sexually explicit content."
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
                description="Prompt describing the motion (and sound, in the audio workflow); required.",
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
                description="First-stage noise seed recorded in the immutable job (the second stage's is fixed).",
            ),
            WorkflowInputBinding(
                binding_name="target_width",
                source_field="stage_config.source_preparation.target_dimensions.width",
                backend_key="target_width",
                description="Frozen source-aware output width selected before queue admission.",
            ),
            WorkflowInputBinding(
                binding_name="target_height",
                source_field="stage_config.source_preparation.target_dimensions.height",
                backend_key="target_height",
                description="Frozen source-aware output height selected before queue admission.",
            ),
            WorkflowInputBinding(
                binding_name="frame_count",
                source_field="stage_config.frame_count",
                backend_key="frame_count",
                description="Generated frame count, frozen at admission (a legal 8n+1 length).",
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
        dependency_specs=_dependency_specs(audio),
        governance_state=WORKFLOW_GOVERNANCE_EXPERIMENTAL,
        pinned_revision=f"catalog:{workflow_id}@{version}",
        governance_notes=(
            "EXPERIMENTAL, per-job opt-in only (VID-CAND-LTX25). Never the Make Video default and never preselected. "
            + _NOT_QUALIFIED
            + " Runs only on a StableNew-managed ComfyUI launched with --disable-pinned-memory; the owned runtime is "
            "released after the keep-warm grace. The licence incorporates an acceptable use policy that forbids "
            "sexually explicit content; accepting the gated terms and downloading the files are owner gates. No LoRA "
            "control, no end frame, no prompt enhancer. It differs from its sibling workflow id only in audio."
        ),
        backend_defaults=backend_defaults,
    )


def build_ltx25_specs() -> tuple[WorkflowSpec, ...]:
    return tuple(build_ltx25_spec(workflow_id) for workflow_id in LTX25_IDS)


__all__ = [
    "LTX25_AUDIO_ID",
    "LTX25_AUDIO_STOCK_NODES",
    "LTX25_FRAME_COUNT_POLICY",
    "LTX25_ID",
    "LTX25_IDS",
    "LTX25_LICENSE",
    "LTX25_MODEL_FILES",
    "LTX25_REPO",
    "LTX25_REVISION",
    "LTX25_STOCK_NODES",
    "LTX25_VERSION",
    "build_ltx25_spec",
    "build_ltx25_specs",
]
