"""Experimental SeedVR2 2x upscale of a finished clip's frames (VID-FINISH).

A pinned finishing pass, not a selectable video workflow: it takes the frames a frames-out workflow just made, sends
them losslessly to the same ComfyUI and returns upscaled frames, before RIFE smoothing and the final encode. It is off
by default, experimental and unrated (it has never been run on this PC), so a job needs its own recorded opt-in.

The graph follows ComfyUI 0.38.0's stock ``Upscale Video (SeedVR2 3B Int8)`` blueprint with two deliberate changes:
temporal chunking is fixed (``auto`` sizes chunks from whatever memory happens to be free, so the same job could give
different pixels) and colour correction is the node's own default, ``lab``.

Nothing here downloads. A missing node or model file refuses the job and says that downloading needs the owner's OK.
Memory figures and their basis: ``docs/work_packages/VID-FINISH_loop_trim_upscale.md``.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.policy_warnings import CODE_VIDEO_UPSCALE_EXPERIMENTAL, PolicyWarning
from src.pipeline.video import VideoEncodeCancelled, resolve_ffmpeg_executable, run_ffmpeg
from src.video.workflow_asset_integrity import model_folders

UPSCALE_PASS_ID = "seedvr2_3b_int8_upscale_2x"
UPSCALE_PASS_VERSION = "1.0.0"
UPSCALE_SCALE = 2
FRAMES_PER_CHUNK = 5
LATENT_OVERLAP = 1
COLOR_CORRECTION = "lab"
#: The largest clip the memory estimate covers: A14B's and TI2V-5B's 480p-class sizes, at most 121 frames.
MAX_SOURCE_PIXELS = 399_360
MAX_SOURCE_FRAMES = 121
#: An estimate, not a measurement (work package, "Memory estimate"). The floor is the existing VRAM stop rule's.
ESTIMATED_PEAK_VRAM_MIB = 7400
MIN_AVAILABLE_VRAM_MIB = 10000
ADVISORY_RAM_GB = 16.0
HISTORY_TIMEOUT_SECONDS = 3600.0
#: The temporary folder of one pass, beside the clip; removed after it, never published.
WORK_DIR_SUFFIX = "_upscale_work"
#: SHA-256 of the graph and file list; a change to either needs a new pass version.
UPSCALE_PINNED_DIGEST = "5a000c1b2ac0c45d8063670be479654a318bbd01b360d74b146bcdc6f43ba1ad"

_REPOSITORY = "Comfy-Org/SeedVR2"
_SEEDVR_NODE_FILE = Path("comfy_extras") / "nodes_seedvr.py"


@dataclass(frozen=True)
class UpscaleFile:
    folder: str
    name: str
    size: int


#: Published sizes of the two files (Hugging Face, read 2026-11-28). No SHA-256 is pinned yet: none is installed.
UPSCALE_FILES: tuple[UpscaleFile, ...] = (
    UpscaleFile("diffusion_models", "seedvr2_3b_int8_convrot.safetensors", 3_458_259_704),
    UpscaleFile("vae", "seedvr2_ema_vae_fp16.safetensors", 501_324_814),
)

UPSCALE_NODES: tuple[str, ...] = (
    "LoadVideo",
    "GetVideoComponents",
    "ResizeImageMaskNode",
    "SeedVR2Preprocess",
    "VAELoader",
    "VAEEncodeTiled",
    "SeedVR2TemporalChunk",
    "UNETLoader",
    "SeedVR2Conditioning",
    "KSampler",
    "SeedVR2TemporalMerge",
    "VAEDecodeTiled",
    "SeedVR2PostProcessing",
    "SaveImage",
)

_TILING = {"tile_size": 512, "overlap": 128, "temporal_size": 64, "temporal_overlap": 8}


def build_upscale_prompt(video_name: str, *, seed: int, filename_prefix: str) -> dict[str, Any]:
    """The API graph for one clip already uploaded as ``video_name``."""

    dit, vae = UPSCALE_FILES[0].name, UPSCALE_FILES[1].name

    def node(class_type: str, **inputs: Any) -> dict[str, Any]:
        return {"class_type": class_type, "inputs": inputs}

    return {
        "1": node("LoadVideo", file=video_name),
        "2": node("GetVideoComponents", video=["1", 0]),
        "3": {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": ["2", 0],
                "resize_type": "scale by multiplier",
                "resize_type.multiplier": float(UPSCALE_SCALE),
                "scale_method": "lanczos",
            },
        },
        "4": node("SeedVR2Preprocess", resized_images=["3", 0]),
        "5": node("VAELoader", vae_name=vae),
        "6": node("VAEEncodeTiled", pixels=["4", 0], vae=["5", 0], **_TILING),
        "7": {
            "class_type": "SeedVR2TemporalChunk",
            "inputs": {
                "latent": ["6", 0],
                "temporal_overlap": LATENT_OVERLAP,
                "chunking_mode": "manual",
                "chunking_mode.frames_per_chunk": FRAMES_PER_CHUNK,
            },
        },
        "8": node("UNETLoader", unet_name=dit, weight_dtype="default"),
        "9": node("SeedVR2Conditioning", model=["8", 0], vae_conditioning=["7", 0]),
        "10": node(
            "KSampler",
            model=["8", 0],
            positive=["9", 0],
            negative=["9", 1],
            latent_image=["7", 0],
            seed=int(seed),
            steps=1,
            cfg=1.0,
            sampler_name="euler",
            scheduler="simple",
            denoise=1.0,
        ),
        "11": node("SeedVR2TemporalMerge", latents=["10", 0], temporal_overlap=["7", 1]),
        "12": node("VAEDecodeTiled", samples=["11", 0], vae=["5", 0], **_TILING),
        "13": node(
            "SeedVR2PostProcessing",
            images=["12", 0],
            original_resized_images=["3", 0],
            color_correction_method=COLOR_CORRECTION,
        ),
        "14": node("SaveImage", images=["13", 0], filename_prefix=filename_prefix),
    }


def upscale_install_issues(config: Any) -> tuple[str, ...]:
    """What the configured ComfyUI lacks on disk (nodes, model files), without starting or downloading anything."""

    working_dir = getattr(config, "working_dir", None)
    try:
        folders = model_folders(tuple(getattr(config, "command", None) or ()), working_dir)
    except (OSError, ValueError) as exc:
        return (f"the ComfyUI install cannot be verified: {exc}",)
    issues: list[str] = []
    if not (Path(str(working_dir)).expanduser() / _SEEDVR_NODE_FILE).is_file():
        issues.append(
            "this ComfyUI has no SeedVR2 nodes (comfy_extras/nodes_seedvr.py; the managed ComfyUI 0.38.0 includes them)"
        )
    for item in UPSCALE_FILES:
        found = [
            root / item.name
            for root in folders.get(item.folder, ())
            if (root / item.name).is_file()
        ]
        if not found:
            issues.append(
                f"model file missing: {item.name} ({item.size / 1e9:.2f} GB, from {_REPOSITORY}) "
                f"in ComfyUI models/{item.folder}"
            )
            continue
        try:
            wrong = next((path for path in found if path.stat().st_size != item.size), None)
        except OSError as exc:
            issues.append(f"model file {item.name} cannot be read: {exc}")
            continue
        if wrong is not None:
            issues.append(f"model file has the wrong size (truncated or another file): {wrong}")
    return tuple(issues)


def configured_upscale_issues() -> tuple[str, ...]:
    """``upscale_install_issues`` for the ComfyUI the app is configured to run."""

    from src.video.comfy_process_manager import (
        build_default_comfy_process_config,
        get_registered_comfy_launch_config,
    )

    return upscale_install_issues(
        get_registered_comfy_launch_config() or build_default_comfy_process_config()
    )


def upscale_node_issues(object_info: Mapping[str, Any] | None) -> tuple[str, ...]:
    """What the serving ComfyUI's own node list lacks."""

    missing = [name for name in UPSCALE_NODES if name not in (object_info or {})]
    if not missing:
        return ()
    return (f"the serving ComfyUI does not offer the node(s) {', '.join(missing)}",)


