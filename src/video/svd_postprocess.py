"""Optional postprocess pipeline for native SVD frame sequences."""

from __future__ import annotations

from collections.abc import Callable
import gc
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from src.video.svd_config import SVDConfig, SVDPostprocessConfig
from src.video.svd_errors import SVDPostprocessError
from src.video.video_export import save_video_frames

logger = logging.getLogger(__name__)

_REQUIRED_FACELIB_FILES = (
    "detection_Resnet50_Final.pth",
    "parsing_parsenet.pth",
)


def get_codeformer_runtime_issues(postprocess: SVDPostprocessConfig) -> list[str]:
    issues: list[str] = []
    weight_path = postprocess.face_restore.codeformer_weight_path
    if not weight_path or not Path(weight_path).exists():
        issues.append("CodeFormer weight")

    facelib_root = postprocess.face_restore.facelib_model_root
    if not facelib_root or not Path(facelib_root).exists():
        issues.append("facelib model root")
        return issues

    root = Path(facelib_root)
    for filename in _REQUIRED_FACELIB_FILES:
        if not (root / filename).exists():
            issues.append(filename)
    return issues


def get_realesrgan_runtime_issues(postprocess: SVDPostprocessConfig) -> list[str]:
    issues: list[str] = []
    model_path = postprocess.upscale.model_path
    if not model_path or not Path(model_path).exists():
        issues.append("RealESRGAN weight")
    return issues


def get_gfpgan_runtime_issues(postprocess: SVDPostprocessConfig) -> list[str]:
    issues: list[str] = []
    if importlib.util.find_spec("gfpgan") is None:
        issues.append("gfpgan package")

    weight_path = postprocess.face_restore.gfpgan_weight_path
    if not weight_path or not Path(weight_path).exists():
        issues.append("GFPGAN weight")

    facelib_root = postprocess.face_restore.facelib_model_root
    if not facelib_root or not Path(facelib_root).exists():
        issues.append("facelib model root")
        return issues

    root = Path(facelib_root)
    for filename in _REQUIRED_FACELIB_FILES:
        if not (root / filename).exists():
            issues.append(filename)
    return issues


def validate_svd_postprocess_config(config: SVDConfig) -> tuple[bool, str | None]:
    postprocess = config.postprocess
    if postprocess.face_restore.enabled:
        method = postprocess.face_restore.method
        if method == "CodeFormer":
            issues = get_codeformer_runtime_issues(postprocess)
            if issues:
                return False, "CodeFormer is enabled but required runtime assets are missing: " + ", ".join(issues)
        elif method == "GFPGAN":
            issues = get_gfpgan_runtime_issues(postprocess)
            if issues:
                return False, "GFPGAN is enabled but required runtime assets are missing: " + ", ".join(issues)
    if postprocess.upscale.enabled:
        issues = get_realesrgan_runtime_issues(postprocess)
        if issues:
            return False, "RealESRGAN is enabled but required runtime assets are missing: " + ", ".join(issues)
    if postprocess.interpolation.enabled:
        executable = resolve_rife_executable(postprocess)
        if executable is None:
            return False, "RIFE interpolation is enabled but no rife-ncnn-vulkan executable was found."
    return True, None


def resolve_rife_executable(postprocess: SVDPostprocessConfig) -> Path | None:
    explicit = postprocess.interpolation.executable_path
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path

    env_candidate = os.getenv("STABLENEW_RIFE_EXE")
    if env_candidate:
        path = Path(env_candidate)
        if path.exists():
            return path

    which_path = shutil.which("rife-ncnn-vulkan")
    if which_path:
        return Path(which_path)

    repo_root = Path(__file__).resolve().parents[2]
    repo_candidate = repo_root / "tools" / "rife" / "rife-ncnn-vulkan.exe"
    if repo_candidate.exists():
        return repo_candidate
    return None


