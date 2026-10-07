"""PR-IMG-130C: the pure, policy-driven prompt adaptation engine.

Everything is deterministic and in memory: the canonical ``ModelPolicy`` (PR-IMG-130A) decides, the existing exact LoRA
admission (PR-IMG-117 via ``assess_lora_selection``) is reached through an injected resolver, and no test reads a file,
scans, hashes or touches the network. The authored input is never modified.
"""

from __future__ import annotations

import dataclasses
import socket
import subprocess

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.image_backends import model_policy as mp
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.model_policy import ControlPolicy, FeaturePolicy, ModelPolicy, Support
from src.prompting import prompt_adaptation as pa
from src.prompting.prompt_adaptation import PromptAdaptationInput, adapt_prompt_for_target

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "juggernaut.safetensors"
MYSTERY = "mystery.safetensors"
_SDXL_EVIDENCE = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
_CONFLICT = CompatibilityProfile(CompatibilityStatus.CONFLICTING, None, ())
_FLUX_OTHER = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.FLUX, ())


def _lookup(name: str):
    return {SDXL: _SDXL_EVIDENCE, MYSTERY: _CONFLICT, "flux-other.safetensors": _FLUX_OTHER}.get(name)


def _policy(model: str) -> ModelPolicy:
    return mp.resolve_model_policy(model, family_lookup=_lookup)


def _resolver(table: dict[str, KleinLoraStatus]):
    return lambda name: KleinLoraDecision(name=name, status=table.get(name, KleinLoraStatus.UNVERIFIED), reason="test evidence")


OK = KleinLoraStatus.COMPATIBLE


def _sdxl_authored(**overrides) -> PromptAdaptationInput:
    base = {
        "positive_text": "masterpiece, (red dress:1.2), a lighthouse (at dusk) BREAK a quiet harbor",
        "negative_text": "blurry, watermark",
        "positive_embeddings": (("pos_embed", 0.9),),
        "negative_embeddings": (("neg_embed", 0.7),),
        "loras": (("lora_a", 0.8),),
        "optimizer_enabled": True,
        "global_negative_present": True,
    }
    base.update(overrides)
    return PromptAdaptationInput(**base)


def _future_policy(**features: FeaturePolicy) -> ModelPolicy:
    """A synthetic qualified future family: nothing about it is Klein, so any filename/family conditional would fail."""

    feats = {name: FeaturePolicy(Support.UNSUPPORTED) for name in mp.FEATURES}
    feats.update(features)
    return ModelPolicy(
        policy_id="future_model_x", family="future_x", display_name="Future X", evidence=mp.EVIDENCE_PROFILE,
        controls={name: ControlPolicy() for name in mp.VALUE_CONTROLS}, features=feats,
        profile_ref={"id": "future_model_x", "version": 3}, prompt_dialect=mp.DIALECT_NATURAL_LANGUAGE,
    )


# --- determinism / identity ---------------------------------------------------------------------------------------------


def test_identical_input_policy_and_evidence_produce_identical_plans() -> None:
    resolver = _resolver({"lora_a": OK})
    first = adapt_prompt_for_target(_policy(KLEIN), _sdxl_authored(), lora_resolver=resolver)
    second = adapt_prompt_for_target(_policy(KLEIN), _sdxl_authored(), lora_resolver=resolver)
    assert first == second
    assert first.to_diagnostics() == second.to_diagnostics()


def test_sdxl_target_is_an_identity_projection() -> None:
    source = _sdxl_authored()
    plan = adapt_prompt_for_target(_policy(SDXL), source)

    assert plan.adaptable and not plan.changed and plan.reason == ""
    assert plan.positive_text == source.positive_text  # weighted syntax and BREAK exactly as authored
    assert plan.negative_text == source.negative_text
    assert plan.positive_embeddings == source.positive_embeddings and plan.negative_embeddings == source.negative_embeddings
    assert plan.loras == source.loras
    assert plan.operations == ()
    assert plan.family == mp.FAMILY_SDXL and plan.prompt_dialect == mp.DIALECT_WEIGHTED_TAGS and plan.ruleset_version == pa.ADAPTATION_RULESET_VERSION


def test_adaptation_never_modifies_the_input() -> None:
    source = _sdxl_authored()
    before = dataclasses.asdict(source)
    adapt_prompt_for_target(_policy(KLEIN), source, lora_resolver=_resolver({"lora_a": OK}))
    assert dataclasses.asdict(source) == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.positive_text = "x"  # type: ignore[misc]


# --- natural-language dialect ----------------------------------------------------------------------------------------------


