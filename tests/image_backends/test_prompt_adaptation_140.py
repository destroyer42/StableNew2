"""PR-PROMPT-140: the compile-safe structured entry point of the 130C engine, the repaired weighted-syntax recognizer, and the
bounded LoRA evidence context. Pure and deterministic: an injected resolver is the only evidence source.
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
from src.image_backends.model_policy_lora import LoraEvidenceContext, assess_lora_selection
from src.prompting import prompt_adaptation as pa
from src.prompting.prompt_adaptation import (
    LoraContribution as L,
)
from src.prompting.prompt_adaptation import (
    StructuredPromptInput,
    adapt_structured_prompt,
)
from src.prompting.prompt_adaptation import (
    TriggerContribution as T,
)
from src.prompting.prompt_compatibility import DIALECT_WEIGHTED_ATTENTION, detect_dialect_patterns

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "juggernaut.safetensors"
S = KleinLoraStatus


def _policy(model: str) -> ModelPolicy:
    sdxl = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
    return mp.resolve_model_policy(model, family_lookup=lambda name: sdxl if name == SDXL else None)


def _resolver(table: dict[str, KleinLoraStatus]):
    return lambda name: KleinLoraDecision(name=name, status=table.get(name, S.UNVERIFIED), reason="test")


def _adapt(policy: ModelPolicy, source: StructuredPromptInput, table: dict[str, KleinLoraStatus] | None = None):
    return adapt_structured_prompt(policy, source, lora_resolver=_resolver(table or {}))


# --- recognizer ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["(red dress:1.2)", "(a:.5)", "(x y z:0.80)", "(masterpiece, (a:1.1):1.3)"])
def test_genuine_decimal_attention_weights_are_recognized_and_flattened(text: str) -> None:
    assert DIALECT_WEIGHTED_ATTENTION in detect_dialect_patterns(text)
    flattened, count = pa._flatten_weighted_attention(text)
    assert count >= 1 and ":" not in flattened and "(" not in flattened.replace("(x y z", "")


@pytest.mark.parametrize("text", ["(ratio: 2)", "(ratio:2)", "(note: 5)", "(a: 1.2)", "(a :1.2 )", "(a:b:1.2)", "(at dusk)", "(1:2)"])
def test_ambiguous_key_value_prose_is_never_treated_as_a_weight(text: str) -> None:
    assert DIALECT_WEIGHTED_ATTENTION not in detect_dialect_patterns(text)
    assert pa._flatten_weighted_attention(text) == (text, 0)


# --- compile-safe selection ------------------------------------------------------------------------------------------------


def test_only_definitive_incompatibility_deletes_and_uncertainty_is_preserved_but_marked_incomplete() -> None:
    source = StructuredPromptInput(
        loras=(L("bad", 1.0, pa.KIND_ACTOR), L("unknown", 1.0, pa.KIND_PACK), L("conflict", 1.0, pa.KIND_PACK), L("good", 1.0, pa.KIND_STYLE))
    )
    out = _adapt(_policy(KLEIN), source, {"bad": S.INCOMPATIBLE, "conflict": S.CONFLICTING, "good": S.COMPATIBLE})

    assert [lora.name for lora in out.loras] == ["unknown", "conflict"]  # `good` is a compatible LoRA beyond the one-slot limit
    ops = {op.code for op in out.plan.operations}
    assert {pa.OP_LORA_DROPPED_INCOMPATIBLE, pa.OP_LORA_RETAINED_UNVERIFIED, pa.OP_LORA_RETAINED_CONFLICTING,
            pa.OP_STYLE_LORA_DROPPED_OVER_LIMIT} <= ops
    assert out.plan.complete is False and out.plan.mode == pa.MODE_COMPILE


def test_compatible_loras_keep_execution_order_until_the_limit_and_later_ones_are_dropped() -> None:
    source = StructuredPromptInput(loras=(L("a", 1.0, pa.KIND_ACTOR), L("b", 1.0, pa.KIND_PACK), L("c", 1.0, pa.KIND_STYLE)))
    out = _adapt(_policy(KLEIN), source, {"a": S.COMPATIBLE, "b": S.COMPATIBLE, "c": S.COMPATIBLE})
    assert [lora.name for lora in out.loras] == ["a"] and out.plan.complete is True
    over = out.plan.operations_for(pa.OP_LORA_DROPPED_OVER_LIMIT) + out.plan.operations_for(pa.OP_STYLE_LORA_DROPPED_OVER_LIMIT)
    assert [op.details["index"] for op in over] == [1, 2]


def test_a_missing_resolver_preserves_every_lora() -> None:
    source = StructuredPromptInput(loras=(L("a", 1.0, pa.KIND_PACK),))
    out = adapt_structured_prompt(_policy(KLEIN), source)
    assert [lora.name for lora in out.loras] == ["a"] and out.plan.complete is False


def test_unsupported_lora_feature_drops_every_lora_and_its_owned_triggers_only() -> None:
    future = _future(lora=FeaturePolicy(Support.UNSUPPORTED))
    source = StructuredPromptInput(
        loras=(L("a", 1.0, pa.KIND_ACTOR), L("s", 1.0, pa.KIND_STYLE)),
        triggers=(T("owned", pa.KIND_ACTOR, ("a",)), T("free", pa.KIND_ACTOR, ()), T("style words", pa.KIND_STYLE, ("s",))),
    )
    out = _adapt(future, source)
    assert out.loras == () and [t.text for t in out.triggers] == ["free"]
    assert out.plan.operations_for(pa.OP_ACTOR_TRIGGER_DROPPED) and out.plan.operations_for(pa.OP_STYLE_TRIGGER_DROPPED)


def test_a_trigger_shared_by_two_loras_survives_while_either_owner_survives() -> None:
    source = StructuredPromptInput(
        loras=(L("a1", 1.0, pa.KIND_ACTOR), L("a2", 1.0, pa.KIND_ACTOR)),
        triggers=(T("shared", pa.KIND_ACTOR, ("a1", "a2")),),
    )
    kept = _adapt(_policy(KLEIN), source, {"a1": S.INCOMPATIBLE, "a2": S.COMPATIBLE})
    assert [t.text for t in kept.triggers] == ["shared"]
    gone = _adapt(_policy(KLEIN), source, {"a1": S.INCOMPATIBLE, "a2": S.INCOMPATIBLE})
    assert gone.triggers == ()


def test_a_dropped_pack_lora_never_deletes_authored_prose_and_the_limitation_is_recorded() -> None:
    source = StructuredPromptInput(positive_prose=("keep my words bad_lora",), loras=(L("bad_lora", 1.0, pa.KIND_PACK),))
    out = _adapt(_policy(KLEIN), source, {"bad_lora": S.INCOMPATIBLE})
    assert out.positive_prose == ("keep my words bad_lora",) and out.loras == ()
    assert out.plan.operations_for(pa.OP_PACK_TRIGGER_UNOWNED)


# --- negative channel, embeddings, dialect ------------------------------------------------------------------------------------


def test_an_unsupported_negative_channel_omits_every_negative_component_and_embedding() -> None:
    source = StructuredPromptInput(
        negative_prose=("global", "pack", "phrase"), negative_embeddings=(("n", 1.0),), positive_embeddings=(("p", 1.0),),
        global_negative_present=True, optimizer_enabled=True,
    )
    out = _adapt(_policy(KLEIN), source)
    assert out.negative_channel is False and out.negative_prose == ("", "", "") and out.negative_embeddings == () and out.positive_embeddings == ()
    assert {op.code for op in out.plan.operations} >= {
        pa.OP_NEGATIVE_DROPPED, pa.OP_POSITIVE_EMBEDDING_DROPPED, pa.OP_NEGATIVE_EMBEDDING_DROPPED,
        pa.OP_GLOBAL_NEGATIVE_NOT_APPLIED, pa.OP_OPTIMIZER_NOT_APPLIED,
    }


def test_sdxl_is_an_identity_projection_and_dialect_rules_apply_per_component() -> None:
    source = StructuredPromptInput(
        positive_prose=("(a:1.2)", "x BREAK y"), negative_prose=("(n:1.1)",), loras=(L("l", 0.5, pa.KIND_PACK),),
        negative_embeddings=(("n", 1.0),),
    )
    sdxl = _adapt(_policy(SDXL), source)
    assert sdxl.positive_prose == source.positive_prose and sdxl.negative_prose == source.negative_prose
    assert sdxl.loras == source.loras and sdxl.plan.changed is False and sdxl.plan.operations == ()

    supported = _adapt(_future(negative_prompt=FeaturePolicy(Support.SUPPORTED), embeddings=FeaturePolicy(Support.SUPPORTED)), source)
    assert supported.positive_prose == ("a", "x\n\ny") and supported.negative_prose == ("n",)
    assert supported.negative_embeddings == (("n", 1.0),)  # a supported channel keeps its embeddings


def test_unknown_targets_are_refused_unchanged_and_incomplete() -> None:
    source = StructuredPromptInput(positive_prose=("(a:1.2)",), negative_prose=("n",), loras=(L("l", 1.0, pa.KIND_PACK),))
    out = _adapt(_policy("mystery.safetensors"), source, {"l": S.INCOMPATIBLE})
    assert out.positive_prose == source.positive_prose and out.loras == source.loras and out.negative_prose == ("n",)
    assert out.plan.adaptable is False and out.plan.complete is False and out.plan.codes() == (pa.OP_TARGET_UNVERIFIED,)


def test_a_synthetic_future_policy_is_driven_only_by_policy() -> None:
    future = _future(lora=FeaturePolicy(Support.SUPPORTED, limit=2), negative_prompt=FeaturePolicy(Support.UNSUPPORTED))
    source = StructuredPromptInput(
        positive_prose=("a (x:1.1)",), negative_prose=("bad",), loras=tuple(L(n, 1.0, pa.KIND_PACK) for n in "abc"),
    )
    out = _adapt(future, source)
    assert out.positive_prose == ("a x",) and out.negative_prose == ("",) and [lora.name for lora in out.loras] == ["a", "b"]
    assert out.plan.policy_id == "future_x" and out.plan.complete is True


def test_the_adapter_is_deterministic_immutable_pure_and_content_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("adaptation must be pure")

    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    source = StructuredPromptInput(positive_prose=("secret (x:1.1)",), loras=(L("secret_lora", 1.0, pa.KIND_PACK),))
    before = dataclasses.asdict(source)
    first = _adapt(_policy(KLEIN), source, {"secret_lora": S.COMPATIBLE})
    second = _adapt(_policy(KLEIN), source, {"secret_lora": S.COMPATIBLE})
    assert first == second and dataclasses.asdict(source) == before
    assert "secret" not in repr(first.plan.to_diagnostics())


# --- assessment statuses and the bounded evidence context -------------------------------------------------------------------------


def test_assessment_exposes_the_stable_pr_img_117_decision_status_per_lora() -> None:
    table = {"c": S.COMPATIBLE, "i": S.INCOMPATIBLE, "k": S.CONFLICTING}
    for name, status in table.items():
        assessment = assess_lora_selection(_policy(KLEIN), [(name, 0.5)], _resolver(table))
        assert assessment.statuses == {name: status.value}
    assert assess_lora_selection(_policy(KLEIN), [("x", 0.5)], None).statuses == {"x": "unverified"}  # no resolver: unverified


def test_the_evidence_context_resolves_each_distinct_name_once() -> None:
    calls: list[str] = []

    def resolver(name: str) -> KleinLoraDecision:
        calls.append(name)
        return KleinLoraDecision(name, S.COMPATIBLE, "ok")

    context = LoraEvidenceContext(resolver)
    for _ in range(5):
        for name in ("a", "b", "a"):
            assert context(name).runnable
    assert calls == ["a", "b"] and context.lookups == 2
    assert not LoraEvidenceContext(None)("x").runnable


def _future(**features: FeaturePolicy) -> ModelPolicy:
    feats = {name: FeaturePolicy(Support.UNSUPPORTED) for name in mp.FEATURES}
    feats.update(features)
    return ModelPolicy(
        policy_id="future_x", family="future_x", display_name="Future X", evidence=mp.EVIDENCE_PROFILE,
        controls={name: ControlPolicy() for name in mp.VALUE_CONTROLS}, features=feats,
        profile_ref={"id": "future_x", "version": 1}, prompt_dialect=mp.DIALECT_NATURAL_LANGUAGE,
    )
