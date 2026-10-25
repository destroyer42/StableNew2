"""Media lifecycle, renderer transitions, budgets and host authority without real decoders."""

import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from src.gui.app_state_v2 import AppStateV2
from src.gui.view_contracts.media_image_decode import (
    InspectionImage,
    decode_inspection_image,
    render_viewport,
)
from src.gui.view_contracts.media_inspector_contract import MediaInspectorState
from src.gui.widgets.media_inspector import MediaInspector


class Work:
    def __init__(self):
        self.tasks = []
        self.closed = False

    def submit(self, key, work, *, on_result=None, on_error=None, **kwargs):
        self.tasks.append((key, work, on_result, on_error))
        return len(self.tasks)

    def finish(self, index):
        key, work, done, error = self.tasks[index]
        try:
            value = work()
        except Exception as exc:
            if error and not self.closed:
                error(exc)
        else:
            if done and not self.closed:
                done(value)

    def close(self):
        self.closed = True


@pytest.fixture
def inspector(tk_root, monkeypatch):
    work = Work()
    monkeypatch.setattr(
        "src.gui.widgets.media_inspector.build_edit_work_runner", lambda owner: work
    )
    widget = MediaInspector(tk_root)
    widget._decode_image = lambda path, cancel: InspectionImage(
        Image.new("RGB", (100, 50), "red"), (100, 50)
    )
    widget._mapped(SimpleNamespace(widget=widget))
    yield widget, work
    widget.destroy()


def test_pure_selection_default_revision_eligibility_and_zoom():
    state = MediaInspectorState(default_shown=False, shown=False)
    assert state.select("first.png") and not state.renderable
    token = state.revision
    state.visibility(shown=True)
    assert state.renderable and state.revision > token
    assert not state.select("first.png") and state.shown
    state.zoom_by(100)
    assert state.zoom == 8
    state.zoom_by(0.0001)
    assert state.zoom == 0.125
    state.visibility(eligible=False)
    assert not state.renderable
    state.select("second.png")
    assert not state.shown and state.zoom is None


@pytest.mark.parametrize("operation", ["hide", "replace", "deny", "unmap", "detach", "destroy"])
def test_stale_image_result_cannot_publish_after_lifecycle_change(inspector, operation):
    widget, work = inspector
    widget.set_media("one.png")
    token = widget.model.revision
    if operation == "hide":
        widget.set_visibility(False)
    elif operation == "replace":
        widget.set_media("two.png")
    elif operation == "deny":
        widget.set_eligibility(False)
    elif operation == "unmap":
        widget._unmapped(SimpleNamespace(widget=widget))
    elif operation == "detach":
        widget.detach()
    else:
        widget.destroy()
    work.finish(0)
    assert widget._image is None
    assert widget._photo_image is None
    assert widget._closed or widget.model.revision != token


def test_same_selection_does_not_decode_again_and_hide_releases(inspector):
    widget, work = inspector
    widget.set_media("one.png")
    work.finish(0)
    widget.set_media("one.png")
    assert len(work.tasks) == 1
    widget.set_visibility(False)
    assert widget._image is None and widget._photo_image is None
    widget.set_visibility(True)
    assert len(work.tasks) == 2


def test_host_empty_status_survives_map_idle_policy_and_clear(inspector):
    widget, work = inspector
    for text in ("No saved artifact", "Hidden by content visibility"):
        widget.set_placeholder(text)
        widget._mapped(SimpleNamespace(widget=widget))
        widget._policy_changed()
        widget.update_idletasks()
        assert widget.status_var.get() == text
        assert widget.current_path() is None and work.tasks == []
    widget.clear()
    assert widget.status_var.get() == "Select media"


def test_video_only_omits_image_controls_and_image_return_publishes(inspector):
    from src.video.review_preview import PreviewResult

    widget, work = inspector
    widget._decode_video = lambda path, cancel: PreviewResult(
        path=path, status="failed", message="fixture"
    )
    widget.set_media("one.mp4")
    assert not widget._zoom_bar.winfo_manager()
    widget.set_media("still.png")
    assert widget._zoom_bar.winfo_manager() == "pack"
    work.finish(len(work.tasks) - 1)
    widget._render_image()
    work.finish(len(work.tasks) - 1)
    assert widget._photo_image is not None
    assert widget.current_path() == "still.png"


