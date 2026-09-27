"""PR-VID-184R Arm-A / Arm-B manifests and the deterministic one-variable diff.

Arm A is the accepted PR-VID-184 run (pinned memory enabled by default). Arm B is identical except
for the single ComfyUI launch flag ``--disable-pinned-memory``. Nothing here touches a GPU.
"""

from __future__ import annotations

from typing import Any

PY_EXE = r"C:\Users\rob\qual\vid184\env\venv\Scripts\python.exe"
COMFY_ROOT = r"C:\Users\rob\qual\vid184\env\comfyui_source"
INPUT_DIR = r"C:\Users\rob\qual\vid184\env\inputs"
OUTPUT_DIR = r"C:\Users\rob\qual\vid184\env\outputs"
PORT = 8189

PINNED_FLAG = "--disable-pinned-memory"
COMMON_LAUNCH_ARGS = [
    "main.py", "--listen", "127.0.0.1", "--port", str(PORT),
    "--input-directory", INPUT_DIR, "--output-directory", OUTPUT_DIR, "--disable-auto-launch",
]  # fmt: skip

# Flags that must never appear in either arm (each would be a second experimental variable).
FORBIDDEN_FLAGS = (
    "--disable-dynamic-vram", "--cuda-device", "--lowvram", "--novram", "--highvram",
    "--gpu-only", "--cpu", "--reserve-vram", "--cache-none", "--high-ram", "--fp16-unet",
    "--force-fp32", "--fast",
)  # fmt: skip

# Manifest keys allowed to differ between the arms.
ALLOWED_DIFF_KEYS = frozenset({"arm", "launch_args", "evidence_dir", "pinned_memory_expected"})

FROZEN_WORKLOAD: dict[str, Any] = {
    "comfyui_sha": "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
    "torch": "2.14.0+cu130",
    "comfy_aimdo": "0.5.5",
    "graph_sha256": "9ef8dae44d330e5af05c70fccd02d86d0855b4fb983d1913f8f7f8a012c3928c",
    "reference_sha256": "362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb",
    "driving_39f_sha256": "d761eb58876cef2bd344731d3dd482b5f59cbd9478c6e8b5e0da94c48266677d",
    "model_sha256": {
        "diffusion_models/wan_animate_2_distill_int8_convrot.safetensors": "d2e566ecac3f164cb1a6b63dc7d868d6678c9affa49fbceb3abe4f9458f89c8a",
        "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
        "vae/Wan2_1_VAE_bf16.safetensors": "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9",
        "clip_vision/clip_vision_h.safetensors": "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161",
    },
    "generation_length": 41,
    "evidence_frames": 39,
    "seed": 58819112904309696,
    "cache": "OFF (WanAnimate2Cache excluded)",
    "port": PORT,
    "contract_sha256": "30608f7a3595d5db000946fbb4941918fdf6dd09cdf8fa1387a7953ed706543c",
}  # fmt: skip


def launch_args(arm: str) -> list[str]:
    if arm == "A":
        return list(COMMON_LAUNCH_ARGS)
    if arm == "B":
        return [*COMMON_LAUNCH_ARGS, PINNED_FLAG]
    raise ValueError(f"unknown arm {arm!r}")


def arm_manifest(arm: str) -> dict[str, Any]:
    return {
        **FROZEN_WORKLOAD,
        "arm": arm,
        "launch_args": launch_args(arm),
        "pinned_memory_expected": "enabled (log: 'Enabled pinned memory')" if arm == "A" else "disabled (no 'Enabled pinned memory' log line)",
        "evidence_dir": r"C:\Users\rob\qual\vid184\env\evidence" if arm == "A" else r"C:\Users\rob\qual\vid184\env\evidence_184r",
    }  # fmt: skip


def diff_manifests(a: dict[str, Any], b: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    keys = set(a) | set(b)
    return {k: (a.get(k), b.get(k)) for k in sorted(keys) if a.get(k) != b.get(k)}


def launch_arg_difference(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return [x for x in b["launch_args"] if x not in a["launch_args"]] + [
        f"-{x}" for x in a["launch_args"] if x not in b["launch_args"]
    ]


__all__ = [
    "ALLOWED_DIFF_KEYS", "FORBIDDEN_FLAGS", "FROZEN_WORKLOAD", "PINNED_FLAG",
    "arm_manifest", "diff_manifests", "launch_arg_difference", "launch_args",
]  # fmt: skip
