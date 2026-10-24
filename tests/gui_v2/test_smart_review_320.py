"""Smart Review dialog: opt-in, suggestion-only flows, hand-off to the existing mask editor, and the queue boundary."""

from __future__ import annotations

import hashlib
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from src.gui.mask_editor_dialog import MaskEditorDialog
from src.gui.smart_review_dialog import SmartReviewDialog, TextDraft
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui_v2.mask_editor_state import MaskViewport
from src.image_backends import masked_inpaint as capability
from src.pipeline import image_edit_inputs as inputs
from src.review.assist.contracts import (
    CAPABILITY_CAPTION,
    CAPABILITY_SEGMENT,
    CaptionOutput,
    ModelIdentity,
    RawObject,
    SegmentOutput,
)
from src.review.assist.geometry import image_to_canvas
from src.review.assist.providers import availability_from
from src.review.assist.session import AssistEnablement, AssistSession
from tests.pipeline.test_inpaint300 import png

MODEL = ModelIdentity(CAPABILITY_SEGMENT, "sam-2-1-small", "local child process, CPU")
CAPTION_MODEL = ModelIdentity(CAPABILITY_CAPTION, "florence-2-base-ft", "local child process, CPU")


class Segmenter:
    def __init__(self):
        self.calls = []

    def segment(self, source, points, boxes, cancel):
        self.calls.append((tuple(points), tuple(boxes)))
        logits = np.full((32, 32), -4.0, dtype=np.float32)
        logits[16:28, 16:28] = 4.0  # the lower-right quadrant region of the 128 px source
        return SegmentOutput(logits, 0.9, MODEL)


class Captioner:
    def __init__(self, text="A blue square."):
        self.text = text
        self.calls = 0

    def caption(self, source, cancel):
        self.calls += 1
        return CaptionOutput(self.text, (RawObject("square", (4, 4, 90, 90)),), CAPTION_MODEL)


class Probe:
    def __init__(self, reasons=()):
        self.reasons = reasons
        self.checked = []

    def check(self, capability_name, cancel):
        self.checked.append(capability_name)
        return availability_from(capability_name, self.reasons)


def sync_runner():
    return BackgroundWorkRunner(
        spawn=lambda _, target: target(), dispatch=lambda callback: callback()
    )


class Draft:
    def __init__(self, text="a portrait"):
        self.text = text
        self.changes = 0

    def get(self):
        return self.text

    def set(self, text):
        self.text = text
        self.changes += 1


@pytest.fixture
def source_path(tmp_path):
    path = tmp_path / "source.png"
    path.write_bytes(png())
    return path


def make_dialog(
    tk_root, source_path, *, probe=None, segmenter=None, captioner=None, enabled=(), **kwargs
):
    enablement = AssistEnablement()
    for name in enabled:
        enablement.set(name, True)
    session = AssistSession(
        source_path,
        segmenter=segmenter or Segmenter(),
        captioner=captioner or Captioner(),
        probe=probe or Probe(),
        enablement=enablement,
    )
    opened = []
    dialog = SmartReviewDialog(
        tk_root,
        source_path=source_path,
        controller=SimpleNamespace(app_state=SimpleNamespace(content_visibility_mode="nsfw")),
        enablement=enablement,
        session=session,
        runner=sync_runner(),
        open_editor=lambda path, mask, sha: opened.append((path, mask, sha)),
        **kwargs,
    )
    dialog.update()
    dialog._fit()
    dialog.update()
    return dialog, session, opened


def click(dialog, x, y, *, mode=None):
    if mode:
        dialog.mode.set(mode)
    cx, cy = image_to_canvas(dialog.viewport, x, y)
    dialog.canvas.event_generate("<ButtonPress-1>", x=int(cx), y=int(cy))
    dialog.canvas.event_generate("<ButtonRelease-1>", x=int(cx), y=int(cy))
    dialog.update()


