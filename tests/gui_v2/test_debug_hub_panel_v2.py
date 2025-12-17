import tkinter as tk

import pytest

from src.gui.panels_v2.debug_hub_panel_v2 import DebugHubPanelV2
from src.pipeline.job_models_v2 import NormalizedJobRecord, PackUsageInfo, StagePromptInfo
from src.utils import InMemoryLogHandler


class _StubController:
    def __init__(self, job: NormalizedJobRecord) -> None:
        self._job = job
        self.bundle_requested = False

    def get_preview_jobs(self) -> list[NormalizedJobRecord]:
        return [self._job]

    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return {
            "jobs": [],
            "watchdog_events": [],
            "cleanup_history": [],
            "containers": {},
            "last_bundle": None,
            "last_bundle_reason": None,
        }

    def generate_diagnostics_bundle_manual(self) -> None:
        self.bundle_requested = True


def _build_job() -> NormalizedJobRecord:
    prompt_info = StagePromptInfo(
        original_prompt="mystic castle",
        final_prompt="mystic castle at night",
        original_negative_prompt="blurry, bad quality",
        final_negative_prompt="blurry, bad quality, GLOBAL_BAD",
        global_negative_applied=True,
        global_negative_terms="GLOBAL_BAD",
    )
    return NormalizedJobRecord(
        job_id="job-001",
        config={"model": "stable-diffusion-v1-5"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=12345,
        txt2img_prompt_info=prompt_info,
        pack_usage=[PackUsageInfo(pack_name="fantasy_dragon")],
    )


def _create_panel(job: NormalizedJobRecord, root: tk.Tk):
    log_handler = InMemoryLogHandler(max_entries=10)
    controller = _StubController(job)
    panel = DebugHubPanelV2.open(
        master=root, controller=controller, app_state=None, log_handler=log_handler
    )
    panel.update_idletasks()
    return panel, controller


def _cleanup_panel(panel: DebugHubPanelV2) -> None:
    try:
        panel.close()
    except Exception:
        pass


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_prompt_tab_displays_pack_prompt(tk_root: tk.Tk):
    job = _build_job()
    panel, _ = _create_panel(job, tk_root)
    panel.prompt_tab.refresh()
    items = panel.prompt_tab.tree.get_children()
    assert len(items) == 1
    values = panel.prompt_tab.tree.item(items[0], "values")
    assert values[0] == "job-001"
    assert "mystic castle" in values[1]
    assert "GLOBAL_BAD" in values[2]
    assert "fantasy_dragon" in values[3]
    _cleanup_panel(panel)


def test_debug_hub_has_expected_tabs(tk_root: tk.Tk):
    job = _build_job()
    panel, _ = _create_panel(job, tk_root)
    assert len(panel.notebook.tabs()) == 6
    _cleanup_panel(panel)
