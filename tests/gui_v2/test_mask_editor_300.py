"""Real Tk mask editing, stale-preview protection and canonical admission without a runtime."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.gui.mask_editor_dialog import MaskEditorDialog
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui_v2.mask_editor_state import MaskDocument, MaskViewport
from src.image_backends import masked_inpaint as capability
from src.pipeline import image_edit_inputs as inputs
from tests.pipeline.test_inpaint300 import png


def test_brush_zoom_pan_and_polarity_use_original_pixels():
    document = MaskDocument((128, 128))
    viewport = MaskViewport(2, 20, 40)
    point = viewport.image_point(100, 120)
    assert point == (40, 40)
    document.checkpoint()
    document.paint(point, point, 9)
    assert document.mask.getpixel((40, 40)) == 255
    assert document.mask.getpixel((20, 20)) == 0
    before = document.mask.tobytes()
    viewport.zoom(2, 100, 120)
    assert viewport.image_point(100, 120) == point
    viewport.x += 17
    viewport.y -= 3
    assert viewport.image_point(117, 117) == point
    document.paint(point, point, 3, erase=True)
    assert document.mask.getpixel((40, 40)) == 0
    document.undo()
    assert document.mask.getextrema() == (0, 0)
    document.redo()
    assert document.mask.getpixel((40, 40)) == 0
    document.clear()
    assert document.mask.getextrema() == (0, 0)
    document.undo()
    assert document.mask.tobytes() != before  # undo Clear recovers the erased stroke


def test_overlay_alignment_and_zoom_do_not_change_mask_bytes():
    document = MaskDocument((128, 128))
    document.paint((40, 40), (40, 40), 5)
    before = document.mask.tobytes()
    viewport = MaskViewport(2, 10, 30)
    view = document.render(Image.new("RGB", (128, 128), "blue"), viewport, (250, 250))
    assert view.getpixel((90, 110))[0] > 0
    assert view.getpixel((30, 50)) == (0, 0, 255)
    assert document.mask.tobytes() == before


@pytest.fixture
def dialog(tk_root, tmp_path, monkeypatch):
    from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily

    monkeypatch.setattr(
        inputs, "default_snapshot_root", lambda: tmp_path / "state" / "image_edit_inputs"
    )
    monkeypatch.setattr(
        capability,
        "RegistryFamilyLookup",
        lambda: lambda _: CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()),
    )
    path = tmp_path / "source.png"
    path.write_bytes(png())
    controller = SimpleNamespace(
        _extract_reprocess_baseline_from_image=lambda _: {"model": "sdxl"},
        _build_reprocess_config=lambda _: {
            "model": "sdxl",
            "backend_options": {"image": {"backend_id": "forge_webui"}},
            "img2img": {"steps": 20, "sampler_name": "Euler", "scheduler": "Karras", "seed": 7},
        },
        job_service=SimpleNamespace(
            submit_njrs=Mock(side_effect=lambda rows, _: [row.job_id for row in rows])
        ),
    )
    runner = BackgroundWorkRunner(
        spawn=lambda _, target: target(), dispatch=lambda callback: callback()
    )
    editor = MaskEditorDialog(tk_root, source_path=path, controller=controller, runner=runner)
    editor.update_idletasks()
    editor._fit()
    editor.prompt.insert("1.0", "add a red flower")
    editor.update()
    yield editor, controller
    editor._closed = True
    editor.destroy()


def paint(editor):
    editor.viewport = MaskViewport(2, 10, 10)
    editor.brush_size.set(10)
    editor.canvas.event_generate("<ButtonPress-1>", x=90, y=90)
    editor.canvas.event_generate("<B1-Motion>", x=110, y=110)
    editor.canvas.event_generate("<ButtonRelease-1>", x=110, y=110)
    assert editor.document.mask.getpixel((40, 40)) == 255


@pytest.mark.gui
def test_tk_brush_preview_and_queue_submit_exact_frozen_record_once(dialog):
    editor, controller = dialog
    paint(editor)
    editor.preview_button.invoke()
    assert editor._preview is not None, editor.status.get()
    preview = editor._preview
    frozen = deepcopy(preview.job.to_queue_snapshot())
    assert editor.queue_button.instate(["!disabled"])
    assert "effective_img2img" in editor.details.get("1.0", "end")
    editor.queue_button.invoke()
    editor.queue_button.invoke()
    controller.job_service.submit_njrs.assert_called_once()
    assert controller.job_service.submit_njrs.call_args.args[0][0] is preview.job
    assert preview.job.to_queue_snapshot() == frozen
    assert editor.document.mask.getpixel((40, 40)) == 255


@pytest.mark.gui
@pytest.mark.parametrize("change", ["paint", "denoise", "source", "admission_failure"])
def test_edits_or_source_drift_cannot_silently_queue_another_preview(dialog, change):
    editor, controller = dialog
    paint(editor)
    editor.preview_button.invoke()
    assert editor._preview is not None, editor.status.get()
    if change == "paint":
        paint(editor)
    elif change == "denoise":
        editor.denoise.set(0.8)
    elif change == "source":
        Image.new("RGB", (128, 128), "green").save(editor.source_path)
    else:
        controller.job_service.submit_njrs.side_effect = ValueError("refused")
    editor.queue_button.invoke()
    if change in {"paint", "denoise", "source"}:
        controller.job_service.submit_njrs.assert_not_called()
    else:
        assert "Admission failed" in editor.status.get()
        assert editor.document.mask.getpixel((40, 40)) == 255
        assert editor._preview is not None
    assert editor.queue_button.instate(["disabled"])


@pytest.mark.gui
def test_pending_preview_is_discarded_if_form_changes(dialog):
    editor, _ = dialog
    paint(editor)
    pending = []
    editor._runner = SimpleNamespace(start=lambda name, work, done: pending.append((work, done)))
    editor.preview_button.invoke()
    editor.denoise.set(0.7)
    work, done = pending.pop()
    done(work())
    assert editor._preview is None
    assert editor.queue_button.instate(["disabled"])
    assert "Draft changed" in editor.status.get()


@pytest.mark.gui
def test_default_worker_keeps_load_prepare_and_admission_off_tk(dialog, monkeypatch):
    import src.gui.mask_editor_dialog as module

    original_editor, controller = dialog
    main_thread = threading.get_ident()
    workers, renders = [], []
    original_read, original_prepare = module.read_source, module.prepare_mask_edit

    def read(path):
        workers.append(threading.get_ident())
        return original_read(path)

    def prepare(**kwargs):
        workers.append(threading.get_ident())
        return original_prepare(**kwargs)

    def admit(rows, policy):
        workers.append(threading.get_ident())
        return [row.job_id for row in rows]

    monkeypatch.setattr(module, "read_source", read)
    monkeypatch.setattr(module, "prepare_mask_edit", prepare)
    controller.job_service.submit_njrs.side_effect = admit
    editor = MaskEditorDialog(
        original_editor, source_path=original_editor.source_path, controller=controller
    )
    editor.status.trace_add("write", lambda *_: renders.append(threading.get_ident()))

    def complete():
        deadline = time.monotonic() + 5
        while editor._busy and time.monotonic() < deadline:
            original_editor.update()
            time.sleep(0.01)
        assert not editor._busy

    try:
        complete()
        editor.prompt.insert("1.0", "a flower")
        editor.update()
        paint(editor)
        editor.preview_button.invoke()
        complete()
        assert editor._preview is not None, editor.status.get()
        editor.queue_button.invoke()
        complete()
        assert "Queued frozen job" in editor.status.get()
        assert len(workers) == 3 and all(value != main_thread for value in workers)
        assert renders and all(value == main_thread for value in renders)
    finally:
        editor._closed = True
        editor.destroy()


@pytest.mark.gui
def test_review_edit_mask_action_opens_only_one_still_image(tk_root, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "src.gui.mask_editor_dialog.MaskEditorDialog",
        lambda parent, **kwargs: opened.append(kwargs),
    )
    path = tmp_path / "source.png"
    path.write_bytes(png())
    review = SimpleNamespace(_get_selected_review_paths=lambda: [path], app_controller=object())
    ReviewTabFrame._open_mask_editor(review)
    assert opened[0]["source_path"] == path
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.messagebox.showwarning", lambda *a, **k: None
    )
    review._get_selected_review_paths = lambda: [path, path]
    ReviewTabFrame._open_mask_editor(review)
    assert len(opened) == 1
