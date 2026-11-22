"""PR-VID-STORY-380 test fakes: finished StableNew clip jobs exactly as the repository hands them back.

Every job's NJR is built by the real ``VideoWorkflowNjrBuilder`` (or ``build_sequence_njr``) over the real workflow
catalog, behind the same registry port the app uses. Its result has the runner's shape (``metadata`` with
``video_workflow_artifact`` or ``sequence_artifact``) and, for a single clip, a backend manifest nested the way
``ComfyWorkflowVideoBackend._write_manifest`` writes it: ``provenance_extra`` first, then ``manifest_extra``, so the
file's ``frames_out`` is the full ``FramesOutRecord`` and ``interpolation`` is the smoothing record. Sequence jobs get a
real ledger (and a storyboard take its real cut manifest). Frames are small real PNGs and clips are placeholder bytes:
nothing starts Comfy, FFmpeg, RIFE, a GPU or a network.

Run folders sit under ``<output root>/Reprocess/`` and carry the job's folder token, as the runner names them, so the
ledger locator finds them too.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.runtime_state import CancelToken
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.pipeline.video_sequence_executor import (
    CUT_MANIFEST_FILE_NAME,
    SequenceOutcome,
    sequence_artifact_payload,
)
from src.queue.job_model import JobStatus
from src.state.output_routing import OUTPUT_ROUTE_REPROCESS
from src.video.frames_out import FramesOutRecord
from src.video.sequence_job_build import build_sequence_njr
from src.video.sequence_ledger import (
    BASIS_NATIVE,
    LEDGER_FILE_NAME,
    STATE_COMPLETED,
    FileRecord,
    FinalFrame,
    LedgerSegment,
    SequenceLedger,
    sha256_of,
    write_ledger,
)
from src.video.sequence_locator import folder_token
from src.video.sequence_plan import ROOT_PARENT, SequencePlan, StoryboardPlanLink
from src.video.storyboard_cut import take_manifest, write_cut_manifest
from src.video.svd_config import SVDConfig
from src.video.video_interpolation import VideoInterpolationResult
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID, WAN_A14B_VERSION

#: The registry the app hands to builders and admission (approved and experimental offerable, never disabled).
REG = DefaultWorkflowRegistryPort()

A14B_SIZE = (832, 480)
A14B_FPS = 16
TI2V_ID = "wan22_ti2v_5b_i2v_v1"
TI2V_ENCODED_VERSION = (
    "1.2.0"  # the encoded-only TI2V-5B version (Comfy writes the clip; no frames)
)
TI2V_FPS = 24
ANIMATE2_DRIVE_ID = "wan_animate2_drive_i2v_v1"
#: Small frames where the size is irrelevant (sequence and decoded frames).
SMALL = (64, 48)


# --------------------------------------------------------------------------------------------- files


def png(
    path: Path, size: tuple[int, int] = A14B_SIZE, color: tuple[int, int, int] = (40, 90, 160)
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def overwrite_png(path: Path) -> None:
    """Same size, different pixels: only the hash tells it apart."""

    with Image.open(path) as image:
        size = image.size
    png(Path(path), size, (255, 0, 255))


def remove(paths: Iterable[Path], *more: Path) -> None:
    for path in [*paths, *more]:
        Path(path).unlink()


def _clip(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 placeholder clip")
    return path


def fake_rife(tmp_path: Path) -> Path:
    """An existing file the builder accepts as the RIFE executable (it is never run)."""

    return _clip(tmp_path / "tools" / "rife-ncnn-vulkan.exe")


# --------------------------------------------------------------------------------------------- repository


@dataclass
class FakeJob:
    job_id: str
    status: JobStatus
    result: dict[str, Any] | None
    _normalized_record: NormalizedJobRecord | None


@dataclass
class FakeRepository:
    """``get_job_model`` as ``JobRepository`` answers it; ``files`` remembers what each fake job wrote."""

    jobs: dict[str, FakeJob] = field(default_factory=dict)
    files: dict[str, dict[str, Path]] = field(default_factory=dict)

    def add(
        self,
        njr: NormalizedJobRecord,
        *,
        status: JobStatus = JobStatus.COMPLETED,
        result: dict[str, Any] | None = None,
        files: Mapping[str, Path] | None = None,
    ) -> str:
        job_id = str(njr.job_id)
        self.jobs[job_id] = FakeJob(job_id, status, result, njr)
        self.files[job_id] = dict(files or {})
        return job_id

    def get_job_model(self, job_id: str) -> FakeJob | None:
        return self.jobs.get(job_id)


def unsmoothed_mp4(repo: FakeRepository, job_id: str) -> Path:
    return repo.files[job_id]["unsmoothed"]


def comfy_original(repo: FakeRepository, job_id: str) -> Path:
    return repo.files[job_id]["comfy_original"]


# --------------------------------------------------------------------------------------------- NJRs


def a14b_settings(**overrides: Any) -> dict[str, Any]:
    """The Make Video settings line for Wan2.2 I2V-A14B (the approved default)."""

    return {
        "workflow_id": WAN_A14B_ID,
        "workflow_version": WAN_A14B_VERSION,
        "prompt": "the person waves",
        "negative_prompt": "blurry, watermark",
        "seed": "1234",
        "frame_count": 81,
        "output_route": OUTPUT_ROUTE_REPROCESS,
        **overrides,
    }


def ti2v_encoded_settings(**overrides: Any) -> dict[str, Any]:
    return {
        "workflow_id": TI2V_ID,
        "workflow_version": TI2V_ENCODED_VERSION,
        "prompt": "the person waves",
        "seed": "77",
        "frame_count": 17,
        **overrides,
    }


def builder(tmp_path: Path) -> VideoWorkflowNjrBuilder:
    return VideoWorkflowNjrBuilder(workflow_registry=REG, output_dir_provider=lambda: str(tmp_path))


def source_image(tmp_path: Path, size: tuple[int, int] = A14B_SIZE) -> Path:
    return png(tmp_path / "sources" / "source.png", size, (40, 90, 160))


def clip_njr(tmp_path: Path, form: Mapping[str, Any]) -> NormalizedJobRecord:
    """A single-clip NJR exactly as Make Video builds it."""

    njr_builder = builder(tmp_path)
    frozen = njr_builder.freeze_inputs(str(source_image(tmp_path)), dict(form))
    return njr_builder.build_job(dict(form), frozen).njr


def _smoothing(form: dict[str, Any], tmp_path: Path, smoothed_fps: int | None, fps: int) -> None:
    if smoothed_fps is not None:
        form["interpolation"] = {
            "enabled": True,
            "multiplier": smoothed_fps // fps,
            "executable_path": str(fake_rife(tmp_path)),
        }


def run_dir(tmp_path: Path, job_id: str) -> Path:
    folder = tmp_path / OUTPUT_ROUTE_REPROCESS / f"20261121_120000_video_{folder_token(job_id)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# --------------------------------------------------------------------------------------------- results


def _aggregate(
    *,
    output_paths: list[Path],
    frame_paths: list[Path],
    manifest: Path | None,
    source: str | None,
) -> dict[str, Any]:
    """``video_workflow_artifact`` as ``PipelineRunner`` aggregates one Comfy result."""

    paths = [str(path) for path in output_paths]
    return {
        "stage": "video_workflow",
        "backend_id": "comfy",
        "artifact_type": "video",
        "output_paths": paths,
        "video_paths": [paths[0]] if paths else [],
        "gif_paths": [],
        "frame_paths": [str(path) for path in frame_paths],
        "frame_path_count": 0,
        "manifest_paths": [] if manifest is None else [str(manifest)],
        "thumbnail_path": str(frame_paths[0]) if frame_paths else None,
        "source_image_path": source,
        "primary_path": paths[0] if paths else None,
        "count": len(paths),
        "artifacts": [],
    }


def _backend_manifest(
    folder: Path,
    *,
    njr: NormalizedJobRecord,
    output_paths: list[Path],
    frame_paths: list[Path],
    provenance_extra: Mapping[str, Any],
    manifest_extra: Mapping[str, Any] | None,
) -> Path:
    """Nested as ``_write_manifest`` nests it: base fields, then ``provenance_extra``, then ``manifest_extra``."""

    stage = dict(njr.stage_chain[0].extra)
    paths = [str(path) for path in output_paths]
    target = folder / "manifests" / f"{output_paths[0].stem}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "backend_id": "comfy",
        "workflow_id": stage["workflow_id"],
        "workflow_version": stage["workflow_version"],
        "prompt_id": "prompt-1",
        "output_paths": paths,
        "video_path": paths[0],
        "video_paths": paths,
        "gif_path": None,
        "gif_paths": [],
        "frame_paths": [str(path) for path in frame_paths],
        "frame_path_count": len(frame_paths),
        "manifest_paths": [str(target)],
        "count": len(paths),
    }
    payload.update(dict(provenance_extra))
    payload.update(dict(manifest_extra or {}))
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def _result(aggregate: Mapping[str, Any], variant_extra: Mapping[str, Any]) -> dict[str, Any]:
    variant = {
        "path": aggregate["primary_path"],
        "output_paths": list(aggregate["output_paths"]),
        "frame_paths": list(aggregate["frame_paths"]),
        "manifest_path": (aggregate["manifest_paths"] or [None])[0],
        **dict(variant_extra),
    }
    return {
        "success": True,
        "variants": [variant],
        "metadata": {
            "video_artifacts": {"video_workflow": dict(aggregate)},
            "video_primary_artifact": dict(aggregate),
            "video_primary_backend_id": "comfy",
            "video_primary_stage": "video_workflow",
            "video_workflow_artifact": dict(aggregate),
        },
    }


def _interpolation(
    *, source: str, smooth: Path, frames: int, fps: int, smoothed_fps: int
) -> dict[str, Any]:
    multiplier = smoothed_fps // fps
    return VideoInterpolationResult(
        source_video_path=source,
        video_path=str(smooth),
        input_frame_count=frames,
        output_frame_count=(frames - 1) * multiplier + 1,
        input_fps=fps,
        output_fps=smoothed_fps,
        multiplier=multiplier,
        model="rife-v4.6",
    ).to_dict()


# --------------------------------------------------------------------------------------------- jobs


def frames_out_job(
    tmp_path: Path,
    *,
    count: int = 81,
    size: tuple[int, int] = A14B_SIZE,
    smoothed_fps: int | None = None,
    form: Mapping[str, Any] | None = None,
) -> tuple[FakeRepository, str, list[Path]]:
    """A finished A14B frames-out clip: Comfy's PNGs, StableNew's encode and, when smoothed, the RIFE clip leading."""

    settings = dict(form or a14b_settings(frame_count=count))
    _smoothing(settings, tmp_path, smoothed_fps, A14B_FPS)
    njr = clip_njr(tmp_path, settings)
    folder = run_dir(tmp_path, njr.job_id)
    frames = [
        png(folder / f"{WAN_A14B_ID}_{number:05d}_.png", size, (number % 256, 120, 200)).resolve()
        for number in range(1, count + 1)
    ]
    digests = [sha256_of(frame) for frame in frames]
    encoded = _clip(folder / f"{WAN_A14B_ID}_{njr.job_id}.mp4").resolve()
    record = FramesOutRecord(
        video_path=str(encoded),
        fps=A14B_FPS,
        frame_count=count,
        expected_frame_count=count,
        first_frame_path=str(frames[0]),
        last_frame_path=str(frames[-1]),
        last_frame_sha256=digests[-1],
        frame_paths=[str(frame) for frame in frames],
        frame_sha256=digests,
        reconciliation={"status": "match", "expected_frame_count": count},
        encoder={"crf": 18, "preset": "medium", "pix_fmt": "yuv420p"},
    )
    provenance: dict[str, Any] = {"frames_out": record.summary()}
    outputs = [encoded]
    if smoothed_fps is not None:
        smooth = _clip(folder / f"{encoded.stem}_smooth.mp4").resolve()
        provenance["interpolation"] = _interpolation(
            source=str(folder), smooth=smooth, frames=count, fps=A14B_FPS, smoothed_fps=smoothed_fps
        )
        outputs = [smooth, encoded]
    manifest = _backend_manifest(
        folder,
        njr=njr,
        output_paths=outputs,
        frame_paths=frames,
        provenance_extra=provenance,
        manifest_extra={"frames_out": record.to_dict()},
    )
    aggregate = _aggregate(
        output_paths=outputs,
        frame_paths=frames,
        manifest=manifest,
        source=str(njr.input_image_paths[0]),
    )
    repo = FakeRepository()
    job_id = repo.add(
        njr,
        result=_result(aggregate, provenance),
        files={"unsmoothed": encoded, "comfy_original": encoded},
    )
    return repo, job_id, frames


@dataclass
class FakeDecoder:
    """``decode_clip_to_frames`` without FFmpeg: writes ``count`` PNGs the way the real one names them."""

    count: int
    size: tuple[int, int] = SMALL
    decoded_path: Path | None = None
    calls: int = 0

    def __call__(
        self, clip: Path, out_dir: Path, cancel_token: CancelToken | None = None
    ) -> list[Path]:
        self.calls += 1
        self.decoded_path = clip
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        return [
            png(out_dir / f"d_{number:06d}.png", self.size, (number, 30, 60))
            for number in range(1, self.count + 1)
        ]


def encoded_only_job(
    tmp_path: Path, *, smoothed_fps: int | None = None, frame_count: int = 17
) -> tuple[FakeRepository, str, FakeDecoder]:
    """A finished TI2V-5B 1.2.0 clip: Comfy's own MP4 (plus a preview still), smoothed when asked."""

    settings = ti2v_encoded_settings(frame_count=frame_count)
    _smoothing(settings, tmp_path, smoothed_fps, TI2V_FPS)
    njr = clip_njr(tmp_path, settings)
    folder = run_dir(tmp_path, njr.job_id)
    original = _clip(folder / "wan22_ti2v_5b_00001_.mp4").resolve()
    preview = png(folder / "wan22_ti2v_5b_00001_.png", SMALL).resolve()
    provenance: dict[str, Any] = {}
    outputs = [original]
    if smoothed_fps is not None:
        smooth = _clip(folder / f"{original.stem}_smooth.mp4").resolve()
        provenance["interpolation"] = _interpolation(
            source=str(original),
            smooth=smooth,
            frames=frame_count,
            fps=TI2V_FPS,
            smoothed_fps=smoothed_fps,
        )
        outputs = [smooth, original]
    manifest = _backend_manifest(
        folder,
        njr=njr,
        output_paths=outputs,
        frame_paths=[preview],
        provenance_extra=provenance,
        manifest_extra=None,
    )
    aggregate = _aggregate(
        output_paths=outputs, frame_paths=[preview], manifest=manifest, source=None
    )
    repo = FakeRepository()
    job_id = repo.add(
        njr,
        result=_result(aggregate, provenance),
        files={"unsmoothed": original, "comfy_original": original},
    )
    return repo, job_id, FakeDecoder(count=frame_count)