def upscale_refusal(issues: Sequence[str]) -> str:
    return (
        f"The SeedVR2 upscale cannot run: {'; '.join(issues)}. Downloading anything needs the owner's OK. "
        "Nothing was downloaded. Turn off the upscale to make this clip without it."
    )


def upscale_size_issue(width: int, height: int, frame_count: int) -> str | None:
    """Why this clip is outside what the memory estimate covers, or ``None``."""

    if width <= 0 or height <= 0:
        return "the clip's frame size is unknown, so the upscale's GPU memory cannot be bounded"
    if frame_count <= 0:
        return "the clip's length is unknown, so the upscale's memory use cannot be bounded"
    if width * height > MAX_SOURCE_PIXELS:
        return f"{width}x{height} is above the 480p class ({MAX_SOURCE_PIXELS:,} pixels) the 12 GB estimate covers"
    if frame_count > MAX_SOURCE_FRAMES:
        return f"{frame_count} frames is above the {MAX_SOURCE_FRAMES} frames the estimate covers"
    return None


def upscale_readiness_spec() -> Any:
    """The shape ``WorkflowResourceReadiness`` reads, so the pass uses the same stop rule as the video workflows."""

    return SimpleNamespace(
        backend_defaults={
            "resource_readiness": {
                "policy": "seedvr2_3b_int8_upscale_v1",
                "min_available_to_comfy_vram_mib": MIN_AVAILABLE_VRAM_MIB,
                "min_available_ram_gb": ADVISORY_RAM_GB,
            }
        }
    )


