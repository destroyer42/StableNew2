"""DESK-QUICK: a Queue refusal is visible from whichever tab the operator queued from."""

from __future__ import annotations

from typing import Any

from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import HeaderZone


def test_the_header_shows_a_refusal_on_every_tab_until_it_is_cleared(tk_root: Any) -> None:
    header, state = HeaderZone(tk_root), AppStateV2()
    header.bind_queue_refusal(state)
    try:
        assert not header.queue_refusal_label.grid_info()

        state.set_queue_refusal("Nothing was queued. The model file is missing.")
        tk_root.update_idletasks()
        assert header.queue_refusal_label.grid_info()
        assert "model file is missing" in header.queue_refusal_label.cget("text")

        state.set_queue_refusal(None)
        tk_root.update_idletasks()
        assert not header.queue_refusal_label.grid_info()
    finally:
        header.destroy()


def test_clicking_the_header_refusal_dismisses_it(tk_root: Any) -> None:
    header, state = HeaderZone(tk_root), AppStateV2()
    header.bind_queue_refusal(state)
    state.set_queue_refusal("Nothing was queued. old")
    try:
        header.dismiss_queue_refusal()
        tk_root.update_idletasks()

        assert state.queue_refusal is None
        assert not header.queue_refusal_label.grid_info()
    finally:
        header.destroy()


def test_the_main_window_binds_its_header_to_the_app_state(tk_root: Any) -> None:
    from tests.helpers.gui_harness_v2 import GuiV2Harness

    harness = GuiV2Harness(tk_root)
    try:
        harness.window.app_state.set_queue_refusal("Nothing was queued. wired")
        tk_root.update()

        assert "wired" in harness.window.header_zone.queue_refusal_label.cget("text")
    finally:
        harness.cleanup()
