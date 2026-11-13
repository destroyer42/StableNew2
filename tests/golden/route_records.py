"""One production-shaped record per compile route, plus the observation helpers the refusal and admission suites share.

Nothing here asserts; it only builds.  Each builder returns a record the route's real compiler produced (ids may be
random: the admission checks do not snapshot).  ``observe`` turns "what did this call do" into a plain, stable value
(exception type and message, or ``accepted``), which is what a refusal table freezes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.job_service import JobService
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.controller.svd_controller import SVDController
from src.pipeline.history_variation_compiler import HistoryVariationDraft, compile_history_variation
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.video.movie_assembly_compiler import (
    AssemblyIntentClip,
    MovieAssemblyIntent,
    VideoFacts,
    build_movie_assembly_njr,
    freeze_movie_assembly,
)
from src.video.sequence_resume import build_resume_njr
from src.video.svd_config import SVDConfig
from tests.golden.test_njr_golden_derivation import prompt_pack_parent
from tests.golden.test_njr_golden_generation import generic_builder, generic_config
from tests.golden.test_njr_golden_reprocess_video import (
    CapturingJobService,
    _failed_ledger,
    _sequence_parent,
    video_controller,
    video_form,
)
from tests.learning_v2.test_learning_independent_baseline_650 import Bench
from tests.pipeline.test_history_variation_compiler_610a import _source as variation_source


def observe(call: Callable[[], Any]) -> dict[str, str]:
    """What a call did: ``accepted``, or the exact exception type and message it refused with."""

    try:
        call()
    except Exception as exc:  # noqa: BLE001 - the type and text are the baseline
        return {"outcome": "refused", "type": type(exc).__name__, "message": str(exc)}
    return {"outcome": "accepted"}


@dataclass
class RouteEnv:
    tmp_path: Path
    copy_asset: Callable[..., Path]
    monkeypatch: pytest.MonkeyPatch


def _reprocess(env: RouteEnv) -> NormalizedJobRecord:
    source = env.copy_asset("blue_64.png", "in/first.png")
    plan = ReprocessJobBuilder(id_fn=lambda: "admit-reprocess").build_grouped_reprocess_jobs(
        items=[
            ReprocessSourceItem(
                input_image_path=str(source),
                prompt="a clean portrait",
                model="sdxl.safetensors",
                config={"img2img": {"denoising_strength": 0.4, "steps": 18}},
            )
        ],
        stages=["img2img"],
        output_dir=str(env.tmp_path / "output"),
    )
    return plan.jobs[0]


def _svd(env: RouteEnv) -> NormalizedJobRecord:
    env.monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda _config, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )
    env.monkeypatch.setattr(Path, "home", classmethod(lambda _cls: env.tmp_path / "home"))
    service = CapturingJobService()
    SVDController(
        app_controller=SimpleNamespace(
            output_dir=str(env.tmp_path / "output"), job_service=service
        ),
        svd_service=SimpleNamespace(),
    ).submit_svd_job(
        source_image_path=env.copy_asset("portrait_480x832.png", "in/svd.png"),
        config=SVDConfig.from_dict({"inference": {"num_frames": 25, "seed": 2024}}),
    )
    return service.submitted[0]


def _video(env: RouteEnv) -> NormalizedJobRecord:
    controller, service = video_controller(env.tmp_path)
    controller.submit_video_workflow_job(
        source_image_path=env.copy_asset("portrait_480x832.png", "in/video.png"),
        form_data=video_form(),
    )
    return service.submitted[0]


def _movie(env: RouteEnv) -> NormalizedJobRecord:
    clips = [
        env.copy_asset("still_red_40x30.png", "src/b.png"),
        env.copy_asset("still_blue_40x30.png", "src/a.png"),
    ]
    spec = freeze_movie_assembly(
        MovieAssemblyIntent(
            clips=tuple(AssemblyIntentClip(str(path), 0.5) for path in clips),
            fps=8,
            transition_seconds=0.125,
        ),
        video_probe=lambda _path: VideoFacts(8, 8, 1.0, None),
        audio_probe=lambda _path: None,
    )
    return build_movie_assembly_njr(
        spec,
        output_dir=env.tmp_path / "output",
        builder=ReprocessJobBuilder(id_fn=lambda: "admit-movie"),
    )


def _sequence_resume(env: RouteEnv) -> NormalizedJobRecord:
    parent, source = _sequence_parent(env.tmp_path, env.copy_asset)
    ledger = _failed_ledger(parent, source, env.tmp_path / "parent-run")
    return build_resume_njr(
        parent, stage_name="video_workflow", ledger_path=ledger, id_fn=lambda: "admit-resume"
    )


def _learning(env: RouteEnv) -> NormalizedJobRecord:
    bench = Bench(env.tmp_path)
    experiment = bench.preview()
    return bench.controller._build_variant_njr(bench.controller.learning_state.plan[0], experiment)


ROUTES: dict[str, Callable[[RouteEnv], NormalizedJobRecord]] = {
    "generic": lambda env: generic_builder().build_jobs(base_config=generic_config())[0],
    "prompt_pack": lambda env: prompt_pack_parent(env.tmp_path),
    "reprocess": _reprocess,
    "learning": _learning,
    "history_variation": lambda env: compile_history_variation(
        HistoryVariationDraft.from_source(variation_source()).with_edits(seed=5),
        id_fn=lambda: "admit-variation",
    ),
    "history_replay": lambda env: compile_replay_intent(
        ReplayIntent(variation_source()), id_fn=lambda: "admit-replay"
    ),
    "video_workflow": _video,
    "native_svd": _svd,
    "movie_clips": _movie,
    "sequence": lambda env: _sequence_parent(env.tmp_path, env.copy_asset)[0],
    "sequence_resume": _sequence_resume,
}


@contextmanager
def real_job_service(root: Path) -> Iterator[JobService]:
    """The production ``JobService`` over the SQLite queue and repository; no runner is started."""

    repository = JobRepository(root / "state" / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(
        queue,
        runner=SingleNodeJobRunner(queue, run_callable=None, poll_interval=0.01),
        history_store=repository,
    )
    service.auto_run_enabled = False
    try:
        yield service
    finally:
        service.stop()
        repository.close()


def admit(service: JobService, record: NormalizedJobRecord) -> dict[str, str]:
    return observe(lambda: service.submit_njrs([record], SubmissionPolicy()))