def upscale_warning() -> PolicyWarning:
    """N1: shown beside Queue and recorded as accepted on the job that turns the upscale on."""

    return PolicyWarning(
        code=CODE_VIDEO_UPSCALE_EXPERIMENTAL,
        subject=f"{UPSCALE_PASS_ID}@{UPSCALE_PASS_VERSION}",
        title="The SeedVR2 upscale is experimental and unrated.",
        why=(
            "It has never been run on this PC: its time and memory use are estimates and its picture quality "
            "has not been rated."
        ),
        fix="Queue runs it anyway and records your opt-in on the job. Turn the upscale off for the normal clip.",
        source_gate="video_finishing.upscale",
    )


def frozen_upscale(*, seed: int) -> dict[str, Any]:
    """The block an NJR records; the graph and files are fixed by the pass version."""

    return {
        "pass_id": UPSCALE_PASS_ID,
        "pass_version": UPSCALE_PASS_VERSION,
        "scale": UPSCALE_SCALE,
        "seed": int(seed),
        "experimental_opt_in": True,
    }


def require_frozen_upscale(value: Any) -> dict[str, Any]:
    """A job's upscale block, checked before anything dispatches."""

    block = dict(value) if isinstance(value, Mapping) else {}
    if (block.get("pass_id"), block.get("pass_version")) != (UPSCALE_PASS_ID, UPSCALE_PASS_VERSION):
        raise ValueError(
            f"This job names an upscale pass or version StableNew does not have "
            f"({block.get('pass_id')} {block.get('pass_version')}). Queue the clip again."
        )
    if block.get("experimental_opt_in") is not True:
        raise ValueError(
            "The SeedVR2 upscale is experimental and this job has no recorded opt-in for it."
        )
    return block


def build_lossless_input_command(
    ffmpeg: str | Path, frame_pattern: str | Path, target: str | Path, *, fps: int
) -> list[str]:
    """The numbered PNG frames as one lossless RGB clip, which is what the blueprint's ``LoadVideo`` reads."""

    return [
        str(ffmpeg),
        "-v",
        "error",
        "-y",
        "-framerate",
        str(int(fps)),
        "-i",
        str(frame_pattern),
        "-c:v",
        "libx264rgb",
        "-qp",
        "0",
        "-preset",
        "veryfast",
        str(target),
    ]


def encode_lossless_input(
    frames: Sequence[str | Path],
    work_dir: Path,
    *,
    fps: int,
    name: str,
    cancel_token: CancelToken | None = None,
) -> Path:
    """Write ``frames`` (already in playback order) to ``<work_dir>/<name>.mp4`` without losing a pixel."""

    ffmpeg = resolve_ffmpeg_executable()
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not available to prepare the clip for the upscale")
    staged = work_dir / "input"
    staged.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        shutil.copyfile(frame, staged / f"frame_{index:06d}.png")
    target = work_dir / f"{name}.mp4"
    command = build_lossless_input_command(ffmpeg, staged / "frame_%06d.png", target, fps=fps)
    try:
        completed = run_ffmpeg(
            command, cancel=None if cancel_token is None else cancel_token.is_cancelled
        )
    except VideoEncodeCancelled as exc:
        raise CancellationError("upscale preparation cancelled") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"FFmpeg could not prepare the clip for the upscale: {completed.stderr.strip()}"
        )
    return target


__all__ = [
    "ESTIMATED_PEAK_VRAM_MIB",
    "HISTORY_TIMEOUT_SECONDS",
    "MAX_SOURCE_FRAMES",
    "MAX_SOURCE_PIXELS",
    "MIN_AVAILABLE_VRAM_MIB",
    "UPSCALE_FILES",
    "UPSCALE_NODES",
    "UPSCALE_PASS_ID",
    "UPSCALE_PASS_VERSION",
    "UPSCALE_PINNED_DIGEST",
    "UPSCALE_SCALE",
    "WORK_DIR_SUFFIX",
    "UpscaleFile",
    "build_lossless_input_command",
    "build_upscale_prompt",
    "configured_upscale_issues",
    "encode_lossless_input",
    "frozen_upscale",
    "require_frozen_upscale",
    "upscale_install_issues",
    "upscale_node_issues",
    "upscale_readiness_spec",
    "upscale_refusal",
    "upscale_size_issue",
    "upscale_warning",
]
