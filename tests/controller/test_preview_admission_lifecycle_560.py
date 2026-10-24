"""PR-GUI-UX-560 repair: an in-flight Preview can never contradict what Add to Queue / Run / Run Now queued.

Deterministic: the background Preview build is blocked on an Event, and each compile of the unseeded random Matrix
draws from a generator with a known, different seed (no sleeps, no reliance on chance).
"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.contracts import PreviewRequest
from src.controller.app_controller import AppController
from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.controller.app_controller_services.runtime_projection_coordinator import (
    RuntimeProjectionCoordinator,
)
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.pipeline.matrix_expansion_plan import MatrixExpansionPlan
from src.pipeline.njr_core_v26 import NormalizedJobRecord
from tests.controller.test_matrix_preview_admission_560 import Harness, _matrix

EVENT_TIMEOUT = 30.0  # a failure bound, never a pacing delay


def _selection(records: list[NormalizedJobRecord]) -> list[tuple[tuple[str, Any], ...]]:
    return [tuple(sorted(dict(r.matrix_slot_values).items())) for r in records]


@pytest.fixture
def distinct_samples(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Every unseeded compile draws from the next known seed, so the Nth compile is reproducible and the first two differ."""
    seeds = iter([1, 2, 3, 4, 5, 6])
    used: list[int] = []

    def make_rng(self: MatrixExpansionPlan) -> random.Random:
        seed = next(seeds)
        used.append(seed)
        return random.Random(seed)

    monkeypatch.setattr(MatrixExpansionPlan, "make_rng", make_rng)
    yield used


class InFlightPreview:
    """A real RuntimeProjectionCoordinator + sink whose single background Preview build is held on an Event."""

    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.built: list[NormalizedJobRecord] = []
        self.sink = AppStateProjectionSink(harness.app_state)
        self.coordinator = RuntimeProjectionCoordinator(
            sink=self.sink,
            background_tasks=BackgroundTaskCoordinator(),
            build_queue_projection=lambda: ([], []),
            load_history_entries=lambda _limit: [],
            summarize_running_job=lambda _job: None,
        )

    def _build(self, request: PreviewRequest) -> list[NormalizedJobRecord]:
        self.started.set()
        assert self.release.wait(EVENT_TIMEOUT), "the held Preview build was never released"
        self.built = self.harness.builder.build_jobs(list(request.pack_entries))
        return self.built

    def begin(self) -> None:
        """What the Pipeline tab does when the draft changes: invalidate, then rebuild in the background."""
        state = self.harness.app_state
        state.add_packs_to_job_draft([self.harness.entry()])
        request = PreviewRequest(
            pack_entries=tuple(state.job_draft.packs), preview_revision=state.preview_revision
        )
        self.coordinator.publish_preview_refresh(
            request, build_preview_jobs=self._build, on_complete=lambda *_: self.finished.set()
        )
        assert self.started.wait(EVENT_TIMEOUT)

    def finish(self) -> None:
        self.release.set()
        assert self.finished.wait(EVENT_TIMEOUT), "the held Preview build never completed"


def _run_now(harness: Harness) -> Callable[[], Any]:
    return lambda: harness.controller._submit_preview_jobs_for_run(  # noqa: SLF001
        run_mode="queue", source="run_now_button", prompt_source="pack", prompt_pack_id=None
    )


def _run(harness: Harness) -> Callable[[], Any]:
    return lambda: harness.controller._submit_preview_jobs_for_run(  # noqa: SLF001
        run_mode="queue", source="run_button", prompt_source="pack", prompt_pack_id=None
    )


def _add_to_queue_draft(harness: Harness) -> Callable[[], Any]:
    return lambda: harness.controller.enqueue_draft_jobs(run_config={"run_mode": "queue"})


def _add_to_queue_direct(harness: Harness) -> Callable[[], Any]:
    return lambda: harness.controller.submit_preview_jobs_to_queue(source="add_to_queue_button")


def _async_run(harness: Harness) -> Callable[[], Any]:
    def submit() -> None:
        controller = object.__new__(AppController)
        controller.app_state = harness.app_state
        controller._append_log = lambda *_a, **_k: None  # noqa: SLF001
        controller._capture_stage_plan_for_tests = lambda _c: None  # noqa: SLF001
        controller._ui_dispatch = lambda callback: callback()  # noqa: SLF001
        controller._run_submission_in_progress = True  # noqa: SLF001
        prepared = SimpleNamespace(
            source="run_now_button", prompt_source="pack", run_config={"run_mode": "queue"}
        )
        controller._submit_run_to_queue_async(harness.controller, prepared, "run_now_button")  # noqa: SLF001

    return submit


