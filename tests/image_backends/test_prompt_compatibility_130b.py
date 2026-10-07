"""PR-IMG-130B: deterministic Prompt-target compatibility analysis (pure; no Tk, I/O, network or model).

The analysis consumes ``ModelPolicy`` only: SDXL, the exact Klein profile, unknown/conflicting evidence and a synthetic
future policy. It describes; it never rewrites a prompt, and its findings never echo prompt text or asset names.
"""

from __future__ import annotations

import copy
import inspect
from unittest.mock import Mock

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.image_backends import model_policy as mp
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.model_policy import ControlPolicy, FeaturePolicy, ModelPolicy, Support
from src.prompting import prompt_compatibility as pc
from src.prompting.prompt_compatibility import (
    PromptStateSnapshot,
    Severity,
    detect_dialect_patterns,
    project_prompt_target,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "juggernaut.safetensors"
SECRET = "xyzzy-private-subject"


def _sdxl() -> ModelPolicy:
    lookup = Mock(return_value=CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()))
    return mp.resolve_model_policy(SDXL, family_lookup=lookup)


def _klein() -> ModelPolicy:
    return mp.resolve_model_policy(KLEIN)


def _unknown(status: CompatibilityStatus = CompatibilityStatus.UNKNOWN) -> ModelPolicy:
    return mp.resolve_model_policy("mystery.safetensors", family_lookup=Mock(return_value=CompatibilityProfile(status, None, ())))


def _resolver(table: dict[str, KleinLoraStatus]):
    def resolve(name: str) -> KleinLoraDecision:
        status = table.get(name, KleinLoraStatus.UNVERIFIED)
        return KleinLoraDecision(name=name, status=status, reason="test evidence")

    return resolve


def _project(policy: ModelPolicy, model: str, **state):
    resolver = state.pop("resolver", None)
    return project_prompt_target(policy, model, PromptStateSnapshot(**state), lora_resolver=resolver)


def _codes(projection) -> set[str]:
    return set(projection.codes())


# --- SDXL: today's behavior, nothing added -----------------------------------------------------------------------------


def test_sdxl_target_keeps_every_prompt_tool_available_and_adds_no_findings() -> None:
    projection = _project(
        _sdxl(), SDXL, positive_text="(masterpiece:1.3), best quality, highres BREAK a cat", negative_text="blurry",
        positive_embedding_count=2, negative_embedding_count=1, loras=(("a", 0.8), ("b", 0.5)), optimizer_enabled=True,
    )

    assert projection.label == f"Prompt Target: SDXL — {SDXL}"
    assert projection.family == "sdxl" and projection.prompt_dialect == mp.DIALECT_WEIGHTED_TAGS
    assert projection.optimizer_available and projection.embedding_additions_allowed and projection.negative_prompt_supported
    assert projection.findings == () and projection.guidance == () and projection.runnable_as_authored
    assert projection.negative_note == projection.optimizer_note == projection.embeddings_note == ""


# --- exact Klein ---------------------------------------------------------------------------------------------------------


def test_exact_klein_projects_its_profile_not_generic_flux() -> None:
    projection = _project(_klein(), KLEIN)

    assert projection.label == "Prompt Target: FLUX.2 Klein 4B FP8 — profile v2"
    assert projection.family == mp.FAMILY_FLUX2_KLEIN != "flux"
    assert projection.profile_ref == {"id": "flux2_klein_4b_fp8", "version": 2}
    assert projection.prompt_dialect == mp.DIALECT_NATURAL_LANGUAGE
    assert any("natural-language" in line for line in projection.guidance)
    assert not projection.optimizer_available and not projection.embedding_additions_allowed
    assert not projection.negative_prompt_supported and projection.findings == ()


def test_a_non_empty_negative_prompt_is_action_required_and_the_text_is_untouched() -> None:
    state = PromptStateSnapshot(negative_text=f"blurry, {SECRET}")
    before = copy.deepcopy(state)

    projection = project_prompt_target(_klein(), KLEIN, state)

    finding = next(f for f in projection.findings if f.code == pc.NEGATIVE_PROMPT_UNSUPPORTED)
    assert finding.severity is Severity.ACTION_REQUIRED and finding.scope == "negative"
    assert SECRET not in finding.message and "blurry" not in finding.message
    assert not projection.runnable_as_authored and state == before
    assert "preserved" in projection.negative_note