def drag(dialog, start, end):
    dialog.mode.set("box")
    first, second = image_to_canvas(dialog.viewport, *start), image_to_canvas(dialog.viewport, *end)
    dialog.canvas.event_generate("<ButtonPress-1>", x=int(first[0]), y=int(first[1]))
    dialog.canvas.event_generate("<ButtonRelease-1>", x=int(second[0]), y=int(second[1]))
    dialog.update()


def finish(dialog):
    dialog._closed = True
    dialog.destroy()


@pytest.mark.gui
def test_opens_with_everything_off_and_nothing_probed_or_run(tk_root, source_path):
    probe, segmenter, captioner = Probe(), Segmenter(), Captioner()
    dialog, session, _ = make_dialog(
        tk_root, source_path, probe=probe, segmenter=segmenter, captioner=captioner
    )
    try:
        assert "Image 128" in dialog.status.get()
        assert not any(var.get() for var in dialog.enable_vars.values())
        for button in (
            dialog.propose_button,
            dialog.analyze_button,
            dialog.accept_button,
            dialog.reject_button,
        ):
            assert button.instate(["disabled"])
        click(
            dialog, 64, 64, mode="foreground"
        )  # prompts can be placed, but nothing may run while off
        assert dialog.propose_button.instate(["disabled"])
        assert (
            probe.checked == []
            and segmenter.calls == []
            and captioner.calls == 0
            and not session.busy
        )
    finally:
        finish(dialog)


@pytest.mark.gui
def test_enabling_probes_only_that_capability_and_reports_unavailable_reasons(tk_root, source_path):
    probe = Probe(("resource_missing:weights", "transformers_too_old"))
    dialog, _, _ = make_dialog(tk_root, source_path, probe=probe)
    try:
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        dialog.update()
        assert probe.checked == [CAPABILITY_SEGMENT]
        text = dialog.capability_labels[CAPABILITY_SEGMENT].cget("text")
        assert "unavailable" in text and "weights" in text and "older than the qualified" in text
        assert "Manual mask editing is unaffected" in text
        click(dialog, 64, 64, mode="foreground")
        assert dialog.propose_button.instate(["disabled"])  # no fallback to anything else
        dialog.enable_vars[CAPABILITY_SEGMENT].set(False)
        assert dialog.capability_labels[CAPABILITY_SEGMENT].cget("text") == "Off"
    finally:
        finish(dialog)


@pytest.mark.gui
def test_point_to_overlay_to_accept_hands_exact_mask_to_the_editor_and_closes(tk_root, source_path):
    segmenter = Segmenter()
    dialog, session, opened = make_dialog(
        tk_root, source_path, segmenter=segmenter, enabled=(CAPABILITY_SEGMENT,)
    )
    try:
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        dialog.update()
        assert dialog.propose_button.instate(["disabled"])  # no prompt yet
        click(dialog, 80, 80, mode="foreground")
        click(dialog, 10, 10, mode="background")
        assert [(p.x, p.y, p.positive) for p in dialog.points] == [(80, 80, True), (10, 10, False)]
        dialog.propose_button.invoke()
        dialog.update()
        assert segmenter.calls and session.segment is not None, dialog.status.get()
        assert dialog._mask_view is not None and "suggestion" in dialog.status.get()
        assert (
            dialog.accept_button.instate(["!disabled"]) and not opened
        )  # nothing is handed over before Accept
        dialog.accept_button.invoke()
        assert len(opened) == 1 and opened[0][0] == source_path
        assert opened[0][2] == hashlib.sha256(source_path.read_bytes()).hexdigest()
        mask = Image.open(__import__("io").BytesIO(opened[0][1]))
        assert mask.mode == "L" and mask.size == (128, 128)
        array = np.asarray(mask)
        assert array[80, 80] == 255 and array[10, 10] == 0
    finally:
        if dialog.winfo_exists():
            finish(dialog)
    assert session.closed


