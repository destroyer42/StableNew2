"""PR-VID-SEQ-330-CORE through the real runner: one NJR, one queue row, one ``run_njr`` call, N internal segments.

A fake Comfy backend and a fake SVD pipeline write small real PNGs; FFmpeg tests skip when FFmpeg is absent. No GPU,
runtime or network is touched, and nothing is registered in the workflow catalog.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.controller.svd_controller import SVDController
from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.video import resolve_ffmpeg_executable
from src.services.runtime_transition_service import RuntimeTransitionCoordinator
from src.video import ComfyWorkflowVideoBackend, VideoBackendRegistry, VideoExecutionResult
from src.video.sequence_ledger import LEDGER_FILE_NAME, STATE_FAILED, read_ledger, sha256_of
from src.video.sequence_plan import SequencePlanError
from src.video.sequence_resume import SequenceResumeError, build_resume_njr
from src.video.svd_config import SVDConfig
from src.video.svd_native_backend import SVDNativeVideoBackend

needs_ffmpeg = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None, reason="FFmpeg is not installed"
)
WORKFLOW = "wan22_ti2v_5b_i2v_v1"


def _png(path: Path, shade: int, size: tuple[int, int] = (480, 832)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (shade % 256, (shade * 5) % 256, 60)).save(path)
    return path


def _sha(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeComfy:
    """Stands in for the Comfy backend: writes real frames, records every request, offers the sequence release."""

    backend_id = "comfy"
    capabilities = ComfyWorkflowVideoBackend.capabilities

    def __init__(self, *, fail_on: int | None = None, frames_out: bool = True) -> None:
        self.fail_on = fail_on
        self.frames_out = frames_out
        self.requests: list[dict[str, Any]] = []
        self.releases: list[list[tuple[str, str]]] = []

    def execute(self, pipeline: Any, request: Any) -> VideoExecutionResult:
        index = len(self.requests)
        config = dict(request.stage_config)
        self.requests.append(
            {
                "job_id": request.job_id,
                "hold_runtime": request.hold_runtime,
                "input": str(request.input_image_path),
                "input_sha": _sha(request.input_image_path),
                "seed": config.get("seed"),
                "frame_count": config.get("frame_count"),
                "workflow_version": request.workflow_version,
                "config_workflow_version": config.get("workflow_version"),
                "execution_version": (config.get("video_execution") or {}).get("workflow_version"),
                "prompt": request.prompt,
                "has_sequence_block": "sequence_metadata" in config,
            }
        )
        if self.fail_on == index:
            raise RuntimeError("the runtime fell over")
        out = Path(request.output_dir)
        frames = [
            _png(out / f"{request.job_id}_{n:05d}_.png", int(config["seed"]) % 200 + n * 7)
            for n in range(1, int(config["frame_count"]) + 1)
        ]
        clip = out / f"{request.job_id}.mp4"
        clip.write_bytes(b"clip")
        result: dict[str, Any] = {
            "path": str(clip),
            "video_path": str(clip),
            "output_paths": [str(clip)],
            "frame_paths": [str(frame) for frame in frames],
            "manifest_path": None,
            "artifact": {
                "schema": "stablenew.artifact.v2.6",
                "stage": "video_workflow",
                "artifact_type": "video",
                "primary_path": str(clip),
                "output_paths": [str(clip)],
                "manifest_path": None,
                "input_image_path": str(request.input_image_path),
            },
        }
        if self.frames_out:
            result["frames_out"] = {
                "last_frame_path": str(frames[-1]),
                "last_frame_sha256": _sha(frames[-1]),
                "frame_count": len(frames),
            }
        else:
            result["frame_paths"] = []  # an encoded clip only: the decoded fallback applies
        return VideoExecutionResult.from_stage_result(
            backend_id="comfy",
            stage_name="video_workflow",
            result=result,
            backend_metadata={},
            replay_manifest_fragment={},
        )

    def release_for_sequence(self, workflows: Any) -> dict[str, Any]:
        self.releases.append(list(workflows))
        return {"released": True, "ownership": "stablenew"}


def _runner(tmp_path: Path, backend: Any) -> PipelineRunner:
    registry = VideoBackendRegistry()
    registry.register(backend)
    runner = PipelineRunner(
        Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"), video_backend_registry=registry
    )
    runner._pipeline = Mock()
    return runner


class _Queue:
    def __init__(self) -> None:
        self.jobs: dict[str, Any] = {}

    def get_job(self, job_id: str) -> Any:
        return self.jobs.get(job_id)


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self.queue = _Queue()

    def submit_njrs(self, njrs: Any, policy: Any) -> list[str]:
        self.calls.append(list(njrs))
        return [f"queued-{len(self.calls)}-{i}" for i, _ in enumerate(njrs)]


def _controller(tmp_path: Path) -> tuple[VideoWorkflowController, _JobService]:
    service = _JobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app), service


def _form(**kw: Any) -> dict[str, Any]:
    return {
        "workflow_id": WORKFLOW,
        "workflow_version": "1.3.0",
        "prompt": "the person waves",
        "frame_count": 17,
        **kw,
    }


def _intent(count: int = 3, **seg: Any) -> dict[str, Any]:
    return {
        "segments": [{"frame_count": 17, "seed": 100 + i, **seg} for i in range(count)],
        "assembly": {"clip_name": "walk", "quality": "draft"},
    }


def _built(tmp_path: Path, intent: dict[str, Any] | None = None, **form: Any):
    controller, service = _controller(tmp_path)
    source = _png(tmp_path / "source.png", 9)
    built = controller.build_sequence_job(
        source_image_path=str(source), form_data=_form(**form), sequence_intent=intent or _intent()
    )
    return controller, service, built


# ----------------------------------------------------------------------------- admission through the controller


def test_a_sequence_is_admitted_as_one_njr_through_one_submit(tmp_path: Path) -> None:
    controller, service = _controller(tmp_path)
    source = _png(tmp_path / "source.png", 9)

    job_id = controller.submit_sequence_job(
        source_image_path=str(source), form_data=_form(), sequence_intent=_intent(3)
    )

    assert (
        job_id == "queued-1-0" and len(service.calls) == 1 and len(service.calls[0]) == 1
    )  # ONE NJR, ONE submit
    stage = service.calls[0][0].stage_chain[0]
    plan = dict(stage.extra)["sequence_metadata"]
    assert [s["seed"] for s in plan["segments"]] == [100, 101, 102]
    assert (
        plan["segments"][0]["anchor_policy"] == "source"
        and plan["segments"][1]["anchor_policy"] == "carry_last_frame"
    )
    assert plan["fps"] == 24 and plan["target_width"] and plan["target_height"]
    assert service.calls[0][0].workload.config["video_workflow"]["sequence_metadata"] == plan


def test_illegal_intents_are_refused_before_anything_is_queued(tmp_path: Path) -> None:
    controller, service = _controller(tmp_path)
    source = str(_png(tmp_path / "source.png", 9))
    bad = [
        (_form(), _intent(13), "more than the 12"),
        (_form(), {"segments": [{"frame_count": 17}, {"frame_count": 18}]}, "cannot generate"),
        (
            _form(),
            {"segments": [{"frame_count": 17}, {"frame_count": 17, "bogus": 1}]},
            "unknown segment 1",
        ),
        (_form(interpolation={"enabled": True}), _intent(2), "not applied inside a sequence"),
    ]
    for form, intent, needle in bad:
        with pytest.raises((SequencePlanError, ValueError), match=needle):
            controller.submit_sequence_job(
                source_image_path=source, form_data=form, sequence_intent=intent
            )

    assert service.calls == []


def test_the_njr_is_never_mutated_by_running_it(tmp_path: Path) -> None:
    backend = FakeComfy()
    _controller_, _service, built = _built(tmp_path)
    before = json.dumps(built.njr.to_queue_snapshot(), sort_keys=True, default=str)

    _runner(tmp_path, backend).run_njr(built.njr, cancel_token=None)

    assert json.dumps(built.njr.to_queue_snapshot(), sort_keys=True, default=str) == before


# ----------------------------------------------------------------------------- end to end through run_njr


@needs_ffmpeg
def test_one_run_njr_call_runs_every_segment_assembles_and_releases_once(tmp_path: Path) -> None:
    backend = FakeComfy()
    _c, _s, built = _built(
        tmp_path,
        {
            "segments": [
                {"frame_count": 17, "seed": 11, "workflow_version": "1.2.0"},
                {"frame_count": 21, "seed": 22, "prompt": "turns away"},
                {"frame_count": 17, "seed": 33, "overlap_frames": 1},
            ],
            "assembly": {"clip_name": "walk", "quality": "draft"},
        },
    )

    result = _runner(tmp_path, backend).run_njr(built.njr, cancel_token=None)

    assert result.success is True, result.error
    job_id = built.njr.job_id
    assert [r["job_id"] for r in backend.requests] == [
        f"{job_id}_seg00",
        f"{job_id}_seg01",
        f"{job_id}_seg02",
    ]
    assert [r["hold_runtime"] for r in backend.requests] == [True, True, True]
    assert [(r["seed"], r["frame_count"]) for r in backend.requests] == [
        (11, 17),
        (22, 21),
        (33, 17),
    ]
    assert [r["workflow_version"] for r in backend.requests] == ["1.2.0", "1.3.0", "1.3.0"]
    assert [r["execution_version"] for r in backend.requests] == [
        "1.2.0",
        "1.3.0",
        "1.3.0",
    ]  # the intent block too
    assert [r["prompt"] for r in backend.requests] == [
        "the person waves",
        "turns away",
        "the person waves",
    ]
    assert Path(backend.requests[0]["input"]).name.endswith(".png")
    assert all(Path(r["input"]).suffix == ".png" for r in backend.requests)
    assert backend.releases == [
        [(WORKFLOW, "1.2.0"), (WORKFLOW, "1.3.0"), (WORKFLOW, "1.3.0")]
    ]  # ONE release

    artifact = result.metadata["sequence_artifact"]
    assert artifact["is_complete"] is True and artifact["completed_segments"] == 3
    ledger = read_ledger(Path(artifact["ledger_path"]), expected_sha256=artifact["ledger_sha256"])
    assert [s.frame_count for s in ledger.segments] == [17, 21, 17]
    for position in (1, 2):  # the carried frame is the exact PNG of the segment before it
        assert (
            backend.requests[position]["input_sha"]
            == ledger.segments[position - 1].final_frame.file.sha256
        )
    movie = Path(artifact["assembled_video"]["output_path"])
    assert movie.name == "walk.mp4" and movie.is_file()
    assert (
        artifact["assembled_video"]["total_frames"] == 17 + 20 + 16
    )  # each carried segment drops the one frame that re-renders its anchor
    assert result.metadata["video_primary_artifact"]["primary_path"] == str(movie)
    assert result.metadata["assembled_video_artifact"]["primary_path"] == str(movie)


def test_a_failed_segment_leaves_a_resumable_ledger_and_still_releases_once(tmp_path: Path) -> None:
    backend = FakeComfy(fail_on=2)
    _c, _s, built = _built(tmp_path, _intent(4))

    result = _runner(tmp_path, backend).run_njr(built.njr, cancel_token=None)

    assert result.success is False and "fell over" in str(result.error)
    assert len(backend.requests) == 3 and len(backend.releases) == 1
    pointer = result.metadata["sequence_artifact"]  # the pointer survives a failed run
    ledger = read_ledger(Path(pointer["ledger_path"]))
    assert ledger.state == STATE_FAILED and [s.index for s in ledger.segments] == [0, 1]
    assert pointer["completed_segments"] == 2 and pointer["ledger_state"] == "failed"


def test_cancelling_through_run_njr_keeps_the_prefix_and_releases_the_runtime_once(
    tmp_path: Path,
) -> None:
    token = CancelToken()

    class CancellingComfy(FakeComfy):
        def execute(self, pipeline: Any, request: Any) -> VideoExecutionResult:
            result = super().execute(pipeline, request)
            if len(self.requests) == 2:
                token.cancel()  # arrives just as segment 1 finishes
            return result

    backend = CancellingComfy()
    _c, _s, built = _built(tmp_path, _intent(4))

    with pytest.raises(CancellationError):
        _runner(tmp_path, backend).run_njr(built.njr, cancel_token=token)

    assert len(backend.requests) == 2 and len(backend.releases) == 1
    [ledger_path] = list(tmp_path.rglob(LEDGER_FILE_NAME))
    ledger = read_ledger(ledger_path)
    assert ledger.state == "cancelled"
    assert [s.index for s in ledger.segments] == [0, 1]  # the segment that was finishing is kept
    assert ledger.runtime_release == {"released": True, "ownership": "stablenew"}


@needs_ffmpeg
def test_a_resume_is_a_new_njr_that_runs_only_the_unfinished_suffix(tmp_path: Path) -> None:
    failing = FakeComfy(fail_on=2)
    controller, service, built = _built(tmp_path, _intent(4))
    parent = _runner(tmp_path, failing).run_njr(built.njr, cancel_token=None)
    ledger_path = parent.metadata["sequence_artifact"]["ledger_path"]
    parent_bytes = Path(ledger_path).read_bytes()

    child = build_resume_njr(built.njr, stage_name="video_workflow", ledger_path=ledger_path)

    assert child.job_id != built.njr.job_id
    assert (
        child.source.parent_job_id == built.njr.job_id
    )  # lineage on the canonical replay identity
    block = dict(child.stage_chain[0].extra)["sequence_resume"]
    assert block["from_segment"] == 2 and block["parent_job_id"] == built.njr.job_id
    assert (
        dict(built.njr.stage_chain[0].extra).get("sequence_resume") is None
    )  # the parent is not mutated

    healthy = FakeComfy()
    run = _runner(tmp_path / "second", healthy).run_njr(child, cancel_token=None)

    assert run.success is True, run.error
    assert [r["seed"] for r in healthy.requests] == [102, 103]  # only segments 2 and 3
    artifact = run.metadata["sequence_artifact"]
    assert artifact["completed_segments"] == 4 and artifact["is_complete"] is True
    resumed = read_ledger(Path(artifact["ledger_path"]))
    assert resumed.parent["job_id"] == built.njr.job_id
    parent_run, child_run = Path(ledger_path).parent, Path(artifact["ledger_path"]).parent
    assert parent_run != child_run
    for prefix in resumed.segments[
        :2
    ]:  # copied into the child's own run, never pointing back at the parent
        for record in prefix.artifact_files():
            assert child_run in Path(record.path).parents
            assert parent_run not in Path(record.path).parents
    assert Path(ledger_path).read_bytes() == parent_bytes  # the parent's ledger was only ever read
    # segment 2 started from the COPIED last frame of segment 1, verified by hash
    assert healthy.requests[0]["input_sha"] == resumed.segments[1].final_frame.file.sha256
    del controller, service


def test_resume_sequence_job_queues_one_new_job_and_refuses_a_tampered_checkpoint(
    tmp_path: Path,
) -> None:
    failing = FakeComfy(fail_on=2)
    controller, service, built = _built(tmp_path, _intent(3))
    parent = _runner(tmp_path, failing).run_njr(built.njr, cancel_token=None)
    service.queue.jobs[built.njr.job_id] = SimpleNamespace(
        _normalized_record=built.njr, result={"metadata": parent.metadata}
    )

    queued = controller.resume_sequence(built.njr.job_id)

    assert queued.startswith("queued-1") and len(service.calls) == 1 and len(service.calls[0]) == 1
    assert service.calls[0][0].source.parent_job_id == built.njr.job_id

    ledger = read_ledger(Path(parent.metadata["sequence_artifact"]["ledger_path"]))
    Path(ledger.segments[0].frames[0].path).write_bytes(b"tampered")
    with pytest.raises(SequenceResumeError, match="changed since it was recorded"):
        controller.resume_sequence(built.njr.job_id)
    assert len(service.calls) == 1  # nothing further was queued

    with pytest.raises(SequenceResumeError, match="not a known sequence job"):
        controller.resume_sequence("nope")


def test_a_decoded_fallback_workflow_runs_with_an_explicit_basis(
    tmp_path: Path, monkeypatch
) -> None:
    import src.video.sequence_frames as frames_module

    calls: list[Path] = []

    def decode(clip: Path, out_dir: Path, _cancel: Any = None) -> list[Path]:
        calls.append(clip)
        return [_png(out_dir / f"d_{n:06d}.png", 40 + n) for n in range(1, 18)]

    monkeypatch.setattr(frames_module, "decode_clip_to_frames", decode)
    monkeypatch.setattr("src.pipeline.video_sequence_executor.decode_clip_to_frames", decode)
    backend = FakeComfy(frames_out=False)
    _c, _s, built = _built(tmp_path, {**_intent(2), "assembly": {"enabled": False}})

    result = _runner(tmp_path, backend).run_njr(built.njr, cancel_token=None)

    assert result.success is True, result.error
    ledger = read_ledger(Path(result.metadata["sequence_artifact"]["ledger_path"]))
    assert [s.final_frame.basis for s in ledger.segments] == ["decoded", "decoded"]
    assert ledger.segments[0].final_frame.detail["decoded_frame_count"] == 17
    assert len(calls) == 2


# ----------------------------------------------------------------------------- what must not change


def test_a_single_clip_job_is_exactly_what_it_was(tmp_path: Path) -> None:
    backend = FakeComfy()
    controller, _service = _controller(tmp_path)
    source = _png(tmp_path / "source.png", 9)
    frozen = controller._njr_builder.freeze_inputs(str(source), _form())
    built = controller._njr_builder.build_job(_form(), frozen)

    result = _runner(tmp_path, backend).run_njr(built.njr, cancel_token=None)

    assert result.success is True, result.error
    [request] = backend.requests
    assert request["hold_runtime"] is False and request["job_id"] == built.njr.job_id
    assert request["has_sequence_block"] is False
    assert backend.releases == []  # the backend's own per-job policy owns a single clip's release
    assert not list((tmp_path / "runs").rglob(LEDGER_FILE_NAME))
    assert "sequence_artifact" not in result.metadata


def test_a_block_in_the_retired_shape_is_refused_with_a_readable_reason(tmp_path: Path) -> None:
    _c, _s, built = _built(tmp_path)
    stage = built.njr.stage_chain[0]
    legacy = {**dict(stage.extra), "sequence_metadata": {"sequence_id": "old", "total_segments": 2}}
    config = {**built.njr.workload.config, "video_workflow": legacy}
    njr = replace(
        built.njr,
        stages=(replace(stage, extra=legacy),),
        workload=replace(built.njr.workload, config=config),
    )

    result = _runner(tmp_path, FakeComfy()).run_njr(njr, cancel_token=None)

    assert result.success is False and "before PR-VID-SEQ-330" in str(result.error)


# ----------------------------------------------------------------------------- native SVD


class FakeSvdPipeline:
    """Stands in for ``run_svd_native_stage``: honours the overridden config and the capture request."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run_svd_native_stage(
        self,
        *,
        input_image_path,
        stage_config,
        output_dir,
        job_id,
        cancel_token=None,
        context_metadata=None,
    ) -> dict[str, Any]:
        config = SVDConfig.from_dict(stage_config)
        self.calls.append(
            {
                "job_id": job_id,
                "seed": config.inference.seed,
                "num_frames": config.inference.num_frames,
                "save_frames": config.output.save_frames,
                "input_sha": _sha(input_image_path),
                "capture": (context_metadata or {}).get("sequence_capture"),
                "has_sequence_block": "sequence_metadata" in stage_config,
            }
        )
        out = Path(output_dir)
        frames = [
            _png(
                out / f"{job_id}_frame_{n:03d}.png",
                config.inference.seed % 100 + n * 5,
                (1024, 576),
            )
            for n in range(config.inference.num_frames)
        ]
        native = None
        capture = (context_metadata or {}).get("sequence_capture")
        if capture:
            path = _png(
                Path(capture["native_final_frame_path"]), 222, (1024, 576)
            )  # pre-RIFE: not an exported frame
            native = {
                "path": str(path),
                "sha256": _sha(path),
                "frame_index": config.inference.num_frames - 1,
            }
        clip = out / f"{job_id}.mp4"
        clip.write_bytes(b"svd")
        return {
            "stage": "svd_native",
            "path": str(clip),
            "output_paths": [str(clip)],
            "video_path": str(clip),
            "frame_paths": [str(f) for f in frames],
            "frame_count": len(frames),
            "fps": config.inference.fps,
            "native_final_frame": native,
            "postprocess": {"applied": ["interpolation"]},
            "manifest_path": None,
            "artifact": {
                "schema": "stablenew.artifact.v2.6",
                "stage": "svd_native",
                "artifact_type": "video",
                "primary_path": str(clip),
                "output_paths": [str(clip)],
                "manifest_path": None,
                "input_image_path": str(input_image_path),
            },
        }