def _sequence_njr(
    tmp_path: Path,
    segments: int,
    *,
    color_matched: bool,
    storyboard: StoryboardPlanLink | None = None,
) -> tuple[NormalizedJobRecord, SequencePlan]:
    intent: dict[str, Any] = {"segments": [{"frame_count": 17} for _ in range(segments)]}
    if color_matched:
        intent["color_match"] = True
    built = build_sequence_njr(
        njr_builder=builder(tmp_path),
        registry=REG,
        source_image_path=str(source_image(tmp_path)),
        form_data=a14b_settings(frame_count=17),
        sequence_intent=intent,
        storyboard=storyboard,
    )
    stage = dict(built.njr.stage_chain[0].extra)
    return built.njr, SequencePlan.from_dict(dict(stage["sequence_metadata"]))


def _ledger_segments(
    folder: Path, plan: SequencePlan, *, color_matched: bool
) -> list[LedgerSegment]:
    recorded: list[LedgerSegment] = []
    for spec in plan.segments:
        frames = tuple(
            FileRecord.of(
                png(
                    folder / f"seg{spec.index}_{number:05d}_.png",
                    SMALL,
                    (spec.index * 40, number, 90),
                )
            )
            for number in range(1, spec.frame_count + 1)
        )
        last = png(folder / "sequence" / "anchors" / f"seg_{spec.index:02d}_last.png", SMALL)
        shutil.copyfile(frames[-1].path, last)
        matched: tuple[FileRecord, ...] = ()
        if color_matched and spec.index > 0:
            matched = tuple(
                FileRecord.of(
                    png(
                        folder
                        / "sequence"
                        / "color_matched"
                        / f"seg_{spec.index:02d}"
                        / f"m_{n:06d}.png",
                        SMALL,
                        (spec.index * 40, n, 200),
                    )
                )
                for n in range(spec.frame_count - spec.overlap_frames)
            )
        recorded.append(
            LedgerSegment(
                index=spec.index,
                seed=spec.seed,
                expected_frame_count=spec.frame_count,
                frame_count=spec.frame_count,
                final_frame=FinalFrame(file=FileRecord.of(last), basis=BASIS_NATIVE),
                frames=frames,
                workflow_id=spec.workflow_id,
                workflow_version=spec.workflow_version,
                overlap_frames=spec.overlap_frames,
                color_matched=matched,
                color_match=None if not color_matched else {"transformed": spec.index > 0},
            )
        )
    return recorded


