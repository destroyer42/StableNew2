"""Run one frozen conversion plan through Blender and FFmpeg and publish a verified derivative (PR-VID-MOTION-354).

Sequence: re-verify the source bytes -> private owned work folder -> Blender child renders PNG frames (CPU only, contained,
bounded, cancellable) -> frame set verified (exact count, order, size) -> FFmpeg encodes them losslessly -> the encoded file
is decoded back and its frame count, size and rate checked -> video and provenance are staged together and published by one
directory rename.  Nothing is published unless every check passed; a failure removes only the folder this call created.
The original animation and character files are only ever opened for reading.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_text
from src.utils.managed_process import ProcessOutcome, run_bounded
from src.video.motion_conversion.blender import BlenderInstall, child_environment
from src.video.motion_conversion.conversion_plan import (
    SCRIPT_VERSION,
    AnimationProbe,
    ConversionPlan,
    canonical_json,
    parse_rational,
)
from src.video.motion_conversion.fbx_scan import scan_fbx
from src.video.motion_conversion.inventory import sha256_file
from src.video.motion_source_preparation import build_file_md5_command, parse_framemd5

PROVENANCE_SCHEMA = "stablenew.motion-conversion-provenance.v1"
SCRIPT_PATH = Path(__file__).with_name("blender_scripts") / "motion_render.bpy"
WORK_DIRNAME = ".work"
OWNER_MARKER = ".stablenew-owned"
PROVENANCE_NAME = "provenance.json"
PREVIEW_FRAMES = 9
MAX_REPORT_BYTES = 256 * 1024
BLENDER_BASE_SECONDS = 180.0
BLENDER_SECONDS_PER_FRAME = 45.0
BLENDER_MAX_SECONDS = 3600.0
FFMPEG_TIMEOUT_SECONDS = 600.0
MAX_FFMPEG_STDOUT = 8 * 1024 * 1024
PURPOSE_ACCEPTED = "accepted"
PURPOSE_PREVIEW = "preview"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_SLUG = re.compile(r"[^A-Za-z0-9._-]+")

STATUS_OK = "ok"
STATUS_REUSED = "reused"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

Runner = Callable[..., ProcessOutcome]


@dataclass(frozen=True, slots=True)
class ConversionResult:
    status: str
    reason: str = ""
    directory: str = ""
    video_path: str = ""
    provenance_path: str = ""
    output_sha256: str = ""
    frame_count: int = 0
    plan_digest: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_OK, STATUS_REUSED)


def _fail(
    reason: str, plan: ConversionPlan | None = None, *, status: str = STATUS_FAILED
) -> ConversionResult:
    return ConversionResult(
        status=status, reason=reason, plan_digest=plan.digest if plan is not None else ""
    )


def slug(text: str) -> str:
    return _SLUG.sub("_", text).strip("._")[:48] or "motion"


def preview_plan(plan: ConversionPlan) -> ConversionPlan:
    """The same plan cut to a few frames from the same start, for a quick look (never a library candidate)."""

    return replace(plan, output_frames=min(plan.output_frames, PREVIEW_FRAMES))


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or not head.startswith(_PNG_MAGIC) or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def verify_frames(frames_dir: Path, count: int, width: int, height: int) -> str:
    """Empty string when ``frame_00001.png`` .. ``frame_<count>.png`` are exactly the directory's contents and sized right."""

    names = sorted(p.name for p in frames_dir.iterdir()) if frames_dir.is_dir() else []
    expected = [f"frame_{i:05d}.png" for i in range(1, count + 1)]
    if names != expected:
        missing = sorted(set(expected) - set(names))[:3]
        extra = sorted(set(names) - set(expected))[:3]
        return f"The render produced {len(names)} file(s), expected {count} (missing {missing}, unexpected {extra})."
    for name in expected:
        size = png_size(frames_dir / name)
        if size != (width, height):
            return f"{name} is not a {width}x{height} PNG."
    return ""