def test_an_empty_or_whitespace_negative_prompt_raises_nothing() -> None:
    assert _project(_klein(), KLEIN, negative_text="  \n").findings == ()


def test_embeddings_are_action_required_with_counts_only() -> None:
    projection = _project(_klein(), KLEIN, positive_embedding_count=2, negative_embedding_count=1)

    finding = next(f for f in projection.findings if f.code == pc.EMBEDDINGS_UNSUPPORTED)
    assert finding.severity is Severity.ACTION_REQUIRED and dict(finding.details) == {"positive": 2, "negative": 1}
    assert "3 embedding" in finding.message and not projection.embedding_additions_allowed
    assert "removed" in projection.embeddings_note


def test_the_optimizer_is_unavailable_for_klein_and_an_enabled_setting_is_only_reported() -> None:
    off = _project(_klein(), KLEIN, optimizer_enabled=False)
    on = _project(_klein(), KLEIN, optimizer_enabled=True)

    assert not off.optimizer_available and pc.OPTIMIZER_NOT_APPLIED not in off.codes()
    assert pc.OPTIMIZER_NOT_APPLIED in on.codes()
    assert next(f for f in on.findings if f.code == pc.OPTIMIZER_NOT_APPLIED).severity is Severity.INFO
    assert "unchanged" in on.optimizer_note


# --- LoRA: the existing admission evidence, including the style LoRA -----------------------------------------------------------


def test_one_compatible_lora_is_runnable() -> None:
    projection = _project(_klein(), KLEIN, loras=(("a", 0.8),), resolver=_resolver({"a": KleinLoraStatus.COMPATIBLE}))

    assert projection.findings == () and projection.runnable_as_authored


def test_an_unverified_lora_is_action_required_without_naming_it() -> None:
    projection = _project(_klein(), KLEIN, loras=(("secret_lora", 0.8),), resolver=_resolver({}))

    finding = next(f for f in projection.findings if f.code == pc.LORA_NOT_VERIFIED)
    assert finding.severity is Severity.ACTION_REQUIRED and "secret_lora" not in finding.message


def test_two_slot_loras_exceed_the_one_lora_envelope() -> None:
    both = {"a": KleinLoraStatus.COMPATIBLE, "b": KleinLoraStatus.COMPATIBLE}
    projection = _project(_klein(), KLEIN, loras=(("a", 0.8), ("b", 0.5)), resolver=_resolver(both))

    finding = next(f for f in projection.findings if f.code == pc.LORA_COUNT_EXCEEDS_LIMIT)
    assert dict(finding.details)["limit"] == 1 and dict(finding.details)["count"] == 2
    assert not projection.runnable_as_authored


def test_a_slot_lora_plus_an_applied_style_lora_is_not_presented_as_runnable() -> None:
    both = {"a": KleinLoraStatus.COMPATIBLE, "style": KleinLoraStatus.COMPATIBLE}

    projection = _project(
        _klein(), KLEIN, loras=(("a", 0.8),), style_lora=("style", 0.65), resolver=_resolver(both)
    )

    finding = next(f for f in projection.findings if f.code == pc.LORA_COUNT_EXCEEDS_LIMIT)
    assert dict(finding.details)["style_lora_included"] is True and "Style Consistency" in finding.message
    assert not projection.runnable_as_authored


def test_the_style_lora_alone_obeys_the_same_exact_admission() -> None:
    ok = _project(_klein(), KLEIN, style_lora=("style", 0.65), resolver=_resolver({"style": KleinLoraStatus.COMPATIBLE}))
    bad = _project(_klein(), KLEIN, style_lora=("style", 0.65), resolver=_resolver({}))

    assert ok.findings == ()
    assert pc.LORA_NOT_VERIFIED in bad.codes() and not bad.runnable_as_authored


def test_lora_admission_is_the_existing_evaluator_not_a_second_resolver() -> None:
    source = inspect.getsource(pc)

    assert "assess_lora_selection" in source and "KleinLoraStatus" not in source and "evaluate_klein_loras" not in source