def _sequence_result(
    plan: SequencePlan, ledger: SequenceLedger, ledger_path: Path, sha: str
) -> dict[str, Any]:
    outcome = SequenceOutcome(ledger=ledger, ledger_path=ledger_path, ledger_sha256=sha)
    return {
        "success": True,
        "metadata": {"sequence_artifact": sequence_artifact_payload(outcome, plan)},
    }


def sequence_job(
    tmp_path: Path, *, segments: int = 2, color_matched: bool = False
) -> tuple[FakeRepository, str, list[str]]:
    """A finished v1 sequence job (17 frames a segment) and the exact frames it encoded, in order."""

    njr, plan = _sequence_njr(tmp_path, segments, color_matched=color_matched)
    folder = run_dir(tmp_path, njr.job_id)
    recorded = _ledger_segments(folder, plan, color_matched=color_matched)
    ledger = SequenceLedger(
        sequence_id=plan.sequence_id,
        job_id=str(njr.job_id),
        plan_sha256=plan.plan_sha256(),
        total_segments=len(plan.segments),
        policy_version=plan.policy_version,
        state=STATE_COMPLETED,
        segments=recorded,
    )
    ledger_path = folder / LEDGER_FILE_NAME
    sha = write_ledger(ledger_path, ledger)
    expected: list[str] = []
    for segment in recorded:
        used = segment.color_matched or segment.frames[segment.overlap_frames :]
        expected.extend(record.path for record in used)
    repo = FakeRepository()
    job_id = repo.add(njr, result=_sequence_result(plan, ledger, ledger_path, sha))
    return repo, job_id, expected


