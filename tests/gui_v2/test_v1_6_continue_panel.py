"""V1-6: the "Continue a clip" task of the Video Workflow tab.

Real Tk widgets and the real Storyboard service over the PR-VID-STORY-380 fake jobs; the worker runs inline.  No GPU,
Comfy process, FFmpeg, model or network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.storyboard_submission_service import StoryboardSubmissionService
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.video_workflow_continue_v2 import (
    CHOOSE_A_CLIP,
    ContinueClipHost,
    apply_continuation,
)
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.queue.job_model import JobStatus
from src.video.sequence_ledger import sha256_of
from src.video.storyboard_tree_store import StoryboardTreeStore
from src.video.workflow_catalog_wan_a14b import WAN_A14B_ID
from tests.helpers.make_video_313 import make_app, make_window
from tests.helpers.storyboard_380 import (
    REG,
    FakeRepository,
    builder,
    frames_out_job,
    refused_job,
)

pytestmark = pytest.mark.gui


class _Repository(FakeRepository):
    def list_recent_jobs(self, *, limit: int = 50, statuses: Any = None) -> list[Any]:
        return [SimpleNamespace(job_id=job_id) for job_id in reversed(list(self.jobs))][:limit]


class _Jobs:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.njrs: list[Any] = []

    def submit_njrs(self, njrs: list[Any], policy: Any) -> list[str]:
        self.njrs.extend(njrs)
        return [self.repository.add(njr, status=JobStatus.QUEUED) for njr in njrs]


@pytest.fixture
def env(tk_root, tmp_path):
    app, controller, _service = make_app(tmp_path)
    controller.rife_available = lambda: False
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)

    source, job_id, frames = frames_out_job(tmp_path, count=81)
    repository = _Repository(jobs=dict(source.jobs), files=dict(source.files))
    jobs = _Jobs(repository)
    service = StoryboardSubmissionService(
        njr_builder=builder(tmp_path),
        workflow_registry=REG,
        job_service=lambda: jobs,
        repository=lambda: repository,
        store=StoryboardTreeStore(tmp_path / "trees"),
        output_root=lambda: str(tmp_path),
        draw_seed=lambda: 4242,
    )
    tab._continue_host = ContinueClipHost(
        tab,
        service=lambda: service,
        on_opened=lambda opening: apply_continuation(tab, opening),
        on_queued=tab._on_continue_queued,
        on_refused=tab._fail,
        on_status=tab.status_var.set,
        runner=BackgroundWorkRunner(spawn=lambda _name, target: target(), dispatch=lambda fn: fn()),
    )
    yield SimpleNamespace(
        tab=tab,
        service=service,
        repository=repository,
        jobs=jobs,
        job_id=job_id,
        frames=frames,
        tmp=tmp_path,
    )
    tab.destroy()


def _stage(njr: Any) -> dict[str, Any]:
    return dict(njr.stage_chain[0].extra)


def test_continuing_a_clip_fills_the_form_and_queues_one_take(env):
    tab = env.tab
    tab.open_continue(env.job_id)

    assert tab.current_task() == "continue_clip" and tab.continue_panel.winfo_manager()
    assert tab.workflow_var.get() == WAN_A14B_ID
    assert tab.prompt_text.get("1.0", "end").strip() == "the person waves"
    assert tab.source_image_var.get() == str(env.frames[-1])
    assert tab.continue_panel.frame_text_var.get() == "frame 81 of 81 (last)"
    assert "a new Storyboard" in tab.continue_panel.clip_var.get()
    assert not tab.continue_panel.prompt_only_button.winfo_manager()
    assert env.service.store.list_trees() == []  # opening writes nothing

    tab.prompt_text.delete("1.0", "end")
    tab.prompt_text.insert("1.0", "she sits down")
    tab._on_submit()

    (njr,) = env.jobs.njrs
    assert (_stage(njr)["prompt"], _stage(njr)["frame_count"]) == ("she sits down", 81)
    assert sha256_of(Path(njr.input_image_paths[0])) == sha256_of(env.frames[-1])
    assert "in Storyboard 'Continued: she sits down'" in tab.status_var.get()


def test_the_chosen_frame_and_length_reach_the_take(env):
    tab = env.tab
    tab.open_continue(env.job_id)
    tab.continue_panel._on_scale("9")
    assert tab.source_image_var.get() == str(env.frames[9])
    tab.motion_intent_panel.enter_duration("3")

    tab._on_submit()
    tab._on_submit()  # again: the same Storyboard, not a second one

    first, second = env.jobs.njrs
    assert _stage(first)["frame_count"] == 49
    assert sha256_of(Path(first.input_image_paths[0])) == sha256_of(env.frames[9])
    ((storyboard_id, _title, _updated),) = env.service.store.list_trees()
    takes = env.service.store.load(storyboard_id).takes
    assert [take.handoff_index for take in takes] == [9, 9]
    assert second.job_id != first.job_id


def test_a_clip_that_cannot_be_a_take_offers_prompt_only_motion(env):
    tab = env.tab
    driven, driven_id = refused_job(env.tmp, "driving_video")
    env.repository.jobs.update(driven.jobs)
    env.repository.jobs[driven_id].result = env.repository.jobs[env.job_id].result

    tab.open_continue(driven_id)
    assert "driving video" in tab.continue_panel.clip_var.get()
    assert tab.continue_panel.prompt_only_button.winfo_manager()
    tab._on_submit()
    assert env.jobs.njrs == [] and "prompt-only" in tab.status_var.get()

    tab.continue_panel.prompt_only_button.invoke()
    assert tab.current_task() == "animate"
    assert tab.source_image_var.get() == str(env.frames[-1])


def test_end_on_a_picture_starts_from_the_last_frame(env):
    tab = env.tab
    tab.open_continue(env.job_id)
    tab.continue_panel.end_picture_button.invoke()

    assert tab.current_task() == "between_images" and tab.end_image_frame.winfo_manager()
    assert tab.source_image_var.get() == str(env.frames[-1])
    assert not tab.continue_panel.winfo_manager()


def test_choosing_the_task_alone_asks_for_a_clip_and_another_image_leaves_it(env):
    tab = env.tab
    assert tab.select_task("continue_clip")
    assert tab.continue_panel.clip_var.get() == CHOOSE_A_CLIP
    tab._on_submit()
    assert env.jobs.njrs == [] and CHOOSE_A_CLIP in tab.status_var.get()

    tab.set_source_image_path(str(env.frames[0]))
    assert tab.current_task() == "animate"


def test_another_engine_is_refused_rather_than_ignored(env):
    tab = env.tab
    tab.open_continue(env.job_id)
    other = next(value for value in tab._workflow_map if value != WAN_A14B_ID and "ti2v" in value)
    tab.workflow_var.set(other)
    assert tab.current_task() == "continue_clip"
    tab._on_submit()
    assert env.jobs.njrs == [] and "keeps the clip's engine" in tab.status_var.get()
