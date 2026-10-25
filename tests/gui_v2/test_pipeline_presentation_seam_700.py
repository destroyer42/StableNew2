from __future__ import annotations

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from tests.gui_v2.test_pipeline_adetailer_toggle_v2 import DummyPipelineController


def _tab(tk_root, state: AppStateV2) -> PipelineTabFrame:
    controller = DummyPipelineController()
    return PipelineTabFrame(
        tk_root, app_state=state, app_controller=controller, pipeline_controller=controller
    )


@pytest.mark.gui
def test_pipeline_construction_publishes_visible_tk_defaults(tk_root) -> None:
    state = AppStateV2()
    tab = _tab(tk_root, state)

    assert state.get_pipeline_stage_flags() == {
        "txt2img": bool(tab.txt2img_enabled.get()),
        "img2img": bool(tab.img2img_enabled.get()),
        "adetailer": bool(tab.adetailer_enabled.get()),
        "upscale": bool(tab.upscale_enabled.get()),
    }
    assert state.get_pipeline_stage_flags()["adetailer"] is True


@pytest.mark.gui
def test_pipeline_tk_stage_var_projects_to_app_state(tk_root) -> None:
    state = AppStateV2()
    tab = _tab(tk_root, state)

    tab.img2img_enabled.set(True)
    tk_root.update_idletasks()

    assert state.get_pipeline_stage_flags()["img2img"] is True


@pytest.mark.gui
def test_app_state_stage_change_projects_back_to_tk_var(tk_root) -> None:
    state = AppStateV2()
    tab = _tab(tk_root, state)

    state.set_pipeline_stage_enabled("upscale", True)
    tk_root.update_idletasks()

    assert tab.upscale_enabled.get() is True


@pytest.mark.gui
def test_sync_state_overrides_publishes_upscale_values(tk_root) -> None:
    state = AppStateV2()
    tab = _tab(tk_root, state)

    tab.upscale_factor.set(3.0)
    tab._sync_state_overrides()

    assert state.get_pipeline_upscale_params()[0] == 3.0
