"""Focused workflow-coherence coverage for the PR-LEARN-300 continuation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState, LearningVariant
from src.learning.discovered_review_models import (
    STATUS_CLOSED,
    STATUS_IGNORED,
    DiscoveredReviewExperiment,
    DiscoveredReviewItem,
)
from src.learning.discovered_review_store import DiscoveredReviewStore
from src.learning.experiment_conclusion import build_experiment_conclusion
from src.learning.experiment_freeze import describe_matrix_freeze, freeze_prompt_pack_source
from src.learning.experiment_lifecycle import (
    classify_experiment_lifecycle,
    has_successful_admission,
)
from src.learning.staged_recommendations import (
    apply_derived_recommendation_patch,
    build_derived_recommendation_patch,
)
from src.promptpacks.storage import save_prompt_pack_document


def _matrix_pack(path: Path, *, mode: str = "random", values: list[str] | None = None) -> Path:
    return save_prompt_pack_document(
        path,
        {
            "pack_data": {
                "name": "matrix",
                "slots": [{"index": 0, "text": "portrait with [[hair]] hair"}],
                "matrix": {
                    "enabled": True,
                    "mode": mode,
                    "slots": [{"name": "hair", "values": values or []}],
                },
            },
            "preset_data": {},
        },
    )


def test_random_matrix_freezes_first_canonical_value_and_explains_policy(tmp_path: Path) -> None:
    pack = _matrix_pack(tmp_path / "matrix.json", values=["red", "blue"])
    original = pack.read_bytes()

    frozen = freeze_prompt_pack_source(
        {
            "prompt_source": "pack",
            "selected_prompt_pack_name": "matrix",
            "selected_prompt_pack_path": str(pack),
            "selected_prompt_index": 0,
        }
    )

    assert frozen["matrix_source_mode"] == "random"
    assert frozen["matrix_values"] == {"hair": "red"}
    assert frozen["matrix_combination_total"] == 2
    assert "red hair" in frozen["rendered_positive_prompt"]
    assert "Random" in describe_matrix_freeze(frozen)
    assert "1/2" in describe_matrix_freeze(frozen)
    assert pack.read_bytes() == original


def test_random_matrix_without_selected_row_tokens_is_unused(tmp_path: Path) -> None:
    pack = save_prompt_pack_document(
        tmp_path / "unused.json",
        {
            "pack_data": {
                "name": "unused",
                "slots": [{"index": 0, "text": "plain portrait"}],
                "matrix": {
                    "enabled": True,
                    "mode": "random",
                    "slots": [{"name": "hair", "values": ["red", "blue"]}],
                },
            },
            "preset_data": {},
        },
    )

    frozen = freeze_prompt_pack_source(
        {
            "prompt_source": "pack",
            "selected_prompt_pack_name": "unused",
            "selected_prompt_pack_path": str(pack),
            "selected_prompt_index": 0,
        }
    )

    assert frozen["matrix_source_mode"] == "random"
    assert frozen["matrix_used"] is False
    assert frozen["matrix_freeze_policy"] == "unused"
    assert frozen["rendered_positive_prompt"] == "plain portrait"


def test_referenced_empty_matrix_slot_is_a_controlled_build_error(tmp_path: Path) -> None:
    pack = _matrix_pack(tmp_path / "empty.json")

    with pytest.raises(ValueError, match="Matrix slot 'hair' has no values"):
        freeze_prompt_pack_source(
            {
                "prompt_source": "pack",
                "selected_prompt_pack_name": "matrix",
                "selected_prompt_pack_path": str(pack),
                "selected_prompt_index": 0,
            }
        )


def test_working_draft_is_not_library_admitted_until_job_id_exists() -> None:
    draft = {"plan": [{"status": "pending", "job_id": ""}]}
    admitted = {"plan": [{"status": "queued", "job_id": "job-1"}]}

    assert has_successful_admission(draft) is False
    assert classify_experiment_lifecycle(draft) == "Draft/Legacy Draft"
    assert has_successful_admission(admitted) is True
    assert classify_experiment_lifecycle(admitted) == "Queued"


def test_library_lifecycle_uses_saved_sample_review_completion() -> None:
    payload = {
        "plan": [
            {
                "status": "completed",
                "job_id": "job-1",
                "completed_images": 2,
            }
        ]
    }
    assert classify_experiment_lifecycle(payload, saved_rating_count=1) == "Review Needed"
    assert classify_experiment_lifecycle(payload, saved_rating_count=2) == "Complete"


def test_conclusion_uses_saved_ratings_and_separates_drafts() -> None:
    plan = [
        LearningVariant(param_value=6.0, status="completed", image_refs=["a.png", "b.png"]),
        LearningVariant(param_value=7.0, status="completed", image_refs=["c.png"]),
    ]
    conclusion = build_experiment_conclusion(
        plan,
        {
            "a.png": {"overall_rating": 3, "subscores": {"composition": 4}},
            "c.png": {"overall_rating": 5, "subscores": {"composition": 5}},
        },
        {"exp:b.png": {"overall_rating": 5}},
    )

    assert conclusion["saved"] == 2
    assert conclusion["draft"] == 1
    assert conclusion["unrated"] == 0
    assert conclusion["best_value"] == 7.0
    assert conclusion["sufficient_evidence"] is True


def test_uncontrolled_conclusion_never_claims_a_causal_winner() -> None:
    plan = [
        LearningVariant(
            param_value=6.0,
            status="completed",
            image_refs=["a.png"],
            execution_metadata={"controlled_evidence_valid": False},
        ),
        LearningVariant(param_value=7.0, status="completed", image_refs=["b.png"]),
    ]
    conclusion = build_experiment_conclusion(
        plan,
        {"a.png": {"overall_rating": 3}, "b.png": {"overall_rating": 5}},
        {},
    )

    assert conclusion["best_value"] is None
    assert conclusion["sufficient_evidence"] is False
    assert "Insufficient controlled" in conclusion["message"]


def test_staged_suggestion_patch_changes_only_isolated_derived_stage() -> None:
    baseline = {"txt2img": {"cfg_scale": 7.0}, "img2img": {"cfg_scale": 6.0}}
    recommendation = SimpleNamespace(
        recommendations=[
            SimpleNamespace(
                parameter_name="cfg_scale",
                recommended_value=7.5,
                confidence_score=0.8,
            )
        ]
    )
    patch = build_derived_recommendation_patch(
        recommendation, target_stage="refine", current_config=baseline
    )
    derived = apply_derived_recommendation_patch(baseline, patch)

    assert baseline["img2img"]["cfg_scale"] == 6.0
    assert derived["img2img"]["cfg_scale"] == 7.5
    assert derived["txt2img"] == baseline["txt2img"]

    rejected = apply_derived_recommendation_patch(
        baseline,
        {"target_stage": "txt2img", "stage_patch": {"cfg_scale": 99, "unknown": True}},
        target_stage="refine",
    )
    assert rejected == baseline


def test_confirmed_suggestion_submission_uses_selected_candidate_and_job_service() -> None:
    controller = LearningController(LearningState())
    plan = SimpleNamespace(jobs=[SimpleNamespace(job_id="derived-1")])
    build = Mock(return_value=plan)
    controller.build_staged_curation_advancement_plan = build  # type: ignore[method-assign]
    submitted: list[object] = []
    service = SimpleNamespace(
        submit_njrs=lambda jobs, _policy: submitted.extend(jobs) or ["queued-1"]
    )
    controller._get_job_service = lambda: service  # type: ignore[method-assign]
    patch = {
        "target_stage": "img2img",
        "stage_patch": {"cfg_scale": 7.5},
        "changes": [{"setting": "cfg_scale"}],
    }

    count = controller.submit_staged_curation_advancement(
        "group-1",
        "refine",
        candidate_ids=["candidate-1"],
        recommendation_patch=patch,
    )

    assert count == 1
    assert submitted == plan.jobs
    build.assert_called_once_with(
        "group-1",
        "refine",
        candidate_ids=["candidate-1"],
        recommendation_patch=patch,
    )


def test_staged_suggestion_preview_uses_selected_artifact_context(tmp_path: Path) -> None:
    captured: list[tuple[object, ...]] = []
    recommendation = SimpleNamespace(recommendations=[])
    engine = SimpleNamespace(
        recommend=lambda *args, **kwargs: captured.append((args, kwargs)) or recommendation
    )
    controller = LearningController(LearningState())
    controller._recommendation_engine = engine  # noqa: SLF001
    store = DiscoveredReviewStore(tmp_path / "store")
    item = DiscoveredReviewItem(
        item_id="candidate-1",
        artifact_path=str(tmp_path / "candidate.png"),
        positive_prompt="portrait",
        model="model-a",
        width=768,
        height=1024,
    )
    store.save_group(
        DiscoveredReviewExperiment(
            group_id="group-1",
            display_name="group",
            stage="txt2img",
            prompt_hash="hash",
            items=[item],
        )
    )
    controller._discovered_review_store = store  # noqa: SLF001
    controller._get_baseline_config = lambda: {  # type: ignore[method-assign]
        "img2img": {"cfg_scale": 6.0}
    }

    preview = controller.preview_staged_curation_suggestions(
        "group-1", "candidate-1", "refine"
    )

    assert preview["changes"] == []
    assert captured == [(('portrait', 'refine'), {'model': 'model-a', 'width': 768, 'height': 1024})]


def _discovered_group(
    group_id: str, artifact_path: Path, *, status: str = "waiting_review"
) -> DiscoveredReviewExperiment:
    return DiscoveredReviewExperiment(
        group_id=group_id,
        display_name=group_id,
        stage="txt2img",
        prompt_hash=group_id,
        status=status,
        origin="filesystem_scan",
        items=[DiscoveredReviewItem(item_id=f"{group_id}-item", artifact_path=str(artifact_path))],
    )


def test_discovered_handles_report_available_and_missing_counts(tmp_path: Path) -> None:
    available = tmp_path / "available.png"
    available.write_bytes(b"png")
    store = DiscoveredReviewStore(tmp_path / "store")
    group = _discovered_group("mixed", available)
    group.items.append(
        DiscoveredReviewItem(item_id="missing", artifact_path=str(tmp_path / "missing.png"))
    )
    store.save_group(group)

    [handle] = store.list_handles()
    assert handle.item_count == 2
    assert handle.available_item_count == 1
    assert handle.missing_item_count == 1


def test_rebuild_preserves_done_and_dismissed_operator_decisions(tmp_path: Path) -> None:
    store = DiscoveredReviewStore(tmp_path / "store")
    missing = tmp_path / "missing.png"
    store.save_group(_discovered_group("active", missing))
    store.save_group(_discovered_group("done", missing, status=STATUS_CLOSED))
    store.save_group(_discovered_group("dismissed", missing, status=STATUS_IGNORED))

    result = store.reset_filesystem_scan_state()

    assert result["groups_removed"] == 1
    assert store.load_group("active") is None
    assert store.load_group("done") is not None
    assert store.load_group("dismissed") is not None


def test_explicit_legacy_cleanup_preserves_protected_groups_and_physical_files(
    tmp_path: Path,
) -> None:
    store = DiscoveredReviewStore(tmp_path / "store")
    missing = tmp_path / "missing.png"
    protected_image = tmp_path / "protected.png"
    protected_manifest = tmp_path / "protected.json"
    protected_image.write_bytes(b"png")
    protected_manifest.write_text("{}", encoding="utf-8")

    legacy = _discovered_group("legacy", missing)
    legacy.origin = "legacy_unknown"
    protected = _discovered_group("protected", protected_image)
    protected.origin = "controlled_experiment_handoff"
    protected.items[0].manifest_path = str(protected_manifest)
    store.save_group(legacy)
    store.save_group(protected)

    preview = store.preview_missing_cleanup()
    assert preview["legacy_missing_items"] == 1
    result = store.prune_missing_scanner_items(include_legacy=True)

    assert result["missing_items"] == 1
    assert store.load_group("legacy") is None
    assert store.load_group("protected") is not None
    assert protected_image.is_file()
    assert protected_manifest.is_file()