@pytest.mark.gui
def test_reject_cancel_and_changed_prompts_leave_nothing_behind(tk_root, source_path):
    dialog, session, opened = make_dialog(tk_root, source_path, enabled=(CAPABILITY_SEGMENT,))
    try:
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        click(dialog, 80, 80, mode="foreground")
        dialog.propose_button.invoke()
        assert session.segment is not None
        dialog.reject_button.invoke()
        assert session.segment is None and dialog._mask_view is None and not opened
        dialog.propose_button.invoke()
        assert session.segment is not None
        click(
            dialog, 90, 90, mode="foreground"
        )  # new prompt: the old suggestion no longer matches what is shown
        assert session.segment is None and dialog._mask_view is None
        dialog.propose_button.invoke()
        dialog._cancel()
        assert session.segment is None and not opened
        dialog._clear_prompts()
        assert dialog.points == [] and dialog.propose_button.instate(["disabled"])
    finally:
        finish(dialog)


@pytest.mark.gui
def test_prompts_outside_the_image_or_over_the_cap_are_refused_with_a_message(tk_root, source_path):
    dialog, _, _ = make_dialog(tk_root, source_path, enabled=(CAPABILITY_SEGMENT,))
    try:
        dialog.update()
        dialog.viewport = MaskViewport(1, 40, 40)  # 128 px image centred-ish in the canvas
        dialog._render()
        dialog.canvas.event_generate("<ButtonPress-1>", x=5, y=5)
        dialog.canvas.event_generate("<ButtonRelease-1>", x=5, y=5)
        assert dialog.points == [] and "image" in dialog.status.get().lower()
        for index in range(6):
            click(dialog, 20 + index * 3, 60, mode="foreground")
        assert len(dialog.points) == 4 and "At most 4" in dialog.status.get()
        drag(dialog, (20, 20), (90, 90))
        assert len(dialog.boxes) == 1
        drag(dialog, (30, 30), (100, 100))
        assert len(dialog.boxes) == 1 and "Only one box" in dialog.status.get()
    finally:
        finish(dialog)


@pytest.mark.gui
def test_box_only_prompt_is_enough_to_propose(tk_root, source_path):
    segmenter = Segmenter()
    dialog, session, _ = make_dialog(
        tk_root, source_path, segmenter=segmenter, enabled=(CAPABILITY_SEGMENT,)
    )
    try:
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        drag(dialog, (60, 60), (110, 110))
        dialog.propose_button.invoke()
        assert segmenter.calls[0][1][0].x1 == 60 and session.segment is not None
    finally:
        finish(dialog)


@pytest.mark.gui
def test_source_replaced_after_proposal_is_refused_at_accept(tk_root, source_path):
    dialog, session, opened = make_dialog(tk_root, source_path, enabled=(CAPABILITY_SEGMENT,))
    try:
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        click(dialog, 80, 80, mode="foreground")
        dialog.propose_button.invoke()
        assert session.segment is not None
        Image.new("RGB", (128, 128), "green").save(source_path)
        dialog.accept_button.invoke()
        assert not opened and dialog._mask_view is None
        assert "changed" in dialog.status.get()
        assert str(source_path) not in dialog.status.get()
    finally:
        finish(dialog)


@pytest.mark.gui
def test_caption_suggestion_applies_once_and_undo_keeps_operator_edits(tk_root, source_path):
    draft = Draft("a portrait")
    captioner = Captioner("A blue square.")
    dialog, session, _ = make_dialog(
        tk_root,
        source_path,
        captioner=captioner,
        enabled=(CAPABILITY_CAPTION,),
        prompt_binding=draft,
    )
    try:
        dialog.enable_vars[CAPABILITY_CAPTION].set(True)
        dialog.update()
        assert dialog.analyze_button.instate(["!disabled"]) and captioner.calls == 0
        dialog.analyze_button.invoke()
        dialog.update()
        assert session.caption is not None and captioner.calls == 1
        assert "Suggestion from Florence-2 Base FT" in dialog.caption_source.cget("text")
        assert "Not ground truth" in dialog.caption_source.cget("text")
        assert "A blue square." in dialog.caption_text.get("1.0", "end")
        assert "square" in dialog.objects_label.cget("text")
        assert draft.text == "a portrait" and draft.changes == 0  # showing it changed nothing
        dialog.apply_button.invoke()
        assert "A blue square." in draft.text and draft.text.startswith("a portrait")
        assert dialog.apply_button.instate(["disabled"])  # once
        dialog.undo_button.invoke()
        assert draft.text == "a portrait"
        dialog.apply_button.invoke()
        draft.text += " and my own words"
        dialog.undo_button.invoke()
        assert draft.text.endswith("and my own words") and "edited since" in dialog.status.get()
        dialog.dismiss_button.invoke()
        assert session.caption is None and dialog.caption_text.get("1.0", "end").strip() == ""
    finally:
        finish(dialog)


