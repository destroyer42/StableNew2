from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.preview_panel_v2 import PreviewPanelV2


class _Controller:
    def __init__(self) -> None:
        self.v2_calls = 0
        self.legacy_calls = 0

    def on_add_job_to_queue_v2(self) -> None:
        self.v2_calls += 1

    def on_add_to_queue(self) -> None:
        self.legacy_calls += 1


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
        return
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.mark.gui
def test_preview_panel_prefers_v2_add_to_queue_handler(tk_root: tk.Tk) -> None:
    controller = _Controller()
    panel = PreviewPanelV2(tk_root, controller=controller)

    panel._on_add_to_queue()

    assert controller.v2_calls == 1
    assert controller.legacy_calls == 0


@pytest.mark.gui
def test_preview_panel_falls_back_to_legacy_add_to_queue_handler(tk_root: tk.Tk) -> None:
    class _LegacyOnly:
        def __init__(self) -> None:
            self.legacy_calls = 0

        def on_add_to_queue(self) -> None:
            self.legacy_calls += 1

    controller = _LegacyOnly()
    panel = PreviewPanelV2(tk_root, controller=controller)

    panel._on_add_to_queue()

    assert controller.legacy_calls == 1


@pytest.mark.gui
def test_preview_panel_forwards_clear_draft_to_the_controller(tk_root: tk.Tk) -> None:
    class _ClearController:
        def __init__(self) -> None:
            self.clear_calls = 0

        def on_clear_draft(self) -> None:
            self.clear_calls += 1

    controller = _ClearController()
    panel = PreviewPanelV2(tk_root, controller=controller)

    panel._on_clear_draft()

    assert controller.clear_calls == 1


@pytest.mark.gui
def test_preview_panel_shows_a_queue_refusal_until_it_is_cleared(tk_root: tk.Tk) -> None:
    app_state = AppStateV2()
    panel = PreviewPanelV2(tk_root, app_state=app_state, manage_app_state_subscriptions=False)
    assert not panel.queue_refusal_label.grid_info()

    app_state.set_queue_refusal("Nothing was queued. The model file is missing.")
    tk_root.update_idletasks()

    assert panel.queue_refusal_label.grid_info()
    assert "model file is missing" in panel.queue_refusal_label.cget("text")

    app_state.set_queue_refusal(None)
    tk_root.update_idletasks()
    assert not panel.queue_refusal_label.grid_info()


@pytest.mark.gui
def test_preview_panel_drops_the_refusal_when_a_new_preview_is_refreshed(tk_root: tk.Tk) -> None:
    app_state = AppStateV2()
    panel = PreviewPanelV2(tk_root, app_state=app_state, manage_app_state_subscriptions=False)
    app_state.set_queue_refusal("Nothing was queued. old")
    tk_root.update_idletasks()

    app_state.invalidate_preview()
    panel.update_from_app_state(app_state)

    assert not panel.queue_refusal_label.grid_info()
