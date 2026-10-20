"""PR-VID-QUALITY-211: the real Tk review window, its entry points and its worker hygiene.

A real repository and evidence file in a temp dir; a synchronous work runner (or a deferring one) in place
of ``ThreadRegistry``; stub or real-FFmpeg previews.  Skipped without a display.  No GPU, Comfy or network.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views import video_experiment_review_window as window_module
from src.gui.views.video_experiment_review_window import (
    VideoExperimentReviewWindow,
    build_review_service,
    open_video_experiment_review,
)
from src.learning.video_review_service import VideoReviewService
from src.queue.job_model import JobStatus
from src.video.review_preview import PreviewClip, PreviewResult, prepare_review_preview
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.video_review_211 import (
    FFMPEG_AVAILABLE,
    build_plan,
    finish,
    make_clip,
    new_repository,
    persist,
    persist_plan,
    video_result,
)


def _sync_runner() -> BackgroundWorkRunner:
    return BackgroundWorkRunner(spawn=lambda name, target: target(), dispatch=lambda fn: fn())


class _DeferredRunner(BackgroundWorkRunner):
    """Collects work so a test can destroy the window before any of it finishes."""

    def __init__(self) -> None:
        self.pending: list[Any] = []
        super().__init__(
            spawn=lambda name, target: self.pending.append(target), dispatch=lambda fn: fn()
        )


class _Env:
    def __init__(self, tmp_path: Path, *, complete: tuple[int, ...] = (0, 1, 2)) -> None:
        self.tmp = tmp_path
        self.plan = build_plan(tmp_path)
        self.repository = new_repository(tmp_path)
        self.ids = persist_plan(self.repository, self.plan)
        self.records = tmp_path / "learning_records.jsonl"
        self.clips: dict[int, Path] = {}
        for index in complete:
            clip = tmp_path / "out" / f"arm{index}.mp4"
            clip.parent.mkdir(exist_ok=True)
            clip.write_bytes(f"clip {index}".encode() * 40)
            self.clips[index] = clip
            finish(self.repository, self.ids[index], JobStatus.COMPLETED, result=video_result(clip))

    def service(self) -> VideoReviewService:
        return VideoReviewService(self.repository, self.records)


def _stub_preview(frames: dict[str, int] | None = None, fps: float = 12.0):
    counts = frames or {}

    def preview(path: str, cancel=None) -> PreviewResult:
        count = counts.get(Path(path).stem, 6)
        clip = PreviewClip(
            path=path,
            width=8,
            height=6,
            source_width=64,
            source_height=48,
            fps=fps,
            frame_count=count,
            reported_frame_count=count,
            duration_seconds=count / fps,
            raw=b"".join(bytes([n * 20 % 256]) * (8 * 6 * 3) for n in range(count)),
        )
        return PreviewResult(path, "ok", clip)

    return preview


def _open(root, env, **kwargs) -> VideoExperimentReviewWindow:
    window = VideoExperimentReviewWindow(
        root,
        service=kwargs.pop("service", env.service()),
        initial_job_id=kwargs.pop("job_id", env.ids[1]),
        runner=kwargs.pop("runner", _sync_runner()),
        preview_fn=kwargs.pop("preview_fn", _stub_preview()),
        **kwargs,
    )
    root.update()  # runs the after_idle load
    return window


def _tree_rows(window) -> list[tuple]:
    return [window.arm_tree.item(item, "values") for item in window.arm_tree.get_children()]


# ------------------------------------------------------------------ opening and comparing


def test_opening_by_job_id_shows_the_stable_arms_overview_and_a_first_frame(tk_root, tmp_path):
    env = _Env(tmp_path)
    window = _open(tk_root, env, job_id=env.ids[2])

    rows = _tree_rows(window)
    assert [row[0] for row in rows] == ["A (baseline)", "B", "C"]
    assert [row[2] for row in rows] == env.ids
    assert rows[0][3] == "Ready to review."
    overview = window.overview_text.get("1.0", "end")
    assert "Shared seed: 424242" in overview and "wan_animate2_drive_i2v_v1" in overview
    assert "Tested control: pose_strength" in overview
    assert window.sides[0].choice_var.get().startswith("A") and window.sides[
        1
    ].choice_var.get().startswith("B")
    assert window.sides[0].shown is not None and window.sides[1].shown is not None
    assert "Review preview" in window.sides[0].info_var.get()
    window.destroy()


def test_unfinished_and_failed_arms_are_listed_but_cannot_be_put_on_screen(tk_root, tmp_path):
    env = _Env(tmp_path, complete=(0,))
    finish(env.repository, env.ids[2], JobStatus.FAILED, error="out of memory")
    window = _open(tk_root, env, job_id=env.ids[0])

    states = [row[3] for row in _tree_rows(window)]
    assert (
        states[0] == "Ready to review."
        and states[1].startswith("Queued")
        and "out of memory" in states[2]
    )
    assert window.sides[1].choice_var.get() == ""
    assert "Only one" in window.status_var.get() or "1 ready" in window.status_var.get()
    window.destroy()


def test_a_bad_job_id_reports_why_and_leaves_the_window_usable(tk_root, tmp_path):
    env = _Env(tmp_path)
    plain = make_test_njr(prompt="plain image job")
    persist(env.repository, [plain])
    window = _open(tk_root, env, job_id=plain.job_id)

    assert window.status_var.get().startswith("Cannot review:")
    assert "not an arm of a Video Workflow experiment" in window.status_var.get()
    window.job_var.set(env.ids[0])
    window._on_load()
    assert "Experiment " in window.status_var.get() and _tree_rows(window)
    window.destroy()


def test_transport_steps_scrubs_and_restarts_the_common_clock(tk_root, tmp_path):
    env = _Env(tmp_path)
    window = _open(tk_root, env, preview_fn=_stub_preview({"arm0": 6, "arm1": 3}))
    clock = window._session.clock
    first = window.sides[0].shown

    window._on_step(1)
    assert clock.position == 1 and window.sides[0].shown != first
    window._on_step(1)
    window._on_step(1)
    right_held = window.sides[1].shown
    window._on_step(1)
    assert window.sides[1].shown == right_held  # the 3-frame clip is held on its last frame
    window._on_scrub("5")
    assert clock.position == 5 and "t = " in window.position_var.get()
    window._on_restart()
    assert clock.position == 0 and float(window.scrub.get()) == 0.0
    assert "B is shorter" in window.clock_notes_var.get()
    window.destroy()


def test_play_advances_with_injected_time_and_pause_stops_it(tk_root, tmp_path):
    env = _Env(tmp_path)
    ticks = iter([0.0, 0.2, 0.2, 0.45, 0.45, 1.5, 1.5, 1.5, 1.5])
    window = _open(
        tk_root, env, now=lambda: next(ticks, 9.0), preview_fn=_stub_preview({"arm0": 6, "arm1": 6})
    )

    window._on_play()
    assert window._session.clock.playing and window.play_var.get() == "Pause"
    window._tick()
    assert window._session.clock.position >= 1
    window._on_play()
    assert not window._session.clock.playing and window.play_var.get() == "Play"
    window.destroy()
    assert window._tick_id is None


def test_choosing_another_pair_keeps_arm_identities(tk_root, tmp_path):
    env = _Env(tmp_path)
    window = _open(tk_root, env, job_id=env.ids[0])

    choices = {text[0]: text for _job, text in window._session.available_choices()}
    window.sides[0].choice_var.set(choices["B"])
    window.sides[1].choice_var.set(choices["C"])
    window._on_pair_selected()

    assert window._session.pair == (env.ids[1], env.ids[2])
    assert "B" in window.sides[0].caption_var.get() and "C" in window.sides[1].caption_var.get()
    assert window.sides[0].form_frame.cget("text").startswith("Review of B")
    window.destroy()


# ------------------------------------------------------------------ rating in the window


def test_rating_two_clips_in_the_window_persists_and_survives_a_rebuilt_window(tk_root, tmp_path):
    env = _Env(tmp_path)
    window = _open(tk_root, env, job_id=env.ids[0])
    left, right = window.sides
    left.overall_var.set("5")
    left.outcome_var.set("Not achieved")
    left.dimension_vars["temporal_continuity"].set("4")
    left.notes.insert("1.0", "feet stayed planted")
    window._on_notes(left)
    window._on_save(left)
    assert left.message_var.get() == "Saved (revision 1)."
    right.overall_var.set("2")
    right.outcome_var.set("Achieved")
    window._on_save(right)
    assert right.message_var.get() == "Saved (revision 1)."
    assert "unsaved" not in left.form_frame.cget("text")
    window.destroy()

    rows = [
        json.loads(line)["metadata"]["video_quality_review"]
        for line in env.records.read_text().splitlines()
    ]
    assert [(r["arm_label"], r["overall_rating"], r["action_outcome"]) for r in rows] == [
        ("A", 5, "not_achieved"),
        ("B", 2, "achieved"),
    ]

    reopened = _open(tk_root, env, job_id=env.ids[2])  # a different arm, a fresh window and service
    assert (
        reopened.sides[0].overall_var.get() == "5"
        and reopened.sides[0].outcome_var.get() == "Not achieved"
    )
    assert reopened.sides[0].notes.get("1.0", "end-1c") == "feet stayed planted"
    assert reopened.sides[0].message_var.get() == "Saved review, revision 1."
    assert reopened.sides[1].overall_var.get() == "2"
    reopened.destroy()


def test_a_failed_save_is_shown_as_failed_and_keeps_the_edits(tk_root, tmp_path, monkeypatch):
    from src.learning.learning_record import LearningRecordWriter

    env = _Env(tmp_path)
    window = _open(tk_root, env, job_id=env.ids[0])
    monkeypatch.setattr(LearningRecordWriter, "append_record", lambda self, record: False)
    left = window.sides[0]
    left.overall_var.set("3")
    left.outcome_var.set("Partially achieved")

    window._on_save(left)

    assert left.message_var.get().startswith("Save FAILED, your edits are kept")
    assert "Saved" not in left.message_var.get().replace("Save FAILED", "")
    assert left.overall_var.get() == "3" and "unsaved" in left.form_frame.cget("text")
    assert not env.records.exists() or env.records.read_text() == ""
    window.destroy()


def test_invalid_input_is_refused_before_any_write(tk_root, tmp_path):
    env = _Env(tmp_path)
    window = _open(tk_root, env, job_id=env.ids[0])
    left = window.sides[0]

    window._on_save(left)  # nothing chosen yet

    assert left.message_var.get().startswith("Not saved: Overall rating is required")
    assert not env.records.exists()
    window.destroy()


def test_a_manual_preference_is_saved_from_the_window(tk_root, tmp_path):
    env = _Env(tmp_path)
    window = _open(tk_root, env, job_id=env.ids[0])
    label = window._session.available_choices()[1][1]
    window.pref_var.set(label)
    window._on_preference()
    window.pref_reason_var.set("cleaner shoulders")
    window._on_save_preference()

    assert "Saved manual preference" in window.pref_message_var.get()
    saved = json.loads(env.records.read_text().splitlines()[-1])["metadata"]["video_quality_review"]
    assert saved["entry_type"] == "manual_preference" and saved["preferred_arm_label"] == "B"
    window.destroy()


# ------------------------------------------------------------------ decoder trouble and originals


def test_a_missing_decoder_keeps_metadata_ratings_and_the_original_available(tk_root, tmp_path):
    env = _Env(tmp_path)
    opened: list[str] = []

    def no_ffmpeg(path, cancel=None):
        return PreviewResult(
            path,
            "failed",
            None,
            "ffmpeg_unavailable",
            "FFmpeg was not found, so no review preview can be shown.",
        )

    window = _open(tk_root, env, job_id=env.ids[0], preview_fn=no_ffmpeg, opener=opened.append)
    left = window.sides[0]

    assert "FFmpeg was not found" in left.info_var.get()
    assert str(left.save_button.cget("state")) == "normal"
    assert str(left.original_button.cget("state")) == "normal"
    window._on_open_original(left)
    assert opened == [str(env.clips[0])]
    env.clips[0].unlink()
    window._render()
    assert str(left.original_button.cget("state")) == "disabled"
    window._on_open_original(left)
    assert opened == [str(env.clips[0])] and "no longer available" in left.info_var.get()
    window.destroy()


def test_a_failing_decoder_function_does_not_crash_tk(tk_root, tmp_path):
    env = _Env(tmp_path)

    def explode(path, cancel=None):
        raise RuntimeError("codec exploded")

    window = _open(tk_root, env, job_id=env.ids[0], preview_fn=explode)

    assert "codec exploded" in window.sides[0].info_var.get()
    assert window.winfo_exists()
    window.destroy()


# ------------------------------------------------------------------ worker hygiene


def test_destroying_before_the_workers_finish_is_safe_and_cancels_them(tk_root, tmp_path):
    env = _Env(tmp_path)
    runner = _DeferredRunner()
    window = _open(tk_root, env, runner=runner)
    assert runner.pending  # the load has not run yet
    session = window._session

    window.destroy()
    for target in list(runner.pending):
        target()  # the late worker finishes into a dead window

    assert session.closed and session.group is None


def test_repeated_open_and_close_cycles_leave_nothing_behind(tk_root, tmp_path):
    env = _Env(tmp_path)
    sessions = []
    for _ in range(12):
        window = _open(tk_root, env, job_id=env.ids[0])
        sessions.append(window._session)
        window.destroy()
    tk_root.update()

    assert all(session.closed and not session._slots for session in sessions)


def test_changing_the_pair_while_decoding_discards_the_stale_frames(tk_root, tmp_path):
    env = _Env(tmp_path)
    runner = _DeferredRunner()
    window = VideoExperimentReviewWindow(
        tk_root,
        service=env.service(),
        initial_job_id=env.ids[0],
        runner=runner,
        preview_fn=_stub_preview(),
    )
    tk_root.update()
    runner.pending.pop(0)()  # the load finishes; two preview decodes are queued
    first_wave = list(runner.pending)
    runner.pending.clear()
    choices = {text[0]: text for _job, text in window._session.available_choices()}
    window.sides[0].choice_var.set(choices["A"])
    window.sides[1].choice_var.set(choices["C"])
    window._on_pair_selected()  # B is abandoned while its decode is in flight
    for target in first_wave:
        target()
    for target in list(runner.pending):
        target()

    assert window._session.slot(env.ids[1]) is None
    assert window.sides[1].shown is not None and window.sides[1].shown[0] == env.ids[2]
    window.destroy()


# ------------------------------------------------------------------ real decoder, end to end


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg/FFprobe are not installed")
def test_real_clips_play_side_by_side_with_different_durations(tk_root, tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    long_clip = make_clip(tmp_path, "long.mp4", frames=12, rate=12)
    short_clip = make_clip(tmp_path, "short.mp4", frames=6, rate=12)
    finish(repository, ids[0], JobStatus.COMPLETED, result=video_result(long_clip))
    finish(repository, ids[1], JobStatus.COMPLETED, result=video_result(short_clip))
    service = VideoReviewService(repository, tmp_path / "records.jsonl")

    window = VideoExperimentReviewWindow(
        tk_root,
        service=service,
        initial_job_id=ids[2],
        runner=_sync_runner(),
        preview_fn=lambda path, cancel=None: prepare_review_preview(path, cancel=cancel),
    )
    tk_root.update()

    clock = window._session.clock
    assert clock.steps == 12
    assert window._session.slot(ids[0]).clip.frame_count == 12
    assert window._session.slot(ids[1]).clip.frame_count == 6
    assert window.sides[0].shown is not None and window.sides[1].shown is not None
    window._on_scrub("11")
    assert clock.position == 11 and "(held)" in window.position_var.get()
    assert "B is shorter" in window.clock_notes_var.get()
    window.destroy()


# ------------------------------------------------------------------ entry points


class _Controller:
    def __init__(self, repository) -> None:
        self.job_service = SimpleNamespace(history_store=repository)
        self.app_state = SimpleNamespace(content_visibility_mode="sfw")


def test_the_launcher_needs_a_repository_that_can_find_siblings(tk_root, tmp_path):
    assert build_review_service(SimpleNamespace()) is None
    assert (
        build_review_service(SimpleNamespace(job_service=SimpleNamespace(history_store=object())))
        is None
    )
    assert open_video_experiment_review(tk_root, SimpleNamespace(), "x") is None
    env = _Env(tmp_path)
    assert isinstance(build_review_service(_Controller(env.repository)), VideoReviewService)


def test_history_panel_offers_review_only_for_experiment_arms(tk_root, tmp_path, monkeypatch):
    env = _Env(tmp_path)
    plain = make_test_njr(prompt="plain image")
    persist(env.repository, [plain])
    controller = _Controller(env.repository)
    opened: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        window_module, "open_video_experiment_review", lambda *args: opened.append(args) or None
    )
    panel = JobHistoryPanelV2(tk_root, controller=controller, manage_app_state_subscriptions=False)
    arm_entry = env.repository.get_job(env.ids[1])
    plain_entry = env.repository.get_job(plain.job_id)
    panel._entries = {arm_entry.job_id: arm_entry, plain_entry.job_id: plain_entry}

    panel._selected_job_id = plain_entry.job_id
    panel._update_action_buttons(plain_entry)
    assert str(panel.review_btn.cget("state")) == "disabled"
    panel._on_review_video_experiment()
    assert opened == []

    panel._selected_job_id = arm_entry.job_id
    panel._update_action_buttons(arm_entry)
    assert str(panel.review_btn.cget("state")) == "normal"
    assert panel._history_menu.entrycget("Review Video Experiment", "state") == "normal"
    panel._on_review_video_experiment()
    assert len(opened) == 1 and opened[0][1] is controller and opened[0][2] == arm_entry.job_id
    # Without a repository that can answer, the action is not offered at all.
    bare = JobHistoryPanelV2(
        tk_root, controller=SimpleNamespace(), manage_app_state_subscriptions=False
    )
    bare._selected_job_id = arm_entry.job_id
    bare._entries = {arm_entry.job_id: arm_entry}
    bare._update_action_buttons(arm_entry)
    assert str(bare.review_btn.cget("state")) == "disabled"


def test_the_visibility_mode_reaches_the_window_through_the_launcher(tk_root, tmp_path):
    plan = build_plan(tmp_path, prompt="a nude woman walks")
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    controller = _Controller(repository)

    assert controller.app_state.content_visibility_mode == "sfw"
    launched = open_video_experiment_review(tk_root, controller, ids[0])
    assert (
        launched is not None
    )  # the launcher builds the real service over the controller's repository
    launched.destroy()

    env_window = VideoExperimentReviewWindow(
        tk_root,
        service=VideoReviewService(repository, tmp_path / "r.jsonl"),
        initial_job_id=ids[0],
        runner=_sync_runner(),
        preview_fn=_stub_preview(),
        visibility_mode_provider=lambda: "sfw",
    )
    tk_root.update()
    text = env_window.overview_text.get("1.0", "end")
    assert "[Hidden in SFW mode]" in text and "nude" not in text
    env_window.destroy()


def test_video_workflow_tab_review_button_opens_the_last_queued_experiment(tk_root, monkeypatch):
    from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

    app = SimpleNamespace(
        get_video_workflow_specs=lambda: [],
        build_video_workflow_defaults=lambda: {},
        job_service=SimpleNamespace(),
    )
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    opened: list[str] = []
    monkeypatch.setattr(
        window_module,
        "open_video_experiment_review",
        lambda parent, controller, job_id="": opened.append(job_id) or object(),
    )
    panel = tab.experiment_panel

    panel._on_review_clicked()
    assert opened == [""]  # no experiment queued yet: the window opens empty for a typed job id
    panel._review_job_id = "job-from-queue"
    panel._on_review_clicked()
    assert opened == ["", "job-from-queue"]
    tab._on_experiment_queued(["job-1", "job-2"])
    assert "Queued 2 experiment jobs" in tab.status_var.get()


# ------------------------------------------------------------------ nothing blocking runs on Tk


def test_construction_and_idle_do_no_repository_hashing_or_decode_work(tk_root, tmp_path):
    env = _Env(tmp_path)
    runner = _DeferredRunner()
    calls: list[str] = []
    service = env.service()
    real_load = service.load
    service.load = lambda *a, **k: calls.append("load") or real_load(*a, **k)

    def preview(path, cancel=None):
        calls.append("decode")
        return _stub_preview()(path, cancel)

    window = _open(tk_root, env, service=service, runner=runner, preview_fn=preview)
    tk_root.update()

    assert calls == [] and len(runner.pending) == 1  # the load is only queued, nothing ran inline
    runner.pending.pop(0)()
    assert calls == ["load"] and len(runner.pending) == 2  # the decodes are queued, not run
    for target in list(runner.pending):
        target()
    assert calls == ["load", "decode", "decode"]
    window.destroy()


def test_real_worker_threads_do_the_work_and_tk_gets_the_results(tk_root, tmp_path):
    import threading
    import time

    env = _Env(tmp_path)
    main = threading.get_ident()
    seen: dict[str, set[int]] = {"load": set(), "decode": set(), "render": set()}
    service = env.service()
    real_load = service.load

    def traced_load(*args, **kwargs):
        seen["load"].add(threading.get_ident())
        return real_load(*args, **kwargs)

    service.load = traced_load
    preview = _stub_preview()

    def traced_preview(path, cancel=None):
        seen["decode"].add(threading.get_ident())
        return preview(path, cancel)

    window = VideoExperimentReviewWindow(
        tk_root, service=service, initial_job_id=env.ids[0], preview_fn=traced_preview
    )
    real_render = window._render_now

    def traced_render():
        seen["render"].add(threading.get_ident())
        real_render()

    window._render_now = traced_render
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not (window.sides[0].shown and window.sides[1].shown):
        tk_root.update()
        time.sleep(0.01)

    assert window.sides[0].shown is not None and window.sides[1].shown is not None
    assert main not in seen["load"] and main not in seen["decode"]
    assert seen["render"] == {main}
    window.destroy()


def test_a_reload_rebuilds_the_form_widgets_from_the_reloaded_review(tk_root, tmp_path):
    env = _Env(tmp_path)
    window = _open(tk_root, env, job_id=env.ids[0])
    left = window.sides[0]
    left.overall_var.set("4")
    left.notes.insert("1.0", "typed but never saved")
    window._on_notes(left)
    assert "unsaved" in left.form_frame.cget("text")

    window._on_load()  # reload: the unsaved edits are discarded with the old session forms

    assert left.overall_var.get() == "" and left.notes.get("1.0", "end-1c") == ""
    assert "unsaved" not in left.form_frame.cget("text")
    window.destroy()


def test_playback_ticks_do_not_rebuild_the_static_overview_or_the_arm_table(tk_root, tmp_path):
    env = _Env(tmp_path)
    ticks = iter([0.0, 0.2, 0.4, 0.6])
    window = _open(tk_root, env, now=lambda: next(ticks, 9.0))
    rows_before = window.arm_tree.get_children()
    window._on_play()
    before = window._static_key
    window._tick()
    window._tick()

    assert window._static_key is before and window.arm_tree.get_children() == rows_before
    assert window._session.clock.position > 0
    window.destroy()