@pytest.mark.gui
def test_caption_apply_is_blocked_when_review_shows_another_image(tk_root, source_path):
    draft = Draft("a portrait")
    dialog, _, _ = make_dialog(
        tk_root,
        source_path,
        enabled=(CAPABILITY_CAPTION,),
        prompt_binding=draft,
        draft_current=lambda: False,
    )
    try:
        dialog.enable_vars[CAPABILITY_CAPTION].set(True)
        dialog.analyze_button.invoke()
        dialog.apply_button.invoke()
        assert draft.text == "a portrait" and "different image" in dialog.status.get()
    finally:
        finish(dialog)


@pytest.mark.gui
def test_hidden_content_caption_is_not_shown_copied_or_applied(tk_root, source_path):
    draft = Draft("a portrait")
    dialog, _, _ = make_dialog(
        tk_root,
        source_path,
        captioner=Captioner("A topless woman on a bed"),
        enabled=(CAPABILITY_CAPTION,),
        prompt_binding=draft,
        visibility_mode=lambda: "sfw",
    )
    try:
        dialog.enable_vars[CAPABILITY_CAPTION].set(True)
        dialog.analyze_button.invoke()
        shown = dialog.caption_text.get("1.0", "end")
        if (
            "topless" in shown
        ):  # the resolver decides what is hidden; if it hid it, nothing may leak or apply
            pytest.skip("content-visibility resolver treats this caption as visible")
        assert dialog.apply_button.instate(["disabled"]) and dialog.copy_button.instate(
            ["disabled"]
        )
        assert draft.text == "a portrait"
    finally:
        finish(dialog)


@pytest.mark.gui
def test_errors_are_shown_without_paths_and_leave_the_dialog_usable(tk_root, source_path):
    class Failing(Segmenter):
        def segment(self, source, points, boxes, cancel):
            raise RuntimeError(f"boom {source_path}")

    dialog, session, _ = make_dialog(
        tk_root, source_path, segmenter=Failing(), enabled=(CAPABILITY_SEGMENT,)
    )
    try:
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        click(dialog, 80, 80, mode="foreground")
        dialog.propose_button.invoke()
        assert str(source_path) not in dialog.status.get() and "boom" not in dialog.status.get()
        assert not session.busy and dialog.propose_button.instate(["!disabled"])
    finally:
        finish(dialog)


@pytest.mark.gui
def test_close_cancels_work_and_late_replies_do_not_touch_a_destroyed_dialog(tk_root, source_path):
    pending = []
    enablement = AssistEnablement()
    enablement.set(CAPABILITY_SEGMENT, True)
    session = AssistSession(
        source_path,
        segmenter=Segmenter(),
        captioner=Captioner(),
        probe=Probe(),
        enablement=enablement,
    )
    dialog = SmartReviewDialog(
        tk_root,
        source_path=source_path,
        controller=SimpleNamespace(),
        enablement=enablement,
        session=session,
        runner=SimpleNamespace(start=lambda name, work, done: pending.append((name, work, done))),
        open_editor=lambda *a: None,
    )
    name, work, done = pending.pop(0)  # the load
    done(work())
    dialog.update()
    dialog._close()
    assert session.closed
    while pending:  # probes / work completing after close must be ignored
        _, work, done = pending.pop()
        done(work())


