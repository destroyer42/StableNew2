from __future__ import annotations

from collections.abc import Callable

from src.gui.app_state_v2 import AppStateV2


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.scheduled: list[Callable[[], None]] = []
        self.ui: list[Callable[[], None]] = []

    def schedule(self, fn: Callable[[], None]) -> None:
        self.scheduled.append(fn)

    def invoke_later(self, delay_ms: int, fn: Callable[[], None]) -> None:
        self.scheduled.append(fn)

    def run_on_ui_thread(self, fn: Callable[[], None]) -> None:
        self.ui.append(fn)
        fn()


def test_app_state_has_no_concrete_gui_invoker_requirement() -> None:
    state = AppStateV2()
    dispatcher = _RecordingDispatcher()

    state.set_invoker(dispatcher)

    assert state._invoker is dispatcher


def test_stage_projection_preserves_controller_fallback_defaults() -> None:
    assert AppStateV2().get_pipeline_stage_flags() == {
        "txt2img": True,
        "img2img": False,
        "adetailer": False,
        "upscale": False,
    }


def test_stage_projection_notifies_through_ui_thread_contract() -> None:
    state = AppStateV2()
    dispatcher = _RecordingDispatcher()
    calls: list[dict[str, bool]] = []
    state.set_invoker(dispatcher)
    state.subscribe("pipeline_stage_enabled", lambda: calls.append(state.get_pipeline_stage_flags()))

    assert state.set_pipeline_stage_enabled("img2img", True) is True

    assert len(dispatcher.ui) == 1
    assert calls[-1]["img2img"] is True


def test_unchanged_or_unknown_stage_does_not_notify() -> None:
    state = AppStateV2()
    calls: list[int] = []
    state.subscribe("pipeline_stage_enabled", lambda: calls.append(1))

    assert state.set_pipeline_stage_enabled("txt2img", True) is False
    assert state.set_pipeline_stage_enabled("refiner", True) is False
    assert calls == []


def test_stage_projection_is_not_persisted_config() -> None:
    state = AppStateV2()
    state.set_pipeline_stage_enabled("upscale", True)

    fields = set(state.__dataclass_fields__)
    assert "_pipeline_stage_enabled" not in fields
    assert "_pipeline_prompt_text" not in fields
    assert "_pipeline_upscale_params" not in fields


def test_ephemeral_prompt_and_upscale_projection() -> None:
    state = AppStateV2()

    state.set_pipeline_prompt_text("portrait")
    state.set_pipeline_upscale_params(factor=2.5, model=" 4x-UltraSharp ", tile_size=512)

    assert state.get_pipeline_prompt_text() == "portrait"
    assert state.get_pipeline_upscale_params() == (2.5, "4x-UltraSharp", 512)


def test_upscale_projection_normalizes_bad_values() -> None:
    state = AppStateV2()

    state.set_pipeline_upscale_params(factor="bad", model="", tile_size="bad")  # type: ignore[arg-type]

    assert state.get_pipeline_upscale_params() == (2.0, "", 0)
