"""PR-LEARN-LORA-690: one designated LoRA position varies; everything else is frozen and proven.

L-numbers refer to the work package's deterministic matrix. No WebUI, GPU, model load or download: assets are a
fake registry resolver, JobService is a recording fake, and the Pipeline is a plain dict the tests mutate.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.image_backends.model_policy import FeaturePolicy, Support, resolve_model_policy
from src.learning import lora_composition as lc
from src.learning.lora_composition import (
    STATUS_AMBIGUOUS,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_MISSING,
    STATUS_UNCERTAIN,
    Candidate,
    LoraAsset,
    LoraCompositionDesign,
    freeze_candidates,
)
from tests.learning_v2.test_model_comparison_140 import SDXL, policy

KNIGHT = (
    "Cinematic portrait of a medieval knight, realistic face, detailed armor, natural lighting."
)
FIXED = "<lora:BetterThanWords:0.55>"
A, B, C = "CharacterStyle-A", "CharacterStyle-B", "CharacterStyle-C"


def sha(name: str) -> str:
    return hashlib.sha256(name.casefold().encode()).hexdigest()


def assets(**overrides: LoraAsset):
    def resolve(name: str) -> LoraAsset:
        found = overrides.get(name) or overrides.get(name.casefold())
        if found is not None:
            return found
        return LoraAsset(
            name,
            STATUS_COMPATIBLE,
            sha256=sha(name),
            family="sdxl",
            evidence="embedded_metadata:ss_base_model_version",
        )

    return resolve


def sdxl():
    return policy(SDXL)


def baseline() -> dict:
    from tests.learning_v2.test_learning_independent_baseline_650 import pipeline_config

    return pipeline_config()


def cands(*pairs) -> tuple[Candidate, ...]:
    return tuple(Candidate(name, weight) for name, weight in pairs)


def freeze(design: LoraCompositionDesign, *, resolver=None, pol=None, base=None, **kwargs):
    return freeze_candidates(
        design,
        pol or sdxl(),
        base if base is not None else baseline(),
        resolver=resolver or assets(),
        **kwargs,
    )


def add_design(prompt=KNIGHT + " " + FIXED, *, images=1, original=None, pairs=None):
    pairs = pairs or [(None, 0), (A, 0.5), (A, 0.8), (A, 1.0)]
    return LoraCompositionDesign(lc.ADD_REMOVE, prompt, cands(*pairs), original, images)


def loras(candidate: dict) -> list[tuple[str, float]]:
    return [(name, weight) for name, weight in candidate["expected_loras"]]


def stripped(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<lora:[^>]*>", "", text)).strip()


# -- B. Add / remove ------------------------------------------------------------------------------------------


def test_l11_l12_l13_l14_add_remove_is_a_true_control_and_fixed_neighbours_stay():
    frozen = freeze(add_design())
    one, two, three, four = frozen["candidates"]
    assert [c["label"] for c in frozen["candidates"]] == ["A", "B", "C", "D"]
    assert loras(one) == [("BetterThanWords", 0.55)]  # zero strength means absent, not <lora:..:0>
    assert "<lora:CharacterStyle-A" not in one["positive"] and ":0>" not in one["positive"]
    assert loras(two) == [("BetterThanWords", 0.55), (A, 0.5)]
    assert loras(three) == [("BetterThanWords", 0.55), (A, 0.8)]
    assert loras(four) == [("BetterThanWords", 0.55), (A, 1.0)]
    for candidate in frozen["candidates"]:
        assert candidate["positive"].count("<lora:BetterThanWords:0.55>") == 1
    assert [c["asset"] for c in frozen["candidates"]][0] is None
    assert frozen["candidates"][1]["asset"]["sha256"] == sha(A)


def test_l16_everything_outside_the_designated_contribution_is_identical():
    frozen = freeze(add_design(), negative="bad hands")
    assert len({stripped(c["positive"]) for c in frozen["candidates"]}) == 1
    assert {c["negative"] for c in frozen["candidates"]} == {"bad hands"}
    assert stripped(frozen["candidates"][0]["positive"]) == stripped(KNIGHT)


def test_l15_an_added_lora_cannot_duplicate_a_fixed_lora_unless_it_is_the_designated_original():
    prompt = KNIGHT + f" {FIXED} <lora:{A}:0.7>"
    with pytest.raises(ValueError, match="already in the prompt"):
        freeze(add_design(prompt))
    # Designating it makes it the tested position: every arm removes the baseline contribution first.
    frozen = freeze(add_design(prompt, original=A))
    assert loras(frozen["candidates"][0]) == [("BetterThanWords", 0.55)]
    assert loras(frozen["candidates"][2]) == [("BetterThanWords", 0.55), (A, 0.8)]


def test_zero_strength_collapses_to_no_lora_and_duplicates_are_refused():
    assert Candidate(A, 0).name is None and Candidate(A, 0).weight == 0
    with pytest.raises(ValueError, match="distinct"):
        freeze(add_design(pairs=[(None, 0), (A, 0)]))
    with pytest.raises(ValueError, match="distinct"):
        freeze(add_design(pairs=[(A, 0.5), (A, 0.5)]))


def test_add_remove_requires_one_lora_identity():
    with pytest.raises(ValueError, match="one LoRA"):
        freeze(add_design(pairs=[(None, 0), (A, 0.8), (B, 0.8)]))


# -- C. Replacement -------------------------------------------------------------------------------------------


def replace_design(prompt=None, pairs=None, original=A, images=1):
    prompt = prompt or f"{KNIGHT} <lora:{A}:0.8> {FIXED}"
    pairs = pairs or [(A, 0.8), (B, 0.8), (C, 0.8)]
    return LoraCompositionDesign(lc.REPLACE, prompt, cands(*pairs), original, images)


def test_l17_l18_l19_l20_replacement_removes_the_original_and_keeps_fixed_in_place():
    frozen = freeze(replace_design())
    control, swap_b, swap_c = frozen["candidates"]
    assert loras(control) == [
        (A, 0.8),
        ("BetterThanWords", 0.55),
    ]  # tested position keeps its place
    assert loras(swap_b) == [(B, 0.8), ("BetterThanWords", 0.55)]
    assert loras(swap_c) == [(C, 0.8), ("BetterThanWords", 0.55)]
    for candidate in (swap_b, swap_c):
        assert f"<lora:{A}" not in candidate["positive"]
        assert candidate["positive"].count("<lora:") == 2
    assert {c["weight"] for c in frozen["candidates"]} == {0.8}
    assert frozen["position"] == 0 and frozen["original"] == A


@pytest.mark.parametrize(
    "pairs,original,message",
    [
        ([(A, 0.8), (B, 0.6)], A, "same"),  # identity-only: strengths must match
        ([(None, 0), (B, 0.8)], A, "No LoRA"),  # removal belongs to Add / Remove
        ([(A, 0.8), (A, 0.8)], A, "distinct"),
        ([(A, 0.8), (B, 0.8)], "Missing", "baseline"),
        ([(B, 0.8), (C, 0.8)], A, "original"),  # no control arm: refused, not silently added
        ([(A, 0.5), (B, 0.5)], A, "baseline strength"),
    ],
)
def test_replace_refusals(pairs, original, message):
    with pytest.raises(ValueError, match=message):
        freeze(replace_design(pairs=pairs, original=original))


def test_l21_l22_original_reintroduced_by_another_source_is_refused():
    # A second inline source (row LoRA vs inline text) naming the same adapter is an ambiguous design.
    from src.pipeline.prompt_pack_parser import PackRow

    row = PackRow((), KNIGHT, f"<lora:{A}:0.7>", ((A, 0.8),), (), ())
    design = replace_design()
    with pytest.raises(ValueError, match="more than once"):
        freeze(design, row=row)


def test_l22_style_consistency_in_the_baseline_is_refused():
    base = baseline()
    base["style_lora"] = {"enabled": True, "style_id": "x", "weight": 0.7}
    with pytest.raises(ValueError, match="Style Consistency"):
        freeze(add_design(), base=base)


def test_l23_trigger_text_is_never_inserted_or_deleted():
    prompt = f"{KNIGHT} trigger-word-a, trigger-word-b {FIXED}"
    frozen = freeze(add_design(prompt))
    for candidate in frozen["candidates"]:
        assert "trigger-word-a, trigger-word-b" in candidate["positive"]
        assert candidate["positive"].count("trigger-word-a") == 1


def test_l24_deduplication_cannot_turn_an_invalid_design_into_another_experiment():
    for prompt in (
        f"{KNIGHT} {FIXED} <lora:BetterThanWords:0.55>",  # identical duplicate
        f"{KNIGHT} {FIXED} <lora:betterthanwords:0.7>",  # conflicting weight, different case
    ):
        with pytest.raises(ValueError, match="more than once"):
            freeze(add_design(prompt))


# -- Compare --------------------------------------------------------------------------------------------------


def compare_design(pairs=None, original=None, prompt=KNIGHT + " " + FIXED, images=1):
    pairs = pairs or [(None, 0), (A, 0.8), (B, 0.8), (C, 0.8)]
    return LoraCompositionDesign(lc.COMPARE, prompt, cands(*pairs), original, images)


def test_compare_candidates_at_a_common_strength_with_an_empty_control():
    frozen = freeze(compare_design())
    assert [loras(c)[-1][0] for c in frozen["candidates"][1:]] == [A, B, C]
    assert loras(frozen["candidates"][0]) == [("BetterThanWords", 0.55)]
    assert {c["weight"] for c in frozen["candidates"][1:]} == {0.8}
    assert len({c["effective_digest"] for c in frozen["candidates"]}) == 4


def test_compare_refuses_changing_identity_and_strength_together():
    with pytest.raises(ValueError, match="same"):
        freeze(compare_design([(None, 0), (A, 0.8), (B, 0.6)]))


# -- D. Freeze bounds -----------------------------------------------------------------------------------------


def test_l27_l28_two_to_eight_candidates_are_supported_and_oversize_is_refused_not_truncated():
    names = [f"Lora-{i}" for i in range(9)]
    freeze(compare_design([(n, 0.8) for n in names[:2]]))
    frozen = freeze(compare_design([(None, 0)] + [(n, 0.8) for n in names[:7]]))
    assert len(frozen["candidates"]) == 8
    with pytest.raises(ValueError, match="two to eight"):
        freeze(compare_design([(None, 0)] + [(n, 0.8) for n in names[:8]]))
    with pytest.raises(ValueError, match="two to eight"):
        freeze(compare_design([(A, 0.8)]))
    for images in (0, 4, True):
        with pytest.raises(ValueError, match="images"):
            freeze(compare_design(images=images))


def test_l26_ordering_and_identity_are_stable_and_digest_is_sealed():
    first = freeze(compare_design())
    again = freeze(compare_design())
    assert first == again and first["contract"] == "learning_lora_composition/1"
    reordered = freeze(compare_design([(None, 0), (B, 0.8), (A, 0.8), (C, 0.8)]))
    assert reordered["digest"] != first["digest"]
    assert [c["name"] for c in reordered["candidates"]] == [None, B, A, C]


# -- A. Installed assets and compatibility --------------------------------------------------------------------


@pytest.mark.parametrize(
    "asset_status,message",
    [
        (STATUS_MISSING, "not found"),
        (STATUS_AMBIGUOUS, "more than one"),
        (STATUS_INCOMPATIBLE, "incompatible"),
    ],
)
def test_l04_l05_l06_unusable_assets_refuse_a_controlled_preview(asset_status, message):
    bad = LoraAsset(B, asset_status, reason=f"{message} in the registry")
    with pytest.raises(ValueError, match=message):
        freeze(compare_design(), resolver=assets(**{B: bad}))
    with pytest.raises(ValueError, match=message):
        freeze(
            compare_design([(None, 0), (A, 0.8)], prompt=f"{KNIGHT} <lora:{B}:0.4>"),
            resolver=assets(**{B: bad}),
        )


def test_uncertain_compatibility_is_disclosed_not_promoted_and_hashless_assets_refuse():
    uncertain = LoraAsset(B, STATUS_UNCERTAIN, sha256=sha(B), reason="no family evidence")
    frozen = freeze(compare_design(), resolver=assets(**{B: uncertain}))
    assert frozen["candidates"][2]["asset"]["status"] == STATUS_UNCERTAIN
    assert frozen["compatibility_notes"]
    with pytest.raises(ValueError, match="identity"):
        freeze(compare_design(), resolver=assets(**{B: LoraAsset(B, STATUS_COMPATIBLE)}))


def test_l07_policy_limit_applies_to_the_whole_effective_set():
    base = sdxl()
    limited = replace(
        base, features={**base.features, "lora": FeaturePolicy(Support.SUPPORTED, 1, "", ())}
    )
    with pytest.raises(ValueError, match="limit"):
        freeze(add_design(), pol=limited)
    off = replace(base, features={**base.features, "lora": FeaturePolicy(Support.UNSUPPORTED)})
    with pytest.raises(ValueError, match="does not support"):
        freeze(add_design(), pol=off)


def test_unsupported_targets_optimizer_and_stage_loras_refuse():
    with pytest.raises(ValueError, match="registry-verified SDXL"):
        freeze(add_design(), pol=resolve_model_policy("unknown"))
    base = baseline()
    base["prompt_optimizer"] = {"enabled": True}
    with pytest.raises(ValueError, match="optimizer"):
        freeze(add_design(), base=base)
    base = baseline()
    base["txt2img"]["lora_strengths"] = [{"name": "Hidden", "strength": 0.4, "enabled": True}]
    with pytest.raises(ValueError, match="stage LoRA"):
        freeze(add_design(), base=base)
    base["txt2img"]["lora_strengths"] = [
        {"name": "BetterThanWords", "strength": 0.55, "enabled": True}
    ]
    freeze(add_design(), base=base)  # reconciled with the inline declaration: allowed


# -- E. Readback ------------------------------------------------------------------------------------------------


def snapshot_for(frozen: dict) -> dict:
    return {
        "study_type": lc.STUDY_TYPE,
        lc.STUDY_TYPE: frozen,
        "experiment_id": "e1",
        "variant_values": [c["label"] for c in frozen["candidates"]],
    }


def variant_for(frozen: dict, index: int, config=None):
    candidate = frozen["candidates"][index]
    return SimpleNamespace(
        param_value=candidate["label"],
        job_id=f"job-{index}",
        variant_id=f"e1:{index}",
        experiment_id="e1",
        executed_config=config
        if config is not None
        else {"prompt": candidate["positive"], "negative_prompt": candidate["negative"]},
        execution_metadata={},
    )


def readback_of(frozen, index, **changes):
    candidate = frozen["candidates"][index]
    value = {
        "final_prompt": candidate["expected_positive"],
        "final_negative_prompt": candidate["expected_negative"],
    }
    value.update(changes)
    return value


def reason(frozen, index, readback, *, bind=True):
    snapshot = snapshot_for(frozen)
    snapshot["compiled_lora_composition_plan"] = [
        {"config_digest": lc.digest(variant_for(frozen, i).executed_config)}
        for i in range(len(frozen["candidates"]))
    ]
    return lc.readback_reason(snapshot, variant_for(frozen, index), readback)


def test_l38_matching_full_set_readback_is_controlled():
    frozen = freeze(replace_design())
    assert reason(frozen, 1, readback_of(frozen, 1)) == ""


def test_l39_missing_readback_is_uncontrolled():
    frozen = freeze(replace_design())
    assert reason(frozen, 1, {}) == "lora_composition_readback_unavailable"


def test_l40_l41_removed_or_replaced_lora_still_present_is_uncontrolled():
    frozen = freeze(replace_design())
    expected = frozen["candidates"][1]["expected_positive"]
    kept = expected + f" <lora:{A}:0.8>"
    assert (
        reason(frozen, 1, readback_of(frozen, 1, final_prompt=kept))
        == "lora_composition_excluded_present"
    )
    no_lora = freeze(add_design())
    leaked = no_lora["candidates"][0]["expected_positive"] + f" <lora:{A}:0.5>"
    assert (
        reason(no_lora, 0, readback_of(no_lora, 0, final_prompt=leaked))
        == "lora_composition_excluded_present"
    )


def test_l42_l43_l44_strength_third_lora_and_duplicate_tokens():
    frozen = freeze(replace_design())
    expected = frozen["candidates"][1]["expected_positive"]
    changed = expected.replace("BetterThanWords:0.55", "BetterThanWords:0.9")
    assert (
        reason(frozen, 1, readback_of(frozen, 1, final_prompt=changed))
        == "lora_composition_strength_mismatch"
    )
    third = expected + " <lora:Unexpected:0.3>"
    assert (
        reason(frozen, 1, readback_of(frozen, 1, final_prompt=third))
        == "lora_composition_unexpected_lora"
    )
    duplicate = expected + f" <lora:{B}:0.8>"
    assert (
        reason(frozen, 1, readback_of(frozen, 1, final_prompt=duplicate))
        == "lora_composition_duplicate"
    )


def test_l45_l46_seed_and_launch_boundaries_go_through_existing_evidence(tmp_path):
    bench = _golden(tmp_path)
    bench.run()
    experiment = bench.state.current_experiment
    snap = _snapshot(experiment)
    variant = bench.state.plan[1]
    candidate = snap[lc.STUDY_TYPE]["candidates"][1]
    readback = {
        "final_prompt": candidate["expected_positive"],
        "final_negative_prompt": candidate["expected_negative"],
    }
    from src.learning.experiment_reconciliation import completion_evidence

    result = {
        "metadata": {**readback, "all_seeds": [101, 102, 103], "all_subseeds": [700, 701, 702]},
        "variants": [{**readback, "runtime_admission": {"launch_profile": "one"}}],
    }
    assert (
        completion_evidence(experiment, variant, result).execution_metadata[
            "controlled_evidence_valid"
        ]
        is True
    )
    wrong = copy.deepcopy(result)
    wrong["metadata"]["final_prompt"] = wrong["variants"][0]["final_prompt"] = (
        candidate["expected_positive"] + " <lora:X:1>"
    )
    proof = completion_evidence(experiment, variant, wrong)
    assert proof.execution_metadata["controlled_evidence_valid"] is False
    experiment.metadata.update(observed_seed_vector=[101, 102, 103], observed_launch_profile="one")
    seed = copy.deepcopy(result)
    seed["metadata"]["all_seeds"] = [101, 102, 104]
    assert (
        completion_evidence(experiment, variant, seed).execution_metadata[
            "controlled_evidence_valid"
        ]
        is False
    )
    launch = copy.deepcopy(result)
    launch["variants"][0]["runtime_admission"]["launch_profile"] = "two"
    assert (
        completion_evidence(experiment, variant, launch).execution_metadata[
            "controlled_evidence_valid"
        ]
        is False
    )


def test_l47_the_contract_does_not_claim_physical_lora_loading():
    frozen = freeze(add_design())
    limits = frozen["evidence_limits"]
    assert "prompt readback" in limits and "not independent proof" in limits


# -- Integration through the real LearningController ----------------------------------------------------------


def _bench(tmp_path, resolver=None):
    from tests.learning_v2.test_learning_independent_baseline_650 import Bench

    bench = Bench(tmp_path)
    bench.controller._learning_lora_asset_resolver = resolver or assets()
    bench.pipeline["txt2img"].update(
        seed=101,
        steps=30,
        cfg_scale=6,
        sampler_name="DPM++ 2M",
        scheduler="Karras",
        width=1024,
        height=1024,
    )
    return bench


def _spec(operation, pairs, original=None, **extra):
    return {
        "operation": operation,
        "original": original,
        "candidates": [{"name": name, "weight": weight} for name, weight in pairs],
        **extra,
    }


def _golden(tmp_path, **kwargs):
    bench = _bench(tmp_path, kwargs.pop("resolver", None))
    bench.preview(
        variable=lc.VARIABLE,
        images=3,
        study_type=lc.STUDY_TYPE,
        prompt=KNIGHT + " " + FIXED,
        custom_prompt=KNIGHT + " " + FIXED,
        lora_composition=_spec(lc.COMPARE, [(None, 0), (A, 0.8), (B, 0.8), (C, 0.8)]),
        **kwargs,
    )
    return bench


def _snapshot(experiment):
    from src.learning.experiment_execution import thaw_snapshot

    return thaw_snapshot(experiment.execution_snapshot_json)


def test_l25_l29_l30_l31_l32_l34_l36_l37_golden_preview_run_is_frozen_and_admitted_once(tmp_path):
    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    snapshot = _snapshot(experiment)
    assert snapshot["study_type"] == lc.STUDY_TYPE and snapshot["variant_values"] == [
        "A",
        "B",
        "C",
        "D",
    ]
    assert not bench.service.submit_njrs.called  # Preview queues nothing
    bench.pipeline["txt2img"].update(model="changed", seed=9, steps=1, cfg_scale=12)
    bench.controller.known_loras = lambda: ["changed"]
    jobs = bench.run()
    assert len(jobs) == 4 and sum(job.workload.images_per_prompt for job in jobs) == 12
    assert {job.seed for job in jobs} == {101} and {job.stages[0].steps for job in jobs} == {30}
    assert {job.stages[0].model for job in jobs} == {SDXL}
    assert (
        len({stripped(job.positive_prompt) for job in jobs}) == 1
    )  # only the LoRA contribution differs
    expected = [
        [("BetterThanWords", 0.55)],
        [("BetterThanWords", 0.55), (A, 0.8)],
        [("BetterThanWords", 0.55), (B, 0.8)],
        [("BetterThanWords", 0.55), (C, 0.8)],
    ]
    assert [[(t.name, t.weight) for t in job.provenance.lora_tags] for job in jobs] == expected
    from src.image_backends.forge_klein_lora import extract_lora_tags

    for job, want in zip(jobs, expected, strict=True):
        tags, _ = extract_lora_tags(job.positive_prompt)
        assert [(t.name, t.weight) for t in tags] == want
    assert bench.service.submit_njrs.call_count == 1
    bench.controller.run_plan()
    assert bench.service.submit_njrs.call_count == 1  # duplicate Run does not re-admit
    assert [v.variant_id for v in bench.state.plan] == [
        f"{experiment.experiment_id}:{i}" for i in range(4)
    ]
    assert len({v.job_id for v in bench.state.plan}) == 4


def test_l33_asset_identity_change_before_admission_refuses_everything(tmp_path):
    bench = _golden(tmp_path)
    bench.controller._learning_lora_asset_resolver = assets(
        **{B: LoraAsset(B, STATUS_COMPATIBLE, sha256="0" * 64, family="sdxl")}
    )
    with pytest.raises(ValueError, match="asset identity"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called
    bench.controller._learning_lora_asset_resolver = assets(
        **{B: LoraAsset(B, STATUS_MISSING, reason="gone")}
    )
    with pytest.raises(ValueError, match="asset identity"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


def test_l35_one_failed_candidate_admits_zero(tmp_path, monkeypatch):
    bench = _golden(tmp_path)
    from src.learning.learning_controller_services import lora_composition as service

    original = service._materialize

    def changed(*args):
        record = original(*args)
        if args[-1].param_value == "C":
            raise ValueError("simulated parity failure")
        return record

    monkeypatch.setattr(service, "_materialize", changed)
    with pytest.raises(ValueError, match="parity"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


def test_l01_l02_l03_a_registry_lora_absent_from_the_prompt_is_selectable_and_marked(tmp_path):
    bench = _golden(tmp_path)
    frozen = _snapshot(bench.state.current_experiment)[lc.STUDY_TYPE]
    assert [item["name"] for item in frozen["fixed"]] == ["BetterThanWords"]
    assert all(
        item["name"] not in {c["name"] for c in frozen["candidates"]} for item in frozen["fixed"]
    )
    assert frozen["candidates"][1]["asset"]["family"] == "sdxl"


def test_l10_preview_and_selection_do_not_touch_assets_or_pack_files(tmp_path):
    bench = _bench(tmp_path)
    asset = tmp_path / f"{A}.safetensors"
    asset.write_bytes(b"weights")
    before = (asset.read_bytes(), asset.stat().st_mtime_ns)
    bench.preview(
        variable=lc.VARIABLE,
        images=1,
        study_type=lc.STUDY_TYPE,
        custom_prompt=KNIGHT,
        lora_composition=_spec(lc.ADD_REMOVE, [(None, 0), (A, 0.8)]),
    )
    assert (asset.read_bytes(), asset.stat().st_mtime_ns) == before


def test_replace_golden_removes_a_in_every_other_arm(tmp_path):
    bench = _bench(tmp_path)
    bench.preview(
        variable=lc.VARIABLE,
        images=1,
        study_type=lc.STUDY_TYPE,
        custom_prompt=f"{KNIGHT} <lora:{A}:0.8> {FIXED}",
        lora_composition=_spec(lc.REPLACE, [(A, 0.8), (B, 0.8), (C, 0.8)], original=A),
    )
    jobs = bench.run()
    from src.image_backends.forge_klein_lora import extract_lora_tags

    names = [[t.name for t in extract_lora_tags(job.positive_prompt)[0]] for job in jobs]
    assert names == [[A, "BetterThanWords"], [B, "BetterThanWords"], [C, "BetterThanWords"]]
    assert all(A not in [t.name for t in job.provenance.lora_tags] for job in jobs[1:])


def test_native_pack_row_source_freezes_structured_loras(tmp_path):
    from tests.learning_v2.test_model_comparison_140 import experiment as write_pack

    write_pack(tmp_path, loras=[["BetterThanWords", 0.55]])
    path = tmp_path / "pack.json"
    before = path.read_bytes()
    bench = _bench(tmp_path)
    bench.preview(
        variable=lc.VARIABLE,
        images=1,
        study_type=lc.STUDY_TYPE,
        prompt_source="pack",
        selected_prompt_pack_path=str(path),
        selected_prompt_pack_name="study",
        selected_prompt_index=0,
        selected_prompt_text="row text",
        lora_composition=_spec(lc.COMPARE, [(None, 0), (A, 0.8)], fixed_slots={"place": "forest"}),
    )
    frozen = _snapshot(bench.state.current_experiment)[lc.STUDY_TYPE]
    assert [item["name"] for item in frozen["fixed"]] == ["BetterThanWords"]
    assert (
        "forest" in frozen["candidates"][0]["positive"]
        and "[[" not in frozen["candidates"][0]["positive"]
    )
    path.unlink()
    jobs = bench.run()
    assert len(jobs) == 2 and path.exists() is False
    assert before  # the PromptPack was never rewritten before removal


# -- F. Ratings, conclusion and isolation ---------------------------------------------------------------------


def _rated(tmp_path, ratings=(3, 5, 3, 3), valid=True):
    from src.learning.learning_record import LearningRecordWriter

    bench = _golden(tmp_path)
    bench.run()
    experiment = bench.state.current_experiment
    bench.controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    rows, details = [], {}
    for i, variant in enumerate(bench.state.plan):
        variant.status = "completed"
        variant.image_refs = [f"sample-{i}.png"]
        variant.completed_images = 1
        variant.execution_metadata.update(
            controlled_evidence_valid=valid,
            variable_validation_reason="valid",
            actual_all_seeds=[101, 102, 103],
        )
        record, _, _ = bench.controller.build_rating_record(
            experiment, variant, variant.image_refs[0], ratings[i], "", None
        )
        assert record.metadata["record_kind"] == "learning_experiment_rating"
        assert record.metadata["study_type"] == lc.STUDY_TYPE
        meta = record.metadata[lc.STUDY_TYPE]
        assert meta["candidate_label"] == chr(65 + i) and meta["operation"] == lc.COMPARE
        assert meta["expected_lora_digest"] and meta["fixed_digest"]
        assert bench.controller._learning_record_writer.append_record(record)
        rows.append(json.loads(record.to_json()))
        details[variant.image_refs[0]] = {"overall_rating": ratings[i]}
    return bench, rows, details


def test_l48_l49_l52_ratings_link_to_candidates_and_form_a_local_conclusion(tmp_path):
    bench, _rows, details = _rated(tmp_path)
    result = lc.conclusion(bench.state.plan, details, {})
    assert (
        result["best_value"] == "B"
        and result["saved"] == 4
        and result["sufficient_evidence"] is True
    )
    assert result["comparison_claim"] == "experiment_local_lora_preference"
    assert "Highest rated in this experiment" in result["message"]
    assert "physically" in result["message"] or "intent" in result["message"]


def test_l50_drafts_do_not_count_and_l51_ties_have_no_unique_winner(tmp_path):
    bench, _rows, details = _rated(tmp_path, ratings=(4, 4, 3, 3))
    assert lc.conclusion(bench.state.plan, details, {})["best_value"] is None
    assert (
        lc.conclusion(bench.state.plan, {}, {"draft:sample-1.png": {"overall_rating": 5}})["saved"]
        == 0
    )


def test_l53_uncontrolled_variants_support_no_preference(tmp_path):
    bench, _rows, details = _rated(tmp_path, valid=False)
    result = lc.conclusion(bench.state.plan, details, {})
    assert result["best_value"] is None and result["controlled_valid"] is False


def test_l54_l55_composition_ratings_never_recommend_or_publish(tmp_path):
    from src.generation_profiles.identity import ModelIdentityResolver
    from src.generation_profiles.store import GenerationProfileStore
    from src.learning.profile_publication import ProfilePublicationService
    from src.learning.recommendation_engine import RecommendationEngine

    bench, rows, _details = _rated(tmp_path)
    assert not bench.controller.get_recommendations_for_current_prompt()
    assert (
        not RecommendationEngine(tmp_path / "ratings.jsonl")
        .recommend(KNIGHT, "txt2img")
        .recommendations
    )
    resolver = ModelIdentityResolver(
        policy_resolver=lambda _: sdxl(), sha_lookup=lambda _: "a" * 64
    )
    proposal = ProfilePublicationService(
        GenerationProfileStore(tmp_path / "profiles"), resolver
    ).evaluate(rows, "test.safetensors")
    assert not proposal.ready and not proposal.settings


def test_l56_l57_saved_experiment_round_trips_exact_ordering(tmp_path):
    from src.gui.learning_state import LearningExperiment, LearningVariant

    bench = _golden(tmp_path)
    bench.run()
    experiment = bench.state.current_experiment
    restored = LearningExperiment.from_dict(experiment.to_dict())
    variants = [LearningVariant.from_dict(v.to_dict()) for v in bench.state.plan]
    assert restored.execution_snapshot_json == experiment.execution_snapshot_json
    assert [v.job_id for v in variants] == [v.job_id for v in bench.state.plan]
    assert [c["name"] for c in _snapshot(restored)[lc.STUDY_TYPE]["candidates"]] == [None, A, B, C]


def test_visibility_prompt_and_captions_hide_resource_names_when_not_visible(tmp_path):
    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    assert A in lc.visibility_prompt(experiment)  # input to the classifier only
    hidden = lc.candidate_caption(experiment, "B", visible=False)
    assert A not in hidden and "hidden" in hidden.lower()
    shown = lc.candidate_caption(experiment, "B", visible=True)
    assert A in shown and "0.8" in shown


# -- H. Historical behaviour is untouched ---------------------------------------------------------------------


def test_l63_historical_lora_strength_variable_and_helpers_are_unchanged():
    from src.learning.lora_variant import apply_lora_variant
    from src.learning.variable_metadata import get_variable_metadata

    meta = get_variable_metadata("LoRA Strength")
    assert meta is not None and meta.config_path == "lora_override"
    assert apply_lora_variant("a <lora:x:0.3> b", "x", 0.9).count("<lora:x:0.9>") == 1
    assert lc.VARIABLE != "LoRA Strength" and get_variable_metadata(lc.VARIABLE) is None


def test_preview_details_and_summary_obey_visibility(tmp_path):
    from src.learning.preview_summary import build_preview_summary

    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    hidden = build_preview_summary(experiment, bench.state.plan, show_model_names=False)
    visible = build_preview_summary(experiment, bench.state.plan, show_model_names=True)
    assert hidden is not None and visible is not None
    assert (
        not hidden.prompt_details and A not in str(hidden) and "BetterThanWords" not in str(hidden)
    )
    assert hidden.total_images == 12 and hidden.variants == 4
    assert (
        A in visible.prompt_details
        and "Fixed LoRAs (unchanged in every candidate)" in visible.prompt_details
    )
    assert "not independent proof" in visible.prompt_details
    assert ("LoRA operation", "Compare Candidates") in visible.rows


@pytest.mark.parametrize(
    "field", ["compiled_lora_composition_plan", "stage", "variant_id", "digest"]
)
def test_corrupt_frozen_plan_and_identity_refuse_before_admission(tmp_path, field):
    from src.learning.experiment_execution import freeze_snapshot

    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    snapshot = _snapshot(experiment)
    if field == "compiled_lora_composition_plan":
        snapshot[field][0]["input_digest"] = "x"
    elif field == "stage":
        snapshot[field] = "img2img"
    elif field == "digest":
        snapshot[lc.STUDY_TYPE]["candidates"][1]["weight"] = 0.1
    else:
        bench.state.plan[0].variant_id = "different identity"
    experiment.execution_snapshot_json = freeze_snapshot(snapshot)
    with pytest.raises(ValueError):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


def test_l57_restart_reconciles_exact_sqlite_jobs_without_resubmission(tmp_path):
    from src.learning.execution_controller import LearningExecutionController
    from src.learning.experiment_store import LearningExperimentStore
    from src.queue.job_model import JobStatus
    from src.queue.job_repository import JobRepository
    from tests.learning_v2.test_learning_recovery_260 import (
        RepositoryService,
        recreated,
        transition,
    )

    bench = _golden(tmp_path)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    try:
        service = RepositoryService(repository)
        bench.controller.pipeline_controller = SimpleNamespace(_job_service=service)
        bench.controller.execution_controller = LearningExecutionController(bench.state, service)
        bench.controller.run_plan()
        assert len(service.calls) == 1 and len(repository.list_job_models()) == 4
        bench.state.selected_variant = bench.state.plan[1]
        payload = json.loads(json.dumps(bench.controller.export_resume_state()))
        store = LearningExperimentStore(tmp_path / "experiments")
        handle = store.save_session(
            display_name="LoRA Composition",
            payload=payload,
            experiment_id=bench.state.current_experiment.experiment_id,
        )
        candidate = _snapshot(bench.state.current_experiment)[lc.STUDY_TYPE]["candidates"][1]
        completed = {
            "variants": [
                {
                    "output_paths": [str(tmp_path / f"{i}.png") for i in range(3)],
                    "all_seeds": [101, 102, 103],
                    "all_subseeds": [700, 701, 702],
                    "final_prompt": candidate["expected_positive"],
                    "final_negative_prompt": candidate["expected_negative"],
                    "runtime_admission": {"launch_profile": "one"},
                }
            ]
        }
        transition(repository, bench.state.plan[1].job_id, JobStatus.COMPLETED, result=completed)
        restored, fresh_service = recreated(store.load_session(handle.experiment_id), repository)
        assert [v.job_id for v in restored.learning_state.plan] == [
            v.job_id for v in bench.state.plan
        ]
        assert restored.learning_state.selected_variant.param_value == "B"
        assert (
            restored.learning_state.plan[1].execution_metadata["controlled_evidence_valid"] is True
        )
        assert not fresh_service.calls
    finally:
        repository.close()


def test_candidate_label_text_hides_lora_names_when_not_visible(tmp_path):
    experiment = _golden(tmp_path).state.current_experiment
    assert lc.candidate_label_text(experiment, "A", visible=False) == "No LoRA"
    assert lc.candidate_label_text(experiment, "B", visible=True) == f"{A} @ 0.8"
    assert A not in lc.candidate_label_text(experiment, "B", visible=False)


def test_registry_classification_never_trusts_filename_hints_or_foreign_families():
    from src.assets.compatibility import (
        CompatibilityProfile,
        CompatibilityStatus,
        EvidenceConfidence,
        FamilyEvidence,
        ModelFamily,
    )
    from src.learning.lora_inventory import asset_from_record

    def record(status, family, confidence):
        evidence = (FamilyEvidence(family, "source", "raw", confidence),) if family else ()
        return SimpleNamespace(
            sha256="ab" * 32, compatibility=CompatibilityProfile(status, family, evidence)
        )

    sdxl_meta = record(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, EvidenceConfidence.METADATA)
    assert asset_from_record("x", sdxl_meta, "", "sdxl").status == STATUS_COMPATIBLE
    assert asset_from_record("x", sdxl_meta, "", "flux").status == STATUS_INCOMPATIBLE
    hint = record(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, EvidenceConfidence.FILENAME_HINT)
    assert asset_from_record("x", hint, "", "sdxl").status == STATUS_UNCERTAIN
    conflict = record(CompatibilityStatus.CONFLICTING, None, EvidenceConfidence.METADATA)
    assert asset_from_record("x", conflict, "", "sdxl").status == STATUS_INCOMPATIBLE
    assert (
        asset_from_record("x", None, "matches more than one distinct file", "sdxl").status
        == STATUS_AMBIGUOUS
    )
    assert asset_from_record("x", None, "was not found", "sdxl").status == STATUS_MISSING


def test_discovered_inventory_is_the_preview_and_run_identity_evidence(tmp_path, monkeypatch):
    import src.learning.lora_inventory as inventory

    cache_reads = []
    monkeypatch.setattr(
        inventory,
        "registry_resolver",
        lambda family: lambda name: cache_reads.append(name)
        or LoraAsset(name, STATUS_MISSING, reason="stub cache"),
    )
    assert inventory.inventory_resolver({}, "sdxl")("Anything").status == STATUS_MISSING
    bench = _bench(tmp_path)
    bench.controller._learning_lora_asset_resolver = None
    spec = _spec(lc.ADD_REMOVE, [(None, 0), (A, 0.8)])
    kwargs = {
        "variable": lc.VARIABLE,
        "images": 1,
        "study_type": lc.STUDY_TYPE,
        "custom_prompt": KNIGHT,
        "lora_composition": spec,
    }
    with pytest.raises(
        ValueError, match="stub cache"
    ):  # no discovery yet: the cache-only registry decides
        bench.preview(**kwargs)
    discovered = SimpleNamespace(
        name=A,
        errors=(),
        record=SimpleNamespace(
            sha256=sha(A),
            compatibility=SimpleNamespace(
                status=lc_status("resolved"),
                family=SimpleNamespace(value="sdxl"),
                evidence=(
                    SimpleNamespace(confidence=lc_conf("metadata"), source="embedded_metadata:x"),
                ),
            ),
        ),
    )
    bench.controller.lora_inventory = {A: discovered}
    bench.preview(**kwargs)
    frozen = _snapshot(bench.state.current_experiment)[lc.STUDY_TYPE]
    assert frozen["candidates"][1]["asset"]["sha256"] == sha(A)
    assert cache_reads == [A]


def lc_status(value):
    from src.assets.compatibility import CompatibilityStatus

    return CompatibilityStatus(value)


def lc_conf(value):
    from src.assets.compatibility import EvidenceConfidence

    return EvidenceConfidence(value)
