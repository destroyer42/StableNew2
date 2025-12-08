from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord

pytest_plugins = ["tests.controller.conftest"]

SNAPSHOT_DIR = Path("tests/data/snapshots")


@pytest.fixture
def snapshot_loader():
    def _load(name: str) -> dict[str, any]:
        path = SNAPSHOT_DIR / f"{name}.json"
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return _load


@pytest.fixture
def pipeline_controller_with_stubs(job_service_with_stub_runner_factory):
    service, _, _ = job_service_with_stub_runner_factory
    controller = object.__new__(PipelineController)
    controller._job_service = service
    controller._app_state = None
    controller._learning_enabled = False
    controller._run_job = lambda job: {}
    controller._last_run_config = None
    controller.state_manager = None
    return controller


@pytest.mark.snapshot_regression
def test_simple_txt2img_snapshot_replay(snapshot_loader, pipeline_controller_with_stubs):
    controller = pipeline_controller_with_stubs
    snapshot = snapshot_loader("job_snapshot_simple_txt2img")
    jobs = controller.reconstruct_jobs_from_snapshot(snapshot)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.seed == 12345
    assert "sunset over a calm lake" in job.config.get("prompt", "")
    count = controller._submit_normalized_jobs(
        jobs,
        run_config=snapshot.get("run_config"),
        source=snapshot.get("source", "gui"),
        prompt_source=snapshot.get("prompt_source", "manual"),
    )
    assert count == 1


@pytest.mark.snapshot_regression
def test_multi_stage_snapshot_replay(snapshot_loader, pipeline_controller_with_stubs):
    controller = pipeline_controller_with_stubs
    snapshot = snapshot_loader("job_snapshot_txt2img_refiner_hires")
    jobs = controller.reconstruct_jobs_from_snapshot(snapshot)
    assert len(jobs) == 1
    job = jobs[0]
    stages = snapshot["stage_metadata"]["stages"]
    assert stages == ["txt2img", "hires", "refiner"]
    assert job.randomizer_summary == {"enabled": False}
    count = controller._submit_normalized_jobs(
        jobs,
        run_config=snapshot.get("run_config"),
    )
    assert count == 1


@pytest.mark.snapshot_regression
def test_pack_randomized_snapshot_replay(snapshot_loader, pipeline_controller_with_stubs):
    controller = pipeline_controller_with_stubs
    snapshot = snapshot_loader("job_snapshot_pack_randomized_batch")
    jobs = controller.reconstruct_jobs_from_snapshot(snapshot)
    assert len(jobs) == 1
    job = jobs[0]
    randomizer = snapshot["randomizer_expansions"]
    assert randomizer.get("enabled")
    assert job.variant_total == 3
    assert job.variant_index == 1
    count = controller._submit_normalized_jobs(
        jobs,
        run_config=snapshot.get("run_config"),
    )
    assert count == 1
