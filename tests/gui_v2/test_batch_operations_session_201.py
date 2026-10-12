"""PR-BATCH-OPS-201: toolkit-neutral Batches session (no Tk) over a real service and temporary SQLite."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pytest

from src.gui.view_contracts.batch_operations_contract import BatchOperationsSession, BatchViewHooks
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.queue.batch_membership import BatchKey, BatchKind
from src.queue.failure_triage import TriageCategory
from src.queue.job_model import JobStatus
from tests.helpers.batch_ops_201 import (
    admit,
    image_file,
    make_stack,
    review_njr,
    settle_fifo,
    status_of,
    video_njr,
)

VID = BatchKey(BatchKind.VIDEO_WORKFLOW, "vid")
REV = BatchKey(BatchKind.REVIEW, "rev")


def _evidence(**fields):
    return {"success": False, "error": "boom", "metadata": {"failure_evidence": {
        "contract": "webui_failure_evidence/1", "stage": "txt2img", **fields}}}


class ManualRunner:
    """Holds worker/completion pairs so a test decides when each runs and in which order they land."""

    def __init__(self) -> None:
        self.pending: list[tuple[str, object, object]] = []

    def start(self, name, work, on_done):
        self.pending.append((name, work, on_done))

    def run(self, index: int = 0) -> tuple[WorkOutcome, object]:
        _name, work, on_done = self.pending.pop(index)
        try:
            outcome = work()
        except BaseException as exc:  # noqa: BLE001 - mirrors BackgroundWorkRunner
            outcome = WorkOutcome(error=str(exc) or type(exc).__name__)
        return outcome, on_done

    def drain(self) -> None:
        while self.pending:
            outcome, on_done = self.run()
            on_done(outcome)


@dataclass
class Recorder:
    cancel_answer: bool = True
    retry_answer: tuple[str, ...] | None = ()
    cancel_plans: list = field(default_factory=list)
    retry_plans: list = field(default_factory=list)
    reviewed: list = field(default_factory=list)
    folders: list = field(default_factory=list)
    bundles: list = field(default_factory=list)
    changes: int = 0
    fail_review: bool = False

    def hooks(self) -> BatchViewHooks:
        def confirm(plan):
            self.cancel_plans.append(plan)
            return self.cancel_answer

        def review(plan):
            self.retry_plans.append(plan)
            return self.retry_answer

        def open_review(paths):
            if self.fail_review:
                raise RuntimeError("Review tab is not available")
            self.reviewed.append(paths)
            return len(paths)

        return BatchViewHooks(confirm_cancel=confirm, review_retry=review, open_in_review=open_review,
                              open_folder=self.folders.append, open_movie_clips=self.bundles.append)


@pytest.fixture
def world(tmp_path):
    stack = make_stack(tmp_path)
    admit(stack, [video_njr(f"v{i:02d}", "vid", i, 10) for i in range(10)])
    admit(stack, [review_njr(f"r{i}", "rev", source_count=6) for i in range(6)])
    # v00 ok, v01 ok, v02 FAILED (unavailable), v03 ok, v04 FAILED (outcome unknown); v05.. stay queued.
    settle_fifo(stack, {2: "failed", 4: "failed"}, count=5, results={
        2: _evidence(error_code="connection_error", webui_unavailable=True),
        4: _evidence(error_code="outcome_unknown", request_may_have_executed=True)})
    return stack


def make_session(world, runner=None, recorder=None):
    recorder = recorder or Recorder()
    runner = runner or ManualRunner()

    def changed():
        recorder.changes += 1

    session = BatchOperationsSession(service=world.operations, runner=runner, hooks=recorder.hooks(),
                                     on_change=changed)
    return session, runner, recorder


def loaded(world, key=VID, **kwargs):
    session, runner, recorder = make_session(world, **kwargs)
    session.refresh()
    runner.drain()
    session.select_batch(key)
    runner.drain()
    return session, runner, recorder


# ------------------------------------------------------------------ threading (31)


def test_reads_run_off_the_ui_thread_and_completions_land_on_it(world):
    ui_queue: list = []
    seen: dict[str, int] = {}
    real = world.operations.refresh

    def traced(key=None):
        seen["worker"] = threading.get_ident()
        return real(key)

    world.operations.refresh = traced
    threads: list[threading.Thread] = []

    def spawn(name, target):
        thread = threading.Thread(target=target, name=name)
        threads.append(thread)
        thread.start()

    runner = BackgroundWorkRunner(spawn=spawn, dispatch=ui_queue.append)
    session, _, recorder = make_session(world, runner=runner)
    callers: list[int] = []
    session._on_change = lambda: callers.append(threading.get_ident())
    assert session.refresh()
    for thread in threads:
        thread.join(10)
    assert seen["worker"] != threading.get_ident()  # the repository scan never ran on the UI thread
    assert session.snapshot is None  # nothing applied until the UI thread drains its queue
    for callback in ui_queue:
        callback()
    assert session.snapshot is not None and set(callers) == {threading.get_ident()}


# ------------------------------------------------------------------ projections follow persisted state (26)


def test_progress_rows_and_summary_follow_the_repository(world):
    session, runner, _ = loaded(world)
    assert {row.state for row in session.batch_rows()} == {"Waiting"}
    assert "Queued 5 - Running 0 - Completed 3 - Failed 2 - Cancelled 0" in session.summary_text()
    assert [row.status for row in session.job_rows()][:5] == [
        "COMPLETED", "COMPLETED", "FAILED", "COMPLETED", "FAILED"]
    settle_fifo(world, count=5)  # the five remaining video jobs finish
    session.refresh()
    runner.drain()
    assert "Queued 0 - Running 0 - Completed 8 - Failed 2" in session.summary_text()
    assert "Completed with failures" in session.summary_text()
    assert session.batch_rows()[1].progress == "10/10 finished"


def test_status_and_failure_category_filters_combine_and_prune_hidden_selection(world):
    session, _, _ = loaded(world)
    session.set_job_selection(["v02", "v04", "v00"])
    session.set_filters(status=JobStatus.FAILED)
    assert [row.job_id for row in session.job_rows()] == ["v02", "v04"]
    assert session.selected_ids == ("v02", "v04")  # the hidden completed job leaves the selection
    session.set_filters(status=JobStatus.FAILED, category=TriageCategory.OUTCOME_UNKNOWN)
    assert [row.job_id for row in session.job_rows()] == ["v04"]
    session.set_filters(category=TriageCategory.PRE_DISPATCH_UNAVAILABLE)
    assert [row.job_id for row in session.job_rows()] == ["v02"]
    session.set_filters()
    assert len(session.job_rows()) == 10


def test_selection_survives_refresh_and_vanished_items_are_dropped(world):
    session, runner, _ = loaded(world)
    session.set_job_selection(["v02", "v04"])
    session.refresh()
    runner.drain()
    assert session.selected_ids == ("v02", "v04") and session.selected_key == VID
    world.repository._connection.execute("DELETE FROM jobs WHERE job_id = 'v04'")  # retention pruned it
    session.refresh()
    runner.drain()
    assert session.selected_ids == ("v02",)
    world.repository._connection.execute("DELETE FROM jobs WHERE job_id LIKE 'v%'")
    session.refresh()
    runner.drain()
    assert session.selected_key is None and session.selected_ids == () and session.detail is None


def test_a_stale_refresh_cannot_overwrite_a_newer_selection(world):
    session, runner, _ = make_session(world)
    session.refresh()
    runner.drain()
    session.select_batch(VID)  # refresh A (for VID) in flight
    session.select_batch(REV)  # the operator moved on: refresh B (for REV) in flight
    assert len(runner.pending) == 2
    outcome_a, done_a = runner.run(0)
    outcome_b, done_b = runner.run(0)
    done_b(outcome_b)
    done_a(outcome_a)  # late and out of order
    assert session.selected_key == REV and session.detail.key == REV
    assert "Review" in session.summary_text() and len(session.job_rows()) == 6


def test_a_selection_change_during_a_read_triggers_a_follow_up_for_the_current_batch(world):
    session, runner, _ = make_session(world)
    session.refresh()
    outcome, done = runner.run()  # catalog-only read (no batch selected yet) is in flight
    session.selected_key = VID  # the operator selects while it is outstanding
    done(outcome)
    assert runner.pending  # a follow-up read was scheduled for the batch now selected
    runner.drain()
    assert session.detail.key == VID and len(session.job_rows()) == 10


# ------------------------------------------------------------------ truthful gating (§3)


def test_action_states_say_exactly_why_they_are_unavailable(world):
    session, runner, _ = make_session(world)
    assert not session.cancel_state().enabled and "Select a batch" in session.cancel_state().reason
    session.refresh()
    runner.drain()
    session.select_batch(VID)
    runner.drain()
    assert session.cancel_state().enabled and "5 job(s)" in session.cancel_state().reason
    assert "Select one or more failed" in session.retry_state().reason
    session.set_job_selection(["v00"])
    assert "None of the selected jobs failed" in session.retry_state().reason
    session.set_job_selection(["v00", "v02"])
    assert session.retry_state().enabled and "1 failed" in session.retry_state().reason
    assert session.folder_state().enabled is False  # no recorded output on these synthetic jobs
    session.busy = "Cancel"
    assert not session.cancel_state().enabled and "in progress" in session.cancel_state().reason


# ------------------------------------------------------------------ Cancel Remaining flow (§4)


def test_cancel_confirmation_states_the_count_and_declining_changes_nothing(world):
    session, runner, recorder = loaded(world)
    recorder.cancel_answer = False
    assert session.cancel_remaining()
    runner.drain()
    assert len(recorder.cancel_plans[0].target_job_ids) == 5
    assert "not confirmed" in session.message and session.busy == ""
    assert {status_of(world, f"v{i:02d}") for i in range(5, 10)} == {JobStatus.QUEUED}


def test_cancel_runs_only_after_confirmation_and_then_reloads_from_the_repository(world):
    session, runner, recorder = loaded(world)
    assert session.cancel_remaining()
    assert not session.cancel_remaining()  # a second click while busy is refused
    runner.drain()
    assert session.detail.counts.cancelled == 5 and session.detail.counts.queued == 0
    assert {status_of(world, f"r{i}") for i in range(6)} == {JobStatus.QUEUED}  # other batch untouched


def test_a_job_started_between_confirmation_and_cancel_is_reported_not_cancelled(world):
    session, runner, recorder = loaded(world)
    session.cancel_remaining()
    outcome, done = runner.run()
    world.queue.claim_next_job()  # the runner claims v05 while the confirmation dialog is open
    done(outcome)
    runner.drain()
    assert status_of(world, "v05") is JobStatus.RUNNING
    assert session.detail.counts.running == 1 and session.detail.counts.cancelled == 4


# ------------------------------------------------------------------ Retry Selected Failed flow (§5)


def test_retry_requires_the_specific_acknowledgement_and_cannot_be_clicked_twice(world):
    session, runner, recorder = loaded(world)
    session.set_job_selection(["v02", "v04"])
    recorder.retry_answer = ()  # the dialog is accepted WITHOUT acknowledging the unknown outcome
    assert session.retry_selected()
    assert not session.retry_selected()  # busy
    runner.drain()
    plan = recorder.retry_plans[0]
    assert [i.job_id for i in plan.acknowledgements] == ["v04"]
    assert "Acknowledgement required" in session.message
    assert world.repository.count() == 16  # nothing was admitted
    recorder.retry_answer = ("v04",)
    session.set_job_selection(["v02", "v04"])
    assert session.retry_selected()
    runner.drain()
    assert world.repository.count() == 18 and "Admitted 2 new retry job(s)" in session.message
    assert status_of(world, "v02") is JobStatus.FAILED and status_of(world, "v04") is JobStatus.FAILED


def test_a_duplicate_completion_delivery_cannot_submit_a_second_time(world):
    session, runner, recorder = loaded(world)
    session.set_job_selection(["v02"])
    recorder.retry_answer = ()
    session.retry_selected()
    outcome, done = runner.run()
    done(outcome)  # preflight delivered: the dialog hook ran and the submit worker is queued
    done(outcome)  # the same completion delivered again (stale / duplicate callback)
    assert len(recorder.retry_plans) == 1 and len(runner.pending) == 1
    runner.drain()
    assert world.repository.count() == 17  # exactly one new job


def test_an_ineligible_selection_is_shown_and_never_submitted(world):
    session, runner, recorder = loaded(world)
    session.set_job_selection(["v00", "v02"])
    recorder.retry_answer = ()  # even a confirming dialog cannot submit an ineligible plan
    session.retry_selected()
    runner.drain()
    assert not recorder.retry_plans[0].submittable
    assert "not submitted" in session.message and world.repository.count() == 16


# ------------------------------------------------------------------ outputs (§7)


def _completed_image_jobs(world, tmp_path, count=3):
    files = [image_file(tmp_path / "res" / f"i{i}.png", i) for i in range(count)]
    admit(world, [review_njr(f"o{i}", "out", source_count=count) for i in range(count)])
    claimed = []
    for _ in range(100):  # drain the unrelated queue first, then these
        job = world.queue.claim_next_job()
        if job is None:
            break
        claimed.append(job.job_id)
        index = int(job.job_id[1:]) if job.job_id.startswith("o") else None
        result = ({"success": True, "variants": [{"stage": "img2img", "path": str(files[index])}]}
                  if index is not None else {"success": True, "variants": []})
        world.queue.mark_completed(job.job_id, result)
    return files


def test_open_in_review_receives_the_intended_images_in_selection_order(world, tmp_path):
    files = _completed_image_jobs(world, tmp_path)
    session, runner, recorder = loaded(world, key=BatchKey(BatchKind.REVIEW, "out"))
    session.set_job_selection(["o2", "o0"])
    assert session.review_state().enabled
    assert session.open_outputs("review")
    runner.drain()
    assert recorder.reviewed == [(str(files[2]), str(files[0]))]
    assert "Opened 2 image(s) in Review" in session.message


def test_missing_outputs_are_reported_never_handed_off(world, tmp_path):
    files = _completed_image_jobs(world, tmp_path)
    session, runner, recorder = loaded(world, key=BatchKey(BatchKind.REVIEW, "out"))
    files[1].unlink()
    session.set_job_selection(["o1"])
    session.refresh()
    runner.drain()
    assert not session.review_state().enabled  # the refresh verified the file is gone
    assert "no recorded image" in session.review_state().reason
    session.set_job_selection(["o0", "o1"])
    session.open_outputs("review")
    runner.drain()
    assert recorder.reviewed == [(str(files[0]),)] and "missing or unreadable" in session.message


def test_video_outputs_use_folder_and_movie_clips_handoffs(world, tmp_path):
    clip = tmp_path / "clips" / "x.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    world.queue.claim_next_job()  # the next queued video job (v05)
    world.queue.mark_completed("v05", {"success": True, "variants": [], "metadata": {
        "video_primary_artifact": {"primary_path": str(clip), "output_paths": [str(clip)],
                                   "stage": "video_workflow", "artifact_type": "video"}}})
    session, runner, recorder = loaded(world)
    session.set_job_selection(["v05"])
    assert session.movie_clips_state().enabled and session.folder_state().enabled
    session.open_outputs("movie_clips")
    runner.drain()
    assert recorder.bundles[0]["primary_path"] == str(clip) and recorder.bundles[0]["video_paths"] == [str(clip)]
    session.open_outputs("folder")
    runner.drain()
    assert recorder.folders == [str(clip.parent)]


def test_a_failing_handoff_is_reported_and_leaves_the_session_usable(world, tmp_path):
    _completed_image_jobs(world, tmp_path)
    session, runner, recorder = loaded(world, key=BatchKey(BatchKind.REVIEW, "out"))
    recorder.fail_review = True
    session.set_job_selection(["o0"])
    session.open_outputs("review")
    runner.drain()
    assert "Review tab is not available" in session.message and session.busy == ""
    assert session.open_outputs("review")  # still usable


# ------------------------------------------------------------------ lifecycle (32)


def test_completions_after_close_are_harmless(world):
    session, runner, recorder = make_session(world)
    session.refresh()
    outcome, done = runner.run()
    changes = recorder.changes
    session.close()
    done(outcome)  # the widget is gone; the worker still reports back
    assert session.snapshot is None and recorder.changes == changes
    assert session.refresh() is False


def test_a_worker_error_is_shown_and_keeps_the_previous_view(world):
    session, runner, _ = loaded(world)
    before = session.job_rows()
    world.operations.refresh = lambda key=None: (_ for _ in ()).throw(RuntimeError("database is locked"))
    session.refresh()
    runner.drain()
    assert "Refresh failed: database is locked" in session.message and session.job_rows() == before
