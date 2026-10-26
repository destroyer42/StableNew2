"""PR-LEARN-PROMPT-MODEL-710: bounded Prompt x Model matrix - freeze, refuse, admit, reconcile, describe.

No WebUI, GPU or image generation. Models are resolved through the same fixtures Model Comparison uses, the controller is
the real ``LearningController`` over a recording JobService, and the aesthetic-embedding prohibition is proved both on the
frozen records and against the executor's own payload hook.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from src.gui.learning_state import LearningExperiment, LearningVariant
from src.learning import prompt_model_matrix as pmm
from src.learning.experiment_conclusion import build_experiment_conclusion
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.learning_controller_services.controlled_studies import (
    LOCAL_ONLY_STUDIES,
    service_for,
)
from src.learning.prompt_model_matrix import (
    STUDY_TYPE,
    build_matrix_snapshot,
    frozen_cell,
    materialize_njr,
)
from src.learning.prompt_slot_experiment import PromptSlotDesign
from src.pipeline.compile_evidence import CompileEvidence
from tests.learning_v2.test_learning_independent_baseline_650 import PEER, Bench
from tests.learning_v2.test_model_comparison_140 import KLEIN, SDXL, baseline, family

TEMPLATE = "A knight, [[expression]], natural lighting."
CANDIDATES = ("calm and confident", "angry and battle-ready", "exhausted but determined")


def config(**overrides):
    result = baseline()
    result["prompt_optimizer"] = {"enabled": False}
    for key, value in overrides.items():
        result[key] = value
    return result


def design(candidates=CANDIDATES, images=1, **kwargs):
    return PromptSlotDesign(
        TEMPLATE, "expression", tuple(candidates), kwargs.pop("fixed", {}), images
    )


def experiment(models=(SDXL, PEER), images=1):
    return LearningExperiment(
        name="matrix",
        experiment_id="mx",
        stage="txt2img",
        images_per_value=images,
        metadata={"selected_models": list(models)},
    )


def build(models=(SDXL, PEER), *, base=None, negative="bad hands", images=1, **kwargs):
    candidates = kwargs.pop("candidates", CANDIDATES)
    return build_matrix_snapshot(
        experiment(models, images),
        base or config(),
        design=design(candidates, images),
        negative=negative,
        evidence=CompileEvidence(family_lookup=family),
        **kwargs,
    )


def cells(snapshot):
    return snapshot[STUDY_TYPE]["cells"]


def variant(snapshot, index, **kwargs):
    return LearningVariant(
        experiment_id=snapshot["experiment_id"],
        variant_id=f"{snapshot['experiment_id']}:{index}",
        param_value=snapshot["variant_values"][index],
        **kwargs,
    )


def njr(snapshot, index=0):
    return materialize_njr(
        snapshot,
        variant(snapshot, index),
        metadata_factory=lambda config: {},
        output_dir="out",
        filename_template="{seed}",
    )


# -- contract, bounds and identity ------------------------------------------------------------------------------


def test_golden_3x2_freezes_row_major_cells_without_queueing():
    snapshot = build()
    study = snapshot[STUDY_TYPE]
    assert snapshot["study_type"] == "prompt_model_matrix"
    assert study["contract"] == "learning_prompt_model_matrix/1"
    assert study["comparison_claim"] == "prompt_by_target_envelope_preference"
    assert study["causal_one_variable"] is False
    assert study["seed_interpretation"] == (
        "same requested seed cohort; latent and noise semantics may differ between models"
    )
    assert study["settings_notice"].startswith(
        "Each model uses its own validated execution settings."
    )
    assert (study["total_cells"], study["total_images"]) == (6, 6)
    assert [(c["row"], c["col"], c["prompt_label"], c["model_label"]) for c in cells(snapshot)] == [
        (0, 0, "A", "Model 1"),
        (0, 1, "A", "Model 2"),
        (1, 0, "B", "Model 1"),
        (1, 1, "B", "Model 2"),
        (2, 0, "C", "Model 1"),
        (2, 1, "C", "Model 2"),
    ]
    assert len({c["cell_id"] for c in cells(snapshot)}) == 6
    assert snapshot["variant_values"] == [pmm.coordinate(c) for c in cells(snapshot)]
    assert all(study["digest"] == pmm._study_digest(study) for _ in [0])


def test_prompt_text_and_model_paths_never_enter_cell_coordinates():
    snapshot = build()
    text = json.dumps(snapshot["variant_values"])
    assert "knight" not in text and "safetensors" not in text and "calm" not in text


def test_each_cell_executes_its_prompt_with_its_model_and_a_shared_seed_cohort():
    snapshot = build()
    records = [njr(snapshot, i) for i in range(6)]
    assert [r.stages[0].model for r in records] == [SDXL, PEER] * 3
    assert len({r.positive_prompt for r in records}) == 3
    assert {r.seed for r in records} == {snapshot["seed_policy"]["requested_base_seed"]}
    assert {r.workload.images_per_prompt for r in records} == {1}
    assert [r.positive_prompt for r in records[::2]] == [
        f"A knight, {c}, natural lighting." for c in CANDIDATES
    ]


def test_cells_within_a_model_share_settings_and_only_the_prompt_differs():
    snapshot = build()
    for col in (0, 1):
        configs = [
            copy.deepcopy(c["arm"]["effective_config"]) for c in cells(snapshot) if c["col"] == col
        ]
        for item in configs:
            for key in ("prompt", "negative_prompt"):
                item.pop(key, None)
                item["txt2img"].pop(key, None)
        assert all(item == configs[0] for item in configs)


@pytest.mark.parametrize(
    "prompts,models,images",
    [(1, 2, 1), (5, 2, 1), (2, 1, 1), (2, 5, 1), (2, 2, 0), (2, 2, 4)],
)
def test_bounds_refuse_without_truncating(prompts, models, images):
    with pytest.raises(ValueError):
        pmm.check_bounds(prompts, models, images)


def test_total_image_and_cell_limits_are_exact():
    pmm.check_bounds(4, 3, 3)  # 12 cells, 36 images
    with pytest.raises(ValueError, match="36"):
        pmm.check_bounds(4, 4, 3)
    assert pmm.plan_summary(4, 4, 2) == (16, 32)


def test_five_prompt_candidates_are_refused_not_truncated():
    with pytest.raises(ValueError, match="no candidates were truncated"):
        build(candidates=("a", "b", "c", "d", "e"))


def test_fixed_values_are_required_for_every_other_slot():
    with pytest.raises(ValueError, match="fixed value"):
        build_matrix_snapshot(
            experiment(),
            config(),
            design=PromptSlotDesign("[[a]] and [[b]]", "a", ("one", "two"), {}, 1),
            evidence=CompileEvidence(family_lookup=family),
        )
    snapshot = build_matrix_snapshot(
        experiment(),
        config(),
        design=PromptSlotDesign("[[a]] and [[b]]", "a", ("one", "two"), {"b": "fixed"}, 1),
        evidence=CompileEvidence(family_lookup=family),
    )
    assert [c["arm"]["executor_base_positive_prompt"] for c in cells(snapshot)[::2]] == [
        "one and fixed",
        "two and fixed",
    ]


def test_duplicate_models_and_candidates_refuse():
    with pytest.raises(ValueError, match="distinct"):
        build(models=(SDXL, SDXL))
    with pytest.raises(ValueError, match="distinct"):
        build(candidates=("same", "same "))


def test_native_pack_row_is_the_prompt_source(tmp_path):
    from src.promptpacks.storage import load_prompt_pack_document, prompt_pack_row_by_index

    path = tmp_path / "pack.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "p",
                    "slots": [
                        {
                            "index": 0,
                            "text": "a knight in [[place]] at [[time]]",
                            "negative": "ugly",
                        }
                    ],
                    "matrix": {"mode": "sequential", "slots": []},
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )
    row = prompt_pack_row_by_index(load_prompt_pack_document(str(path)), 0)
    snapshot = build_matrix_snapshot(
        experiment(),
        config(),
        design=PromptSlotDesign(
            row.quality_line + " " + row.subject_template,
            "place",
            ("forest", "sea"),
            {"time": "dawn"},
            1,
        ),
        row=row,
        source={"kind": "pack", "row_index": 0},
        evidence=CompileEvidence(family_lookup=family),
    )
    positives = [c["arm"]["executor_base_positive_prompt"] for c in cells(snapshot)[::2]]
    assert all("dawn" in text for text in positives)
    assert "forest" in positives[0] and "sea" in positives[1]
    assert "ugly" in cells(snapshot)[0]["arm"]["executor_base_negative_prompt"]


# -- refusals: nothing is dropped, transformed or silently normalized -------------------------------------------


def test_unsupported_negative_refuses_the_whole_study():
    with pytest.raises(ValueError, match="(?i)model 2.*negative"):
        build(models=(SDXL, KLEIN))


def test_exact_profile_model_is_admitted_when_no_negative_is_requested():
    base = config()
    base["pipeline"]["apply_global_negative_txt2img"] = False
    base["global_negative_prompt"] = ""
    snapshot = build(models=(SDXL, KLEIN), base=base, negative="")
    sampling = {
        c["col"]: (
            c["arm"]["effective_config"]["txt2img"]["steps"],
            c["arm"]["effective_config"]["txt2img"]["sampler_name"],
        )
        for c in cells(snapshot)
    }
    assert 0 in sampling and 1 in sampling  # each model keeps its own validated settings
    assert len({c["arm"]["selected_model"] for c in cells(snapshot)}) == 2


def test_candidates_that_collapse_under_adaptation_refuse(monkeypatch):
    real = pmm.build_arm

    def collapsing(**kwargs):
        arm = real(**kwargs)
        if arm["matrix_cell"]["model_index"] == 1:
            arm["executor_base_positive_prompt"] = "same prompt"
        return arm

    monkeypatch.setattr(pmm, "build_arm", collapsing)
    with pytest.raises(ValueError, match="collapse.*Model 2"):
        build()


def test_candidates_that_lose_distinguishing_content_refuse(monkeypatch):
    real = pmm.build_arm

    def lossy(**kwargs):
        arm = real(**kwargs)
        arm["adapted_positive_prompt"] = "A knight"
        return arm

    monkeypatch.setattr(pmm, "build_arm", lossy)
    with pytest.raises(ValueError, match="loses its distinguishing content"):
        build()


@pytest.mark.parametrize(
    "mutate,name",
    [
        (lambda c: c["pipeline"].update(img2img_enabled=True), "img2img"),
        (lambda c: c["pipeline"].update(adetailer_enabled=True), "adetailer"),
        (lambda c: c["pipeline"].update(upscale_enabled=True), "upscale"),
        (lambda c: c["txt2img"].update(enable_hr=True), "hires"),
        (lambda c: c["txt2img"].update(refiner_enabled=True), "refiner"),
        (lambda c: c.update(controlnet={"enabled": True}), "ControlNet"),
        (lambda c: c["txt2img"].update(hypernetwork="x"), "hypernetwork"),
        (lambda c: c.update(prompt_optimizer={"enabled": True}), "optimizer"),
        (lambda c: c.update(lora_override={"name": "x", "weight": 1}), "LoRA"),
        (lambda c: c["txt2img"].update(lora_strengths=[{"name": "x", "weight": 1}]), "LoRA"),
    ],
)
def test_secondary_stages_and_structured_conditioning_are_refused(mutate, name):
    base = config()
    mutate(base)
    with pytest.raises(ValueError, match=name):
        build(base=base)


@pytest.mark.parametrize("models", [(SDXL, PEER), (SDXL, KLEIN), (KLEIN, PEER)])
@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(aesthetic={"enabled": True, "mode": "prompt", "embedding": "aes"}),
        lambda c: c.update(aesthetic={"enabled": True, "mode": "script"}),
        lambda c: c.update(aesthetic={"enabled": True, "mode": "prompt", "text": "pretty"}),
        lambda c: c["txt2img"].update(aesthetic={"enabled": True}),
        lambda c: c.update(aesthetic_enabled=True),
        lambda c: c["txt2img"].update(aesthetic_enabled=True),
        lambda c: c.update(aesthetic=True),
    ],
)
def test_aesthetic_conditioning_is_refused_for_every_model_candidate(models, mutate):
    base = config()
    mutate(base)
    with pytest.raises(ValueError, match="aesthetic"):
        build(models=models, base=base, negative="")


def test_a_disabled_aesthetic_section_is_allowed_and_cannot_reach_the_executor_fallback():
    from src.pipeline.executor import Pipeline

    base = config()
    base["aesthetic"] = {"enabled": False, "mode": "prompt", "embedding": "aes", "text": "pretty"}
    snapshot = build(base=base)
    for index in range(6):
        record = njr(snapshot, index)
        full = {"aesthetic": {"enabled": False}, **dict(record.workload.config)}
        assert pmm.aesthetic_conditioning_requested(full) is False
        payload = {"prompt": record.positive_prompt, "negative_prompt": record.negative_prompt}
        prompt, negative = Pipeline._apply_aesthetic_to_payload(
            SimpleNamespace(), payload, dict(record.workload.config)
        )
        assert (prompt, negative) == (record.positive_prompt, record.negative_prompt)
        assert "<embedding:" not in prompt and "<embedding:" not in negative


def test_no_frozen_cell_can_enable_the_aesthetic_embedding_fallback():
    snapshot = build()
    for cell in cells(snapshot):
        assert pmm.aesthetic_conditioning_requested(cell["arm"]["effective_config"]) is False
        assert "<" not in cell["arm"]["executor_base_positive_prompt"]
    assert pmm.aesthetic_conditioning_requested(snapshot["baseline_config"]) is False


def test_a_resealed_snapshot_with_aesthetic_conditioning_is_still_refused():
    snapshot = build()
    forged = copy.deepcopy(snapshot)
    arm = forged[STUDY_TYPE]["cells"][0]["arm"]
    arm["effective_config"]["aesthetic"] = {"enabled": True, "mode": "prompt", "embedding": "aes"}
    arm["arm_sha256"] = pmm.digest({k: v for k, v in arm.items() if k != "arm_sha256"})
    forged[STUDY_TYPE]["digest"] = pmm._study_digest(forged[STUDY_TYPE])
    with pytest.raises(ValueError, match="excluded conditioning|aesthetic"):
        frozen_cell(forged, forged["variant_values"][0])
    with pytest.raises(ValueError):
        njr(forged, 0)


@pytest.mark.parametrize(
    "text",
    [
        "<embedding:bad>",
        "embedding: bad",
        "<lora:x:1>",
        "<hypernet:x:1>",
        "(weighted:1.2)",
        "[[nested]]",
    ],
)
def test_embedding_lora_and_directive_text_cannot_be_introduced(text):
    with pytest.raises(ValueError):
        build(candidates=("ordinary", text))


def test_registered_embedding_names_cannot_be_introduced():
    with pytest.raises(ValueError, match="registered embedding"):
        build(candidates=("ordinary", "with badhandv4 here"), embedding_names=("badhandv4",))


def test_pack_rows_with_loras_or_embeddings_are_refused(tmp_path):
    from src.promptpacks.storage import load_prompt_pack_document, prompt_pack_row_by_index

    for extra in (
        {"loras": [["style", 0.8]]},
        {"positive_embeddings": ["pos_embed"]},
        {"negative_embeddings": ["neg_embed"]},
    ):
        path = tmp_path / f"pack{len(extra)}{next(iter(extra))}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "pack_data": {
                        "name": "p",
                        "slots": [{"index": 0, "text": "a knight in [[place]]", **extra}],
                        "matrix": {"mode": "sequential", "slots": []},
                    },
                    "preset_data": {},
                }
            ),
            encoding="utf-8",
        )
        row = prompt_pack_row_by_index(load_prompt_pack_document(str(path)), 0)
        with pytest.raises(ValueError, match="LoRA|embedding"):
            build_matrix_snapshot(
                experiment(),
                config(),
                design=PromptSlotDesign("a knight in [[place]]", "place", ("forest", "sea"), {}, 1),
                row=row,
                source={"kind": "pack"},
                evidence=CompileEvidence(family_lookup=family),
            )


def test_structured_global_prompt_text_is_refused():
    base = config()
    base["pipeline"]["apply_global_positive_txt2img"] = True
    base["global_positive_prompt"] = "masterpiece <embedding:aes>"
    with pytest.raises(ValueError, match="structured conditioning"):
        build(base=base)


def test_img2img_and_missing_geometry_refuse():
    exp = experiment()
    exp.input_image_path = "x.png"
    with pytest.raises(ValueError, match="txt2img only"):
        build_matrix_snapshot(
            exp, config(), design=design(), evidence=CompileEvidence(family_lookup=family)
        )
    base = config()
    base["txt2img"].pop("width")
    with pytest.raises(ValueError, match="width and height"):
        build(base=base)


def test_unqualified_model_refuses_with_its_label():
    with pytest.raises(ValueError, match="(?i)model 2"):
        build(models=(SDXL, "sd1"))


# -- frozen integrity ---------------------------------------------------------------------------------------------


def test_tampered_prompt_is_detected_before_admission():
    snapshot = build()
    forged = copy.deepcopy(snapshot)
    forged[STUDY_TYPE]["cells"][0]["arm"]["executor_base_positive_prompt"] = "changed"
    with pytest.raises(ValueError, match="integrity"):
        njr(forged, 0)


def test_variant_outside_the_frozen_cells_is_refused():
    snapshot = build()
    outsider = dict(snapshot["variant_values"][0], cell_id="f" * 20)
    with pytest.raises(ValueError, match="outside"):
        frozen_cell(snapshot, outsider)


def test_compiled_input_drift_is_refused():
    snapshot = build()
    forged = copy.deepcopy(snapshot)
    forged[STUDY_TYPE]["cells"][0]["compiled"]["input_digest"] = "0" * 64
    forged[STUDY_TYPE]["digest"] = pmm._study_digest(forged[STUDY_TYPE])
    with pytest.raises(ValueError, match="differs from the frozen Preview"):
        njr(forged, 0)


def test_snapshot_round_trips_through_the_session_codec():
    snapshot = build()
    again = thaw_snapshot(freeze_snapshot(snapshot))
    assert again == snapshot
    assert njr(again, 3).stages[0].model == PEER


def test_model_comparison_helpers_keep_their_contract():
    """The shared arm helpers the matrix reuses must not change Model Comparison's own record kind."""
    from src.learning import model_comparison as mc

    assert mc.RECORD_KIND == "learning_model_comparison_rating"
    assert pmm.RECORD_KIND == "learning_prompt_model_matrix_rating"
    assert pmm.RECORD_KIND != mc.RECORD_KIND


