"""PR-REVIEW-LIFECYCLE-621: the task-first Review workspace, driven through the real Tk tab.

A real temporary SQLite job repository and the real Learning evidence writer stand behind the tab; no backend, runner,
GPU or application settings are touched. Background work runs inline (the suite's autouse fixture) except where a
test substitutes the manual registry to prove what runs off the Tk thread.
"""

# ruff: noqa: F811, F401  (the Review batch fixtures are reused from test_review_batch_200)

from __future__ import annotations

import hashlib
import json
import tkinter as tk
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.gui.review_batch_dialog import ReviewBatchDialog
from src.gui.view_contracts.review_workspace_contract import (
    FILTER_LABELS,
    ItemState,
    ViewFilter,
    item_key,
)
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.learning.learning_record import LearningRecordWriter
from src.utils.image_metadata import build_contract_kv, write_image_metadata
from tests.gui_v2.edit_work_helpers import use_manual_registry
from tests.gui_v2.test_review_batch_200 import images, workflow


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(paths):
    return {p: (p.stat().st_size, p.stat().st_mtime_ns, _sha(p)) for p in paths}


def _attach_writer(tab: ReviewTabFrame, tmp_path: Path) -> LearningRecordWriter:
    writer = LearningRecordWriter(tmp_path / "evidence.jsonl")
    tab._resolve_evidence_writer = lambda: writer  # type: ignore[method-assign]
    return writer


def _evidence_rows(writer: LearningRecordWriter) -> list[dict]:
    if not writer.records_path.exists():
        return []
    return [
        json.loads(line) for line in writer.records_path.read_text().splitlines() if line.strip()
    ]


def _png(path: Path, color: int = 0, **payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (color % 256, 30, 60)).save(path)
    if payload:
        assert write_image_metadata(
            path,
            build_contract_kv(
                payload.pop("payload"),
                job_id=payload.pop("job_id", "j"),
                run_id="r",
                stage="txt2img",
            ),
        )
    return path


def _visible_names(tab: ReviewTabFrame) -> list[str]:
    return [p.name for p in tab._image_index_by_row]


def _dialogs(tab: ReviewTabFrame) -> list[ReviewBatchDialog]:
    return [child for child in tab.winfo_children() if isinstance(child, ReviewBatchDialog)]


# -- triage ---------------------------------------------------------------------------------------------------------


@pytest.mark.gui
def test_twelve_outputs_are_decided_by_keyboard_with_counts_filters_and_untouched_files(
    tk_root, tmp_path
):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = [_png(tmp_path / f"shot-{i:02}.png", i) for i in range(12)]
        before = _fingerprint(paths)
        writer = _attach_writer(tab, tmp_path)
        tab._set_selected_images(paths)
        assert tab.selection_label.cget("text") == "12 image(s) selected"
        assert "To review 12" in tab.counts_label.cget("text")
        for key in ("r", "d", "w", "u"):  # the documented keys are bound on the list
            assert tab.images_list.bind(f"<Key-{key}>")

        decisions = ["retain"] * 5 + ["discard"] * 4 + ["rework"] * 3
        for decision in decisions:
            assert tab._on_decision_key(decision) == "break"

        counts = tab._session.filter_counts()
        assert counts[ViewFilter.RETAINED] == 5
        assert counts[ViewFilter.ARCHIVED] == 4
        assert counts[ViewFilter.REWORK] == 3
        assert counts[ViewFilter.TO_REVIEW] == 0
        text = tab.counts_label.cget("text")
        assert "Retained 5" in text and "Archived 4" in text and "Re-work 3" in text
        # The default view hides the archived images; the others remain, each with its state in the row.
        assert len(_visible_names(tab)) == 8
        assert all("Archived" not in row for row in tab._row_texts)
        assert sum("[Retained]" in row for row in tab._row_texts) == 5
        assert sum("[Re-work marked]" in row for row in tab._row_texts) == 3
        assert len(_evidence_rows(writer)) == 12
        assert _fingerprint(paths) == before  # no file changed size, mtime or content
        assert {p.name for p in tmp_path.glob("*.png")} == {
            p.name for p in paths
        }  # and none moved or deleted

        tab.filter_var.set(FILTER_LABELS[ViewFilter.RETAINED])
        tab._on_filter_changed()
        assert len(_visible_names(tab)) == 5
    finally:
        tab.destroy()


