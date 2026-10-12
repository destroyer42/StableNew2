"""PR-BATCH-OPS-201: batch outputs reach the real Review tab through its existing selection behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.batch_operations_panel_v2 import BatchOperationsPanelV2
from src.gui.controllers.video_workspace_handoff import route_images_to_review
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.queue.batch_membership import BatchKey, BatchKind
from tests.gui_v2.test_batch_operations_session_201 import ManualRunner
from tests.helpers.batch_ops_201 import admit, image_file, make_stack, review_njr

pytestmark = pytest.mark.gui


class _Notebook:
    def __init__(self) -> None:
        self.selected = []

    def select(self, tab) -> None:
        self.selected.append(tab)


@pytest.fixture
def review(tk_root):
    tab = ReviewTabFrame(tk_root)
    yield tab, SimpleNamespace(review_tab=tab, center_notebook=_Notebook())
    tab.destroy()


def test_route_images_to_review_keeps_order_and_leaves_stage_toggles_alone(review, tmp_path):
    tab, window = review
    files = [image_file(tmp_path / f"p{i}.png", i) for i in range(3)]
    tab.stage_img2img_var.set(True)
    tab.stage_upscale_var.set(True)
    tab._active_handoff = SimpleNamespace(source_metadata_by_path={"x": {}}, direct_queue_preview=None)

    routed = route_images_to_review(
        main_window=window, image_paths=[files[2], files[0], files[2], files[1]], status_message="from batch")

    assert routed == [str(files[2]), str(files[0]), str(files[2]), str(files[1])]
    assert tab.selected_images == [files[2], files[0], files[1]]  # given order; duplicate collapsed
    assert tab.selection_label.cget("text") == "3 image(s) selected"
    assert tab.workflow_hint_label.cget("text") == "from batch"
    assert window.center_notebook.selected == [tab]
    assert tab._active_handoff is None  # an older staged hand-off cannot attach to unrelated images
    assert tab.stage_img2img_var.get() is True and tab.stage_upscale_var.get() is True  # toggles untouched


def test_route_refusals_are_explicit(review):
    tab, window = review
    with pytest.raises(ValueError):
        route_images_to_review(main_window=window, image_paths=[])
    with pytest.raises(RuntimeError, match="Review tab is not available"):
        route_images_to_review(main_window=SimpleNamespace(), image_paths=["a.png"])
    with pytest.raises(RuntimeError, match="does not support"):
        route_images_to_review(main_window=SimpleNamespace(review_tab=object()), image_paths=["a.png"])
    with pytest.raises(ValueError):
        tab.load_selected_images([])


def test_batch_view_open_in_review_selects_exactly_the_usable_outputs(tk_root, tmp_path, review):
    tab, window = review
    stack = make_stack(tmp_path)
    files = [image_file(tmp_path / "out" / f"r{i}.png", i) for i in range(4)]
    admit(stack, [review_njr(f"o{i}", "out", source_count=4) for i in range(4)])
    for i in range(4):
        job = stack.queue.claim_next_job()
        stack.queue.mark_completed(job.job_id, {"success": True, "variants": [
            {"stage": "img2img", "path": str(files[i])}]})
    files[1].write_bytes(b"corrupt")  # recorded but unreadable: must not reach Review
    runner = ManualRunner()
    panel = BatchOperationsPanelV2(tk_root, service=stack.operations, runner=runner,
                                   main_window_provider=lambda: window)
    panel.pack()
    try:
        panel.refresh()
        runner.drain()
        key = BatchKey(BatchKind.REVIEW, "out")
        panel.session.select_batch(key)
        runner.drain()
        panel.job_tree.selection_set(["o0", "o1", "o3"])
        panel.job_tree.event_generate("<<TreeviewSelect>>")
        tk_root.update()
        panel.review_button.invoke()
        runner.drain()
        assert tab.selected_images == [Path(files[0]), Path(files[3])]  # table order, usable files only
        assert "Opened 2 image(s) in Review" in panel.status_var.get()
        assert "missing or unreadable" in panel.status_var.get()
    finally:
        panel.destroy()