def test_klein_flattens_explicit_weighted_attention_and_preserves_ordinary_parentheses() -> None:
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(positive_text="a (red dress:1.2) and ((blue hat:1.1):0.8), a lighthouse (at dusk)")
    )
    assert plan.positive_text == "a red dress and blue hat, a lighthouse (at dusk)"
    flattened = plan.operations_for(pa.OP_WEIGHTED_FLATTENED)
    assert len(flattened) == 1 and flattened[0].details["count"] == 3 and flattened[0].scope == "positive"
    assert plan.changed


def test_ordinary_parenthetical_prose_is_never_stripped() -> None:
    text = "a lighthouse (at dusk), a harbor (quiet, still) and a boat"
    plan = adapt_prompt_for_target(_policy(KLEIN), PromptAdaptationInput(positive_text=text))
    assert plan.positive_text == text and not plan.changed and plan.operations == ()


def test_upper_case_break_is_normalized_to_a_paragraph_boundary_and_lowercase_break_is_prose() -> None:
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(positive_text="a quiet harbor, BREAK a red boat BREAK  waves")
    )
    assert plan.positive_text == "a quiet harbor\n\na red boat\n\nwaves"
    assert plan.operations_for(pa.OP_BREAK_NORMALIZED)[0].details["count"] == 2

    prose = "waves break on the rocks; the breaker and a BREAKER stay"
    kept = adapt_prompt_for_target(_policy(KLEIN), PromptAdaptationInput(positive_text=prose))
    assert kept.positive_text == prose and not kept.changed


def test_matrix_markers_and_extra_network_tokens_survive_unchanged() -> None:
    text = "a [[hair]] woman ([[hair]]:1.3) <lora:foo(bar:1.2):0.8> and [[BREAK]] BREAK end"
    plan = adapt_prompt_for_target(_policy(KLEIN), PromptAdaptationInput(positive_text=text))
    assert plan.positive_text == "a [[hair]] woman [[hair]] <lora:foo(bar:1.2):0.8> and [[BREAK]]\n\nend"


def test_quality_tag_boilerplate_is_preserved_not_invented_away() -> None:
    text = "masterpiece, best quality, ultra detailed, a quiet harbor"
    plan = adapt_prompt_for_target(_policy(KLEIN), PromptAdaptationInput(positive_text=text))
    assert plan.positive_text == text


# --- negative channel and embeddings ---------------------------------------------------------------------------------------


def test_unsupported_negative_and_embeddings_are_omitted_only_from_the_projection() -> None:
    source = _sdxl_authored()
    plan = adapt_prompt_for_target(_policy(KLEIN), source)

    assert plan.negative_text == "" and plan.negative_embeddings == () and plan.positive_embeddings == ()
    assert source.negative_text == "blurry, watermark" and source.negative_embeddings and source.positive_embeddings
    assert plan.operations_for(pa.OP_NEGATIVE_DROPPED)[0].effect == pa.EFFECT_DROPPED
    assert plan.operations_for(pa.OP_POSITIVE_EMBEDDING_DROPPED)[0].details["count"] == 1
    assert plan.operations_for(pa.OP_NEGATIVE_EMBEDDING_DROPPED)[0].details["count"] == 1


def test_negative_text_is_not_semantically_inverted_into_the_positive() -> None:
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(positive_text="a harbor", negative_text="blurry, malformed hands")
    )
    assert plan.positive_text == "a harbor" and "blurry" not in plan.positive_text and "hands" not in plan.positive_text


def test_a_blank_unsupported_negative_records_nothing() -> None:
    plan = adapt_prompt_for_target(_policy(KLEIN), PromptAdaptationInput(positive_text="a harbor", negative_text="   "))
    assert plan.operations_for(pa.OP_NEGATIVE_DROPPED) == ()


def test_supported_negative_and_embeddings_are_retained() -> None:
    policy = _future_policy(
        negative_prompt=FeaturePolicy(Support.SUPPORTED), embeddings=FeaturePolicy(Support.SUPPORTED),
    )
    source = _sdxl_authored(negative_text="blurry (hands:1.4)")
    plan = adapt_prompt_for_target(policy, source)
    assert plan.negative_text == "blurry hands"  # dialect rules also apply to a retained negative channel
    assert plan.positive_embeddings == source.positive_embeddings and plan.negative_embeddings == source.negative_embeddings
    assert plan.operations_for(pa.OP_NEGATIVE_DROPPED) == ()