@pytest.mark.gui
def test_the_next_undecided_image_is_shown_after_each_decision(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = [_png(tmp_path / f"s{i}.png", i) for i in range(3)]
        _attach_writer(tab, tmp_path)
        tab._set_selected_images(paths)
        assert tab._selected_image_path == paths[0]
        tab._on_decision_key("retain")
        assert tab._selected_image_path == paths[1]
        tab._on_decision_key("retain")
        assert tab._selected_image_path == paths[2]
    finally:
        tab.destroy()


@pytest.mark.gui
def test_archive_leaves_the_default_view_appears_under_archived_and_restore_returns_it(
    tk_root, tmp_path
):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = [_png(tmp_path / f"a{i}.png", i) for i in range(3)]
        before = _fingerprint(paths)
        _attach_writer(tab, tmp_path)
        tab._set_selected_images(paths)
        tab._on_decision_key("discard")
        assert paths[0].name not in _visible_names(tab)

        tab.filter_var.set(FILTER_LABELS[ViewFilter.ARCHIVED])
        tab._on_filter_changed()
        assert _visible_names(tab) == [paths[0].name]
        assert tab._select_key(item_key(paths[0]))
        assert str(tab.restore_button.cget("state")) == "normal"
        tab.update_idletasks()
        assert tab.restore_button in sum(
            tab._decision_bar.rows(), []
        )  # Restore appears only for an archived image
        assert tab._restore_current()

        tab.filter_var.set(FILTER_LABELS[ViewFilter.ACTIVE])
        tab._on_filter_changed()
        assert paths[0].name in _visible_names(tab)
        assert tab._session.state_of(item_key(paths[0])) is ItemState.TO_REVIEW
        assert _fingerprint(paths) == before
    finally:
        tab.destroy()


@pytest.mark.gui
def test_undo_records_the_earlier_decision_without_deleting_anything(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = [_png(tmp_path / f"u{i}.png", i) for i in range(2)]
        writer = _attach_writer(tab, tmp_path)
        tab._set_selected_images(paths)
        tab._on_decision_key("discard")
        assert len(_evidence_rows(writer)) == 1
        tab._on_decision_key("undo")
        assert len(_evidence_rows(writer)) == 2  # a compensating row; the first is kept
        assert tab._session.state_of(item_key(paths[0])) is ItemState.TO_REVIEW
    finally:
        tab.destroy()


@pytest.mark.gui
def test_decisions_are_disabled_with_a_reason_when_learning_evidence_is_not_connected(
    tk_root, tmp_path
):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = [_png(tmp_path / "x.png")]
        tab._set_selected_images(paths)
        assert str(tab.retain_button.cget("state")) == "disabled"
        assert "not connected" in tab._decision_tooltips["retain"].text
    finally:
        tab.destroy()


# -- re-work --------------------------------------------------------------------------------------------------------


def _mark_all(tab, tmp_path, paths):
    writer = _attach_writer(tab, tmp_path)
    tab._set_selected_images(paths)
    for _ in paths:
        tab._on_decision_key("rework")
    return writer


@pytest.mark.gui
def test_batch_rework_disables_single_tools_with_a_reason_and_submits_once_with_lineage(
    workflow,
    tmp_path,
    monkeypatch,
):
    controller, repository, tab = workflow
    paths = images(tmp_path, 3)
    original = [p.read_bytes() for p in paths]
    _mark_all(tab, tmp_path, paths)

    assert tab._rework_frame.winfo_manager() == "grid"
    assert "3 image(s) will be processed" in tab._scope_var.get()
    for widget in (
        tab.edit_mask_button,
        tab.extend_canvas_button,
        tab.smart_review_button,
        tab.inspect_improve_button,
    ):
        assert str(widget.cget("state")) == "disabled"
    assert "3 images are marked" in tab._single_note_var.get()

    submitted: list[int] = []
    real = controller.job_service.submit_njrs
    monkeypatch.setattr(
        controller.job_service,
        "submit_njrs",
        lambda *a, **k: (submitted.append(1), real(*a, **k))[1],
    )
    tab.stage_adetailer_var.set(False)
    tab.stage_img2img_var.set(True)
    tab._start_rework()
    (dialog,) = _dialogs(tab)
    preview = dialog.preview
    assert len(preview.jobs) == 3 and not preview.blocked
    assert not repository.list_jobs()  # nothing is queued until the preview is confirmed
    dialog._confirm()

    assert submitted == [1]
    jobs = [repository.get_job_model(job.job_id)._normalized_record for job in preview.jobs]
    assert len(jobs) == 3
    for index, record in enumerate(jobs):
        assert record.extra_metadata["batch_id"] == preview.batch_id
        assert record.source.parent_job_id == f"parent-{index}"
        assert (
            record.source.parent_artifact_id
            == "sha256:" + hashlib.sha256(original[index]).hexdigest()
        )
    # The queued children are derived from the repository: queued, so no longer in the processable scope.
    assert {tab._session.state_of(item_key(p)) for p in paths} == {ItemState.REWORK_QUEUED}
    assert "already queued" in tab._scope_var.get()
    assert str(tab.rework_button.cget("state")) == "disabled"
    assert [p.read_bytes() for p in paths] == original


@pytest.mark.gui
def test_a_blocked_row_is_excluded_explicitly_and_re_previewed(workflow, tmp_path, monkeypatch):
    controller, repository, tab = workflow
    paths = images(tmp_path, 3, incompatible=True)
    _mark_all(tab, tmp_path, paths)
    submitted: list[int] = []
    real = controller.job_service.submit_njrs
    monkeypatch.setattr(
        controller.job_service,
        "submit_njrs",
        lambda *a, **k: (submitted.append(1), real(*a, **k))[1],
    )
    tab.stage_adetailer_var.set(False)
    tab.stage_img2img_var.set(True)
    tab._start_rework()
    (dialog,) = _dialogs(tab)
    assert len(dialog.preview.blocked) == 1 and dialog.submit_button.instate(["disabled"])
    dialog._exclude()
    fresh = [d for d in _dialogs(tab) if len(d.preview.jobs) == 2 and not d.preview.blocked]
    assert len(fresh) == 1
    assert not repository.list_jobs()
    fresh[0]._confirm()
    assert submitted == [1] and len(repository.list_jobs(limit=10)) == 2


@pytest.mark.gui
def test_cancelling_a_mask_edit_leaves_no_job_and_the_item_stays_marked(
    workflow, tmp_path, monkeypatch
):
    controller, repository, tab = workflow
    paths = images(tmp_path, 2)
    _attach_writer(tab, tmp_path)
    tab._set_selected_images(paths)
    tab._on_decision_key("rework")  # one image marked: the single-image tools are available for it
    assert tab._session.rework_scope()[0].path == paths[0]
    assert str(tab.edit_mask_button.cget("state")) == "normal"

    opened: list[dict] = []
    monkeypatch.setattr(
        "src.gui.mask_editor_dialog.MaskEditorDialog", lambda parent, **kw: opened.append(kw)
    )
    tab.edit_mask_button.invoke()  # the dialog is cancelled by simply never submitting
    assert opened and opened[0]["source_path"] == paths[0]
    assert not repository.list_jobs()
    assert tab._session.state_of(item_key(paths[0])) is ItemState.REWORK_MARKED


# -- original-prompt baseline ---------------------------------------------------------------------------------------


@pytest.mark.gui
def test_the_recorded_original_plus_the_operators_edit_is_what_is_queued(workflow, tmp_path):
    controller, repository, tab = workflow
    source = _png(
        tmp_path / "orig.png",
        1,
        payload={
            "generation": {"model": "sdxl-0.safetensors"},
            "stage_manifest": {
                "stage": "txt2img",
                "original_prompt": "a quiet harbor",
                "final_prompt": "a quiet harbor, masterpiece, best quality, optimizer additions",
                "config": {"steps": 20, "cfg_scale": 7},
            },
        },
        job_id="parent-orig",
    )
    _attach_writer(tab, tmp_path)
    tab._set_selected_images([source])
    assert "original" in tab._baseline_note_var.get().lower()
    assert "a quiet harbor" in tab.provenance_text.get("1.0", tk.END)
    assert "optimizer additions" in tab.provenance_text.get(
        "1.0", tk.END
    )  # the final prompt is shown too
    tab._on_decision_key("rework")
    tab.stage_adetailer_var.set(False)
    tab.stage_img2img_var.set(True)
    tab.prompt_text.insert("1.0", "with a lighthouse")
    tab._start_rework()
    (dialog,) = _dialogs(tab)
    (record,) = dialog.preview.jobs
    assert record.positive_prompt == "a quiet harbor, with a lighthouse"
    assert "optimizer additions" not in record.positive_prompt


@pytest.mark.gui
def test_an_image_with_no_recorded_original_is_labelled_as_sent(workflow, tmp_path):
    controller, repository, tab = workflow
    paths = images(tmp_path, 1)
    _attach_writer(tab, tmp_path)
    tab._set_selected_images(paths)
    assert "as sent" in tab._baseline_note_var.get().lower()
    assert "not recorded" in tab.provenance_text.get("1.0", tk.END).lower()


# -- return, recovery, compare --------------------------------------------------------------------------------------


def _queue_one_child(tab, controller, repository, tmp_path, paths):
    _mark_all(tab, tmp_path, paths)
    tab.stage_adetailer_var.set(False)
    tab.stage_img2img_var.set(True)
    tab._start_rework()
    (dialog,) = _dialogs(tab)
    preview = dialog.preview
    dialog._confirm()
    return preview


def _complete(controller, job_id: str, output: Path) -> None:
    queue = controller.job_service.job_queue
    claimed = queue.claim_next_job()
    assert claimed is not None and claimed.job_id == job_id
    queue.mark_completed(
        job_id,
        {
            "success": True,
            "artifact": {
                "stage": "img2img",
                "artifact_type": "image",
                "primary_path": str(output),
                "output_paths": [str(output)],
            },
            "variants": [],
            "metadata": {},
        },
    )


@pytest.mark.gui
def test_a_finished_child_returns_beside_its_source_and_re_work_again_names_the_child_as_parent(
    workflow,
    tmp_path,
    monkeypatch,
):
    controller, repository, tab = workflow
    paths = images(tmp_path, 1)
    preview = _queue_one_child(tab, controller, repository, tmp_path, paths)
    child_id = preview.jobs[0].job_id
    output = _png(
        tmp_path / "out" / "child.png",
        5,
        payload={
            "generation": {"model": "sdxl-0.safetensors"},
            "stage_manifest": {
                "stage": "img2img",
                "final_prompt": "child prompt",
                "config": {"steps": 20, "cfg_scale": 7},
            },
        },
        job_id=child_id,
    )
    _complete(controller, child_id, output)
    assert tab._returned_frame.winfo_manager() in ("", "grid")  # not shown until the next read
    tab._session.refresh()

    assert tab._returned_frame.winfo_manager() == "grid"
    (row,) = tab._returned_rows
    assert row.path == output and row.relation == "verified"
    assert tab.returned_tree.item("0", "values")[1] == "child.png"
    assert tab.returned_tree.item("0", "values")[3] == "Verified"
    assert not tab._returned_note_var.get()  # nothing unverified, nothing failed

    # The returned result opens in the one Compare beside its source.
    renders: list[tuple] = []
    monkeypatch.setattr(
        tab, "_render_compare_viewer", lambda path, **kw: renders.append((path, kw))
    )
    tab._select_key(item_key(paths[0]))
    tab._open_contextual_compare()
    assert renders[-1][0] == paths[0] and renders[-1][1]["secondary_path"] == output
    assert renders[-1][1]["labels"] == ("Source", "Returned re-work")

    # Re-work again: the child becomes the parent of the next job.
    tab.returned_tree.selection_set("0")
    tab._rework_returned_again()
    assert tab._session.state_of(item_key(output)) is ItemState.REWORK_MARKED
    assert tab._selected_image_path == output
    for dialog in _dialogs(tab):
        dialog.destroy()
    tab._start_rework()
    (dialog,) = _dialogs(tab)
    (record,) = dialog.preview.jobs
    assert record.source.parent_job_id == child_id
    assert record.source.parent_artifact_id == "sha256:" + _sha(output)


@pytest.mark.gui
def test_a_failed_child_is_shown_failed_with_a_batches_link_and_is_never_retried(
    workflow, tmp_path
):
    controller, repository, tab = workflow
    paths = images(tmp_path, 1)
    preview = _queue_one_child(tab, controller, repository, tmp_path, paths)
    queue = controller.job_service.job_queue
    queue.claim_next_job()
    queue.mark_failed(preview.jobs[0].job_id, "synthetic backend refusal")
    tab._session.refresh()

    key = item_key(paths[0])
    assert tab._session.state_of(key) is ItemState.REWORK_FAILED
    assert "[Re-work failed]" in tab._row_texts[0]
    assert tab._returned_frame.winfo_manager() == "grid"
    assert "failed" in tab._returned_note_var.get() and "Batches" in tab._returned_note_var.get()
    tab.update_idletasks()
    assert tab.returned_batches_button in sum(tab._returned_actions.rows(), [])
    jobs_before = len(repository.list_jobs(limit=10))
    for _ in range(3):
        tab._session.refresh()
    assert (
        len(repository.list_jobs(limit=10)) == jobs_before == 1
    )  # nothing was retried automatically

    # A restart re-derives the same state from the evidence file and the repository.
    reopened = ReviewTabFrame(tab.master, app_controller=controller)
    try:
        reopened._resolve_evidence_writer = tab._resolve_evidence_writer  # type: ignore[method-assign]
        reopened._set_selected_images(paths)
        assert reopened._session.state_of(key) is ItemState.REWORK_FAILED
    finally:
        reopened.destroy()


@pytest.mark.gui
def test_open_batch_lists_the_repository_batches_and_loads_their_outputs(workflow, tmp_path):
    controller, repository, tab = workflow
    paths = images(tmp_path, 1)
    preview = _queue_one_child(tab, controller, repository, tmp_path, paths)
    output = _png(tmp_path / "out" / "batch-child.png", 7)
    _complete(controller, preview.jobs[0].job_id, output)
    for dialog in _dialogs(tab):
        dialog.destroy()

    fresh = ReviewTabFrame(tab.master, app_controller=controller)
    try:
        fresh._on_open_batch()
        picker = fresh._set_picker
        assert picker is not None
        (token,) = picker.tree.get_children()
        assert token.endswith(preview.batch_id)
        picker.tree.selection_set(token)
        picker._open()
        assert fresh.selected_images == [output]
        assert not picker.winfo_exists()
    finally:
        fresh.destroy()


# -- prompt visibility ----------------------------------------------------------------------------------------------


@pytest.mark.gui
def test_prompts_are_shown_marked_not_recorded_and_redacted_in_sfw(tk_root, tmp_path):
    secret = "nude portrait reference"
    source = _png(
        tmp_path / "p.png",
        3,
        payload={
            "stage_manifest": {
                "stage": "txt2img",
                "original_prompt": secret,
                "final_prompt": secret + ", optimized",
                "config": {"negative_prompt": "bad anatomy"},
            }
        },
    )
    tab = ReviewTabFrame(tk_root)
    try:
        tab._set_selected_images([source])
        shown = tab.provenance_text.get("1.0", tk.END)
        assert secret in shown and "optimized" in shown
        assert "ADetailer: not recorded" in shown
        tab.on_content_visibility_mode_changed("sfw")
        redacted = tab.provenance_text.get("1.0", tk.END)
        assert secret not in redacted and "Hidden in SFW" in redacted
    finally:
        tab.destroy()


# -- Tk thread ------------------------------------------------------------------------------------------------------


@pytest.mark.gui
def test_the_batch_rating_save_runs_off_the_tk_thread(tk_root, tmp_path, monkeypatch):
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState

    registry = use_manual_registry(monkeypatch)
    tab = ReviewTabFrame(tk_root)
    try:
        writer = LearningRecordWriter(tmp_path / "records.jsonl")
        controller = LearningController(LearningState(), learning_record_writer=writer)
        monkeypatch.setattr(controller, "refresh_recommendations", Mock())
        monkeypatch.setattr(tab, "_resolve_learning_controller", lambda: controller)
        monkeypatch.setattr(
            tab,
            "_build_feedback_payload",
            lambda path, form=None: {"image_path": str(path), "rating": 4},
        )
        paths = [tmp_path / f"image-{i}.png" for i in range(3)]
        tab._image_index_by_row = paths
        for path in paths:
            tab.images_list.insert("end", path.name)
        tab.images_list.selection_set(0, 2)
        registry.run_all()  # drain anything queued while the tab was built

        tab._save_feedback_batch()
        # The Tk thread returned before any payload was built or any record written.
        assert not writer.records_path.exists()
        assert "Saving the rating for 3 image(s)" in tab._feedback_status_var.get()
        assert str(tab.apply_selected_button.cget("state")) == "disabled"
        assert registry.run_all() >= 1
        assert len(writer.records_path.read_text().splitlines()) == 3
        assert "Saved 3 feedback record(s); not confirmed 0" in tab._feedback_status_var.get()
        assert str(tab.apply_selected_button.cget("state")) == "normal"
        assert len(tab._feedback_undo_stack[-1]) == 3
    finally:
        tab.destroy()


@pytest.mark.gui
def test_reading_review_state_is_background_work_and_the_tab_survives_closing_meanwhile(
    tk_root, tmp_path, monkeypatch
):
    registry = use_manual_registry(monkeypatch)
    tab = ReviewTabFrame(tk_root)
    paths = [_png(tmp_path / f"m{i}.png", i) for i in range(2)]
    tab._set_selected_images(paths)
    assert "(reading review state...)" in tab.counts_label.cget("text")
    tab.destroy()
    registry.run_all()  # a late result of a closed tab is dropped without error


# -- layout ---------------------------------------------------------------------------------------------------------


@pytest.mark.gui
def test_the_rework_and_returned_regions_are_hidden_until_there_is_something_to_show(tk_root):
    tab = ReviewTabFrame(tk_root)
    try:
        assert tab._rework_frame.winfo_manager() == ""
        assert tab._returned_frame.winfo_manager() == ""
        for removed in (
            "reprocess_selected_button",
            "reprocess_all_button",
            "import_selected_button",
        ):
            assert not hasattr(tab, removed)
        assert not hasattr(tab, "_import_selected_history_job")
    finally:
        tab.destroy()


@pytest.mark.gui
def test_the_decision_bar_and_the_set_bar_are_in_view_without_scrolling_on_the_laptop_viewport(
    tk_root, tmp_path
):
    from src.gui.view_contracts.window_layout_contract import compute_window_layout

    layout = compute_window_layout(1366, 768)
    tk_root.geometry(f"{layout.width}x{layout.height}+0+0")
    tk_root.deiconify()
    tab = ReviewTabFrame(tk_root)
    try:
        tab.pack(fill="both", expand=True)
        paths = [_png(tmp_path / f"v{i}.png", i) for i in range(3)]
        tab._set_selected_images(paths)
        tk_root.update()
        canvas = tab._workspace_scroll._canvas
        top, bottom = canvas.winfo_rooty(), canvas.winfo_rooty() + canvas.winfo_height()
        for widget in (tab.retain_button, tab.discard_button, tab.mark_rework_button):
            assert (
                top <= widget.winfo_rooty()
                and widget.winfo_rooty() + widget.winfo_height() <= bottom
            ), widget
        assert tab.open_button.winfo_ismapped() and tab.filter_box.winfo_ismapped()
    finally:
        tab.destroy()
        tk_root.withdraw()
