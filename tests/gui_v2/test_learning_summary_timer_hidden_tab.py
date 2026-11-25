"""PR-GUI-STALL-ATTRIBUTION: a hidden Learning tab must not keep working on the Tk thread.

The Learning tab re-armed a 1 s timer that rebuilt the run summary whether or not the tab was on screen. The summary
reads the job queue's diagnostics snapshot (several ``JobQueue._lock`` acquisitions, two snapshots a tick) while a
generation holds that same lock across every progress commit, so a hidden tab kept the Tk thread queued behind
generation I/O. A hidden tab now does nothing on the tick; a visible one refreshes as before.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.services.ui_state_store import UIStateStore
from tests.gui_v2.tk_test_utils import get_shared_tk_root


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def _build_tab(root, tmp_dir: str) -> LearningTabFrame:
    store = UIStateStore(Path(tmp_dir) / "ui_state.json")
    with (
        patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store),
        patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=Path(tmp_dir) / "experiments",
        ),
    ):
        return LearningTabFrame(
            root, app_state=AppStateV2(), pipeline_controller=_StubPipelineController()
        )


def test_timer_tick_does_no_work_while_the_tab_is_hidden() -> None:
    root = get_shared_tk_root()
    if root is None:
        return
    with TemporaryDirectory() as tmp_dir:
        tab = _build_tab(root, tmp_dir)
        try:
            calls: list[str] = []
            tab._refresh_summary = lambda: calls.append("refresh")  # type: ignore[method-assign]
            tab.winfo_ismapped = lambda: False  # type: ignore[method-assign]

            tab._summary_tick()

            assert calls == []
            assert (
                tab._summary_refresh_after_id is not None
            )  # the timer is still armed for when it is shown
        finally:
            tab.destroy()


def test_timer_tick_refreshes_while_the_tab_is_visible() -> None:
    root = get_shared_tk_root()
    if root is None:
        return
    with TemporaryDirectory() as tmp_dir:
        tab = _build_tab(root, tmp_dir)
        try:
            calls: list[str] = []
            tab._refresh_summary = lambda: calls.append("refresh")  # type: ignore[method-assign]
            tab.winfo_ismapped = lambda: True  # type: ignore[method-assign]

            tab._summary_tick()

            assert calls == ["refresh"]
            assert tab._summary_refresh_after_id is not None
        finally:
            tab.destroy()


def test_the_first_summary_is_still_built_when_the_tab_is_constructed() -> None:
    root = get_shared_tk_root()
    if root is None:
        return
    with TemporaryDirectory() as tmp_dir:
        tab = _build_tab(root, tmp_dir)
        try:
            assert tab._summary_var.get().startswith("Plan:")
        finally:
            tab.destroy()
