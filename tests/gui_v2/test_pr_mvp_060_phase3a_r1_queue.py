from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.gui.main_window_v2 import MainWindowV2
from src.utils.config import ConfigManager
from src.utils.thread_registry import get_thread_registry
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


class _IsolatedConfigManager(ConfigManager):
    def __init__(self, packs_dir: Path) -> None:
        super().__init__(presets_dir=packs_dir.parent / "presets")
        self._packs_dir = packs_dir

    def _pack_config_path(self, pack_name: str) -> Path:
        return self._packs_dir / f"{Path(pack_name).stem}.json"


def _pump_until(root, predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    root.update()
    assert predicate(), "timed out waiting for the hosted projection"


@pytest.mark.gui
def test_pipeline_tab_pack_add_preview_and_queue_projection(
    tk_root, tmp_path: Path
) -> None:
    """Exercise the real AppController/MainWindow/PipelineTab projection path."""

    # Other GUI tests may exercise the process-wide registry shutdown path;
    # this isolated harness must begin with a live registry.
    registry = get_thread_registry()
    registry._shutdown_requested = False

    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "native_one_row.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "Native one row",
                    "slots": [
                        {"index": 0, "text": "a lighthouse at dawn", "negative": "blur"}
                    ],
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )

    config_manager = _IsolatedConfigManager(packs_dir)
    config_manager.packs_dir = packs_dir
    controller = AppController(
        None,
        threaded=False,
        packs_dir=packs_dir,
        config_manager=config_manager,
        pipeline_runner=FakePipelineRunner(),
    )
    # AppController constructs its PipelineController bridge internally; bind
    # the same isolated config seam used by the controller for this test.
    controller.pipeline_controller._config_manager = config_manager
    controller.pipeline_controller._prompt_pack_builder = None
    window = MainWindowV2(
        tk_root,
        app_state=controller.app_state,
        app_controller=controller,
        pipeline_controller=controller.pipeline_controller,
    )
    controller.set_main_window(window)
    try:
        tab = window.pipeline_tab
        sidebar = tab.sidebar
        # The hosted sidebar's adapter may discover repository packs as well;
        # constrain the visible selection to the isolated pack loaded by the
        # real controller without mutating application state.
        pack_name = controller.packs[0].name
        sidebar._current_pack_names = [pack_name]
        sidebar.pack_listbox.delete(0, "end")
        sidebar.pack_listbox.insert("end", pack_name)
        sidebar.pack_listbox.selection_set(0)
        controller.on_set_auto_run_v2(False)
        sidebar._on_add_to_job()

        _pump_until(
            tk_root,
            lambda: bool(controller.app_state.job_draft.packs)
            and bool(controller.app_state.preview_jobs),
        )
        assert tab.preview_panel.add_to_queue_button.instate(["!disabled"])

        # Production button callback; no direct state mutation or manual panel
        # refresh is used to deliver the queue projection.
        tab.preview_panel.add_to_queue_button.invoke()
        _pump_until(
            tk_root,
            lambda: len(controller.app_state.queue_jobs) == 1
            and tab.queue_panel.job_listbox.size() == 1,
        )
        controller.on_queue_clear_v2()
        _pump_until(
            tk_root,
            lambda: not controller.app_state.queue_jobs
            and tab.queue_panel.job_listbox.size() == 0,
        )
    finally:
        window.cleanup()
        registry._shutdown_requested = False