# -- reconciliation: per-cell proof ------------------------------------------------------------------------------


def completed_variant(
    snapshot, index=0, *, model=None, positive=None, negative=None, executed=True
):
    cell = cells(snapshot)[index]
    arm = cell["arm"]
    record = njr(snapshot, index)
    v = variant(snapshot, index, job_id="job-1")
    v.executed_config = copy.deepcopy(dict(record.workload.config)) if executed else {}
    v.executed_config.update(
        prompt=arm["executor_base_positive_prompt"],
        negative_prompt=arm["executor_base_negative_prompt"],
    )
    readback = {
        "final_prompt": cell["compiled"]["expected_positive"] if positive is None else positive,
        "final_negative_prompt": cell["compiled"]["expected_negative"]
        if negative is None
        else negative,
    }
    payload = {
        **readback,
        "config": {
            "override_settings": {
                "sd_model_checkpoint": model or arm["effective_config"]["txt2img"]["model"]
            }
        },
    }
    return v, readback, payload


def test_readback_proves_prompt_and_model():
    snapshot = build()
    v, readback, payload = completed_variant(snapshot, 1)
    assert pmm.readback_reason(snapshot, v, readback, payload, {}) == ""
    assert pmm.execution_evidence(snapshot, payload, {})["runtime_model_readback"]


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"positive": "other"}, "matrix_prompt_readback_mismatch"),
        ({"negative": "other"}, "matrix_prompt_readback_mismatch"),
        ({"model": "wrong.safetensors"}, "matrix_model_readback_mismatch"),
    ],
)
def test_mismatched_readback_is_uncontrolled(kwargs, reason):
    snapshot = build()
    v, readback, payload = completed_variant(snapshot, 0, **kwargs)
    assert pmm.readback_reason(snapshot, v, readback, payload, {}) == reason


