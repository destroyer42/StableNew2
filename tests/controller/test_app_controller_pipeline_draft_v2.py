from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController


class _DummyAppState:
    def __init__(self) -> None:
        self.prompt = "test prompt"
        self.negative_prompt = "test negative"
        self.parts: list[tuple[str, str, int]] = []

    def add_job_draft_part(self, positive: str, negative: str, estimated_images: int = 1) -> None:
        self.parts.append((positive, negative, estimated_images))


class _AppControllerStub(AppController):
    """Controller shell without __init__ side effects; records preview-refresh requests."""

    def __init__(self, app_state: Any, *, main_window: Any = None) -> None:
        self.app_state = app_state
        self.main_window = main_window
        self._logged: list[str] = []
        self.sync_preview_refreshes = 0
        self.dirty_requests: list[dict[str, bool]] = []

    def _append_log(self, message: str) -> None:
        self._logged.append(message)

    def _refresh_preview_from_state(self) -> None:
        self.sync_preview_refreshes += 1

    def _mark_ui_dirty(self, **flags: bool) -> None:
        self.dirty_requests.append(flags)


def _make_controller(**kwargs: Any) -> _AppControllerStub:
    return _AppControllerStub(_DummyAppState(), **kwargs)


def test_add_single_prompt_to_draft_records_part_and_refreshes_preview() -> None:
    ctrl = _make_controller()
    ctrl.add_single_prompt_to_draft()
    assert ctrl.app_state.parts == [("test prompt", "test negative", 1)]
    assert ctrl.sync_preview_refreshes == 1
    assert ctrl.dirty_requests == []


def test_add_single_prompt_to_draft_marks_preview_dirty_in_gui_context() -> None:
    """With a GUI window the refresh is coalesced via the debounced dirty-flag path."""
    ctrl = _make_controller(main_window=object())
    ctrl.add_single_prompt_to_draft()
    assert ctrl.app_state.parts == [("test prompt", "test negative", 1)]
    assert ctrl.dirty_requests == [{"preview": True}]
    assert ctrl.sync_preview_refreshes == 0


def test_add_single_prompt_to_draft_skips_empty_prompt() -> None:
    ctrl = _make_controller()
    ctrl.app_state.prompt = ""
    ctrl.add_single_prompt_to_draft()
    assert ctrl.app_state.parts == []
    assert ctrl.sync_preview_refreshes == 0
    assert ctrl.dirty_requests == []