def test_optimizer_and_global_negative_are_reported_not_applied_without_touching_values() -> None:
    plan = adapt_prompt_for_target(_policy(KLEIN), _sdxl_authored())
    assert plan.operations_for(pa.OP_OPTIMIZER_NOT_APPLIED)[0].effect == pa.EFFECT_NOT_APPLIED
    assert plan.operations_for(pa.OP_GLOBAL_NEGATIVE_NOT_APPLIED)
    quiet = adapt_prompt_for_target(_policy(KLEIN), PromptAdaptationInput(positive_text="a harbor"))
    assert quiet.operations_for(pa.OP_OPTIMIZER_NOT_APPLIED) == () and quiet.operations_for(pa.OP_GLOBAL_NEGATIVE_NOT_APPLIED) == ()


# --- LoRAs -----------------------------------------------------------------------------------------------------------------


def test_unsupported_loras_are_omitted() -> None:
    policy = _future_policy()  # lora unsupported
    plan = adapt_prompt_for_target(policy, PromptAdaptationInput(loras=(("a", 1.0), ("b", 0.5)), style_lora=("s", 0.6)))
    assert plan.loras == () and plan.style_lora is None
    assert len(plan.operations_for(pa.OP_LORA_DROPPED_UNSUPPORTED)) == 2
    assert len(plan.operations_for(pa.OP_STYLE_LORA_DROPPED_UNSUPPORTED)) == 1


def test_unverified_exact_admission_loras_are_omitted_and_compatible_ones_retained() -> None:
    resolver = _resolver({"good": OK})
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(loras=(("unknown_one", 0.8), ("good", 0.7))), lora_resolver=resolver
    )
    assert plan.loras == (("good", 0.7),)
    assert plan.operations_for(pa.OP_LORA_DROPPED_UNVERIFIED)[0].details["index"] == 0
    assert plan.operations_for(pa.OP_LORA_RETAINED)[0].details["index"] == 1


def test_no_resolver_means_no_lora_is_admitted() -> None:
    plan = adapt_prompt_for_target(_policy(KLEIN), PromptAdaptationInput(loras=(("good", 0.7),)))
    assert plan.loras == () and plan.operations_for(pa.OP_LORA_DROPPED_UNVERIFIED)


def test_a_rejected_weight_is_dropped_with_its_own_code_not_called_unverified() -> None:
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(loras=(("good", 3.5),)), lora_resolver=_resolver({"good": OK})
    )
    assert plan.loras == () and plan.operations_for(pa.OP_LORA_DROPPED_REJECTED) and not plan.operations_for(pa.OP_LORA_DROPPED_UNVERIFIED)


def test_lora_limit_keeps_authored_order_and_drops_later_compatible_loras() -> None:
    resolver = _resolver({"first": OK, "second": OK, "third": OK})
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(loras=(("first", 0.5), ("second", 0.6), ("third", 0.7))), lora_resolver=resolver
    )
    assert plan.loras == (("first", 0.5),)
    over = plan.operations_for(pa.OP_LORA_DROPPED_OVER_LIMIT)
    assert [op.details["index"] for op in over] == [1, 2] and over[0].details["limit"] == 1


def test_an_unverified_lora_does_not_consume_the_limit() -> None:
    resolver = _resolver({"second": OK})
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(loras=(("first", 0.5), ("second", 0.6))), lora_resolver=resolver
    )
    assert plan.loras == (("second", 0.6),)


def test_style_consistency_counts_against_the_same_limit_and_is_evaluated_after_slot_loras() -> None:
    resolver = _resolver({"slot": OK, "style": OK})
    plan = adapt_prompt_for_target(
        _policy(KLEIN),
        PromptAdaptationInput(loras=(("slot", 0.5),), style_lora=("style", 0.6), style_trigger_phrase="in the style of x"),
        lora_resolver=resolver,
    )
    assert plan.loras == (("slot", 0.5),) and plan.style_lora is None
    assert plan.operations_for(pa.OP_STYLE_LORA_DROPPED_OVER_LIMIT)
    assert plan.style_trigger_phrase == "" and plan.operations_for(pa.OP_STYLE_TRIGGER_DROPPED)

    alone = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(style_lora=("style", 0.6), style_trigger_phrase="in the style of x"),
        lora_resolver=resolver,
    )
    assert alone.style_lora == ("style", 0.6) and alone.style_trigger_phrase == "in the style of x"
    assert alone.operations_for(pa.OP_STYLE_LORA_RETAINED)


