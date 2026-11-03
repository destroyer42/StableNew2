"""Run one frozen conversion plan through Blender and FFmpeg and publish a verified derivative (PR-VID-MOTION-354).

Sequence: re-verify the source bytes -> private owned work folder -> Blender child renders PNG frames (CPU only, contained,
bounded, cancellable) -> frame set verified (exact count, order, size) -> FFmpeg encodes them losslessly -> the encoded file
is decoded back and its frame count, size and rate checked -> video and provenance are staged together and published by one
directory rename.  Nothing is published unless every check passed; a failure removes only the folder this call created.
The original animation and character files are only ever opened for reading.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from src.utils.atomic_io import atomic_write_text
from src.utils.managed_process import ProcessOutcome, run_bounded
from src.video.motion_conversion import diagnostics as diag
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
# A render whose pixels all sit within SUBJECT_TONE_DELTA of its background tone (all but a tiny fraction of them) is a miss:
# the subject is absent or off-frame.  A real figure, even a thin skeleton, covers well over this.
SUBJECT_TONE_DELTA = 24
MIN_SUBJECT_COVERAGE = 0.0005
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
    #: One of the ``diagnostics.KIND_*`` values when the conversion did not succeed.
    failure_kind: str = ""
    #: A redacted JSON report outside the repository (see ``diagnostics``); empty when none could be written.
    diagnostic_path: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_OK, STATUS_REUSED)


def _fail(
    reason: str,
    plan: ConversionPlan | None = None,
    *,
    status: str = STATUS_FAILED,
    kind: str = "",
    diagnostic_path: str = "",
) -> ConversionResult:
    return ConversionResult(
        status=status,
        reason=reason,
        plan_digest=plan.digest if plan is not None else "",
        failure_kind=kind,
        diagnostic_path=diagnostic_path,
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
    for name in expected:
        covered = subject_coverage(frames_dir / name)
        if covered is None:
            return f"{name} could not be decoded."
        if covered < MIN_SUBJECT_COVERAGE:
            return f"{name} shows no visible subject (a blank or nearly empty render); nothing was published."
    return ""


def verify_motion(frames_dir: Path, count: int) -> str:
    """Refuse a multi-frame render whose frames are all byte-identical: the animation was not applied."""

    if count < 2:
        return ""
    digests = {
        hashlib.sha256((frames_dir / f"frame_{i:05d}.png").read_bytes()).hexdigest()
        for i in range(1, count + 1)
    }
    if len(digests) == 1:
        return "Every rendered frame is identical, so the animation was not applied; nothing was published."
    return ""


def subject_coverage(path: Path) -> float | None:
    """Fraction of pixels that differ clearly from the frame's dominant (background) tone; ``None`` if undecodable."""

    try:
        with Image.open(path) as image:
            histogram: list[int] = list(image.convert("L").histogram())
    except (OSError, ValueError):
        return None
    total = sum(histogram)
    if total <= 0:
        return None
    background = max(range(256), key=histogram.__getitem__)
    near = sum(
        count
        for tone, count in enumerate(histogram)
        if abs(tone - background) <= SUBJECT_TONE_DELTA
    )
    return float((total - near) / total)


