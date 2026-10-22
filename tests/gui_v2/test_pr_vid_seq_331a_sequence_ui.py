"""PR-VID-SEQ-331A: the multi-shot sequence section and Resume/Replay in Job History.

Real Tk widgets; the production ``VideoWorkflowController`` and NJR builder sit behind the recording stand-in for
``JobService.submit_njrs`` from ``tests/helpers/make_video_313.py``. No GPU, Comfy process, model or network is involved.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from src.video.sequence_shots import MAX_SHOTS, MIN_SHOTS
from tests.helpers.make_video_313 import TI2V_ID, make_app, make_image

pytestmark = pytest.mark.gui


@pytest.fixture
def env(tk_root, tmp_path):
    app, controller, service = make_app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    yield SimpleNamespace(app=app, controller=controller, service=service, tab=tab, tmp=tmp_path)
    tab.destroy()


def _ready(env, shots: int = 2) -> Any:
    env.tab.workflow_var.set(TI2V_ID)
    env.tab._on_workflow_id_changed()
    env.tab.source_image_var.set(make_image(env.tmp / "source.png", (480, 832)))
    env.tab.prompt_text.delete("1.0", "end")
    env.tab.prompt_text.insert("1.0", "the person waves")
    panel = env.tab.sequence_panel
    while len(panel._rows) < shots:
        panel.add_shot()
    return panel


# ----------------------------------------------------------------------------- the shot list


def test_the_panel_starts_with_the_minimum_shots_and_stays_within_the_limits(env) -> None:
    panel = _ready(env)

    assert len(panel._rows) == MIN_SHOTS
    assert (
        str(panel._rows[0].keyframe_entry.cget("state")) == "disabled"
    )  # shot 1 starts from the source image
    panel._remove_row(panel._rows[0])
    assert len(panel._rows) == MIN_SHOTS and "at least" in panel.status_var.get()
    while len(panel._rows) < MAX_SHOTS:
        assert panel.add_shot()
    assert not panel.add_shot() and "at most" in panel.status_var.get()
    panel._remove_row(panel._rows[2])
    assert [row.label.cget("text") for row in panel._rows][:3] == ["Shot 1", "Shot 2", "Shot 3"]


def test_lengths_offered_are_the_selected_workflows_legal_choices(env) -> None:
    panel = _ready(env)
    labels = list(env.tab._frame_count_labels)

    assert labels and list(panel._rows[0].length_combo.cget("values")) == labels
    assert panel.shots()[0].frame_count == env.tab._frame_count_labels[labels[0]]


def test_a_workflow_that_declares_no_lengths_cannot_queue_a_sequence(env) -> None:
    panel = _ready(env)
    env.tab._apply_frame_count_choices({}, True)  # what selecting such a workflow does

    assert not env.tab._frame_count_labels
    assert str(panel.queue_button.cget("state")) == "disabled"
    assert "no length policy" in panel.status_var.get()
    panel._on_queue()
    assert env.service.calls == []


# ----------------------------------------------------------------------------- queueing


def test_queue_sequence_admits_one_njr_with_the_typed_plan_through_submit_njrs(env) -> None:
    panel = _ready(env, shots=3)
    keyframe = make_image(env.tmp / "keyframe.png", (480, 832), "red")
    panel._rows[0].prompt_var.set("waves")
    panel._rows[1].prompt_var.set("turns away")
    panel._rows[2].prompt_var.set("sits down")
    panel._rows[2].keyframe_var.set(keyframe)
    panel.clip_name_var.set("walk")

    panel._on_queue()

    assert len(env.service.calls) == 1 and len(env.service.submitted) == 1  # ONE submit, ONE NJR
    plan = dict(env.service.submitted[0].stage_chain[0].extra)["sequence_metadata"]
    assert [s["prompt"] for s in plan["segments"]] == ["waves", "turns away", "sits down"]
    assert [s["anchor_policy"] for s in plan["segments"]] == [
        "source",
        "carry_last_frame",
        "provided",
    ]
    assert (
        plan["segments"][2]["anchor_path"] == keyframe
        and plan["segments"][2]["overlap_frames"] == 0
    )
    assert plan["assembly"]["clip_name"] == "walk"
    assert "Queued a 3-shot sequence as job job-1-0" in panel.status_var.get()


def test_a_refusal_is_shown_inline_and_queues_nothing(env) -> None:
    panel = _ready(env)
    panel._rows[1].keyframe_var.set(str(env.tmp / "missing.png"))

    panel._on_queue()

    assert env.service.calls == []
    assert panel.status_var.get().startswith("Not queued:")

    env.tab.source_image_var.set("")
    panel._on_queue()
    assert "Choose a source image first" in panel.status_var.get() and env.service.calls == []


def test_a_keyframe_of_the_wrong_size_is_refused_by_admission_not_approximated(env) -> None:
    panel = _ready(env)
    panel._rows[1].keyframe_var.set(make_image(env.tmp / "small.png", (64, 96)))

    panel._on_queue()

    assert env.service.calls == [] and panel.status_var.get().startswith("Not queued:")


def test_check_progress_before_anything_is_queued_says_so(env) -> None:
    panel = _ready(env)

    panel._on_progress()

    assert "No sequence has been queued" in panel.status_var.get()


# ----------------------------------------------------------------------------- Job History


def _snapshot(segments: int) -> dict[str, Any]:
    plan = {"segments": [{"index": i} for i in range(segments)]}
    return {
        "normalized_job": {"workload": {"config": {"video_workflow": {"sequence_metadata": plan}}}}
    }


def _entry(
    job_id: str, status: JobStatus, *, snapshot: Any = None, result: Any = None
) -> JobHistoryEntry:
    return JobHistoryEntry(
        job_id=job_id,
        created_at="2025-01-01T12:00:00",
        status=status,
        payload_summary="seq",
        completed_at="2025-01-01T12:05:00",
        snapshot=snapshot,
        result=result,
    )


class _FakeVideoController:
    def __init__(self, progress: Any = (1, 3, "cancelled")) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self._progress = progress

    def sequence_job_progress(self, job_id: str) -> Any:
        return self._progress

    def resume_sequence(
        self, job_id: str, from_segment: Any = None, *, ledger_path: Any = None
    ) -> str:
        self.calls.append(("resume", job_id, ledger_path))
        return "child-resume"

    def replay_sequence(self, job_id: str, *, ledger_path: Any = None) -> str:
        self.calls.append(("replay", job_id, ledger_path))
        return "child-replay"


@pytest.fixture
def history(tk_root):
    video = _FakeVideoController()
    synced: list[bool] = []
    controller = SimpleNamespace(
        get_video_workflow_controller=lambda: video,
        sync_queue_state_after_direct_submission=lambda: synced.append(True),
    )
    state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, controller=controller, app_state=state)
    yield SimpleNamespace(panel=panel, state=state, video=video, synced=synced, root=tk_root)
    panel.destroy()


def _select(h, entries: list[JobHistoryEntry], row: int) -> None:
    h.state.set_history_items(entries)
    h.root.update_idletasks()
    item = h.panel.history_tree.get_children()[row]
    h.panel.history_tree.selection_set(item)
    h.panel.history_tree.event_generate("<<TreeviewSelect>>")
    h.root.update_idletasks()


def test_history_offers_resume_and_replay_only_for_a_sequence_job(history) -> None:
    sequence = _entry(
        "seq-1",
        JobStatus.CANCELLED,
        snapshot=_snapshot(3),
        result={"metadata": {"sequence_artifact": {"completed_segments": 1}}},
    )
    ordinary = _entry("img-1", JobStatus.COMPLETED)

    _select(history, [sequence, ordinary], 0)
    assert history.panel.sequence_status_var.get().startswith(
        "Sequence cancelled: 1 of 3 segments done"
    )
    assert str(history.panel.resume_sequence_btn.cget("state")) == "normal"
    assert str(history.panel.replay_sequence_btn.cget("state")) == "normal"
    assert history.panel.resume_sequence_btn.winfo_manager() == "pack"

    _select(history, [sequence, ordinary], 1)
    assert history.panel.sequence_status_var.get() == ""
    assert history.panel.resume_sequence_btn.winfo_manager() == ""


def test_a_finished_sequence_can_only_be_replayed_and_a_running_one_neither(history) -> None:
    done = _entry("seq-ok", JobStatus.COMPLETED, snapshot=_snapshot(2))
    running = _entry("seq-run", JobStatus.RUNNING, snapshot=_snapshot(2))

    _select(history, [done, running], 0)
    assert str(history.panel.resume_sequence_btn.cget("state")) == "disabled"
    assert str(history.panel.replay_sequence_btn.cget("state")) == "normal"

    _select(history, [done, running], 1)
    assert str(history.panel.resume_sequence_btn.cget("state")) == "disabled"
    assert str(history.panel.replay_sequence_btn.cget("state")) == "disabled"


def test_resume_and_replay_queue_a_new_job_and_say_so(history) -> None:
    entry = _entry("seq-1", JobStatus.FAILED, snapshot=_snapshot(3))
    _select(history, [entry], 0)

    history.panel.resume_sequence_btn.invoke()
    assert history.video.calls == [("resume", "seq-1", None)]
    assert (
        "Queued a resume of job seq-1 as job child-resume" in history.panel.replay_status_var.get()
    )

    history.panel.replay_sequence_btn.invoke()
    assert history.video.calls[-1] == ("replay", "seq-1", None)
    assert "full replay" in history.panel.replay_status_var.get()
    assert history.synced == [True, True]  # the queue view is refreshed after each admission


def test_a_job_with_no_checkpoint_asks_for_the_file_and_nothing_is_queued_without_it(
    history,
) -> None:
    history.video._progress = None
    entry = _entry("seq-1", JobStatus.CANCELLED, snapshot=_snapshot(2))
    _select(history, [entry], 0)

    history.panel._pick_sequence_ledger = lambda: None
    history.panel.resume_sequence_btn.invoke()
    assert history.video.calls == []
    assert "sequence_state.json" in history.panel.replay_status_var.get()

    history.panel._pick_sequence_ledger = lambda: "C:/runs/seq/sequence_state.json"
    history.panel.resume_sequence_btn.invoke()
    assert history.video.calls == [("resume", "seq-1", "C:/runs/seq/sequence_state.json")]


def test_a_refused_resume_is_shown_and_does_not_look_queued(history) -> None:
    from src.video.sequence_resume import SequenceResumeError

    def refuse(*_a: Any, **_k: Any) -> str:
        raise SequenceResumeError("the checkpoint changed since it was recorded")

    history.video.resume_sequence = refuse  # type: ignore[method-assign]
    _select(history, [_entry("seq-1", JobStatus.FAILED, snapshot=_snapshot(2))], 0)

    history.panel.resume_sequence_btn.invoke()

    text = history.panel.replay_status_var.get()
    assert "Resume Sequence refused" in text and "changed since" in text and history.synced == []


def test_the_panels_plan_is_the_plan_a_direct_submission_of_the_same_intent_freezes(env) -> None:
    from src.video.sequence_shots import ShotDraft, build_sequence_intent

    panel = _ready(env, shots=2)
    keyframe = make_image(env.tmp / "keyframe.png", (480, 832), "red")
    shots = [
        ShotDraft(prompt="waves", frame_count=17, seed="11"),
        ShotDraft(prompt="turns", frame_count=21, seed="12", keyframe_path=keyframe),
    ]
    for row, shot in zip(panel._rows, shots, strict=True):
        row.prompt_var.set(shot.prompt)
        row.keyframe_var.set(shot.keyframe_path)
        row.length_var.set(
            next(k for k, v in env.tab._frame_count_labels.items() if v == shot.frame_count)
        )
        row.seed_var.set(shot.seed)
    # Both submissions share one source image, form and sequence id, so the digest differs only if the plans do.
    panel._session.submit = _with_sequence_id(panel._session.submit, "fixed-id")  # type: ignore[method-assign]

    panel._on_queue()
    source, form = (
        env.tab.source_image_var.get(),
        env.tab.get_video_workflow_state(for_submission=True),
    )
    direct = {**build_sequence_intent(shots), "sequence_id": "fixed-id"}
    env.controller.submit_sequence_job(
        source_image_path=source, form_data=form, sequence_intent=direct
    )

    first, second = (
        dict(n.stage_chain[0].extra)["sequence_metadata"] for n in env.service.submitted
    )
    assert first["plan_digest"] == second["plan_digest"]
    assert [s["seed"] for s in first["segments"]] == [11, 12]


def _with_sequence_id(submit: Any, sequence_id: str) -> Any:
    def wrapped(**kwargs: Any) -> Any:
        controller = submit.__self__._get_controller()
        original = controller.submit_sequence_job

        def with_id(**inner: Any) -> Any:
            inner["sequence_intent"] = {**inner["sequence_intent"], "sequence_id": sequence_id}
            return original(**inner)

        controller.submit_sequence_job = with_id
        try:
            return submit(**kwargs)
        finally:
            del controller.submit_sequence_job

    return wrapped