def test_unavailable_readback_is_unproven_not_assumed():
    snapshot = build()
    v, readback, payload = completed_variant(snapshot, 0)
    assert pmm.readback_reason(snapshot, v, {}, payload, {}) == "matrix_prompt_readback_unavailable"
    assert pmm.readback_reason(snapshot, v, readback, {}, {}) == "matrix_model_readback_unavailable"


def test_cell_job_identity_must_match():
    snapshot = build()
    v, readback, payload = completed_variant(snapshot, 0)
    v.variant_id = "mx:3"
    assert pmm.readback_reason(snapshot, v, readback, payload, {}) == "matrix_identity_unverified"
    v.variant_id, v.job_id = "mx:0", ""
    assert pmm.readback_reason(snapshot, v, readback, payload, {}) == "matrix_identity_unverified"


def test_executed_config_conflict_is_detected():
    snapshot = build()
    v, readback, payload = completed_variant(snapshot, 0)
    v.executed_config["prompt"] = "tampered"
    assert (
        pmm.readback_reason(snapshot, v, readback, payload, {})
        == "matrix_compiled_context_conflict"
    )


def test_other_studies_are_not_affected_by_matrix_reconciliation():
    assert pmm.readback_reason({"study_type": "controlled_variable"}, None, {}) == ""
    assert pmm.execution_evidence({"study_type": "controlled_variable"}, {}, {}) == {}


