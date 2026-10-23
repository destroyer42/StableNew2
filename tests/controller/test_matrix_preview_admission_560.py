"""PR-GUI-UX-560: the accepted Preview is exactly what the queue admits; Matrix is never re-sampled afterwards."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.app_controller_services.run_submission_service import QueueRunSubmissionService
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.pipeline_controller_services.preview_admission import accepted_preview_records
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.matrix_expansion_plan import plan_matrix_expansion
from src.pipeline.njr_core_v26 import NormalizedJobRecord
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller.test_job_service_unit import FakeRunner
from tests.helpers.job_helpers import make_test_njr
from tests.pipeline.test_prompt_pack_job_builder import (
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)

PROMPT = "A [[character]] in a [[location]]"
DIMENSIONS = {
    "character": ["knight", "ranger", "mage", "druid"],
    "location": ["forest", "castle", "market"],
}


def _matrix(**extra: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "slots": [{"name": n, "values": list(v)} for n, v in DIMENSIONS.items()],
        **extra,
    }


class Harness:
    """Real compiler + real AppStateV2 + real JobService over a SQLite repository."""

    def __init__(self, tmp_path: Path, matrix: dict[str, Any]) -> None:
        self.config_manager = StubConfigManager(tmp_path)
        self.pack = _write_native_pack(
            self.config_manager.packs_dir / "matrix-pack.json", text=PROMPT, matrix=matrix
        )
        self.builder = PromptPackNormalizedJobBuilder(
            config_manager=self.config_manager,
            job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
            packs_dir=self.config_manager.packs_dir,
        )
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.queue = JobQueue(repository=self.repository)
        self.service = JobService(self.queue, runner=FakeRunner(), require_normalized_records=True)
        self.app_state = AppStateV2()
        self.compiles = 0
        controller = object.__new__(PipelineController)
        controller._job_service = self.service
        controller._app_state = self.app_state
        controller._last_run_config = None
        controller._app_controller = None
        controller.can_enqueue_learning_jobs = lambda _count: (True, "")
        controller._is_queue_submission_blocked = lambda: False
        controller._sort_jobs_by_model = lambda rows: rows
        controller.get_preview_jobs = self._compile  # the only place a Matrix can be (re)sampled
        self.controller = controller

    def entry(self, row: int = 0) -> PackJobEntry:
        return PackJobEntry(
            pack_id=self.pack.name,
            pack_name="Matrix Pack",
            pack_row_index=row,
            prompt_text=PROMPT,
            config_snapshot={"randomization": {"enabled": False}},
            stage_flags={"txt2img": True},
            randomizer_metadata={"enabled": False, "max_variants": 0},
        )

    def _compile(self) -> list[NormalizedJobRecord]:
        self.compiles += 1
        return self.builder.build_jobs(list(self.app_state.job_draft.packs))

    def accept_preview(self) -> list[NormalizedJobRecord]:
        """What the Pipeline tab does: draft the pack, compile once, publish as the authoritative Preview."""
        self.app_state.add_packs_to_job_draft([self.entry()])
        records = self._compile()
        self.app_state.set_preview_jobs(records)
        return records

    def queued(self) -> list[NormalizedJobRecord]:
        return [job._normalized_record for job in self.repository.list_job_models()]


@pytest.fixture(params=["seeded", "unseeded"])
def harness(request, tmp_path: Path) -> Harness:
    extra = {"sample_seed": 99} if request.param == "seeded" else {}
    return Harness(tmp_path, _matrix(mode="random", limit=5, **extra))


def _semantic(record: NormalizedJobRecord) -> dict[str, Any]:
    """The whole envelope, except one field the repository's snapshot reader already normalizes ('' -> None)."""
    payload = record.to_dict()
    info = payload.get("provenance", {}).get("txt2img_prompt_info")
    if isinstance(info, dict):
        info.pop("global_negative_terms", None)
    return payload


def test_add_to_queue_admits_the_accepted_preview_unchanged(harness: Harness) -> None:
    preview = harness.accept_preview()
    compiles_before = harness.compiles

    submitted = harness.controller.submit_preview_jobs_to_queue(
        records=list(harness.app_state.preview_jobs)
    )

    assert submitted == len(preview) == 5
    assert harness.compiles == compiles_before  # nothing compiled at submission
    queued = harness.queued()
    assert [_semantic(r) for r in queued] == [
        _semantic(r) for r in preview
    ]  # order, Matrix values, provenance
    assert [dict(r.matrix_slot_values) for r in queued] == [
        dict(r.matrix_slot_values) for r in preview
    ]


@pytest.mark.parametrize("source", ["add_to_queue_button", "run_button", "run_now_button", "gui"])
def test_every_submission_entry_point_admits_the_accepted_preview_without_recompiling(
    harness: Harness, source: str
) -> None:
    preview = harness.accept_preview()
    compiles_before = harness.compiles

    submitted = harness.controller.submit_preview_jobs_to_queue(
        source=source
    )  # records=None: the draft path

    assert submitted == 5
    assert harness.compiles == compiles_before
    assert [_semantic(r) for r in harness.queued()] == [_semantic(r) for r in preview]


