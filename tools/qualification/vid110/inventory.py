"""Read-only inventory of the qualification host (Comfy, models, nodes, disk, RAM, GPU)."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_NODES = (
    "Wan22ImageToVideoLatent",
    "WanVaceToVideo",
    "TrimVideoLatent",
    "CreateVideo",
    "SaveVideo",
    "LoadVideo",
    "GetVideoComponents",
    "ModelSamplingSD3",
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "KSampler",
    "VAEDecode",
    "LoadImage",
    "CLIPTextEncode",
)
OPTIONAL_NODES = ("WanAnimateToVideo", "WanFunControlToVideo", "Canny")
LOADER_ENUMS = {
    "diffusion_models": ("UNETLoader", "unet_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
}


def _get_json(url: str, timeout: float = 20.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback Comfy
        return json.loads(response.read().decode("utf-8"))


def gpu_state() -> dict[str, Any]:
    """Whole-GPU state from ``nvidia-smi`` (per-process VRAM is not reported under WDDM)."""

    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,"
                "utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=15,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": str(exc)}
    name, driver, total, used, free, util, temp = (p.strip() for p in out.split(","))
    return {
        "available": True,
        "name": name,
        "driver": driver,
        "vram_total_mib": int(total),
        "vram_used_mib": int(used),
        "vram_free_mib": int(free),
        "utilization_pct": int(util),
        "temperature_c": int(temp),
    }


def disk_free_gb(path: Path) -> float:
    return round(shutil.disk_usage(path).free / 1e9, 1)


def system_ram() -> dict[str, float]:
    import psutil

    memory = psutil.virtual_memory()
    return {
        "total_gb": round(memory.total / 1e9, 1),
        "available_gb": round(memory.available / 1e9, 1),
    }


def inventory_comfy(base_url: str) -> dict[str, Any]:
    """Comfy version, available loader files and node presence, from public endpoints only."""

    base = base_url.rstrip("/")
    try:
        stats = _get_json(f"{base}/system_stats")
        info = _get_json(f"{base}/object_info", timeout=60)
    except (OSError, ValueError) as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}
    system = stats.get("system", {})
    files: dict[str, list[str]] = {}
    for label, (node, field) in LOADER_ENUMS.items():
        spec = ((info.get(node) or {}).get("input", {}).get("required", {}) or {}).get(field)
        files[label] = list(spec[0]) if spec and isinstance(spec[0], list) else []
    return {
        "reachable": True,
        "base_url": base,
        "comfyui_version": system.get("comfyui_version"),
        "pytorch_version": system.get("pytorch_version"),
        "python_version": str(system.get("python_version", "")).split(" ")[0],
        "launch_args": list(system.get("argv", [])),
        "node_count": len(info),
        "required_nodes": {n: n in info for n in REQUIRED_NODES},
        "optional_nodes": {n: n in info for n in OPTIONAL_NODES},
        "loader_files": files,
    }


def build_inventory(comfy_url: str, models_dir: Path) -> dict[str, Any]:
    return {
        "comfy": inventory_comfy(comfy_url),
        "gpu": gpu_state(),
        "system_ram": system_ram(),
        "disk_free_gb": disk_free_gb(models_dir if models_dir.exists() else Path(".")),
        "models_dir": str(models_dir),
    }


def missing_prerequisites(
    inventory: dict[str, Any], *, required_files: dict[str, list[str]]
) -> list[str]:
    """Deterministic list of unmet prerequisites for a lane (empty means ready)."""

    problems: list[str] = []
    comfy = inventory.get("comfy", {})
    if not comfy.get("reachable"):
        return ["ComfyUI is not reachable"]
    for node, present in comfy.get("required_nodes", {}).items():
        if not present:
            problems.append(f"missing Comfy node {node}")
    for label, names in required_files.items():
        have = set(comfy.get("loader_files", {}).get(label, []))
        problems.extend(f"missing {label} file {n}" for n in names if n not in have)
    return problems
