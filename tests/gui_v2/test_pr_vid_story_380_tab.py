"""PR-VID-STORY-380 B3-B5: the Storyboard tab through real Tk widgets with a fake service (workers run inline)."""

from __future__ import annotations

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.storyboard_tab_frame_v2 import StoryboardTabFrameV2
from src.video.sequence_plan import ROOT_PARENT
from tests.gui_v2.storyboard_tab_helpers import FakeService, fake_controller

pytestmark = pytest.mark.gui


@pytest.fixture
def fake_service(tmp_path):
    return FakeService(tmp_path)


@pytest.fixture
def storyboard_tab(tk_root, fake_service):
    tab = StoryboardTabFrameV2(
        tk_root, app_controller=fake_controller(fake_service), app_state=AppStateV2()
    )
    tab.pack()
    yield tab
    tab.destroy()


def test_opening_reconciles_on_a_worker_and_renders_columns(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id)
    assert fake_service.calls[0] == ("reconcile", fake_service.diner_id)
    assert storyboard_tab.columns.column_titles() == [
        "Shot 1",
        "Shot 2 · from A @ f8",
        "Shot 3 · from A1 @ f10",
        "Shot 4 · from A1b @ f12",
        "Shot 5 · from A1b1 @ end",
    ]
    assert storyboard_tab.columns.card_ids("Shot 2 · from A @ f8") == ["t1", "t3", "t4"]
    assert storyboard_tab.dropped_text_var.get() == "Show dropped (1)"
    assert storyboard_tab.title_var.get().startswith("Diner arrest · saved")


def test_marks_save_without_touching_files(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id)
    storyboard_tab.columns.toggle_drop("t3")
    assert fake_service.saved_marks == [("t3", "dropped")] and fake_service.files_touched == []
    assert storyboard_tab.dropped_text_var.get() == "Show dropped (2)"
    assert "t3" not in storyboard_tab.columns.card_ids("Shot 2 · from A @ f8")
    storyboard_tab.columns.toggle_keep("t4")
    assert fake_service.saved_marks[-1] == ("t4", "kept")


def test_show_dropped_reveals_the_hidden_take(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id)
    storyboard_tab.show_dropped_var.set(True)
    storyboard_tab.render()
    assert storyboard_tab.columns.card_ids("Shot 2 · from A @ f8") == ["t1", "t2", "t3", "t4"]


def test_selecting_a_take_loads_its_cut_into_the_viewer(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id)
    storyboard_tab.select_take("t1b")
    # root[:8] + A1[:2] + A1b(4 kept) = 14 frames; the slider starts on the last frame
    assert storyboard_tab.viewer.frame_count == 14
    assert storyboard_tab.contract.joins() == (8, 10)
    assert storyboard_tab.viewer.index == 13
    assert storyboard_tab.viewer.readout_var.get() == "frame 14 / 14 · A1b frame 5 of 5"
    storyboard_tab.viewer.step(-1)
    assert storyboard_tab.viewer.readout_var.get() == "frame 13 / 14 · A1b frame 4 of 5"
    storyboard_tab.viewer.seek(9)
    assert storyboard_tab.viewer.readout_var.get().startswith("frame 10 / 14 · A1 frame ")
    assert "t1_" in storyboard_tab._frame_path


def test_thumbnails_load_through_the_worker(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id)
    assert {"t1", "t4", ROOT_PARENT} <= set(storyboard_tab._photos)


def test_a_take_with_missing_frames_cannot_be_viewed_or_continued(storyboard_tab, fake_service):
    original = fake_service.project

    def broken(tree):
        views = original(tree)
        views["t4"] = views["t4"].__class__(
            **{
                **{f: getattr(views["t4"], f) for f in views["t4"].__dataclass_fields__},
                "frames_ok": False,
                "problem": "frames missing or changed: C:/x/f.png",
            }
        )
        return views

    fake_service.project = broken
    storyboard_tab.open_storyboard(fake_service.diner_id)
    storyboard_tab.select_take("t4")
    assert storyboard_tab.viewer.frame_count == 0
    assert storyboard_tab.status_var.get() == "frames missing or changed: C:/x/f.png"


def test_start_from_job_creates_then_shows_the_storyboard(storyboard_tab, fake_service):
    storyboard_tab.start_from_job("job-9", status_message="Preparing from Recent outputs…")
    assert fake_service.calls[0][:2] == ("create_from_clip", "job-9")
    assert storyboard_tab.tree is not None and storyboard_tab.status_var.get() == "Ready."


def test_errors_show_in_the_status_line_not_a_dialog(storyboard_tab, fake_service):
    def refuse(job_id, title):
        raise RuntimeError(
            "Only the smoothed video is left; its in-between frames were invented, so it cannot be continued exactly"
        )

    fake_service.create_from_clip = refuse
    storyboard_tab.start_from_job("job-9")
    assert storyboard_tab.status_var.get().startswith("Only the smoothed video is left")
    assert storyboard_tab.tree is None


def test_rename_and_save_as_go_through_the_store(storyboard_tab, fake_service):
    storyboard_tab.open_storyboard(fake_service.diner_id)
    storyboard_tab.rename("Diner v2")
    assert storyboard_tab.tree.title == "Diner v2"
    storyboard_tab.save_as("Diner copy")
    assert fake_service.saved_copies == ["Diner copy"]


# ---------------------------------------------------------------------------------------------- B4: Continue panel


def _continue_from(tab, take_id, *, index, rows):
    tab.open_storyboard("diner")
    tab.select_take(take_id)
    tab.viewer.seek(index)
    tab.viewer.continue_button.invoke()
    tab.set_rows(rows)


