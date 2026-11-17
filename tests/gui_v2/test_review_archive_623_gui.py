"""PR-REVIEW-ARCHIVE-623: Discard moves the image through the real Tk tab (temporary roots, synthetic images only).

The move runs on the existing Review worker after the view has advanced off the image; a refusal keeps the item
discarded with its reason; one confirmation covers a multi-image discard; Restore handles a taken original path; the
Archived filter lists archived images from their records after a restart. A real modal would hang the run, so every
confirmation goes through the tab's injectable hook.
"""

# ruff: noqa: F811, F401  (the Review fixtures are reused from test_review_batch_200)

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.gui.view_contracts.review_workspace_contract import (
    FILTER_LABELS,
    ItemState,
    ViewFilter,
    item_key,
)
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.review import archive as arc
from src.review.workspace_io import scan_image_folder
from tests.gui_v2.edit_work_helpers import use_manual_registry
from tests.gui_v2.test_review_batch_200 import workflow
from tests.gui_v2.test_review_lifecycle_621_gui import (
    _attach_writer,
    _evidence_rows,
    _png,
    _visible_names,
)
from tests.helpers.batch_ops_201 import review_njr


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _outputs(tmp_path: Path, count: int = 3) -> list[Path]:
    return [_png(tmp_path / "output" / "Pipeline" / "run" / f"s{i}.png", i) for i in range(count)]


def _where(tmp_path: Path, path: Path) -> Path:
    return arc.mirror_target(path, tmp_path / "output")


def _show_archived_filter(tab: ReviewTabFrame) -> None:
    tab.filter_var.set(FILTER_LABELS[ViewFilter.ARCHIVED])
    tab._on_filter_changed()


@pytest.mark.gui
def test_discard_runs_on_the_worker_after_the_view_has_advanced_off_the_image(
    tk_root, tmp_path, monkeypatch
):
    registry = use_manual_registry(monkeypatch)
    tab = ReviewTabFrame(tk_root)
    try:
        paths = _outputs(tmp_path)
        digest = _sha(paths[0])
        _attach_writer(tab, tmp_path)
        tab._set_selected_images(paths)
        registry.run_all()

        tab._on_decision_key("discard")

        assert tab._selected_image_path == paths[1]  # the view moved on first
        assert paths[0].exists()  # nothing was moved on the Tk thread
        assert registry.run_all() >= 1
        assert not paths[0].exists() and _sha(_where(tmp_path, paths[0])) == digest
        assert "moved to the archive" in tab._feedback_status_var.get()
        assert tab._session.state_of(item_key(paths[0])) is ItemState.ARCHIVED
    finally:
        tab.destroy()


