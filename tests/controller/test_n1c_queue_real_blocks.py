"""N1 follow-up: five real blocks that were dispatch-only are refused at Queue (``JobService.submit_njrs``).

``AGENTS.md`` section 2: "A block is reported as early as it can be known. Dispatch re-checks only what can change
while a job waits." Each refusal says what to do, nothing reaches the queue, and the same job is admitted once the
cause is gone. The dispatch copies stay for work admitted before the Queue checks existed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import src.image_backends.forge_webui_backend as forge_backend_module
import src.video.movie_assembly_engine as assembly_engine
from src.controller.job_service import JobService
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_ID
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from src.queue.job_queue import JobQueue
from src.video.movie_assembly_compiler import (
    AssemblyIntentClip,
    MovieAssemblyIntent,
    VideoFacts,
    build_movie_assembly_njr,
    freeze_movie_assembly,
)
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

KLEIN = "flux-2-klein-4b-fp8.safetensors"
DETECTOR = {"adetailer_model": "face_yolov8n.pt"}


class _Runner:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def is_running(self) -> bool:
        return self.started

    def run_once(self, job):  # pragma: no cover - nothing is dispatched here
        raise AssertionError("dispatch is never reached")

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        return None


def _service() -> JobService:
    return JobService(JobQueue(), runner=_Runner())


def _refused(record, match: str) -> None:
    service = _service()
    with pytest.raises(ValueError, match=match):
        service.submit_njrs([record])
    assert (
        service.job_queue.list_jobs() == []
    )  # nothing waits in the queue to fail after the operator left


def _admitted(record) -> None:
    service = _service()
    assert service.submit_njrs([record]) == [record.job_id]


def _image_njr(
    *,
    job_id: str,
    backend: str,
    chain: tuple,
    config: dict | None = None,
    profile: dict | None = None,
):
    image: dict = {"backend_id": backend}
    if profile is not None:
        image["model_profile"] = profile
    return make_pipeline_njr(
        job_id=job_id,
        positive_prompt="a lighthouse at dusk",
        base_model=str(chain[0].model),
        stage_chain=chain,
        config=config or {},
        backend_options={"image": image},
    )


def _host(monkeypatch: pytest.MonkeyPatch, total_bytes: int) -> None:
    monkeypatch.setattr(
        forge_backend_module,
        "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=total_bytes, available_bytes=total_bytes // 2),
    )


# 1. Klein profile: the 32-GB-class host-RAM minimum (a fixed host fact; owner Q3 keeps it a block).


def test_a_klein_job_on_a_host_below_32_gb_is_refused_at_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _image_njr(
        job_id="n1c-klein",
        backend="forge_webui",
        chain=(make_stage_config("txt2img", model=KLEIN),),
        profile={"id": KLEIN_PROFILE_ID, "version": 1},
    )
    _host(monkeypatch, 17_000_000_000)
    _refused(
        record,
        r"32-GB-class host.*Nothing was queued\. Run this model on a host with at least 32 GB of RAM",
    )
    _host(monkeypatch, 34_107_092_992)
    _admitted(record)


# 2. Hypernetworks on Forge Neo (the pinned runtime removed them).


def test_a_hypernetwork_on_forge_is_refused_at_queue() -> None:
    chain = (make_stage_config("txt2img", model="sdxl.safetensors"),)
    record = _image_njr(
        job_id="n1c-hn", backend="forge_webui", chain=chain, config={"hypernetwork": "ink_wash"}
    )
    _refused(
        record,
        r"Hypernetworks are not supported by the Forge runtime.*ink_wash.*Nothing was queued\. Remove the "
        r"hypernetwork, or select the A1111 compatibility runtime",
    )
    _admitted(
        _image_njr(
            job_id="n1c-hn-a1111",
            backend="a1111_webui",
            chain=chain,
            config={"hypernetwork": "ink_wash"},
        )
    )


# 3. Localized-only ADetailer on A1111 (it needs the managed Forge runtime's companion extension).


def _adetailer_chain(mode: str | None) -> tuple:
    extra = dict(DETECTOR) if mode is None else {**DETECTOR, "adetailer_execution_mode": mode}
    return (
        make_stage_config("txt2img", model="sdxl.safetensors"),
        make_stage_config("adetailer", model="sdxl.safetensors", extra=extra),
    )


def test_localized_only_adetailer_on_a1111_is_refused_at_queue() -> None:
    _refused(
        _image_njr(
            job_id="n1c-adl", backend="a1111_webui", chain=_adetailer_chain("localized_only")
        ),
        r"cannot run StableNew's localized-only ADetailer.*Nothing was queued\. Switch the image runtime to Forge",
    )
    _admitted(
        _image_njr(
            job_id="n1c-adl-forge", backend="forge_webui", chain=_adetailer_chain("localized_only")
        )
    )
    # A configuration compiled before the mode existed keeps its whole-image behavior and still runs on A1111.
    _admitted(
        _image_njr(job_id="n1c-adl-legacy", backend="a1111_webui", chain=_adetailer_chain(None))
    )


# 4. FFmpeg missing for Movie Clips assembly.


def _assembly_njr(tmp_path: Path):
    stills = []
    for name, rgb in (("b.png", (200, 0, 0)), ("a.png", (0, 0, 200))):
        path = tmp_path / name
        Image.new("RGB", (40, 30), rgb).save(path)
        stills.append(path)
    intent = MovieAssemblyIntent(
        clips=tuple(AssemblyIntentClip(str(path), 0.5) for path in stills),
        fps=8,
        transition_seconds=0.125,
    )
    spec = freeze_movie_assembly(
        intent, video_probe=lambda p: VideoFacts(8, 8, 1.0, None), audio_probe=lambda p: None
    )
    return build_movie_assembly_njr(spec, output_dir=tmp_path / "output")


def test_movie_clips_without_ffmpeg_are_refused_at_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _assembly_njr(tmp_path)
    monkeypatch.setattr(assembly_engine, "resolve_ffmpeg_executable", lambda: None)
    _refused(
        record,
        r"FFmpeg was not found.*Nothing was queued\. Install FFmpeg or set STABLENEW_FFMPEG_PATH",
    )
    monkeypatch.setattr(
        assembly_engine, "resolve_ffmpeg_executable", lambda: tmp_path / "ffmpeg.exe"
    )
    _admitted(record)


def test_dispatch_keeps_its_ffmpeg_check_for_work_admitted_earlier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FFmpeg can be removed while a job waits, so the engine re-checks before it writes anything."""

    record = _assembly_njr(tmp_path)
    from src.video.movie_assembly_models import MovieAssemblySpec

    spec = MovieAssemblySpec.from_dict(record.config["movie_assembly"])
    monkeypatch.setattr(assembly_engine, "resolve_ffmpeg_executable", lambda: None)
    with pytest.raises(
        assembly_engine.MovieAssemblyError, match="FFmpeg was not found.*Install FFmpeg"
    ):
        assembly_engine.run_movie_assembly(spec, run_dir=tmp_path / "run")
    assert not (tmp_path / "run").exists()