@needs_ffmpeg
def test_native_svd_runs_as_a_sequence_with_the_pre_postprocess_final_frame(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_a, **_k: SimpleNamespace(available=True, blocking_reasons=()),
    )
    service = _JobService()
    controller = SVDController(
        app_controller=SimpleNamespace(job_service=service, output_dir=str(tmp_path / "out"))
    )
    source = _png(tmp_path / "svd_source.png", 3, (1024, 576))

    job_id = controller.submit_sequence_job(
        source_image_path=source,
        config=SVDConfig(),
        intent={
            "segments": [{"frame_count": 4, "seed": 5}, {"frame_count": 6, "seed": 6}],
            "assembly": {"clip_name": "svd_seq", "quality": "draft"},
        },
    )
    assert job_id.startswith("queued-1") and len(service.calls[0]) == 1
    njr = service.calls[0][0]
    assert dict(njr.stage_chain[0].extra)["sequence_metadata"]["stage"] == "svd_native"

    pipeline = FakeSvdPipeline()
    registry = VideoBackendRegistry()
    # Hermetic runtime transition: a developer's real local A1111/Comfy must not influence dispatch.
    registry.register(
        SVDNativeVideoBackend(
            transition=RuntimeTransitionCoordinator(
                webui_manager_getter=lambda: None,
                comfy_manager_getter=lambda: None,
                svd_service_factory=lambda: Mock(),
                webui_endpoint_present=lambda: False,
                comfy_endpoint_present=lambda: False,
            )
        )
    )
    runner = PipelineRunner(
        Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"), video_backend_registry=registry
    )
    runner._pipeline = pipeline

    result = runner.run_njr(njr, cancel_token=None)

    assert result.success is True, result.error
    assert [(c["seed"], c["num_frames"], c["save_frames"]) for c in pipeline.calls] == [
        (5, 4, True),
        (6, 6, True),
    ]
    assert all(
        c["capture"]["native_final_frame_path"].endswith("native_last.png") for c in pipeline.calls
    )
    ledger = read_ledger(Path(result.metadata["sequence_artifact"]["ledger_path"]))
    first = ledger.segments[0].final_frame
    assert first.basis == "native" and first.detail["origin"] == "svd_native_pre_postprocess"
    assert (
        pipeline.calls[1]["input_sha"] == first.file.sha256
    )  # segment 1 started from the NATIVE frame
    assert first.file.sha256 != ledger.segments[0].frames[-1].sha256
    assert (
        result.metadata["sequence_artifact"]["assembled_video"]["total_frames"] == 4 + 5
    )  # segment 1 drops its anchor-repeating first frame
    assert sha256_of(Path(result.metadata["sequence_artifact"]["assembled_video"]["output_path"]))


