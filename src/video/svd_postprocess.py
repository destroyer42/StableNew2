"""Optional postprocess pipeline for native SVD frame sequences."""

from __future__ import annotations

import gc
import json
import logging
import math
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.secondary_motion_retirement import (
    SECONDARY_MOTION_RETIRED_MESSAGE,
    block_enables_secondary_motion,
)
from src.utils.managed_process import run_bounded
from src.video.restoration.runtime import (
    GFPGAN_UNSUPPORTED_ISSUE,
    POSTPROCESS_INSTALL_HINT,
    WORKER_REPORT_FILENAME,
    WORKER_WARNING_PREFIX,
    missing_packages,
)
from src.video.restoration.upscale_models import (
    UpscaleModelSelection,
    requests_two_times,
    resolve_upscale_model,
)
from src.video.rife_runtime import (
    find_rife_executable,
    find_rife_model_dir,
    get_rife_multiplier_validation_error,
)
from src.video.svd_config import SVDConfig, SVDPostprocessConfig
from src.video.svd_errors import SVDPostprocessError
from src.video.video_export import save_video_frames

logger = logging.getLogger(__name__)

_REQUIRED_FACELIB_FILES = (
    "detection_Resnet50_Final.pth",
    "parsing_parsenet.pth",
)
_RIFE_CUSTOM_FRAMECOUNT_UNSUPPORTED = "only rife-v4 model support custom numframe and timestep"
# A hung worker would otherwise block the single queue runner forever and keep holding VRAM (audit B8).
WORKER_STAGE_TIMEOUT_SECONDS = 1800.0
RIFE_TIMEOUT_SECONDS = 1800.0
_CHILD_MAX_STDOUT_BYTES = 4 * 1024 * 1024
_CHILD_MAX_STDERR_BYTES = 256 * 1024
_RIFE_DURATION_PRESERVING_SEMANTICS = "duration_preserving_temporal_smoothing"


def get_effective_svd_export_fps(
    *,
    base_fps: int,
    postprocess_metadata: Mapping[str, Any] | None,
    interpolation_multiplier: int,
) -> int:
    """Return the actual artifact cadence while retaining base SVD config FPS."""
    if not postprocess_metadata or "interpolation" not in (
        postprocess_metadata.get("applied") or []
    ):
        return base_fps
    interpolation = postprocess_metadata.get("interpolation")
    if isinstance(interpolation, Mapping):
        output_fps = interpolation.get("output_fps")
        if isinstance(output_fps, int) and output_fps > 0:
            return output_fps
    return base_fps * interpolation_multiplier


def get_codeformer_runtime_issues(postprocess: SVDPostprocessConfig) -> list[str]:
    issues: list[str] = list(missing_packages("codeformer"))
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


def resolve_svd_upscale_model(postprocess: SVDPostprocessConfig) -> UpscaleModelSelection | None:
    """The weights an upscale stage would load for this config (native 2x for a 2x request when present)."""

    upscale = postprocess.upscale
    return resolve_upscale_model(
        scale=upscale.scale, model_path=upscale.model_path, model_path_x2=upscale.model_path_x2
    )


def get_realesrgan_runtime_issues(postprocess: SVDPostprocessConfig) -> list[str]:
    issues: list[str] = list(missing_packages("upscale"))
    upscale = postprocess.upscale
    if resolve_svd_upscale_model(postprocess) is None:
        issues.append("RealESRGAN weight")
    # An explicitly configured 2x weight that is not there is a mistake to fix, not a quiet fallback.
    if (
        requests_two_times(upscale.scale)
        and upscale.model_path_x2
        and not Path(upscale.model_path_x2).is_file()
    ):
        issues.append("RealESRGAN x2 weight")
    return issues


def get_gfpgan_runtime_issues(postprocess: SVDPostprocessConfig) -> list[str]:
    issues: list[str] = [GFPGAN_UNSUPPORTED_ISSUE]

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


def _install_hint(issues: list[str]) -> str:
    """Point at the optional-profile install only when a package (not just an asset) is missing."""

    return " " + POSTPROCESS_INSTALL_HINT if any(i.endswith(" package") for i in issues) else ""


