"""Controller pack wiring tests for PR-GUI-LEFT-01."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk

import pytest

from src.controller.app_controller import AppController
from src.gui.main_window_v2 import MainWindow
from src.utils.prompt_packs import PromptPackInfo
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def _fake_packs() -> list[PromptPackInfo]:
    return [
        PromptPackInfo(name="alpha", path=Path("/packs/alpha.txt")),
        PromptPackInfo(name="beta", path=Path("/packs/beta.txt")),
    ]


def _get_log_text(controller: AppController) -> str:
    return controller.main_window.bottom_zone.log_text.get("1.0", "end")


def test_load_packs_populates_left_zone(monkeypatch, tk_root):
    monkeypatch.setattr("src.controller.app_controller.discover_packs", lambda *_: _fake_packs())
    window = MainWindow(tk_root)
    controller = AppController(
        window,
        threaded=False,
        pipeline_runner=NoopRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )

    listbox = window.left_zone.packs_list
    assert listbox.get(0) == "alpha"
    assert listbox.get(1) == "beta"
    assert len(controller.packs) == 2


def test_pack_selection_tracks_state(monkeypatch, tk_root):
    monkeypatch.setattr("src.controller.app_controller.discover_packs", lambda *_: _fake_packs())
    window = MainWindow(tk_root)
    controller = AppController(
        window,
        threaded=False,
        pipeline_runner=NoopRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )

    controller.on_pack_selected(1)
    assert controller._selected_pack_index == 1  # type: ignore[attr-defined]
    log = _get_log_text(controller)
    assert "Pack selected: beta" in log


def test_load_and_edit_pack_require_selection(monkeypatch, tk_root):
    monkeypatch.setattr("src.controller.app_controller.discover_packs", lambda *_: _fake_packs())
    window = MainWindow(tk_root)
    controller = AppController(
        window,
        threaded=False,
        pipeline_runner=NoopRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )
    expected_path = str(_fake_packs()[0].path)

    controller.on_load_pack()
    controller.on_edit_pack()
    log = _get_log_text(controller)
    assert "no pack is selected" in log.lower()

    controller.on_pack_selected(0)
    controller.on_load_pack()
    controller.on_edit_pack()
    log = _get_log_text(controller)
    assert "Load Pack -> alpha" in log
    assert expected_path in log
class NoopRunner:
    def run(self, config, cancel_token, log_fn=None):
        return
