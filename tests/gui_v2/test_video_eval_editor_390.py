"""Exercise the authoring controls and the existing queue boundary with local fixtures."""

from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.video_eval_editor_dialog import THREE_ENGINES, VideoEvalEditorDialog
from src.gui.views.video_eval_panel_v2 import VideoEvalPanel
from src.video.video_eval_suite import load_eval_suite


def _widgets(parent: Any) -> Iterator[Any]:
    for child in parent.winfo_children():
        yield child
        yield from _widgets(child)


def _button(parent: Any, title: str) -> ttk.Button:
    return next(
        widget
        for widget in _widgets(parent)
        if isinstance(widget, ttk.Button) and widget.cget("text") == title
    )


def _field(parent: Any, label: str) -> Any:
    widget = next(
        item
        for item in parent.winfo_children()
        if isinstance(item, ttk.Label) and item.cget("text") == label
    )
    return parent.grid_slaves(row=widget.grid_info()["row"], column=1)[0]


def _input(widget: Any, text: str) -> None:
    if isinstance(widget, ttk.Combobox):
        widget.set(text)
    else:
        widget.delete(0, "end")
        widget.insert(0, text)


def _runner() -> BackgroundWorkRunner:
    return BackgroundWorkRunner(spawn=lambda _name, work: work(), dispatch=lambda fn: fn())


class _Jobs:
    def __init__(self):
        self.calls = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [job.job_id for job in njrs]


def _local_images(tmp_path):
    images = []
    for index, color in enumerate(("red", "green", "blue")):
        path = tmp_path / f"image{index}.png"
        Image.new("RGB", (64, 96), color).save(path)
        images.append(path)
    return images


def _select_case(editor, index):
    editor.tabs.select(1)
    editor.update_idletasks()
    editor.lists["case"].selection_clear(0, "end")
    editor.lists["case"].selection_set(index)
    editor._select("case")  # Call the ListboxSelect handler even on a withdrawn test window.
    assert editor.indices["case"] == index


@pytest.mark.parametrize("accept", [False, True])
def test_template_controls_to_compiled_preview_and_one_confirmation(tk_root, tmp_path, accept):
    images = _local_images(tmp_path)
    picker = iter(images)
    jobs = _Jobs()
    confirmations = []
    output = tmp_path / "output"
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(output_dir=output, job_service=jobs)
    )
    panel = VideoEvalPanel(
        tk_root,
        get_controller=lambda: controller,
        output_dir=lambda: str(output),
        show_prompts=lambda: False,
        runner=_runner(),
        ask_open=lambda **_kwargs: str(next(picker)),
        confirm=lambda _title, text: confirmations.append(text) or accept,
    )
    template_bytes = THREE_ENGINES.read_bytes()
    panel.editor_button.invoke()
    editor = panel._editor
    assert editor is not None
    _button(editor, "Three-engine template").invoke()
    assert editor.lists["case"].size() == 3
    assert editor.count.get().startswith("3 cases × 3 arms = 9 jobs")
    _button(editor, "Validate").invoke()
    assert "Resolve these issues" in editor.status.get()
    editor.preview_button.invoke()
    assert not confirmations and not jobs.calls and not output.exists()
    for index in range(3):
        _select_case(editor, index)
        _button(editor.details["case"], "Bind Image…").invoke()

    cases_tab = editor.lists["case"].master.master
    _button(cases_tab, "Add").invoke()
    assert "= 12 jobs" in editor.count.get()
    _button(cases_tab, "Remove").invoke()
    arms_tab = editor.lists["arm"].master.master
    _button(arms_tab, "Duplicate").invoke()
    candidate = editor.draft.arms[-1]["arm_id"]
    assert "4 arms = 12 jobs" in editor.count.get()
    _input(_field(editor.details["arm"], "Frames (blank uses default)"), "49")
    _input(_field(editor.suite_form, "Baseline arm"), candidate)
    _input(_field(editor.suite_form, "Shared seed"), "12")
    editor.preview_button.invoke()

    selected = panel._selected_plan()
    assert selected is not None and selected.jobs == 12
    saved = load_eval_suite(selected.path)
    assert saved.baseline_arm_id == candidate and saved.seed == 12
    assert [case.image_path for case in saved.cases] == images
    assert saved.arms[-1].overrides["frame_count"] == 49
    assert len(confirmations) == 1
    assert f"walk_forward × {candidate}" in confirmations[0]
    assert "wan22_ti2v_5b_i2v_v1 1.3.0" in confirmations[0]
    assert "49 frames" in confirmations[0] and "Queue all 12 jobs" in confirmations[0]
    assert len(jobs.calls) == int(accept)
    if accept:
        assert len(jobs.calls[0]) == 12
    assert THREE_ENGINES.read_bytes() == template_bytes