def test_the_svd_runner_saves_the_native_last_frame_only_when_asked(tmp_path: Path) -> None:
    from src.video.svd_runner import SVDRunner

    frames = [Image.new("RGB", (16, 16), (i * 20, 0, 0)) for i in range(3)]
    target = tmp_path / "native" / "last.png"

    saved = SVDRunner._capture_native_final_frame(
        frames, {"sequence_capture": {"native_final_frame_path": str(target)}}
    )

    assert saved is not None and saved["frame_index"] == 2 and saved["sha256"] == _sha(target)
    assert Image.open(target).getpixel((0, 0)) == (
        40,
        0,
        0,
    )  # the LAST generated frame, as generated
    assert SVDRunner._capture_native_final_frame(frames, None) is None
    assert SVDRunner._capture_native_final_frame(frames, {"other": 1}) is None
    assert (
        SVDRunner._capture_native_final_frame(
            [], {"sequence_capture": {"native_final_frame_path": str(target)}}
        )
        is None
    )


@needs_ffmpeg
def test_continuity_and_plan_origin_provenance_is_kept_on_the_sequence_artifact(
    tmp_path: Path,
) -> None:
    _c, _s, built = _built(tmp_path, {**_intent(2), "assembly": {"enabled": False}})
    link = {
        "pack_id": "cont-seq-001",
        "pack_summary": {"pack_id": "cont-seq-001", "display_name": "Sequence Pack"},
    }
    njr = replace(built.njr, workload=replace(built.njr.workload, continuity_link=link))

    result = _runner(tmp_path, FakeComfy()).run_njr(njr, cancel_token=None)

    assert result.success is True, result.error
    assert result.metadata["continuity"]["pack_id"] == "cont-seq-001"
    assert result.metadata["sequence_artifact"]["continuity_link"]["pack_id"] == "cont-seq-001"


@needs_ffmpeg
def test_plan_origin_carried_in_the_njr_metadata_is_stamped_on_the_sequence_artifact(
    tmp_path: Path,
) -> None:
    _c, _s, built = _built(tmp_path, {**_intent(2), "assembly": {"enabled": False}})
    origin = {"plan_id": "story-001", "scene_id": "scene-001", "shot_id": "shot-001"}
    provenance = replace(
        built.njr.provenance, metadata={**built.njr.provenance.metadata, "plan_origin": origin}
    )

    result = _runner(tmp_path, FakeComfy()).run_njr(
        replace(built.njr, provenance=provenance), cancel_token=None
    )

    assert result.success is True, result.error
    assert result.metadata["plan_origin"]["plan_id"] == "story-001"
    assert result.metadata["sequence_artifact"]["plan_origin"]["shot_id"] == "shot-001"
