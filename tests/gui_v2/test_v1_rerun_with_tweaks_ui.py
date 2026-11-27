"""V1-2: desktop Re-run with tweaks (Recent outputs, Job History, the Video Workflow form).

Real Tk widgets; the production ``VideoWorkflowController`` and NJR builder sit behind the recording ``JobService``
stand-in, and finished jobs come from a repository double with the canonical ``get_job_model`` shape.  The worker that
reads the job runs inline so the test is deterministic.  No GPU, Comfy process, model or network.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.video_workflow_recent_outputs_panel_v2 import WorkflowRecentOutputsPanel
from src.gui.views.video_workflow_rerun_host import RerunHost
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.pipeline.history_variation_marker import VARIATION_KEY
from src.pipeline.njr_core_v26 import SourceKind, thaw_json
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import Job, JobStatus
from src.video.motion_intent import length_policy
from src.video.motion_rerun import apply_tweaks, load_snapshot, parse_tweaks, rerun_submission_form
from src.video.recent_video_outputs import RecentVideoOutput
from tests.helpers.make_video_313 import RECOMMENDED_ID, make_app, make_image, make_window
from tests.helpers.motion_library_353 import write_clip

pytestmark = pytest.mark.gui

SCENE = "a woman on a balcony at dusk"
A14B_POLICY = length_policy(
    {"default": 81, "minimum": 17, "maximum": 121, "step": 4, "offset": 1, "fps": 16}
)


class Repo:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def add(self, njr: Any) -> str:
        self.jobs[njr.job_id] = Job(
            job_id=njr.job_id, status=JobStatus.COMPLETED, _normalized_record=njr
        )
        return njr.job_id

    def get_job_model(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)


def _inline_runner() -> BackgroundWorkRunner:
    return BackgroundWorkRunner(spawn=lambda _name, target: target(), dispatch=lambda fn: fn())


def _stage(njr) -> dict[str, Any]:
    return thaw_json(next(s for s in njr.stage_chain if s.stage_type == "video_workflow").extra)


@pytest.fixture
def env(tk_root, tmp_path):
    repo = Repo()
    app, controller, service = make_app(tmp_path, repository=repo)
    controller.rife_available = lambda: False
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    tab._rerun_host = RerunHost(
        tab,
        repository=lambda: repo,
        on_opened=tab.apply_rerun,
        on_refused=tab._fail,
        on_status=tab.status_var.set,
        runner=_inline_runner(),
    )
    tab.source_image_var.set(make_image(tmp_path / "source.png"))
    tab.prompt_text.insert("1.0", SCENE)
    tab.motion_intent_panel.choose_preset("Walk")
    tab.seed_var.set("7")
    tab._on_submit()
    parent = service.submitted[-1]
    repo.add(parent)
    yield SimpleNamespace(
        app=app, controller=controller, service=service, tab=tab, repo=repo, parent=parent
    )
    tab.destroy()


def _scramble(tab) -> None:
    """Leave the form somewhere else, so the re-run visibly fills it."""

    tab.motion_intent_panel.choose_preset("None")
    tab._set_text_value(tab.prompt_text, "something else")
    tab.motion_intent_panel.enter_duration("2")


def test_re_run_fills_the_form_from_the_finished_job_with_a_new_random_seed(env):
    tab = env.tab
    _scramble(tab)
    tab.open_rerun(env.parent.job_id)
    panel = tab.motion_intent_panel
    assert tab.current_task() == "animate" and tab.workflow_var.get() == RECOMMENDED_ID
    assert tab.prompt_text.get("1.0", "end").strip() == SCENE
    assert panel.preset_var.get() == "Walk" and panel.phrase_var.get().startswith("walks")
    assert tab._frame_count_labels[tab.frame_count_var.get()] == 81
    assert tab.seed_var.get() == ""
    assert "Re-run with tweaks of job" in tab.status_var.get()
    assert {
        "frame_count",
        "motion_phrase",
        "seed",
    } <= tab._pins.pinned  # every value is the operator's


def test_queueing_an_untouched_re_run_builds_a_new_njr_with_lineage(env):
    tab = env.tab
    tab.open_rerun(env.parent.job_id)
    tab._on_submit()
    child = env.service.submitted[-1]
    assert child.job_id != env.parent.job_id
    assert child.source.kind is SourceKind.HISTORY_REPLAY
    assert child.source.parent_job_id == env.parent.job_id
    assert list(dict(child.source.metadata)[VARIATION_KEY]["edited_fields"]) == ["seed"]
    assert child.positive_prompt == env.parent.positive_prompt
    child_stage, parent_stage = _stage(child), _stage(env.parent)
    for stage in (child_stage, parent_stage):
        stage.pop("seed")
        stage.pop("source_preparation", None)
    assert child_stage == parent_stage


def test_a_desktop_edit_and_the_same_phone_tweak_build_the_same_job(env):
    tab = env.tab
    tab.open_rerun(env.parent.job_id)
    tab._set_text_value(tab.prompt_text, "a man on a balcony")
    tab.motion_intent_panel.enter_duration("3")
    tab.seed_var.set("5")
    tab._on_submit()
    desktop = env.service.submitted[-1]
    snapshot = load_snapshot(env.repo, env.parent.job_id)
    tweaked, _ = apply_tweaks(
        snapshot,
        parse_tweaks({"prompt": "a man on a balcony", "duration_seconds": 3, "seed": 5}),
        A14B_POLICY,
    )
    form = rerun_submission_form(snapshot, tweaked, A14B_POLICY)
    env.controller.submit_video_workflow_job(
        source_image_path=tweaked.source_image_path, form_data=form
    )
    phone = env.service.submitted[-1]
    desktop_stage, phone_stage = _stage(desktop), _stage(phone)
    for stage in (desktop_stage, phone_stage):
        stage.pop("source_preparation", None)
    assert desktop_stage == phone_stage
    assert desktop.positive_prompt == phone.positive_prompt
    assert desktop.source.parent_job_id == phone.source.parent_job_id == env.parent.job_id
    assert (
        list(dict(desktop.source.metadata)[VARIATION_KEY]["edited_fields"])
        == list(dict(phone.source.metadata)[VARIATION_KEY]["edited_fields"])
        == ["prompt", "frame_count", "seed"]
    )


def test_the_lineage_stops_when_the_source_changes(env, tmp_path):
    tab = env.tab
    tab.open_rerun(env.parent.job_id)
    tab.source_image_var.set(make_image(tmp_path / "other.png", color="red"))
    tab._on_submit()
    child = env.service.submitted[-1]
    assert child.source.kind is SourceKind.VIDEO_WORKFLOW


def test_an_unknown_job_is_refused_with_the_reason_and_the_form_is_kept(env):
    tab = env.tab
    tab._set_text_value(tab.prompt_text, "keep me")
    tab.open_rerun("missing-job")
    assert "was not found" in tab.status_var.get()
    assert tab.prompt_text.get("1.0", "end").strip() == "keep me"
    assert tab._rerun is None


# ---------------------------------------------------------------- entry points


def _pump_until(root: tk.Misc, predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_recent_outputs_offers_re_run_for_the_selected_clip(tk_root, tmp_path):
    clip = write_clip(tmp_path / "job-2.mp4", b"finished clip")
    output = RecentVideoOutput(job_id="job-2", video_path=str(clip), completed_at=None)
    chosen: list[RecentVideoOutput] = []
    panel = WorkflowRecentOutputsPanel(
        tk_root, list_outputs=lambda: [output], rerun_with_tweaks=chosen.append
    )
    try:
        assert str(panel.rerun_button.cget("state")) == "disabled"
        panel.request_refresh()
        assert _pump_until(tk_root, lambda: bool(panel.tree.get_children()))
        panel.tree.selection_set("job-2")
        panel.tree.event_generate("<<TreeviewSelect>>")
        assert _pump_until(tk_root, lambda: str(panel.rerun_button.cget("state")) == "normal")
        panel.rerun_button.invoke()
        assert chosen == [output]
    finally:
        panel.destroy()


class _RerunTab:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open_rerun(self, job_id: str) -> None:
        self.opened.append(job_id)


def _history_entry(job_id: str, video: Path | None, status: JobStatus) -> JobHistoryEntry:
    stamp = "2025-01-01T12:00:00"
    result: dict[str, Any] = {}
    if video is not None:
        result = {
            "video_bundle": {
                "stage": "video_workflow",
                "primary_path": str(video),
                "output_paths": [str(video)],
            }
        }
    return JobHistoryEntry(
        job_id=job_id,
        created_at=stamp,
        status=status,
        payload_summary="a clip",
        completed_at=stamp,
        started_at=stamp,
        snapshot=None,
        result=result,
    )


def test_job_history_opens_a_completed_clip_for_re_run(tk_root, tmp_path):
    window = SimpleNamespace(
        video_workflow_tab=_RerunTab(), center_notebook=SimpleNamespace(select=lambda tab: None)
    )
    state = AppStateV2()
    panel = JobHistoryPanelV2(
        tk_root, controller=SimpleNamespace(main_window=window), app_state=state
    )
    try:
        video = write_clip(tmp_path / "out" / "gen.mp4", b"generated")
        for entry, enabled in (
            (_history_entry("job-1", video, JobStatus.COMPLETED), True),
            (_history_entry("job-f", video, JobStatus.FAILED), False),
        ):
            state.set_history_items([entry])
            tk_root.update_idletasks()
            [item] = panel.history_tree.get_children()
            panel.history_tree.selection_set(item)
            panel.history_tree.event_generate("<<TreeviewSelect>>")
            tk_root.update()
            assert panel.rerun_btn.instate(["!disabled"]) is enabled
            panel._on_rerun_with_tweaks()
        assert window.video_workflow_tab.opened == ["job-1"]
        assert "completed video job" in panel.replay_status_var.get()
    finally:
        panel.destroy()
