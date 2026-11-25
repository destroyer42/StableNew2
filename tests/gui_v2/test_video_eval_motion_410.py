"""PR-VID-MOTION-410: the eval editor's driving-motion section and the Motion Review window (Tk, injected ports)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.view_contracts import video_eval_motion_contract as contract
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.video_eval_editor_dialog import VideoEvalEditorDialog
from src.gui.views.video_eval_motion_review_window import VideoEvalMotionReviewWindow
from src.utils.os_shell import ShellResult
from src.video.review_preview import STATUS_OK, PreviewClip, PreviewResult
from src.video.video_eval_authoring import EvalWorkflowCatalog
from src.video.video_eval_suite import SUITE_SCHEMA_V2, load_eval_suite
from tests.video.motion_410_support import drive_arm, make_image, make_video, sha
from tests.video.test_pr_vid_motion_410_evidence import MotionRun


def _widgets(parent: Any) -> Iterator[Any]:
    for child in parent.winfo_children():
        yield child
        yield from _widgets(child)


def _button(parent: Any, title: str) -> ttk.Button:
    return next(
        w for w in _widgets(parent) if isinstance(w, ttk.Button) and w.cget("text") == title
    )


def _labels(parent: Any) -> list[str]:
    return [str(w.cget("text")) for w in _widgets(parent) if isinstance(w, ttk.Label)]


def _runner() -> BackgroundWorkRunner:
    return BackgroundWorkRunner(spawn=lambda _name, work: work(), dispatch=lambda fn: fn())


def _select(editor, kind: str, index: int) -> None:
    editor.tabs.select(1 if kind == "case" else 2)
    editor.update_idletasks()
    editor.lists[kind].selection_clear(0, "end")
    editor.lists[kind].selection_set(index)
    editor._select(kind)


# ------------------------------------------------------------------ contract helpers (no Tk)


def test_merge_bound_replaces_the_driver_but_only_fills_blank_suggestions() -> None:
    motion = {"action": "my own wording", "annotations": {"framing": "full body"}}
    bound = {
        "driving": {"path": "x.mp4", "sha256": "a" * 64},
        "annotations": {"framing": "head", "viewpoint": "front"},
        "direction": "left to right",
        "action": "library label",
    }
    contract.merge_bound(motion, bound)
    assert motion["driving"] == bound["driving"]
    assert motion["action"] == "my own wording"  # never overwritten
    assert motion["annotations"] == {"framing": "full body", "viewpoint": "front"}
    assert motion["direction"] == "left to right"


def test_provenance_lines_never_claim_a_library_origin_for_a_local_video() -> None:
    local = contract.provenance_line({"driving": {"path": "a.mp4"}})
    assert "not verified" in local and "Motion Library" not in local.split(" ")[0]
    library = contract.provenance_line(
        {
            "driving": {
                "path": "a.mp4",
                "library_asset": {
                    "asset_id": "ma_1",
                    "derived_from": {"original_sha256": "b" * 64, "start_frame": 3, "end_frame": 9},
                },
            }
        }
    )
    assert "Motion Library asset ma_1" in library and "frames 3-9" in library
    assert contract.provenance_line({}) == "No driving reference bound yet."


def test_library_choices_are_bounded_filtered_and_unconfigured_is_explained() -> None:
    assets = [
        SimpleNamespace(
            asset_id=f"ma_{i}",
            display_name=f"clip {i}",
            tags=("wave",) if i % 2 else (),
            imported_at=f"2026-01-{i + 1:02d}",
            motion_label="",
            harvest=object() if i == 0 else None,
        )
        for i in range(5)
    ]
    store = SimpleNamespace(assets=lambda: assets)
    assert [c.asset_id for c in contract.library_choices(store)] == [
        "ma_4",
        "ma_3",
        "ma_2",
        "ma_1",
        "ma_0",
    ]
    assert [c.asset_id for c in contract.library_choices(store, "wave")] == ["ma_3", "ma_1"]
    assert "(harvested)" in contract.library_choices(store, "ma_0")[0].label
    none, message = contract.open_library_store(root=lambda: "")
    assert none is None and "No Motion Library is configured" in message
    broken, why = contract.open_library_store(
        root=lambda: "x", factory=lambda _root: (_ for _ in ()).throw(OSError("denied"))
    )
    assert broken is None and "denied" in why


# ------------------------------------------------------------------ the editor


def _editor(tk_root, tmp_path, ask):
    saved: list[Path] = []
    editor = VideoEvalEditorDialog(
        tk_root,
        plan_root=tmp_path / "plans",
        initial_path=None,
        runner=_runner(),
        on_saved=lambda path, preview: saved.append(path),
        on_close=lambda: None,
        catalog=EvalWorkflowCatalog(),
        ask_open=ask,
        confirm_discard=lambda *_a, **_k: True,
    )
    editor.saved = saved  # type: ignore[attr-defined]
    return editor


def test_the_editor_binds_a_driver_and_a_source_validates_and_saves_a_v2_suite(
    tk_root, tmp_path
) -> None:
    driver = make_video(tmp_path / "media" / "wave.mp4", b"wave")
    image = make_image(tmp_path / "media" / "s0.png")
    answers = iter([str(image), str(driver)])
    editor = _editor(tk_root, tmp_path, lambda **_k: next(answers))

    _select(editor, "case", 0)
    _button(editor.details["case"], "Bind Image…").invoke()
    _button(editor.details["case"], "Add Driving Motion").invoke()
    assert "driving motion" in editor.lists["case"].get(0)
    _button(editor.details["case"], "Bind Local Video…").invoke()
    motion = editor.draft.cases[0]["motion"]
    assert motion["driving"]["sha256"] == sha(driver)
    assert any("not verified" in text for text in _labels(editor.details["case"]))
    assert "Appearance and scene prompt" in _labels(editor.details["case"])
    assert not any(
        b.cget("text") == "Use Ordered Segments"
        for b in _widgets(editor.details["case"])
        if isinstance(b, ttk.Button)
    )

    editor.draft.cases[0].update(prompt="a woman in a red coat")
    motion.update(
        action="turns her head",
        motion_prompt="turns head right",
        category="head_turn",
        expected_outcome="The head rotates about 60 degrees to the right and holds.",
    )
    editor.draft.arms[0].update(drive_arm("arm_1", pose_strength=1.0))
    editor.draft.arms[0]["arm_id"] = "arm_1"
    editor.draft.data.update(suite_id="motion-ui", baseline_arm="arm_1")
    editor._render()
    editor.save_button.invoke()

    assert editor.saved and editor.saved[0].name.endswith(".suite.json")
    suite = load_eval_suite(editor.saved[0])
    assert suite.schema == SUITE_SCHEMA_V2 and suite.cases[0].motion.driving_sha256 == sha(driver)
    assert suite.cases[0].motion.category == "head_turn"


def test_the_editor_duplicates_a_motion_case_for_another_source_without_adding_an_arm(
    tk_root, tmp_path
) -> None:
    other = make_image(tmp_path / "media" / "other.png", color=(5, 200, 5))
    editor = _editor(tk_root, tmp_path, lambda **_k: str(other))
    editor.draft.cases[0]["motion"] = {
        "driving": {
            "path": str(make_video(tmp_path / "m" / "a.mp4")),
            "sha256": sha(tmp_path / "m" / "a.mp4"),
        },
        "category": "head_turn",
    }
    editor._render()
    arms_before = len(editor.draft.arms)
    _select(editor, "case", 0)
    _button(editor.details["case"], "Duplicate Case for Another Source…").invoke()

    assert len(editor.draft.cases) == 2 and len(editor.draft.arms) == arms_before
    copy = editor.draft.cases[1]
    assert (
        copy["image"] == str(other.resolve())
        and copy["motion"]["driving"] == editor.draft.cases[0]["motion"]["driving"]
    )
    assert "2 cases" in editor.count.get() and editor.indices["case"] == 1


def test_a_motion_suite_hides_the_case_owned_arm_fields_and_explains_why(tk_root, tmp_path) -> None:
    editor = _editor(tk_root, tmp_path, lambda **_k: "")
    editor.draft.cases[0]["motion"] = {}
    editor.draft.arms[0].update(drive_arm("arm_1", pose_strength=1.0))
    editor.draft.arms[0]["arm_id"] = "arm_1"
    editor._render()
    _select(editor, "arm", 0)
    labels = _labels(editor.details["arm"])
    assert "Driving clip" not in labels and "Motion Prompt" not in labels
    assert (
        "Pose Strength" in labels and "Reference Image Strength" in labels
    )  # declared controls stay editable
    assert any("bind their own driving-motion references" in text for text in labels)


# ------------------------------------------------------------------ the review window


def _clip(path: str, frames: int, fps: float) -> PreviewResult:
    raw = bytes((i * 7) % 256 for i in range(12 * frames))
    clip = PreviewClip(
        path=path,
        width=2,
        height=2,
        source_width=64,
        source_height=64,
        fps=fps,
        frame_count=frames,
        reported_frame_count=None,
        duration_seconds=None,
        raw=raw,
    )
    return PreviewResult(path=path, status=STATUS_OK, clip=clip)


@pytest.fixture
def built(tmp_path):
    run = MotionRun(tmp_path)
    run.build()
    return run


def _window(tk_root, built, **kwargs):
    opened: list[str] = []
    window = VideoEvalMotionReviewWindow(
        tk_root,
        run_dir=built.run_dir,
        runner=_runner(),
        preview_fn=lambda path, cancel=None: _clip(path, 24, 24.0),
        image_fn=lambda path, cancel=None: __import__("PIL.Image", fromlist=["Image"]).new(
            "RGB", (8, 8), "red"
        ),
        opener=lambda path: opened.append(path) or ShellResult(True),
        revealer=lambda path: opened.append(f"reveal:{path}") or ShellResult(True),
        **kwargs,
    )
    window.opened = opened  # type: ignore[attr-defined]
    tk_root.update()
    return window


def test_the_window_shows_three_media_roles_without_playing_and_opens_originals_on_request(
    tk_root, built
) -> None:
    window = _window(tk_root, built)
    session = window._session
    assert session.case_id == "head_s0" and session.arms == ("baseline", "motion_emphasis")
    assert session.clock.playing is False and window.play_var.get() == "Play"
    assert window.status_var.get().startswith("Run ")
    assert (
        "Driving reference" in window._panels["driver"]["caption"].get()
        or "Effective input" in window._panels["driver"]["caption"].get()
    )
    assert window._photos.get("source") is not None and window._photos.get("driver") is not None
    notes = window.notes.get("1.0", "end")
    assert "Review previews" in notes and "Expected outcome" in notes

    window._open("driver")
    window._reveal("left")
    assert window.opened[0] == str(built.driver) and window.opened[1].startswith("reveal:")
    window.destroy()


def test_play_pause_and_scrub_use_the_one_clock(tk_root, built) -> None:
    window = _window(tk_root, built)
    window._on_play()
    assert window._session.clock.playing and window.play_var.get() == "Pause"
    window._on_play()
    assert not window._session.clock.playing
    window._on_scrub("1.0")
    assert window._session.clock.position == window._session.clock.last_position
    assert "frame" in window.position_var.get()
    window.destroy()


def test_closing_the_window_cancels_work_and_late_results_are_ignored(tk_root, built) -> None:
    window = _window(tk_root, built)
    session = window._session
    slot = session.slot("left")
    assert slot is not None
    window.destroy()
    assert session.closed and slot.cancel.is_set()
    assert session.slot("left") is None


def test_sfw_mode_withholds_the_source_and_driver_frames(tk_root, built) -> None:
    window = _window(tk_root, built, visibility_mode_provider=lambda: "sfw")
    assert window._photos.get("source") is None and window._photos.get("driver") is None
    assert (
        window._panels["driver"]["caption"].get().endswith("Hidden in SFW mode.")
        or "Hidden in SFW mode." in window._panels["driver"]["caption"].get()
    )
    assert "hidden in SFW mode" in window.notes.get("1.0", "end")
    window.destroy()


def test_a_run_without_a_report_is_explained_not_crashed(tk_root, tmp_path) -> None:
    run = MotionRun(tmp_path)  # admitted but no report built
    window = _window(tk_root, run)
    assert "Build the report" in window.status_var.get()
    window.destroy()


def test_the_panel_offers_motion_review_only_for_a_built_motion_run(tk_root, tmp_path) -> None:
    from src.gui.views.video_eval_panel_v2 import VideoEvalPanel
    from src.video.video_eval_catalog import RunEntry

    panel = VideoEvalPanel(
        tk_root,
        get_controller=lambda: None,
        output_dir=lambda: str(tmp_path),
        show_prompts=lambda: True,
        runner=_runner(),
    )
    entry = lambda motion, built: RunEntry(tmp_path, "t", "s", 3, built, None, None, motion=motion)  # noqa: E731
    for run, enabled in (
        (entry(True, True), True),
        (entry(True, False), False),
        (entry(False, True), False),
    ):
        panel._runs = [run]
        panel.run_combo.configure(values=[run.label])
        panel.run_combo.current(0)
        panel._update_controls()
        assert panel.motion_review_button.instate(["!disabled"]) is enabled
    assert json.dumps(entry(True, True).label)  # a motion run is labelled as such
    assert "driving motion" in entry(True, True).label
