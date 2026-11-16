"""PR-REVIEW-LIFECYCLE-621: the Tk-free Review workspace session (states, filters, decisions, scope, staleness).

Real Learning evidence file and (where lineage matters) a temporary SQLite repository; synthetic images only.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.view_contracts.edit_work_runner import EditWorkRunner
from src.gui.view_contracts.review_workspace_contract import (
    ItemState,
    ReviewWorkspaceSession,
    ViewFilter,
    item_key,
)
from src.learning.learning_record import LearningRecordWriter
from src.review.review_evidence import lookup_disposition, save_disposition
from tests.gui_v2.edit_work_helpers import ManualRegistry, manual_runner
from tests.helpers.batch_ops_201 import admit, image_file, make_stack, review_njr, settle_fifo


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(paths):
    return [(p.stat().st_size, p.stat().st_mtime_ns, _sha(p)) for p in paths]


def _inline() -> EditWorkRunner:
    return EditWorkRunner(BackgroundTaskCoordinator(run_inline=True), is_alive=lambda: True)


class Workspace:
    def __init__(self, tmp_path: Path, *, runner=None, repository=None, count=12):
        self.writer = LearningRecordWriter(tmp_path / "records.jsonl")
        self.images = [image_file(tmp_path / "set" / f"img_{i:02d}.png", i) for i in range(count)]
        self.changes = 0

        def write(path, digest, job_id, disposition):
            save_disposition(
                self.writer,
                image_path=path,
                disposition=disposition,
                artifact_sha256=digest or None,
                source_job_id=job_id,
            )

        self.session = ReviewWorkspaceSession(
            runner=runner or _inline(),
            records_path=lambda: self.writer.records_path,
            repository=lambda: repository,
            write_disposition=write,
            on_change=self._changed,
        )

    def _changed(self):
        self.changes += 1

    def key(self, index):
        return item_key(self.images[index])


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path)


def test_twelve_outputs_are_triaged_with_correct_counts_filters_and_untouched_files(workspace):
    session = workspace.session
    before = _fingerprint(workspace.images)
    session.set_items(workspace.images)
    assert session.filter_counts()[ViewFilter.TO_REVIEW] == 12

    plan = ["retain"] * 5 + ["discard"] * 3 + ["rework"] * 4
    for index, disposition in enumerate(plan):
        assert session.decide(workspace.key(index), disposition)

    counts = session.counts()
    assert (
        counts[ItemState.RETAINED],
        counts[ItemState.ARCHIVED],
        counts[ItemState.REWORK_MARKED],
    ) == (5, 3, 4)
    assert counts[ItemState.TO_REVIEW] == 0
    assert session.counts_text() == "To review 0  Retained 5  Re-work 4  Archived 3"
    assert len(session.visible_items()) == 9  # the default view hides what was archived
    session.set_filter(ViewFilter.ARCHIVED)
    assert [item.name for item in session.visible_items()] == [
        "img_05.png",
        "img_06.png",
        "img_07.png",
    ]
    session.set_filter(ViewFilter.REWORK)
    assert len(session.visible_items()) == 4
    assert _fingerprint(workspace.images) == before  # no size, mtime or SHA-256 changed


def test_archive_hides_the_image_restore_returns_it_and_the_file_never_moves(workspace):
    session, image = workspace.session, workspace.images[0]
    before = _fingerprint([image])
    session.set_items(workspace.images)

    session.decide(workspace.key(0), "discard")
    assert workspace.key(0) not in {item.key for item in session.visible_items()}
    session.set_filter(ViewFilter.ARCHIVED)
    assert [item.key for item in session.visible_items()] == [workspace.key(0)]
    assert session.label_of(workspace.key(0)) == "Archived"

    session.set_filter(ViewFilter.ACTIVE)
    assert session.restore(workspace.key(0))
    assert workspace.key(0) in {item.key for item in session.visible_items()}
    assert session.state_of(workspace.key(0)) is ItemState.TO_REVIEW
    assert image.exists() and _fingerprint([image]) == before
    assert not session.restore(workspace.key(0))  # only an archived image can be restored


def test_decisions_survive_a_new_session_and_undo_records_the_earlier_decision(tmp_path):
    first = Workspace(tmp_path, count=3)
    first.session.set_items(first.images)
    first.session.decide(first.key(0), "retain")
    first.session.decide(first.key(0), "discard")
    assert first.session.undo()  # back to retained, by a new row: nothing is deleted
    assert first.session.state_of(first.key(0)) is ItemState.RETAINED
    assert first.session.undo()
    assert first.session.state_of(first.key(0)) is ItemState.TO_REVIEW
    assert not first.session.undo()
    assert len(first.writer.records_path.read_text().splitlines()) == 4

    first.session.decide(first.key(1), "rework")
    second = Workspace.__new__(Workspace)
    second.writer, second.images = first.writer, first.images
    second.session = ReviewWorkspaceSession(
        runner=_inline(), records_path=lambda: first.writer.records_path
    )
    second.session.set_items(first.images)  # a new session over the same records
    assert second.session.state_of(first.key(1)) is ItemState.REWORK_MARKED
    assert second.session.state_of(first.key(0)) is ItemState.TO_REVIEW
    assert (
        lookup_disposition(
            first.writer.records_path, first.images[1], _sha(first.images[1])
        ).disposition
        == "rework"
    )


def test_a_file_replaced_after_it_was_reviewed_is_changed_and_a_failed_write_changes_nothing(
    workspace,
):
    session = workspace.session
    session.set_items(workspace.images[:2])
    session.decide(workspace.key(0), "retain")
    image_file(workspace.images[0], 200)  # different bytes under the same path

    session.refresh()
    assert session.state_of(workspace.key(0)) is ItemState.CHANGED
    assert session.label_of(workspace.key(0)) == "Changed since reviewed"

    def refuse(*_args):
        raise OSError("disk full")

    session._write = refuse  # noqa: SLF001 - simulate the evidence store refusing the write
    assert session.decide(workspace.key(1), "retain")
    assert session.state_of(workspace.key(1)) is ItemState.TO_REVIEW
    assert "not saved" in session.message


def test_next_undecided_skips_decided_and_wraps_to_none(workspace):
    session = workspace.session
    session.set_items(workspace.images[:4])
    session.decide(workspace.key(1), "retain")
    session.decide(workspace.key(2), "retain")

    assert session.next_undecided(workspace.key(0)) == workspace.key(3)
    assert session.next_undecided(workspace.key(3)) is None
    assert session.next_undecided(None) == workspace.key(0)


def test_rework_scope_gates_single_image_tools_with_a_reason(workspace):
    session = workspace.session
    session.set_items(workspace.images[:5])
    assert not session.rework_state().enabled and "Mark" in session.rework_state().reason
    assert session.single_tool_state(workspace.key(0)).enabled  # nothing marked: the image shown

    for index in (0, 1, 2):
        session.decide(workspace.key(index), "rework")

    assert session.rework_state().enabled and "3 image(s)" in session.rework_state().reason
    gate = session.single_tool_state(workspace.key(0))
    assert not gate.enabled and "3 images are marked" in gate.reason
    assert session.single_target(workspace.key(0)) is None
    assert session.scope_line() == "Re-work: 3 image(s) will be processed"

    session.decide(workspace.key(1), "retain")
    session.decide(workspace.key(2), "retain")
    assert session.single_tool_state(workspace.key(4)).enabled
    assert session.single_target(workspace.key(4)).key == workspace.key(0)


def test_late_results_and_closed_sessions_are_dropped(tmp_path):
    registry = ManualRegistry()
    workspace = Workspace(tmp_path, runner=manual_runner(registry), count=3)
    session = workspace.session

    session.set_items(workspace.images[:2])
    session.set_items(workspace.images[2:])  # a newer set supersedes the first request
    registry.run_all()
    assert [item.name for item in session.items] == ["img_02.png"]
    assert set(session.facts) == {workspace.key(2)}

    session.close()
    session.refresh()
    assert registry.queued == []


def test_a_decision_on_an_image_with_a_pending_write_is_refused(tmp_path):
    registry = ManualRegistry()
    workspace = Workspace(tmp_path, runner=manual_runner(registry), count=2)
    session = workspace.session
    session.set_items(workspace.images)
    registry.run_all()

    assert session.decide(workspace.key(0), "retain")
    assert (
        session.state_of(workspace.key(0)) is ItemState.RETAINED
    )  # shown at once, saved by the worker
    assert not session.decide(workspace.key(0), "discard")
    assert "still being saved" in session.message
    registry.run_all()
    assert (
        lookup_disposition(workspace.writer.records_path, workspace.images[0], None).disposition
        == "retain"
    )


def test_without_evidence_the_decision_actions_are_disabled_with_a_reason(tmp_path):
    session = ReviewWorkspaceSession(runner=_inline())
    session.set_items([image_file(tmp_path / "a.png")])
    gate = session.decide_state(item_key(tmp_path / "a.png"), "retain")
    assert not gate.enabled and "Learning evidence" in gate.reason


# --- jobs are derived from the repository, never stored ---------------------------------------------------------------


def _lineage_workspace(tmp_path):
    stack = make_stack(tmp_path)
    workspace = Workspace(tmp_path, repository=stack.repository, count=3)
    return stack, workspace


def _child(job_id, source, *, digest=None, parent_job=None):
    record = review_njr(
        job_id, f"batch-{job_id}", source=source, artifact_sha256=digest, source_count=1
    )
    if parent_job:
        record = replace(record, source=replace(record.source, parent_job_id=parent_job))
    return record


def _result(output):
    return {
        "success": True,
        "artifact": {
            "stage": "img2img",
            "artifact_type": "image",
            "primary_path": str(output),
            "output_paths": [str(output)],
        },
        "variants": [],
        "metadata": {},
    }


def test_queued_failed_and_returned_states_come_from_the_repository_and_survive_restart(tmp_path):
    stack, workspace = _lineage_workspace(tmp_path)
    session = workspace.session
    session.set_items(workspace.images)
    for index in range(3):
        session.decide(workspace.key(index), "rework")
    outputs = [image_file(tmp_path / "out" / f"child_{i}.png", 100 + i) for i in range(3)]
    admit(
        stack,
        [_child(f"c{i}", workspace.images[i], digest=_sha(workspace.images[i])) for i in range(3)],
    )

    session.refresh()
    assert {session.state_of(workspace.key(i)) for i in range(3)} == {ItemState.REWORK_QUEUED}
    assert not session.rework_scope()  # already queued: not offered again
    assert "3 already queued" in session.scope_line()

    settle_fifo(
        stack,
        {1: "failed"},
        error="backend refused",
        results={0: _result(outputs[0]), 2: _result(outputs[2])},
    )
    session.refresh()
    # A finished source awaits a decision (its result is back); only the failed one is offered again.
    assert session.state_of(workspace.key(0)) is ItemState.RETURNED
    assert session.state_of(workspace.key(1)) is ItemState.REWORK_FAILED
    assert session.state_of(workspace.key(2)) is ItemState.RETURNED
    assert [item.key for item in session.rework_scope()] == [workspace.key(1)]
    rows = session.returned_rows()
    assert [
        (row.source_name, row.path.name, row.relation, row.state, row.in_set) for row in rows
    ] == [
        ("img_00.png", "child_0.png", "verified", ItemState.RETURNED, False),
        ("img_02.png", "child_2.png", "verified", ItemState.RETURNED, False),
    ]

    # A restart: a new session over the same records and repository re-derives the same states.
    reopened = stack.reopen()
    again = ReviewWorkspaceSession(
        runner=_inline(),
        records_path=lambda: workspace.writer.records_path,
        repository=lambda: reopened.repository,
    )
    again.set_items(workspace.images)
    assert [again.state_of(workspace.key(i)) for i in range(3)] == [
        ItemState.RETURNED,
        ItemState.REWORK_FAILED,
        ItemState.RETURNED,
    ]
    assert len(again.returned_rows()) == 2


def test_marking_a_returned_source_again_puts_it_back_in_scope_only_for_newer_work(tmp_path):
    stack, workspace = _lineage_workspace(tmp_path)
    session = workspace.session
    session.set_items(workspace.images[:1])
    key = workspace.key(0)
    session.decide(key, "rework")
    output = image_file(tmp_path / "out" / "child.png", 160)
    admit(stack, [_child("c0", workspace.images[0], digest=_sha(workspace.images[0]))])
    settle_fifo(stack, result=_result(output))
    session.refresh()
    assert session.state_of(key) is ItemState.RETURNED and not session.rework_scope()

    session.decide(key, "rework")  # a newer mark: the finished job belongs to the earlier one
    session.refresh()
    assert session.state_of(key) is ItemState.REWORK_MARKED
    assert [item.key for item in session.rework_scope()] == [key]


def test_returned_output_added_to_the_set_is_returned_until_it_is_decided(tmp_path):
    stack, workspace = _lineage_workspace(tmp_path)
    session = workspace.session
    session.set_items(workspace.images[:1])
    output = image_file(tmp_path / "out" / "child.png", 150)
    admit(stack, [_child("c0", workspace.images[0], digest=_sha(workspace.images[0]))])
    settle_fifo(stack, result=_result(output))

    (key,) = session.add_items([output], after=workspace.key(0))
    assert [item.name for item in session.items] == ["img_00.png", "child.png"]
    assert session.state_of(key) is ItemState.RETURNED
    assert session.next_undecided(workspace.key(0)) == key

    session.decide(key, "retain")
    assert session.state_of(key) is ItemState.RETAINED
    (row,) = session.returned_rows()
    assert row.state is ItemState.RETAINED and row.in_set
