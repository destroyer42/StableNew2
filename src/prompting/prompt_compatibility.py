"""Prompt-target compatibility analysis (PR-IMG-130B): what the selected model's policy means for the current prompt.

Pure and deterministic: no Tk, no I/O, no network, no model/WebUI/LLM call, no asset scan or hash. It consumes the
canonical ``ModelPolicy`` (PR-IMG-130A; never a filename or a Klein conditional) plus a read-only snapshot of the Prompt
state and returns an immutable projection: the target label, prompt dialect, feature applicability, operator guidance and
deterministic findings with stable machine-readable codes (the contract PR-IMG-130C can consume for explicit adaptation).

It never rewrites a prompt, an embedding, a LoRA or any stored setting; it describes. Exact executable decisions stay with
the compiler/backend and the existing LoRA admission evidence (``assess_lora_selection``). Findings never reproduce prompt
text, embedding names or LoRA names, and text-derived findings are not produced for content the visibility mode hides.

Severity: ``ACTION_REQUIRED`` is reserved for exact qualified-profile limits the backend will reject (non-empty negative
text, embeddings, LoRA admission). Syntax/style patterns are ``ADVISORY`` only (heuristics are never blocking).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.image_backends.forge_klein_lora import LoraResolver
from src.image_backends.model_policy import (
    DIALECT_NATURAL_LANGUAGE,
    EVIDENCE_CONFLICTING,
    FAMILY_UNKNOWN,
    ModelPolicy,
    Support,
)
from src.image_backends.model_policy_lora import assess_lora_selection


class Severity(str, Enum):
    INFO = "info"
    ADVISORY = "advisory"
    ACTION_REQUIRED = "action_required"


# -- stable finding codes ---------------------------------------------------------------------------------------------
TARGET_UNVERIFIED = "target_unverified"
CONTENT_HIDDEN = "content_hidden"
NEGATIVE_PROMPT_UNSUPPORTED = "negative_prompt_unsupported"
EMBEDDINGS_UNSUPPORTED = "embeddings_unsupported"
OPTIMIZER_NOT_APPLIED = "prompt_optimizer_not_applied"
GLOBAL_NEGATIVE_NOT_APPLIED = "global_negative_not_applied"
STYLE_LORA_NOT_EVALUATED = "style_lora_not_evaluated"
LORA_UNSUPPORTED = "lora_unsupported"
LORA_COUNT_EXCEEDS_LIMIT = "lora_count_exceeds_limit"
LORA_NOT_VERIFIED = "lora_not_verified"
DIALECT_WEIGHTED_ATTENTION = "dialect_weighted_attention_syntax"
DIALECT_BREAK_SEPARATOR = "dialect_break_separator"
DIALECT_QUALITY_BOILERPLATE = "dialect_quality_tag_boilerplate"

#: Distinct quality boilerplate tags needed before the (advisory) boilerplate finding fires: one ordinary phrase such
#: as "a high quality photograph" must never trigger it.
QUALITY_TAG_THRESHOLD = 3
_QUALITY_TAGS = (
    "masterpiece", "best quality", "high quality", "highres", "absurdres", "ultra detailed", "ultra-detailed",
    "extremely detailed", "intricate details", "8k", "4k", "uhd", "hdr", "sharp focus", "professional",
)
_QUALITY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(re.escape(tag) for tag in _QUALITY_TAGS) + r")(?![A-Za-z0-9])", re.IGNORECASE
)
#: Explicit attention weights such as ``(phrase:1.2)``; a bare parenthetical is ordinary prose. Shared with the adaptation
#: engine (PR-IMG-130C/140) so detection and adaptation can never recognise different syntax. Deliberately conservative
#: because automatic compilation acts on it: the weight must be a decimal written directly after the colon and the phrase
#: may contain no colon, so key/value prose such as ``(ratio: 2)`` or ``(ratio:2)`` is never treated as a weight.
WEIGHTED_ATTENTION_PATTERN = re.compile(r"\(\s*(?P<inner>[^()\n:]{1,120}?)\s*:(?P<weight>\d+\.\d+|\.\d+)\)")
BREAK_SEPARATOR_PATTERN = re.compile(r"(?<![A-Za-z0-9])BREAK(?![A-Za-z0-9])")  # the A1111 chunk separator is upper-case
#: Angle-bracket extra-network tokens (``<lora:...>`` and kin) and matrix ``[[slot]]`` markers are not prompt prose.
NON_PROSE_PATTERN = re.compile(r"<[^<>\n]*>|\[\[[^\[\]\n]*\]\]")


@dataclass(frozen=True, slots=True)
class PromptFinding:
    code: str
    severity: Severity
    #: Which part of the Prompt state the finding concerns: target, positive, negative, embeddings, lora, optimizer.
    scope: str
    #: Operator-facing sentence. Never contains prompt text, embedding names or LoRA names.
    message: str
    #: Machine-readable facts (counts, limits); never prompt content.
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "severity": self.severity.value, "scope": self.scope,
            "message": self.message, "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class PromptStateSnapshot:
    """The Prompt authoring state the analysis reads (copied values; the analysis never writes back)."""

    positive_text: str = ""
    negative_text: str = ""
    #: ``True`` when the content-visibility mode hides that text (text-derived findings are then suppressed).
    positive_hidden: bool = False
    negative_hidden: bool = False
    positive_embedding_count: int = 0
    negative_embedding_count: int = 0
    #: Slot LoRAs as (name, weight), in order.
    loras: tuple[tuple[str, float], ...] = ()
    #: The pack-level style LoRA that resolution will add as an executable LoRA token, when it is applied.
    style_lora: tuple[str, float] | None = None
    #: The stored Prompt Optimizer ``enabled`` setting (never modified by the analysis).
    optimizer_enabled: bool = False
    #: Whether a non-empty global negative prompt is stored (only the fact, never its text).
    global_negative_present: bool = False
    #: A style LoRA is selected but its availability has not been evaluated yet, so it is not counted (the analysis
    #: never triggers the scan that evaluation may need).
    style_lora_pending: bool = False


@dataclass(frozen=True, slots=True)
class PromptTargetProjection:
    label: str
    display_name: str
    family: str
    policy_id: str
    profile_ref: Mapping[str, Any] | None
    evidence: str
    prompt_dialect: str
    guidance: tuple[str, ...]
    findings: tuple[PromptFinding, ...]
    #: Feature applicability for the Prompt tab's controls (derived from ``ModelPolicy``; unverified is not disabled).
    optimizer_available: bool
    embedding_additions_allowed: bool
    negative_prompt_supported: bool
    #: One-line note beside the negative editor ("" when nothing to say).
    negative_note: str = ""
    optimizer_note: str = ""
    embeddings_note: str = ""
    #: Set when a stored global negative is not applied for this target ("" otherwise); never contains the text.
    global_negative_note: str = ""
    #: Whether the explicit target adaptation (PR-IMG-130C) has capability evidence to work from.
    adaptation_available: bool = False

    @property
    def action_required(self) -> tuple[PromptFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ACTION_REQUIRED)

    @property
    def runnable_as_authored(self) -> bool:
        """``False`` when an exact qualified-profile limit would be rejected before generation."""

        return not self.action_required

    def codes(self) -> tuple[str, ...]:
        return tuple(f.code for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "family": self.family, "policy_id": self.policy_id,
            "profile_ref": dict(self.profile_ref) if self.profile_ref else None,
            "evidence": self.evidence, "prompt_dialect": self.prompt_dialect,
            "findings": [f.to_dict() for f in self.findings],
        }


def _strip_non_prose(text: str) -> str:
    return NON_PROSE_PATTERN.sub(" ", text or "")


def detect_dialect_patterns(text: str) -> tuple[str, ...]:
    """Codes of clearly SDXL/A1111-oriented syntax in ``text`` (deterministic; a ``<lora:...>`` token is never one)."""

    prose = _strip_non_prose(text)
    found: list[str] = []
    if WEIGHTED_ATTENTION_PATTERN.search(prose):
        found.append(DIALECT_WEIGHTED_ATTENTION)
    if BREAK_SEPARATOR_PATTERN.search(prose):
        found.append(DIALECT_BREAK_SEPARATOR)
    distinct = {match.group(1).lower() for match in _QUALITY_PATTERN.finditer(prose)}
    if len(distinct) >= QUALITY_TAG_THRESHOLD:
        found.append(DIALECT_QUALITY_BOILERPLATE)
    return tuple(found)


_DIALECT_MESSAGES = {
    DIALECT_WEIGHTED_ATTENTION: "explicit attention-weight syntax such as (phrase:1.2)",
    DIALECT_BREAK_SEPARATOR: "the A1111 BREAK separator",
    DIALECT_QUALITY_BOILERPLATE: "a run of quality-tag boilerplate",
}


def target_is_unverified(policy: ModelPolicy) -> bool:
    """``True`` when StableNew lacks capability evidence for this target (unknown/conflicting family or an unqualified
    family label): nothing may be claimed or deterministically adapted for it."""

    return policy.family == FAMILY_UNKNOWN or (not policy.qualified and policy.feature("lora").support is Support.UNVERIFIED)


def target_label(policy: ModelPolicy, model_name: str | None) -> str:
    """``Prompt Target: ...`` text from the policy (never from the file name)."""

    model = str(model_name or "").strip() or "(no model selected)"
    if policy.qualified:
        version = (policy.profile_ref or {}).get("version")
        return f"Prompt Target: {policy.display_name} — profile v{version}"
    if policy.family == FAMILY_UNKNOWN:
        suffix = "evidence conflicting — capabilities unverified" if policy.evidence == EVIDENCE_CONFLICTING else "capabilities unverified"
        return f"Prompt Target: Unclassified — {model} — {suffix}"
    unverified = policy.feature("lora").support is Support.UNVERIFIED
    return f"Prompt Target: {policy.display_name} — {model}" + (" — capabilities unverified" if unverified else "")


def _guidance(policy: ModelPolicy) -> tuple[str, ...]:
    lines: list[str] = []
    if policy.prompt_dialect == DIALECT_NATURAL_LANGUAGE:
        lines.append(
            f"{policy.display_name} generally responds better to direct natural-language descriptions than to tag "
            "lists or weighted syntax. Your prompt is never rewritten."
        )
    if target_is_unverified(policy):
        lines.append("Capabilities for this model are unverified, so the Prompt tools behave as they always have.")
    return tuple(lines)


def project_prompt_target(
    policy: ModelPolicy,
    model_name: str | None,
    state: PromptStateSnapshot,
    *,
    lora_resolver: LoraResolver | None = None,
) -> PromptTargetProjection:
    """Describe the Prompt state against the selected model's policy. Pure; mutates nothing."""

    findings: list[PromptFinding] = []
    if target_is_unverified(policy):
        findings.append(PromptFinding(
            TARGET_UNVERIFIED, Severity.INFO, "target",
            "This model's capabilities are unverified; nothing is disabled and nothing is claimed.",
        ))
    if state.positive_hidden or state.negative_hidden:
        findings.append(PromptFinding(
            CONTENT_HIDDEN, Severity.INFO, "target",
            "Some prompt content is hidden by the content-visibility mode, so diagnostics about it are not shown.",
        ))

    negative = policy.feature("negative_prompt")
    negative_supported = negative.support is not Support.UNSUPPORTED
    negative_note = ""
    if not negative_supported:
        negative_note = (
            f"Not supported by {policy.display_name}: existing text is preserved and can still be edited or removed, "
            "but a non-empty negative prompt is rejected before generation."
        )
        if state.negative_text.strip() and not state.negative_hidden:
            findings.append(PromptFinding(
                NEGATIVE_PROMPT_UNSUPPORTED, Severity.ACTION_REQUIRED, "negative",
                f"A negative prompt is present but {policy.display_name} does not support one. Remove it to run on "
                "this model; the text is preserved and is not changed.",
            ))

    global_negative_note = ""
    if not negative_supported and state.global_negative_present:
        global_negative_note = f"Global Negative: stored but not applied for {policy.display_name}."
        findings.append(PromptFinding(
            GLOBAL_NEGATIVE_NOT_APPLIED, Severity.INFO, "negative",
            f"{global_negative_note} It is kept as you set it; the qualified profile deliberately disables global negative terms.",
        ))

    embeddings = policy.feature("embeddings")
    additions_allowed = embeddings.support is not Support.UNSUPPORTED
    embeddings_note = ""
    if not additions_allowed:
        embeddings_note = (
            f"Embeddings are not supported by {policy.display_name}: new ones cannot be added; existing entries are "
            "kept and can be removed."
        )
        total = state.positive_embedding_count + state.negative_embedding_count
        if total:
            findings.append(PromptFinding(
                EMBEDDINGS_UNSUPPORTED, Severity.ACTION_REQUIRED, "embeddings",
                f"{total} embedding(s) are selected but {policy.display_name} does not support embeddings. Remove them "
                "to run on this model; they are preserved and not changed.",
                {"positive": state.positive_embedding_count, "negative": state.negative_embedding_count},
            ))

    optimizer_available = policy.feature("prompt_optimizer").support is not Support.UNSUPPORTED
    optimizer_note = ""
    if not optimizer_available:
        optimizer_note = (
            f"Not applied for {policy.display_name}: the qualified profile disables the Prompt Optimizer. "
            "Your stored optimizer settings are unchanged."
        )
        if state.optimizer_enabled:
            findings.append(PromptFinding(
                OPTIMIZER_NOT_APPLIED, Severity.INFO, "optimizer",
                f"The Prompt Optimizer is enabled in your settings but is not applied for {policy.display_name}.",
            ))

    lora_policy = policy.feature("lora")
    style_matters = lora_policy.support is Support.UNSUPPORTED or (
        lora_policy.support is Support.SUPPORTED and lora_policy.limit is not None
    )  # only a bounded/unsupported LoRA envelope makes an unevaluated style LoRA relevant
    if state.style_lora_pending and style_matters:
        findings.append(PromptFinding(
            STYLE_LORA_NOT_EVALUATED, Severity.INFO, "lora",
            "A Style Consistency LoRA is selected but its availability has not been evaluated yet, so it is not counted "
            "here until the style status refreshes.",
        ))

    selected = list(state.loras)
    if state.style_lora is not None:
        selected.append(state.style_lora)
    if selected:
        assessment = assess_lora_selection(policy, selected, lora_resolver)
        style_included = state.style_lora is not None
        if assessment.exact and not assessment.supported:
            findings.append(PromptFinding(
                LORA_UNSUPPORTED, Severity.ACTION_REQUIRED, "lora",
                f"{policy.display_name} does not support LoRAs; the selection is preserved and not changed.",
                {"count": assessment.count},
            ))
        elif assessment.exact:
            if assessment.over_limit:
                findings.append(PromptFinding(
                    LORA_COUNT_EXCEEDS_LIMIT, Severity.ACTION_REQUIRED, "lora",
                    f"{assessment.count} LoRAs are selected but {policy.display_name} admits at most {assessment.limit}"
                    + (" (this includes the applied Style Consistency LoRA)." if style_included else ".")
                    + " Nothing is removed for you.",
                    {"count": assessment.count, "limit": assessment.limit, "style_lora_included": style_included},
                ))
            if assessment.not_verified:
                findings.append(PromptFinding(
                    LORA_NOT_VERIFIED, Severity.ACTION_REQUIRED, "lora",
                    f"{assessment.not_verified} selected LoRA(s) are not verified for {policy.display_name} and would be "
                    "rejected before generation.",
                    {"not_verified": assessment.not_verified, "style_lora_included": style_included},
                ))

    if policy.prompt_dialect == DIALECT_NATURAL_LANGUAGE and state.positive_text.strip() and not state.positive_hidden:
        for code in detect_dialect_patterns(state.positive_text):
            findings.append(PromptFinding(
                code, Severity.ADVISORY, "positive",
                f"This prompt appears to contain {_DIALECT_MESSAGES[code]}, which suits SDXL/A1111 more than "
                f"{policy.display_name}. Direct natural-language descriptions usually work better. Your original prompt "
                "is preserved.",
            ))

    return PromptTargetProjection(
        label=target_label(policy, model_name),
        display_name=policy.display_name,
        family=policy.family,
        policy_id=policy.policy_id,
        profile_ref=policy.profile_ref,
        evidence=policy.evidence,
        prompt_dialect=policy.prompt_dialect,
        guidance=_guidance(policy),
        findings=tuple(findings),
        optimizer_available=optimizer_available,
        embedding_additions_allowed=additions_allowed,
        negative_prompt_supported=negative_supported,
        negative_note=negative_note,
        optimizer_note=optimizer_note,
        embeddings_note=embeddings_note,
        global_negative_note=global_negative_note,
        adaptation_available=not target_is_unverified(policy),
    )


__all__ = [
    "BREAK_SEPARATOR_PATTERN",
    "CONTENT_HIDDEN",
    "DIALECT_BREAK_SEPARATOR",
    "DIALECT_QUALITY_BOILERPLATE",
    "DIALECT_WEIGHTED_ATTENTION",
    "EMBEDDINGS_UNSUPPORTED",
    "GLOBAL_NEGATIVE_NOT_APPLIED",
    "STYLE_LORA_NOT_EVALUATED",
    "LORA_COUNT_EXCEEDS_LIMIT",
    "LORA_NOT_VERIFIED",
    "LORA_UNSUPPORTED",
    "NEGATIVE_PROMPT_UNSUPPORTED",
    "NON_PROSE_PATTERN",
    "OPTIMIZER_NOT_APPLIED",
    "PromptFinding",
    "PromptStateSnapshot",
    "PromptTargetProjection",
    "QUALITY_TAG_THRESHOLD",
    "Severity",
    "TARGET_UNVERIFIED",
    "WEIGHTED_ATTENTION_PATTERN",
    "detect_dialect_patterns",
    "project_prompt_target",
    "target_is_unverified",
    "target_label",
]