class SVDPostprocessRunner:
    """Runs optional frame enhancement stages after SVD frame generation."""

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self._status_callback = status_callback

    def process_frames(
        self,
        *,
        frames: list[Image.Image],
        config: SVDConfig,
        work_dir: str | Path,
    ) -> tuple[list[Image.Image], dict[str, Any] | None]:
        if not frames:
            return frames, None

        valid, reason = validate_svd_postprocess_config(config)
        if not valid:
            raise SVDPostprocessError(reason or "SVD postprocess configuration is invalid")

        postprocess = config.postprocess
        if not (
            postprocess.face_restore.enabled
            or postprocess.interpolation.enabled
            or postprocess.upscale.enabled
        ):
            return frames, None

        logger.info(
            "[SVD][postprocess] start input_frames=%s face_restore=%s interpolation=%s upscale=%s",
            len(frames),
            postprocess.face_restore.enabled,
            postprocess.interpolation.enabled,
            postprocess.upscale.enabled,
        )
        root = Path(work_dir)
        current_frames = list(frames)
        metadata: dict[str, Any] = {
            "input_frame_count": len(frames),
            "applied": [],
        }
        enabled_stage_names = [
            stage_name
            for stage_name, enabled in (
                ("face_restore", postprocess.face_restore.enabled),
                ("interpolation", postprocess.interpolation.enabled),
                ("upscale", postprocess.upscale.enabled),
            )
            if enabled
        ]
        total_enabled_stages = len(enabled_stage_names)

        if postprocess.face_restore.enabled:
            self._emit_status(
                stage_detail="postprocess: face_restore",
                progress=0.0 if total_enabled_stages == 0 else metadata["applied"].__len__() / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )
            current_frames = self._run_worker_stage(
                stage_name="face_restore",
                action="face_restore",
                frames=current_frames,
                payload=postprocess.face_restore.to_dict(),
                work_dir=root,
            )
            metadata["applied"].append("face_restore")
            metadata["face_restore"] = postprocess.face_restore.to_dict()
            self._emit_status(
                stage_detail="postprocess: face_restore",
                progress=len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )

        if postprocess.interpolation.enabled:
            self._emit_status(
                stage_detail="postprocess: interpolation",
                progress=0.0 if total_enabled_stages == 0 else metadata["applied"].__len__() / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )
            current_frames = self._run_rife_stage(
                frames=current_frames,
                postprocess=postprocess,
                work_dir=root,
            )
            metadata["applied"].append("interpolation")
            metadata["interpolation"] = postprocess.interpolation.to_dict()
            self._emit_status(
                stage_detail="postprocess: interpolation",
                progress=len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )

        if postprocess.upscale.enabled:
            self._emit_status(
                stage_detail="postprocess: upscale",
                progress=0.0 if total_enabled_stages == 0 else metadata["applied"].__len__() / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )
            current_frames = self._run_worker_stage(
                stage_name="upscale",
                action="upscale",
                frames=current_frames,
                payload=postprocess.upscale.to_dict(),
                work_dir=root,
            )
            metadata["applied"].append("upscale")
            metadata["upscale"] = postprocess.upscale.to_dict()
            self._emit_status(
                stage_detail="postprocess: upscale",
                progress=len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )

        metadata["output_frame_count"] = len(current_frames)
        if current_frames:
            metadata["output_width"] = current_frames[0].width
            metadata["output_height"] = current_frames[0].height
        logger.info(
            "[SVD][postprocess] complete output_frames=%s applied=%s size=%sx%s",
            len(current_frames),
            metadata["applied"],
            metadata.get("output_width"),
            metadata.get("output_height"),
        )
        return current_frames, metadata

    def _run_worker_stage(
        self,
        *,
        stage_name: str,
        action: str,
        frames: list[Image.Image],
        payload: dict[str, Any],
        work_dir: Path,
    ) -> list[Image.Image]:
        input_dir = work_dir / f"{stage_name}_input"
        output_dir = work_dir / f"{stage_name}_output"
        self._reset_dir(input_dir)
        self._reset_dir(output_dir)
        logger.info(
            "[SVD][postprocess] stage=%s start input_frames=%s",
            stage_name,
            len(frames),
        )
        try:
            save_video_frames(frames=frames, output_dir=input_dir, prefix="frame")
            config_payload = {
                "action": action,
                "input_dir": str(input_dir.resolve()),
                "output_dir": str(output_dir.resolve()),
                "payload": payload,
            }
            cmd = [
                sys.executable,
                "-m",
                "src.video.svd_postprocess_worker",
                "--config-json",
                json.dumps(config_payload),
            ]
            completed = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip() or "unknown worker error"
                raise SVDPostprocessError(f"{stage_name} worker failed: {message}")
        finally:
            self._close_images(frames)
            frames.clear()
            self._release_runtime_memory()
        processed = self._load_frame_sequence(output_dir)
        if not processed:
            raise SVDPostprocessError(f"{stage_name} worker produced no output frames")
        logger.info(
            "[SVD][postprocess] stage=%s complete output_frames=%s",
            stage_name,
            len(processed),
        )
        return processed

    def _run_rife_stage(
        self,
        *,
        frames: list[Image.Image],
        postprocess: SVDPostprocessConfig,
        work_dir: Path,
    ) -> list[Image.Image]:
        executable = resolve_rife_executable(postprocess)
        if executable is None:
            raise SVDPostprocessError("RIFE interpolation runtime is not available")

        input_dir = work_dir / "rife_input"
        output_dir = work_dir / "rife_output"
        self._reset_dir(input_dir)
        self._reset_dir(output_dir)
        target_count = ((len(frames) - 1) * int(postprocess.interpolation.multiplier)) + 1
        logger.info(
            "[SVD][postprocess] stage=interpolation start input_frames=%s multiplier=%s target_frames=%s exe=%s",
            len(frames),
            postprocess.interpolation.multiplier,
            target_count,
            executable.name,
        )
        try:
            save_video_frames(frames=frames, output_dir=input_dir, prefix="frame")

            # Inference from the official rife-ncnn-vulkan CLI: -n expects a target frame count.
            cmd = [
                str(executable),
                "-i",
                str(input_dir.resolve()),
                "-o",
                str(output_dir.resolve()),
                "-n",
                str(target_count),
            ]
            model_dir = postprocess.interpolation.model_dir
            if model_dir:
                cmd.extend(["-m", str(model_dir)])
            completed = subprocess.run(
                cmd,
                cwd=str(executable.parent),
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip() or "unknown interpolation error"
                raise SVDPostprocessError(f"RIFE interpolation failed: {message}")
        finally:
            self._close_images(frames)
            frames.clear()
            self._release_runtime_memory()
        interpolated = self._load_frame_sequence(output_dir)
        if not interpolated:
            raise SVDPostprocessError("RIFE interpolation produced no output frames")
        logger.info(
            "[SVD][postprocess] stage=interpolation complete output_frames=%s",
            len(interpolated),
        )
        return interpolated

    @staticmethod
    def _reset_dir(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_frame_sequence(path: Path) -> list[Image.Image]:
        frame_paths = sorted(
            candidate for candidate in path.iterdir() if candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}
        )
        frames: list[Image.Image] = []
        for frame_path in frame_paths:
            with Image.open(frame_path) as image:
                frames.append(image.convert("RGB"))
        return frames

    @staticmethod
    def _close_images(images: list[Image.Image]) -> None:
        for image in images:
            close = getattr(image, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    @staticmethod
    def _release_runtime_memory() -> None:
        gc.collect()

    def _emit_status(
        self,
        *,
        stage_detail: str,
        progress: float,
        current_step: int = 0,
        total_steps: int = 0,
        eta_seconds: float | None = None,
    ) -> None:
        if self._status_callback is None:
            return
        try:
            self._status_callback(
                {
                    "stage_detail": stage_detail,
                    "progress": max(0.0, min(1.0, float(progress))),
                    "current_step": int(current_step),
                    "total_steps": int(total_steps),
                    "eta_seconds": eta_seconds,
                }
            )
        except Exception as exc:
            logger.warning("[SVD][postprocess] status callback failed: %s", exc)
