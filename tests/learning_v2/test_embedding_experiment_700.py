"""PR-LEARN-EMBED-700: one designated textual-inversion position varies; everything else is frozen and proven.

Test names group the work package's deterministic matrix (E-numbers are labels, not a one-to-one index). No WebUI, GPU, model load or download: assets are a fake
registry resolver, JobService is a recording fake, and the Pipeline is a plain dict the tests mutate. Backend
behavior (``<embedding:>`` stripping, bare-name invocation, ``TI`` report) is pinned in
``tests/utils/test_embedding_invocation_700.py`` against the audited Forge Neo source.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.image_backends.model_policy import resolve_model_policy
from src.learning import embedding_experiment as ee
from src.learning.embedding_experiment import (
    STATUS_AMBIGUOUS,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_MISSING,
    STATUS_STALE,
    STATUS_UNVERIFIED,
    Candidate,
    EmbeddingAsset,
    EmbeddingDesign,
    freeze_candidates,
)
from src.pipeline.prompt_pack_parser import PackRow
from tests.learning_v2.test_model_comparison_140 import KLEIN, SDXL, policy

KNIGHT = (
    "Cinematic portrait of a medieval knight, realistic face, detailed armor, natural lighting."
)
A, B, C = "PortraitStyle", "FilmGrain", "SoftLight"
FIXED_POS, FIXED_NEG = "DetailBoost", "bad_hands"


def sha(name: str) -> str:
    return hashlib.sha256(name.casefold().encode()).hexdigest()


def asset(name: str, status: str = STATUS_COMPATIBLE, **fields) -> EmbeddingAsset:
    base = {
        "sha256": sha(name),
        "family": "sdxl",
        "structure": "sdxl_clip_l_g",
        "file_format": ".safetensors",
        "vectors": 8,
    }
    return EmbeddingAsset(name, status, **{**base, **fields})


def assets(**overrides: EmbeddingAsset):
    def resolve(name: str) -> EmbeddingAsset:
        return overrides.get(name) or overrides.get(name.casefold()) or asset(name)

    return resolve


def sdxl():
    return policy(SDXL)


def baseline() -> dict:
    from tests.learning_v2.test_learning_independent_baseline_650 import pipeline_config

    return pipeline_config()


def cands(*pairs) -> tuple[Candidate, ...]:
    return tuple(Candidate(name, weight) for name, weight in pairs)


def design(
    operation=ee.WEIGHT,
    pairs=((A, 0.6), (A, 1.0), (A, 1.3)),
    *,
    channel=ee.POSITIVE,
    prompt=KNIGHT,
    original=None,
    images=1,
    slots=None,
):
    return EmbeddingDesign(
        operation, channel, prompt, cands(*pairs), original, images, dict(slots or {})
    )


def row(positive=(), negative=(), quality="", subject=KNIGHT, phrases=()) -> PackRow:
    return PackRow(tuple(positive), quality, subject, (), tuple(negative), tuple(phrases))


def freeze(d: EmbeddingDesign, *, resolver=None, pol=None, base=None, **kwargs):
    return freeze_candidates(
        d,
        pol or sdxl(),
        base if base is not None else baseline(),
        resolver=resolver or assets(),
        **kwargs,
    )


PRESENCE_PAIRS = ((None, 0), (A, 1.0))
IDENTITY_PAIRS = ((None, 0), (A, 1.0), (B, 1.0), (C, 1.0))


def embeds(candidate: dict, channel=ee.POSITIVE) -> list[tuple[str, float]]:
    return [(n, w) for n, w in candidate[f"expected_{channel}_embeddings"]]


# -- A. Design shape ---------------------------------------------------------------------------------------------


def test_e01_e02_presence_is_exactly_no_embedding_versus_embedding_present():
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS))
    off, on = frozen["candidates"]
    assert (off["name"], on["name"]) == (None, A)
    assert off["positive"] == KNIGHT and on["positive"] == f"{A} {KNIGHT}"
    assert off["asset"] is None and on["asset"]["sha256"] == sha(A)
    assert on["invocation"] == A and "<embedding:" not in on["positive"] + on["negative"]


@pytest.mark.parametrize(
    "pairs",
    [
        ((None, 0), (A, 1.0), (A, 0.8)),  # three states
        ((A, 1.0), (A, 0.8)),  # no empty control
        ((None, 0), (None, 0)),  # no embedding at all
    ],
)
def test_presence_refuses_anything_but_two_states(pairs):
    with pytest.raises(ValueError):
        freeze(design(ee.PRESENCE, pairs))


def test_e03_e04_weight_varies_one_embedding_and_uses_attention_syntax():
    frozen = freeze(design(ee.WEIGHT, ((A, 0.6), (A, 1.0), (A, 1.3))))
    texts = [c["positive"] for c in frozen["candidates"]]
    assert texts == [f"({A}:0.6) {KNIGHT}", f"{A} {KNIGHT}", f"({A}:1.3) {KNIGHT}"]
    assert {c["asset"]["sha256"] for c in frozen["candidates"]} == {sha(A)}


def test_weight_may_include_an_absent_control_and_refuses_two_embeddings_or_none():
    freeze(design(ee.WEIGHT, ((None, 0), (A, 0.6), (A, 1.0))))
    with pytest.raises(ValueError, match="exactly one embedding"):
        freeze(design(ee.WEIGHT, ((A, 0.6), (B, 1.0))))
    with pytest.raises(ValueError):
        freeze(design(ee.WEIGHT, ((None, 0), (None, 0))))


def test_e05_e06_identity_changes_the_embedding_at_one_common_weight():
    frozen = freeze(design(ee.IDENTITY, IDENTITY_PAIRS))
    names = [c["name"] for c in frozen["candidates"]]
    assert names == [None, A, B, C]
    assert [c["weight"] for c in frozen["candidates"]] == [0.0, 1.0, 1.0, 1.0]
    assert {c["asset"]["sha256"] for c in frozen["candidates"][1:]} == {sha(A), sha(B), sha(C)}


@pytest.mark.parametrize(
    ("pairs", "message"),
    [
        (((A, 1.0), (B, 0.8)), "same weight"),
        (((A, 1.0), (A, 1.0)), "distinct"),
        (((None, 0), (None, 0), (A, 1.0)), "distinct"),
        (((A, 1.0), (B, 1.0), (None, 0), (C, 1.0), (None, 0)), "distinct"),
    ],
)
def test_identity_refusals(pairs, message):
    with pytest.raises(ValueError, match=message):
        freeze(design(ee.IDENTITY, pairs))


def test_e07_negative_channel_varies_only_the_negative_prompt():
    frozen = freeze(design(ee.WEIGHT, ((B, 0.7), (B, 1.0)), channel=ee.NEGATIVE), negative="blurry")
    first, second = frozen["candidates"]
    assert first["positive"] == second["positive"] == KNIGHT
    assert first["negative"] == f"blurry, ({B}:0.7)" and second["negative"] == f"blurry, {B}"
    assert embeds(first, ee.NEGATIVE) == [(B, 0.7)] and embeds(first) == []


def test_e08_a_candidate_cannot_be_tested_in_both_channels():
    base_row = row(negative=[(A, 1.0)])
    with pytest.raises(ValueError, match="negative channel|one experiment cannot vary both"):
        freeze(design(ee.WEIGHT, ((A, 0.6), (A, 1.0))), row=base_row)


def test_e09_e10_fixed_embeddings_stay_and_candidates_never_duplicate_them():
    base_row = row(positive=[(FIXED_POS, 0.9)], negative=[(FIXED_NEG, 1.2)])
    frozen = freeze(design(ee.WEIGHT, ((A, 0.6), (A, 1.0)), channel=ee.POSITIVE), row=base_row)
    for candidate in frozen["candidates"]:
        assert (FIXED_POS, 0.9) in embeds(candidate) and (FIXED_NEG, 1.2) in embeds(
            candidate, ee.NEGATIVE
        )
        assert candidate["positive"].count(FIXED_POS) == 1
        assert candidate["negative"] == f"({FIXED_NEG}:1.2)"
    assert [item["name"] for item in frozen["fixed"]] == [FIXED_POS, FIXED_NEG]
    with pytest.raises(ValueError, match="already a fixed embedding"):
        freeze(design(ee.IDENTITY, ((None, 0), (FIXED_POS, 1.0), (A, 1.0))), row=base_row)


def test_e11_e12_a_designated_original_keeps_its_position_and_is_removed_elsewhere():
    base_row = row(positive=[(FIXED_POS, 0.9), (A, 0.8), ("TailTag", 1.0)])
    frozen = freeze(design(ee.IDENTITY, ((A, 0.8), (B, 0.8), (None, 0)), original=A), row=base_row)
    first, second, third = frozen["candidates"]
    assert [n for n, _ in embeds(first)] == [FIXED_POS, A, "TailTag"]
    assert [n for n, _ in embeds(second)] == [FIXED_POS, B, "TailTag"]
    assert [n for n, _ in embeds(third)] == [FIXED_POS, "TailTag"]
    assert all(A not in c["positive"] for c in (second, third))
    with pytest.raises(ValueError, match="designated original"):
        freeze(design(ee.IDENTITY, ((B, 0.8), (C, 0.8)), original=A), row=base_row)
    with pytest.raises(ValueError, match="not in the baseline channel"):
        freeze(design(ee.IDENTITY, ((A, 0.8), (B, 0.8)), original=A), row=row())


def test_identity_keeps_the_original_control_at_its_baseline_weight():
    base_row = row(positive=[(A, 0.8)])
    with pytest.raises(ValueError, match="baseline weight"):
        freeze(design(ee.IDENTITY, ((A, 1.0), (B, 1.0)), original=A), row=base_row)


def test_e13_everything_outside_the_designated_contribution_is_identical():
    base_row = row(
        positive=[(FIXED_POS, 1.0)], negative=[(FIXED_NEG, 1.0)], phrases=["blurry"], subject=KNIGHT
    )
    frozen = freeze(design(ee.IDENTITY, IDENTITY_PAIRS), row=base_row)
    import re

    def bare(text: str) -> str:
        text = re.sub(rf"\(?\b({A}|{B}|{C})\b(:[0-9.]+\))?", "", text)
        return re.sub(r"\s+", " ", text).strip(" ,")

    assert len({bare(c["positive"]) for c in frozen["candidates"]}) == 1
    assert len({c["negative"] for c in frozen["candidates"]}) == 1
    assert (
        len(
            {
                c["fixed_digest"] if "fixed_digest" in c else frozen["fixed_digest"]
                for c in frozen["candidates"]
            }
        )
        == 1
    )


def test_e14_weight_is_bounded_and_canonicalized():
    assert Candidate(A, 0.123).weight == 0.12
    assert Candidate(A, 0.0) == Candidate(None)
    for bad in (-0.1, 1.51, float("nan"), float("inf"), "x"):
        with pytest.raises(ValueError, match="weight"):
            Candidate(A, bad)


def test_e15_zero_weight_collapses_to_no_embedding_and_duplicates_are_refused():
    with pytest.raises(ValueError, match="repeats an earlier"):
        freeze(design(ee.WEIGHT, ((None, 0), (A, 0.0), (A, 1.0))))
    with pytest.raises(ValueError, match="repeats an earlier"):
        freeze(design(ee.WEIGHT, ((A, 1.0), (A, 1.004))))


def test_e16_e17_bounds_two_to_eight_candidates_one_to_three_images():
    many = tuple((A, round(0.1 * i, 2)) for i in range(1, 9))
    assert len(freeze(design(ee.WEIGHT, many, images=3))["candidates"]) == 8
    with pytest.raises(ValueError, match="two to eight"):
        freeze(design(ee.WEIGHT, many + ((A, 1.5),)))
    with pytest.raises(ValueError, match="two to eight"):
        freeze(design(ee.WEIGHT, ((A, 1.0),)))
    for images in (0, 4, True):
        with pytest.raises(ValueError, match="one to three images"):
            freeze(design(ee.WEIGHT, many[:3], images=images))
    with pytest.raises(ValueError, match="positive or the negative"):
        freeze(design(ee.WEIGHT, many[:3], channel="sideways"))


def test_e18_stable_ordering_and_sealed_digest():
    one, two = (
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS)),
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS)),
    )
    assert one == two and [c["label"] for c in one["candidates"]] == ["A", "B"]
    reordered = freeze(design(ee.PRESENCE, tuple(reversed(PRESENCE_PAIRS))))
    assert [c["name"] for c in reordered["candidates"]] == [A, None]
    assert reordered["digest"] != one["digest"]
    snapshot = {"study_type": ee.STUDY_TYPE, ee.STUDY_TYPE: one, "variant_values": ["A", "B"]}
    assert ee.frozen_section(snapshot)["digest"] == one["digest"]
    tampered = copy.deepcopy(snapshot)
    tampered[ee.STUDY_TYPE]["candidates"][1]["weight"] = 0.1
    with pytest.raises(ValueError, match="corrupt"):
        ee.frozen_section(tampered)
    with pytest.raises(ValueError, match="does not belong"):
        ee.frozen_candidate(snapshot, "Z")


# -- B. Prompt-source safety ------------------------------------------------------------------------------------


def test_e19_inline_embedding_references_cannot_be_isolated_and_are_refused():
    with pytest.raises(ValueError, match="inline embedding reference"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS, prompt=f"{KNIGHT} <embedding:{B}>"))
    with pytest.raises(ValueError, match="inline embedding reference"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), negative=f"<embedding:{B}:0.5>, blurry")


def test_e20_same_name_in_ordinary_prose_is_refused_not_double_counted():
    with pytest.raises(ValueError, match="exactly the intended embeddings"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS, prompt=f"{KNIGHT} in {A} style"))


def test_e21_duplicate_fixed_declarations_are_refused_not_silently_deduplicated():
    with pytest.raises(ValueError, match="more than once"):
        freeze(
            design(ee.PRESENCE, PRESENCE_PAIRS),
            row=row(positive=[(FIXED_POS, 1.0), (FIXED_POS, 0.5)]),
        )


def test_e22_unresolved_matrix_slots_need_explicit_fixed_values():
    with pytest.raises(ValueError, match="Matrix slots"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS, prompt=f"{KNIGHT} in [[place]]"))
    frozen = freeze(
        design(
            ee.PRESENCE,
            PRESENCE_PAIRS,
            prompt=f"{KNIGHT} in [[place]]",
            slots={"place": "a forest"},
        )
    )
    assert (
        "a forest" in frozen["candidates"][0]["positive"]
        and "[[" not in frozen["candidates"][1]["positive"]
    )
    with pytest.raises(ValueError, match="plain text"):
        freeze(
            design(ee.PRESENCE, PRESENCE_PAIRS, prompt="a [[p]]", slots={"p": f"<embedding:{B}>"})
        )


def test_e23_conditioned_pack_rows_are_not_supported():
    conditioned = replace(row(), conditioning={"openpose": "x"})
    with pytest.raises(ValueError, match="Conditioned"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), row=conditioned)


@pytest.mark.parametrize("name", ["a:b", "a,b", "a(b)", "a[b]", "<a>", "a|b"])
def test_e24_names_prompt_syntax_would_split_cannot_be_tested(name):
    with pytest.raises(ValueError, match="cannot be invoked|syntax"):
        freeze(design(ee.PRESENCE, ((None, 0), (name, 1.0))))
    with pytest.raises(ValueError, match="cannot be invoked"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), row=row(positive=[(name, 1.0)]))


# -- C. Asset admission and target policy -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (STATUS_MISSING, "not found"),
        (STATUS_AMBIGUOUS, "ambiguous|more than one"),
        (STATUS_INCOMPATIBLE, "incompatible|cannot be used"),
        (STATUS_STALE, "changed on disk"),
        (STATUS_UNVERIFIED, "unverified|unknown availability"),
    ],
)
def test_e25_e26_e27_unusable_assets_refuse_a_controlled_preview(status, text):
    resolver = assets(**{A: asset(A, status)})
    with pytest.raises(ValueError, match=f"(?i)'{A}'.*({text})|{A}.*({text})"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), resolver=resolver)


def test_e28_an_asset_without_a_content_identity_refuses():
    with pytest.raises(ValueError, match="SHA-256"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), resolver=assets(**{A: asset(A, sha256="")}))


def test_e29_fixed_embeddings_are_admitted_like_tested_ones():
    broken = assets(**{FIXED_POS: asset(FIXED_POS, STATUS_MISSING)})
    with pytest.raises(ValueError, match=FIXED_POS):
        freeze(
            design(ee.PRESENCE, PRESENCE_PAIRS),
            row=row(positive=[(FIXED_POS, 1.0)]),
            resolver=broken,
        )


def test_e30_target_must_be_registry_verified_sdxl_forge_txt2img():
    with pytest.raises(ValueError, match="SDXL txt2img"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), pol=policy(KLEIN))
    with pytest.raises(ValueError, match="txt2img"):
        ee.require_target(sdxl(), baseline(), ee.POSITIVE, "img2img")
    unverified = resolve_model_policy("sdxl-unlisted-checkpoint.safetensors")
    with pytest.raises(ValueError):
        ee.require_target(unverified, baseline(), ee.POSITIVE)
    other = baseline()
    other["backend_options"] = {"image": {"backend_id": "comfyui"}}
    with pytest.raises(ValueError, match="Forge"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), base=other)


def test_e31_optimizer_and_style_consistency_in_the_baseline_are_refused():
    base = baseline()
    base["prompt_optimizer"] = {"enabled": True}
    with pytest.raises(ValueError, match="prompt optimizer"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), base=base)
    nested = baseline()
    nested.setdefault("txt2img", {})["prompt_optimizer"] = {"enabled": True}
    with pytest.raises(ValueError, match="prompt optimizer"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), base=nested)
    styled = baseline()
    styled["style_lora"] = {"enabled": True, "name": "style"}
    with pytest.raises(ValueError, match="Style Consistency"):
        freeze(design(ee.PRESENCE, PRESENCE_PAIRS), base=styled)


def test_e32_negative_channel_requires_negative_prompt_support(monkeypatch):
    from src.image_backends.model_policy import FeaturePolicy, Support

    target = sdxl()
    real = type(target).feature

    def feature(self, name, stage="txt2img"):
        if name == "negative_prompt":
            return FeaturePolicy(Support.UNSUPPORTED)
        return real(self, name, stage)

    monkeypatch.setattr(type(target), "feature", feature)
    ee.require_target(target, baseline(), ee.POSITIVE)
    with pytest.raises(ValueError, match="negative prompt"):
        ee.require_target(target, baseline(), ee.NEGATIVE)


def test_e33_evidence_limits_never_claim_consumption_or_applied_weight():
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS))
    limits = frozen["evidence_limits"]
    assert "by name" in limits and "weight" in limits and "not" in limits


# -- D. Readback and backend consumption ------------------------------------------------------------------------


def snapshot_for(frozen: dict) -> dict:
    return {
        "study_type": ee.STUDY_TYPE,
        ee.STUDY_TYPE: frozen,
        "experiment_id": "e1",
        "variant_values": [c["label"] for c in frozen["candidates"]],
        "compiled_embedding_plan": [
            {"config_digest": ee.digest(_config_of(c))} for c in frozen["candidates"]
        ],
    }


def _config_of(candidate: dict) -> dict:
    return {"prompt": candidate["positive"], "negative_prompt": candidate["negative"]}


def variant_for(frozen: dict, index: int, config=None):
    candidate = frozen["candidates"][index]
    return SimpleNamespace(
        param_value=candidate["label"],
        job_id=f"job-{index}",
        variant_id=f"e1:{index}",
        experiment_id="e1",
        executed_config=config if config is not None else _config_of(candidate),
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


def reason(frozen, index, readback, report=None):
    return ee.readback_reason(snapshot_for(frozen), variant_for(frozen, index), readback, report)


def test_e34_matching_readback_is_controlled_but_consumption_stays_unverified():
    frozen = freeze(design(ee.WEIGHT, ((A, 0.6), (A, 1.0))))
    assert reason(frozen, 0, readback_of(frozen, 0)) == ""
    assert ee.consumption_status(frozen["candidates"][0], None)[0] == ee.CONSUMPTION_REQUEST_ONLY


def test_e35_missing_readback_is_uncontrolled():
    frozen = freeze(design(ee.WEIGHT, ((A, 0.6), (A, 1.0))))
    assert reason(frozen, 0, {}) == "embedding_readback_unavailable"


def test_e36_e37_removed_embedding_still_present_and_polarity_flip_are_uncontrolled():
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS))
    leaked = frozen["candidates"][0]["expected_positive"] + f" {A}"
    assert (
        reason(frozen, 0, readback_of(frozen, 0, final_prompt=leaked))
        == "embedding_excluded_present"
    )
    flipped = reason(
        frozen,
        1,
        readback_of(frozen, 1, final_prompt=KNIGHT, final_negative_prompt=f"{A}"),
    )
    assert flipped == "embedding_polarity_mismatch"


def test_e38_e39_e40_weight_unexpected_and_duplicate_tokens():
    frozen = freeze(design(ee.WEIGHT, ((A, 0.6), (A, 1.0))))
    expected = frozen["candidates"][0]["expected_positive"]
    assert (
        reason(frozen, 0, readback_of(frozen, 0, final_prompt=expected.replace("0.6", "0.9")))
        == "embedding_weight_mismatch"
    )
    assert (
        reason(frozen, 0, readback_of(frozen, 0, final_prompt=expected + " "))
        == "embedding_readback_mismatch"
    )
    duplicate = expected + f", {A}"
    assert (
        reason(frozen, 0, readback_of(frozen, 0, final_prompt=duplicate)) == "embedding_duplicate"
    )
    identity = freeze(design(ee.IDENTITY, IDENTITY_PAIRS))
    extra = identity["candidates"][1]["expected_positive"] + f" {B}"
    assert (
        reason(identity, 1, readback_of(identity, 1, final_prompt=extra))
        == "embedding_excluded_present"
    )


def test_e41_a_dropped_tested_or_fixed_embedding_is_distinguished():
    base_row = row(positive=[(FIXED_POS, 0.9)])
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS), row=base_row)
    candidate = frozen["candidates"][1]
    dropped_tested = candidate["expected_positive"].replace(A, "", 1)
    assert (
        reason(frozen, 1, readback_of(frozen, 1, final_prompt=dropped_tested))
        == "embedding_missing"
    )
    dropped_fixed = candidate["expected_positive"].replace(f"({FIXED_POS}:0.9)", "")
    assert (
        reason(frozen, 1, readback_of(frozen, 1, final_prompt=dropped_fixed))
        == "embedding_fixed_changed"
    )


def test_e42_authoring_notation_in_the_readback_is_never_accepted_as_consumption():
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS))
    text = frozen["candidates"][1]["expected_positive"] + f" <embedding:{A}>"
    assert (
        reason(frozen, 1, readback_of(frozen, 1, final_prompt=text))
        == "embedding_unexpected_reference"
    )


def test_e43_compiled_context_and_identity_conflicts():
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS))
    snapshot, variant = snapshot_for(frozen), variant_for(frozen, 1)
    variant.executed_config = {**variant.executed_config, "steps": 5}
    assert (
        ee.readback_reason(snapshot, variant, readback_of(frozen, 1))
        == "embedding_compiled_context_conflict"
    )
    variant = variant_for(frozen, 1)
    variant.variant_id = "other:1"
    assert (
        ee.readback_reason(snapshot, variant, readback_of(frozen, 1))
        == "embedding_identity_unverified"
    )
    corrupt = copy.deepcopy(snapshot)
    corrupt[ee.STUDY_TYPE]["candidates"][1]["weight"] = 0.3
    assert (
        ee.readback_reason(corrupt, variant_for(frozen, 1), readback_of(frozen, 1))
        == "embedding_frozen_evidence_invalid"
    )
    assert ee.readback_reason({"study_type": "other"}, variant_for(frozen, 1), {}) == ""


def test_e44_e45_backend_ti_report_confirms_contradicts_or_stays_silent():
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS), row=row(negative=[(FIXED_NEG, 1.0)]))
    on, off = frozen["candidates"][1], frozen["candidates"][0]
    status = ee.consumption_status
    assert status(on, {"reported": True, "names": [A, FIXED_NEG]}) == (ee.CONSUMPTION_REPORTED, "")
    assert (
        status(on, {"reported": True, "names": [FIXED_NEG]})[1] == "embedding_backend_not_consumed"
    )
    assert (
        status(on, {"reported": True, "names": [A, FIXED_NEG, B]})[1]
        == "embedding_backend_unexpected"
    )
    assert (
        status(off, {"reported": True, "names": [A, FIXED_NEG]})[1]
        == "embedding_backend_unexpected"
    )
    # silence is not evidence of absence (the backend may reuse cached conditioning)
    assert status(on, None)[0] == ee.CONSUMPTION_REQUEST_ONLY
    assert status(on, {"reported": True, "names": []})[0] == ee.CONSUMPTION_REQUEST_ONLY
    # Forge strips ':' and ',' from the names it reports
    colon = freeze(design(ee.PRESENCE, ((None, 0), ("a.b-c", 1.0))))
    assert (
        status(colon["candidates"][1], {"reported": True, "names": ["a.b-c"]})[0]
        == ee.CONSUMPTION_REPORTED
    )
    assert (
        reason(frozen, 1, readback_of(frozen, 1), {"reported": True, "names": [FIXED_NEG]})
        == "embedding_backend_not_consumed"
    )
    assert (
        reason(frozen, 1, readback_of(frozen, 1), {"reported": True, "names": [A, FIXED_NEG]}) == ""
    )


def test_e46_execution_evidence_is_typed_and_empty_for_other_studies():
    frozen = freeze(design(ee.PRESENCE, PRESENCE_PAIRS))
    snapshot, variant = snapshot_for(frozen), variant_for(frozen, 1)
    report = {"reported": True, "names": [A]}
    evidence = ee.execution_evidence(snapshot, variant, report)
    assert evidence == {
        "embedding_consumption_status": ee.CONSUMPTION_REPORTED,
        "backend_textual_inversion": report,
    }
    assert ee.execution_evidence({"study_type": "prompt_slot"}, variant, report) == {}
    assert (
        ee.execution_evidence(snapshot, variant, None)["embedding_consumption_status"]
        == ee.CONSUMPTION_REQUEST_ONLY
    )


def test_observed_embeddings_boundaries():
    seen = ee.observed_embeddings
    assert seen("Style-A, Style", ["Style", "Style-A"]) == [("Style-A", 1.0), ("Style", 1.0)]
    assert seen("(Style:0.6) x", ["Style"]) == [("Style", 0.6)]
    assert seen("restyled Styles", ["Style"]) == []
    assert seen("anything", []) == []


# -- Integration through the real LearningController ----------------------------------------------------------


def _bench(tmp_path, resolver=None):
    from tests.learning_v2.test_learning_independent_baseline_650 import Bench

    bench = Bench(tmp_path)
    bench.controller._learning_embedding_asset_resolver = resolver or assets()
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


def _spec(operation, pairs, original=None, channel=ee.POSITIVE, **extra):
    return {
        "operation": operation,
        "channel": channel,
        "original": original,
        "candidates": [{"name": name, "weight": weight} for name, weight in pairs],
        **extra,
    }


def _golden(tmp_path, **kwargs):
    bench = _bench(tmp_path, kwargs.pop("resolver", None))
    bench.preview(
        variable=ee.VARIABLE,
        images=3,
        study_type=ee.STUDY_TYPE,
        prompt=KNIGHT,
        custom_prompt=KNIGHT,
        embedding_experiment=_spec(ee.IDENTITY, IDENTITY_PAIRS),
        **kwargs,
    )
    return bench


def _snapshot(experiment):
    from src.learning.experiment_execution import thaw_snapshot

    return thaw_snapshot(experiment.execution_snapshot_json)


def test_e47_to_e55_golden_preview_run_is_frozen_and_admitted_once(tmp_path):
    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    snapshot = _snapshot(experiment)
    assert snapshot["study_type"] == ee.STUDY_TYPE
    assert snapshot["variant_values"] == ["A", "B", "C", "D"]
    assert snapshot["variable_under_test"] == ee.VARIABLE
    assert not bench.service.submit_njrs.called  # Preview queues nothing
    bench.pipeline["txt2img"].update(model="changed", seed=9, steps=1, cfg_scale=12)
    jobs = bench.run()
    assert len(jobs) == 4 and sum(job.workload.images_per_prompt for job in jobs) == 12
    assert {job.seed for job in jobs} == {101} and {job.stages[0].steps for job in jobs} == {30}
    assert {job.stages[0].model for job in jobs} == {SDXL}
    assert [job.positive_prompt for job in jobs] == [
        KNIGHT,
        f"{A} {KNIGHT}",
        f"{B} {KNIGHT}",
        f"{C} {KNIGHT}",
    ]
    for job, want in zip(jobs, [[], [A], [B], [C]], strict=True):
        assert [str(t) for t in job.provenance.positive_embeddings] == want
        assert not job.provenance.negative_embeddings
        assert "<embedding:" not in job.positive_prompt + (job.negative_prompt or "")
    assert bench.service.submit_njrs.call_count == 1
    bench.controller.run_plan()
    assert bench.service.submit_njrs.call_count == 1  # duplicate Run does not re-admit
    assert [v.variant_id for v in bench.state.plan] == [
        f"{experiment.experiment_id}:{i}" for i in range(4)
    ]
    assert len({v.job_id for v in bench.state.plan}) == 4


def test_e56_negative_channel_golden_compiles_only_the_negative_prompt(tmp_path):
    bench = _bench(tmp_path)
    bench.preview(
        variable=ee.VARIABLE,
        images=1,
        study_type=ee.STUDY_TYPE,
        custom_prompt=KNIGHT,
        embedding_experiment=_spec(
            ee.WEIGHT, [(B, 0.7), (B, 1.0)], channel=ee.NEGATIVE, negative_prompt="blurry"
        ),
    )
    jobs = bench.run()
    assert {job.positive_prompt for job in jobs} == {KNIGHT}
    assert [job.negative_prompt for job in jobs] == [f"blurry, ({B}:0.7)", f"blurry, {B}"]
    assert [list(job.provenance.negative_embeddings) for job in jobs] == [
        [f"({B}:0.7)"],
        [B],
    ]
    assert all(not job.provenance.positive_embeddings for job in jobs)


def test_e57_asset_identity_change_before_admission_refuses_everything(tmp_path):
    bench = _golden(tmp_path)
    bench.controller._learning_embedding_asset_resolver = assets(**{B: asset(B, sha256="0" * 64)})
    with pytest.raises(ValueError, match="asset identity"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called
    bench.controller._learning_embedding_asset_resolver = assets(**{B: asset(B, STATUS_MISSING)})
    with pytest.raises(ValueError, match="asset identity"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


def test_e58_one_failed_candidate_admits_zero(tmp_path, monkeypatch):
    bench = _golden(tmp_path)
    from src.learning.learning_controller_services import embedding_experiment as service

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


def test_e59_preview_and_selection_never_touch_embedding_files(tmp_path):
    bench = _bench(tmp_path)
    file = tmp_path / f"{A}.safetensors"
    file.write_bytes(b"embedding bytes")
    before = (file.read_bytes(), file.stat().st_mtime_ns)
    bench.preview(
        variable=ee.VARIABLE,
        images=1,
        study_type=ee.STUDY_TYPE,
        custom_prompt=KNIGHT,
        embedding_experiment=_spec(ee.PRESENCE, PRESENCE_PAIRS),
    )
    assert (file.read_bytes(), file.stat().st_mtime_ns) == before


def _write_pack(tmp_path, positive=(), negative=()):
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
                            "text": "a knight in [[place]]",
                            "negative": "blurry",
                            "positive_embeddings": list(positive),
                            "negative_embeddings": list(negative),
                            "loras": [],
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
    return path


def test_e60_native_pack_row_freezes_structured_embeddings_and_replaces_the_original(tmp_path):
    path = _write_pack(tmp_path, positive=[FIXED_POS, [A, 0.8]], negative=[FIXED_NEG])
    before = path.read_bytes()
    bench = _bench(tmp_path)
    bench.preview(
        variable=ee.VARIABLE,
        images=1,
        study_type=ee.STUDY_TYPE,
        prompt_source="pack",
        selected_prompt_pack_path=str(path),
        selected_prompt_pack_name="study",
        selected_prompt_index=0,
        selected_prompt_text="row text",
        embedding_experiment=_spec(
            ee.IDENTITY,
            [(A, 0.8), (B, 0.8), (None, 0)],
            original=A,
            fixed_slots={"place": "forest"},
        ),
    )
    frozen = _snapshot(bench.state.current_experiment)[ee.STUDY_TYPE]
    assert [item["name"] for item in frozen["fixed"]] == [FIXED_POS, FIXED_NEG]
    assert frozen["source"]["kind"] == "pack" and frozen["source"]["row_index"] == 0
    assert all(
        "forest" in c["positive"] and "[[" not in c["positive"] for c in frozen["candidates"]
    )
    assert all(c["negative"].startswith(FIXED_NEG) for c in frozen["candidates"])
    path.unlink()  # the frozen preview no longer needs the pack
    jobs = bench.run()
    assert len(jobs) == 3 and not path.exists()
    assert [[str(t) for t in job.provenance.positive_embeddings] for job in jobs] == [
        [FIXED_POS, f"({A}:0.8)"],
        [FIXED_POS, f"({B}:0.8)"],
        [FIXED_POS],
    ]
    assert before


def test_e61_custom_prompt_with_inline_embedding_refuses_preview(tmp_path):
    bench = _bench(tmp_path)
    with pytest.raises(ValueError, match="inline embedding reference"):
        bench.preview(
            variable=ee.VARIABLE,
            images=1,
            study_type=ee.STUDY_TYPE,
            custom_prompt=f"{KNIGHT} <embedding:{C}>",
            embedding_experiment=_spec(ee.PRESENCE, PRESENCE_PAIRS),
        )
    assert not getattr(bench.state.current_experiment, "execution_snapshot_json", "")


# -- E. Ratings, conclusion and isolation -----------------------------------------------------------------------


def _rated(tmp_path, ratings=(3, 5, 3, 3), valid=True, status=ee.CONSUMPTION_REQUEST_ONLY):
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
            embedding_consumption_status=status,
        )
        record, _, _ = bench.controller.build_rating_record(
            experiment, variant, variant.image_refs[0], ratings[i], "", None
        )
        assert record.metadata["record_kind"] == "learning_experiment_rating"
        assert record.metadata["study_type"] == ee.STUDY_TYPE
        meta = record.metadata[ee.STUDY_TYPE]
        assert meta["candidate_label"] == chr(65 + i) and meta["operation"] == ee.IDENTITY
        assert meta["expected_embedding_digest"] and meta["fixed_digest"]
        assert meta["consumption_status"] == status and meta["evidence_limits"]
        assert bench.controller._learning_record_writer.append_record(record)
        rows.append(json.loads(record.to_json()))
        details[variant.image_refs[0]] = {"overall_rating": ratings[i]}
    return bench, rows, details


def test_e62_e63_e66_ratings_link_to_candidates_and_form_an_exploratory_local_conclusion(tmp_path):
    bench, _rows, details = _rated(tmp_path)
    result = ee.conclusion(bench.state.plan, details, {})
    assert (
        result["best_value"] == "B"
        and result["saved"] == 4
        and result["sufficient_evidence"] is True
    )
    assert result["comparison_claim"] == "experiment_local_embedding_preference"
    assert result["causal_one_variable"] is False and result["consumption_verified"] is False
    assert result["evidence_level"] == "request_verified"
    assert "Exploratory preference" in result["message"] and "unverified" in result["message"]
    assert "no universal best" in result["message"]


def test_e64_reported_consumption_for_every_candidate_upgrades_the_claim(tmp_path):
    bench, _rows, details = _rated(tmp_path, status=ee.CONSUMPTION_REPORTED)
    result = ee.conclusion(bench.state.plan, details, {})
    assert (
        result["causal_one_variable"] is True and result["evidence_level"] == "consumption_reported"
    )
    assert "by name" in result["message"] and "weight is not reported" in result["message"]
    bench.state.plan[2].execution_metadata["embedding_consumption_status"] = (
        ee.CONSUMPTION_CONTRADICTED
    )
    assert ee.conclusion(bench.state.plan, details, {})["causal_one_variable"] is False


def test_e65_drafts_do_not_count_and_ties_have_no_unique_winner(tmp_path):
    bench, _rows, details = _rated(tmp_path, ratings=(4, 4, 3, 3))
    assert ee.conclusion(bench.state.plan, details, {})["best_value"] is None
    assert (
        ee.conclusion(bench.state.plan, {}, {"draft:sample-1.png": {"overall_rating": 5}})["saved"]
        == 0
    )


def test_e67_uncontrolled_variants_support_no_preference(tmp_path):
    bench, _rows, details = _rated(tmp_path, valid=False)
    result = ee.conclusion(bench.state.plan, details, {})
    assert result["best_value"] is None and result["controlled_valid"] is False


def test_e68_e69_embedding_ratings_never_recommend_or_publish(tmp_path):
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


def test_e70_saved_experiment_round_trips_exact_ordering(tmp_path):
    from src.gui.learning_state import LearningExperiment, LearningVariant

    bench = _golden(tmp_path)
    bench.run()
    experiment = bench.state.current_experiment
    restored = LearningExperiment.from_dict(experiment.to_dict())
    variants = [LearningVariant.from_dict(v.to_dict()) for v in bench.state.plan]
    assert restored.execution_snapshot_json == experiment.execution_snapshot_json
    assert [v.job_id for v in variants] == [v.job_id for v in bench.state.plan]
    assert [c["name"] for c in _snapshot(restored)[ee.STUDY_TYPE]["candidates"]] == [None, A, B, C]


def test_e71_visibility_prompt_captions_and_summary_hide_names_when_not_visible(tmp_path):
    from src.learning.controlled_study_display import candidate_caption, candidate_label_text
    from src.learning.preview_summary import build_preview_summary

    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    assert A in ee.visibility_prompt(experiment)  # classifier input only
    hidden = ee.candidate_caption(experiment, "B", visible=False)
    assert A not in hidden and "hidden" in hidden.lower()
    shown = ee.candidate_caption(experiment, "B", visible=True)
    assert A in shown and "Positive prompt" in shown
    assert candidate_caption(ee.STUDY_TYPE, experiment, "B", visible=True) == shown
    assert candidate_label_text(ee.STUDY_TYPE, experiment, "A", visible=False) == "No embedding"
    assert candidate_label_text(ee.STUDY_TYPE, experiment, "B", visible=True) == f"{A} @ 1"
    assert A not in candidate_label_text(ee.STUDY_TYPE, experiment, "B", visible=False)
    summary_hidden = build_preview_summary(experiment, bench.state.plan, show_model_names=False)
    summary_visible = build_preview_summary(experiment, bench.state.plan, show_model_names=True)
    assert summary_hidden is not None and summary_visible is not None
    assert not summary_hidden.prompt_details and A not in str(summary_hidden)
    assert summary_hidden.total_images == 12 and summary_hidden.variants == 4
    assert A in summary_visible.prompt_details and "by name" in summary_visible.prompt_details
    assert ("Embedding experiment", "Identity (Positive prompt)") in summary_visible.rows or any(
        key == "Embedding experiment" for key, _ in summary_visible.rows
    )


@pytest.mark.parametrize("field", ["compiled_embedding_plan", "stage", "variant_id", "digest"])
def test_e72_corrupt_frozen_plan_and_identity_refuse_before_admission(tmp_path, field):
    from src.learning.experiment_execution import freeze_snapshot

    bench = _golden(tmp_path)
    experiment = bench.state.current_experiment
    snapshot = _snapshot(experiment)
    if field == "compiled_embedding_plan":
        snapshot[field][0]["input_digest"] = "x"
    elif field == "stage":
        snapshot[field] = "img2img"
    elif field == "digest":
        snapshot[ee.STUDY_TYPE]["candidates"][1]["weight"] = 0.1
    else:
        bench.state.plan[0].variant_id = "different identity"
    experiment.execution_snapshot_json = freeze_snapshot(snapshot)
    with pytest.raises(ValueError):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


def test_e73_seed_launch_and_backend_report_go_through_existing_evidence(tmp_path):
    from src.learning.experiment_reconciliation import completion_evidence

    bench = _golden(tmp_path)
    bench.run()
    experiment = bench.state.current_experiment
    snap = _snapshot(experiment)
    variant = bench.state.plan[1]
    candidate = snap[ee.STUDY_TYPE]["candidates"][1]
    readback = {
        "final_prompt": candidate["expected_positive"],
        "final_negative_prompt": candidate["expected_negative"],
    }

    def result(report=None, **changes):
        entry = {**readback, "runtime_admission": {"launch_profile": "one"}, **changes}
        if report is not None:
            entry["backend_textual_inversion"] = report
        return {
            "metadata": {**readback, "all_seeds": [101, 102, 103], "all_subseeds": [700, 701, 702]},
            "variants": [entry],
        }

    silent = completion_evidence(experiment, variant, result()).execution_metadata
    assert silent["controlled_evidence_valid"] is True
    assert silent["embedding_consumption_status"] == ee.CONSUMPTION_REQUEST_ONLY
    reported = completion_evidence(
        experiment, variant, result({"reported": True, "names": [A]})
    ).execution_metadata
    assert reported["controlled_evidence_valid"] is True
    assert reported["embedding_consumption_status"] == ee.CONSUMPTION_REPORTED
    contradicted = completion_evidence(
        experiment, variant, result({"reported": True, "names": [B]})
    ).execution_metadata
    assert contradicted["controlled_evidence_valid"] is False
    assert contradicted["embedding_consumption_status"] == ee.CONSUMPTION_CONTRADICTED
    wrong = copy.deepcopy(result())
    wrong["variants"][0]["final_prompt"] = candidate["expected_positive"] + f" {C}"
    wrong["metadata"]["final_prompt"] = wrong["variants"][0]["final_prompt"]
    assert (
        completion_evidence(experiment, variant, wrong).execution_metadata[
            "controlled_evidence_valid"
        ]
        is False
    )
    experiment.metadata.update(observed_seed_vector=[101, 102, 103], observed_launch_profile="one")
    seed = copy.deepcopy(result())
    seed["metadata"]["all_seeds"] = [101, 102, 104]
    assert (
        completion_evidence(experiment, variant, seed).execution_metadata[
            "controlled_evidence_valid"
        ]
        is False
    )
    launch = result()
    launch["variants"][0]["runtime_admission"]["launch_profile"] = "two"
    assert (
        completion_evidence(experiment, variant, launch).execution_metadata[
            "controlled_evidence_valid"
        ]
        is False
    )


def test_e74_restart_reconciles_exact_sqlite_jobs_without_resubmission(tmp_path):
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
            display_name="Embedding",
            payload=payload,
            experiment_id=bench.state.current_experiment.experiment_id,
        )
        candidate = _snapshot(bench.state.current_experiment)[ee.STUDY_TYPE]["candidates"][1]
        completed = {
            "variants": [
                {
                    "output_paths": [str(tmp_path / f"{i}.png") for i in range(3)],
                    "all_seeds": [101, 102, 103],
                    "all_subseeds": [700, 701, 702],
                    "final_prompt": candidate["expected_positive"],
                    "final_negative_prompt": candidate["expected_negative"],
                    "runtime_admission": {"launch_profile": "one"},
                    "backend_textual_inversion": {"reported": True, "names": [A]},
                }
            ]
        }
        transition(repository, bench.state.plan[1].job_id, JobStatus.COMPLETED, result=completed)
        restored, fresh_service = recreated(store.load_session(handle.experiment_id), repository)
        assert [v.job_id for v in restored.learning_state.plan] == [
            v.job_id for v in bench.state.plan
        ]
        assert restored.learning_state.selected_variant.param_value == "B"
        metadata = restored.learning_state.plan[1].execution_metadata
        assert metadata["controlled_evidence_valid"] is True
        assert metadata["embedding_consumption_status"] == ee.CONSUMPTION_REPORTED
        assert not fresh_service.calls
    finally:
        repository.close()


def test_e75_the_study_is_local_only_and_the_variable_has_no_historical_metadata():
    from src.learning.learning_controller_services.controlled_studies import (
        LOCAL_ONLY_STUDIES,
        service_for,
    )
    from src.learning.variable_metadata import get_variable_metadata

    assert ee.STUDY_TYPE in LOCAL_ONLY_STUDIES and service_for(ee.STUDY_TYPE) is not None
    assert service_for("controlled_variable") is None
    assert get_variable_metadata(ee.VARIABLE) is None


# -- F. Registry inventory (identity and safe compatibility) ----------------------------------------------------


def test_e76_inventory_projection_never_trusts_names_or_pickles():
    from src.learning import embedding_inventory as inv

    def resource(**fields):
        base = {
            "name": "x",
            "sha256": sha("x"),
            "file_format": ".safetensors",
            "structure": inv.STRUCTURE_SDXL,
            "suitability": "sdxl",
            "vectors": 8,
        }
        return inv.EmbeddingResource(**{**base, **fields})

    classify = inv.asset_from_resource
    assert classify(resource(), "sdxl").status == STATUS_COMPATIBLE
    assert (
        classify(resource(suitability="sd15", structure="sd15_clip_l"), "sdxl").status
        == STATUS_INCOMPATIBLE
    )
    assert (
        classify(resource(file_format=".pt"), "sdxl").status == STATUS_UNVERIFIED
    )  # pickle: never opened
    assert classify(resource(file_format=".bin"), "sdxl").status == STATUS_UNVERIFIED
    assert classify(resource(file_format=".ckpt"), "sdxl").status == STATUS_INCOMPATIBLE
    assert classify(resource(structure="", suitability=""), "sdxl").status == STATUS_UNVERIFIED
    assert (
        classify(resource(error="header unreadable", structure=""), "sdxl").status
        == STATUS_UNVERIFIED
    )
    assert classify(resource(locations=2), "sdxl").status == STATUS_AMBIGUOUS
    assert classify(resource(fingerprint_current=False), "sdxl").status == STATUS_STALE
    # a name that looks like SDXL does not make an unknown structure compatible
    assert (
        classify(resource(name="sdxl_pony_xl", structure="", suitability=""), "sdxl").status
        == STATUS_UNVERIFIED
    )


def test_e77_inventory_rows_search_fixed_and_selectable_state():
    from src.learning import embedding_inventory as inv

    resources = {
        A: inv.EmbeddingResource(A, sha(A), ".safetensors", 1, inv.STRUCTURE_SDXL, "sdxl", 8),
        B: inv.EmbeddingResource(B, sha(B), ".pt"),
        "zeta": inv.EmbeddingResource(
            "zeta", sha("zeta"), ".safetensors", 1, inv.STRUCTURE_SDXL, "sdxl", 8
        ),
    }
    rows = inv.inventory_rows(resources, "sdxl", fixed=["zeta"], baseline=[A])
    assert [r.name for r in rows] == [B, A, "zeta"]  # case-insensitive order
    by_name = {r.name: r for r in rows}
    assert by_name[A].selectable and by_name[A].label.startswith("In baseline prompt")
    assert not by_name[B].selectable and "unverified" in by_name[B].label.lower()
    assert not by_name["zeta"].selectable and by_name["zeta"].fixed
    assert [r.name for r in inv.inventory_rows(resources, "sdxl", query="grain")] == [B]
    assert [r.name for r in inv.inventory_rows(resources, "sdxl", visible=lambda n: n != B)] == [
        A,
        "zeta",
    ]


def test_e78_discovered_inventory_is_the_preview_and_run_identity_evidence(tmp_path):
    import src.learning.embedding_inventory as inv

    bench = _bench(tmp_path)
    bench.controller._learning_embedding_asset_resolver = None
    kwargs = {
        "variable": ee.VARIABLE,
        "images": 1,
        "study_type": ee.STUDY_TYPE,
        "custom_prompt": KNIGHT,
        "embedding_experiment": _spec(ee.PRESENCE, PRESENCE_PAIRS),
    }
    # With no discovery, identity comes from the cache-only registry, which can never prove SDXL structure.
    with pytest.raises(
        ValueError, match="(?i)unverified|unknown availability|not in the local|WebUI root"
    ):
        bench.preview(**kwargs)
    bench.controller.embedding_inventory = {
        A: inv.EmbeddingResource(A, sha(A), ".safetensors", 1, inv.STRUCTURE_SDXL, "sdxl", 8)
    }
    bench.preview(**kwargs)
    frozen = _snapshot(bench.state.current_experiment)[ee.STUDY_TYPE]
    assert frozen["candidates"][1]["asset"]["sha256"] == sha(A)
    assert frozen["candidates"][1]["asset"]["status"] == STATUS_COMPATIBLE
    # Changing the discovered file after Preview is a stale identity at Run.
    bench.controller.embedding_inventory = {
        A: inv.EmbeddingResource(
            A, sha(A), ".safetensors", 1, inv.STRUCTURE_SDXL, "sdxl", 8, fingerprint_current=False
        )
    }
    with pytest.raises(ValueError, match="asset identity"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


def test_discovery_reads_only_safetensors_headers_and_never_persists(tmp_path):
    """The worker uses the accepted header-only reader; pickle containers are listed but not opened."""
    import struct

    from src.assets import AssetRegistry
    from src.learning import embedding_inventory as inv

    webui = tmp_path / "webui"
    folder = webui / "embeddings"
    folder.mkdir(parents=True)
    header = json.dumps(
        {
            "clip_l": {"dtype": "F32", "shape": [2, 768], "data_offsets": [0, 6144]},
            "clip_g": {"dtype": "F32", "shape": [2, 1280], "data_offsets": [6144, 16384]},
        }
    ).encode()
    (folder / "GoodStyle.safetensors").write_bytes(
        struct.pack("<Q", len(header)) + header + b"\0" * 16384
    )
    pickle_bytes = b"not really a pickle, must never be loaded"
    (folder / "OldStyle.pt").write_bytes(pickle_bytes)
    (webui / "models").mkdir()
    registry = AssetRegistry(webui_root=webui, cache_path=tmp_path / "cache.json")
    found = inv.discover_embeddings(lambda: False, registry)
    assert set(found) == {"GoodStyle", "OldStyle"}
    assert found["GoodStyle"].structure == inv.STRUCTURE_SDXL and found["GoodStyle"].vectors == 2
    assert inv.asset_from_resource(found["GoodStyle"], "sdxl").status == STATUS_COMPATIBLE
    assert found["OldStyle"].structure == "" and found["OldStyle"].file_format == ".pt"
    assert inv.asset_from_resource(found["OldStyle"], "sdxl").status == STATUS_UNVERIFIED
    assert (folder / "OldStyle.pt").read_bytes() == pickle_bytes
    assert not (tmp_path / "cache.json").exists()  # discovery does not persist
    with pytest.raises(InterruptedError):
        inv.discover_embeddings(lambda: True, registry)
    resolver = inv.inventory_resolver(found, "sdxl")
    assert resolver("goodstyle").status == STATUS_COMPATIBLE
    (folder / "GoodStyle.safetensors").write_bytes(b"x")
    assert resolver("GoodStyle").status == STATUS_STALE
