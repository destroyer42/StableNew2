"""PR-GUI-UX-580: ordered, conditional, truthful saving of the active photo's baseline (no Tk, real store)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PIL import Image

from src.gui.view_contracts.photo_baseline_save_contract import (
    BaselineDraft,
    PhotoBaselineSaveSession,
)
from src.photo_optimize.models import PhotoOptimizeBaseline
from src.photo_optimize.store import PhotoOptimizeStore, StaleBaselineError
from tests.gui_v2.edit_work_helpers import ManualRegistry, manual_runner


def _store(tmp_path: Path, count: int = 2) -> tuple[PhotoOptimizeStore, list[str]]:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    ids = []
    for index in range(count):
        source = tmp_path / "source" / f"p{index}.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 48), (40 * index, 80, 120)).save(source)
        ids.append(store.import_photo(source).asset_id)
    return store, ids


def _draft(store, asset_id: str, prompt: str, notes: str = "") -> BaselineDraft:
    asset = store.get_asset(asset_id)
    baseline = PhotoOptimizeBaseline.from_dict(asset.baseline.to_dict())
    baseline.prompt = prompt
    return BaselineDraft(asset_id=asset_id, notes=notes, tags=(), baseline=baseline)


@pytest.fixture
def session_env(tmp_path):
    store, ids = _store(tmp_path)
    registry = ManualRegistry()
    changes: list[int] = []
    session = PhotoBaselineSaveSession(
        get_store=lambda: store, runner=manual_runner(registry), on_change=lambda: changes.append(1)
    )
    for asset_id in ids:
        session.rebase(asset_id, store.get_asset(asset_id).baseline)
    return store, ids, registry, session


def test_a_burst_of_edits_writes_the_first_and_the_latest_draft_and_nothing_between(session_env):
    store, (a, _b), registry, session = session_env
    for prompt in ("one", "two", "three", "four"):
        session.note_edit(a)
        session.save(_draft(store, a, prompt))
    assert session.status(a)[0] == "saving"
    registry.run_all()
    assert store.get_asset(a).baseline.prompt == "four"  # last edit wins
    assert len(registry.ran) == 2  # the in-flight write plus the one coalesced pending write
    assert session.status(a) == ("saved", "Saved")


def test_a_delayed_write_for_one_photo_never_lands_on_another(session_env):
    store, (a, b), registry, session = session_env
    session.save(_draft(store, a, "prompt for A"))
    session.save(_draft(store, b, "prompt for B"))
    registry.run_all()
    assert store.get_asset(a).baseline.prompt == "prompt for A"
    assert store.get_asset(b).baseline.prompt == "prompt for B"


def test_a_failed_write_is_never_reported_saved_and_a_later_success_clears_it(
    session_env, monkeypatch
):
    store, (a, _b), registry, session = session_env
    real = store.update_asset_fields

    def failing(*args, **kwargs):
        raise OSError("disk is read-only")

    monkeypatch.setattr(store, "update_asset_fields", failing)
    session.save(_draft(store, a, "lost"))
    registry.run_all()
    state, message = session.status(a)
    assert state == "error" and "disk is read-only" in message
    assert store.get_asset(a).baseline.prompt != "lost"

    monkeypatch.setattr(store, "update_asset_fields", real)
    session.save(_draft(store, a, "kept"))
    registry.run_all()
    assert session.status(a) == ("saved", "Saved")
    assert store.get_asset(a).baseline.prompt == "kept"


def test_a_stale_form_cannot_overwrite_a_newer_baseline_and_says_so(session_env):
    store, (a, _b), registry, session = session_env
    # Another actor (a promotion, revert or batch edit) changes the stored baseline after the form was loaded.
    newer = PhotoOptimizeBaseline.from_dict(store.get_asset(a).baseline.to_dict())
    newer.prompt = "promoted elsewhere"
    store.update_asset_fields(a, baseline=newer)

    session.note_edit(a)
    session.save(_draft(store, a, "stale edit"))
    registry.run_all()
    state, message = session.status(a)
    assert state == "error" and "changed by another action" in message
    assert store.get_asset(a).baseline.prompt == "promoted elsewhere"

    # Reselecting reloads the form against the new baseline; editing is accepted again.
    session.rebase(a, store.get_asset(a).baseline)
    session.save(_draft(store, a, "after reload"))
    registry.run_all()
    assert store.get_asset(a).baseline.prompt == "after reload"


def test_waiters_run_only_after_the_outstanding_write_settles(session_env):
    store, (a, _b), registry, session = session_env
    session.save(_draft(store, a, "pending write"))
    outcomes = []
    session.when_settled(a, outcomes.append)
    assert outcomes == []  # plan preparation / promotion must not read the sidecar yet
    registry.run_all()
    assert len(outcomes) == 1 and outcomes[0].ok
    session.when_settled(a, outcomes.append)  # nothing outstanding: answered immediately
    assert len(outcomes) == 2


def test_a_waiter_hears_about_a_failed_write(session_env, monkeypatch):
    store, (a, _b), registry, session = session_env
    monkeypatch.setattr(
        store,
        "update_asset_fields",
        lambda *a_, **k: (_ for _ in ()).throw(ValueError("bad geometry")),
    )
    session.save(_draft(store, a, "x"))
    outcomes = []
    session.when_settled(a, outcomes.append)
    registry.run_all()
    assert outcomes[0].ok is False and "bad geometry" in outcomes[0].message


def test_conditional_write_refuses_without_touching_the_sidecar(tmp_path):
    store, (a, _b) = _store(tmp_path)
    before = store.sidecar_path(a).read_bytes()
    changed = PhotoOptimizeBaseline.from_dict(store.get_asset(a).baseline.to_dict())
    changed.prompt = "new"
    with pytest.raises(StaleBaselineError):
        store.update_asset_fields(
            a, baseline=changed, expected_baseline={"prompt": "not the stored one"}
        )
    assert store.sidecar_path(a).read_bytes() == before


def test_sidecar_updates_for_one_photo_are_serialised_by_the_asset_lock(tmp_path):
    store, (a, _b) = _store(tmp_path)
    finished = threading.Event()
    changed = PhotoOptimizeBaseline.from_dict(store.get_asset(a).baseline.to_dict())
    changed.prompt = "waits for the lock"

    def writer() -> None:
        store.update_asset_fields(a, baseline=changed)
        finished.set()

    with store.asset_lock(a):  # e.g. a promotion holding the sidecar
        thread = threading.Thread(target=writer)
        thread.start()
        assert not finished.wait(0.2)  # the baseline save cannot interleave with the promotion
    assert finished.wait(5)
    thread.join(5)
    assert store.get_asset(a).baseline.prompt == "waits for the lock"


def test_a_closed_runner_delivers_nothing_but_the_write_still_completes(tmp_path):
    store, (a, _b) = _store(tmp_path)
    registry = ManualRegistry()
    runner = manual_runner(registry)
    session = PhotoBaselineSaveSession(get_store=lambda: store, runner=runner)
    session.rebase(a, store.get_asset(a).baseline)
    session.save(_draft(store, a, "flushed on close"))
    runner.close()
    registry.run_all()
    assert store.get_asset(a).baseline.prompt == "flushed on close"