def test_detach_close_return_and_parent_destroy_do_not_change_selection(inspector):
    widget, work = inspector
    widget.set_media("one.png")
    widget.actual_size()
    widget.detach()
    window = widget._window
    widget.detach()
    assert widget._window is window
    assert widget.model.path == "one.png" and widget.model.zoom == 1
    assert widget._host.winfo_toplevel() is window
    widget.dock()
    assert widget._window is None and not widget.model.detached
    assert widget.model.path == "one.png" and widget.model.zoom == 1
    widget.detach()
    window = widget._window
    widget.destroy()
    assert not window.winfo_exists() and work.closed


def test_policy_higher_priority_than_local_show(inspector):
    widget, work = inspector
    widget._app_state = AppStateV2()
    widget._app_state.content_visibility_mode = "sfw"
    widget.set_media("safe-name.png", subject={"prompt": "explicit nude"})
    widget.set_visibility(True)
    assert not widget.model.renderable and work.tasks == []
    widget._app_state.content_visibility_mode = "nsfw"
    widget._policy_changed()
    assert widget.model.renderable and len(work.tasks) == 1
    widget._app_state.content_visibility_mode = "sfw"
    widget._policy_changed()
    work.finish(0)
    assert widget._image is None


def test_resize_uses_retained_bounded_image_not_file_decode(inspector):
    widget, work = inspector
    widget.set_media("one.png")
    work.finish(0)
    widget._render_image()
    assert work.tasks[-1][0] == "media"
    work.finish(1)
    assert widget._photo_image is not None
    widget.actual_size()
    widget._render_image()
    assert widget.current_path() == "one.png"
    assert len(work.tasks) == 3


def test_image_decode_budget_missing_corrupt_and_truthful_downsample(tmp_path, monkeypatch):
    cancel = threading.Event()
    small = tmp_path / "small.png"
    Image.new("RGB", (40, 20)).save(small)
    assert decode_inspection_image(str(small), cancel).native
    large = tmp_path / "large.png"
    Image.new("RGB", (1600, 20)).save(large)
    decoded = decode_inspection_image(str(large), cancel)
    assert decoded.source_size == (1600, 20) and not decoded.native
    monkeypatch.setattr("src.gui.view_contracts.media_image_decode.MAX_SOURCE_PIXELS", 100)
    with pytest.raises(ValueError, match="budget"):
        decode_inspection_image(str(small), cancel)
    with pytest.raises(ValueError, match="missing"):
        decode_inspection_image(str(tmp_path / "missing.png"), cancel)
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="corrupt"):
        decode_inspection_image(str(corrupt), cancel)


def test_zoomed_viewport_never_allocates_virtual_full_image():
    image = Image.new("RGB", (1536, 1536))
    rendered, virtual, position = render_viewport(image, (800, 600), 8, (0.5, 0.5))
    assert rendered.size == (800, 600)
    assert virtual == (12288, 12288)
    fitted, virtual, position = render_viewport(image, (400, 300), None, (0, 0))
    assert fitted.size == (300, 300)
    assert position == (50, 0)


@pytest.mark.parametrize("operation", ["hide", "replace", "deny", "detach", "unmap", "destroy"])
def test_existing_video_session_cancels_and_releases_on_transition(inspector, operation):
    from src.video.review_preview import PreviewClip, PreviewResult

    widget, work = inspector
    events = []

    def decode(path, cancel):
        events.append(cancel)
        clip = PreviewClip(path, 2, 2, 2, 2, 24, 1, 1, 1.0, bytes(12))
        return PreviewResult(path=path, status="ok", clip=clip)

    widget._decode_video = decode
    widget.set_media("clip.mp4")
    old = widget._video
    work.finish(0)
    assert old.session.clip is not None
    widget.set_media("clip.mp4")
    assert len(work.tasks) == 1  # refresh never decodes an unchanged clip again
    if operation == "hide":
        widget.set_visibility(False)
    elif operation == "replace":
        widget.set_media("next.mp4")
    elif operation == "deny":
        widget.set_eligibility(False)
    elif operation == "detach":
        widget.detach()
    elif operation == "unmap":
        widget._unmapped(SimpleNamespace(widget=widget))
    else:
        widget.destroy()
    assert events[0].is_set()
    assert old.session.clip is None and old._tick_id is None and old._photo is None
    assert all(task[0] == "media" for task in work.tasks)


def test_late_video_decode_and_rapid_show_cannot_publish(inspector):
    from src.video.review_preview import PreviewResult

    widget, work = inspector
    widget._decode_video = lambda path, cancel: PreviewResult(
        path=path, status="failed", message="late"
    )
    widget.set_media("one.mp4")
    old = widget._video
    widget.set_visibility(False)
    widget.set_visibility(True)
    widget.set_media("two.mp4")
    work.finish(0)
    assert old.session.clip is None and old.session.path == ""
    assert widget._video.session.path == "two.mp4"