def take_job(tmp_path: Path, *, segments: int = 2) -> tuple[FakeRepository, str, list[str]]:
    """A finished storyboard take (policy v2, from a still root) with its cut manifest; returns its cut's frames."""

    link = StoryboardPlanLink(
        storyboard_id="sb-take",
        parent_id=ROOT_PARENT,
        take_ids=tuple(f"t{n + 1}" for n in range(segments)),
        handoff_index=None,
    )
    njr, plan = _sequence_njr(tmp_path, segments, color_matched=False, storyboard=link)
    folder = run_dir(tmp_path, njr.job_id)
    recorded = _ledger_segments(folder, plan, color_matched=False)
    cut = take_manifest(
        lead_in=None,
        segments=[
            (link.take_ids[s.index], s.frames, s.overlap_frames, s.final_frame.basis)
            for s in recorded
        ],
        fps=plan.fps,
        width=SMALL[0],
        height=SMALL[1],
        job_id=str(njr.job_id),
    )
    written = write_cut_manifest(folder / CUT_MANIFEST_FILE_NAME, cut)
    ledger = SequenceLedger(
        sequence_id=plan.sequence_id,
        job_id=str(njr.job_id),
        plan_sha256=plan.plan_sha256(),
        total_segments=len(plan.segments),
        policy_version=plan.policy_version,
        state=STATE_COMPLETED,
        segments=recorded,
        cut_manifest={"path": written.path, "sha256": written.sha256},
    )
    ledger_path = folder / LEDGER_FILE_NAME
    sha = write_ledger(ledger_path, ledger)
    repo = FakeRepository()
    job_id = repo.add(njr, result=_sequence_result(plan, ledger, ledger_path, sha))
    return repo, job_id, [frame.path for frame in cut.frames]


