from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController


class _DummyPipelineController:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def refresh_preview_from_state(self) -> None:
        self.refresh_calls += 1


class _DummyAppState:
    def __init__(self) -> None:
        self.prompt = "test prompt"
        self.negative_prompt = "test negative"
        self.parts: list[tuple[str, str, int]] = []

    def add_job_draft_part(self, positive: str, negative: str, estimated_images: int = 1) -> None:
        self.parts.append((positive, negative, estimated_images))


class _AppControllerStub(AppController):
    def __init__(self, pipeline_controller: Any, app_state: Any) -> None:
        self.pipeline_controller = pipeline_controller
        self.app_state = app_state
        self._logged: list[str] = []

    def _append_log(self, message: str) -> None:
        self._logged.append(message)


def _make_controller() -> _AppControllerStub:
    pipeline_ctrl = _DummyPipelineController()
    app_state = _DummyAppState()
    return _AppControllerStub(pipeline_controller=pipeline_ctrl, app_state=app_state)


def test_add_single_prompt_to_draft_records_part_and_refreshes_preview() -> None:
    ctrl = _make_controller()
    ctrl.add_single_prompt_to_draft()
    assert ctrl.app_state.parts == [("test prompt", "test negative", 1)]
    assert ctrl.pipeline_controller.refresh_calls == 1


def test_add_single_prompt_to_draft_skips_empty_prompt() -> None:
    ctrl = _make_controller()
    ctrl.app_state.prompt = ""
    ctrl.add_single_prompt_to_draft()
    assert ctrl.app_state.parts == []
    assert ctrl.pipeline_controller.refresh_calls == 0