@pytest.mark.parametrize(
    "width,height,scaling", [(1366, 768, 1), (1920, 1080, 1), (1366, 768, 1.5)]
)
def test_controls_reachable_at_supported_sizes(tk_root, width, height, scaling):
    original_scaling = tk_root.tk.call("tk", "scaling")
    tk_root.tk.call("tk", "scaling", scaling * 96 / 72)
    widget = MediaInspector(tk_root, width=144, height=144)
    widget.pack(fill="both", expand=True)
    tk_root.geometry(f"{width}x{height}")
    tk_root.deiconify()
    tk_root.update()
    try:
        for control in (widget.show_button, widget.detach_button, widget.open_button):
            assert control.winfo_ismapped()
            assert 0 <= control.winfo_rootx() - tk_root.winfo_rootx() < width
            assert 0 <= control.winfo_rooty() - tk_root.winfo_rooty() < height
        assert widget.toolbar.winfo_reqwidth() <= 200 * scaling
    finally:
        widget.destroy()
        tk_root.tk.call("tk", "scaling", original_scaling)


def test_hidden_notebook_owner_suspends_detached_comparison(tk_root, monkeypatch):
    from tkinter import ttk

    work = Work()
    monkeypatch.setattr(
        "src.gui.widgets.media_inspector.build_edit_work_runner", lambda owner: work
    )
    tabs = ttk.Notebook(tk_root)
    first, second = ttk.Frame(tabs), ttk.Frame(tabs)
    tabs.add(first, text="First")
    tabs.add(second, text="Second")
    tabs.pack()
    widget = MediaInspector(first)
    widget.pack()
    widget._decode_image = lambda path, cancel: InspectionImage(
        Image.new("RGB", (10, 10)), (10, 10)
    )
    tk_root.deiconify()
    tk_root.update()
    widget.set_media("one.png")
    widget.detach()
    tk_root.update()
    assert widget.model.active
    tabs.select(second)
    tk_root.update()
    assert not widget.model.active and widget._image is None and widget._video is None
    assert widget.current_path() == "one.png"
    tabs.destroy()


def test_real_coordinator_serializes_old_and_new_detached_video(tk_root, monkeypatch):
    from src.video.review_preview import PreviewResult
    from tests.gui_v2.edit_work_helpers import use_manual_registry

    registry = use_manual_registry(monkeypatch)
    calls = []

    def decode(path, cancel):
        calls.append((path, cancel.is_set()))
        return PreviewResult(path=path, status="failed", message="fixture")

    widget = MediaInspector(tk_root, decode=decode)
    widget._mapped(SimpleNamespace(widget=widget))
    try:
        widget.set_media("one.mp4")
        old = widget._video
        widget.detach()
        assert len(registry.queued) == 1
        assert len(widget._work.metrics()["inflight"]) == 1
        assert list(widget._work.metrics()["pending"]) == ["media"]
        registry.run_next()
        assert calls == [("one.mp4", True)]
        assert len(registry.queued) == 1  # replacement starts only after canceled work exits
        registry.run_next()
        assert calls == [("one.mp4", True), ("one.mp4", False)]
        assert old.session.clip is None and old._tick_id is None
        assert widget._video.session.path == "one.mp4"
        assert widget._work.metrics()["inflight"] == {}
    finally:
        widget.destroy()


def test_outer_and_detached_show_share_one_value_without_clear_reset(tk_root, monkeypatch):
    import tkinter as tk

    work = Work()
    monkeypatch.setattr(
        "src.gui.widgets.media_inspector.build_edit_work_runner", lambda owner: work
    )
    shown = tk.BooleanVar(master=tk_root, value=False)
    widget = MediaInspector(tk_root, shown_var=shown, show_control=False)
    widget._mapped(SimpleNamespace(widget=widget))
    try:
        widget.set_media("one.png")
        assert not widget.model.renderable and not shown.get()
        shown.set(True)
        widget.set_media("one.png")
        widget.detach()
        widget.set_visibility(False)
        assert not shown.get() and widget._image is None
        shown.set(True)
        widget.set_media("one.png")
        assert widget.model.renderable
        shown.set(False)
        widget.clear()
        assert not shown.get() and not widget.model.shown and widget._window is None
    finally:
        widget.destroy()
