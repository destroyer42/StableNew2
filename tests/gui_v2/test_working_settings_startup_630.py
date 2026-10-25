"""PR-IMG-PROFILE-630: the Working Settings card, 'Save Current Settings as Startup Defaults', the ADetailer stage default."""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.view_contracts import config_source_contract as contract


class _FakePackListManager:
    def get_list_names(self) -> list[str]:
        return []

    def refresh(self) -> None:
        pass


class _Controller:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls = 0

    def get_current_config(self) -> dict[str, object]:
        return {}

    def on_save_startup_defaults(self) -> tuple[bool, str]:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def make_sidebar(monkeypatch: pytest.MonkeyPatch, tk_root: tk.Tk):
    monkeypatch.setattr("src.gui.sidebar_panel_v2.PromptPackListManager", _FakePackListManager)

    def factory(controller: Any) -> SidebarPanelV2:
        return SidebarPanelV2(tk_root, controller=controller, app_state=AppStateV2())

    return factory


def test_working_settings_card_names_the_source_and_has_no_preset_or_recipe_controls(
    make_sidebar,
) -> None:
    sidebar = make_sidebar(_Controller((True, "x")))
    assert sidebar.save_startup_defaults_button.cget("text") == contract.SAVE_STARTUP_DEFAULTS_LABEL
    assert "Working stage settings" in sidebar.config_source_label.cget("text")
    for retired in ("saved_recipe_dropdown", "preset_dropdown", "recipe_summary_label"):
        assert not hasattr(sidebar, retired)


def test_startup_save_success_is_reported_verbatim_from_the_controller(make_sidebar) -> None:
    controller = _Controller(
        (
            True,
            "Saved startup defaults for m.safetensors. They are used the next time StableNew starts.",
        )
    )
    sidebar = make_sidebar(controller)
    sidebar.save_startup_defaults_button.invoke()
    assert controller.calls == 1
    assert "Saved startup defaults for m.safetensors" in sidebar.settings_action_label.cget("text")


@pytest.mark.parametrize("result", [(False, "Select a model first."), RuntimeError("disk full")])
def test_startup_save_failure_is_never_reported_as_success(make_sidebar, result: Any) -> None:
    sidebar = make_sidebar(_Controller(result))
    sidebar.save_startup_defaults_button.invoke()
    text = sidebar.settings_action_label.cget("text")
    assert text and "Saved" not in text.split(".")[0]
    assert contract.startup_save_result_text(False, "x") in text or "not" in text.lower()


def test_startup_save_without_a_controller_method_says_it_is_unavailable(make_sidebar) -> None:
    sidebar = make_sidebar(SimpleNamespace(get_current_config=lambda: {}))
    sidebar.save_startup_defaults_button.invoke()
    assert sidebar.settings_action_label.cget("text") == contract.startup_save_unavailable_text()


def test_restored_startup_defaults_are_named_as_the_source(make_sidebar) -> None:
    sidebar = make_sidebar(_Controller((True, "")))
    sidebar.set_settings_source("startup")
    assert "startup defaults" in sidebar.config_source_label.cget("text")


def _controller_without_widgets(**published_flags: bool) -> Any:
    state = AppStateV2()
    for stage, enabled in published_flags.items():
        state.set_pipeline_stage_enabled(stage, enabled)
    controller = SimpleNamespace(
        app_state=state,
        state=SimpleNamespace(
            current_config=SimpleNamespace(refiner_enabled=False, hires_enabled=False)
        ),
    )
    controller._get_pipeline_stage_flags_from_state = (
        lambda: AppController._get_pipeline_stage_flags_from_state(controller)
    )
    return controller


def test_unpublished_adetailer_state_defaults_to_off_not_on() -> None:
    flags = AppController._build_stage_flags(_controller_without_widgets())
    assert flags["adetailer"] is False and flags["txt2img"] is True
    assert flags["img2img"] is False and flags["upscale"] is False


def test_stage_flags_follow_the_published_stage_projection() -> None:
    flags = AppController._build_stage_flags(
        _controller_without_widgets(adetailer=True, upscale=True, img2img=False)
    )
    assert flags["adetailer"] is True and flags["upscale"] is True and flags["img2img"] is False
