from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2


class _ExplodingTkVariable:
    def get(self):
        raise AssertionError("controller must not read Tk variables")

    def set(self, _value):
        raise AssertionError("controller must not write Tk variables")


class _Sidebar:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, bool]] = []

    def set_stage_state(self, stage: str, enabled: bool, *, emit_change: bool) -> None:
        self.calls.append((stage, enabled, emit_change))


def _controller() -> AppController:
    controller = object.__new__(AppController)
    controller.app_state = AppStateV2()
    sidebar = _Sidebar()
    controller._get_sidebar_panel = lambda: sidebar  # type: ignore[method-assign]
    controller._generation_profiles = SimpleNamespace(notify_changed=lambda: None)
    controller.main_window = SimpleNamespace(
        pipeline_tab=SimpleNamespace(
            txt2img_enabled=_ExplodingTkVariable(),
            img2img_enabled=_ExplodingTkVariable(),
            adetailer_enabled=_ExplodingTkVariable(),
            upscale_enabled=_ExplodingTkVariable(),
            prompt_text=_ExplodingTkVariable(),
            upscale_factor=_ExplodingTkVariable(),
            upscale_model=_ExplodingTkVariable(),
            upscale_tile_size=_ExplodingTkVariable(),
        ),
        sidebar=sidebar,
    )
    return controller


def test_get_stage_flags_reads_app_state_not_tk() -> None:
    controller = _controller()
    controller.app_state.set_pipeline_stage_enabled("img2img", True)
    controller.app_state.set_pipeline_stage_enabled("upscale", True)

    assert controller._get_pipeline_stage_flags_from_state() == {
        "txt2img": True,
        "img2img": True,
        "adetailer": False,
        "upscale": True,
    }


def test_stage_flags_fall_back_to_defaults_without_app_state() -> None:
    controller = _controller()
    controller.app_state = None  # type: ignore[assignment]

    assert controller._get_pipeline_stage_flags_from_state() == {
        "txt2img": True,
        "img2img": False,
        "adetailer": False,
        "upscale": False,
    }


def test_set_sidebar_stage_state_does_not_write_tk_variable() -> None:
    controller = _controller()

    controller._set_sidebar_stage_state("upscale", True)

    assert controller.app_state.get_pipeline_stage_flags()["upscale"] is True
    assert controller.main_window.sidebar.calls == [("upscale", True, False)]


def test_stage_toggle_publishes_to_app_state_without_tk_write() -> None:
    controller = _controller()

    controller.on_stage_toggled("img2img", True)

    assert controller.app_state.get_pipeline_stage_flags()["img2img"] is True


def test_photo_optimize_defaults_use_state_flags_not_tk() -> None:
    controller = _controller()
    controller._collect_current_stage_configs = lambda: {"txt2img": {}}  # type: ignore[method-assign]
    controller.app_state.set_pipeline_stage_enabled("adetailer", True)
    captured: dict[str, dict[str, object]] = {}

    def _capture(config):
        captured.update(config)
        return {}

    with patch("src.photo_optimize.submission.pipeline_defaults", _capture):
        controller.build_photo_optimize_defaults()

    assert captured["adetailer"]["enabled"] is True
    assert captured["img2img"]["enabled"] is False


def test_legacy_upscale_helper_reads_app_state_projection() -> None:
    controller = _controller()
    controller.app_state.set_pipeline_upscale_params(factor=1.75, model="model-x", tile_size=384)

    assert controller._get_pipeline_tab_upscale_params(controller.main_window.pipeline_tab) == (
        1.75,
        "model-x",
        384,
    )


def test_legacy_prompt_helper_reads_app_state_projection() -> None:
    controller = _controller()
    controller.app_state.set_pipeline_prompt_text("state-owned prompt")

    assert (
        controller._get_pipeline_tab_prompt(controller.main_window.pipeline_tab)
        == "state-owned prompt"
    )