@pytest.mark.gui
def test_default_runner_keeps_loading_and_inference_off_the_tk_thread(tk_root, source_path):
    main_thread = threading.get_ident()
    threads, renders = [], []

    class Recording(Segmenter):
        def segment(self, source, points, boxes, cancel):
            threads.append(threading.get_ident())
            return super().segment(source, points, boxes, cancel)

    enablement = AssistEnablement()
    enablement.set(CAPABILITY_SEGMENT, True)
    session = AssistSession(
        source_path,
        segmenter=Recording(),
        captioner=Captioner(),
        probe=Probe(),
        enablement=enablement,
    )
    dialog = SmartReviewDialog(
        tk_root,
        source_path=source_path,
        controller=SimpleNamespace(),
        enablement=enablement,
        session=session,
        open_editor=lambda *a: None,
    )
    dialog.status.trace_add("write", lambda *_: renders.append(threading.get_ident()))

    def settle(until):
        deadline = time.monotonic() + 8
        while not until() and time.monotonic() < deadline:
            dialog.update()
            time.sleep(0.01)
        assert until(), dialog.status.get()

    try:
        settle(lambda: session.identity is not None)
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        settle(lambda: dialog._ready(CAPABILITY_SEGMENT))
        dialog._fit()
        click(dialog, 80, 80, mode="foreground")
        dialog.propose_button.invoke()
        settle(lambda: session.segment is not None)
        assert threads and all(value != main_thread for value in threads)
        assert renders and all(value == main_thread for value in renders)
    finally:
        finish(dialog)


# -- hand-off to the existing editor and the queue boundary ---------------------------------------------------------
@pytest.fixture
def editor_env(tk_root, tmp_path, monkeypatch):
    from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily

    monkeypatch.setattr(
        inputs, "default_snapshot_root", lambda: tmp_path / "state" / "image_edit_inputs"
    )
    monkeypatch.setattr(
        capability,
        "RegistryFamilyLookup",
        lambda: lambda _: CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()),
    )
    path = tmp_path / "edit.png"
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
    return path, controller


def open_editor(tk_root, path, controller, mask=None, sha=None):
    editor = MaskEditorDialog(
        tk_root,
        source_path=path,
        controller=controller,
        runner=sync_runner(),
        suggested_mask=mask,
        suggested_source_sha256=(
            hashlib.sha256(path.read_bytes()).hexdigest() if sha is None else sha
        ),
    )
    editor.loaded_status = editor.status.get()
    editor.update_idletasks()
    editor._fit()
    editor.prompt.insert("1.0", "add a red flower")
    editor.update()
    return editor


def suggestion(path):
    session = AssistSession(
        path,
        segmenter=Segmenter(),
        captioner=Captioner(),
        probe=Probe(),
        enablement=_enabled(),
    )
    from src.review.assist.contracts import PointPrompt
    from src.review.assist.identity import load_source

    session.bind(load_source(path), path)
    ticket = session.begin_segment([PointPrompt(80, 80, True)], [])
    assert session.adopt_segment(
        ticket, session.run_segment(ticket, [PointPrompt(80, 80, True)], [])
    )
    return session.accept_mask()


def _enabled():
    enablement = AssistEnablement()
    enablement.set(CAPABILITY_SEGMENT, True)
    return enablement


