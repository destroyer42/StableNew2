from __future__ import annotations

from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.operator_readiness_panel_v2 import OperatorReadinessPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.services.operator_readiness_service import (
    OperatorReadinessRecord,
    OperatorReadinessSnapshot,
    OperatorReadinessState,
)
from src.services.ui_state_store import UIStateStore


@pytest.fixture(autouse=True)
def no_asset_scan_in_presentation_tests(monkeypatch):
    # Geometry and artifact tests need no model library. Keep Tk teardown free
    # of unrelated asset worker callbacks; conditioning has its own injected tests.
    monkeypatch.setattr(
        "src.gui.widgets.openpose_picker_panel.OpenPosePickerPanel.refresh_library",
        lambda self: None,
    )


def _visible_inside(widget, viewport):
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    left, top = viewport.winfo_rootx(), viewport.winfo_rooty()
    assert left <= x and x + widget.winfo_width() <= left + viewport.winfo_width()
    assert top <= y and y + widget.winfo_height() <= top + viewport.winfo_height()


@pytest.mark.parametrize("geometry", ["1280x540", "1896x800"])
def test_prompt_editing_and_embedding_selectors_are_reachable(tk_root, tmp_path, geometry):
    tk_root.geometry(geometry)
    tk_root.deiconify()
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path / "packs")
    frame.pack(fill="both", expand=True)
    try:
        tk_root.update()
        tk_root.update_idletasks()
        assert frame.editor.winfo_height() >= 120
        assert frame.negative_editor.winfo_height() >= 72
        _visible_inside(frame.editor, frame.prompts_tab)
        _visible_inside(frame.negative_editor, frame.prompts_tab)
        frame.workspace_state.set_slot_text(0, "a mountain lake")
        frame.workspace_state.set_slot_negative(0, "blur")
        frame._refresh_editor()
        frame.editor_notebook.select(frame.embedding_scroll)
        tk_root.update_idletasks()
        frame.embedding_scroll._canvas.yview_moveto(0)
        tk_root.update_idletasks()
        _visible_inside(frame.embedding_picker.pos_entry, frame.embedding_scroll._canvas)
        frame.embedding_scroll._canvas.yview_moveto(1)
        tk_root.update_idletasks()
        _visible_inside(frame.embedding_picker.neg_entry, frame.embedding_scroll._canvas)
        frame.embedding_picker.set_positive_embeddings([("landscape", 0.8)])
        frame.editor_notebook.select(frame.prompts_tab)
        tk_root.update_idletasks()
        assert frame.editor.get("1.0", "end").strip() == "a mountain lake"
        assert frame.negative_editor.get("1.0", "end").strip() == "blur"
        assert frame.embedding_picker.get_positive_embeddings() == [("landscape", 0.8)]
    finally:
        frame.destroy()
        tk_root.withdraw()


def test_embedding_construction_and_destruction_preserve_global_wheel_router(tk_root, tmp_path):
    from src.gui.widgets.embedding_picker_panel import EmbeddingPickerPanel
    from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

    outer = ScrollableFrame(tk_root)
    original = tk_root.bind_all("<MouseWheel>")
    picker = EmbeddingPickerPanel(outer.inner, webui_root=str(tmp_path))
    assert tk_root.bind_all("<MouseWheel>") == original
    picker.destroy()
    assert tk_root.bind_all("<MouseWheel>") == original
    outer.destroy()


def test_readiness_recovery_is_reachable_with_long_guidance(tk_root, tmp_path):
    records = tuple(
        OperatorReadinessRecord(
            id=f"record-{i}" if i < 15 else "gpu_device",
            display_name=f"Readiness {i}",
            state=OperatorReadinessState.ACTION_REQUIRED,
            summary="A retained diagnostic with a recovery instruction. " * 3,
            blocking_reasons=("Check the recorded state.",),
            operator_actions=("Use the existing explicit recovery action.",),
            source="test",
        )
        for i in range(16)
    )
    service = SimpleNamespace(collect=lambda **_: OperatorReadinessSnapshot((), records))
    release = Mock()
    tk_root.geometry("780x520")
    tk_root.deiconify()
    panel = OperatorReadinessPanelV2(
        tk_root,
        service=service,
        on_confirm_gpu_recovery=release,
        ui_state_store=UIStateStore(tmp_path / "ui.json"),
    )
    panel.pack(fill="both", expand=True)
    try:
        tk_root.update()
        tk_root.update_idletasks()
        assert panel.body_scroll.has_scroll_overflow()
        panel.body_scroll._canvas.yview_moveto(1)
        tk_root.update_idletasks()
        _visible_inside(
            panel.record_widgets["gpu_device"]["confirm_gpu_recovery"], panel.body_scroll._canvas
        )
        _visible_inside(panel.refresh_button, tk_root)
        release.assert_not_called()
    finally:
        panel.destroy()
        tk_root.withdraw()


def test_optimizer_explains_inactive_anchor_and_logging(tk_root, tmp_path):
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path / "packs")
    try:
        tips = [getattr(widget, "tooltip", None) for widget in frame._prompt_optimizer_widgets]
        text = " ".join(tip.text for tip in tips if tip)
        assert "has no effect" in text
        assert "prompt text before and after" in text
        assert "does not truncate" in text
    finally:
        frame.destroy()