def test_completion_evidence_marks_a_wrong_model_uncontrolled():
    from src.learning.experiment_reconciliation import completion_evidence

    snapshot = build()
    exp = experiment()
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    seeds = snapshot["seed_policy"]
    for label, model, expected in (
        ("ok", None, "completed"),
        ("bad", "wrong.safetensors", "uncontrolled"),
    ):
        v, readback, payload = completed_variant(snapshot, 0, model=model)
        result = {
            "metadata": {},
            "variants": [payload],
            "all_seeds": [seeds["requested_base_seed"]],
            "all_subseeds": [seeds["requested_subseed"]],
        }
        evidence = completion_evidence(copy.deepcopy(exp), v, result)
        assert evidence.status == expected, label
        assert evidence.execution_metadata["controlled_evidence_valid"] is (expected == "completed")
        assert evidence.execution_metadata["variable_validation_reason"] == (
            "valid" if expected == "completed" else "matrix_model_readback_mismatch"
        )


# -- ratings, isolation and results ------------------------------------------------------------------------------


def test_rating_evidence_is_compact_cell_scoped_and_never_one_variable():
    snapshot = build()
    value = snapshot["variant_values"][2]
    record = pmm.rating_classification(
        snapshot,
        value,
        {
            "controlled_evidence_valid": True,
            "variable_validation_reason": "valid",
            "actual_all_seeds": [5],
            "runtime_prompt_readback": {"final_prompt": "p"},
        },
        image_ref="a.png",
        image_refs=["a.png"],
    )
    assert record["record_kind"] == "learning_prompt_model_matrix_rating"
    assert record["comparison_claim"] == "prompt_by_target_envelope_preference"
    assert record["causal_one_variable"] is False
    evidence = record["prompt_model_matrix"]
    assert evidence["cell_id"] == value["cell_id"]
    assert (evidence["prompt_label"], evidence["model_label"]) == ("B", "Model 1")
    assert evidence["sample_index"] == 0 and evidence["actual_seed"] == 5
    assert evidence["controlled_evidence_valid"] is True
    assert evidence["prompt_readback_status"] == evidence["model_readback_status"] == "matched"
    assert evidence["seed_interpretation"] == pmm.SEED_INTERPRETATION
    for key in ("prompt_effective_digest", "model_context_digest", "arm_sha256", "study_digest"):
        assert len(evidence[key]) == 64
    assert "knight" not in json.dumps(record) and "safetensors" not in json.dumps(record)