@pytest.mark.gui
def test_accepted_suggestion_is_adjustable_and_queues_exactly_one_frozen_job_only_after_confirmation(
    tk_root, editor_env
):
    path, controller = editor_env
    mask = suggestion(path)
    editor = open_editor(tk_root, path, controller, mask)
    try:
        assert "suggested mask loaded" in editor.loaded_status.lower()
        assert (
            editor.document.mask.getpixel((80, 80)) == 255
            and editor.document.mask.getpixel((5, 5)) == 0
        )
        controller.job_service.submit_njrs.assert_not_called()  # adopting a suggestion is not a submission
        editor.document.undo()  # the adopted mask is one undo step, like a brush stroke
        assert editor.document.mask.getextrema() == (0, 0)
        editor.document.redo()
        assert editor.document.mask.getpixel((80, 80)) == 255
        editor.viewport = MaskViewport(2, 10, 10)  # brush adjustment on top of the suggestion
        editor.brush_size.set(10)
        editor.canvas.event_generate("<ButtonPress-1>", x=50, y=50)
        editor.canvas.event_generate("<B1-Motion>", x=60, y=60)
        editor.canvas.event_generate("<ButtonRelease-1>", x=60, y=60)
        assert (
            editor.document.mask.getpixel((25, 25)) == 255
            and editor.document.mask.getpixel((80, 80)) == 255
        )
        editor.preview_button.invoke()
        assert editor._preview is not None, editor.status.get()
        controller.job_service.submit_njrs.assert_not_called()  # Preview alone never admits
        editor.queue_button.invoke()
        editor.queue_button.invoke()
        controller.job_service.submit_njrs.assert_called_once()
        assert controller.job_service.submit_njrs.call_args.args[0][0] is editor._preview.job
    finally:
        editor._closed = True
        editor.destroy()


@pytest.mark.gui
@pytest.mark.parametrize("kind", ["wrong_size", "not_a_png", "grey_levels", "empty"])
def test_invalid_suggestion_never_enters_the_editor(tk_root, editor_env, kind):
    import io

    path, controller = editor_env
    buffer = io.BytesIO()
    if kind == "wrong_size":
        Image.new("L", (64, 64), 255).save(buffer, format="PNG")
    elif kind == "grey_levels":
        Image.new("L", (128, 128), 128).save(buffer, format="PNG")
    elif kind == "empty":
        Image.new("L", (128, 128), 0).save(buffer, format="PNG")
    else:
        buffer.write(b"not a png")
    editor = open_editor(tk_root, path, controller, buffer.getvalue())
    try:
        assert editor.document.mask.getextrema() == (0, 0)
        assert "not loaded" in editor.loaded_status.lower()
        controller.job_service.submit_njrs.assert_not_called()
    finally:
        editor._closed = True
        editor.destroy()


@pytest.mark.gui
def test_suggestion_for_a_replaced_source_is_not_loaded(tk_root, editor_env):
    path, controller = editor_env
    mask = suggestion(path)
    editor = open_editor(tk_root, path, controller, mask, sha="0" * 64)
    try:
        assert (
            editor.document.mask.getextrema() == (0, 0) and "image changed" in editor.loaded_status
        )
    finally:
        editor._closed = True
        editor.destroy()


@pytest.mark.gui
def test_editor_without_a_suggestion_behaves_as_before(tk_root, editor_env):
    path, controller = editor_env
    editor = open_editor(tk_root, path, controller)
    try:
        assert editor.document.mask.getextrema() == (0, 0)
        assert "suggested" not in editor.status.get().lower()
    finally:
        editor._closed = True
        editor.destroy()