def validate_svd_postprocess_config(config: SVDConfig) -> tuple[bool, str | None]:
    postprocess = config.postprocess
    # Secondary motion is retired (D8): a stored config that names it still loads, an enabled one is refused here.
    if block_enables_secondary_motion(postprocess.secondary_motion.to_dict()):
        return False, SECONDARY_MOTION_RETIRED_MESSAGE
    if postprocess.face_restore.enabled:
        method = postprocess.face_restore.method
        if method == "CodeFormer":
            issues = get_codeformer_runtime_issues(postprocess)
            if issues:
                return (
                    False,
                    "CodeFormer is enabled but required runtime assets are missing: "
                    + ", ".join(issues)
                    + _install_hint(issues),
                )
        elif method == "GFPGAN":
            issues = get_gfpgan_runtime_issues(postprocess)
            if issues:
                return (
                    False,
                    "GFPGAN is enabled but required runtime assets are missing: "
                    + ", ".join(issues),
                )
    if postprocess.upscale.enabled:
        issues = get_realesrgan_runtime_issues(postprocess)
        if issues:
            return (
                False,
                "RealESRGAN is enabled but required runtime assets are missing: "
                + ", ".join(issues)
                + _install_hint(issues),
            )
    if postprocess.interpolation.enabled:
        multiplier_error = get_rife_multiplier_validation_error(
            int(postprocess.interpolation.multiplier)
        )
        if multiplier_error:
            return False, multiplier_error
        executable = resolve_rife_executable(postprocess)
        if executable is None:
            return (
                False,
                "RIFE interpolation is enabled but no rife-ncnn-vulkan executable was found. "
                "Use Locate RIFE in the SVD tab, set STABLENEW_RIFE_EXE, or unpack a release "
                "into tools/rife.",
            )
        configured_model = postprocess.interpolation.model_dir
        if configured_model:
            model = find_rife_model_dir(executable, configured_model)
            if model is None or not model.is_dir():
                return (
                    False,
                    f"RIFE interpolation is enabled but the model folder '{configured_model}' "
                    "does not exist.",
                )
    return True, None


def resolve_rife_executable(postprocess: SVDPostprocessConfig) -> Path | None:
    return find_rife_executable(postprocess.interpolation.executable_path)


def resolve_rife_model(postprocess: SVDPostprocessConfig, executable: Path) -> Path | None:
    """The ``-m`` model folder for this run: the configured one, else the newest ``rife-v4.x`` beside the exe."""

    return find_rife_model_dir(executable, postprocess.interpolation.model_dir)


