"""Experimental Wan2.2 I2V-A14B + SVI 2.0 workflow for multi-segment sequences (VID-A14B-SVI-375).

Stable Video Infinity 2.0 (epfl-vita, MIT) ships one LoRA per A14B expert that teaches the model to continue a clip
from a carried frame without drifting away from the subject.  Its stock-ComfyUI recipe (the WAN-BENCH-373 SVI rerun,
``C:/Users/rob/qual/bench373/svi-rerun/plan.json``; upstream ``vita-epfl/Stable-Video-Infinity`` branch ``svi_wan22``
``docs/svi/comfyui.md``) is the approved A14B 4-step graph with three changes:

* each expert loads its lightx2v 4-step LoRA (high-noise strength **0.5**, low-noise **1.0**) and then its SVI LoRA
  (strength 1.0) before ``ModelSamplingSD3``;
* ``WanImageToVideo`` receives ``ref_pad_image``: the padding frames of the image conditioning are filled with the
  sequence's *first* source image instead of grey.  The start image of a later segment is still the carried last frame;
  the reference pad stays segment 0's prepared source in every segment, which is what anchors identity;
* both ``KSamplerAdvanced`` passes run at CFG **1.5** (the negative prompt now has an effect).

The reference pad binds ``stage_config.source_preparation.prepared_image_path``.  The NJR builder freezes that block
once, for segment 0's source, and the sequence executor overrides only seed, length, workflow identity and prompts, so
every segment of one job (and a single clip) pads with the same prepared source image.  When the job is a sequence the
backend checks the file against the plan's recorded SHA-256 before it uploads it.

Three versions of one workflow id select the adapter source and CFG (an operator control would not be carried by a
sequence, and each version pins exactly the files it loads):

* **1.0.0** our derived copies of the official bf16 SVI LoRAs (only the ``diffusion_model.`` key prefix added, tensor
  bytes unchanged), CFG 1.5;
* **1.1.0** Kijai's fp16 repacks of the same LoRAs (``Kijai/WanVideo_comfy``), CFG 1.5;
* **1.2.0** the derived copies at CFG 1.0 (the approved graph's CFG).

All three are EXPERIMENTAL and need the job's own opt-in.  They are never the picker entry or the Make Video default and
share the approved 1.0.0's frame policy, ``--disable-pinned-memory`` launch requirement, keep-warm grace, source
preparation, timeout and readiness floors (unmeasured for SVI).  Nothing downloads the adapters; a missing file is a
dependency the readiness probe and preflight refuse.  SVI Pro (custom nodes) is out of scope.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_DEFAULT_NEGATIVE,
    WAN_A14B_HIGH_LORA,
    WAN_A14B_HIGH_UNET,
    WAN_A14B_LOW_LORA,
    WAN_A14B_LOW_UNET,
    WAN_A14B_MODEL_FILES,
    WAN_A14B_STOCK_NODES,
    WAN_A14B_TEXT_ENCODER,
    WAN_A14B_VAE,
    build_wan_a14b_spec,
)
from src.video.workflow_contracts import (
    WORKFLOW_GOVERNANCE_EXPERIMENTAL,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowSpec,
)

WAN_A14B_SVI_ID = "wan22_i2v_a14b_svi"
WAN_A14B_SVI_VERSION = "1.0.0"
WAN_A14B_SVI_KIJAI_VERSION = "1.1.0"
WAN_A14B_SVI_CFG1_VERSION = "1.2.0"
WAN_A14B_SVI_VERSIONS = (
    WAN_A14B_SVI_VERSION,
    WAN_A14B_SVI_KIJAI_VERSION,
    WAN_A14B_SVI_CFG1_VERSION,
)

WAN_A14B_SVI_DEFAULT_CFG = 1.5
WAN_A14B_SVI_LIGHTX2V_HIGH_STRENGTH = 0.5
WAN_A14B_SVI_LIGHTX2V_LOW_STRENGTH = 1.0
WAN_A14B_SVI_STRENGTH = 1.0
# The stock node input that takes the reference pad (ComfyUI 0.38.0 comfy_extras/nodes_wan.py: an optional IMAGE,
# resized to the target size; older builds do not have it and would reject the prompt).
WAN_A14B_SVI_REF_PAD_NODE = "WanImageToVideo"
WAN_A14B_SVI_REF_PAD_INPUT = "ref_pad_image"
WAN_A14B_SVI_REF_PAD_SOURCE = "stage_config.source_preparation.prepared_image_path"

ADAPTER_DERIVED = "derived_bf16"
ADAPTER_KIJAI = "kijai_fp16"

WAN_A14B_SVI_OFFICIAL_REPO = "epfl-vita/svi-model"
WAN_A14B_SVI_OFFICIAL_REVISION = "f9bdd50c57e4c28f0d088b6bad8afa3fdc3bc1ac"
WAN_A14B_SVI_KIJAI_REPO = "Kijai/WanVideo_comfy"
WAN_A14B_SVI_KIJAI_REVISION = "8260d429d19fd7a72304cad059160b95d843913f"

# (dependency id, file name, loader input, sha256, upstream repo, revision) per adapter source; high-noise first.
# Derived: the official bf16 files with every key prefixed ``diffusion_model.`` (stock ComfyUI cannot match the
# unprefixed keys); built by bench373 svi-rerun/build_svi_comfy.py, deterministic, recorded in each file's
# ``.provenance.json`` sidecar.  The official originals are recorded in provenance only: they never load.
WAN_A14B_SVI_ADAPTER_FILES: dict[str, tuple[tuple[str, str, str, str, str, str], ...]] = {
    ADAPTER_DERIVED: (
        (
            "wan_a14b_svi_high_noise_lora_derived",
            "SVI_Wan2.2-I2V-A14B_high_noise_lora_v2.0.comfy.safetensors",
            "LoraLoaderModelOnly.lora_name",
            "0367ad1b466e22e8c5bb44a358af3cd238c5976d90cc784e4b8795c22cd99ef6",
            WAN_A14B_SVI_OFFICIAL_REPO,
            WAN_A14B_SVI_OFFICIAL_REVISION,
        ),
        (
            "wan_a14b_svi_low_noise_lora_derived",
            "SVI_Wan2.2-I2V-A14B_low_noise_lora_v2.0.comfy.safetensors",
            "LoraLoaderModelOnly.lora_name",
            "9380636b55e5ca6cf6cd6a155c454d52c5f4f442fc1de3e15da70f7b5e0a17f2",
            WAN_A14B_SVI_OFFICIAL_REPO,
            WAN_A14B_SVI_OFFICIAL_REVISION,
        ),
    ),
    ADAPTER_KIJAI: (
        (
            "wan_a14b_svi_high_noise_lora_kijai",
            "SVI_Wan2.2-I2V-A14B_lora_HIGH_v2.0_rank_128_fp16.safetensors",
            "LoraLoaderModelOnly.lora_name",
            "dc45a5b33282793c9eadef218167ea046684bef3cf2a593b205f06603375573c",
            WAN_A14B_SVI_KIJAI_REPO,
            WAN_A14B_SVI_KIJAI_REVISION,
        ),
        (
            "wan_a14b_svi_low_noise_lora_kijai",
            "SVI_Wan2.2-I2V-A14B_lora_LOW_v2.0_rank_128_fp16.safetensors",
            "LoraLoaderModelOnly.lora_name",
            "403f0ad00fe692eea749c4211ed9db191c17c1059aa759b83557e18f08fe097b",
            WAN_A14B_SVI_KIJAI_REPO,
            WAN_A14B_SVI_KIJAI_REVISION,
        ),
    ),
}
WAN_A14B_SVI_ADAPTER_BYTES = {
    "SVI_Wan2.2-I2V-A14B_high_noise_lora_v2.0.comfy.safetensors": 1226941352,
    "SVI_Wan2.2-I2V-A14B_low_noise_lora_v2.0.comfy.safetensors": 1226941352,
    "SVI_Wan2.2-I2V-A14B_lora_HIGH_v2.0_rank_128_fp16.safetensors": 1226934120,
    "SVI_Wan2.2-I2V-A14B_lora_LOW_v2.0_rank_128_fp16.safetensors": 1226934120,
}
# The official epfl-vita originals the derived copies were built from (never loaded; provenance only).
WAN_A14B_SVI_OFFICIAL_ORIGINALS = {
    "SVI_Wan2.2-I2V-A14B_high_noise_lora_v2.0.safetensors": (
        "8e8d8ed323dca40439a5ff3829432008320de13ab6896b83c36d0eaa00783aef"
    ),
    "SVI_Wan2.2-I2V-A14B_low_noise_lora_v2.0.safetensors": (
        "febf40f1e1a6696e8551165eb72808f37e8f3ec59031280afce5740a580aca8b"
    ),
}

_ADAPTER_LABELS = {
    ADAPTER_DERIVED: "derived bf16 SVI 2.0 LoRAs (official epfl-vita tensors, diffusion_model. key prefix added)",
    ADAPTER_KIJAI: "Kijai's fp16 repack of the SVI 2.0 LoRAs (every tensor converted from bf16)",
}
_VERSIONS: dict[str, tuple[str, float, str]] = {
    # version: (adapter source, CFG, display label)
    WAN_A14B_SVI_VERSION: (ADAPTER_DERIVED, WAN_A14B_SVI_DEFAULT_CFG, "derived bf16, CFG 1.5"),
    WAN_A14B_SVI_KIJAI_VERSION: (ADAPTER_KIJAI, WAN_A14B_SVI_DEFAULT_CFG, "Kijai fp16, CFG 1.5"),
    WAN_A14B_SVI_CFG1_VERSION: (ADAPTER_DERIVED, 1.0, "derived bf16, CFG 1.0"),
}


def svi_prompt_template(
    *, adapter: str = ADAPTER_DERIVED, cfg: float = WAN_A14B_SVI_DEFAULT_CFG
) -> dict[str, Any]:
    """The WAN-BENCH-373 SVI graph with StableNew's templated inputs; node ids follow the bench graph."""

    (_hid, high_svi, *_h), (_lid, low_svi, *_l) = WAN_A14B_SVI_ADAPTER_FILES[adapter]

    def node(kind: str, **inputs: Any) -> dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    sampler = {
        "steps": 4,
        "cfg": cfg,
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
            strength_model=WAN_A14B_SVI_LIGHTX2V_HIGH_STRENGTH,
        ),
        "4": node(
            "LoraLoaderModelOnly",
            model=["2", 0],
            lora_name=WAN_A14B_LOW_LORA,
            strength_model=WAN_A14B_SVI_LIGHTX2V_LOW_STRENGTH,
        ),
        "5": node("ModelSamplingSD3", model=["20", 0], shift=5.0),
        "6": node("ModelSamplingSD3", model=["21", 0], shift=5.0),
        "7": node("CLIPLoader", clip_name=WAN_A14B_TEXT_ENCODER, type="wan", device="cpu"),
        "8": node("VAELoader", vae_name=WAN_A14B_VAE),
        "9": node("LoadImage", image="{{input.source_image}}"),
        "10": node(
            WAN_A14B_SVI_REF_PAD_NODE,
            positive=["11", 0],
            negative=["12", 0],
            vae=["8", 0],
            width="{{input.target_width}}",
            height="{{input.target_height}}",
            length="{{input.frame_count}}",
            batch_size=1,
            start_image=["9", 0],
            ref_pad_image=["17", 0],
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
            filename_prefix="stablenew/wan_a14b_svi_{{request.job_id}}",
        ),
        "17": node("LoadImage", image="{{input.ref_pad_image}}"),
        "20": node(
            "LoraLoaderModelOnly",
            model=["3", 0],
            lora_name=high_svi,
            strength_model=WAN_A14B_SVI_STRENGTH,
        ),
        "21": node(
            "LoraLoaderModelOnly",
            model=["4", 0],
            lora_name=low_svi,
            strength_model=WAN_A14B_SVI_STRENGTH,
        ),
    }