SUBMISSIONS = [
    pytest.param(_run_now, id="run-now-sync"),
    pytest.param(_run, id="run-sync"),
    pytest.param(_async_run, id="run-now-async"),
    pytest.param(_add_to_queue_draft, id="add-to-queue-draft"),
    pytest.param(_add_to_queue_direct, id="add-to-queue-direct"),
]


@pytest.mark.parametrize("make_submit", SUBMISSIONS)
def test_an_in_flight_preview_cannot_publish_a_selection_that_was_not_queued(
    tmp_path: Path, distinct_samples: list[int], make_submit: Callable[[Harness], Callable[[], Any]]
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))  # unseeded
    in_flight = InFlightPreview(harness)
    in_flight.begin()  # Preview refresh outstanding; nothing accepted yet
    assert harness.app_state.preview_jobs == []

    make_submit(harness)()  # the operator presses the button while the build is still held

    queued = harness.queued()
    assert len(queued) == 3
    assert harness.compiles == 1 and distinct_samples == [1]  # exactly one admission compile

    in_flight.finish()  # the earlier build now completes with a *different* sample
    assert distinct_samples == [1, 2]
    assert _selection(in_flight.built) != _selection(queued), (
        "fixture must produce two different samples"
    )

    shown = harness.app_state.preview_jobs
    assert shown == [] or _selection(shown) == _selection(queued), (
        "the late Preview result displayed a selection that is not the one queued"
    )
    assert [r.job_id for r in harness.queued()] == [
        r.job_id for r in queued
    ]  # queue untouched by the late result


@pytest.mark.parametrize(
    "make_submit", [pytest.param(_run_now, id="run-now"), pytest.param(_async_run, id="async")]
)
def test_run_without_an_accepted_preview_presents_exactly_what_it_queued(
    tmp_path: Path, distinct_samples: list[int], make_submit: Callable[[Harness], Callable[[], Any]]
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    in_flight = InFlightPreview(harness)
    in_flight.begin()

    make_submit(harness)()
    in_flight.finish()

    queued = harness.queued()
    assert [r.job_id for r in harness.app_state.preview_jobs] == [r.job_id for r in queued]
    assert _selection(harness.app_state.preview_jobs) == _selection(queued)


def test_a_seeded_matrix_keeps_its_selection_through_the_same_race(tmp_path: Path) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3, sample_seed=77))
    in_flight = InFlightPreview(harness)
    in_flight.begin()

    _run_now(harness)()
    in_flight.finish()

    queued = harness.queued()
    assert _selection(in_flight.built) == _selection(queued)  # a seed makes both builds agree
    shown = harness.app_state.preview_jobs
    assert shown == [] or _selection(shown) == _selection(queued)


def test_an_accepted_preview_is_submitted_exactly_and_a_later_refresh_cannot_replace_it(
    tmp_path: Path, distinct_samples: list[int]
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    accepted = harness.accept_preview()
    assert distinct_samples == [1]

    _run_now(harness)()

    assert distinct_samples == [1]  # no second compile
    assert [r.to_dict()["job_id"] for r in harness.queued()] == [r.job_id for r in accepted]
    assert _selection(harness.queued()) == _selection(accepted)


def test_a_revision_change_after_admission_discards_the_presented_records(
    tmp_path: Path, distinct_samples: list[int]
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    state = harness.app_state
    state.add_packs_to_job_draft([harness.entry()])

    accepted, revision = state.claim_preview_for_admission()
    assert accepted == []
    records = harness._compile()  # noqa: SLF001
    state.add_packs_to_job_draft(
        [harness.entry(row=1)]
    )  # the draft changes while the admission compile runs

    assert state.accept_preview_result(records, revision=revision) is False
    assert state.preview_jobs == []


def test_claiming_supersedes_an_older_build_and_presenting_needs_the_claimed_revision(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    state = harness.app_state
    state.add_packs_to_job_draft([harness.entry()])
    older = state.preview_revision

    accepted, claimed = state.claim_preview_for_admission()

    assert accepted == [] and claimed == older + 1
    stale = harness.builder.build_jobs(list(state.job_draft.packs))
    assert (
        state.accept_preview_result(stale, revision=older) is False
    )  # the superseded build is discarded
    assert state.preview_jobs == []
    assert state.accept_preview_result(stale, revision=claimed) is True
    assert state.preview_jobs == stale
    # An accepted Preview is returned as-is and is never re-claimed.
    again, revision = state.claim_preview_for_admission()
    assert again == stale and revision == claimed
