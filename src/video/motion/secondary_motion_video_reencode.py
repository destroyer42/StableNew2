from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.motion.secondary_motion_provenance import build_secondary_motion_manifest_block
from src.video.motion.secondary_motion_worker import run_secondary_motion_worker
from src.video.svd_errors import SVDExportError
from src.video.video_export import export_image_sequence_video


def _extract_video_frames(*, video_path: Path, output_dir: Path) -> list[Path]:
    ffmpeg_executable = resolve_ffmpeg_executable()
    if ffmpeg_executable is None:
        raise SVDExportError("FFmpeg is not available for secondary motion re-encode")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / "frame_%06d.png"
    cmd = [
        str(ffmpeg_executable),
        "-i",
        str(video_path),
        "-vsync",
        "0",
        "-y",
        str(output_pattern),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise SVDExportError(f"FFmpeg failed to extract video frames: {result.stderr}")
    return sorted(output_dir.glob("frame_*.png"))


def apply_secondary_motion_to_video(
    *,
    video_path: str | Path,
    output_dir: str | Path,
    runtime_block: Mapping[str, Any],
    fps: int,
) -> dict[str, Any]:
    payload = dict(runtime_block or {}) if isinstance(runtime_block, Mapping) else {}
    source_video_path = Path(video_path)
    root = Path(output_dir)
    work_dir = root / f"{source_video_path.stem}_secondary_motion"
    extracted_dir = work_dir / "extracted_frames"
    motion_dir = work_dir / "motion_frames"
    extracted_frames = _extract_video_frames(video_path=source_video_path, output_dir=extracted_dir)
    if not extracted_frames:
        raise SVDExportError("Secondary motion re-encode could not extract any frames")
    apply_result = run_secondary_motion_worker(
        {
            "input_dir": str(extracted_dir),
            "output_dir": str(motion_dir),
            "intent": dict(payload.get("intent") or {}),
            "policy": dict(payload.get("policy") or {}),
            "seed": payload.get("seed"),
        }
    )
    output_frame_paths = [Path(path) for path in apply_result.get("output_paths") or []]
    if not output_frame_paths:
        raise SVDExportError("Secondary motion re-encode produced no output frames")
    promoted_video_path = root / f"{source_video_path.stem}_secondary_motion.mp4"
    export_image_sequence_video(
        image_paths=output_frame_paths,
        output_path=promoted_video_path,
        fps=max(1, int(fps or 8)),
    )
    apply_result = dict(apply_result)
    apply_result["source_video_path"] = str(source_video_path)
    apply_result["reencoded_video_path"] = str(promoted_video_path)
    manifest_block = build_secondary_motion_manifest_block(
        intent=payload.get("intent"),
        policy=payload.get("policy"),
        apply_result=apply_result,
    )
    return {
        "primary_path": str(promoted_video_path),
        "output_paths": [str(promoted_video_path)],
        "video_path": str(promoted_video_path),
        "video_paths": [str(promoted_video_path)],
        "frame_paths": [str(path) for path in output_frame_paths],
        "thumbnail_path": str(output_frame_paths[0]) if output_frame_paths else None,
        "secondary_motion": manifest_block,
        "source_video_path": str(source_video_path),
    }


__all__ = ["apply_secondary_motion_to_video"]