"""PR-REVIEW-FIXES-625: the Review tab's text, keys, archive and layout defects found by the live acceptance run."""

# ruff: noqa: F811, F401  (the Review fixtures are reused from the 623 tests)

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

from src.controller.batch_output_resolution import resolve_job_outputs
from src.gui.view_contracts.review_workspace_contract import (
    FILTER_LABELS,
    ItemState,
    ViewFilter,
    item_key,
    selection_label_text,
    undo_decision_text,
    undo_rating_text,
)
from src.gui.views import review_tab_frame_v2 as review_module
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.review.archive import ARCHIVED_MESSAGE
from tests.gui_v2.test_batch_operations_visibility_201 import world
from tests.gui_v2.test_review_archive_623_gui import _outputs, _show_archived_filter
from tests.gui_v2.test_review_lifecycle_621_gui import _attach_writer

pytestmark = pytest.mark.gui


@pytest.fixture
def tab(tk_root, tmp_path):
    view = ReviewTabFrame(tk_root)
    _attach_writer(view, tmp_path)
    yield view
    view.destroy()


# --- C: Undo says what it undid -----------------------------------------------------------------------------


def test_undo_texts_name_the_action():
    assert "decision (Discard)" in undo_decision_text("a.png", "discard", "")
    assert "undecided again" in undo_decision_text("a.png", "discard", "")
    assert "back to Retain" in undo_decision_text("a.png", "rework", "retain")
    text = undo_rating_text(1, ["C:/x/a.png"])
    assert "rating" in text and "removed 1 saved rating record" in text and "a.png" in text
    assert "image file was not changed" in text
    assert "2 images" in undo_rating_text(2, ["a.png", "b.png"])


def test_undoing_a_decision_says_which_decision(tab, tmp_path):
    paths = _outputs(tmp_path)
    tab._set_selected_images(paths)
    tab._on_decision_key("retain")
    tab._on_decision_key("undo")
    message = tab._session.message
    assert "Undid the decision (Retain)" in message and paths[0].name in message


# --- D: keys --------------------------------------------------------------------------------------------------


def _key(widget, state=0):
    return SimpleNamespace(widget=widget, state=state)


def test_decision_keys_work_on_any_non_text_widget_of_the_tab(tab):
    assert tab._owns_decision_key(_key(tab.images_list))
    assert tab._owns_decision_key(_key(tab.retain_button))
    assert tab._owns_decision_key(_key(tab))


@pytest.mark.parametrize(
    "make", [ttk.Entry, tk.Entry, tk.Text, ttk.Spinbox, ttk.Combobox, tk.Spinbox]
)
def test_decision_keys_are_never_captured_while_typing(tab, make):
    field = make(tab)
    assert not tab._owns_decision_key(_key(field))


def test_typing_into_the_prompt_boxes_is_never_captured(tab):
    assert not tab._owns_decision_key(_key(tab.prompt_text))
    assert not tab._owns_decision_key(_key(tab.negative_text))
    assert not tab._owns_decision_key(_key(tab.feedback_notes))


def test_decision_keys_ignore_widgets_outside_the_tab_and_modified_keys(tab, tk_root):
    outside = tk.Frame(tk_root)
    assert not tab._owns_decision_key(_key(outside))
    assert not tab._owns_decision_key(_key(tab.retain_button, state=0x4))  # Control-R is not Retain
    assert not tab._owns_decision_key(_key(tab.retain_button, state=0x20000))  # Alt on Windows


def test_the_workspace_key_binding_is_installed_and_removed_with_the_tab(tk_root):
    top = tk_root.winfo_toplevel()

    def bound() -> str:
        return "".join(top.bind(f"<Key-{key}>") for key in "rdwuRDWU")

    view = ReviewTabFrame(tk_root)
    funcids = [funcid for _sequence, funcid in view._workspace_keys]
    assert len(funcids) == 8 and all(funcid in bound() for funcid in funcids)
    view.destroy()
    assert not any(funcid in bound() for funcid in funcids)


def test_the_workspace_handler_acts_for_a_button_and_passes_a_text_field_through(tab, tmp_path):
    paths = _outputs(tmp_path)
    tab._set_selected_images(paths)
    handler = tab._workspace_key_handler("retain")
    assert handler(_key(tab.prompt_text)) is None
    assert tab._session.facts_of(item_key(paths[0])).disposition == ""
    assert handler(_key(tab.retain_button)) == "break"
    assert tab._session.facts_of(item_key(paths[0])).disposition == "retain"


# --- E: stale text --------------------------------------------------------------------------------------------


def test_selection_label_matches_the_images_shown():
    assert selection_label_text(0, 0) == "No images selected"
    assert selection_label_text(5, 5, "Active") == "5 image(s) selected"
    assert selection_label_text(184, 1, "Active") == "1 of 184 image(s) shown (Active filter)"


def test_the_header_count_follows_the_filter(tab, tmp_path):
    paths = _outputs(tmp_path, 3)
    tab._set_selected_images(paths)
    assert tab.selection_label.cget("text") == "3 image(s) selected"
    tab.filter_var.set(FILTER_LABELS[ViewFilter.RETAINED])
    tab._on_filter_changed()
    tab._refresh_workspace_view()
    assert tab.selection_label.cget("text") == "0 of 3 image(s) shown (Retained filter)"


