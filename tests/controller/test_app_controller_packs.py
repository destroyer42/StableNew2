"""Controller pack wiring tests for PR-GUI-LEFT-01."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindow
from src.gui.main_window_v2 import MainWindowV2
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


def _fake_packs_dir(tmp_path: Path) -> Path:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    for name in ("alpha", "beta"):
        (packs_dir / f"{name}.txt").write_text("prompt1\nneg: bad\n", encoding="utf-8")
    return packs_dir


def _get_log_text(controller: AppController) -> str:
    app_state = getattr(controller, "app_state", None)
    flush_now = getattr(app_state, "flush_now", None)
    if callable(flush_now):
        flush_now()
    try:
        controller.main_window.root.update()
    except Exception:
        pass
    return controller.main_window.bottom_zone.log_text.get("1.0", "end")


def test_load_packs_populates_left_zone(tmp_path: Path, tk_root):
    packs_dir = _fake_packs_dir(tmp_path)
    window = MainWindow(tk_root)
    controller = AppController(
        window,
        threaded=False,
        pipeline_runner=NoopRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
        packs_dir=packs_dir,
    )
    controller._packs_dir = packs_dir
    controller.load_packs()

    assert [pack.name for pack in controller.packs] == ["alpha", "beta"]


def test_pack_selection_tracks_state(tmp_path: Path, tk_root):
    packs_dir = _fake_packs_dir(tmp_path)
    window = MainWindow(tk_root)
    controller = AppController(
        window,
        threaded=False,
        pipeline_runner=NoopRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
        packs_dir=packs_dir,
    )
    controller._packs_dir = packs_dir
    controller.load_packs()

    controller.on_pack_selected(1)
    assert controller._selected_pack_index == 1  # type: ignore[attr-defined]
    log = _get_log_text(controller)
    assert "Pack selected: beta" in log


def test_load_and_edit_pack_require_selection(tmp_path: Path, tk_root):
    packs_dir = _fake_packs_dir(tmp_path)
    window = MainWindow(tk_root)
    controller = AppController(
        window,
        threaded=False,
        pipeline_runner=NoopRunner(),
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
        packs_dir=packs_dir,
    )
    controller._packs_dir = packs_dir
    controller.load_packs()
    expected_path = str(packs_dir / "alpha.txt")

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


def test_find_pack_by_id_falls_back_to_disk_when_visible_cache_is_stale(tmp_path: Path, tk_root):
    packs_dir = _fake_packs_dir(tmp_path)
    window = MainWindowV2(tk_root, app_state=AppStateV2())
    controller = AppController(
        window,
        threaded=False,
        pipeline_runner=None,
        pipeline_controller=None,
        job_service=None,
        packs_dir=packs_dir,
    )
    controller._packs_dir = packs_dir
    controller.packs = []

    found = controller._find_pack_by_id("alpha")

    assert found is not None
    assert found.name == "alpha"
    assert found.path == packs_dir / "alpha.txt"


class NoopRunner:
    def run(self, config, cancel_token, log_fn=None):
        return