def test_history_publication_updates_only_exact_job_artifact(tk_root, tmp_path, monkeypatch):
    from src.gui.job_history_panel_v2 import JobHistoryPanelV2
    from tests.gui_v2.test_job_history_panel_v2 import _make_entry

    state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, app_state=state)
    panel.show_artifact_var.set(True)
    panel.artifact_thumbnail.set_image_from_path = Mock()
    image = tmp_path / "result.png"
    image.write_bytes(b"recorded image; decoding is mocked")
    other = _make_entry("another-job", replayable=True)
    other.result = {"artifact": {"artifact_type": "image", "primary_path": str(image)}}
    selected = _make_entry("displayed-job", replayable=True)
    try:
        panel._populate_history([other, selected])
        rows = panel.history_tree.get_children()
        panel.history_tree.selection_set(rows[1])
        panel._on_select()
        panel.artifact_thumbnail.set_image_from_path.assert_not_called()
        selected.result = {"artifact": {"artifact_type": "image", "primary_path": str(image)}}
        panel._populate_history([other, selected])
        panel.artifact_thumbnail.set_image_from_path.assert_called_once_with(str(image))
        panel.artifact_thumbnail.set_image_from_path.reset_mock()
        panel._populate_history([other, selected])
        panel.artifact_thumbnail.set_image_from_path.assert_not_called()
        image.unlink()
        panel._refresh_selected_artifact()
        assert panel._shown_artifact_path is None
        panel.artifact_thumbnail.set_image_from_path.assert_not_called()
    finally:
        panel.destroy()


def test_selected_video_plays_its_recorded_clip_not_the_poster_and_respects_visibility(
    tk_root, tmp_path, monkeypatch
):
    import src.gui.job_history_panel_v2 as history_module
    from src.gui.job_history_panel_v2 import JobHistoryPanelV2
    from tests.gui_v2.test_job_history_panel_v2 import _make_entry

    class FakeVideoPreview(ttk.Frame):
        def __init__(self, parent, *, edge):
            super().__init__(parent)
            self.shown: list[str] = []
            self.stop_count = 0

        def show(self, path):
            self.shown.append(path)

        def stop(self):
            self.stop_count += 1

    monkeypatch.setattr(history_module, "VideoPreviewWidget", FakeVideoPreview)
    state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, app_state=state)
    panel.show_artifact_var.set(True)
    panel.artifact_thumbnail.set_image_from_path = Mock()
    thumb = tmp_path / "frame.png"
    thumb.write_bytes(b"thumbnail")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"recorded clip; playback is faked")
    entry = _make_entry("video", replayable=True)
    entry.payload_summary = "explicit"
    entry.result = {
        "artifact": {
            "artifact_type": "video",
            "primary_path": str(clip),
            "thumbnail_path": str(thumb),
        }
    }
    try:
        panel._populate_history([entry])
        panel.history_tree.selection_set(panel.history_tree.get_children()[0])
        panel._on_select()
        player = panel.artifact_video_preview
        assert isinstance(player, FakeVideoPreview)
        assert player.shown == [str(clip)]
        panel.artifact_thumbnail.set_image_from_path.assert_not_called()
        assert panel._shown_artifact_path == str(clip)
        assert panel.artifact_frame.winfo_manager() == "grid"
        stops = player.stop_count
        state.set_content_visibility_mode("sfw")
        state.flush_now()
        assert player.stop_count > stops
        assert player.shown == [str(clip)]
        assert panel._shown_artifact_path is None
        assert panel.artifact_frame.winfo_manager() == ""
        assert not player.winfo_manager()
        assert panel.artifact_status_var.get() == ""
        assert panel.artifact_open_btn.instate(["disabled"])
        assert panel.artifact_reveal_btn.instate(["disabled"])
        panel.artifact_thumbnail.set_image_from_path.assert_not_called()
    finally:
        panel.destroy()


@pytest.mark.parametrize("kind", ["directory", "video", "manifest", "missing"])
def test_non_image_artifacts_do_not_enter_image_decoder(tk_root, tmp_path, monkeypatch, kind):
    monkeypatch.setattr("src.gui.preview_panel_v2.PREVIEW_STATE_PATH", tmp_path / "preview.json")
    path = (
        tmp_path
        / {
            "directory": "folder.png",
            "video": "clip.mp4",
            "manifest": "manifest.json",
            "missing": "absent.png",
        }[kind]
    )
    if kind == "directory":
        path.mkdir()
    elif kind != "missing":
        path.write_bytes(b"data")
    panel = PreviewPanelV2(tk_root, app_state=AppStateV2())
    try:
        panel._show_preview_var.set(True)
        panel.thumbnail.set_image_from_path = Mock()
        panel.update_with_summary(
            SimpleNamespace(job_id="job", artifact={"primary_path": str(path)})
        )
        panel.thumbnail.set_image_from_path.assert_not_called()
    finally:
        panel.destroy()
