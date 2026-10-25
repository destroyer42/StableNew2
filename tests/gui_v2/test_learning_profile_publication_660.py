"""Headless interaction tests with deferred workers and real temporary durable evidence."""

import json
from dataclasses import replace

import pytest

from src.gui.controllers.learning_profile_publication import (
    LearningProfilePublicationCoordinator,
    PublicationContext,
)
from src.gui.views.learning_profile_publication import LearningProfilePublicationPanel
from src.learning.experiment_execution import freeze_snapshot
from tests.learning_v2.test_profile_publication_660 import make_publication, records


class Runner:
    def __init__(self):
        self.pending = []
        self.closed = False

    def submit(self, _key, work, **callbacks):
        self.pending.append((work, callbacks))

    def finish(self):
        work, callbacks = self.pending.pop(0)
        error = None
        try:
            result = work()
        except Exception as exc:
            error = exc
            if not self.closed:
                callbacks["on_error"](exc)
        else:
            if not self.closed:
                callbacks["on_result"](result)
        if not self.closed and "on_complete" in callbacks:
            callbacks["on_complete"](True, error)

    def close(self):
        self.closed = True


@pytest.fixture
def flow(tmp_path):
    publication = make_publication(tmp_path)
    rows = records(publication)
    path = tmp_path / "ratings.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    contexts = [
        PublicationContext(
            "experiment-1",
            "test.safetensors",
            "txt2img",
            freeze_snapshot(rows[0]["metadata"]["frozen_experiment"]["snapshot"]),
        )
    ]
    events, refreshes, runner = [], [], Runner()
    coordinator = LearningProfilePublicationCoordinator(
        service=publication,
        records_path=path,
        runner=runner,
        context=lambda: contexts[0],
        catalogs=lambda: {},
        show=lambda state, result: events.append((state, result)),
        refresh_catalog=lambda: refreshes.append(True),
    )
    return coordinator, contexts, events, refreshes, runner, rows


def test_review_confirm_catalog_and_no_implicit_apply(flow):
    coordinator, _contexts, events, refreshes, runner, _rows = flow
    before = coordinator.records_path.read_bytes()
    coordinator.review()
    assert events[-1][0] == "busy" and coordinator.proposal is None
    runner.finish()
    assert events[-1][0] == "proposal" and coordinator.proposal.ready
    assert not coordinator.service.store.root.exists()
    coordinator.publish(name="Confirmed", lineage=None, confirmed=False)
    assert not runner.pending and not coordinator.service.store.root.exists()
    coordinator.publish(name="Confirmed", lineage=None, confirmed=True)
    coordinator.publish(name="Double click", lineage=None, confirmed=True)
    assert len(runner.pending) == 1
    runner.finish()
    assert events[-1][0] == "success" and "Confirmed, revision 1" in events[-1][1]
    assert len(refreshes) == 1
    assert len(list(coordinator.service.store.root.rglob("*.json"))) == 1
    assert coordinator.records_path.read_bytes() == before


@pytest.mark.parametrize("change", ["experiment_id", "model", "stage", "snapshot"])
def test_switched_context_rejects_async_review_and_confirmation(flow, change):
    coordinator, contexts, events, _refreshes, runner, _rows = flow
    coordinator.review()
    contexts[0] = replace(contexts[0], **{change: "different"})
    runner.finish()
    assert coordinator.proposal is None
    coordinator.publish(name="Stale", lineage=None, confirmed=True)
    assert events[-1][0] == "error"
    assert not coordinator.service.store.root.exists()


def test_superseded_review_and_closed_pending_publish(flow):
    coordinator, _contexts, events, _refreshes, runner, _rows = flow
    coordinator.review()
    coordinator.review()
    runner.finish()
    assert coordinator.proposal is None
    runner.finish()
    assert coordinator.proposal.ready
    coordinator.publish(name="Closed", lineage=None, confirmed=True)
    coordinator.close()
    count = len(events)
    runner.finish()
    assert len(events) == count and not coordinator.service.store.root.exists()


def test_changed_saved_evidence_refuses_at_publish(flow):
    coordinator, _contexts, events, refreshes, runner, rows = flow
    coordinator.review()
    runner.finish()
    rows[1]["metadata"]["user_rating"] = 1
    with coordinator.records_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rows[1]) + "\n")
    coordinator.publish(name="Stale evidence", lineage=None, confirmed=True)
    runner.finish()
    assert events[-1][0] == "error" and "stale" in events[-1][1]
    assert not refreshes and not coordinator.service.store.root.exists()


def test_storage_failure_is_error_never_success(flow, monkeypatch):
    coordinator, _contexts, events, refreshes, runner, _rows = flow
    coordinator.review()
    runner.finish()

    def fail(_profile):
        raise RuntimeError("Disk unavailable")

    monkeypatch.setattr(coordinator.service.store, "publish_learning_profile", fail)
    coordinator.publish(name="Failure", lineage=None, confirmed=True)
    runner.finish()
    assert events[-1] == ("error", "Disk unavailable")
    assert not refreshes


def test_comparative_or_stage_specific_explains_refusal(flow):
    coordinator, contexts, events, _refreshes, runner, _rows = flow
    contexts[0] = replace(contexts[0], snapshot='{"study_type":"model_comparison"}')
    coordinator.review()
    assert "Model Comparison" in events[-1][1] and not runner.pending
    contexts[0] = replace(contexts[0], stage="adetailer")
    coordinator.review()
    assert "Stage-specific" in events[-1][1] and not runner.pending


def test_widget_confirmation_is_separate_and_cancel_writes_nothing(flow, monkeypatch):
    from types import SimpleNamespace

    coordinator, _contexts, _events, _refreshes, runner, _rows = flow
    coordinator.review()
    runner.finish()
    widget = SimpleNamespace(
        _proposal=coordinator.proposal,
        _get_coordinator=lambda: coordinator,
        _selected_lineage=lambda: None,
        _profile_name_var=SimpleNamespace(get=lambda: "Reviewed"),
    )
    decisions = []

    def confirm(*args, **kwargs):
        decisions.append(args)
        return False

    monkeypatch.setattr("src.gui.views.learning_profile_publication.messagebox.askyesno", confirm)
    LearningProfilePublicationPanel.publish(widget)
    assert decisions and not runner.pending and not coordinator.service.store.root.exists()
