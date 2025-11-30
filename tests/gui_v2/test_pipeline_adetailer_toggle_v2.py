from __future__ import annotations

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


class DummyPipelineController:
    def __init__(self) -> None:
        self.stage_toggled_calls: list[tuple[str, bool]] = []

    def list_models(self) -> list[str]:
        return []

    def list_vaes(self) -> list[str]:
        return []

    def list_upscalers(self) -> list[str]:
        return []

    def get_available_samplers(self) -> list[str]:
        return []

    def get_available_schedulers(self) -> list[str]:
        return []

    def on_model_selected(self, *_args: object) -> None:
        return None

    def on_vae_selected(self, *_args: object) -> None:
        return None

    def get_last_run_config(self) -> dict[str, object]:
        return {}

    def get_current_config(self) -> dict[str, object]:
        return {
            "model": "sd_xl_base_1",
            "sampler": "Euler",
            "width": 832,
            "height": 832,
            "steps": 20,
            "cfg_scale": 7.5,
        }

    def on_stage_toggled(self, stage: str, enabled: bool) -> None:
        self.stage_toggled_calls.append((stage, enabled))

    def on_adetailer_config_changed(self, *_args: object) -> None:
        return None

    def get_lora_runtime_settings(self) -> list[dict[str, object]]:
        return []

    def update_lora_runtime_strength(self, *_args: object, **_kwargs: object) -> None:
        return None

    def update_lora_runtime_enabled(self, *_args: object, **_kwargs: object) -> None:
        return None


@pytest.mark.gui
def test_pipeline_adetailer_toggle_controls_stage_card_visibility(tk_root) -> None:
    controller = DummyPipelineController()
    app_state = AppStateV2()
    pipeline_tab = PipelineTabFrame(
        tk_root,
        app_state=app_state,
        app_controller=controller,
        pipeline_controller=controller,
    )

    sidebar = pipeline_tab.sidebar
    ad_card = pipeline_tab.stage_cards_panel.adetailer_card

    assert not ad_card.winfo_ismapped()

    sidebar.stage_states["adetailer"].set(True)
    sidebar._on_stage_toggle("adetailer")
    tk_root.update_idletasks()
    assert ad_card.winfo_ismapped()
    assert controller.stage_toggled_calls[-1] == ("adetailer", True)

    sidebar.stage_states["adetailer"].set(False)
    sidebar._on_stage_toggle("adetailer")
    tk_root.update_idletasks()
    assert not ad_card.winfo_ismapped()
    assert controller.stage_toggled_calls[-1] == ("adetailer", False)
