#ARCHIVE
# Legacy adetailer stage integration test that duplicates Phase 6 diagnostics flow.
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyPipelineRunner:
    def run(self, *args: Any, **kwargs: Any) -> Any:
        return None


class FakeStageCardsPanel:
    def __init__(self) -> None:
        self.loaded: list[dict[str, Any]] = []
        self.enabled_calls: list[tuple[str, bool]] = []
        self.collect_calls = 0
        self.resource_updates: list[dict[str, Any]] = []

    def load_adetailer_config(self, config: dict[str, Any]) -> None:
        self.loaded.append(dict(config or {}))

    def collect_adetailer_config(self) -> dict[str, Any]:
        self.collect_calls += 1
        return {"adetailer_model": "stub-model"}

    def set_stage_enabled(self, stage: str, enabled: bool) -> None:
        self.enabled_calls.append((stage, enabled))

    def add_adetailer_listener(self, listener: Any) -> None:
        try:
            listener(self.collect_adetailer_config())
        except Exception:
            pass

    def apply_resource_update(self, resources: dict[str, Any]) -> None:
        self.resource_updates.append(dict(resources or {}))


class FakeSidebarPanel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def set_stage_state(self, stage: str, enabled: bool, *, emit_change: bool = True) -> None:
        self.calls.append((stage, enabled))


def _build_controller(panel: FakeStageCardsPanel | None = None, sidebar: FakeSidebarPanel | None = None) -> AppController:
    controller = AppController(
        None,
        threaded=False,
        pipeline_runner=DummyPipelineRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )
    controller.app_state = AppStateV2()
    mw = SimpleNamespace()
    mw.pipeline_tab = SimpleNamespace(stage_cards_panel=panel)
    if sidebar:
        mw.sidebar_panel_v2 = sidebar
    controller.main_window = mw
    return controller


def test_stage_toggle_updates_app_state_and_panel() -> None:
    panel = FakeStageCardsPanel()
    controller = _build_controller(panel=panel)

    controller.on_stage_toggled("adetailer", True)

    assert controller.app_state.adetailer_enabled
    assert controller.app_state.adetailer_config.get("enabled") is True
    assert controller.app_state.adetailer_config.get("adetailer_model") == "stub-model"
    assert panel.collect_calls == 1


def test_config_load_updates_panel_and_sidebar_state() -> None:
    panel = FakeStageCardsPanel()
    sidebar = FakeSidebarPanel()
    controller = _build_controller(panel=panel, sidebar=sidebar)
    config = {
        "pipeline": {"adetailer_enabled": True},
        "adetailer": {"adetailer_model": "face-name"},
    }

    controller._apply_adetailer_config_section(config)

    assert panel.loaded and panel.loaded[-1]["adetailer_model"] == "face-name"
    assert ("adetailer", True) in panel.enabled_calls
    assert sidebar.calls == [("adetailer", True)]
    assert controller.app_state.adetailer_enabled
    assert controller.app_state.adetailer_config["adetailer_model"] == "face-name"


def test_resource_refresh_forwards_resources_to_stage_panel() -> None:
    panel = FakeStageCardsPanel()
    controller = _build_controller(panel=panel)
    controller.state.resources = {
        "models": ["m1"],
        "vaes": ["v1"],
        "samplers": ["s1"],
        "schedulers": ["sched1"],
    }

    controller._update_gui_dropdowns()

    assert panel.resource_updates
    assert panel.resource_updates[-1] == controller.state.resources
