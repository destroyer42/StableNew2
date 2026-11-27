"""DESK-QUICK: a Queue-time refusal reaches app state (and so the screen), not only the log."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController
from src.controller.app_controller_services.run_submission_service import (
    QueueRunSubmissionService,
    queue_refusal_text,
)
from src.gui.app_state_v2 import AppStateV2

_BLOCK = (
    "ADetailer cannot run with Z-Image on forge_webui. Create a fresh job with a supported checkpoint."
)


def _controller(**attributes: Any) -> AppController:
    controller = object.__new__(AppController)
    controller.app_state = AppStateV2()
    controller._append_log = lambda text: None
    controller._ui_dispatch = lambda fn: fn()
    controller._is_shutting_down = False
    for name, value in attributes.items():
        setattr(controller, name, value)
    return controller


def _raising(error: Exception) -> Any:
    def submit(**_kwargs: Any) -> int:
        raise error

    return SimpleNamespace(
        submit_preview_jobs_to_queue=submit,
        enqueue_draft_jobs=submit,
        ensure_run_submission_ready=lambda: True,
    )


def test_refusal_text_says_nothing_was_queued_why_and_the_fix() -> None:
    text = queue_refusal_text(ValueError(_BLOCK))

    assert text.startswith("Nothing was queued.")
    assert _BLOCK in text
    assert "Preview is kept" in text


def test_refusal_text_does_not_repeat_a_message_that_already_says_nothing_was_queued() -> None:
    text = queue_refusal_text(ValueError("The runtime cannot do this. Nothing was queued. Switch it."))

    assert text.count("Nothing was queued.") == 1


def test_refusal_text_names_an_error_without_a_message() -> None:
    assert "RuntimeError" in queue_refusal_text(RuntimeError())


def test_add_to_queue_refusal_is_published_to_app_state() -> None:
    controller = _controller(_queue_submit_in_progress=True)

    AppController._submit_preview_jobs_to_queue_async(
        controller, _raising(ValueError(_BLOCK)), [object()], {}, "t"
    )

    assert _BLOCK in controller.app_state.queue_refusal


def test_run_refusal_is_published_to_app_state(monkeypatch) -> None:
    controller = _controller()
    monkeypatch.setattr(
        QueueRunSubmissionService, "accepted_preview_jobs", lambda *_args: [object()]
    )
    prepared = SimpleNamespace(source="run", prompt_source="pack", run_config={})

    AppController._submit_run_to_queue_async(
        controller, _raising(ValueError(_BLOCK)), prepared, "run"
    )

    assert _BLOCK in controller.app_state.queue_refusal


def test_run_while_the_webui_is_not_ready_says_so_on_screen() -> None:
    controller = _controller()
    pipeline = SimpleNamespace(ensure_run_submission_ready=lambda: False)
    prepared = SimpleNamespace(source="run", prompt_source="pack", run_config={})

    AppController._submit_run_to_queue_async(controller, pipeline, prepared, "run")

    assert "WebUI is not ready" in controller.app_state.queue_refusal


def test_a_refused_replay_is_published_to_app_state() -> None:
    def replay(_job_id: str) -> int:
        raise ValueError(_BLOCK)

    controller = _controller(pipeline_controller=SimpleNamespace(replay_job_from_history=replay))

    assert controller.on_replay_history_job_v2("job-1") is False
    assert _BLOCK in controller.app_state.queue_refusal


def test_the_next_add_to_queue_clears_the_old_refusal() -> None:
    controller = _controller(
        pipeline_controller=SimpleNamespace(enqueue_draft_jobs=lambda **_kwargs: 1),
        _queue_submit_in_progress=False,
        _ensure_run_mode_default=lambda _source: None,
        _prepare_queue_run_config=lambda: {},
        _spawn_tracked_thread=lambda **_kwargs: None,
    )
    controller.app_state.set_queue_refusal("Nothing was queued. old")

    controller.on_add_job_to_queue_v2()

    assert controller.app_state.queue_refusal is None


def test_a_superseded_preview_run_is_refused_on_screen() -> None:
    state = AppStateV2()

    def compile_fresh() -> list[Any]:
        state.invalidate_preview()
        return [object()]

    service = QueueRunSubmissionService(
        append_log=lambda _text: None, capture_stage_plan_for_tests=lambda _c: None
    )

    assert service.accepted_preview_jobs(state, SimpleNamespace(get_preview_jobs=compile_fresh)) == []
    assert "nothing was queued" in state.queue_refusal.lower()


def test_a_rebuilt_preview_drops_the_old_refusal() -> None:
    state = AppStateV2()
    state.set_queue_refusal("Nothing was queued. old")
    seen: list[str | None] = []
    state.subscribe("preview_jobs", lambda: seen.append(state.queue_refusal))

    state.invalidate_preview()

    assert seen == [None]