def test_uncontrolled_rating_evidence_names_the_unproven_readback():
    snapshot = build()
    record = pmm.rating_classification(
        snapshot,
        snapshot["variant_values"][0],
        {
            "controlled_evidence_valid": False,
            "variable_validation_reason": "matrix_model_readback_mismatch",
        },
        image_ref="a.png",
        image_refs=["a.png"],
    )
    evidence = record["prompt_model_matrix"]
    assert evidence["controlled_evidence_valid"] is False
    assert evidence["model_readback_status"] == "mismatch"


def test_matrix_is_experiment_local_and_isolated_from_inference():
    assert "prompt_model_matrix" in LOCAL_ONLY_STUDIES
    assert service_for("prompt_model_matrix") is not None
    from src.learning.recommendation_engine import RecommendationEngine

    engine = RecommendationEngine.__new__(RecommendationEngine)
    record = {
        "metadata": {
            "study_type": "prompt_model_matrix",
            "record_kind": pmm.RECORD_KIND,
            "user_rating": 5,
            "variable_under_test": "Prompt x Model",
        }
    }
    scored = RecommendationEngine._score_records(engine, [record])
    assert scored == []


def scored_plan(snapshot, ratings_by_cell):
    plan, details = [], {}
    for index, cell in enumerate(cells(snapshot)):
        v = variant(snapshot, index, image_refs=[f"{cell['cell_id']}.png"], status="completed")
        v.execution_metadata = {"controlled_evidence_valid": True}
        plan.append(v)
        value = ratings_by_cell.get(index)
        if value:
            details[f"{cell['cell_id']}.png"] = {"overall_rating": value}
    return plan, details


