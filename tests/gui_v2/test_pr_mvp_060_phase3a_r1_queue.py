from __future__ import annotations

from src.contracts import PackJobEntry
from src.gui.app_state_v2 import AppStateV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.pipeline.job_models_v2 import NormalizedJobRecord


def test_pipeline_tab_pack_add_enables_queue_without_override(tk_root) -> None:
    """Exercise the production PipelineTab/PreviewPanel subscription boundary."""

    app_state = AppStateV2()

    class _Controller:
        def __init__(self) -> None:
            self.app_state = app_state
            self.pipeline_controller = self
            self.state_manager = None

        def bind_app_state(self, _state) -> None:
            return None

        def request_preview_refresh(self) -> None:
            return None

        def get_preview_jobs(self) -> list[NormalizedJobRecord]:
            return list(app_state.preview_jobs)

        def on_pipeline_add_packs_to_job(self, _pack_ids: list[str]) -> None:
            app_state.add_packs_to_job_draft(
                [
                    PackJobEntry(
                        pack_id="pack-alpha",
                        pack_name="pack-alpha",
                        config_snapshot={},
                        prompt_text="a lighthouse",
                        negative_prompt_text="",
                        stage_flags={"txt2img": True},
                        randomizer_metadata={"enabled": False},
                    )
                ]
            )
            app_state.set_preview_jobs([object()])

        def get_current_config(self) -> dict[str, object]:
            return {}

    controller = _Controller()
    tab = PipelineTabFrame(
        tk_root,
        app_state=app_state,
        app_controller=controller,
        pipeline_controller=controller,
    )
    tab.pack(fill="both", expand=True)
    tk_root.deiconify()
    tk_root.update_idletasks()

    sidebar = tab.sidebar
    sidebar._current_pack_names = ["pack-alpha"]
    sidebar.pack_listbox.insert("end", "pack-alpha")
    sidebar.pack_listbox.selection_set(0)

    # Production selector callback; no override interaction or direct preview
    # refresh invocation.
    sidebar._on_add_to_job()
    tk_root.update()

    assert app_state.preview_jobs
    assert tab.preview_panel.add_to_queue_button.instate(["!disabled"])