def test_preview_submits_nothing(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "t1b", index=13, rows=["sirens outside"])
    storyboard_tab.preview_button.invoke()
    assert [c[0] for c in fake_service.calls].count("submit") == 0
    assert [c[0] for c in fake_service.calls].count("preview") == 1
    assert "lead-in 14 frames" in storyboard_tab.status_var.get()
    assert storyboard_tab.status_var.get().endswith("Nothing was queued.")


def test_queue_parallel_sends_one_request(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "t1b", index=13, rows=["a", "b", "c"])
    assert storyboard_tab.queue_button.cget("text") == "Queue 3 takes"
    assert storyboard_tab.continue_title_var.get() == "Continue A1b from its frame 14"
    storyboard_tab.queue_button.invoke()
    request = fake_service.last_submit
    assert request.mode == "parallel" and [r.prompt for r in request.rows] == ["a", "b", "c"]
    assert request.handoff_index == 13 and request.parent_id == "t1b"
    assert request.expected_revision == 0
    assert [c[0] for c in fake_service.calls].count("submit") == 1
    assert storyboard_tab.status_var.get().startswith("Queued 1 take(s)")


def test_sequential_mode_relabels_and_sends_a_chain(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "t4", index=11, rows=["one", "two"])
    storyboard_tab.mode_var.set("sequential")
    storyboard_tab._refresh_queue_label()
    assert storyboard_tab.queue_button.cget("text") == "Queue chain of 2"
    storyboard_tab.queue_button.invoke()
    assert fake_service.last_submit.mode == "sequential" and len(fake_service.last_submit.rows) == 2


def test_a_frame_inside_an_earlier_shot_branches_from_that_take(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "t1b", index=3, rows=["x"])
    assert storyboard_tab.continue_title_var.get() == "Continue A from its frame 4"
    storyboard_tab.queue_button.invoke()
    assert (fake_service.last_submit.parent_id, fake_service.last_submit.handoff_index) == (
        "root",
        3,
    )


def test_ai_button_is_disabled_with_reason(storyboard_tab):
    assert str(storyboard_tab.ai_button.cget("state")) == "disabled"
    assert storyboard_tab.ai_reason_var.get() == "AI Assist is not set up"


def test_a_seventh_row_is_not_offered(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "t1b", index=13, rows=["r"] * 6)
    assert str(storyboard_tab.add_row_button.cget("state")) == "disabled"
    storyboard_tab.add_row()
    assert len(storyboard_tab._row_widgets) == 6
    storyboard_tab.remove_row(storyboard_tab._row_widgets[-1])
    assert str(storyboard_tab.add_row_button.cget("state")) == "normal"


def test_invalid_rows_are_refused_inline_and_nothing_is_sent(storyboard_tab, fake_service):
    _continue_from(storyboard_tab, "t1b", index=13, rows=["", "ok"])
    storyboard_tab._row_widgets[1].seed_var.set("12x")
    storyboard_tab.queue_button.invoke()
    assert "Row 1 needs a positive prompt." in storyboard_tab.status_var.get()
    assert "Row 2 seed must be blank, random or a whole number" in storyboard_tab.status_var.get()
    assert all(call[0] != "submit" for call in fake_service.calls)


def test_a_refused_submit_shows_the_service_message_and_keeps_the_panel_usable(
    storyboard_tab, fake_service
):
    _continue_from(storyboard_tab, "t1b", index=13, rows=["a"])

    def refuse(request):
        raise RuntimeError(
            "Revision conflict: the storyboard changed since it was shown; reopen it. Nothing queued."
        )

    fake_service.submit = refuse
    storyboard_tab.queue_button.invoke()
    assert storyboard_tab.status_var.get().startswith("Revision conflict")
    assert str(storyboard_tab.queue_button.cget("state")) == "normal"


def test_a_take_still_pending_cannot_be_continued(storyboard_tab, fake_service):
    fake_service.states["t4"] = "pending"
    storyboard_tab.open_storyboard("diner")
    original = fake_service.project

    def pending(tree):
        views = original(tree)
        views["t4"] = views["t4"].__class__(
            take_id="t4",
            state="pending",
            status_text="pending",
            shown_job_id=None,
            manifest=None,
            stitched_path=None,
            clip_path=None,
            encoded=False,
            frames_ok=True,
            problem="",
            can_resume=False,
            can_replay=False,
        )
        return views

    fake_service.project = pending
    storyboard_tab.refresh()
    storyboard_tab.select_take("t4")
    assert str(storyboard_tab.queue_button.cget("state")) == "disabled"


def test_an_image_root_continues_from_the_still_with_no_handoff(storyboard_tab, fake_service):
    from dataclasses import replace

    fake_service.tree = replace(
        fake_service.tree, root=replace(fake_service.tree.root, kind="image", image_path="")
    )
    fake_service.cuts.pop("root")
    storyboard_tab.open_storyboard("diner")
    storyboard_tab.select_take("root")
    assert storyboard_tab.continue_title_var.get() == "Continue A from the still image"
    storyboard_tab.set_rows(["start"])
    storyboard_tab.queue_button.invoke()
    assert (
        fake_service.last_submit.handoff_index is None
        and fake_service.last_submit.parent_id == "root"
    )


def test_experimental_opt_in_is_shown_only_when_needed_and_never_preset(
    storyboard_tab, fake_service
):
    fake_service.needs_experimental_opt_in = lambda tree: True
    _continue_from(storyboard_tab, "t1b", index=13, rows=["a"])
    assert storyboard_tab.experimental_check.winfo_manager() == "grid"
    assert storyboard_tab.experimental_var.get() is False
    storyboard_tab.experimental_var.set(True)
    storyboard_tab.queue_button.invoke()
    assert fake_service.last_submit.experimental_opt_in is True