# --- dialect diagnostics (advisory, deterministic) -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A woman standing in a sunlit kitchen, holding a ceramic cup.", ()),
        ("A portrait, high quality photograph of a cat, soft light.", ()),  # one ordinary phrase
        ("masterpiece, best quality, a cat", ()),  # two boilerplate tags: below the threshold
        ("a cat <lora:style_one:0.8>", ()),  # a LoRA token alone is not SDXL syntax
        ("a cat <lora:one:0.8> <lora:two:0.4>", ()),
        ("A woman (see attached sketch) near the window", ()),  # an ordinary parenthetical
        ("The word break appears in lowercase prose; a break in the clouds.", ()),
        ("a [[subject]] standing near a [[place]]", ()),  # matrix markers are not prose
        ("a woman, (red dress:1.2), standing", (pc.DIALECT_WEIGHTED_ATTENTION,)),
        ("(masterpiece:1.3), a cat", (pc.DIALECT_WEIGHTED_ATTENTION,)),
        ("a cat sitting\nBREAK\na dog running", (pc.DIALECT_BREAK_SEPARATOR,)),
        ("masterpiece, best quality, highres, a cat", (pc.DIALECT_QUALITY_BOILERPLATE,)),
        ("Masterpiece, BEST QUALITY, 8K, ultra detailed", (pc.DIALECT_QUALITY_BOILERPLATE,)),
        ("(a:1.1) BREAK masterpiece, best quality, 4k", (pc.DIALECT_WEIGHTED_ATTENTION, pc.DIALECT_BREAK_SEPARATOR, pc.DIALECT_QUALITY_BOILERPLATE)),
    ],
)
def test_dialect_patterns_are_deterministic_and_conservative(text: str, expected: tuple[str, ...]) -> None:
    assert detect_dialect_patterns(text) == expected
    assert detect_dialect_patterns(text) == expected  # stable


def test_sdxl_syntax_under_klein_is_advisory_never_blocking_and_leaves_the_prompt_alone() -> None:
    text = f"(masterpiece:1.2), {SECRET}, BREAK, best quality, highres, 8k"
    state = PromptStateSnapshot(positive_text=text)

    projection = project_prompt_target(_klein(), KLEIN, state)

    assert _codes(projection) == {pc.DIALECT_WEIGHTED_ATTENTION, pc.DIALECT_BREAK_SEPARATOR, pc.DIALECT_QUALITY_BOILERPLATE}
    assert all(f.severity is Severity.ADVISORY and SECRET not in f.message for f in projection.findings)
    assert all("preserved" in f.message for f in projection.findings)
    assert projection.runnable_as_authored and state.positive_text == text


def test_plain_natural_language_under_klein_has_no_findings() -> None:
    assert _project(_klein(), KLEIN, positive_text="A quiet harbor at dawn, fishing boats rocking gently.").findings == ()


def test_dialect_findings_apply_only_to_natural_language_targets() -> None:
    text = "(masterpiece:1.3) BREAK best quality, highres, 8k"

    assert _project(_sdxl(), SDXL, positive_text=text).findings == ()
    assert _project(_unknown(), "mystery.safetensors", positive_text=text).codes() == (pc.TARGET_UNVERIFIED,)


# --- unknown / conflicting / future ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [CompatibilityStatus.UNKNOWN, CompatibilityStatus.CONFLICTING])
def test_unknown_or_conflicting_evidence_is_an_unverified_target_not_sdxl_or_klein(status: CompatibilityStatus) -> None:
    projection = _project(_unknown(status), "mystery.safetensors", negative_text="x", positive_embedding_count=1, loras=(("a", 1.0),))

    assert projection.label.startswith("Prompt Target: Unclassified — mystery.safetensors — ")
    assert "capabilities unverified" in projection.label
    assert ("conflicting" in projection.label) == (status is CompatibilityStatus.CONFLICTING)
    assert projection.family == mp.FAMILY_UNKNOWN and projection.policy_id != "sdxl" and projection.profile_ref is None
    assert projection.codes() == (pc.TARGET_UNVERIFIED,)  # nothing disabled, nothing claimed
    assert projection.optimizer_available and projection.embedding_additions_allowed and projection.negative_prompt_supported
    assert any("unverified" in line for line in projection.guidance)


