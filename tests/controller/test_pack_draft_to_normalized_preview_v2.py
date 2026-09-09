from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.utils.prompt_packs import PromptPackInfo
from tests.helpers.njr_factory import make_pipeline_njr


class DummyPipelineTab:
    def __init__(self) -> None:
        self.txt2img_enabled = True
        self.img2img_enabled = False
        self.adetailer_enabled = True
        self.upscale_enabled = True


def test_on_pipeline_add_packs_to_job_populates_preview_metadata(tmp_path: Path) -> None:
    pack_path = tmp_path / "test_pack.txt"
    pack_path.write_text("positive prompt\nneg:negative remark")

    controller = AppController(
        main_window=None,
        pipeline_runner=None,
        pipeline_controller=None,
        job_service=None,
    )
    controller.app_state = AppStateV2()
    controller.main_window = type("Window", (), {"pipeline_tab": DummyPipelineTab()})()
    controller.packs = [PromptPackInfo(name="test_pack", path=pack_path, preset_name="")]

    controller.on_pipeline_add_packs_to_job(["test_pack"])

    assert len(controller.app_state.job_draft.packs) == 1
    entry = controller.app_state.job_draft.packs[0]
    assert entry.prompt_text == "positive prompt"
    assert entry.negative_prompt_text == "negative remark"
    assert entry.stage_flags.get("txt2img", False)
    assert entry.stage_flags.get("img2img") is False
    assert entry.stage_flags.get("adetailer", False)
    assert entry.stage_flags.get("upscale", False)
    assert entry.stage_flags.get("refiner") in {True, False}
    assert "enabled" in entry.randomizer_metadata

    assert entry.config_snapshot.get("randomization_enabled") is not None


def test_sidebar_add_to_job_refreshes_new_multi_row_json_pack_preview(tmp_path: Path) -> None:
    """The production-shaped selector action must publish a fresh preview."""

    class _Window:
        root = None
        app_state = AppStateV2()
        pipeline_tab = SimpleNamespace(
            txt2img_enabled=True,
            img2img_enabled=False,
            adetailer_enabled=False,
            upscale_enabled=False,
        )

        @staticmethod
        def run_in_main_thread(callback):
            callback()

        @staticmethod
        def run_in_main_thread_later(_delay_ms, callback):
            callback()

        @staticmethod
        def connect_controller(_controller):
            return None

    class _Listbox:
        @staticmethod
        def curselection():
            return (0,)

    controller = AppController(main_window=None, threaded=False, pipeline_runner=None)
    controller.load_packs = lambda: None  # type: ignore[method-assign]
    controller._update_status = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    window = _Window()
    controller.set_main_window(window)

    pack_path = tmp_path / "native_multi_row.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "native_multi_row",
                    "slots": [{"text": "first"}, {"text": "second"}, {"text": "third"}],
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )
    try:
        controller.packs = [PromptPackInfo(name="native_multi_row", path=pack_path)]
        pipeline_controller = controller.pipeline_controller

        def _build_preview_jobs(request):
            return [
                make_pipeline_njr(
                    job_id=f"preview-{index}",
                    positive_prompt=entry.prompt_text,
                )
                for index, entry in enumerate(request.pack_entries)
            ]

        pipeline_controller.get_preview_jobs_for_request = _build_preview_jobs  # type: ignore[method-assign]

        sidebar = object.__new__(SidebarPanelV2)
        sidebar.pack_listbox = _Listbox()
        sidebar.controller = controller
        sidebar._current_pack_names = ["native_multi_row"]

        # Invoke the actual selector callback; no manual refresh or override toggle.
        sidebar._on_add_to_job()

        assert len(controller.app_state.job_draft.packs) == 3
        assert len(controller.app_state.preview_jobs) == 3
        assert [job.config["prompt"] for job in controller.app_state.preview_jobs] == [
            "first",
            "second",
            "third",
        ]
        assert PreviewPanelV2._can_add_to_queue(
            controller.app_state.job_draft,
            controller.app_state.preview_jobs,
        )
    finally:
        pack_path.unlink(missing_ok=True)
