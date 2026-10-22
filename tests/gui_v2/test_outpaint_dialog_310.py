"""Real Tk Extend Canvas: anchored view, preview/queue identity, stale work, close during work and reachability."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.gui.outpaint_dialog import OutpaintDialog
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui_v2.outpaint_canvas_view import canvas_view, render_canvas_view
from src.image_backends import masked_inpaint as capability
from src.pipeline import image_edit_inputs as inputs
from src.pipeline.outpaint_canvas import Extents
from tests.pipeline.test_outpaint_frozen_310 import H, W, original_image, png_bytes

PROMPT = "the meadow continues"


# ------------------------------------------------------------------ pure view (no Tk)


@pytest.mark.parametrize(
    "extents",
    [
        Extents(left=64),
        Extents(right=64),
        Extents(top=40),
        Extents(bottom=40),
        Extents(8, 16, 24, 32),
    ],
)
def test_view_keeps_the_original_anchored_at_left_top_as_margins_change(extents):
    view = canvas_view((W, H), extents, (420, 300))
    canvas, original = view.canvas, view.original
    assert original[0] - canvas[0] == pytest.approx(extents.left * view.scale)
    assert original[1] - canvas[1] == pytest.approx(extents.top * view.scale)
    assert original[2] - original[0] == pytest.approx(W * view.scale)
    assert original[3] - original[1] == pytest.approx(H * view.scale)
    assert canvas[2] - original[2] == pytest.approx(extents.right * view.scale)
    assert canvas[3] - original[3] == pytest.approx(extents.bottom * view.scale)
    assert canvas[0] >= 0 and canvas[1] >= 0 and canvas[2] <= 420 and canvas[3] <= 300


def test_rendered_view_draws_original_inside_boundary_and_mask_black_over_it():
    proxy = original_image()
    extents = Extents(left=32, top=16)
    size = (400, 300)
    view = canvas_view((W, H), extents, size)
    image = render_canvas_view(proxy, (W, H), extents, size)
    cx, cy = (view.original[0] + view.original[2]) / 2, (view.original[1] + view.original[3]) / 2
    assert image.getpixel((round(cx), round(cy))) != image.getpixel(
        (round(view.canvas[0]) + 3, round(view.canvas[1]) + 3)
    )
    mask = render_canvas_view(proxy, (W, H), extents, size, show_mask=True)
    assert mask.getpixel((round(cx), round(cy))) == (0, 0, 0)
    assert mask.getpixel((round(view.canvas[0]) + 3, round(view.canvas[1]) + 3)) == (255, 255, 255)


# ------------------------------------------------------------------ real Tk


@pytest.fixture
def make_dialog(tk_root, tmp_path, monkeypatch):
    from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily

    monkeypatch.setattr(
        inputs, "default_snapshot_root", lambda: tmp_path / "state" / "image_edit_inputs"
    )
    monkeypatch.setattr(
        capability,
        "RegistryFamilyLookup",
        lambda: lambda name: CompatibilityProfile(
            CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()
        )
        if name == "sdxl"
        else None,
    )
    path = tmp_path / "source.png"
    path.write_bytes(png_bytes(original_image()))
    made = []

    def build(model="sdxl", runner=None, controller=None):
        controller = controller or SimpleNamespace(
            _extract_reprocess_baseline_from_image=lambda _: {"model": model, "job_id": "parent"},
            _build_reprocess_config=lambda _: {
                "model": model,
                "backend_options": {"image": {"backend_id": "forge_webui"}},
                "img2img": {"steps": 20, "sampler_name": "Euler", "scheduler": "Karras", "seed": 7},
            },
            job_service=SimpleNamespace(
                submit_njrs=Mock(side_effect=lambda rows, _: [row.job_id for row in rows])
            ),
        )
        runner = runner or BackgroundWorkRunner(
            spawn=lambda _, target: target(), dispatch=lambda callback: callback()
        )
        dialog = OutpaintDialog(tk_root, source_path=path, controller=controller, runner=runner)
        dialog.update_idletasks()
        made.append(dialog)
        return dialog, controller

    yield SimpleNamespace(build=build, path=path)
    for dialog in made:
        dialog._closed = True
        try:
            dialog.destroy()
        except Exception:
            pass


def margins(dialog, left=16, right=8, top=24, bottom=0):
    dialog.left.set(left)
    dialog.right.set(right)
    dialog.top.set(top)
    dialog.bottom.set(bottom)
    dialog.prompt.delete("1.0", "end")
    dialog.prompt.insert("1.0", PROMPT)
    dialog.update()


@pytest.mark.gui
def test_select_extend_preview_inspect_and_queue_exact_frozen_record_once(make_dialog):
    dialog, controller = make_dialog.build()
    assert "Supported target" in dialog.support.get()
    margins(dialog)
    assert "152 × 120" in dialog.dimensions.get()
    dialog.preview_button.invoke()
    assert dialog._preview is not None, dialog.status.get()
    preview = dialog._preview
    frozen = deepcopy(preview.job.to_queue_snapshot())
    details = dialog.details.get("1.0", "end")
    for expected in (
        "original_pixels_pasted.v1",
        "new_region_white_original_black.v1",
        "sha256",
        "parent",
    ):
        assert expected in details
    assert "not been qualified" in details
    assert dialog.queue_button.instate(["!disabled"])
    dialog.queue_button.invoke()
    dialog.queue_button.invoke()  # a double click cannot admit twice
    controller.job_service.submit_njrs.assert_called_once()
    assert controller.job_service.submit_njrs.call_args.args[0][0] is preview.job
    assert preview.job.to_queue_snapshot() == frozen
    assert "Queued frozen job" in dialog.status.get()
    assert make_dialog.path.read_bytes() == png_bytes(original_image())


@pytest.mark.gui
@pytest.mark.parametrize("change", ["left", "bottom", "prompt", "denoise", "blur", "source"])
def test_any_change_invalidates_the_approved_preview(make_dialog, change):
    dialog, controller = make_dialog.build()
    margins(dialog)
    dialog.preview_button.invoke()
    assert dialog._preview is not None, dialog.status.get()
    if change == "left":
        dialog.left.set(24)
    elif change == "bottom":
        dialog.bottom.set(8)
    elif change == "prompt":
        dialog.prompt.insert("end", " more")
        dialog.update()
    elif change == "denoise":
        dialog.denoise.set(0.7)
    elif change == "blur":
        dialog.blur.set(12)
    else:
        Image.new("RGB", (W, H), "green").save(make_dialog.path)
    dialog.queue_button.invoke()
    if change == "source":
        assert (
            dialog._preview is not None
        )  # still queueable in the UI; admission itself must refuse
        assert "Admission failed" in dialog.status.get() and "Source changed" in dialog.status.get()
    else:
        assert dialog._preview is None and dialog.queue_button.instate(["disabled"])
    controller.job_service.submit_njrs.assert_not_called()


@pytest.mark.gui
def test_stale_worker_result_cannot_restore_an_outdated_preview(make_dialog):
    pending = []
    runner = SimpleNamespace(start=lambda name, work, done: pending.append((name, work, done)))
    sync = BackgroundWorkRunner(
        spawn=lambda _, target: target(), dispatch=lambda callback: callback()
    )
    dialog, _ = make_dialog.build(runner=sync)
    margins(dialog)
    dialog._runner = runner
    dialog.preview_button.invoke()
    dialog.right.set(16)  # the draft changes while the worker is still running
    _, work, done = pending.pop()
    done(work())
    assert dialog._preview is None and dialog.queue_button.instate(["disabled"])
    assert "Draft changed" in dialog.status.get()


@pytest.mark.gui
def test_closing_during_work_discards_late_callbacks_without_error(make_dialog):
    pending = []
    sync = BackgroundWorkRunner(
        spawn=lambda _, target: target(), dispatch=lambda callback: callback()
    )
    dialog, controller = make_dialog.build(runner=sync)
    margins(dialog)
    dialog._runner = SimpleNamespace(start=lambda name, work, done: pending.append((work, done)))
    dialog.preview_button.invoke()
    dialog._close()
    work, done = pending.pop()
    done(work())  # arrives after the window is gone
    assert dialog._preview is None
    controller.job_service.submit_njrs.assert_not_called()


@pytest.mark.gui
def test_close_is_deferred_while_admission_is_in_flight(make_dialog):
    pending = []
    sync = BackgroundWorkRunner(
        spawn=lambda _, target: target(), dispatch=lambda callback: callback()
    )
    dialog, controller = make_dialog.build(runner=sync)
    margins(dialog)
    dialog.preview_button.invoke()
    dialog._runner = SimpleNamespace(start=lambda name, work, done: pending.append((work, done)))
    dialog.queue_button.invoke()
    dialog._close()
    assert dialog.winfo_exists() and "Admission is in progress" in dialog.status.get()
    work, done = pending.pop()
    done(work())
    assert controller.job_service.submit_njrs.call_count == 1


@pytest.mark.gui
@pytest.mark.parametrize(
    "setup,message",
    [
        (lambda d: margins(d, 0, 0, 0, 0), "at least one"),
        (lambda d: margins(d, 5, 0, 0, 0), "multiple of 8"),
        (lambda d: margins(d, -8, 0, 0, 0), "negative"),
        (lambda d: (margins(d), d.prompt.delete("1.0", "end"), d.update()), "Describe"),
    ],
)
def test_refusals_are_visible_and_nothing_is_queued(make_dialog, setup, message):
    dialog, controller = make_dialog.build()
    setup(dialog)
    dialog.preview_button.invoke()
    assert dialog._preview is None
    assert "Preview refused" in dialog.status.get() and message in dialog.status.get()
    assert dialog.queue_button.instate(["disabled"])
    controller.job_service.submit_njrs.assert_not_called()


@pytest.mark.gui
def test_unsupported_target_is_stated_and_refuses_preview(make_dialog):
    dialog, controller = make_dialog.build(model="unknown")
    assert "require Forge" in dialog.support.get()
    margins(dialog)
    dialog.preview_button.invoke()
    assert dialog._preview is None and "require Forge" in dialog.status.get()
    assert not inputs.default_snapshot_root().exists()


@pytest.mark.gui
def test_admission_failure_keeps_the_draft_and_requires_a_fresh_preview(make_dialog):
    dialog, controller = make_dialog.build()
    controller.job_service.submit_njrs.side_effect = ValueError("refused")
    margins(dialog)
    dialog.preview_button.invoke()
    dialog.queue_button.invoke()
    assert "Admission failed" in dialog.status.get()
    assert dialog._preview is not None and dialog.left.get() == 16
    dialog.queue_button.invoke()  # no automatic or repeated attempt
    assert controller.job_service.submit_njrs.call_count == 1


@pytest.mark.gui
def test_align_button_applies_the_documented_rule_visibly(make_dialog):
    dialog, _ = make_dialog.build()
    margins(dialog, 5, 0, 0, 0)
    assert "Cannot preview" in dialog.dimensions.get()
    dialog.align_button.invoke()
    assert (dialog.right.get(), dialog.bottom.get()) == (3, 0)
    assert "New size: 136 × 96" in dialog.dimensions.get()


@pytest.mark.gui
@pytest.mark.parametrize("size", ["760x560", "800x600"])
def test_primary_actions_stay_reachable_in_a_small_window(make_dialog, size):
    dialog, _ = make_dialog.build()
    dialog.geometry(size)
    margins(dialog)
    dialog.preview_button.invoke()
    dialog.update()
    dialog.update_idletasks()
    bottom = dialog.winfo_rooty() + dialog.winfo_height()
    right = dialog.winfo_rootx() + dialog.winfo_width()
    for button in (
        dialog.preview_button,
        dialog.queue_button,
        dialog.align_button,
        dialog.close_button,
    ):
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() <= bottom
        assert button.winfo_rootx() + button.winfo_width() <= right


@pytest.mark.gui
def test_default_worker_keeps_load_prepare_and_admission_off_tk(make_dialog, tk_root, monkeypatch):
    import src.gui.outpaint_dialog as module

    main_thread = threading.get_ident()
    workers, renders = [], []
    original_read, original_prepare = module.read_source, module.prepare_outpaint_edit

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
    monkeypatch.setattr(module, "prepare_outpaint_edit", prepare)
    controller = SimpleNamespace(
        _extract_reprocess_baseline_from_image=lambda _: {"model": "sdxl"},
        _build_reprocess_config=lambda _: {
            "model": "sdxl",
            "backend_options": {"image": {"backend_id": "forge_webui"}},
            "img2img": {"steps": 20, "sampler_name": "Euler", "scheduler": "Karras", "seed": 7},
        },
        job_service=SimpleNamespace(submit_njrs=Mock(side_effect=admit)),
    )
    dialog = module.OutpaintDialog(tk_root, source_path=make_dialog.path, controller=controller)
    dialog.status.trace_add("write", lambda *_: renders.append(threading.get_ident()))

    def complete():
        deadline = time.monotonic() + 5
        while dialog._busy and time.monotonic() < deadline:
            dialog.update()
            time.sleep(0.01)
        assert not dialog._busy

    try:
        complete()
        margins(dialog)
        dialog.preview_button.invoke()
        complete()
        assert dialog._preview is not None, dialog.status.get()
        dialog.queue_button.invoke()
        complete()
        assert "Queued frozen job" in dialog.status.get()
        assert len(workers) == 3 and all(value != main_thread for value in workers)
        assert renders and all(value == main_thread for value in renders)
    finally:
        dialog._closed = True
        dialog.destroy()


@pytest.mark.gui
def test_review_extend_canvas_action_opens_only_one_still_image(tk_root, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "src.gui.outpaint_dialog.OutpaintDialog", lambda parent, **kwargs: opened.append(kwargs)
    )
    path = tmp_path / "source.png"
    path.write_bytes(png_bytes(original_image()))
    review = SimpleNamespace(_get_selected_review_paths=lambda: [path], app_controller=object())
    ReviewTabFrame._open_outpaint_editor(review)
    assert opened[0]["source_path"] == path
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.messagebox.showwarning", lambda *a, **k: None
    )
    review._get_selected_review_paths = lambda: [path, path]
    ReviewTabFrame._open_outpaint_editor(review)
    review._get_selected_review_paths = lambda: [tmp_path / "clip.mp4"]
    ReviewTabFrame._open_outpaint_editor(review)
    review._get_selected_review_paths = lambda: [path]
    review.app_controller = None
    ReviewTabFrame._open_outpaint_editor(review)
    assert len(opened) == 1


@pytest.mark.gui
@pytest.mark.parametrize("value", [-128, -500, -8])
def test_large_negative_margins_are_explained_without_a_callback_exception(make_dialog, value):
    dialog, _ = make_dialog.build()
    errors = []
    dialog.report_callback_exception = lambda *exc: errors.append(exc)
    dialog.left.set(value)
    dialog.update()
    dialog.canvas.event_generate("<Configure>")
    dialog.update()
    assert errors == []
    assert "negative" in dialog.dimensions.get()


@pytest.mark.gui
def test_close_is_not_blocked_by_a_finished_admission_while_repreviewing(make_dialog):
    dialog, controller = make_dialog.build()
    margins(dialog)
    dialog.preview_button.invoke()
    dialog.queue_button.invoke()
    pending = []
    dialog._runner = SimpleNamespace(start=lambda name, work, done: pending.append((work, done)))
    dialog.preview_button.invoke()
    dialog._close()
    assert dialog._closed
    controller.job_service.submit_njrs.assert_called_once()