def svd_njr(tmp_path: Path) -> NormalizedJobRecord:
    """A native SVD clip job as ``SVDController`` builds it."""

    return ReprocessJobBuilder().build_reprocess_job(
        input_image_paths=[str(source_image(tmp_path))],
        stages=["svd_native"],
        config={"svd_native": SVDConfig().to_dict(), "pipeline": {"output_route": "SVD"}},
        output_dir=str(tmp_path),
        prompt="SVD animation source: source",
        pack_name="SVD",
    )


def refused_job(tmp_path: Path, kind: str) -> tuple[FakeRepository, str]:
    """A job a storyboard root must refuse: ``svd``, ``not_completed``, ``driving_video`` or ``missing_frames``."""

    if kind == "missing_frames":
        repo, job_id, frames = frames_out_job(tmp_path, count=17)
        frames[5].unlink()
        return repo, job_id
    repo = FakeRepository()
    if kind == "svd":
        return repo, repo.add(svd_njr(tmp_path), result={"success": True, "metadata": {}})
    if kind == "not_completed":
        njr = clip_njr(tmp_path, a14b_settings(frame_count=17))
        return repo, repo.add(njr, status=JobStatus.RUNNING)
    if kind == "driving_video":
        pose = _clip(tmp_path / "motion" / "dance.mp4")
        form = {
            "workflow_id": ANIMATE2_DRIVE_ID,
            "workflow_version": "1.0.0",
            "prompt": "the person dances",
            "frame_count": 17,
            "pose_video_path": str(pose),
            "experimental_opt_in": True,
        }
        return repo, repo.add(clip_njr(tmp_path, form), result={"success": True, "metadata": {}})
    raise ValueError(f"unknown refused job kind {kind!r}")


__all__ = [
    "A14B_FPS",
    "A14B_SIZE",
    "REG",
    "SMALL",
    "FakeDecoder",
    "FakeJob",
    "FakeRepository",
    "a14b_settings",
    "clip_njr",
    "comfy_original",
    "encoded_only_job",
    "frames_out_job",
    "overwrite_png",
    "png",
    "refused_job",
    "remove",
    "run_dir",
    "sequence_job",
    "svd_njr",
    "take_job",
    "ti2v_encoded_settings",
    "unsmoothed_mp4",
]
