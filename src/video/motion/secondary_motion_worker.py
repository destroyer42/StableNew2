from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .secondary_motion_engine import apply_secondary_motion_to_frames
from .secondary_motion_models import SecondaryMotionIntent, SecondaryMotionPolicy


_FRAME_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _list_frame_paths(input_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _FRAME_SUFFIXES
        ]
    )


def run_secondary_motion_worker(payload: Mapping[str, Any]) -> dict[str, Any]:
    input_dir = Path(str(payload.get("input_dir") or "")).resolve()
    output_dir = Path(str(payload.get("output_dir") or "")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    frame_paths = _list_frame_paths(input_dir) if input_dir.exists() else []
    frames = [Image.open(path).copy() for path in frame_paths]
    for image in frames:
        image.load()

    intent = SecondaryMotionIntent.from_dict(payload.get("intent"))
    policy = SecondaryMotionPolicy.from_dict(payload.get("policy"))
    output_frames, apply_result = apply_secondary_motion_to_frames(
        frames,
        policy=policy,
        intent=intent,
        seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
    )

    output_paths: list[str] = []
    for index, image in enumerate(output_frames):
        source_path = frame_paths[index] if index < len(frame_paths) else None
        suffix = source_path.suffix if source_path is not None else ".png"
        output_path = output_dir / (
            source_path.name if source_path is not None else f"frame_{index:04d}{suffix}"
        )
        image.save(output_path)
        output_paths.append(str(output_path))

    result = apply_result.to_dict()
    result["application_path"] = "frame_directory_worker"
    result["input_dir"] = str(input_dir)
    result["output_dir"] = str(output_dir)
    result["input_paths"] = [str(path) for path in frame_paths]
    result["output_paths"] = output_paths
    return result


__all__ = ["run_secondary_motion_worker"]