class ProbeError(RuntimeError):
    """The Blender probe failed; ``result`` carries the classified cause and report path for the caller."""

    def __init__(self, message: str, result: ConversionResult | None = None) -> None:
        super().__init__(message)
        self.result = result


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
        diagnostics_dir: str | Path | None = None,
    ) -> None:
        self._install = install
        self._root = Path(output_root).expanduser().resolve()
        self._ffmpeg = str(ffmpeg)
        self._runner = runner
        self._script = Path(script_path)
        self._environ = environ
        self._clock = clock
        self._diagnostics_dir = Path(diagnostics_dir) if diagnostics_dir else None

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

    def _failure_result(
        self,
        info: diag.FailureInfo,
        plan: ConversionPlan | None,
        *,
        context: Mapping[str, Any],
        reason: str = "",
        outcome: ProcessOutcome | None = None,
        script_report: Mapping[str, Any] | None = None,
        elapsed: float = 0.0,
    ) -> ConversionResult:
        """A failed result carrying its classified cause and, where a folder is configured, a redacted report."""

        status = STATUS_CANCELLED if info.kind == diag.KIND_CANCELLED else STATUS_FAILED
        path = ""
        if self._diagnostics_dir is not None and info.kind != diag.KIND_CANCELLED:
            path = self._write_diagnostic(info, context, outcome, script_report, elapsed)
        return _fail(
            reason or info.message, plan, status=status, kind=info.kind, diagnostic_path=path
        )

    def _write_diagnostic(
        self,
        info: diag.FailureInfo,
        context: Mapping[str, Any],
        outcome: ProcessOutcome | None,
        script_report: Mapping[str, Any] | None,
        elapsed: float,
    ) -> str:
        process: dict[str, Any] = {"elapsed_seconds": round(elapsed, 1)}
        if outcome is not None:
            process.update(
                exit_code=diag.exit_code_text(outcome.returncode),
                timed_out=outcome.timed_out,
                cancelled=outcome.cancelled,
                output_truncated=outcome.output_truncated,
                contained=outcome.contained,
            )
        redact = diag.redactor([(self._root, "<conversion-root>")])
        report = diag.build_report(
            info,
            context={
                **context,
                "blender": self._install.to_record(),
                "script_version": SCRIPT_VERSION,
            },
            process=process,
            stdout=outcome.stdout if outcome is not None else b"",
            stderr=outcome.stderr if outcome is not None else b"",
            script_report=script_report,
            redact=redact,
            clock=self._clock,
        )
        try:
            assert self._diagnostics_dir is not None
            return str(diag.write_report(self._diagnostics_dir, report))
        except OSError:
            return ""  # the reason is still shown; a report that cannot be written must not hide it

    @staticmethod
    def _plan_context(plan: ConversionPlan) -> dict[str, Any]:
        return {
            "plan_digest": plan.digest,
            "source_name": Path(plan.source_path).name,
            "source_sha256": plan.source_sha256,
            "source_route": plan.source_route,
            "profile": plan.profile,
            "camera": plan.camera,
            "camera_mode": plan.camera_mode,
            "root_motion": plan.root_motion,
            "output_frames": plan.output_frames,
            "geometry": f"{plan.width}x{plan.height}",
        }

    def _blender(
        self,
        action: str,
        request: dict[str, Any],
        work: Path,
        timeout: float,
        cancel: threading.Event | None,
        context: Mapping[str, Any],
        plan: ConversionPlan | None = None,
    ) -> tuple[dict[str, Any] | None, ConversionResult | None]:
        """Run one Blender child.  Returns ``(report, None)`` or ``(None, failed result)``."""

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
        started = time.monotonic()
        # Blender prints per-frame progress to the console: a long clip writes far more than any fixed cap, so the console
        # is a log whose tail is kept, never a reason to stop the render.  The result is read from the report file.
        outcome = self._runner(
            command,
            timeout_seconds=timeout,
            max_stdout_bytes=MAX_REPORT_BYTES,
            cancel=cancel,
            cwd=str(work),
            env=child_environment(self._environ, work / "blender-user"),
            keep_output_tail=True,
        )
        elapsed = time.monotonic() - started
        report = self._read_report(report_path)
        clean = (
            outcome.returncode == 0
            and not outcome.launch_error
            and not outcome.timed_out
            and not outcome.cancelled
        )
        if clean and report is not None and report.get("ok"):
            return report, None
        info = diag.classify_blender_failure(
            action,
            returncode=outcome.returncode,
            timed_out=outcome.timed_out,
            cancelled=outcome.cancelled,
            launch_error=outcome.launch_error,
            report=report,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            timeout_seconds=timeout,
        )
        direct = (diag.KIND_LAUNCH, diag.KIND_CANCELLED, diag.KIND_TIMEOUT)
        reason = (
            info.message
            if info.kind in direct
            else f"Blender could not {action} the file: {info.message}"[:600]
        )
        failed = self._failure_result(
            info,
            plan,
            context={**context, "action": action},
            reason=reason,
            outcome=outcome,
            script_report=report,
            elapsed=elapsed,
        )
        return None, failed

    @staticmethod
    def _read_report(path: Path) -> dict[str, Any] | None:
        try:
            if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

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
            report, failed = self._blender(
                "probe",
                {"path": str(source_path), "kind": kind, "transform": transform},
                work,
                300.0,
                cancel,
                {"source_name": Path(str(source_path)).name, "source_kind": kind},
            )
            if report is None:
                raise ProbeError(failed.reason if failed is not None else "Blender failed.", failed)
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
            return _fail("Unknown conversion purpose.", plan, kind=diag.KIND_REFUSED)
        refused = self._verify_inputs(plan, cancel)
        if refused is not None:
            return self._refuse(plan, refused)
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
            return self._refuse(
                plan,
                diag.FailureInfo(diag.KIND_STORAGE, f"The output folder cannot be used: {exc}"),
            )
        try:
            return self._convert_in(work, plan, purpose, target, cancel, warnings)
        except OSError as exc:
            return self._refuse(
                plan,
                diag.FailureInfo(diag.KIND_STORAGE, f"A file operation failed: {exc}"),
            )
        finally:
            self._remove_owned(work)

    def _refuse(
        self,
        plan: ConversionPlan,
        info: diag.FailureInfo,
        *,
        outcome: ProcessOutcome | None = None,
    ) -> ConversionResult:
        """A classified failure that is not a Blender child's own (verification, encoding, storage, input checks)."""

        return self._failure_result(info, plan, context=self._plan_context(plan), outcome=outcome)

    def _verify_inputs(
        self, plan: ConversionPlan, cancel: threading.Event | None
    ) -> diag.FailureInfo | None:
        if not self._script.is_file():
            return diag.FailureInfo(
                diag.KIND_CAPABILITY,
                "The Blender conversion script is missing from this installation.",
            )
        pairs = [(plan.source_path, plan.source_sha256, "animation file")]
        if plan.character_path:
            pairs.append((plan.character_path, plan.character_sha256, "reference character"))
        for path, expected, label in pairs:
            try:
                actual = sha256_file(Path(path), cancel)
            except InterruptedError:
                return diag.FailureInfo(diag.KIND_CANCELLED, "Cancelled.")
            except OSError as exc:
                return diag.FailureInfo(diag.KIND_ASSET, f"The {label} cannot be read: {exc}")
            if actual != expected:
                return diag.FailureInfo(
                    diag.KIND_SOURCE,
                    f"The {label} changed since the plan was made (SHA-256 differs); inspect it again.",
                )
        return None

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
        report, failed = self._blender(
            "render",
            {"plan": plan.to_record(), "frames_dir": str(frames_dir)},
            work,
            timeout,
            cancel,
            self._plan_context(plan),
            plan,
        )
        if report is None:
            assert failed is not None
            return failed
        if report.get("render_device") != "CPU" or report.get("render_engine") != "CYCLES":
            return self._refuse(
                plan,
                diag.FailureInfo(
                    diag.KIND_CAPABILITY,
                    f"The render was not confirmed CPU-only ({report.get('render_engine')}/{report.get('render_device')}); "
                    "nothing was published.",
                ),
            )
        if int(report.get("frames_written", -1)) != plan.output_frames:
            return self._refuse(
                plan,
                diag.FailureInfo(
                    diag.KIND_OUTPUT, "Blender reported a different number of frames than the plan."
                ),
            )
        problem = verify_frames(
            frames_dir, plan.output_frames, plan.width, plan.height
        ) or verify_motion(frames_dir, plan.output_frames)
        if problem:
            return self._refuse(plan, diag.FailureInfo(diag.KIND_OUTPUT, problem))

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
            return _fail("Cancelled.", plan, status=STATUS_CANCELLED, kind=diag.KIND_CANCELLED)
        if encode.returncode != 0 or not staged_video.is_file():
            return self._refuse(
                plan,
                diag.FailureInfo(diag.KIND_ENCODE, "FFmpeg could not encode the rendered frames."),
                outcome=encode,
            )
        check = self._runner(
            build_file_md5_command(self._ffmpeg, staged_video, "yuv420p"),
            timeout_seconds=FFMPEG_TIMEOUT_SECONDS,
            max_stdout_bytes=MAX_FFMPEG_STDOUT,
            cancel=cancel,
        )
        if check.cancelled:
            return _fail("Cancelled.", plan, status=STATUS_CANCELLED, kind=diag.KIND_CANCELLED)
        decoded = parse_framemd5(check.stdout) if check.returncode == 0 else []
        if len(decoded) != plan.output_frames:
            return self._refuse(
                plan,
                diag.FailureInfo(
                    diag.KIND_ENCODE,
                    f"The encoded video decodes to {len(decoded)} frame(s), expected {plan.output_frames}; not published.",
                ),
                outcome=check,
            )
        output_sha = sha256_file(staged_video)
        record = self._provenance(plan, purpose, report, video_name, output_sha, target, warnings)
        atomic_write_text(stage / PROVENANCE_NAME, json.dumps(record, indent=2, sort_keys=True))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(stage, target)  # one rename publishes video and provenance together
        except OSError as exc:
            return self._refuse(
                plan,
                diag.FailureInfo(
                    diag.KIND_STORAGE, f"The result could not be published at {target}: {exc}"
                ),
            )
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


