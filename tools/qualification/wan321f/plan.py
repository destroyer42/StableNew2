"""Frozen candidate, not a catalog entry or physical-execution command.

Asset provenance comes from the accepted WAN-321 investigation. No network, model,
GPU, runtime or filesystem access occurs at import or during graph construction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BASE_SHA = "991aebc6c409b7174d7d10e2df20b337f28fbc5d"
COMFY_SHA = "6b747c0428c343e1417219641db93a4fb7cb69ae"
REPACK_REV = "ee6f4a40737a995bf5818954cfce6d59443b0f04"
LORA_REV = "57adea585d1d21085e2dfc91ce3c7b646cdd9345"
MODEL_ROOT = "E:/Users/rober/ComfyUI/models"
INSTALL = "C:/Users/rob/AppData/Local/StableNew/ManagedComfy/v0.38.0-py313"
EVIDENCE_ROOT = "C:/Users/rob/projects/StableNew-main/reports/wan321f"
INPUT_PATH = "C:/Users/rob/qual/vid184/env/inputs/source_fullbody.png"
INPUT_SHA = "362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb"
SEEDS = (321001, 321002, 321003)
SOURCE_HASHES = {
    "nodes.py": "5eeea34944e282a362adfcad4d8eeae5de6aeeff0bdac06d8e694378001d5f12",
    "comfy_extras/nodes_wan.py": "9ae0b3b3c1384b50860b6ebfadff13ae1b012fa5db045c756372aa5979a21985",
    "comfy_extras/nodes_model_advanced.py": "8308f07f95938c2156136553ffd1e81b13e71aa6955c71f48c64404bdf91fe1c",
    "comfy/model_sampling.py": "176eeaa45b871fe96fa244961e24ba1f02c1654758b3de37966974ce6850bff7",
    "comfy/samplers.py": "2850b400e0c07ddb73429f35e5da3de01952e7ee58f4c050124ea948cbda53ae",
}


@dataclass(frozen=True)
class Asset:
    role: str
    relative_path: str
    bytes: int
    sha256: str
    repo: str
    revision: str
    upstream_path: str

    @property
    def local_path(self) -> str:
        return f"{MODEL_ROOT}/{self.relative_path}"


ASSETS = (
    Asset(
        "high",
        "diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        14294742832,
        "6122e79d55e0f235698d11d657f3b196c5273c830da00b2b013c5a048d5e6a42",
        "Comfy-Org/Wan-2.2",
        REPACK_REV,
        "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    ),
    Asset(
        "low",
        "diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        14294742832,
        "5471a457b6ac404202a5fbe6c11595a3d5641fc766b00f38763f72303fffc21e",
        "Comfy-Org/Wan-2.2",
        REPACK_REV,
        "split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    ),
    Asset(
        "text",
        "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        6735906897,
        "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
        "Comfy-Org/Wan-2.2",
        REPACK_REV,
        "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    ),
    Asset(
        "vae",
        "vae/wan_2.1_vae.safetensors",
        253815318,
        "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
        "Comfy-Org/Wan-2.2",
        REPACK_REV,
        "split_files/vae/wan_2.1_vae.safetensors",
    ),
    Asset(
        "high_lora",
        "loras/wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors",
        634645944,
        "887c3bdeb74e83859c920438e16ca31f39ab18ce189abc5f0e36f8348c5bbb19",
        "lightx2v/Wan2.2-Distill-Loras",
        LORA_REV,
        "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors",
    ),
    Asset(
        "low_lora",
        "loras/wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors",
        739472104,
        "8833bd4fd7c8eabebf0bc8ee5cfaf47f4f310ce116928a02c1adf8941dd4b0f1",
        "lightx2v/Wan2.2-Distill-Loras",
        LORA_REV,
        "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors",
    ),
)

PROMPT = (
    "A full-body woman in navy athletic clothing takes one small step forward and "
    "raises her right hand. Static camera, continuous natural movement, same person "
    "and clothing, softly lit abstract background."
)
NEGATIVE = "static, blurry, deformed hands, extra limbs, watermark, subtitles"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_graph(attempt: int) -> dict[str, Any]:
    if type(attempt) is not int or not 1 <= attempt <= 3:
        raise ValueError("Only the three frozen attempts exist")
    names = {a.role: Path(a.relative_path).name for a in ASSETS}

    def node(kind: str, **inputs: Any) -> dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    common = {
        "steps": 4,
        "cfg": 1.0,
        "sampler_name": "euler",
        "scheduler": "simple",
        "noise_seed": SEEDS[attempt - 1],
        "positive": ["10", 0],
        "negative": ["10", 1],
    }
    return {
        "1": node("UNETLoader", unet_name=names["high"], weight_dtype="default"),
        "2": node("UNETLoader", unet_name=names["low"], weight_dtype="default"),
        "3": node(
            "LoraLoaderModelOnly", model=["1", 0], lora_name=names["high_lora"], strength_model=1.0
        ),
        "4": node(
            "LoraLoaderModelOnly", model=["2", 0], lora_name=names["low_lora"], strength_model=1.0
        ),
        "5": node("ModelSamplingSD3", model=["3", 0], shift=5.0),
        "6": node("ModelSamplingSD3", model=["4", 0], shift=5.0),
        "7": node("CLIPLoader", clip_name=names["text"], type="wan", device="cpu"),
        "8": node("VAELoader", vae_name=names["vae"]),
        "9": node("LoadImage", image="wan321f-source.png"),
        "10": node(
            "WanImageToVideo",
            positive=["11", 0],
            negative=["12", 0],
            vae=["8", 0],
            width=480,
            height=832,
            length=81,
            batch_size=1,
            start_image=["9", 0],
        ),
        "11": node("CLIPTextEncode", clip=["7", 0], text=PROMPT),
        "12": node("CLIPTextEncode", clip=["7", 0], text=NEGATIVE),
        "13": node(
            "KSamplerAdvanced",
            **common,
            model=["5", 0],
            latent_image=["10", 2],
            add_noise="enable",
            start_at_step=0,
            end_at_step=2,
            return_with_leftover_noise="enable",
        ),
        "14": node(
            "KSamplerAdvanced",
            **common,
            model=["6", 0],
            latent_image=["13", 0],
            add_noise="disable",
            start_at_step=2,
            end_at_step=4,
            return_with_leftover_noise="disable",
        ),
        "15": node("VAEDecode", samples=["14", 0], vae=["8", 0]),
        "16": node("SaveImage", images=["15", 0], filename_prefix=f"wan321f_attempt_{attempt}"),
    }


def frozen_plan() -> dict[str, Any]:
    runtime_dir = f"{EVIDENCE_ROOT}/runtime"
    command = [
        f"{INSTALL}/venv/Scripts/python.exe",
        f"{INSTALL}/source/main.py",
        "--listen",
        "127.0.0.1",
        "--port",
        "8197",
    ]
    for folder in ("input", "output", "temp", "user"):
        command.extend([f"--{folder}-directory", f"{runtime_dir}/{folder}"])
    command.extend(
        [
            "--extra-model-paths-config",
            f"{runtime_dir}/extra_model_paths.yaml",
            "--disable-pinned-memory",
            "--disable-auto-launch",
            "--disable-all-custom-nodes",
        ]
    )
    return {
        "schema": "stablenew.wan321f.v1",
        "base_sha": BASE_SHA,
        "execution_class": "Standard, qualification-only",
        "assets": [
            {**asdict(a), "local_path": a.local_path, "license_declaration": "Apache-2.0"}
            for a in ASSETS
        ],
        "asset_bytes": sum(a.bytes for a in ASSETS),
        "input": {
            "path": INPUT_PATH,
            "sha256": INPUT_SHA,
            "width": 480,
            "height": 832,
            "snapshot": "wan321f-source.png",
        },
        "launch_command": command,
        "stock_source_sha256": SOURCE_HASHES.copy(),
        "runtime": {
            "revision": COMFY_SHA,
            "install": INSTALL,
            "version": "0.38.0",
            "manager": "src.video.comfy_process_manager.ComfyProcessManager",
            "base_url": "http://127.0.0.1:8197",
            "required_flags": [
                "--disable-pinned-memory",
                "--disable-auto-launch",
                "--disable-all-custom-nodes",
            ],
            "extra_model_paths": {
                "base_path": MODEL_ROOT,
                **{k: k for k in ("diffusion_models", "text_encoders", "vae", "loras")},
            },
            "restart": False,
            "external_runtime": "refuse",
        },
        "output": {
            "mode": "PNG frames",
            "width": 480,
            "height": 832,
            "frames": 81,
            "intended_fps": 16,
            "rife": False,
            "encode": False,
        },
        "attempts": [
            {"attempt": i, "seed": SEEDS[i - 1], "graph": build_graph(i)} for i in range(1, 4)
        ],
        "budget": {
            "maximum_dispatches": 3,
            "automatic_retries": 1,
            "retry_policy": (
                "At most one retry of a positively resolved failure within three total attempts; "
                "never retry ambiguous dispatch, safety stop, allocation failure or device loss"
            ),
        },
        "safety_proposal": {
            "owner_accepted": False,
            "attempt_time_owner_accepted": True,
            "sample_seconds": 0.5,
            "commit_percent_abort": 97.0,
            "commit_headroom_gib_abort": 1.0,
            "physical_available_gib_abort": 0.25,
            "consecutive": 2,
            "attempt_seconds": 300.0,
            "session_seconds": 3600.0,
            "telemetry_gap_seconds": 2.0,
            "missing_telemetry": "immediate stop",
            "device_loss": "immediate stop; end session",
        },
        "authorization": {
            "asset_download": False,
            "generation": False,
            "runtime_start_or_restart": False,
        },
        "evidence_root": EVIDENCE_ROOT,
    }


def inspect_file(path: str, expected_bytes: int | None, expected_sha: str) -> str:
    candidate = Path(path)
    if not candidate.is_file():
        return f"missing: {path}"
    if expected_bytes is not None and candidate.stat().st_size != expected_bytes:
        return f"size mismatch: {path}"
    with candidate.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    return "" if actual == expected_sha else f"hash mismatch: {path}"


def asset_refusals(inspector: Any = inspect_file) -> list[str]:
    problems = [inspector(a.local_path, a.bytes, a.sha256) for a in ASSETS]
    problems.append(inspector(INPUT_PATH, 385055, INPUT_SHA))
    return [p for p in problems if p]


def source_refusals(inspector: Any = inspect_file) -> list[str]:
    return [
        problem
        for name, expected in SOURCE_HASHES.items()
        if (problem := inspector(f"{INSTALL}/source/{name}", None, expected))
    ]