def test_run_and_run_now_use_the_job_service_and_never_execute_directly(harness: Harness) -> None:
    preview = harness.accept_preview()
    policies: list[Any] = []
    real_submit = harness.service.submit_njrs

    def spy(records, policy=None):
        policies.append(policy)
        return real_submit(records, policy)

    harness.service.submit_njrs = spy  # type: ignore[method-assign]
    harness.controller.run_njr = Mock(
        side_effect=AssertionError("fresh work must be queued, never run directly")
    )

    assert harness.controller._submit_preview_jobs_for_run(  # noqa: SLF001
        run_mode="queue", source="run_now_button", prompt_source="pack", prompt_pack_id=None
    )

    assert harness.compiles == 1  # only the Preview compile
    assert [_semantic(r) for r in harness.queued()] == [_semantic(r) for r in preview]
    assert len(policies) == 1 and policies[0].start_when_idle is True


def test_the_run_service_hands_the_accepted_preview_to_the_async_run_path(harness: Harness) -> None:
    preview = harness.accept_preview()

    records = QueueRunSubmissionService.accepted_preview_jobs(harness.app_state, harness.controller)

    assert records == preview
    assert harness.compiles == 1


def test_an_unseeded_random_matrix_would_resample_on_recompile_so_admission_must_not(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=3))
    preview = harness.accept_preview()
    seen = {tuple(sorted(dict(r.matrix_slot_values).items())) for r in preview}
    # Recompiling is a new independent sample; keep drawing until one differs (12 positions, 3 chosen).
    resamples = [
        {tuple(sorted(dict(r.matrix_slot_values).items())) for r in harness._compile()}
        for _ in range(25)  # noqa: SLF001
    ]
    assert any(sample != seen for sample in resamples), (
        "the fixture should demonstrate historical resampling"
    )

    harness.compiles = 0
    harness.controller.submit_preview_jobs_to_queue()

    assert harness.compiles == 0
    assert {tuple(sorted(dict(r.matrix_slot_values).items())) for r in harness.queued()} == seen


def test_seeded_recompile_reproduces_the_selection_but_admission_still_uses_the_preview(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, _matrix(mode="random", limit=4, sample_seed=7))
    preview = harness.accept_preview()
    plan = plan_matrix_expansion(_matrix(mode="random", limit=4, sample_seed=7))

    assert [dict(r.matrix_slot_values) for r in preview] == [
        plan.combination_mapping(i) for i in plan.selected_indexes()
    ]
    assert [dict(r.matrix_slot_values) for r in harness._compile()] == [  # noqa: SLF001
        dict(r.matrix_slot_values) for r in preview
    ]


def test_a_changed_draft_invalidates_the_accepted_preview_and_stale_records_are_never_submitted(
    harness: Harness,
) -> None:
    stale = harness.accept_preview()
    revision = harness.app_state.preview_revision

    harness.app_state.add_packs_to_job_draft([harness.entry(row=1)])  # a relevant authored change

    assert harness.app_state.preview_revision > revision
    assert harness.app_state.preview_jobs == []

    harness.compiles = 0
    harness.controller.submit_preview_jobs_to_queue()

    assert (
        harness.compiles == 1
    )  # no accepted Preview exists, so the draft is compiled exactly once
    queued = harness.queued()
    assert len(queued) == 10  # both draft rows, freshly compiled
    assert {r.job_id for r in queued}.isdisjoint({r.job_id for r in stale})


def test_saving_a_pack_the_draft_uses_invalidates_the_preview_and_announces_the_draft(
    harness: Harness,
) -> None:
    harness.accept_preview()
    notified: list[str] = []
    harness.app_state.subscribe("job_draft", lambda: notified.append("job_draft"))
    revision = harness.app_state.preview_revision

    assert (
        harness.app_state.pack_file_saved(harness.pack, packs_dir=harness.config_manager.packs_dir)
        is True
    )

    assert harness.app_state.preview_jobs == []
    assert harness.app_state.preview_revision == revision + 1
    assert "job_draft" in notified


def test_saving_an_unrelated_pack_leaves_the_preview_alone(
    harness: Harness, tmp_path: Path
) -> None:
    preview = harness.accept_preview()
    revision = harness.app_state.preview_revision

    other = tmp_path / "some-other-pack.json"
    assert (
        harness.app_state.pack_file_saved(other, packs_dir=harness.config_manager.packs_dir)
        is False
    )

    assert harness.app_state.preview_jobs == preview
    assert harness.app_state.preview_revision == revision


def test_saving_with_an_empty_draft_does_not_touch_anything(tmp_path: Path) -> None:
    state = AppStateV2()
    revision = state.preview_revision

    assert state.pack_file_saved(tmp_path / "x.json", packs_dir=tmp_path) is False
    assert state.preview_revision == revision


def test_a_stale_preview_result_is_discarded_by_the_existing_revision_guard(
    harness: Harness,
) -> None:
    from src.contracts.projections import PreviewProjection
    from src.gui.app_state_projection_sink import AppStateProjectionSink

    request_revision = harness.app_state.preview_revision
    harness.app_state.add_packs_to_job_draft([harness.entry()])
    late = tuple(harness._compile())  # noqa: SLF001  (built for the old revision)

    AppStateProjectionSink(harness.app_state).apply_preview_projection(
        PreviewProjection(1, late, request_revision, None)
    )

    assert harness.app_state.preview_jobs == []