def test_a_rating_status_does_not_stay_under_another_image(tab, tmp_path):
    paths = _outputs(tmp_path, 2)
    tab._set_selected_images(paths)
    tab._feedback_status_var.set("Saved 1 feedback record: a.png. The image file was not changed.")
    tab._rating_status_shown = True
    tab._show_image(paths[1])
    assert tab._feedback_status_var.get() == ""


def test_a_decision_status_is_kept_when_the_next_image_is_shown(tab, tmp_path):
    paths = _outputs(tmp_path, 2)
    tab._set_selected_images(paths)
    tab._feedback_status_var.set("a.png was moved to the archive.")
    tab._show_image(paths[1])
    assert "moved to the archive" in tab._feedback_status_var.get()


def test_the_history_banner_ends_with_its_set(tab, tmp_path):
    paths = _outputs(tmp_path, 2)
    tab.workflow_hint_label.config(
        text="Editing the recorded image of History job abc123. Choose the stages."
    )
    tab._set_selected_images(paths)
    assert "Editing the recorded image" not in tab.workflow_hint_label.cget("text")
    tab.workflow_hint_label.config(text="Editing the recorded image of History job abc123.")
    tab._on_clear()
    assert "Editing the recorded image" not in tab.workflow_hint_label.cget("text")


def test_the_opened_count_is_what_the_list_holds(tab, tmp_path):
    paths = _outputs(tmp_path, 2)
    twice = [str(paths[0]), str(paths[0]), str(paths[1])]
    listed = tab.load_selected_images(
        twice,
        status_message="Opened {count} batch output image(s) from Queue/History.",
        confirmed=True,
    )
    text = tab.workflow_hint_label.cget("text")
    assert listed == 2 and text.startswith("Opened 2 batch output image(s)")
    assert "1 duplicate path(s)" in text


def test_batch_outputs_recorded_under_two_spellings_are_one_output(tmp_path):
    from PIL import Image

    from src.queue.batch_projection import OutputKind

    image = tmp_path / "out" / "a.png"
    image.parent.mkdir()
    Image.new("RGB", (8, 8)).save(image)
    other_spelling = str(image.parent / ".." / "out" / "a.png")
    refs = [
        SimpleNamespace(path=str(image), origin="output", kind=OutputKind.IMAGE),
        SimpleNamespace(path=other_spelling, origin="output", kind=OutputKind.IMAGE),
    ]
    summary = SimpleNamespace(
        job=lambda _id: SimpleNamespace(artifacts=refs, workload_kind="image")
    )
    assert resolve_job_outputs(summary, ["j1"]).images == (str(image),)


# --- F: Inspect Metadata on an archived image -----------------------------------------------------------------


def test_inspect_metadata_on_an_archived_image_says_it_is_archived(tab, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(review_module.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    paths = _outputs(tmp_path, 2)
    tab._set_selected_images(paths)
    tab._on_decision_key("discard")
    _show_archived_filter(tab)
    assert tab._select_key(item_key(paths[0]))
    assert tab._session.state_of(item_key(paths[0])) is ItemState.ARCHIVED
    tab._open_metadata_inspector()
    assert shown and ARCHIVED_MESSAGE in shown[-1][1]


# --- G: the Batches panel says why the output actions are disabled in SFW mode -----------------------------------


def test_batches_panel_states_the_sfw_reason_for_the_output_actions(tk_root, world):
    from src.gui.batch_operations_panel_v2 import BatchOperationsPanelV2
    from src.gui.view_contracts.batch_operations_contract import SFW_OUTPUTS_REASON
    from tests.gui_v2.test_batch_operations_session_201 import ManualRunner
    from tests.gui_v2.test_batch_operations_visibility_201 import KEY

    stack, _explicit, _plain = world
    runner = ManualRunner()
    panel = BatchOperationsPanelV2(
        tk_root,
        service=stack.operations,
        runner=runner,
        visibility_mode=lambda: "sfw",
        main_window_provider=lambda: None,
    )
    panel.pack(fill="both", expand=True)
    try:
        panel.refresh()
        runner.drain()
        panel.session.select_batch(KEY)
        runner.drain()
        panel.session.set_job_selection(["v0"])
        tk_root.update()
        assert panel.review_button.instate(["disabled"])
        assert SFW_OUTPUTS_REASON in panel.hint_var.get()
        panel.session.set_job_selection(["v1"])
        tk_root.update()
        assert SFW_OUTPUTS_REASON not in panel.hint_var.get()
    finally:
        panel.destroy()


# --- H: the compare window gives the extra space to the image -----------------------------------------------------


def test_compare_window_gives_the_extra_space_to_the_canvas_not_the_status_line(tab, tk_root):
    status = tk.StringVar(master=tab, value="Source: a.png    Loading...")
    tab.pack(fill="both", expand=True)  # an unmapped tab hides its media and closes the viewer
    tk_root.update()
    tab._revisions.begin_compare("a.png")
    viewer, canvas = tab._build_compare_shell("Large Compare - a.png", status)
    try:
        viewer.transient(
            ""
        )  # the test root is withdrawn, which would keep a transient viewer unmapped
        viewer.geometry("1000x800")
        viewer.deiconify()
        viewer.update()
        frame = canvas.master
        label = next(
            child
            for child in frame.winfo_children()
            if isinstance(child, ttk.Label) and str(child.cget("textvariable")) == str(status)
        )
        assert canvas.winfo_height() > 500
        assert label.winfo_height() < 60
        assert canvas.winfo_y() < 200  # the image area starts under the toolbar and the status line
    finally:
        viewer.destroy()
