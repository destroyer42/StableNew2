from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController


class _DummyPipelineController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add_single_prompt_to_draft(self) -> None:
        self.calls.append("add")

    def clear_draft_job_bundle(self) -> None:
        self.calls.append("clear")

    def enqueue_draft_bundle(self) -> int:
        self.calls.append("enqueue")
        return 2


class _AppControllerStub(AppController):
    """Lightweight stub that avoids running the real __init__."""

    def __init__(self) -> None:
        # Skip AppController.__init__ by not calling super().__init__
        self.pipeline_controller = None  # type: ignore[assignment]
        self.app_state = None  # type: ignore[assignment]


def _make_controller() -> AppController:
    ctrl = _AppControllerStub.__new__(_AppControllerStub)
    ctrl.pipeline_controller = _DummyPipelineController()
    ctrl.app_state = None  # type: ignore[assignment]
    return ctrl


def test_add_single_prompt_to_draft_forwards_to_pipeline_controller() -> None:
    ctrl = _make_controller()
    ctrl.add_single_prompt_to_draft()
    assert ctrl.pipeline_controller.calls == ["add"]


def test_clear_draft_job_bundle_forwards_to_pipeline_controller() -> None:
    ctrl = _make_controller()
    ctrl.clear_draft_job_bundle()
    assert ctrl.pipeline_controller.calls == ["clear"]


def test_enqueue_draft_bundle_returns_pipeline_result() -> None:
    ctrl = _make_controller()
    result = ctrl.enqueue_draft_bundle()
    assert result == 2
    assert ctrl.pipeline_controller.calls == ["enqueue"]
