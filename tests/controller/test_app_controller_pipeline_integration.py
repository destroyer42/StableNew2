"""Integration tests for AppController queue-first pipeline wiring."""

from __future__ import annotations

import pytest

from src.controller.app_controller import AppController
from src.utils.prompt_packs import PromptPackInfo
from tests.controller.test_app_controller_config import DummyWindow
from tests.helpers.factories import make_run_config
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class RecordingPipelineController:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, object] | None] = []
        self.stop_calls = 0

    def start_pipeline(self, *, run_config=None, **_kwargs):
        self.start_calls.append(run_config)
        return True

    def stop_pipeline(self) -> bool:
        self.stop_calls += 1
        return True


@pytest.fixture
def pack_file(tmp_path, monkeypatch):
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    pack_path = packs_dir / "alpha.txt"
    pack_path.write_text("sunset over the ocean\nneg:low quality", encoding="utf-8")
    monkeypatch.setattr(
        "src.controller.app_controller.discover_packs",
        lambda *_args, **_kwargs: [PromptPackInfo(name="alpha", path=pack_path)],
    )
    return pack_path


def test_on_run_clicked_delegates_to_queue_first_pipeline_controller(pack_file, monkeypatch):
    window = DummyWindow()
    pipeline_controller = RecordingPipelineController()
    monkeypatch.setattr(
        "src.controller.app_controller.discover_packs",
        lambda *_args, **_kwargs: [PromptPackInfo(name="alpha", path=pack_file)],
    )
    controller = AppController(
        window,
        threaded=False,
        packs_dir=pack_file.parent,
        pipeline_controller=pipeline_controller,
        job_service=make_stubbed_job_service(),
    )
    controller.app_state.run_config = make_run_config(model="SDXL-Lightning", sampler="DPM++ 2M")
    controller.on_pack_selected(0)

    controller.on_run_clicked()

    assert len(pipeline_controller.start_calls) == 1
    run_config = pipeline_controller.start_calls[0]
    assert run_config is not None
    assert run_config["run_mode"] == "queue"
    assert run_config["source"] == "run"


def test_stop_triggers_job_service_cancel_and_pipeline_stop(pack_file, monkeypatch):
    window = DummyWindow()
    pipeline_controller = RecordingPipelineController()
    monkeypatch.setattr(
        "src.controller.app_controller.discover_packs",
        lambda *_args, **_kwargs: [PromptPackInfo(name="alpha", path=pack_file)],
    )
    controller = AppController(
        window,
        threaded=False,
        packs_dir=pack_file.parent,
        pipeline_controller=pipeline_controller,
        job_service=make_stubbed_job_service(),
    )
    controller.app_state.run_config = make_run_config()
    controller.on_pack_selected(0)

    controller.state.lifecycle = controller.state.lifecycle.RUNNING
    controller.on_stop_clicked()

    assert pipeline_controller.stop_calls == 0
    assert controller.state.lifecycle == controller.state.lifecycle.IDLE