class MotionConverter:
    def __init__(
        self,
        install: BlenderInstall,
        output_root: str | Path,
        *,
        ffmpeg: str | Path,
        runner: Runner = run_bounded,
        script_path: Path = SCRIPT_PATH,
        environ: dict[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._install = install
        self._root = Path(output_root).expanduser().resolve()
        self._ffmpeg = str(ffmpeg)
        self._runner = runner
        self._script = Path(script_path)
        self._environ = environ
        self._clock = clock

    # ------------------------------------------------------------------ owned work folders

    def _new_work_dir(self) -> Path:
        parent = self._root / WORK_DIRNAME
        parent.mkdir(parents=True, exist_ok=True)
        work = parent / f"run-{uuid.uuid4().hex[:16]}"
        work.mkdir()
        (work / OWNER_MARKER).write_text(work.name, encoding="utf-8")
        return work

    def _remove_owned(self, work: Path) -> None:
        """Delete ``work`` only when it is a folder this converter created (marker names it, and it sits in our .work)."""

        try:
            marker = work / OWNER_MARKER
            if (
                work.parent == self._root / WORK_DIRNAME
                and marker.is_file()
                and marker.read_text(encoding="utf-8") == work.name
            ):
                shutil.rmtree(work, ignore_errors=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ blender child

    def _blender(
        self,
        action: str,
        request: dict[str, Any],
        work: Path,
        timeout: float,
        cancel: threading.Event | None,
    ) -> tuple[dict[str, Any] | None, str, ProcessOutcome]:
        request_path, report_path = work / f"{action}.request.json", work / f"{action}.report.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        command = self._install.command(
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "-noaudio",
            "--python-exit-code",
            "3",
            "--python",
            str(self._script),
            "--",
            action,
            str(request_path),
            str(report_path),
        )
        outcome = self._runner(
            command,
            timeout_seconds=timeout,
            max_stdout_bytes=MAX_REPORT_BYTES,
            cancel=cancel,
            cwd=str(work),
            env=child_environment(self._environ, work / "blender-user"),
        )
        if outcome.launch_error:
            return None, f"Blender could not be started: {outcome.launch_error}", outcome
        if outcome.cancelled:
            return None, "Cancelled.", outcome
        if outcome.timed_out:
            return None, f"Blender did not finish within {int(timeout)} s and was stopped.", outcome
        report: dict[str, Any] | None = None
        try:
            report = (
                json.loads(report_path.read_text(encoding="utf-8"))
                if report_path.is_file()
                else None
            )
        except (OSError, ValueError):
            report = None
        if outcome.returncode != 0 or report is None or not report.get("ok"):
            detail = (report or {}).get(
                "error"
            ) or f"Blender exited with code {outcome.returncode}."
            return None, f"Blender could not {action} the file: {detail}"[:400], outcome
        return report, "", outcome

    def probe(
        self,
        source_path: str | Path,
        kind: str,
        *,
        transform: dict[str, Any],
        cancel: threading.Event | None = None,
    ) -> AnimationProbe:
        """Ask Blender (one bounded child, explicit operator action) for the animation's rate, range and bones."""

        work = self._new_work_dir()
        try:
            report, problem, _ = self._blender(
                "probe",
                {"path": str(source_path), "kind": kind, "transform": transform},
                work,
                300.0,
                cancel,
            )
            if report is None:
                raise RuntimeError(problem)
            return AnimationProbe(
                fps=parse_rational(report["fps"]),
                frame_first=parse_rational(report["frame_first"]),
                frame_last=parse_rational(report["frame_last"]),
                bone_names=tuple(str(n) for n in report.get("bone_names", ())),
                has_mesh=bool(report.get("has_mesh")),
                blender_version=".".join(str(p) for p in self._install.version),
            )
        finally:
            self._remove_owned(work)

    # ------------------------------------------------------------------ convert

    def convert(
        self,
        plan: ConversionPlan,
        *,
        purpose: str = PURPOSE_ACCEPTED,
        cancel: threading.Event | None = None,
        warnings: tuple[str, ...] = (),
    ) -> ConversionResult:
        if purpose not in (PURPOSE_ACCEPTED, PURPOSE_PREVIEW):
            return _fail("Unknown conversion purpose.", plan)
        problem = self._verify_inputs(plan, cancel)
        if problem:
            return _fail(
                problem, plan, status=STATUS_CANCELLED if problem == "Cancelled." else STATUS_FAILED
            )
        target = self._final_dir(plan, purpose)
        existing = self._existing_result(target, plan)
        if existing is not None:
            return existing
        revision = 2
        while (
            target.exists()
        ):  # an unverifiable folder with this name is left alone; publish beside it
            target = target.with_name(f"{self._final_dir(plan, purpose).name}-r{revision}")
            revision += 1
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            work = self._new_work_dir()
        except OSError as exc:
            return _fail(f"The output folder cannot be used: {exc}", plan)
        try:
            return self._convert_in(work, plan, purpose, target, cancel, warnings)
        except OSError as exc:
            return _fail(f"A file operation failed: {exc}", plan)
        finally:
            self._remove_owned(work)

    def _verify_inputs(self, plan: ConversionPlan, cancel: threading.Event | None) -> str:
        if not self._script.is_file():
            return "The Blender conversion script is missing from this installation."
        pairs = [(plan.source_path, plan.source_sha256, "animation file")]
        if plan.character_path:
            pairs.append((plan.character_path, plan.character_sha256, "reference character"))
        for path, expected, label in pairs:
            try:
                actual = sha256_file(Path(path), cancel)
            except InterruptedError:
                return "Cancelled."
            except OSError as exc:
                return f"The {label} cannot be read: {exc}"
            if actual != expected:
                return f"The {label} changed since the plan was made (SHA-256 differs); inspect it again."
        return ""

    def _final_dir(self, plan: ConversionPlan, purpose: str) -> Path:
        base = "previews" if purpose == PURPOSE_PREVIEW else "converted"
        stem = slug(Path(plan.source_path).stem)
        return self._root / base / f"{stem}_{plan.profile}_{plan.digest[:12]}"

    def _existing_result(self, target: Path, plan: ConversionPlan) -> ConversionResult | None:
        """A previously published identical conversion that still verifies is returned instead of re-rendered."""

        record_path = target / PROVENANCE_NAME
        if not record_path.is_file():
            return None
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            video = published_video(target, record) if isinstance(record, dict) else None
            ok = (
                video is not None
                and record.get("plan_digest") == plan.digest
                and video.is_file()
                and sha256_file(video) == record["output"]["sha256"]
            )
        except (OSError, ValueError, KeyError):
            ok = False
        if not ok:
            return None
        return ConversionResult(
            STATUS_REUSED,
            "An identical, verified conversion already exists.",
            str(target),
            str(video),
            str(record_path),
            record["output"]["sha256"],
            int(record["output"]["frame_count"]),
            plan.digest,
            tuple(record.get("warnings", ())),
        )

    def _convert_in(
        self,
        work: Path,
        plan: ConversionPlan,
        purpose: str,
        target: Path,
        cancel: threading.Event | None,
        warnings: tuple[str, ...],
    ) -> ConversionResult:
        frames_dir = work / "frames"
        frames_dir.mkdir()
        timeout = min(
            BLENDER_MAX_SECONDS,
            BLENDER_BASE_SECONDS + BLENDER_SECONDS_PER_FRAME * plan.output_frames,
        )
        report, problem, _ = self._blender(
            "render",
            {"plan": plan.to_record(), "frames_dir": str(frames_dir)},
            work,
            timeout,
            cancel,
        )
        if report is None:
            return _fail(
                problem, plan, status=STATUS_CANCELLED if problem == "Cancelled." else STATUS_FAILED
            )
        if report.get("render_device") != "CPU" or report.get("render_engine") != "CYCLES":
            return _fail(
                f"The render was not confirmed CPU-only ({report.get('render_engine')}/{report.get('render_device')}); "
                "nothing was published.",
                plan,
            )
        if int(report.get("frames_written", -1)) != plan.output_frames:
            return _fail("Blender reported a different number of frames than the plan.", plan)
        problem = verify_frames(frames_dir, plan.output_frames, plan.width, plan.height)
        if problem:
            return _fail(problem, plan)

        stage = work / "stage"
        stage.mkdir()
        video_name = f"{target.name}.mp4"
        staged_video = stage / video_name
        encode = self._runner(
            self.encode_command(frames_dir, plan, staged_video),
            timeout_seconds=FFMPEG_TIMEOUT_SECONDS,
            max_stdout_bytes=MAX_FFMPEG_STDOUT,
            cancel=cancel,
        )
        if encode.cancelled:
            return _fail("Cancelled.", plan, status=STATUS_CANCELLED)
        if encode.returncode != 0 or not staged_video.is_file():
            return _fail("FFmpeg could not encode the rendered frames.", plan)
        check = self._runner(
            build_file_md5_command(self._ffmpeg, staged_video, "yuv420p"),
            timeout_seconds=FFMPEG_TIMEOUT_SECONDS,
            max_stdout_bytes=MAX_FFMPEG_STDOUT,
            cancel=cancel,
        )
        decoded = parse_framemd5(check.stdout) if check.returncode == 0 else []
        if len(decoded) != plan.output_frames:
            return _fail(
                f"The encoded video decodes to {len(decoded)} frame(s), expected {plan.output_frames}; not published.",
                plan,
            )
        output_sha = sha256_file(staged_video)
        record = self._provenance(plan, purpose, report, video_name, output_sha, target, warnings)
        atomic_write_text(stage / PROVENANCE_NAME, json.dumps(record, indent=2, sort_keys=True))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(stage, target)  # one rename publishes video and provenance together
        except OSError as exc:
            return _fail(f"The result could not be published at {target}: {exc}", plan)
        return ConversionResult(
            STATUS_OK,
            "",
            str(target),
            str(target / video_name),
            str(target / PROVENANCE_NAME),
            output_sha,
            plan.output_frames,
            plan.digest,
            warnings,
        )

    def encode_command(
        self, frames_dir: Path, plan: ConversionPlan, destination: Path
    ) -> list[str]:
        return [
            self._ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-hide_banner",
            "-protocol_whitelist",
            "file",
            "-framerate",
            str(plan.target_fps),
            "-i",
            str(frames_dir / "frame_%05d.png"),
            "-frames:v",
            str(plan.output_frames),
            "-an",
            "-map_metadata",
            "-1",
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-preset",
            "medium",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(plan.target_fps),
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-y",
            "-f",
            "mp4",
            str(destination),
        ]

    # ------------------------------------------------------------------ provenance

    def _provenance(
        self,
        plan: ConversionPlan,
        purpose: str,
        report: dict[str, Any],
        video_name: str,
        output_sha: str,
        target: Path,
        warnings: tuple[str, ...],
    ) -> dict[str, Any]:
        scan = scan_fbx(plan.source_path) if plan.source_type == "fbx" else None
        character: dict[str, Any]
        if plan.character_path:
            character = {
                "mode": "reference_character",
                "path": plan.character_path,
                "sha256": plan.character_sha256,
                "binding": plan.binding.to_record() if plan.binding is not None else None,
            }
        elif plan.profile == "skeleton_reference":
            character = {"mode": "skeleton_only", "path": "", "sha256": ""}
        else:
            character = {
                "mode": "embedded_skinned_mesh",
                "has_skin": bool(scan.has_skin) if scan is not None else False,
                "mesh_object_count": report.get("mesh_object_count"),
            }
        return {
            "schema": PROVENANCE_SCHEMA,
            "derived": True,
            "purpose": purpose,
            "created_at": self._clock().isoformat(),
            "plan_digest": plan.digest,
            "plan": plan.to_record(),
            "source": {
                "path": plan.source_path,
                "sha256": plan.source_sha256,
                "type": plan.source_type,
                "route": plan.source_route,
            },
            "rig": {
                "fingerprint": plan.rig_fingerprint,
                "bone_count": len(report.get("bone_names", ())),
            },
            "character": character,
            "conversion": {
                "profile": plan.profile,
                "camera": plan.camera,
                "camera_mode": plan.camera_mode,
                "root_motion": plan.root_motion,
                "frame_window": {
                    "start_seconds": f"{plan.start_seconds.numerator}/{plan.start_seconds.denominator}",
                    "output_frames": plan.output_frames,
                },
                "source_fps": f"{plan.source_fps.numerator}/{plan.source_fps.denominator}",
                "target_fps": plan.target_fps,
                "retimed_by_sampling": plan.retimed,
                "coordinate_transform": dict(plan.transform),
                "geometry": {"width": plan.width, "height": plan.height},
                "facing_estimated": bool(report.get("facing_estimated")),
            },
            "tools": {
                "blender": self._install.to_record(),
                "script_version": SCRIPT_VERSION,
                "script_sha256": sha256_file(self._script),
                "render_engine": report.get("render_engine"),
                "render_device": report.get("render_device"),
                "ffmpeg": self._ffmpeg_label(),
            },
            "output": {
                "file": video_name,
                "sha256": output_sha,
                "frame_count": plan.output_frames,
                "fps": plan.target_fps,
                "width": plan.width,
                "height": plan.height,
                "published_location": str(target),
            },
            "warnings": list(warnings),
        }

    def _ffmpeg_label(self) -> str:
        return Path(self._ffmpeg).name


def published_video(folder: Path, record: dict[str, Any]) -> Path | None:
    """The video a record names, only when it is a plain file name inside ``folder`` (a record is data, never a path)."""

    output = record.get("output")
    if not isinstance(output, dict):
        return None
    name, digest = output.get("file"), output.get("sha256")
    if (
        not isinstance(name, str)
        or not isinstance(digest, str)
        or not name
        or Path(name).name != name
        or name in (".", "..")
    ):
        return None
    if not all(isinstance(record.get(key), dict) for key in ("source", "conversion")):
        return None
    return folder / name


def read_provenance(path: str | Path) -> dict[str, Any] | None:
    """A conversion record, or ``None`` when it is missing, malformed or of another schema."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != PROVENANCE_SCHEMA:
        return None
    return data


def verify_published(directory: str | Path) -> str:
    """Empty when the published video still hashes to its provenance record; otherwise the reason."""

    folder = Path(directory)
    record = read_provenance(folder / PROVENANCE_NAME)
    if record is None:
        return "The conversion record is missing or unreadable."
    try:
        video = published_video(folder, record)
        if video is None:
            return "The conversion record is malformed."
        if sha256_file(video) != record["output"]["sha256"]:
            return "The converted video no longer matches its record."
    except OSError:
        return "The converted video is missing."
    return ""


__all__ = [
    "ConversionResult",
    "MotionConverter",
    "PROVENANCE_SCHEMA",
    "canonical_json",
    "preview_plan",
    "published_video",
    "read_provenance",
    "verify_frames",
    "verify_published",
]