def test_conclusion_is_descriptive_and_scoped_to_each_model():
    snapshot = build()
    plan, details = scored_plan(snapshot, {0: 5, 1: 2, 2: 3, 3: 4, 4: 1, 5: 4})
    result = build_experiment_conclusion(plan, details, {}, study_type="prompt_model_matrix")
    assert result["best_value"] is None  # never a global winner
    assert result["causal_one_variable"] is False
    assert result["comparison_claim"] == "prompt_by_target_envelope_preference"
    assert result["models"]["Model 1"]["best_prompts"] == ["A"]
    assert result["models"]["Model 2"]["status"] == "tie"
    assert result["models"]["Model 2"]["best_prompts"] == ["B", "C"]
    assert "Highest rated within this study" in result["models"]["Model 1"]["message"]
    assert "no global winner" in result["message"]
    assert "significance" in result["message"]


def test_conclusion_reports_insufficient_samples_and_excludes_uncontrolled_ratings():
    snapshot = build()
    plan, details = scored_plan(snapshot, {0: 5, 2: 3, 4: 4})
    result = build_experiment_conclusion(plan, details, {}, study_type="prompt_model_matrix")
    assert result["models"]["Model 2"]["status"] == "insufficient_samples"
    assert result["sufficient_evidence"] is False
    plan[0].execution_metadata = {"controlled_evidence_valid": False}
    result = build_experiment_conclusion(plan, details, {}, study_type="prompt_model_matrix")
    assert result["controlled_valid"] is False
    assert result["models"]["Model 1"]["status"] == "insufficient_samples"