def test_a_synthetic_future_policy_is_projected_from_policy_alone() -> None:
    future = ModelPolicy(
        policy_id="future_nl", family="future_nl", display_name="Future NL Model", evidence=mp.EVIDENCE_PROFILE,
        controls={name: ControlPolicy() for name in mp.VALUE_CONTROLS},
        features={
            **{name: FeaturePolicy(Support.SUPPORTED) for name in mp.FEATURES},
            "negative_prompt": FeaturePolicy(Support.UNSUPPORTED),
            "embeddings": FeaturePolicy(Support.UNSUPPORTED),
            "lora": FeaturePolicy(Support.UNSUPPORTED),
            "prompt_optimizer": FeaturePolicy(Support.SUPPORTED),
        },
        prompt_dialect=mp.DIALECT_NATURAL_LANGUAGE,
        profile_ref={"id": "future_nl", "version": 7},
    )

    projection = _project(
        future, "whatever.safetensors", positive_text="(x:1.2) BREAK y", negative_text="n", positive_embedding_count=1,
        loras=(("a", 1.0),), optimizer_enabled=True,
    )

    assert projection.label == "Prompt Target: Future NL Model — profile v7" and projection.optimizer_available
    assert _codes(projection) == {
        pc.NEGATIVE_PROMPT_UNSUPPORTED, pc.EMBEDDINGS_UNSUPPORTED, pc.LORA_UNSUPPORTED,
        pc.DIALECT_WEIGHTED_ATTENTION, pc.DIALECT_BREAK_SEPARATOR,
    }
    assert any("Future NL Model" in f.message for f in projection.findings)


# --- visibility, redaction, purity ------------------------------------------------------------------------------------------------


def test_hidden_content_yields_no_text_derived_findings_only_a_generic_notice() -> None:
    projection = _project(
        _klein(), KLEIN, positive_text=f"(a:1.2) {SECRET}", negative_text=SECRET, positive_hidden=True, negative_hidden=True
    )

    assert projection.codes() == (pc.CONTENT_HIDDEN,)
    assert all(SECRET not in f.message for f in projection.findings)


def test_findings_serialize_for_a_later_adaptation_package_without_content() -> None:
    projection = _project(_klein(), KLEIN, negative_text=SECRET, positive_text=f"(a:1.2) {SECRET}")

    payload = projection.to_dict()

    assert payload["profile_ref"] == {"id": "flux2_klein_4b_fp8", "version": 2}
    assert {f["code"] for f in payload["findings"]} == {pc.NEGATIVE_PROMPT_UNSUPPORTED, pc.DIALECT_WEIGHTED_ATTENTION}
    assert SECRET not in repr(payload)


def test_the_analysis_module_cannot_scan_hash_or_use_the_network() -> None:
    source = inspect.getsource(pc)

    for banned in (".refresh(", "hashlib", "import requests", "import socket", "urllib", "subprocess", "AssetRegistry", "_infer_model_family"):
        assert banned not in source, banned


def test_the_analysis_has_no_filename_or_klein_conditional() -> None:
    source = inspect.getsource(pc)

    for banned in ("klein_4b_fp8.safetensors", "is_klein", "flux-2-klein", "klein_selected"):
        assert banned not in source, banned


# --- review finding 1 (pure contract): a stored global negative under a no-negative target ----------------------------------------------


def test_a_stored_global_negative_is_an_informational_finding_not_an_action_required_one() -> None:
    projection = _project(_klein(), KLEIN, global_negative_present=True)

    finding = next(f for f in projection.findings if f.code == pc.GLOBAL_NEGATIVE_NOT_APPLIED)
    assert finding.severity is Severity.INFO and finding.scope == "negative"
    assert "FLUX.2 Klein 4B FP8" in finding.message and "stored" in finding.message
    assert projection.runnable_as_authored and projection.action_required == ()


def test_a_global_negative_is_unremarkable_where_negative_prompts_are_supported_or_unverified() -> None:
    assert _project(_sdxl(), SDXL, global_negative_present=True).findings == ()
    assert _project(_unknown(), "mystery.safetensors", global_negative_present=True).codes() == (pc.TARGET_UNVERIFIED,)
    assert _project(_klein(), KLEIN, global_negative_present=False).findings == ()