@pytest.mark.gui
def test_discarding_several_highlighted_images_asks_once_and_moves_each(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = _outputs(tmp_path, 4)
        writer = _attach_writer(tab, tmp_path)
        asked: list[int] = []
        tab._confirm_discard_hook = lambda count: asked.append(count) or True
        tab._set_selected_images(paths)
        tab.images_list.selection_clear(0, "end")
        tab.images_list.selection_set(0, 2)  # three highlighted, the first is shown

        tab._on_decision_key("discard")

        assert asked == [3]
        assert [path.exists() for path in paths] == [False, False, False, True]
        assert all(_where(tmp_path, path).exists() for path in paths[:3])
        assert len(_evidence_rows(writer)) == 3
        for _ in range(3):
            tab._on_decision_key("undo")
        assert all(path.exists() for path in paths)
    finally:
        tab.destroy()


@pytest.mark.gui
def test_declining_the_multi_discard_confirmation_changes_nothing(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = _outputs(tmp_path)
        writer = _attach_writer(tab, tmp_path)
        tab._confirm_discard_hook = lambda _count: False
        tab._set_selected_images(paths)
        tab.images_list.selection_set(0, 1)
        tab._on_decision_key("discard")
        assert all(path.exists() for path in paths) and _evidence_rows(writer) == []
    finally:
        tab.destroy()


@pytest.mark.gui
def test_a_single_highlighted_image_is_discarded_without_asking(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = _outputs(tmp_path)
        _attach_writer(tab, tmp_path)
        tab._confirm_discard_hook = lambda _count: pytest.fail("a single discard must not ask")
        tab._set_selected_images(paths)
        tab._on_decision_key("discard")
        assert not paths[0].exists()
    finally:
        tab.destroy()


@pytest.mark.gui
def test_an_image_used_by_a_queued_job_stays_discarded_in_place_with_the_reason_until_the_job_ends(
    workflow, tmp_path
):
    controller, _repository, tab = workflow
    paths = _outputs(tmp_path)
    _attach_writer(tab, tmp_path)
    queue = controller.job_service.job_queue
    controller.job_service.submit_njrs([review_njr("job-q", "batch-q", source=paths[0])])
    tab._set_selected_images(paths)

    tab._on_decision_key("discard")

    assert paths[0].exists()
    assert tab._session.state_of(item_key(paths[0])) is ItemState.ARCHIVED
    message = tab._feedback_status_var.get()
    assert "not moved" in message and "queued or running job" in message
    _show_archived_filter(tab)
    assert _visible_names(tab) == [paths[0].name]
    assert "(not moved)" in tab._row_texts[0]

    job = queue.claim_next_job()
    queue.mark_completed(job.job_id, {"success": True, "variants": [], "metadata": {}})
    assert tab._select_key(item_key(paths[0]))
    tab._on_decision_key("discard")  # the job finished: the retry moves it

    assert not paths[0].exists() and _where(tmp_path, paths[0]).exists()
    assert "(in archive)" in tab._row_texts[0]


@pytest.mark.gui
def test_a_controller_without_a_reachable_queue_refuses_the_move(tk_root, tmp_path):
    from types import SimpleNamespace

    tab = ReviewTabFrame(tk_root, app_controller=SimpleNamespace())  # no job service at all
    try:
        paths = _outputs(tmp_path)
        _attach_writer(tab, tmp_path)
        tab._set_selected_images(paths)
        tab._on_decision_key("discard")
        assert paths[0].exists()
        assert "queue could not be read" in tab._feedback_status_var.get()
        assert tab._session.state_of(item_key(paths[0])) is ItemState.ARCHIVED
    finally:
        tab.destroy()


@pytest.mark.gui
def test_restore_offers_a_new_name_when_a_different_file_took_the_original_path(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = _outputs(tmp_path)
        original = _sha(paths[0])
        _attach_writer(tab, tmp_path)
        offered: list[str] = []
        tab._confirm_alternative_hook = lambda name: offered.append(name) or True
        tab._set_selected_images(paths)
        tab._on_decision_key("discard")
        squatter = _png(paths[0], 200)
        squatter_sha = _sha(squatter)
        _show_archived_filter(tab)
        assert tab._select_key(item_key(paths[0]))

        assert tab._restore_current()
        tab.update()  # the offer is raised from the event loop, never from inside the session callback

        assert offered == [f"s0.restored-{original[:8]}.png"]
        restored = paths[0].with_name(offered[0])
        assert _sha(restored) == original and _sha(squatter) == squatter_sha
        assert not _where(tmp_path, paths[0]).exists()
    finally:
        tab.destroy()


@pytest.mark.gui
def test_declining_the_new_name_leaves_the_image_archived(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = _outputs(tmp_path)
        _attach_writer(tab, tmp_path)
        tab._confirm_alternative_hook = lambda _name: False
        tab._set_selected_images(paths)
        tab._on_decision_key("discard")
        _png(paths[0], 201)
        _show_archived_filter(tab)
        tab._select_key(item_key(paths[0]))
        tab._restore_current()
        tab.update()
        assert _where(tmp_path, paths[0]).exists()
        assert tab._session.state_of(item_key(paths[0])) is ItemState.ARCHIVED
        assert "not restored" in tab._feedback_status_var.get()
    finally:
        tab.destroy()


@pytest.mark.gui
def test_the_archived_filter_lists_archived_images_after_a_restart_and_does_not_load_them(
    tk_root, tmp_path, monkeypatch
):
    paths = _outputs(tmp_path)
    first = ReviewTabFrame(tk_root)
    try:
        _attach_writer(first, tmp_path)
        first._set_selected_images(paths)
        first._on_decision_key("discard")
        first._on_decision_key("discard")
        assert [path.exists() for path in paths] == [False, False, True]
    finally:
        first.destroy()

    second = ReviewTabFrame(tk_root)
    try:
        _attach_writer(second, tmp_path)
        root = tmp_path / "output"
        token = second._revisions.begin_folder_scan()
        scan = scan_image_folder(root, skip=(arc.archive_root(root),))
        assert [path.name for path in scan.paths] == ["s2.png"]  # the scan never lists the archive
        second._publish_folder_scan(token, scan)

        _show_archived_filter(second)
        assert sorted(_visible_names(second)) == ["s0.png", "s1.png"]
        assert all("(in archive)" in row for row in second._row_texts)

        loaded: list[Path] = []
        monkeypatch.setattr(
            second.preview, "set_image_from_path", lambda path, *a, **k: loaded.append(path)
        )
        assert second._select_key(item_key(paths[0]))
        assert loaded == []  # no file exists at the original path: nothing is read from the archive
        assert "in the archive folder" in second._feedback_status_var.get()
        assert str(second.restore_button.cget("state")) == "normal"
    finally:
        second.destroy()


@pytest.mark.gui
def test_opening_a_recent_job_after_a_discard_and_restart_lists_the_archived_output(
    tk_root, tmp_path
):
    from datetime import datetime
    from types import SimpleNamespace

    from src.queue.job_history_store import JobHistoryEntry
    from src.queue.job_model import JobStatus

    paths = _outputs(tmp_path, 2)
    first = ReviewTabFrame(tk_root)
    try:
        _attach_writer(first, tmp_path)
        first._set_selected_images(paths)
        first._on_decision_key("discard")  # paths[0] moves into the archive
        assert not paths[0].exists()
    finally:
        first.destroy()

    entry = JobHistoryEntry(
        job_id="history-arc",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        result={
            "success": True,
            "artifact": {
                "artifact_type": "image",
                "primary_path": str(paths[0]),
                "output_paths": [str(path) for path in paths],
            },
            "variants": [],
            "metadata": {},
        },
    )
    second = ReviewTabFrame(tk_root, app_state=SimpleNamespace(history_items=[entry]))
    try:
        _attach_writer(second, tmp_path)
        second._on_open_recent_job()
        picker = second._set_picker
        picker.tree.selection_set("history-arc")
        picker._open()
        second.update()

        assert paths[1] in second.selected_images and paths[0] in second.selected_images
        _show_archived_filter(second)
        assert _visible_names(second) == [paths[0].name]
        assert "(in archive)" in second._row_texts[0]
        assert second._select_key(item_key(paths[0]))
        assert str(second.restore_button.cget("state")) == "normal"
        assert second._restore_current()
        assert paths[0].exists() and not _where(tmp_path, paths[0]).exists()
    finally:
        second.destroy()


@pytest.mark.gui
def test_the_decision_tooltips_say_what_discard_does(tk_root, tmp_path):
    tab = ReviewTabFrame(tk_root)
    try:
        paths = _outputs(tmp_path)
        _attach_writer(tab, tmp_path)
        tab._set_selected_images(paths)
        text = tab._decision_tooltips["discard"].text
        assert "archive folder" in text and "Nothing is deleted" in text
        assert "never changed" in tab._decision_tooltips["retain"].text
    finally:
        tab.destroy()