def test_replay_reads_the_frozen_record_and_ignores_the_current_pack(harness: Harness) -> None:
    harness.accept_preview()
    harness.controller.submit_preview_jobs_to_queue()
    stored = harness.queued()[0]
    harness.compiles = 0

    # The author rewrites the Matrix after the job was queued.
    _write_native_pack(harness.pack, text=PROMPT, matrix=_matrix(mode="fanout", limit=1))
    replayed = compile_replay_intent(ReplayIntent(stored))

    assert harness.compiles == 0
    assert dict(replayed.matrix_slot_values) == dict(stored.matrix_slot_values)
    assert (
        replayed.provenance.metadata["matrix_expansion"]
        == stored.provenance.metadata["matrix_expansion"]
    )
    assert replayed.positive_prompt == stored.positive_prompt
    assert replayed.job_id != stored.job_id


def test_changing_the_pack_after_queueing_never_alters_queued_records(harness: Harness) -> None:
    harness.accept_preview()
    harness.controller.submit_preview_jobs_to_queue()
    before = [_semantic(r) for r in harness.queued()]

    _write_native_pack(
        harness.pack, text="Something else [[character]]", matrix=_matrix(mode="fanout", limit=2)
    )

    assert [_semantic(r) for r in harness.queued()] == before


def test_accepted_preview_helper_contract() -> None:
    from types import SimpleNamespace

    accepted = [make_test_njr(job_id="a", prompt_source="manual", prompt_pack_id="")]
    fresh = [make_test_njr(job_id="b", prompt_source="manual", prompt_pack_id="")]
    compile_fresh = Mock(side_effect=AssertionError("must not recompile"))

    # A real state: an accepted Preview is returned as-is; none means one compile, presented as the Preview.
    state = AppStateV2()
    state.set_preview_jobs(accepted)
    assert accepted_preview_records(state, compile_fresh) == accepted
    compile_fresh.assert_not_called()

    state.invalidate_preview()
    assert accepted_preview_records(state, lambda: fresh) == fresh
    assert state.preview_jobs == fresh

    # A state double without the Preview lifecycle keeps the plain read.
    double = SimpleNamespace(preview_jobs=list(accepted))
    assert accepted_preview_records(double, compile_fresh) == accepted
    double.preview_jobs = []
    assert accepted_preview_records(double, lambda: fresh) == fresh
    assert accepted_preview_records(None, lambda: fresh) == fresh
    assert accepted_preview_records(AppStateV2(), lambda: None) == []  # type: ignore[arg-type,return-value]


def test_app_controller_run_path_submits_the_accepted_preview_records() -> None:
    from types import SimpleNamespace

    from src.controller.app_controller import AppController

    accepted = [make_test_njr(job_id="accepted-1", prompt_source="manual", prompt_pack_id="")]
    state = AppStateV2()
    state.set_preview_jobs(accepted)
    pipeline = Mock()
    pipeline.ensure_run_submission_ready.return_value = True
    pipeline.get_preview_jobs.side_effect = AssertionError("Run Now must not recompile the Matrix")
    pipeline.submit_preview_jobs_to_queue.return_value = 1

    controller = object.__new__(AppController)
    controller.app_state = state
    controller._append_log = lambda *_args, **_kwargs: None  # noqa: SLF001
    controller._capture_stage_plan_for_tests = lambda _controller: None  # noqa: SLF001
    controller._ui_dispatch = lambda callback: callback()  # noqa: SLF001
    controller._run_submission_in_progress = True  # noqa: SLF001
    prepared = SimpleNamespace(
        source="run_now_button", prompt_source="pack", run_config={"run_mode": "queue"}
    )

    controller._submit_run_to_queue_async(pipeline, prepared, "run_now_button")  # noqa: SLF001

    pipeline.submit_preview_jobs_to_queue.assert_called_once()
    assert pipeline.submit_preview_jobs_to_queue.call_args.kwargs["records"] == accepted
    assert pipeline.submit_preview_jobs_to_queue.call_args.kwargs["source"] == "run_now_button"


def test_a_failing_compile_with_no_accepted_preview_queues_nothing_and_reports(
    harness: Harness,
) -> None:
    harness.controller.get_preview_jobs = Mock(side_effect=RuntimeError("compile failed"))
    errors: list[Exception] = []

    ok = harness.controller._submit_preview_jobs_for_run(  # noqa: SLF001
        run_mode="queue",
        source="run_button",
        prompt_source="pack",
        prompt_pack_id=None,
        on_error=errors.append,
    )

    assert ok is False
    assert [str(error) for error in errors] == ["compile failed"]
    assert harness.queued() == []


def test_an_empty_preview_and_an_empty_compile_submit_nothing(harness: Harness) -> None:
    harness.controller.get_preview_jobs = lambda: []

    assert harness.controller.submit_preview_jobs_to_queue() == 0
    assert harness.queued() == []
