"""PR-GUI-UX-560 final repair: a compile that the draft outran can never be queued, presented, or clear newer edits.

Admission linearization point: the revision-checked publish (``AppStateV2.accept_preview_result``) that follows the
admission compile. Before it, a superseded compile is refused (``PreviewSupersededError``) and nothing reaches
``JobService``; after it, the records are an admitted submission and later edits only affect the next draft.

Deterministic: Events and Barriers only, no sleeps. The held compile snapshots the draft when it starts (as the real
``build_preview_request`` does) and builds from that snapshot after it is released.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.pipeline_controller_services.preview_admission import PreviewSupersededError
from src.pipeline.matrix_expansion_plan import plan_matrix_expansion
from src.pipeline.njr_core_v26 import NormalizedJobRecord
from tests.controller.test_matrix_preview_admission_560 import Harness, _matrix
from tests.helpers.job_helpers import make_test_njr

EVENT_TIMEOUT = 30.0  # a failure bound, never pacing


def _selection(records: list[NormalizedJobRecord]) -> list[tuple[tuple[str, Any], ...]]:
    return [tuple(sorted(dict(r.matrix_slot_values).items())) for r in records]


class HeldCompile:
    """``get_preview_jobs`` that snapshots the draft, announces itself, and builds only once released."""

    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self) -> list[NormalizedJobRecord]:
        self.calls += 1
        snapshot = list(self.harness.app_state.job_draft.packs)
        self.entered.set()
        assert self.release.wait(EVENT_TIMEOUT), "the held compile was never released"
        return self.harness.builder.build_jobs(snapshot)


class Submission:
    """Runs one submission on a worker thread so the test can edit the draft while its compile is held."""

    def __init__(self, action: Callable[[], Any]) -> None:
        self.result: Any = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(action,), daemon=True)

    def _run(self, action: Callable[[], Any]) -> None:
        try:
            self.result = action()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            self.error = exc

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join(EVENT_TIMEOUT)
        assert not self._thread.is_alive(), "the submission never finished"


def _app_controller(harness: Harness, logs: list[str]) -> AppController:
    controller = object.__new__(AppController)
    controller.app_state = harness.app_state
    controller._append_log = lambda message, *_a, **_k: logs.append(str(message))  # noqa: SLF001
    controller._capture_stage_plan_for_tests = lambda _c: None  # noqa: SLF001
    controller._ui_dispatch = lambda callback: callback()  # noqa: SLF001
    controller._run_submission_in_progress = True  # noqa: SLF001
    controller._queue_submit_in_progress = True  # noqa: SLF001
    return controller


def _prepared(source: str) -> SimpleNamespace:
    return SimpleNamespace(source=source, prompt_source="pack", run_config={"run_mode": "queue"})


# ---- the fenced paths: (id, factory(harness, logs) -> action) ------------------------------------------------


def _sync_run(source: str) -> Callable[[Harness, list[str]], Callable[[], Any]]:
    def build(harness: Harness, _logs: list[str]) -> Callable[[], Any]:
        errors: list[Exception] = []
        harness.errors = errors  # type: ignore[attr-defined]
        return lambda: harness.controller._submit_preview_jobs_for_run(  # noqa: SLF001
            run_mode="queue",
            source=source,
            prompt_source="pack",
            prompt_pack_id=None,
            on_error=errors.append,
        )

    return build


def _enqueue_draft(harness: Harness, _logs: list[str]) -> Callable[[], Any]:
    return lambda: harness.controller.enqueue_draft_jobs(run_config={"run_mode": "queue"})


def _direct(harness: Harness, _logs: list[str]) -> Callable[[], Any]:
    return lambda: harness.controller.submit_preview_jobs_to_queue(source="add_to_queue_button")


def _async_run(harness: Harness, logs: list[str]) -> Callable[[], Any]:
    controller = _app_controller(harness, logs)
    return lambda: controller._submit_run_to_queue_async(  # noqa: SLF001
        harness.controller, _prepared("run_now_button"), "run_now_button"
    )


def _async_add(harness: Harness, logs: list[str]) -> Callable[[], Any]:
    controller = _app_controller(harness, logs)
    return lambda: controller._submit_preview_jobs_to_queue_async(  # noqa: SLF001
        harness.controller, [], {"run_mode": "queue"}, "gui"
    )


FENCED = [
    pytest.param(_sync_run("run_button"), id="run-sync"),
    pytest.param(_sync_run("run_now_button"), id="run-now-sync"),
    pytest.param(_enqueue_draft, id="add-to-queue-draft"),
    pytest.param(_direct, id="add-to-queue-direct"),
    pytest.param(_async_run, id="run-now-async"),
    pytest.param(_async_add, id="add-to-queue-async"),
]


@pytest.mark.parametrize("make_action", FENCED)
def test_a_compile_the_draft_outran_is_never_queued_presented_or_allowed_to_clear_the_new_draft(
    tmp_path: Path, make_action: Callable[[Harness, list[str]], Callable[[], Any]]
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))  # unseeded
    state = harness.app_state
    state.add_packs_to_job_draft([harness.entry()])  # draft A, no Preview accepted
    held = HeldCompile(harness)
    harness.controller.get_preview_jobs = held  # type: ignore[method-assign]
    logs: list[str] = []
    submission = Submission(make_action(harness, logs))
    submission.start()
    assert held.entered.wait(EVENT_TIMEOUT)

    state.add_packs_to_job_draft([harness.entry(row=1)])  # the operator adds pack B: draft A+B
    revision = state.preview_revision
    held.release.set()
    submission.join()

    assert harness.queued() == [], "the obsolete compile reached the queue"
    assert state.preview_jobs == [], "the obsolete compile was presented as the Preview"
    assert len(state.job_draft.packs) == 2, "the newer draft was cleared"
    assert state.preview_revision == revision
    assert held.calls == 1, "a superseded compile must not be retried or re-sampled"
    surfaced = [str(e) for e in getattr(harness, "errors", [])] + [str(submission.error)] + logs
    assert any("nothing was queued" in text or "not submitted" in text for text in surfaced), (
        surfaced
    )


def test_the_sync_run_reports_the_refusal_to_its_caller(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    harness.app_state.add_packs_to_job_draft([harness.entry()])
    held = HeldCompile(harness)
    harness.controller.get_preview_jobs = held  # type: ignore[method-assign]
    errors: list[Exception] = []
    submission = Submission(
        lambda: harness.controller._submit_preview_jobs_for_run(  # noqa: SLF001
            run_mode="queue",
            source="run_button",
            prompt_source="pack",
            prompt_pack_id=None,
            on_error=errors.append,
        )
    )
    submission.start()
    assert held.entered.wait(EVENT_TIMEOUT)
    harness.app_state.add_packs_to_job_draft([harness.entry(row=1)])
    held.release.set()
    submission.join()

    assert submission.result is False
    assert len(errors) == 1 and isinstance(errors[0], PreviewSupersededError)
    assert "Review the refreshed Preview and submit again" in str(errors[0])


def test_a_later_submission_after_the_refusal_compiles_the_new_draft_once(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3, sample_seed=11))
    state = harness.app_state
    state.add_packs_to_job_draft([harness.entry()])
    held = HeldCompile(harness)
    harness.controller.get_preview_jobs = held  # type: ignore[method-assign]
    first = Submission(lambda: harness.controller.enqueue_draft_jobs(run_config={}))
    first.start()
    assert held.entered.wait(EVENT_TIMEOUT)
    state.add_packs_to_job_draft([harness.entry(row=1)])
    held.release.set()
    first.join()
    assert isinstance(first.error, PreviewSupersededError) and harness.queued() == []

    harness.controller.get_preview_jobs = harness._compile  # type: ignore[method-assign]  # noqa: SLF001
    harness.compiles = 0
    assert harness.controller.enqueue_draft_jobs(run_config={}) == 6  # A+B, 3 combinations each
    plan = plan_matrix_expansion(_matrix(mode="random", limit=3, sample_seed=11))
    expected = [plan.combination_mapping(i) for i in plan.selected_indexes()]
    assert [dict(r.matrix_slot_values) for r in harness.queued()][
        :3
    ] == expected  # seeded: repeatable
    assert harness.compiles == 1
    assert (
        state.job_draft.packs == [] and state.preview_jobs == []
    )  # the normal success still clears


# ---- the interval after the commit: admitted work is not undone by the next edit -------------------------


def test_an_edit_between_the_commit_and_the_queue_handoff_is_the_next_draft_and_is_not_cleared(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3, sample_seed=4))
    state = harness.app_state
    state.add_packs_to_job_draft([harness.entry()])
    real_submit = harness.service.submit_njrs
    handoff = threading.Event()

    def submit_after_an_edit(records, policy=None):
        handoff.set()
        state.add_packs_to_job_draft(
            [harness.entry(row=1)]
        )  # after the commit, before JobService admits
        return real_submit(records, policy)

    harness.service.submit_njrs = submit_after_an_edit  # type: ignore[method-assign]

    assert harness.controller.enqueue_draft_jobs(run_config={}) == 3

    assert handoff.is_set()
    queued = harness.queued()
    assert len(queued) == 3  # the committed compile is admitted whole
    assert (
        len(state.job_draft.packs) == 2
    )  # A+B: the edit that followed is the next draft, not cleared
    assert state.preview_jobs == []
    before = [r.to_dict() for r in queued]
    state.add_packs_to_job_draft([harness.entry(row=2)])
    assert [r.to_dict() for r in harness.queued()] == before  # admitted NJRs are immutable


def test_a_failed_handoff_queues_nothing_and_leaves_the_draft_alone(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3, sample_seed=4))
    state = harness.app_state
    state.add_packs_to_job_draft([harness.entry()])

    def refuse(_records, _policy=None):
        raise ValueError("admission refused")

    harness.service.submit_njrs = refuse  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="admission refused"):
        harness.controller.enqueue_draft_jobs(run_config={})

    assert harness.queued() == []
    assert len(state.job_draft.packs) == 1  # a failure never clears the draft


# ---- accepted Preview captured by the UI before an asynchronous worker runs -----------------------------


def test_an_async_add_of_a_captured_preview_does_not_clear_a_draft_edited_before_the_worker_ran(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    state = harness.app_state
    accepted = harness.accept_preview()
    captured = list(state.preview_jobs)  # what on_add_job_to_queue_v2 captures on the UI thread
    compiles = harness.compiles
    state.add_packs_to_job_draft(
        [harness.entry(row=1)]
    )  # the operator edits before the worker runs
    logs: list[str] = []
    controller = _app_controller(harness, logs)

    controller._submit_preview_jobs_to_queue_async(  # noqa: SLF001
        harness.controller, captured, {"run_mode": "queue"}, "gui"
    )

    assert [r.job_id for r in harness.queued()] == [
        r.job_id for r in accepted
    ]  # the reviewed Preview, exactly
    assert harness.compiles == compiles  # no recompilation, no resampling
    assert len(state.job_draft.packs) == 2  # A+B survives
    assert state.preview_jobs == []
    assert any("Submitted 3 job(s)" in text for text in logs)


def test_an_async_add_of_an_unchanged_preview_still_clears_the_draft(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    state = harness.app_state
    harness.accept_preview()
    controller = _app_controller(harness, [])

    controller._submit_preview_jobs_to_queue_async(  # noqa: SLF001
        harness.controller, list(state.preview_jobs), {"run_mode": "queue"}, "gui"
    )

    assert len(harness.queued()) == 3
    assert state.job_draft.packs == [] and state.preview_jobs == []


def test_the_guarded_clear_is_one_atomic_step(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    state = harness.app_state
    admitted = harness.accept_preview()

    assert state.clear_admitted_draft([]) is False  # nothing admitted, nothing cleared
    assert (
        state.clear_admitted_draft(list(reversed(admitted))) is False
    )  # not the Preview's records
    assert len(state.job_draft.packs) == 1
    assert state.clear_admitted_draft(list(admitted)) is True
    assert state.job_draft.packs == [] and state.preview_jobs == []
    assert state.clear_admitted_draft(list(admitted)) is False  # already cleared


# ---- preservation ----------------------------------------------------------------------------------------


def test_an_accepted_preview_is_submitted_unchanged_without_claiming_or_compiling(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    accepted = harness.accept_preview()
    revision = harness.app_state.preview_revision
    compiles = harness.compiles

    assert harness.controller.submit_preview_jobs_to_queue(source="run_now_button") == 3

    assert harness.compiles == compiles
    assert harness.app_state.preview_revision == revision  # an accepted Preview is not re-claimed
    assert _selection(harness.queued()) == _selection(accepted)


def test_explicit_njr_submissions_do_not_pass_through_the_preview_fence(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    harness.app_state.add_packs_to_job_draft([harness.entry()])

    def forbid(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("an explicit NJR submission must not consult the Preview lifecycle")

    harness.app_state.claim_preview_for_admission = forbid  # type: ignore[method-assign]
    harness.app_state.accept_preview_result = forbid  # type: ignore[method-assign]
    explicit = [make_test_njr(job_id="explicit-1", prompt_source="manual", prompt_pack_id="")]

    assert harness.controller.submit_preview_jobs_to_queue(records=explicit) == 1
    assert [r.job_id for r in harness.queued()] == ["explicit-1"]
    assert len(harness.app_state.job_draft.packs) == 1  # and it does not touch the draft


def test_the_original_late_background_preview_race_stays_fixed(tmp_path: Path) -> None:
    # Covered in depth by test_preview_admission_lifecycle_560.py; this pins the invariant the fence builds on.
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    state = harness.app_state
    state.add_packs_to_job_draft([harness.entry()])
    _accepted, claimed = state.claim_preview_for_admission()
    older = claimed - 1

    assert state.accept_preview_result(harness._compile(), revision=older) is False  # noqa: SLF001
    assert state.preview_jobs == []
