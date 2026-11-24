"""PR-VID-STORY-IMPORT: clip picker, media visibility and Continue-row usability through real Tk widgets (fake service).

Workers run inline (the shared fixture style); the file browser and the service are injected, so nothing here opens a
dialog, touches the real UI-state file, probes a video or submits a job.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image, ImageTk

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.storyboard_tab_frame_v2 import StoryboardTabFrameV2, _NewStoryboardDialog
from src.services.ui_state_store import UIStateStore
from src.video.storyboard_import import (
    ClipCompatibility,
    ClipFacts,
    ClipImportPlan,
    KnownClip,
    KnownClipRefused,
)
from tests.gui_v2.storyboard_tab_helpers import FakeService, fake_controller

pytestmark = pytest.mark.gui


def _facts(path: str = "C:/clips/Scene One.MP4") -> ClipFacts:
    return ClipFacts(
        path=path,
        filename="Scene One.MP4",
        size_bytes=10,
        sha256="a" * 64,
        width=16,
        height=8,
        fps=16.0,
        fps_rational="16/1",
        fps_variable=False,
        duration_seconds=1.0,
        frame_count=16,
        frame_count_basis="probe",
        codec="h264",
        square_pixels=True,
    )


def _plan(
    status: str = "none", *, blockers: tuple[str, ...] = (), path: str = "C:/clips/Scene One.MP4"
):
    compat = ClipCompatibility("wan22", "1", (16, 8), 16, 5, None, blockers)
    known = KnownClip(status, ("job-1",) if status == "unique" else ())  # type: ignore[arg-type]
    return ClipImportPlan(_facts(path), known, compat, "Scene One")


@pytest.fixture
def fake_service(tmp_path):
    return FakeService(tmp_path)


@pytest.fixture
def store(tmp_path):
    return UIStateStore(tmp_path / "ui_state.json")


def _make_tab(tk_root, service, store):
    tab = StoryboardTabFrameV2(
        tk_root,
        app_controller=fake_controller(service),
        app_state=AppStateV2(),
        ui_state_store=store,
    )
    tab.pack()
    return tab


@pytest.fixture
def tab(tk_root, fake_service, store):
    created = _make_tab(tk_root, fake_service, store)
    yield created
    created.destroy()


def _calls(service, name):
    return [c for c in service.calls if c[0] == name]


# --------------------------------------------------------------------------------------- picking a clip


def test_browse_opens_in_movie_clips_with_mp4_filters_and_no_job_id_field(tab, fake_service):
    seen: dict = {}
    tab.ask_open_file = lambda **kw: seen.update(kw) or ""
    dialog = _NewStoryboardDialog(tab)
    dialog.browse_clip()
    assert seen["initialdir"].replace("\\", "/").endswith("movie_clips") or seen["initialdir"]
    patterns = seen["filetypes"][0][1]
    assert "*.mp4" in patterns and "*.MP4" in patterns
    assert not hasattr(dialog, "job_var")
    dialog.destroy()


def test_cancelling_the_browser_changes_nothing(tab, fake_service):
    tab.ask_open_file = lambda **kw: ""
    dialog = _NewStoryboardDialog(tab)
    dialog.browse_clip()
    assert dialog.clip_var.get() == "" and dialog.plan is None
    assert str(dialog.create_button.cget("state")) == "disabled"
    assert not _calls(fake_service, "inspect_clip")
    dialog.destroy()


def test_picking_a_clip_inspects_it_suggests_a_title_and_creates_without_submitting(
    tab, fake_service
):
    fake_service.plan = _plan("none")
    tab.ask_open_file = lambda **kw: "C:/clips/Scene One.MP4"
    dialog = _NewStoryboardDialog(tab)
    dialog.browse_clip()
    assert dialog.plan is fake_service.plan
    assert dialog.title_var.get() == "Scene One"
    assert "Scene One.MP4" in dialog.summary_var.get()
    assert str(dialog.create_button.cget("state")) == "normal"
    dialog.create()
    created = _calls(fake_service, "create_from_clip_file")
    assert len(created) == 1
    assert created[0][3]["expected_sha256"] == "a" * 64
    assert created[0][3]["import_as_media"] is False
    assert not _calls(fake_service, "submit")
    assert not dialog.winfo_exists()


def test_a_hand_edited_title_is_not_overwritten_by_the_suggestion(tab, fake_service):
    fake_service.plan = _plan("none")
    tab.ask_open_file = lambda **kw: "C:/clips/Scene One.MP4"
    dialog = _NewStoryboardDialog(tab)
    dialog.title_var.set("Mine")
    dialog._title_edited = True
    dialog.browse_clip()
    assert dialog.title_var.get() == "Mine"
    dialog.destroy()


def test_a_blocked_clip_cannot_be_created_and_says_why(tab, fake_service):
    fake_service.plan = _plan("none", blockers=("The clip is too short.",))
    tab.ask_open_file = lambda **kw: "C:/clips/Scene One.MP4"
    dialog = _NewStoryboardDialog(tab)
    dialog.browse_clip()
    assert str(dialog.create_button.cget("state")) == "disabled"
    assert "too short" in dialog.hint_var.get()
    dialog.destroy()


def test_an_unreadable_clip_is_reported_inline(tab, fake_service):
    fake_service.inspect_error = ValueError("not a playable MP4")
    tab.ask_open_file = lambda **kw: "C:/clips/bad.mp4"
    dialog = _NewStoryboardDialog(tab)
    dialog.browse_clip()
    assert "not a playable MP4" in dialog.summary_var.get()
    assert str(dialog.create_button.cget("state")) == "disabled"
    dialog.destroy()


def test_a_refused_known_clip_stays_open_and_offers_the_media_import(tab, fake_service):
    fake_service.plan = _plan("unique")
    fake_service.create_error = KnownClipRefused("job-1", "its frames are gone")
    tab.ask_open_file = lambda **kw: "C:/clips/Scene One.MP4"
    dialog = _NewStoryboardDialog(tab)
    dialog.browse_clip()
    dialog.create()
    assert dialog.winfo_exists()
    assert "its frames are gone" in dialog.hint_var.get()
    assert (
        str(dialog.create_button.cget("state")) == "disabled"
    )  # until the operator chooses the media import
    dialog.media_var.set(True)
    dialog._refresh()
    assert str(dialog.create_button.cget("state")) == "normal"
    dialog.destroy()


def test_still_image_browse_keeps_the_existing_path(tab, fake_service):
    tab.ask_open_file = lambda **kw: "C:/stills/pic.png"
    dialog = _NewStoryboardDialog(tab)
    dialog.browse_image()
    assert dialog.image_var.get() == "C:/stills/pic.png"
    assert str(dialog.create_button.cget("state")) == "normal"
    assert not _calls(fake_service, "inspect_clip")
    dialog.destroy()


# --------------------------------------------------------------------------------------- media visibility


def _open(tab):
    tab.open_storyboard("diner")
    tab.select_take("t1b")
    tab.viewer.seek(5)


def test_visibility_defaults_to_shown_and_is_persisted(tk_root, fake_service, store):
    first = _make_tab(tk_root, fake_service, store)
    assert first.media.thumbnails and first.media.viewer
    first.show_thumbnails_var.set(False)
    first.thumbnails_check.invoke() if False else first._toggle_thumbnails()
    first.show_viewer_var.set(False)
    first._toggle_viewer()
    first.destroy()
    second = _make_tab(tk_root, fake_service, store)
    assert not second.media.thumbnails and not second.media.viewer
    assert not second.show_thumbnails_var.get() and not second.show_viewer_var.get()
    assert not second.columns.thumbnails_visible and not second.viewer.media_visible
    second.destroy()


def test_the_two_switches_are_independent(tab):
    tab.show_thumbnails_var.set(False)
    tab._toggle_thumbnails()
    assert not tab.media.thumbnails and tab.media.viewer
    tab.show_viewer_var.set(False)
    tab._toggle_viewer()
    tab.show_thumbnails_var.set(True)
    tab._toggle_thumbnails()
    assert tab.media.thumbnails and not tab.media.viewer


def test_hidden_thumbnails_load_nothing_and_late_results_are_dropped(tab, fake_service):
    tab.show_thumbnails_var.set(False)
    tab._toggle_thumbnails()
    tab.open_storyboard("diner")
    assert tab.columns._thumb_labels == {}
    assert tab._photos == {}
    stale = Image.new("RGB", (4, 4))
    tab._apply_thumbnails({"t1": stale})
    assert tab._photos == {} and tab.columns._thumb_labels == {}


def test_a_thumbnail_load_started_before_hiding_cannot_restore_it(tab):
    tab.open_storyboard("diner")
    started = tab._thumb_generation
    tab.show_thumbnails_var.set(False)
    tab._toggle_thumbnails()
    tab.show_thumbnails_var.set(True)
    tab._toggle_thumbnails()
    assert tab._thumb_generation != started
    before = dict(tab._photos)
    tab._apply_thumbnails({"t1": Image.new("RGB", (4, 4))}, started)
    assert tab._photos == before


def test_restoring_thumbnails_loads_them_again(tab):
    tab.open_storyboard("diner")
    tab.show_thumbnails_var.set(False)
    tab._toggle_thumbnails()
    assert tab._photos == {}
    tab.show_thumbnails_var.set(True)
    tab._toggle_thumbnails()
    assert tab._photos and tab.columns._thumb_labels


def test_hiding_the_viewer_keeps_the_selection_frame_and_target_and_stops_playback(tab):
    _open(tab)
    tab.viewer.continue_button.invoke()
    target, take, index = tab.target, tab.contract.selected_id, tab.viewer.index
    tab.viewer.toggle_play()
    tab.show_viewer_var.set(False)
    tab._toggle_viewer()
    assert not tab.viewer.playing
    assert (tab.target, tab.contract.selected_id, tab.viewer.index) == (target, take, index)
    assert "frame" in tab.viewer.readout_var.get().lower() or tab.viewer.readout_var.get()
    tab.viewer.toggle_play()  # inert while hidden
    assert not tab.viewer.playing
    tab.show_viewer_var.set(True)
    tab._toggle_viewer()
    assert (tab.target, tab.contract.selected_id, tab.viewer.index) == (target, take, index)


def test_a_frame_that_arrives_after_hiding_is_not_drawn(tab):
    _open(tab)
    tab.show_viewer_var.set(False)
    tab._toggle_viewer()
    tab._apply_frame(Image.new("RGB", (8, 8)))
    assert tab.viewer._photo is None


def test_hiding_media_does_not_submit_or_change_state(tab, fake_service):
    _open(tab)
    tab.show_viewer_var.set(False)
    tab._toggle_viewer()
    tab.show_thumbnails_var.set(False)
    tab._toggle_thumbnails()
    assert not _calls(fake_service, "submit") and not _calls(fake_service, "preview")
    assert fake_service.saved_marks == []


def test_a_broken_preference_file_does_not_stop_the_tab(tk_root, fake_service, tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text("{ not json", encoding="utf-8")
    created = _make_tab(tk_root, fake_service, UIStateStore(path))
    assert created.media.thumbnails and created.media.viewer
    created.destroy()


# --------------------------------------------------------------------------------------- Continue rows


def test_headers_exist_and_rows_align_across_add_and_remove(tab):
    headers = tab.rows_widget.header_labels
    assert (
        list(headers) == ["#", "Positive Prompt", "Negative Prompt", "Seed", "Remove"]
        or len(headers) == 5
    )
    tab.add_row("a")
    tab.add_row("b")
    for row in tab._row_widgets:
        grid = [w.grid_info() for w in row.widgets()]
        assert [int(g["column"]) for g in grid] == [0, 1, 2, 3, 4]
    rows = [int(row.prompt_entry.grid_info()["row"]) for row in tab._row_widgets]
    assert rows == sorted(set(rows)) and min(rows) == 1
    tab.remove_row(tab._row_widgets[0])
    rows = [int(row.prompt_entry.grid_info()["row"]) for row in tab._row_widgets]
    assert rows == list(range(1, len(rows) + 1))
    assert [row.number_label.cget("text") for row in tab._row_widgets] == [
        str(n) for n in range(1, len(rows) + 1)
    ]
    # the headers sit on the same columns as the entries and the prompts get the width
    cols = tab.rows_widget
    assert int(cols.grid_columnconfigure(1)["weight"]) > int(cols.grid_columnconfigure(3)["weight"])


def test_the_negative_hint_explains_a_blank_prompt(tab):
    tab.open_storyboard("diner")
    assert "Blank negative prompt" in tab.rows_widget.hint_var.get()


def test_random_sends_random_and_fixed_sends_the_number(tab, fake_service):
    tab.open_storyboard("diner")
    tab.select_take("t1b")
    tab.viewer.seek(13)
    tab.viewer.continue_button.invoke()
    tab.set_rows(["a", "b"])
    tab._row_widgets[0].seed_mode_var.set("Random")
    tab._row_widgets[1].seed_mode_var.set("Fixed")
    tab._row_widgets[1].seed_var.set("123")
    assert str(tab._row_widgets[0].seed_entry.cget("state")) == "disabled"
    assert str(tab._row_widgets[1].seed_entry.cget("state")) == "normal"
    tab.queue_button.invoke()
    request = fake_service.last_submit
    assert [r.seed for r in request.rows] == ["random", "123"]


@pytest.mark.parametrize("bad", ["", "-1", "12x", "2147483648", "1.5"])
def test_an_invalid_fixed_seed_is_refused_before_submission(tab, fake_service, bad):
    tab.open_storyboard("diner")
    tab.select_take("t1b")
    tab.viewer.seek(13)
    tab.viewer.continue_button.invoke()
    tab.set_rows(["a"])
    tab._row_widgets[0].seed_mode_var.set("Fixed")
    tab._row_widgets[0].seed_var.set(bad)
    tab.queue_button.invoke()
    assert "seed" in tab.status_var.get().lower()
    assert not _calls(fake_service, "submit")


def test_preview_and_queue_still_work_with_six_rows(tab, fake_service):
    tab.open_storyboard("diner")
    tab.select_take("t1b")
    tab.viewer.seek(13)
    tab.viewer.continue_button.invoke()
    tab.set_rows(["r"] * 6)
    assert str(tab.add_row_button.cget("state")) == "disabled"
    tab.preview_button.invoke()
    assert len(_calls(fake_service, "preview")) == 1 and not _calls(fake_service, "submit")
    tab.queue_button.invoke()
    assert len(fake_service.last_submit.rows) == 6


_ = (SimpleNamespace, ImageTk)
