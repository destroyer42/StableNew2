"""Golden policy outputs captured on the unchanged GUI-SEAM-720 parent."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/fixtures/presentation_policy_720.json"


def contract_snapshot(visibility_module, review_module, config_module):
    """Same synthetic inputs for the old locations and the extracted policies."""
    visibility = importlib.import_module(visibility_module)
    review = importlib.import_module(review_module).ReviewWorkflowAdapter()
    adapter_type = importlib.import_module(config_module).GuiConfigAdapterV26
    from src.curation.models import CurationCandidate, SelectionEvent
    from src.pipeline.reprocess_builder import ReprocessJobBuilder

    snapshot = {"visibility": [], "prompts": [], "feedback": [], "config": []}
    for value in [None, "", "SFW", " nsfw ", "invalid", 0, [], {"mode": "sfw"}]:
        snapshot["visibility"].append(
            {
                "normalized": visibility.normalize_content_visibility_mode(value).value,
                "settings": visibility.ContentVisibilitySettings.from_payload(value).to_payload(),
            }
        )
    for base, delta in [
        ("Portrait, Blue Eyes", "blue eyes, cinematic"),
        ("portrait, smiling, blue eyes", "SMILING -> laughing, -blue eyes, cinematic"),
        ("A, a, B", "+a, -B, C -> D"),
        ("  ", ""),
        (None, None),
    ]:
        for mode in ["append", "replace", "modify", "unknown"]:
            snapshot["prompts"].append(
                asdict(
                    review.build_prompt_diff(
                        base_prompt=base,
                        base_negative_prompt="blurry, extra fingers",
                        prompt_delta=delta,
                        negative_prompt_delta="-blurry, bad hands",
                        prompt_mode=mode,
                        negative_prompt_mode=mode,
                    )
                )
            )
    for metadata in [
        {
            "stage_manifest": {
                "prompt": "portrait",
                "negative_prompt": "blurry",
                "model": "sdxl",
                "steps": 20,
            },
            "generation": {"steps": 30, "cfg_scale": 7, "sampler_name": "Euler"},
        },
        {
            "stage_manifest": {"final_prompt": "final", "config": {"negative_prompt": "faded"}},
            "generation": {"scheduler": "Beta"},
        },
        {"stage_manifest": [], "generation": "malformed"},
    ]:
        snapshot["feedback"].append(
            review.build_feedback_payload(
                image_path=Path("image.png"),
                metadata_payload=metadata,
                rating=4,
                quality_label="good",
                notes="unchanged",
                prompt_delta="cinematic",
                negative_prompt_delta="-blurry",
                prompt_mode="append",
                negative_prompt_mode="modify",
                stages=["adetailer"],
                anatomy_rating=3,
                composition_rating=4,
                prompt_adherence_rating=5,
            )
        )

    paths = [ROOT / "__parity_inputs__" / name for name in ("b.png", "a.png", "b.png")]
    selections = []
    for index, path in enumerate(paths):
        candidate = CurationCandidate(
            candidate_id=f"c{index}",
            workflow_id="workflow",
            stage="scout",
            artifact_id=f"a{index}",
            job_id=f"job{index}",
            njr_id=f"njr{index}",
            parent_candidate_id="parent",
            root_candidate_id="root",
            prompt_fingerprint="prompt-hash",
            config_fingerprint="config-hash",
            model_name="sdxl",
        )
        event = SelectionEvent(
            event_id=f"event{index}",
            workflow_id="workflow",
            candidate_id=candidate.candidate_id,
            stage="scout",
            decision="advanced_to_refine",
            timestamp="2026-10-25T00:00:00Z",
        )
        selections.append(
            NS(
                candidate=candidate,
                selection_event=event,
                face_triage_tier="light",
                source_item=NS(artifact_path=str(path), stage="txt2img", positive_prompt="source"),
                reprocess_item=NS(
                    prompt="baseline", negative_prompt="negative", model="sdxl", vae="Automatic"
                ),
            )
        )
    plan = NS(
        selections=selections,
        target_stage="refine",
        workflow=NS(title="Workflow"),
        jobs=[NS(config={"img2img": {"steps": 11, "cfg_scale": 4}})],
    )
    handoff = review.build_staged_curation_handoff(plan=plan)
    snapshot["handoff"] = asdict(handoff)
    preview = ReprocessJobBuilder().build_effective_settings_preview(
        source_stage="txt2img",
        source_model="sdxl",
        source_vae="Automatic",
        stages=["img2img"],
        fallback_config={"img2img": {"steps": 20, "cfg_scale": 7}},
        metadata_config={"img2img": {"steps": 9}},
        prompt="source",
        negative_prompt="bad",
        prompt_mode="append",
        negative_prompt_mode="replace",
        prompt_delta="edit",
        negative_prompt_delta="",
    )
    snapshot["summary"] = review.format_effective_settings_summary(
        preview,
        direct_queue_preview=handoff.direct_queue_preview,
        readiness=review.assess_readiness(preview, backend_id="forge_webui"),
    )
    snapshot["klein"] = {
        "metadata": review.with_klein_edit_request(
            {str(paths[0]): {"source_job_id": "job0"}}, paths[:2]
        ),
        "readiness": asdict(
            review.assess_readiness(preview, single_reference_edit=True, backend_id="forge_webui")
        ),
    }
    for initial in [
        NS(),
        NS(
            run_config={"steps": 33},
            intent_config={"source": "pack"},
            execution_config={"steps": 12},
            backend_options={"image": {"backend_id": "forge_webui"}},
        ),
    ]:
        adapter = adapter_type(initial)
        before = {
            "projection": adapter.get_run_config_projection(),
            "layers": adapter.get_config_layers(),
        }
        payload = {
            "model": "sdxl",
            "steps": 22,
            "txt2img": {"steps": 14},
            "randomization_enabled": True,
            "max_variants": 4,
        }
        original = deepcopy(payload)
        changed = adapter.apply_run_config(payload)
        no_change = adapter.apply_run_config(payload)
        projection = adapter.build_submission_projection(
            lora_strengths=[{"name": "detail", "strength": 0.8}],
            prompt_optimizer_config={"enabled": True},
        )
        assert payload == original
        projection["txt2img"]["steps"] = 999
        assert adapter.get_run_config_projection()["txt2img"]["steps"] == 14
        snapshot["config"].append(
            {
                "before": before,
                "changed": changed,
                "repeat_changed": no_change,
                "submission": adapter.build_submission_projection(
                    lora_strengths=[{"name": "detail", "strength": 0.8}],
                    prompt_optimizer_config={"enabled": True},
                ),
                "layers": adapter.get_config_layers(),
            }
        )
    snapshot["randomizer"] = [
        adapter_type(NS(run_config={"max_variants": value})).get_randomizer_config(
            fallback_current_config=NS(randomization_enabled=True, max_variants=8)
        )
        for value in [None, 0, -2, "bad", "3"]
    ]
    snapshot["contexts"] = [
        adapter_type(state).resolve_prompt_pack_context()
        for state in [
            NS(),
            NS(selected_prompt_pack_id=" selected "),
            NS(job_draft=NS(pack_id="draft")),
            NS(job_draft=NS(packs=[NS(pack_id=""), NS(pack_id="entry")])),
        ]
    ]

    def normalize(value):
        if is_dataclass(value):
            return normalize(asdict(value))
        if isinstance(value, Path):
            return normalize(str(value))
        if isinstance(value, str):
            return value.replace(str(ROOT), "<repo>").replace("\\", "/")
        if isinstance(value, dict):
            return {normalize(k): normalize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        return value

    return normalize(snapshot)


def test_outputs_match_unchanged_parent_contract():
    actual = contract_snapshot(
        "src.state.content_visibility",
        "src.review.workflow_adapter",
        "src.gui_v2.adapters.config_adapter_v26",
    )
    assert actual == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_config_service_fallback_and_existing_state_share_one_adapter():
    from src.controller.app_controller_services.gui_config_service import GuiConfigService
    from src.gui.app_state_v2 import AppStateV2
    from src.gui_v2.adapters.config_adapter_v26 import GuiConfigAdapterV26

    service = GuiConfigService()
    assert service.get_adapter(None) is None
    state = AppStateV2()
    assert service.get_adapter(state) is state.config_adapter
    legacy = NS(current_config=NS(randomization_enabled=True, max_variants=7))
    adapter = service.get_adapter(legacy)
    assert isinstance(adapter, GuiConfigAdapterV26)
    assert adapter.apply_run_config(None) is False
    assert adapter.update_projection(None) is False
    assert adapter.set_randomizer() is False
    assert adapter.get_randomizer_config(fallback_current_config=legacy.current_config) == {
        "randomization_enabled": True,
        "max_variants": 7,
    }
    assert adapter.set_randomizer(enabled=False, max_variants=0) is True
    assert legacy.run_config["max_variants"] == 1
    assert adapter.set_randomizer(enabled=False, max_variants=0) is False


@pytest.mark.parametrize("base,delta", [(1, "word"), ("word", {"malformed": True})])
def test_truthy_nontext_prompts_keep_the_existing_refusal(base, delta):
    from src.review.workflow_adapter import ReviewWorkflowAdapter

    with pytest.raises(AttributeError):
        ReviewWorkflowAdapter.apply_prompt_delta(base, delta, "append")


@pytest.mark.parametrize("payload", [None, {}, {"mode": "SFW"}, {"mode": "invalid"}])
def test_tk_state_and_controller_share_the_canonical_visibility_identity(payload):
    from src.controller.content_visibility_resolver import ContentVisibilityResolver
    from src.gui.app_state_v2 import AppStateV2
    from src.state.content_visibility import ContentVisibilityMode, ContentVisibilitySettings

    settings = ContentVisibilitySettings.from_payload(payload)
    state = AppStateV2()
    assert state.set_content_visibility_mode(settings.mode) is settings.mode
    assert ContentVisibilityResolver(state.content_visibility_mode).mode is settings.mode
    assert type(settings.mode) is ContentVisibilityMode


@pytest.mark.parametrize("mode", ["sfw", "nsfw"])
def test_embedding_review_captions_and_conclusions_use_shared_visibility(tk_root, tmp_path, mode):
    from src.gui.views.learning_review_panel import LearningReviewPanel
    from src.learning.embedding_experiment import conclusion
    from tests.learning_v2.test_embedding_experiment_700 import A, _golden

    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    bench.controller.app_state = NS(resources={}, content_visibility_mode=mode)
    panel = LearningReviewPanel(tk_root)
    try:
        panel.learning_controller = bench.controller
        panel.current_experiment = experiment
        panel._update_metadata(bench.state.plan[1], experiment)
        panel.set_prompt_slot_conclusion(conclusion(bench.state.plan, {}, {}))
        for text in (panel.metadata_text, panel.slot_conclusion_text):
            rendered = text.get("1.0", "end-1c")
            assert (A in rendered) is (mode == "nsfw")
        assert "Candidate B" in panel.metadata_text.get("1.0", "end-1c")
    finally:
        panel.destroy()