def test_a_pending_unscanned_style_lora_is_never_silently_accepted() -> None:
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(positive_text="a harbor", style_lora_pending=True), lora_resolver=_resolver({})
    )
    assert plan.style_lora is None
    dropped = plan.operations_for(pa.OP_STYLE_LORA_DROPPED_UNVERIFIED)
    assert dropped and dropped[0].details["reason"] == "not_evaluated"

    sdxl = adapt_prompt_for_target(_policy(SDXL), PromptAdaptationInput(style_lora_pending=True))
    assert sdxl.style_lora is None and sdxl.operations_for(pa.OP_STYLE_LORA_NOT_EVALUATED) and not sdxl.changed


def test_an_unverified_style_lora_is_omitted_from_the_projection() -> None:
    plan = adapt_prompt_for_target(
        _policy(KLEIN), PromptAdaptationInput(style_lora=("style", 0.6), style_trigger_phrase="trigger"), lora_resolver=_resolver({})
    )
    assert plan.style_lora is None and plan.operations_for(pa.OP_STYLE_LORA_DROPPED_UNVERIFIED) and plan.style_trigger_phrase == ""


# --- unknown / conflicting / future ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", [MYSTERY, "never-seen.safetensors", "", "flux-other.safetensors"])
def test_unknown_conflicting_or_unqualified_targets_refuse_adaptation_and_change_nothing(model: str) -> None:
    source = _sdxl_authored()
    plan = adapt_prompt_for_target(_policy(model), source, lora_resolver=_resolver({"lora_a": OK}))

    assert not plan.adaptable and not plan.changed and plan.reason == pa.OP_TARGET_UNVERIFIED
    assert plan.positive_text == source.positive_text and plan.negative_text == source.negative_text
    assert plan.loras == source.loras and plan.positive_embeddings == source.positive_embeddings
    assert plan.codes() == (pa.OP_TARGET_UNVERIFIED,)
    assert plan.family != mp.FAMILY_SDXL


def test_a_synthetic_future_policy_is_driven_by_policy_not_by_family_or_filename() -> None:
    future = _future_policy(
        negative_prompt=FeaturePolicy(Support.UNSUPPORTED),
        lora=FeaturePolicy(Support.SUPPORTED, limit=2),  # bounded, no exact-admission policy
    )
    plan = adapt_prompt_for_target(
        future, PromptAdaptationInput(positive_text="a (x:1.1) y", negative_text="bad", loras=(("a", 1.0), ("b", 1.0), ("c", 1.0)))
    )
    assert plan.positive_text == "a x y" and plan.negative_text == ""
    assert plan.loras == (("a", 1.0), ("b", 1.0)) and plan.operations_for(pa.OP_LORA_DROPPED_OVER_LIMIT)[0].details["index"] == 2
    assert plan.policy_id == "future_model_x" and plan.profile_ref == {"id": "future_model_x", "version": 3}

    weighted = dataclasses.replace(future, prompt_dialect=mp.DIALECT_WEIGHTED_TAGS)
    kept = adapt_prompt_for_target(weighted, PromptAdaptationInput(positive_text="a (x:1.1) y BREAK z"))
    assert kept.positive_text == "a (x:1.1) y BREAK z" and not kept.changed


def test_qualified_klein_plan_carries_the_exact_target_identity_without_content() -> None:
    plan = adapt_prompt_for_target(_policy(KLEIN), _sdxl_authored(), lora_resolver=_resolver({"lora_a": OK}))
    assert plan.profile_ref == _policy(KLEIN).profile_ref and plan.profile_ref is not None
    assert plan.evidence == mp.EVIDENCE_PROFILE and plan.prompt_dialect == mp.DIALECT_NATURAL_LANGUAGE
    diagnostics = plan.to_diagnostics()
    serialized = repr(diagnostics)
    for secret in ("lighthouse", "red dress", "blurry", "lora_a", "pos_embed", "neg_embed"):
        assert secret not in serialized
    assert diagnostics["ruleset_version"] == pa.ADAPTATION_RULESET_VERSION and diagnostics["changed"] is True


# --- purity: no scan / hash / network / process ----------------------------------------------------------------------------


def test_adaptation_performs_no_io_scan_hash_network_or_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("adaptation must be pure")

    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    calls: list[str] = []

    def resolver(name: str) -> KleinLoraDecision:
        calls.append(name)
        return KleinLoraDecision(name=name, status=OK, reason="cached evidence")

    plan = adapt_prompt_for_target(_policy(KLEIN), _sdxl_authored(), lora_resolver=resolver)
    assert plan.loras == (("lora_a", 0.8),) and calls  # only the injected (cache-only) evidence callable was consulted
