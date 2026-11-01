"""Pinned stock-node Fun Control graph; no installation or physical qualification."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

from src.video.workflow_contracts import (
    WORKFLOW_CAP_POSE_VIDEO,
    WORKFLOW_GOVERNANCE_EXPERIMENTAL,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowSpec,
)

FUN_ID = "wan22_fun_control_5b_canny_i2v_v1"
FUN_REVISION = "7c2bf7cd56b55e483b78e02fd513ec8b774f7643"
FUN_MODEL = "wan2.2_fun_control_5B_bf16.safetensors"
# Published LFS metadata at FUN_REVISION. Encoder/VAE bytes match the TI2V catalog.
FUN_ASSETS = {
    FUN_MODEL: {
        "folder": "diffusion_models",
        "size": 10003303280,
        "sha256": "ace4718a7c87ee3e5606a68ab79142c4395e81aece76b8120bc886f0fbbe1d16",
    },
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors": {
        "folder": "text_encoders",
        "size": 6735906897,
        "sha256": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    },
    "wan2.2_vae.safetensors": {
        "folder": "vae",
        "size": 1409400960,
        "sha256": "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
    },
}


def build_fun_control_spec(frames_base: WorkflowSpec) -> WorkflowSpec:
    """Reuse existing frames-out/source policies without changing any published TI2V spec."""
    defaults = deepcopy(frames_base.backend_defaults)
    graph = defaults["prompt_template"]
    graph["1"]["inputs"]["unet_name"] = FUN_MODEL
    graph["8"] = {
        "class_type": "Wan22FunControlToVideo",
        "inputs": {
            "positive": ["5", 0],
            "negative": ["6", 0],
            "vae": ["3", 0],
            "width": "{{input.target_width}}",
            "height": "{{input.target_height}}",
            "length": "{{input.frame_count}}",
            "batch_size": 1,
            "ref_image": ["7", 0],
            "control_video": ["14", 0],
        },
    }
    graph["9"]["inputs"].update(positive=["8", 0], negative=["8", 1], latent_image=["8", 2])
    graph["11"]["inputs"]["filename_prefix"] = "stablenew/fun_control_{{request.job_id}}"
    graph.update(
        {
            "12": {"class_type": "LoadVideo", "inputs": {"file": "{{input.pose_video}}"}},
            "13": {"class_type": "GetVideoComponents", "inputs": {"video": ["12", 0]}},
            "14": {
                "class_type": "Canny",
                "inputs": {
                    "image": ["13", 0],
                    "low_threshold": 0.1,
                    "high_threshold": 0.6,
                },
            },
        }
    )
    defaults["frame_count_policy"]["maximum"] = 49
    defaults["resource_readiness"] = {
        "policy": "wan22_fun_control_5b",
        "qualification_status": "not_qualified",
        "reason": "Fun Control 5B host RAM, allocation headroom and GPU feasibility are NOT QUALIFIED. "
        "A separately authorized physical qualification and resource policy are required before queueing.",
    }
    defaults["runtime_policy"]["required_launch_flags"] = [
        "--disable-pinned-memory",
        "--disable-auto-launch",
    ]
    defaults["motion_source_policy"] = {"exact_prepared_frames": True}
    defaults["asset_integrity"] = {
        "repository": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
        "revision": FUN_REVISION,
        "files": deepcopy(FUN_ASSETS),
    }
    defaults["provenance"].update(
        qualification="NOT QUALIFIED; offline stock-node verification only (VID-FUN-352)",
        upstream_revision=FUN_REVISION,
        files={name: asset["sha256"] for name, asset in FUN_ASSETS.items()},
        template_blob="9bfbbc6fcd0a000bff39a186679c8453697aa7f2",
        qualified_graph_sha256=hashlib.sha256(
            json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        license_source="https://huggingface.co/alibaba-pai/Wan2.2-Fun-5B-Control/blob/"
        "03b7b533ee2580530b0a6d598cab6191e96c09f9/README_en.md",
    )
    defaults["operator_projection"]["fixed_settings"].update(
        workflow_identity="Wan2.2 Fun Control 5B; reference appearance + driving-video Canny",
        canny="low 0.1 / high 0.6 (fixed)",
        model=FUN_MODEL,
        hardware="NOT QUALIFIED",
        reference="appearance guidance; no exact first-frame guarantee",
        driving="Prepare Motion Source at 24 FPS; exact accepted frames only",
    )
    defaults["operator_projection"]["admission_block_reason"] = defaults["resource_readiness"][
        "reason"
    ]
    nodes = sorted({node["class_type"] for node in graph.values()})
    return replace(
        frames_base,
        workflow_id=FUN_ID,
        workflow_version="1.0.0",
        display_name="Wan2.2 Fun Control 5B Canny I2V (Experimental)",
        description="Uses the reference image to guide appearance and a driving video's Canny edges "
        "to guide movement. Requires a compatible local model and explicit experimental opt-in. "
        "Identity preservation is not guaranteed. Hardware feasibility is NOT QUALIFIED.",
        capability_tags=(*frames_base.capability_tags, WORKFLOW_CAP_POSE_VIDEO),
        input_bindings=(
            *frames_base.input_bindings,
            WorkflowInputBinding(
                "pose_video",
                "stage_config.pose_video_path",
                "pose_video",
                description="Driving / Control Video: ordered frames become Canny source material, not a pose map.",
            ),
        ),
        dependency_specs=(
            WorkflowDependencySpec(
                "fun_control_unet",
                "model_file",
                FUN_MODEL,
                version_hint="UNETLoader.unet_name",
                description=f"{FUN_MODEL} (sha256 {FUN_ASSETS[FUN_MODEL]['sha256']})",
            ),
            *(
                d
                for d in frames_base.dependency_specs
                if d.dependency_id in {"wan22_text_encoder", "wan22_vae"}
            ),
            *(WorkflowDependencySpec(f"node_{node.lower()}", "stock_node", node) for node in nodes),
        ),
        backend_defaults=defaults,
        governance_state=WORKFLOW_GOVERNANCE_EXPERIMENTAL,
        pinned_revision=f"catalog:{FUN_ID}@1.0.0",
        governance_notes="EXPERIMENTAL, per-job opt-in only. Physical execution and visual quality "
        "are NOT QUALIFIED. No exact start/end anchor or identity guarantee; no automatic downloads.",
    )
