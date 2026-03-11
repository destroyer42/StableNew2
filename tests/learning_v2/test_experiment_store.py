from __future__ import annotations

from pathlib import Path

from src.learning.experiment_store import LearningExperimentStore


def test_experiment_store_round_trip(tmp_path: Path) -> None:
    store = LearningExperimentStore(tmp_path / "experiments")

    handle = store.save_session(
        display_name="Resume Test",
        payload={
            "current_experiment": {"name": "Resume Test"},
            "plan": [{"param_value": 20, "status": "queued"}],
            "selected_variant_index": 0,
        },
    )

    loaded = store.load_session(handle.experiment_id)
    assert loaded is not None
    assert loaded["current_experiment"]["name"] == "Resume Test"
    assert loaded["plan"][0]["status"] == "queued"


def test_experiment_store_tracks_last_experiment_and_lists_handles(tmp_path: Path) -> None:
    store = LearningExperimentStore(tmp_path / "experiments")

    first = store.save_session(display_name="First", payload={"current_experiment": {"name": "First"}})
    second = store.save_session(display_name="Second", payload={"current_experiment": {"name": "Second"}})

    last = store.load_last_session()
    assert last is not None
    assert last[0] == second.experiment_id

    handles = store.list_handles()
    assert handles
    assert handles[0].experiment_id == second.experiment_id
    assert {item.experiment_id for item in handles} >= {first.experiment_id, second.experiment_id}