def _model_files(adapter: str) -> tuple[tuple[str, str, str, str, str, str], ...]:
    return (*WAN_A14B_MODEL_FILES, *WAN_A14B_SVI_ADAPTER_FILES[adapter])


def _dependency_specs(adapter: str) -> tuple[WorkflowDependencySpec, ...]:
    return (
        *(
            WorkflowDependencySpec(
                dependency_id=dependency_id,
                dependency_kind="model_file",
                locator=filename,
                version_hint=loader_input,
                description=f"{filename} (sha256 {digest[:16]}..., {repo}@{revision[:12]})",
            )
            for dependency_id, filename, loader_input, digest, repo, revision in _model_files(
                adapter
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
        WorkflowDependencySpec(
            dependency_id="input_wanimagetovideo_ref_pad_image",
            dependency_kind="node_input",
            locator=WAN_A14B_SVI_REF_PAD_INPUT,
            version_hint=WAN_A14B_SVI_REF_PAD_NODE,
            description=(
                f"{WAN_A14B_SVI_REF_PAD_NODE} must accept the optional '{WAN_A14B_SVI_REF_PAD_INPUT}' input "
                "(ComfyUI 0.38.0 has it; an older build would reject the SVI prompt)"
            ),
        ),
    )


_REF_PAD_BINDING = WorkflowInputBinding(
    binding_name=WAN_A14B_SVI_REF_PAD_INPUT,
    source_field=WAN_A14B_SVI_REF_PAD_SOURCE,
    backend_key=WAN_A14B_SVI_REF_PAD_INPUT,
    description=(
        "Reference pad: segment 0's prepared source image, frozen once per job, so every segment pads its image "
        "conditioning with the sequence's first image (SVI anti-drift padding)."
    ),
)


def build_wan_a14b_svi_spec(version: str = WAN_A14B_SVI_VERSION) -> WorkflowSpec:
    adapter, cfg, label = _VERSIONS[version]
    base = build_wan_a14b_spec()
    defaults = deepcopy(base.backend_defaults)
    defaults["workflow_family"] = "wan22_i2v_a14b_svi"
    defaults["make_video_default"] = False
    defaults["prompt_template"] = svi_prompt_template(adapter=adapter, cfg=cfg)
    defaults["default_negative_prompt"] = WAN_A14B_DEFAULT_NEGATIVE
    provenance = defaults["provenance"]
    provenance["qualification"] = (
        "NOT QUALIFIED: VID-A14B-SVI-375 experimental SVI 2.0 graph (WAN-BENCH-373 SVI rerun recipe, exploratory); "
        "offline tests only, pending the owner-rated sequence eval"
    )
    files = WAN_A14B_SVI_ADAPTER_FILES[adapter]
    provenance.update(
        svi_adapter=adapter,
        svi_repo=files[0][4],
        svi_revision=files[0][5],
        svi_license="MIT"
        if adapter == ADAPTER_DERIVED
        else "MIT upstream; the repack's repository states none",
        svi_adapter_bytes={name: WAN_A14B_SVI_ADAPTER_BYTES[name] for _i, name, *_rest in files},
        files={name: digest for _i, name, _h, digest, _r, _v in _model_files(adapter)},
    )
    if adapter == ADAPTER_DERIVED:
        provenance["svi_official_originals"] = dict(WAN_A14B_SVI_OFFICIAL_ORIGINALS)
        provenance["svi_transform"] = (
            "every tensor key prefixed 'diffusion_model.'; tensor bytes unchanged"
        )
    fixed = defaults["operator_projection"]["fixed_settings"]
    fixed.update(
        cfg=cfg,
        lora=(
            f"lightx2v 4-step at {WAN_A14B_SVI_LIGHTX2V_HIGH_STRENGTH} (high) / "
            f"{WAN_A14B_SVI_LIGHTX2V_LOW_STRENGTH} (low), then SVI 2.0 at {WAN_A14B_SVI_STRENGTH} on each expert"
        ),
        svi_adapter=_ADAPTER_LABELS[adapter],
        reference_pad="segment 0's prepared source image fills the conditioning padding in every segment",
        workflow_identity="stock ComfyUI Wan2.2 I2V-A14B two-expert + SVI 2.0, catalog-pinned",
        hardware="NOT QUALIFIED; readiness floors are the approved A14B 1.0.0's (321F) and unmeasured with SVI",
    )
    return WorkflowSpec(
        workflow_id=WAN_A14B_SVI_ID,
        workflow_version=version,
        backend_id=base.backend_id,
        display_name=f"Wan2.2 I2V-A14B SVI 2.0 {label} (Experimental)",
        description=(
            "Experimental Wan2.2 I2V-A14B 4-step with the Stable Video Infinity 2.0 LoRAs, made for multi-shot "
            "sequences: every segment pads its image conditioning with the sequence's first source image to hold "
            f"identity across carried segments. {_ADAPTER_LABELS[adapter].capitalize()}; CFG {cfg:g}. Stock ComfyUI "
            "nodes, native 16 fps, offered for an owner-rated sequence evaluation."
        ),
        capability_tags=base.capability_tags,
        input_bindings=(*base.input_bindings, _REF_PAD_BINDING),
        output_bindings=base.output_bindings,
        dependency_specs=_dependency_specs(adapter),
        governance_state=WORKFLOW_GOVERNANCE_EXPERIMENTAL,
        pinned_revision=f"catalog:{WAN_A14B_SVI_ID}@{version}",
        governance_notes=(
            "EXPERIMENTAL, per-job opt-in only (VID-A14B-SVI-375). The approved A14B 4-step graph with the SVI 2.0 "
            f"recipe: lightx2v {WAN_A14B_SVI_LIGHTX2V_HIGH_STRENGTH}/{WAN_A14B_SVI_LIGHTX2V_LOW_STRENGTH}, SVI LoRA "
            f"{WAN_A14B_SVI_STRENGTH} per expert ({_ADAPTER_LABELS[adapter]}), CFG {cfg:g}, and a ref_pad_image bound "
            "to segment 0's prepared source. Same frame policy, keep-warm grace, --disable-pinned-memory launch "
            "requirement, source preparation, history timeout and readiness floors as the approved A14B 1.0.0; the "
            "floors are not measured with SVI. NOT QUALIFIED: offline catalog, graph and readiness tests only, no "
            "physical run through StableNew (WAN-BENCH-373 ran the recipe once, exploratory). Never the picker entry "
            "or the Make Video default."
        ),
        backend_defaults=defaults,
    )


def build_wan_a14b_svi_specs() -> tuple[WorkflowSpec, ...]:
    """The three experimental SVI versions, in version order."""

    return tuple(build_wan_a14b_svi_spec(version) for version in WAN_A14B_SVI_VERSIONS)


__all__ = [
    "ADAPTER_DERIVED",
    "ADAPTER_KIJAI",
    "WAN_A14B_SVI_ADAPTER_BYTES",
    "WAN_A14B_SVI_ADAPTER_FILES",
    "WAN_A14B_SVI_CFG1_VERSION",
    "WAN_A14B_SVI_DEFAULT_CFG",
    "WAN_A14B_SVI_ID",
    "WAN_A14B_SVI_KIJAI_VERSION",
    "WAN_A14B_SVI_OFFICIAL_ORIGINALS",
    "WAN_A14B_SVI_REF_PAD_INPUT",
    "WAN_A14B_SVI_REF_PAD_NODE",
    "WAN_A14B_SVI_REF_PAD_SOURCE",
    "WAN_A14B_SVI_VERSION",
    "WAN_A14B_SVI_VERSIONS",
    "build_wan_a14b_svi_spec",
    "build_wan_a14b_svi_specs",
    "svi_prompt_template",
]
