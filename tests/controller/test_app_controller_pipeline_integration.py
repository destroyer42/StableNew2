"""Integration tests for AppController -> PipelineRunner wiring.

LEGACY TEST: This test validates the deprecated PipelineConfig path for backward
compatibility testing. New tests should use NJR-only patterns.
See: tests.instructions.md - "Do not import archived legacy modules for new tests"
"""

from __future__ import annotations

import threading
import time

import pytest

from src.controller.app_controller import AppController, LifecycleState
from src.controller.archive.pipeline_config_types import PipelineConfig
from src.utils.prompt_packs import PromptPackInfo
from tests.controller.test_app_controller_config import DummyWindow
from tests.helpers.factories import make_run_config
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class RecordingPipelineRunner:
    def __init__(self):
        self.calls: list[tuple[PipelineConfig, object]] = []

    def run(self, config, cancel_token, log_fn=None):
        self.calls.append((config, cancel_token))
        if log_fn:
            log_fn("[fake-runner] invoked")


class BlockingPipelineRunner:
    def __init__(self):
        self.started = threading.Event()
        self.cancel_seen = threading.Event()
        self._cancel_token = None

    def run(self, config, cancel_token, log_fn=None):
        self._cancel_token = cancel_token
        self.started.set()
        while not cancel_token.is_cancelled():
            time.sleep(0.01)
        self.cancel_seen.set()


@pytest.fixture
def pack_file(tmp_path, monkeypatch):
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    pack_path = packs_dir / "alpha.txt"
    pack_path.write_text("sunset over the ocean\nneg:low quality")
    monkeypatch.setattr(
        "src.controller.app_controller.discover_packs",
        lambda *_args, **_kwargs: [PromptPackInfo(name="alpha", path=pack_path)],
    )
    return pack_path


@pytest.mark.legacy
def test_pipeline_config_assembled_from_controller_state(pack_file):
    window = DummyWindow()
    runner = RecordingPipelineRunner()
    controller = AppController(
        window,
        threaded=False,
        packs_dir=pack_file.parent,
        pipeline_runner=runner,
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )
    controller.app_state.run_config = make_run_config(
        model="SDXL-Lightning",
        sampler="DPM++ 2M",
        overrides={
            "width": 832,
            "height": 640,
            "cfg_scale": 8.9,
        },
    )
    controller.on_pack_selected(0)
    controller.update_config(
        model="SDXL-Lightning",
        sampler="DPM++ 2M",
        width=832,
        height=640,
        steps=42,
        cfg_scale=8.9,
    )

    controller.on_run_clicked()

    assert len(runner.calls) == 1
    pipeline_config = runner.calls[0][0]
    assert isinstance(pipeline_config, PipelineConfig)
    assert pipeline_config.model == "SDXL-Lightning"
    assert pipeline_config.sampler == "DPM++ 2M"
    assert pipeline_config.width == 832
    assert pipeline_config.height == 640
    assert pipeline_config.steps == 42
    assert pipeline_config.cfg_scale == 8.9
    assert pipeline_config.pack_name == "alpha"
    assert "sunset" in pipeline_config.prompt


@pytest.mark.legacy
def test_cancel_triggers_token_and_returns_to_idle(pack_file):
    window = DummyWindow()
    runner = BlockingPipelineRunner()
    controller = AppController(
        window,
        threaded=True,
        packs_dir=pack_file.parent,
        pipeline_runner=runner,
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )
    controller.app_state.run_config = make_run_config()
    controller.on_pack_selected(0)
    controller.on_run_clicked()

    assert runner.started.wait(timeout=1), "runner did not start"

    controller.on_stop_clicked()

    assert runner.cancel_seen.wait(timeout=1), "runner did not observe cancel"

    worker = controller._worker_thread
    if worker is not None:
        worker.join(timeout=1)

    assert controller.state.lifecycle == LifecycleState.IDLE