def test_cancelled_load_ignores_stale_worker_result(tk_root, tmp_path):
    pending = []
    closed = []
    saved = []
    editor = VideoEvalEditorDialog(
        tk_root,
        plan_root=tmp_path,
        initial_path=THREE_ENGINES,
        runner=BackgroundWorkRunner(
            spawn=lambda _name, work: pending.append(work), dispatch=lambda fn: fn()
        ),
        on_saved=lambda *args: saved.append(args),
        on_close=lambda: closed.append(True),
    )
    assert len(pending) == 1
    editor.close_button.invoke()
    pending.pop()()
    assert closed == [True] and saved == []
    assert not (tmp_path / "video").exists()


def test_cap_and_ordered_segment_editing(tk_root, tmp_path):
    editor = VideoEvalEditorDialog(
        tk_root,
        plan_root=tmp_path,
        initial_path=THREE_ENGINES,
        runner=_runner(),
        on_saved=lambda *_args: pytest.fail("Unexpected save"),
        on_close=lambda: None,
    )
    form = editor.details["case"]
    _button(form, "Use Ordered Segments").invoke()
    original = editor.draft.cases[0]["segments"][0]["prompt"]
    _button(form, "Move Down").invoke()
    assert editor.draft.cases[0]["segments"][1]["prompt"] == original
    _button(form, "Add Segment").invoke()
    assert len(editor.draft.cases[0]["segments"]) == 3
    cases_tab = editor.lists["case"].master.master
    for _ in range(19):
        _button(cases_tab, "Add").invoke()
    assert editor.count.get().startswith("22 cases × 3 arms = 66 jobs")
    assert editor.save_button.instate(["disabled"]) and editor.preview_button.instate(["disabled"])
    _button(cases_tab, "Remove").invoke()
    assert editor.preview_button.instate(["!disabled"])
    editor.destroy()


def test_failed_save_leaves_editor_open_and_never_previews(tk_root, tmp_path, monkeypatch):
    picker = iter(_local_images(tmp_path))
    calls = []

    def fail(*_args):
        raise OSError("destination is read only")

    monkeypatch.setattr("src.gui.views.video_eval_editor_dialog.publish_validated_suite", fail)
    editor = VideoEvalEditorDialog(
        tk_root,
        plan_root=tmp_path / "plans",
        initial_path=THREE_ENGINES,
        runner=_runner(),
        on_saved=lambda *args: calls.append(args),
        on_close=lambda: None,
        ask_open=lambda **_kwargs: str(next(picker)),
    )
    for index in range(3):
        _select_case(editor, index)
        _button(editor.details["case"], "Bind Image…").invoke()
    editor.preview_button.invoke()
    assert editor.winfo_exists() and not calls
    assert "destination is read only" in editor.results.get("1.0", "end")
    assert not (tmp_path / "plans").exists()
    editor.destroy()


def test_saved_preview_keeps_published_path_when_settings_change(tk_root, tmp_path):
    output = tmp_path / "output"
    old_root = tmp_path / "first"
    configured = tmp_path / "second"
    saved_path = old_root / "video" / "same-name.suite.json"
    other_plan = configured / "video" / saved_path.name
    for suite in (saved_path, other_plan):
        suite.parent.mkdir(parents=True)
        suite.write_bytes(THREE_ENGINES.read_bytes())
    previewed = []
    controller = SimpleNamespace(
        preview_eval_run=lambda path: previewed.append(Path(path))
        or SimpleNamespace(
            summary=lambda: "Missing source",
            eligible=False,
            suite=SimpleNamespace(arms=()),
            jobs=(),
        )
    )
    panel = VideoEvalPanel(
        tk_root,
        get_controller=lambda: controller,
        output_dir=lambda: str(output),
        show_prompts=lambda: False,
        eval_plans_dir=lambda: str(configured),
        runner=_runner(),
        confirm=lambda *_args: pytest.fail("Refused preview asked to queue"),
    )
    panel._editor_saved(saved_path, preview=True)
    assert previewed == [saved_path]
    assert "Missing source" in panel.status_var.get()
    panel.destroy()