# 5. RIFE smoothing requested on a workflow that declares no frame rate.


def test_rife_without_a_frame_rate_is_refused_at_queue(tmp_path: Path) -> None:
    from tests.video.test_n1_experimental_warning import _build

    rife = tmp_path / "rife-ncnn-vulkan.exe"
    rife.write_bytes(b"stand-in executable; nothing is run")
    # wan22_ti2v_5b_i2v_v1 1.0.0 declares neither a frame-count policy nor a frames-out rate.
    smoothing = {"enabled": True, "multiplier": 2, "executable_path": str(rife)}
    record, _controller = _build(
        tmp_path, "1.0.0", experimental_opt_in=True, interpolation=smoothing
    )
    assert record.config["video_workflow"]["interpolation"]["enabled"] is True
    _refused(
        record,
        r"declares no frame rate, so RIFE smoothing cannot choose an output rate\. Nothing was queued\. Turn off "
        r"RIFE smoothing for this job, or choose a workflow that declares a frame rate",
    )
    # The same workflow at a version that declares its rate is admitted with smoothing on.
    declared, _controller = _build(
        tmp_path, "1.1.0", experimental_opt_in=True, interpolation=smoothing
    )
    _admitted(declared)


def test_dispatch_keeps_its_rife_rate_check_with_its_own_outcome() -> None:
    from types import SimpleNamespace

    from src.video.workflow_frame_count import interpolation_source_fps

    spec = SimpleNamespace(workflow_id="no_rate", backend_defaults={}, declared_input_names=())
    with pytest.raises(ValueError, match=r"Nothing was generated\. Turn off RIFE smoothing"):
        interpolation_source_fps(spec, {})
    assert interpolation_source_fps(spec, {"fps": 16}) == 16