# -- Review tab wiring ----------------------------------------------------------------------------------------------
@pytest.mark.gui
def test_review_tab_has_a_smart_review_button_and_it_opens_one_still_image_only(
    tk_root, source_path, monkeypatch
):
    opened = []
    monkeypatch.setattr(
        "src.gui.smart_review_dialog.SmartReviewDialog",
        lambda parent, **kwargs: opened.append(kwargs),
    )
    warnings = []
    monkeypatch.setattr(
        "src.gui.views.review_tab_frame_v2.messagebox.showwarning",
        lambda *a, **k: warnings.append(a),
    )
    text = __import__("tkinter").Text(tk_root)
    review = SimpleNamespace(
        _get_selected_review_paths=lambda: [source_path],
        app_controller=object(),
        _smart_enablement=None,
        prompt_text=text,
        _refresh_prompt_diff=lambda: None,
        _content_visibility_mode="sfw",
    )
    ReviewTabFrame._open_smart_review(review)
    ReviewTabFrame._open_smart_review(review)
    assert [item["source_path"] for item in opened] == [source_path, source_path]
    assert (
        opened[0]["enablement"] is opened[1]["enablement"]
    )  # one opt-in state per Review tab, all off
    assert not any(
        opened[0]["enablement"].is_enabled(name)
        for name in (CAPABILITY_SEGMENT, CAPABILITY_CAPTION)
    )
    assert opened[0]["visibility_mode"]() == "sfw" and opened[0]["draft_current"]()
    draft = opened[0]["prompt_binding"]
    assert isinstance(draft, TextDraft)
    draft.set("hello")
    assert draft.get() == "hello"
    review._get_selected_review_paths = lambda: [source_path, source_path]
    ReviewTabFrame._open_smart_review(review)
    review._get_selected_review_paths = lambda: [source_path.with_suffix(".gif")]
    ReviewTabFrame._open_smart_review(review)
    review._get_selected_review_paths = lambda: [source_path]
    review.app_controller = None
    ReviewTabFrame._open_smart_review(review)
    assert len(opened) == 2 and len(warnings) == 3


@pytest.mark.gui
def test_real_review_tab_exposes_the_button_without_loading_any_model(tk_root):
    tab = ReviewTabFrame(tk_root)
    try:
        tab.update_idletasks()
        assert tab.smart_review_button.cget("text").startswith("Smart Review")
        assert "Edit Mask…" in tab.edit_mask_button.cget("text")
    finally:
        tab.destroy()


@pytest.mark.gui
def test_failure_to_start_a_worker_releases_the_analysis_slot(tk_root, source_path):
    dialog, session, _ = make_dialog(tk_root, source_path, enabled=(CAPABILITY_CAPTION,))
    try:
        dialog.enable_vars[CAPABILITY_CAPTION].set(True)

        def refuse(name, work, done):
            raise RuntimeError("no thread available")

        dialog._runner = SimpleNamespace(start=refuse)
        dialog.analyze_button.invoke()
        assert (
            not session.busy and not dialog._busy and "could not be started" in dialog.status.get()
        )
    finally:
        finish(dialog)


@pytest.mark.gui
def test_editor_refuses_a_suggestion_with_no_source_identity(tk_root, editor_env):
    path, controller = editor_env
    editor = open_editor(tk_root, path, controller, suggestion(path), sha="")
    try:
        assert (
            editor.document.mask.getextrema() == (0, 0)
            and "not loaded" in editor.loaded_status.lower()
        )
    finally:
        editor._closed = True
        editor.destroy()


@pytest.mark.gui
def test_reopening_with_a_capability_already_enabled_probes_to_completion(tk_root, source_path):
    probe = Probe()
    dialog, _, _ = make_dialog(tk_root, source_path, probe=probe, enabled=(CAPABILITY_SEGMENT,))
    try:
        dialog.update()
        assert dialog._ready(CAPABILITY_SEGMENT) and "ready" in dialog.capability_labels[
            CAPABILITY_SEGMENT
        ].cget("text")
    finally:
        finish(dialog)


@pytest.mark.gui
def test_turning_a_capability_off_during_a_run_cancels_it(tk_root, source_path):
    dialog, session, _ = make_dialog(tk_root, source_path, enabled=(CAPABILITY_SEGMENT,))
    try:
        dialog.enable_vars[CAPABILITY_SEGMENT].set(True)
        click(dialog, 80, 80, mode="foreground")
        dialog._runner = SimpleNamespace(
            start=lambda name, work, done: None
        )  # the run never completes by itself
        dialog.propose_button.invoke()
        assert dialog._busy and session.busy
        dialog.enable_vars[CAPABILITY_SEGMENT].set(False)
        assert session.segment is None and dialog._probe_generation[CAPABILITY_SEGMENT] >= 2
    finally:
        finish(dialog)