def test_results_model_projects_prompts_by_models_and_hides_content():
    from src.learning.grid_results import build_grid_model

    snapshot = build()
    exp = experiment()
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    plan, details = scored_plan(snapshot, {0: 5})
    model = build_grid_model(exp, plan, details, visibility_mode="nsfw")
    assert (model.rows, model.cols) == (3, 2)
    assert model.x_labels == ("Model 1", "Model 2")
    assert model.y_labels == ("Prompt A", "Prompt B", "Prompt C")
    assert model.cell_at(1, 1).label == "Prompt B | Model 2"
    assert model.cell_at(0, 0).rating_summary.startswith("1/")
    assert model.planned_total == 6


def test_results_model_withholds_names_when_content_is_hidden():
    from src.learning.grid_results import build_grid_model

    snapshot = build(candidates=("explicit nsfw nude", "calm"))
    exp = experiment()
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    plan, details = scored_plan(snapshot, {})
    model = build_grid_model(exp, plan, details, visibility_mode="sfw")
    assert model.hidden is True
    assert "safetensors" not in model.subtitle
    assert all(not cell.images for cell in model.cells)


def test_results_model_refuses_two_variants_for_one_cell():
    from src.learning.grid_results import build_grid_model

    snapshot = build()
    exp = experiment()
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    plan, details = scored_plan(snapshot, {})
    plan.append(copy.deepcopy(plan[0]))
    with pytest.raises(ValueError, match="same matrix cell"):
        build_grid_model(exp, plan, details)


def test_preview_summary_has_no_prompt_text_or_paths_by_default():
    snapshot = build()
    text = pmm.preview_summary(snapshot)
    assert "Each model uses its own validated execution settings." in text
    assert "knight" not in text and "safetensors" not in text
    assert "6 cells" in text
    assert SDXL in pmm.preview_summary(snapshot, show_names=True)


def test_display_labels_are_path_free():
    value = build()["variant_values"][3]
    assert pmm.variant_label(value) == "Prompt B | Model 2"
    assert pmm.filename_label(value) == "pb-m2"
    from src.learning.two_axis_grid import filename_label, variant_label

    assert variant_label(value) == "Prompt B | Model 2"
    assert filename_label(value) == "pb-m2"


# -- controller: Preview queues nothing, Run is all-or-none and single-submit -----------------------------------


def matrix_spec(**extra):
    return {
        "template": TEMPLATE,
        "slot": "expression",
        "candidates": list(CANDIDATES),
        "negative_prompt": "bad hands",
        **extra,
    }


def preview(bench, *, models=(SDXL, PEER), images=1, spec=None, **extra):
    if not bench.controller.authoring_baseline():
        bench.controller.copy_pipeline_settings("txt2img")
    experiment = bench.design(
        variable="Prompt x Model",
        images=images,
        study_type="prompt_model_matrix",
        selected_models=list(models),
        prompt_model_matrix=spec or matrix_spec(),
        **extra,
    )
    bench.controller.build_plan(experiment)
    return bench.state.current_experiment