STALE_WORK_SECONDS = 3600.0


def sweep_stale_work(
    output_root: str | Path, *, older_than_seconds: float = STALE_WORK_SECONDS
) -> int:
    """Delete work folders an interrupted run (a crash, a killed application) left in ``<root>/.work``.

    Only a folder that carries this converter's ownership marker naming itself, and that has not been touched for
    ``older_than_seconds``, is removed -- never a live run's folder, never anything this converter did not create.
    Published results are never inside ``.work``.  Returns how many were removed."""

    parent = Path(output_root) / WORK_DIRNAME
    removed = 0
    try:
        children = list(parent.iterdir())
    except OSError:
        return 0
    for work in children:
        try:
            marker = work / OWNER_MARKER
            if (
                work.is_dir()
                and not work.is_symlink()
                and work.name.startswith("run-")
                and marker.is_file()
                and marker.read_text(encoding="utf-8") == work.name
                and time.time() - work.stat().st_mtime > older_than_seconds
            ):
                shutil.rmtree(work, ignore_errors=True)
                removed += 0 if work.exists() else 1
        except OSError:
            continue
    return removed


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
    "ProbeError",
    "PROVENANCE_SCHEMA",
    "canonical_json",
    "preview_plan",
    "published_video",
    "read_provenance",
    "sweep_stale_work",
    "verify_frames",
    "verify_published",
]