class SVDPostprocessRunner:
    """Runs optional frame enhancement stages after SVD frame generation."""

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_token: CancelToken | None = None,
    ) -> None:
        self._repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self._status_callback = status_callback
        self._cancel_token = cancel_token
        self._stage_warnings: list[str] = []
        self._stage_report: dict[str, Any] | None = None
        # What the last interpolation stage ran, for the manifest: every command and the model it named.
        self._rife_commands: list[list[str]] = []
        self._rife_model: Path | None = None

    @staticmethod
    def _record_stage(
        metadata: dict[str, Any], stage_name: str, frames_in: int, frames_out: int, **extra: Any
    ) -> None:
        """Append one executed stage, in execution order, with the frame counts it saw."""

        metadata["stages"].append(
            {"stage": stage_name, "frames_in": frames_in, "frames_out": frames_out, **extra}
        )

    @staticmethod
    def _read_worker_report(path: Path) -> dict[str, Any] | None:
        """What the worker wrote about itself, or ``None`` (absent or unreadable is not a failure)."""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("[SVD][postprocess] ignoring unreadable worker report %s: %s", path, exc)
            return None
        return payload if isinstance(payload, dict) else None

    def _record_stage_warnings(self, metadata: dict[str, Any], stage_name: str) -> None:
        """Surface warnings a successful worker reported (e.g. a face left unrestored)."""

        if self._stage_warnings:
            entries = metadata.setdefault("warnings", [])
            entries.extend({"stage": stage_name, "message": text} for text in self._stage_warnings)
            self._stage_warnings = []

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
            "skipped": [],
        }
        # Stage order is a quality decision, not an accident of the code: face restore first (it works on
        # the generator's own frames), then upscale, then interpolation. Upscaling before RIFE means the
        # slow GAN runs on N frames, not N x multiplier, and RIFE interpolates already-upscaled frames.
        enabled_stage_names = [
            stage_name
            for stage_name, enabled in (
                ("face_restore", postprocess.face_restore.enabled),
                ("upscale", postprocess.upscale.enabled),
                ("interpolation", postprocess.interpolation.enabled),
            )
            if enabled
        ]
        total_enabled_stages = len(enabled_stage_names)
        metadata["stages"] = []

        if postprocess.face_restore.enabled:
            frames_in = len(current_frames)
            self._emit_status(
                stage_detail="postprocess: face_restore",
                progress=0.0
                if total_enabled_stages == 0
                else len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )
            current_frames = cast(
                list[Image.Image],
                self._run_worker_stage(
                    stage_name="face_restore",
                    action="face_restore",
                    frames=current_frames,
                    payload=postprocess.face_restore.to_dict(),
                    work_dir=root,
                ),
            )
            metadata["applied"].append("face_restore")
            face_restore_metadata = postprocess.face_restore.to_dict()
            if self._stage_report is not None:
                face_restore_metadata["worker_report"] = self._stage_report
            metadata["face_restore"] = face_restore_metadata
            self._record_stage(
                metadata,
                "face_restore",
                frames_in,
                len(current_frames),
                temporal_smoothing=postprocess.face_restore.temporal_smoothing,
            )
            self._record_stage_warnings(metadata, "face_restore")
            self._emit_status(
                stage_detail="postprocess: face_restore",
                progress=len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )

        if postprocess.upscale.enabled:
            frames_in = len(current_frames)
            self._emit_status(
                stage_detail="postprocess: upscale",
                progress=0.0
                if total_enabled_stages == 0
                else len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )
            selection = resolve_svd_upscale_model(postprocess)
            if selection is None:
                raise SVDPostprocessError("RealESRGAN upscale has no usable model weights")
            current_frames = cast(
                list[Image.Image],
                self._run_worker_stage(
                    stage_name="upscale",
                    action="upscale",
                    frames=current_frames,
                    payload={
                        **postprocess.upscale.to_dict(),
                        "selected_model_path": selection.model_path,
                    },
                    work_dir=root,
                ),
            )
            metadata["applied"].append("upscale")
            upscale_metadata = postprocess.upscale.to_dict()
            upscale_metadata["model_selection"] = selection.to_dict()
            if self._stage_report is not None:
                upscale_metadata["worker_report"] = self._stage_report
            metadata["upscale"] = upscale_metadata
            self._record_stage(
                metadata,
                "upscale",
                frames_in,
                len(current_frames),
                model=selection.model_name,
                model_source=selection.source,
            )
            self._record_stage_warnings(metadata, "upscale")
            self._emit_status(
                stage_detail="postprocess: upscale",
                progress=len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )

        if postprocess.interpolation.enabled:
            self._emit_status(
                stage_detail="postprocess: interpolation",
                progress=0.0
                if total_enabled_stages == 0
                else len(metadata["applied"]) / total_enabled_stages,
                current_step=len(metadata["applied"]),
                total_steps=total_enabled_stages,
            )
            interpolation_input_frame_count = len(current_frames)
            self._rife_commands = []
            self._rife_model = None
            current_frames = self._run_rife_stage(
                frames=current_frames,
                postprocess=postprocess,
                work_dir=root,
            )
            metadata["applied"].append("interpolation")
            interpolation_metadata = postprocess.interpolation.to_dict()
            interpolation_metadata.update(
                {
                    "semantics": _RIFE_DURATION_PRESERVING_SEMANTICS,
                    "input_frame_count": interpolation_input_frame_count,
                    "input_fps": config.inference.fps,
                    "output_frame_count": len(current_frames),
                    "output_fps": config.inference.fps * int(postprocess.interpolation.multiplier),
                    "model": None if self._rife_model is None else self._rife_model.name,
                    "commands": [list(command) for command in self._rife_commands],
                }
            )
            metadata["interpolation"] = interpolation_metadata
            self._record_stage(
                metadata, "interpolation", interpolation_input_frame_count, len(current_frames)
            )
            self._emit_status(
                stage_detail="postprocess: interpolation",
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
        self._stage_report = None
        try:
            save_video_frames(frames=frames, output_dir=input_dir, prefix="frame")
            config_payload = {
                "action": action,
                "input_dir": str(input_dir.resolve()),
                "output_dir": str(output_dir.resolve()),
                "report_path": str((output_dir / WORKER_REPORT_FILENAME).resolve()),
                "payload": payload,
            }
            cmd = [
                sys.executable,
                "-m",
                "src.video.svd_postprocess_worker",
                "--config-json",
                json.dumps(config_payload),
            ]
            completed = self._run_child(
                cmd,
                cwd=self._repo_root,
                timeout_seconds=WORKER_STAGE_TIMEOUT_SECONDS,
                what=f"{stage_name} worker",
            )
            if completed.returncode != 0:
                message = (
                    completed.stderr.strip() or completed.stdout.strip() or "unknown worker error"
                )
                raise SVDPostprocessError(f"{stage_name} worker failed: {message}")
            self._stage_warnings = [
                line[len(WORKER_WARNING_PREFIX) :].strip()
                for line in (getattr(completed, "stderr", "") or "").splitlines()
                if line.startswith(WORKER_WARNING_PREFIX)
            ]
            for warning in self._stage_warnings:
                logger.warning("[SVD][postprocess] stage=%s warning: %s", stage_name, warning)
            self._stage_report = self._read_worker_report(output_dir / WORKER_REPORT_FILENAME)
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
        multiplier = int(postprocess.interpolation.multiplier)
        multiplier_error = get_rife_multiplier_validation_error(multiplier)
        if multiplier_error:
            raise SVDPostprocessError(multiplier_error)
        target_count = len(frames) * multiplier
        logger.info(
            "[SVD][postprocess] stage=interpolation start input_frames=%s multiplier=%s target_frames=%s exe=%s",
            len(frames),
            postprocess.interpolation.multiplier,
            target_count,
            executable.name,
        )
        try:
            save_video_frames(frames=frames, output_dir=input_dir, prefix="frame")
            cmd = self._build_rife_command(
                executable=executable,
                input_dir=input_dir,
                output_dir=output_dir,
                postprocess=postprocess,
                target_count=target_count,
            )
            completed = self._run_rife_command(cmd=cmd, executable=executable)
            if completed.returncode != 0:
                message = (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or "unknown interpolation error"
                )
                if self._is_rife_custom_framecount_unsupported(message):
                    logger.warning(
                        "[SVD][postprocess] stage=interpolation runtime rejected custom frame target; "
                        "falling back to compatibility mode for multiplier=%s",
                        postprocess.interpolation.multiplier,
                    )
                    return self._run_rife_compatibility_stage(
                        frames=frames,
                        postprocess=postprocess,
                        work_dir=work_dir,
                        executable=executable,
                    )
                raise SVDPostprocessError(f"RIFE interpolation failed: {message}")
        finally:
            self._close_images(frames)
            frames.clear()
            self._release_runtime_memory()
        interpolated = self._load_frame_sequence(output_dir)
        if not interpolated:
            raise SVDPostprocessError("RIFE interpolation produced no output frames")
        self._require_exact_rife_frame_count(interpolated, target_count)
        logger.info(
            "[SVD][postprocess] stage=interpolation complete output_frames=%s",
            len(interpolated),
        )
        return interpolated

    def _run_rife_compatibility_stage(
        self,
        *,
        frames: list[Image.Image],
        postprocess: SVDPostprocessConfig,
        work_dir: Path,
        executable: Path,
    ) -> list[Image.Image]:
        multiplier = int(postprocess.interpolation.multiplier)
        multiplier_error = get_rife_multiplier_validation_error(multiplier)
        if multiplier_error:
            raise SVDPostprocessError(multiplier_error)

        current_frames = list(frames)
        owns_current_frames = False
        pass_count = int(math.log2(multiplier))
        for pass_index in range(pass_count):
            pass_target_count = len(current_frames) * 2
            input_dir = work_dir / f"rife_input_pass_{pass_index + 1}"
            output_dir = work_dir / f"rife_output_pass_{pass_index + 1}"
            self._reset_dir(input_dir)
            self._reset_dir(output_dir)
            try:
                save_video_frames(frames=current_frames, output_dir=input_dir, prefix="frame")
                cmd = self._build_rife_command(
                    executable=executable,
                    input_dir=input_dir,
                    output_dir=output_dir,
                    postprocess=postprocess,
                    target_count=None,
                )
                completed = self._run_rife_command(cmd=cmd, executable=executable)
                if completed.returncode != 0:
                    message = (
                        completed.stderr.strip()
                        or completed.stdout.strip()
                        or "unknown interpolation error"
                    )
                    raise SVDPostprocessError(f"RIFE interpolation failed: {message}")
            finally:
                if owns_current_frames:
                    self._close_images(current_frames)
                    current_frames.clear()
                    self._release_runtime_memory()
            current_frames = self._load_frame_sequence(output_dir)
            owns_current_frames = True
            if not current_frames:
                raise SVDPostprocessError("RIFE interpolation produced no output frames")
            self._require_exact_rife_frame_count(current_frames, pass_target_count)
            logger.info(
                "[SVD][postprocess] stage=interpolation compatibility pass=%s output_frames=%s",
                pass_index + 1,
                len(current_frames),
            )
        return current_frames

    @staticmethod
    def _require_exact_rife_frame_count(frames: list[Image.Image], target_count: int) -> None:
        if len(frames) == target_count:
            return
        actual_count = len(frames)
        SVDPostprocessRunner._close_images(frames)
        frames.clear()
        raise SVDPostprocessError(
            "RIFE interpolation produced an unexpected frame count: "
            f"expected {target_count}, got {actual_count}"
        )

    def _build_rife_command(
        self,
        *,
        executable: Path,
        input_dir: Path,
        output_dir: Path,
        postprocess: SVDPostprocessConfig,
        target_count: int | None,
    ) -> list[str]:
        cmd = [
            str(executable),
            "-i",
            str(input_dir.resolve()),
            "-o",
            str(output_dir.resolve()),
        ]
        if target_count is not None:
            cmd.extend(["-n", str(target_count)])
        # Always name the model when one is known: the executable's own default is an old one that rejects
        # a custom frame target.
        model = resolve_rife_model(postprocess, executable)
        if model is not None:
            cmd.extend(["-m", str(model)])
        self._rife_model = model
        return cmd

    def _run_rife_command(
        self, *, cmd: list[str], executable: Path
    ) -> subprocess.CompletedProcess[str]:
        self._rife_commands.append(list(cmd))
        return self._run_child(
            cmd,
            cwd=executable.parent,
            timeout_seconds=RIFE_TIMEOUT_SECONDS,
            what="RIFE interpolation",
        )

    def _run_child(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        what: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run one contained child under a wall-clock bound; cancel and timeout kill its whole tree."""

        token = self._cancel_token
        outcome = run_bounded(
            cmd,
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=_CHILD_MAX_STDOUT_BYTES,
            max_stderr_bytes=_CHILD_MAX_STDERR_BYTES,
            cancel=None if token is None else token.is_cancelled,
            cwd=cwd,
        )
        if outcome.launch_error:
            raise SVDPostprocessError(f"{what} could not start: {outcome.launch_error}")
        if outcome.cancelled:
            raise CancellationError(f"{what} cancelled")
        if outcome.timed_out:
            raise SVDPostprocessError(
                f"{what} timed out after {timeout_seconds:.0f}s and was stopped"
            )
        if outcome.output_truncated:
            raise SVDPostprocessError(
                f"{what} wrote more than {_CHILD_MAX_STDOUT_BYTES} bytes to stdout and was stopped"
            )
        return subprocess.CompletedProcess(
            cmd,
            outcome.returncode if outcome.returncode is not None else -1,
            outcome.stdout.decode("utf-8", errors="replace"),
            outcome.stderr.decode("utf-8", errors="replace"),
        )

    @staticmethod
    def _is_rife_custom_framecount_unsupported(message: str) -> bool:
        return _RIFE_CUSTOM_FRAMECOUNT_UNSUPPORTED in str(message or "").strip().lower()

    @staticmethod
    def _is_power_of_two(value: int) -> bool:
        return value > 0 and (value & (value - 1)) == 0

    @staticmethod
    def _reset_dir(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_frame_sequence(path: Path) -> list[Image.Image]:
        frame_paths = sorted(
            candidate
            for candidate in path.iterdir()
            if candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}
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