def test_golden_controller_preview_run_and_restore(tmp_path):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    experiment = preview(bench)
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    assert snapshot["study_type"] == STUDY_TYPE
    assert len(bench.state.plan) == 6
    assert not bench.service.submit_njrs.called  # Preview queues nothing
    bench.pipeline["txt2img"].update(
        model="changed", seed=9, steps=1
    )  # live edits never reach the frozen study
    jobs = bench.run()
    assert len(jobs) == 6 and bench.service.submit_njrs.call_count == 1
    assert sum(job.workload.images_per_prompt for job in jobs) == 6
    assert [job.stages[0].model for job in jobs] == [SDXL, PEER] * 3
    assert len({job.positive_prompt for job in jobs}) == 3
    assert {job.seed for job in jobs} == {snapshot["seed_policy"]["requested_base_seed"]}
    assert all(v.job_id for v in bench.state.plan)
    bench.controller.run_plan()  # duplicate click: nothing new is admitted
    assert bench.service.submit_njrs.call_count == 1
    restored = LearningExperiment.from_dict(experiment.to_dict())
    restored_variants = [LearningVariant.from_dict(v.to_dict()) for v in bench.state.plan]
    assert restored.execution_snapshot_json == experiment.execution_snapshot_json
    assert [v.job_id for v in restored_variants] == [v.job_id for v in bench.state.plan]
    assert [v.param_value for v in restored_variants] == snapshot["variant_values"]


def test_golden_controller_projects_the_results_model(tmp_path):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    preview(bench)
    model = bench.controller.get_grid_results_model("nsfw")
    assert (model.rows, model.cols) == (3, 2)


def test_aesthetic_conditioning_in_the_learning_baseline_refuses_preview_and_queues_nothing(
    tmp_path,
):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    bench.pipeline["aesthetic"] = {"enabled": True, "mode": "prompt", "embedding": "aes"}
    outcome = None
    try:
        preview(bench)
    except ValueError as exc:
        outcome = exc
    assert outcome is not None and "aesthetic" in str(outcome)
    assert not bench.service.submit_njrs.called
    assert not bench.state.plan


def test_oversized_design_refuses_preview(tmp_path):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    with pytest.raises(ValueError, match="36|images"):
        preview(
            bench,
            images=3,
            spec=matrix_spec(candidates=["a", "b", "c", "d"]),
            models=(SDXL, PEER, "third.safetensors", "fourth.safetensors"),
        )
    assert not bench.service.submit_njrs.called


def test_collapse_under_one_model_refuses_preview_and_queues_nothing(tmp_path, monkeypatch):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    real = pmm.build_arm

    def collapsing(**kwargs):
        arm = real(**kwargs)
        if arm["matrix_cell"]["model_index"] == 0:
            arm["executor_base_positive_prompt"] = "same"
        return arm

    monkeypatch.setattr(pmm, "build_arm", collapsing)
    with pytest.raises(ValueError, match="collapse"):
        preview(bench)
    assert not bench.service.submit_njrs.called and not bench.state.plan


def test_exact_profile_that_rejects_the_shared_geometry_queues_nothing(tmp_path):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    bench.pipeline["pipeline"]["apply_global_negative_txt2img"] = False
    bench.pipeline["global_negative_prompt"] = ""
    bench.pipeline["txt2img"].update(width=777, height=555)
    with pytest.raises(ValueError, match="geometry|Model 2|qualified"):
        preview(bench, models=(SDXL, KLEIN), spec=matrix_spec(negative_prompt=""))
    assert not bench.service.submit_njrs.called and not bench.state.plan


def test_run_compiles_all_cells_before_one_submit_or_admits_none(tmp_path, monkeypatch):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    preview(bench)
    real = pmm.materialize_njr
    calls = []

    def failing(snapshot, variant, **kwargs):
        calls.append(variant.param_value["cell_id"])
        if len(calls) == 4:
            raise ValueError("cell 4 cannot compile")
        return real(snapshot, variant, **kwargs)

    from src.learning.learning_controller_services import prompt_model_matrix as service

    monkeypatch.setattr(service, "materialize_njr", failing)
    with pytest.raises(ValueError, match="cell 4"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called
    assert all(not v.job_id for v in bench.state.plan)


def test_rating_record_for_a_cell_uses_the_matrix_record_kind(tmp_path):
    bench = Bench(tmp_path)
    bench.pipeline["prompt_optimizer"] = {"enabled": False}
    experiment = preview(bench)
    bench.run()
    target = bench.state.plan[3]
    target.image_refs = ["cell3.png"]
    target.execution_metadata = {
        "controlled_evidence_valid": True,
        "variable_validation_reason": "valid",
        "actual_all_seeds": [1],
    }
    record, _, _ = bench.controller.build_rating_record(
        experiment, target, "cell3.png", 4, "", None
    )
    metadata = record.metadata
    assert metadata["record_kind"] == "learning_prompt_model_matrix_rating"
    assert metadata["causal_one_variable"] is False
    assert metadata["prompt_model_matrix"]["cell_id"] == target.param_value["cell_id"]
