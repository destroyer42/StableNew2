"""Target-envelope isolation, preview freeze, fail-closed admission and evidence."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.model_policy import resolve_model_policy
from src.learning.experiment_conclusion import build_experiment_conclusion
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.model_comparison import (
    build_comparison_snapshot,
    candidate_models,
    digest,
    frozen_arm,
    preview_summary,
    rating_classification,
    study_type,
)
from src.learning.recommendation_engine import RecommendationEngine
from src.pipeline.compile_evidence import CompileEvidence
from src.pipeline.resolution_layer import (
    pack_prompt_intent_from_dict,
    pack_prompt_intent_to_dict,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "ordinary.safetensors"


def family(name):
    if name in {SDXL, "peer.safetensors"}:
        return SimpleNamespace(
            status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sdxl")
        )
    if name == "conflict":
        return SimpleNamespace(status=SimpleNamespace(value="conflicting"), family=None)
    if name == "sd1":
        return SimpleNamespace(
            status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sd1")
        )
    return None


def policy(name):
    return resolve_model_policy(name, family_lookup=family)


def baseline():
    return {
        "txt2img": {
            "model": SDXL,
            "vae": "",
            "sampler_name": "DPM++ 2M",
            "scheduler": "Karras",
            "steps": 30,
            "cfg_scale": 7.0,
            "width": 768,
            "height": 1024,
            "seed": 42,
            "subseed": 700,
            "subseed_strength": 0.5,
        },
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "adetailer_enabled": False,
            "upscale_enabled": False,
            "apply_global_negative_txt2img": True,
        },
        "backend_options": {"image": {"backend_id": "forge_webui"}},
        "global_negative_prompt": "global negative",
        "prompt_optimizer": {"enabled": True},
    }


def experiment(tmp_path, *, models=None, loras=None):
    path = tmp_path / "pack.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "study",
                    "slots": [
                        {
                            "index": 0,
                            "text": "(red dress:1.2) (ratio: 2) (ratio:2) in [[place]]",
                            "negative": "bad",
                            "positive_embeddings": ["positive_embed"],
                            "negative_embeddings": ["negative_embed"],
                            "loras": loras or [],
                        }
                    ],
                    "matrix": {
                        "mode": "random",
                        "slots": [{"name": "place", "values": ["forest", "sea"]}],
                    },
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )
    return LearningExperiment(
        name="comparison",
        experiment_id="study",
        stage="txt2img",
        images_per_value=2,
        metadata={
            "study_type": "model_comparison",
            "prompt_source": "pack",
            "selected_prompt_pack_path": str(path),
            "selected_prompt_pack_name": "study",
            "selected_prompt_index": 0,
            "selected_models": models or [SDXL, KLEIN],
        },
    )


def plan(tmp_path, *, config=None, models=None, loras=None, status=KleinLoraStatus.COMPATIBLE):
    exp = experiment(tmp_path, models=models, loras=loras)
    evidence = CompileEvidence(
        family_lookup=family, lora_resolver=lambda name: KleinLoraDecision(name, status, "fixture")
    )
    snapshot = build_comparison_snapshot(exp, config or baseline(), evidence=evidence)
    return exp, snapshot, evidence


@pytest.mark.parametrize("models", [[SDXL, "peer.safetensors"], [SDXL, KLEIN]])
@pytest.mark.parametrize("width", [768, 1024])
def test_qualified_shared_source_and_geometry(tmp_path, models, width):
    config = baseline()
    config["txt2img"]["width"] = width
    original = copy.deepcopy(config)
    exp, snapshot, evidence = plan(tmp_path, config=config, models=models)
    assert config == original
    assert evidence.policy_lookups == 2
    assert snapshot["prompt_source"]["matrix_values"] == {"place": "forest"}
    assert snapshot["prompt_source"]["matrix_freeze_policy"] == "first_canonical_required_slots"
    intent = snapshot["model_comparison"]["source_intent"]
    assert pack_prompt_intent_to_dict(pack_prompt_intent_from_dict(intent)) == intent
    assert digest(intent) == snapshot["model_comparison"]["source_intent_sha256"]
    for model in models:
        arm = frozen_arm(snapshot, model)
        assert arm["source_intent_sha256"] == digest(intent)
        assert arm["shared_geometry"] == {"width": width, "height": 1024}
        assert arm["effective_config"]["txt2img"]["seed"] == 42
        assert arm["causal_one_variable"] is False
    assert study_type(LearningExperiment()) == "controlled_variable"
    assert "ordinary.safetensors" not in preview_summary(snapshot)
    assert "red dress" not in preview_summary(snapshot)


@pytest.mark.parametrize(
    "models",
    [[SDXL, "unknown"], [SDXL, "conflict"], [SDXL, "sd1"], [SDXL], [SDXL, SDXL], [SDXL, None]],
)
def test_candidate_gates(tmp_path, models):
    with pytest.raises(ValueError):
        plan(tmp_path, models=models)


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda c: c["backend_options"]["image"].update(backend_id="a1111_webui"), "backend"),
        (lambda c: c["txt2img"].update(width=832, height=1216), "geometry"),
        (lambda c: c["txt2img"].update(enable_hr=True), "hires"),
        (lambda c: c["txt2img"].update(refiner_enabled=True), "refiner"),
        (lambda c: c["txt2img"].update(controlnet={"enabled": True}), "controlnet"),
        (lambda c: c["pipeline"].update(adetailer_enabled=True), "stage chain"),
    ],
)
def test_no_backend_geometry_or_feature_adaptation(tmp_path, change, match):
    config = baseline()
    change(config)
    original = copy.deepcopy(config)
    with pytest.raises(ValueError, match=match):
        plan(tmp_path, config=config)
    assert config == original


@pytest.mark.parametrize("source", ["custom", "current"])
def test_promptpack_only(tmp_path, source):
    exp = experiment(tmp_path)
    exp.metadata["prompt_source"] = source
    with pytest.raises(ValueError, match="PromptPack"):
        build_comparison_snapshot(exp, baseline())


def test_target_adaptation_and_fixed_controls(tmp_path):
    exp, snapshot, evidence = plan(
        tmp_path, loras=[["row_prose", 0.8]], status=KleinLoraStatus.INCOMPATIBLE
    )
    sdxl, klein = snapshot["model_comparison"]["arms"]
    assert not sdxl["prompt_adaptation"]["changed"]
    assert "(red dress:1.2)" in sdxl["executor_base_positive_prompt"]
    assert klein["prompt_adaptation"]["changed"]
    assert "(red dress:1.2)" not in klein["executor_base_positive_prompt"]
    assert "red dress" in klein["executor_base_positive_prompt"]
    assert "(ratio: 2) (ratio:2)" in klein["executor_base_positive_prompt"]
    assert klein["executor_base_negative_prompt"] == ""
    assert klein["effective_positive_embeddings"] == klein["effective_negative_embeddings"] == []
    assert sdxl["effective_lora_tags"] == [["row_prose", 0.8]]
    assert klein["effective_lora_tags"] == []
    assert evidence.lora_evidence.lookups == 1
    section = klein["effective_config"]["txt2img"]
    assert (
        section["steps"],
        section["cfg_scale"],
        section["sampler_name"],
        section["scheduler"],
        section["vae"],
    ) == (4, 1.0, "Euler", "Beta", "")
    assert klein["effective_backend_options"]["image"]["model_profile"]["version"] == 2


@pytest.mark.parametrize("status", [KleinLoraStatus.UNVERIFIED, KleinLoraStatus.CONFLICTING])
def test_incomplete_adaptation_refused(tmp_path, status):
    with pytest.raises(ValueError, match="incomplete"):
        plan(tmp_path, loras=[["adapter", 0.8]], status=status)


def test_lora_limit_canonical_and_inline_untouched(tmp_path):
    _, snapshot, evidence = plan(tmp_path, loras=[["first", 0.7], ["second", 0.6]])
    assert snapshot["model_comparison"]["arms"][1]["effective_lora_tags"] == [["first", 0.7]]
    assert evidence.lora_evidence.lookups == 2


def controller_for(exp, config):
    controller = LearningController(learning_state=LearningState())
    controller._get_baseline_config = lambda: copy.deepcopy(config)
    controller._learning_policy_resolver = policy
    controller._learning_lora_resolver = lambda name: KleinLoraDecision(
        name, KleinLoraStatus.COMPATIBLE, "fixture"
    )
    controller.build_plan(exp)
    return controller


def test_run_freezes_source_rules_registry_live_cards_and_atomic_admission(tmp_path, monkeypatch):
    exp = experiment(tmp_path, loras=[["adapter", 0.7]])
    controller = controller_for(exp, baseline())
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    (tmp_path / "pack.json").write_text("changed", encoding="utf-8")
    for target in (
        "src.learning.experiment_freeze.load_prompt_pack_document",
        "src.pipeline.resolution_layer.adapt_pack_intent",
        "src.pipeline.resolution_layer.adapt_structured_prompt",
        "src.image_backends.model_policy.RegistryFamilyLookup.__call__",
    ):
        monkeypatch.setattr(target, lambda *a, **kw: pytest.fail("Run reinterpreted preview"))
    monkeypatch.setattr("src.prompting.prompt_adaptation.ADAPTATION_RULESET_VERSION", "future")
    controller._get_baseline_config = lambda: pytest.fail("Run read live cards")
    controller._learning_policy_resolver = lambda _: pytest.fail("Run resolved live target")
    controller.pipeline_controller = object()
    submit = Mock()
    controller.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    controller.run_plan()
    assert submit.call_count == 1
    records = submit.call_args.args[0]
    assert len(records) == 2
    for index, record in enumerate(records):
        arm = snapshot["model_comparison"]["arms"][index]
        assert record.source.kind.value == "learning"
        assert record.positive_prompt == arm["executor_base_positive_prompt"] == record.config["prompt"]
        assert (
            record.negative_prompt
            == arm["executor_base_negative_prompt"]
            == record.config["negative_prompt"]
        )
        assert (
            record.provenance.to_dict()["metadata"]["prompt_adaptation"] == arm["prompt_adaptation"]
        )
        assert record.provenance.to_dict()["metadata"]["model_comparison"] == arm
        assert record.seed == 42
        assert record.stages[0].model == snapshot["variant_values"][index]
    restored = LearningExperiment.from_dict(exp.to_dict())
    assert restored.execution_snapshot_json == exp.execution_snapshot_json
    assert study_type(restored) == "model_comparison"


@pytest.mark.parametrize(
    "field",
    [
        "executor_base_positive_prompt",
        "executor_base_negative_prompt",
        "prompt_adaptation",
        "source_intent_sha256",
        "shared_geometry",
        "causal_one_variable",
        "effective_lora_tags",
    ],
)
def test_corrupt_arm_prevents_whole_study_admission(tmp_path, field):
    exp = experiment(tmp_path)
    controller = controller_for(exp, baseline())
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    snapshot["model_comparison"]["arms"][1][field] = "corrupt"
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    submit = Mock()
    controller.pipeline_controller = object()
    controller.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    with pytest.raises(ValueError):
        controller.run_plan()
    submit.assert_not_called()
    assert all(v.status == "pending" for v in controller.learning_state.plan)


def test_stale_profile_fails_even_with_consistent_checksum(tmp_path):
    _, snapshot, _ = plan(tmp_path)
    arm = snapshot["model_comparison"]["arms"][1]
    arm["effective_backend_options"]["image"]["model_profile"]["version"] = 999
    arm["effective_config"]["backend_options"] = copy.deepcopy(arm["effective_backend_options"])
    arm["arm_sha256"] = digest({k: v for k, v in arm.items() if k != "arm_sha256"})
    with pytest.raises(ValueError):
        frozen_arm(snapshot, KLEIN)


@pytest.mark.parametrize("field", ["source_intent_sha256", "causal_one_variable", "steps", "manifest"])
def test_resealed_semantic_inconsistency_still_fails(tmp_path, field):
    _, snapshot, _ = plan(tmp_path)
    arm = snapshot["model_comparison"]["arms"][1]
    if field == "steps":
        arm["effective_config"]["txt2img"]["steps"] = 30
    elif field == "manifest":
        arm["prompt_adaptation"]["counts"]["loras"] = 99
    elif field == "causal_one_variable":
        arm[field] = True
    else:
        arm[field] = "different"
    arm["arm_sha256"] = digest({k: v for k, v in arm.items() if k != "arm_sha256"})
    with pytest.raises(ValueError):
        frozen_arm(snapshot, KLEIN)


def test_comparison_rating_and_conclusion_are_never_causal_recommendations(tmp_path):
    _, snapshot, _ = plan(tmp_path)
    classification = rating_classification(snapshot, SDXL)
    assert classification["record_kind"] == "learning_model_comparison_rating"
    assert classification["causal_one_variable"] is False
    engine = RecommendationEngine(tmp_path / "unused.jsonl")
    assert engine._score_records([{"metadata": classification}]) == []
    disguised = {
        "record_kind": "learning_experiment_rating",
        "frozen_experiment": {"snapshot": snapshot},
    }
    assert engine._score_records([{"metadata": disguised}]) == []
    conclusion = build_experiment_conclusion(
        [
            LearningVariant(param_value=SDXL, image_refs=["a"]),
            LearningVariant(param_value=KLEIN, image_refs=["b"]),
        ],
        {"a": {"overall_rating": 5}, "b": {"overall_rating": 3}},
        {},
        study_type="model_comparison",
    )
    assert conclusion["best_value"] == SDXL
    assert conclusion["causal_one_variable"] is False
    assert "frozen target envelope" in conclusion["message"]


def test_path_safe_diagnostics_and_distinct_candidate_identity(tmp_path):
    assert candidate_models(["C:/assets/a.safetensors", "D:/assets/b.safetensors"])
    with pytest.raises(ValueError, match="distinct"):
        candidate_models(["C:/assets/a.safetensors", "D:/assets/a.safetensors"])


@pytest.mark.parametrize("models", [[SDXL, "peer.safetensors"], [SDXL, KLEIN]])
def test_njr_audit_and_actual_atomic_jobservice_boundary(tmp_path, models):
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
    from src.learning.execution_controller import LearningExecutionController
    from src.pipeline.job_models_v2 import CURRENT_NJR_SCHEMA_VERSION
    from src.utils.embedding_prompt_utils import render_embedding_reference

    exp = experiment(tmp_path, models=models, loras=[["adapter", 0.7]])
    original = (tmp_path / "pack.json").read_bytes()
    controller = controller_for(exp, baseline())
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records])
    )
    controller.pipeline_controller = object()
    controller.execution_controller = LearningExecutionController(
        controller.learning_state, service
    )
    controller.run_plan()
    assert service.submit_njrs.call_count == 1
    records = service.submit_njrs.call_args.args[0]
    backend = ForgeWebUIImageBackend(
        lora_resolver=lambda name: KleinLoraDecision(name, KleinLoraStatus.COMPATIBLE, "fixture")
    )
    for record, arm in zip(records, snapshot["model_comparison"]["arms"], strict=True):
        backend.validate_njr_intent(record, ["txt2img"])
        config = record.config
        for key in ("learning_experiment_id", "learning_variant_value", "learning_variable"):
            config.pop(key)
        assert config == arm["effective_config"]
        assert record.schema_version == CURRENT_NJR_SCHEMA_VERSION
        assert record.base_model == arm["effective_config"]["txt2img"]["model"]
        assert record.backend_options == arm["effective_backend_options"]
        assert record.positive_embeddings == tuple(
            render_embedding_reference(*p) for p in arm["effective_positive_embeddings"]
        )
        assert record.negative_embeddings == tuple(
            render_embedding_reference(*p) for p in arm["effective_negative_embeddings"]
        )
        assert [(t.name, t.weight) for t in record.lora_tags] == [
            tuple(p) for p in arm["effective_lora_tags"]
        ]
        assert record.config["global_prompt_policy_source"] == "frozen_njr"
    assert (tmp_path / "pack.json").read_bytes() == original


def test_ratings_persist_resume_review_and_cannot_recommend_models(tmp_path):
    from src.learning.learning_record import LearningRecordWriter

    exp = experiment(tmp_path)
    controller = controller_for(exp, baseline())
    controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    for index, variant in enumerate(controller.learning_state.plan):
        controller._build_variant_njr(variant, exp)
        variant.image_refs = [f"image-{index}.png"]
        controller.record_rating(variant.image_refs[0], 5 - index)
    rows = [json.loads(line) for line in (tmp_path / "ratings.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    for row in rows:
        metadata = row["metadata"]
        assert metadata["record_kind"] == "learning_model_comparison_rating"
        assert metadata["comparison_claim"] == "target_envelope_preference"
        assert metadata["causal_one_variable"] is False
        assert (
            row["base_config"]["prompt"]
            == metadata["model_comparison"]["executor_base_positive_prompt"]
        )
    assert controller._learning_record_writer.get_ratings_for_experiment(exp.experiment_id) == {
        "image-0.png": 5,
        "image-1.png": 4,
    }
    assert RecommendationEngine(tmp_path / "ratings.jsonl")._score_records(rows) == []
    assert controller.get_experiment_conclusion()["causal_one_variable"] is False
    resumed = LearningController(learning_state=LearningState())
    assert resumed.restore_resume_state(controller.export_resume_state())
    assert study_type(resumed.learning_state.current_experiment) == "model_comparison"


@pytest.mark.parametrize(
    "field",
    ["requested_base_seed", "requested_subseed", "requested_sample_count", "subseed_strength"],
)
def test_frozen_seed_request_cannot_change_after_preview(tmp_path, field):
    _, snapshot, _ = plan(tmp_path)
    snapshot["seed_policy"][field] = 999
    with pytest.raises(ValueError, match="seed|sample"):
        frozen_arm(snapshot, SDXL)


def test_disabled_negative_intent_is_retained_without_execution(tmp_path):
    config = baseline()
    config["pipeline"]["apply_global_negative_txt2img"] = False
    _, snapshot, _ = plan(tmp_path, config=config)
    source = snapshot["model_comparison"]["source_intent"]
    assert source["global_negative"] == "global negative"
    assert source["apply_global_negative"] is False
    assert (
        "global negative"
        not in snapshot["model_comparison"]["arms"][0]["executor_base_negative_prompt"]
    )


def test_baseline_inactive_features_do_not_become_requested(tmp_path):
    config = baseline()
    config["txt2img"]["controlnet"] = {"enabled": False}
    plan(tmp_path, config=config)


def test_serializer_preserves_owned_triggers_and_inline_tokens(tmp_path):
    from src.pipeline.prompt_pack_parser import PackRow
    from src.pipeline.resolution_layer import (
        adapt_pack_intent,
        render_pack_intent,
        resolve_pack_intent,
    )

    intent = resolve_pack_intent(
        pack_row=PackRow(
            quality_line="row_prose <lora:inline:0.3>",
            subject_template="",
            embeddings=(),
            lora_tags=(("row_prose", 0.6),),
            negative_embeddings=(),
            negative_phrases=(),
        ),
        actor_resolutions=[{"lora_name": "actor", "weight": 0.8, "trigger_phrase": "owned actor"}],
        style_lora={"lora_name": "style", "weight": 0.7, "trigger_phrase": "owned style"},
    )
    restored = pack_prompt_intent_from_dict(pack_prompt_intent_to_dict(intent))
    assert restored == intent
    assert {trigger.text for trigger in restored.triggers} == {"owned actor", "owned style"}
    adapted = adapt_pack_intent(
        restored,
        policy(KLEIN),
        lora_resolver=lambda name: KleinLoraDecision(name, KleinLoraStatus.INCOMPATIBLE, "fixture"),
    )
    rendered = render_pack_intent(adapted.intent)
    assert "owned actor" not in rendered.positive
    assert "owned style" not in rendered.positive
    assert "row_prose <lora:inline:0.3>" in rendered.positive


def test_bad_arm_builder_never_submits_surviving_arms(tmp_path):
    exp = experiment(tmp_path)
    controller = controller_for(exp, baseline())
    controller.pipeline_controller = object()
    submit = Mock()
    controller.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    original = controller._build_variant_njr
    calls = []

    def build(variant, experiment):
        calls.append(variant.param_value)
        if variant.param_value == KLEIN:
            raise ValueError("bad arm")
        return original(variant, experiment)

    controller._build_variant_njr = build
    with pytest.raises(ValueError, match="bad arm"):
        controller.run_plan()
    assert calls == [SDXL, KLEIN]
    submit.assert_not_called()


def test_one_cached_registry_instance_and_no_refresh_scan_hash(tmp_path, monkeypatch):
    calls = []

    class Registry:
        webui_root = "fixture"

        def __init__(self):
            calls.append("create")

        def cached_snapshot(self):
            calls.append("snapshot")
            return SimpleNamespace(records={})

        def refresh(self):
            pytest.fail("registry refresh during preview")

    monkeypatch.setattr("src.assets.AssetRegistry", Registry)
    monkeypatch.setattr(
        "src.image_backends.model_policy.RegistryFamilyLookup.__call__",
        lambda self, name: (self._get_registry().cached_snapshot(), family(name))[1],
    )
    exp = experiment(tmp_path, models=[SDXL, "peer.safetensors"])
    evidence = CompileEvidence()
    build_comparison_snapshot(exp, baseline(), evidence=evidence)
    assert calls.count("create") == 1
    assert evidence.policy_lookups == 2
