"""Focused durable-workspace coverage for PR-LEARN-300."""

from __future__ import annotations

from pathlib import Path

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState, LearningVariant
from src.learning.discovered_review_models import DiscoveredReviewItem
from src.learning.discovered_review_store import DiscoveredReviewStore
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_record import LearningRecord, LearningRecordWriter


def _design(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": "controlled sweep",
        "prompt_source": "custom",
        "custom_prompt": "portrait",
        "stage": "txt2img",
        "variable_under_test": "CFG Scale",
        "start_value": 6.0,
        "end_value": 7.0,
        "step_value": 1.0,
        "images_per_value": 1,
    }


def test_post_run_design_gets_new_identity_and_preserves_prior_store_session(tmp_path: Path) -> None:
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(_design("Experiment A"))
    first = state.current_experiment
    assert first is not None
    first_id = first.experiment_id
    state.plan = [
        LearningVariant(experiment_id=first_id, status="completed", image_refs=["a1.png"])
    ]
    store = LearningExperimentStore(tmp_path / "experiments")
    store.save_session(display_name=first.name, payload=state.to_dict(), experiment_id=first_id)

    controller.update_experiment_design(_design("Experiment B"))
    second = state.current_experiment
    assert second is not None
    assert second.experiment_id != first_id
    store.save_session(display_name=second.name, payload=state.to_dict(), experiment_id=second.experiment_id)

    first_payload = store.load_session(first_id)
    second_payload = store.load_session(second.experiment_id)
    assert first_payload is not None and second_payload is not None
    assert first_payload["current_experiment"]["name"] == "Experiment A"
    assert first_payload["plan"][0]["image_refs"] == ["a1.png"]
    assert second_payload["current_experiment"]["name"] == "Experiment B"
    assert {handle.experiment_id for handle in store.list_handles()} == {first_id, second.experiment_id}


def test_post_run_design_checkpoints_prior_experiment_before_replacement() -> None:
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(_design("Experiment A"))
    first = state.current_experiment
    assert first is not None
    state.plan = [LearningVariant(experiment_id=first.experiment_id, status="completed")]
    checkpointed_ids: list[str] = []
    controller.add_resume_state_listener(
        lambda: checkpointed_ids.append(state.current_experiment.experiment_id)  # type: ignore[union-attr]
    )

    controller.update_experiment_design(_design("Experiment B"))

    assert checkpointed_ids[0] == first.experiment_id
    assert state.current_experiment is not None
    assert state.current_experiment.experiment_id != first.experiment_id


def test_review_draft_round_trips_without_becoming_saved_evidence() -> None:
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(_design("Drafts"))
    experiment = state.current_experiment
    assert experiment is not None
    state.plan = [LearningVariant(experiment_id=experiment.experiment_id, status="completed", image_refs=["a", "b"])]
    controller.save_review_draft(
        "a", {"overall_rating": 4, "notes": "keep", "subscores": {"composition": 5}}
    )
    assert controller.get_review_draft("a")["notes"] == "keep"  # type: ignore[index]
    assert controller.get_review_counts() == {"saved": 0, "draft": 1, "unrated": 1, "total": 2}

    restored = LearningState.from_dict(state.to_dict())
    restored_controller = LearningController(restored)
    assert restored_controller.get_review_draft("a")["overall_rating"] == 4  # type: ignore[index]
    assert restored_controller.is_image_rated("a") is False


def test_clone_creates_new_identity_with_design_only() -> None:
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(_design("Source experiment"))
    source = state.current_experiment
    assert source is not None
    source.execution_snapshot_json = '{"frozen": true}'
    source.baseline_config = {"txt2img": {"cfg_scale": 6.0}}
    source.values = [6.0, 7.0]
    state.plan = [LearningVariant(experiment_id=source.experiment_id, status="completed", image_refs=["a.png"])]

    clone = controller.clone_current_experiment_as_new()

    assert clone is not None
    assert clone.experiment_id != source.experiment_id
    assert clone.name == source.name
    assert clone.execution_snapshot_json == ""
    assert clone.baseline_config == {}
    assert clone.values == []
    assert state.plan == []


def test_persisted_rating_detail_restores_all_review_fields(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    writer.append_record(
        LearningRecord.from_pipeline_context(
            base_config={},
            variant_configs=[],
            metadata={
                "experiment_id": "exp-1",
                "image_path": "artifact.png",
                "user_rating": 5,
                "user_rating_raw": 4,
                "user_notes": "strong composition",
                "rating_schema_version": 2,
                "rating_context": {"people": True},
                "rating_details": {"composition": 5, "anatomy": 4},
            },
        )
    )
    detail = writer.get_rating_details_for_experiment("exp-1")["artifact.png"]
    assert detail == {
        "overall_rating": 4,
        "notes": "strong composition",
        "context_flags": {"people": True},
        "subscores": {"composition": 5.0, "anatomy": 4.0},
    }


def test_controlled_handoff_creates_curation_workset_with_lineage(tmp_path: Path) -> None:
    state = LearningState()
    controller = LearningController(state)
    controller.update_experiment_design(_design("Controlled A"))
    experiment = state.current_experiment
    assert experiment is not None
    state.plan = [LearningVariant(experiment_id=experiment.experiment_id, status="completed", image_refs=["a.png"])]
    controller._discovered_review_store = DiscoveredReviewStore(tmp_path / "discovered")  # noqa: SLF001
    controller._build_discovered_item_from_image_path = lambda path, index: DiscoveredReviewItem(  # type: ignore[method-assign]
        item_id=f"item-{index}", artifact_path=path, stage="txt2img"
    )

    group_id = controller.send_controlled_artifacts_to_staged_curation(["a.png"])
    assert group_id is not None
    loaded = controller._get_discovered_store().load_group(group_id)  # noqa: SLF001
    assert loaded is not None
    assert loaded.items[0].extra_fields["controlled_source"]["experiment_id"] == experiment.experiment_id
    assert state.current_experiment is experiment
    assert controller.list_staged_curation_handles()[0].group_id == group_id
