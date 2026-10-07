"""Explicit, deterministic, policy-driven prompt adaptation (PR-IMG-130C).

One pure answer to "how would this authored prompt material be adapted for that exact model target?". It consumes the
canonical ``ModelPolicy`` (PR-IMG-130A) and the existing exact LoRA admission (``assess_lora_selection`` over an injected
resolver, PR-IMG-117) and returns an immutable, versioned ``PromptAdaptationPlan``. It reproduces none of those rules and
contains no family, model-name or Klein conditional: a synthetic future policy adapts correctly.

Authored versus projected: the input is the operator's durable authoring material and is never modified; the plan is a
transient projection for one target. Nothing here touches a PromptPack, a workspace, a queue, a compiler or a runner; there
is no Tk, file, network, asset scan, hashing, model, LLM/VLM or process access. The Prompt tab previews the plan today; the
later compiler integration (PR-PROMPT-140) is meant to call the same ``adapt_prompt_for_target`` on structured components
*before* executable string rendering, so preview and execution cannot become two interpretation systems.

Deterministic compatibility adaptation only: explicit A1111 weighted-attention syntax is flattened, an upper-case ``BREAK``
becomes a paragraph boundary, and channels/assets the target does not support are omitted from the projection. There is no
semantic strength inference, no negative-to-positive inversion, no quality-tag rewriting and no prompt enhancement. Plans
carry stable operation codes and structured details (counts, indices, limits), never prompt text or asset names, so they are
safe to log and to freeze later into experiment evidence.

Known ownership gap (recorded, not hidden): a slot LoRA's trigger phrase lives inside the authored text, so this engine
cannot drop it with the LoRA; only the Style Consistency trigger phrase is a separate structured component. The compiler
integration must adapt structured components before rendering to close it. ``<lora:...>`` tokens and ``[[matrix]]``
markers typed into authored text are left exactly as written.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from src.image_backends.forge_klein_lora import LoraResolver
from src.image_backends.model_policy import (
    DIALECT_NATURAL_LANGUAGE,
    STAGE_TXT2IMG,
    ModelPolicy,
    Support,
)
from src.image_backends.model_policy_lora import assess_lora_selection
from src.prompting.prompt_compatibility import (
    BREAK_SEPARATOR_PATTERN,
    NON_PROSE_PATTERN,
    WEIGHTED_ATTENTION_PATTERN,
    target_is_unverified,
)

#: Version of the adaptation rule set; bump whenever any rule's output can change for the same input.
ADAPTATION_RULESET_VERSION = "130c.1"

# -- stable operation codes -------------------------------------------------------------------------------------------
OP_WEIGHTED_FLATTENED = "weighted_attention_flattened"
OP_BREAK_NORMALIZED = "break_separator_normalized"
OP_NEGATIVE_DROPPED = "negative_prompt_dropped_unsupported"
OP_POSITIVE_EMBEDDING_DROPPED = "positive_embedding_dropped_unsupported"
OP_NEGATIVE_EMBEDDING_DROPPED = "negative_embedding_dropped_unsupported"
OP_LORA_DROPPED_UNSUPPORTED = "lora_dropped_unsupported"
OP_LORA_DROPPED_UNVERIFIED = "lora_dropped_unverified"
OP_LORA_DROPPED_REJECTED = "lora_dropped_rejected"
OP_LORA_DROPPED_OVER_LIMIT = "lora_dropped_over_limit"
OP_LORA_RETAINED = "lora_retained_compatible"
OP_STYLE_LORA_DROPPED_UNSUPPORTED = "style_lora_dropped_unsupported"
OP_STYLE_LORA_DROPPED_UNVERIFIED = "style_lora_dropped_unverified"
OP_STYLE_LORA_DROPPED_REJECTED = "style_lora_dropped_rejected"
OP_STYLE_LORA_DROPPED_OVER_LIMIT = "style_lora_dropped_over_limit"
OP_STYLE_LORA_RETAINED = "style_lora_retained_compatible"
OP_STYLE_LORA_NOT_EVALUATED = "style_lora_not_evaluated"
OP_STYLE_TRIGGER_DROPPED = "style_trigger_dropped_with_lora"
OP_OPTIMIZER_NOT_APPLIED = "optimizer_not_applied"
OP_GLOBAL_NEGATIVE_NOT_APPLIED = "global_negative_not_applied"
OP_TARGET_UNVERIFIED = "target_unverified_no_adaptation"

# -- effects ----------------------------------------------------------------------------------------------------------
EFFECT_REWRITTEN = "rewritten"
EFFECT_DROPPED = "dropped"
EFFECT_RETAINED = "retained"
EFFECT_NOT_APPLIED = "not_applied"
EFFECT_REFUSED = "refused"

SCOPE_POSITIVE = "positive"
SCOPE_NEGATIVE = "negative"
SCOPE_EMBEDDINGS = "embeddings"
SCOPE_LORA = "lora"
SCOPE_STYLE = "style_lora"
SCOPE_OPTIMIZER = "optimizer"
SCOPE_TARGET = "target"

#: An upper-case ``BREAK`` becomes this one canonical boundary (an ordinary paragraph break).
BREAK_REPLACEMENT = "\n\n"
_MAX_FLATTEN_PASSES = 32
_BREAK_WITH_SURROUNDINGS = re.compile(
    r"\s*,?\s*(?P<word>" + BREAK_SEPARATOR_PATTERN.pattern + r")\s*,?\s*"
)
_PARAGRAPH_EDGES = re.compile(r"^(?:\n\n)+|(?:\n\n)+$")

EmbeddingEntries = tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class PromptAdaptationInput:
    """The structured authoring material to adapt (copied values; the engine never writes back)."""

    #: The rendered current positive text (template composed; Matrix markers still unexpanded).
    positive_text: str = ""
    negative_text: str = ""
    positive_embeddings: EmbeddingEntries = ()
    negative_embeddings: EmbeddingEntries = ()
    #: Slot LoRAs as (name, weight), in authored order.
    loras: tuple[tuple[str, float], ...] = ()
    #: The applied Style Consistency LoRA from the last existing availability evidence, if any.
    style_lora: tuple[str, float] | None = None
    #: The Style Consistency trigger phrase, a structured component owned by the style selection.
    style_trigger_phrase: str = ""
    #: A style is selected but its availability has not been evaluated yet (never scanned from here).
    style_lora_pending: bool = False
    optimizer_enabled: bool = False
    global_negative_present: bool = False


@dataclass(frozen=True, slots=True)
class AdaptationOperation:
    """One ordered, machine-readable adaptation step. ``details`` hold counts/indices/limits, never content."""

    code: str
    scope: str
    effect: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "scope": self.scope, "effect": self.effect, "details": dict(self.details)}


@dataclass(frozen=True, slots=True)
class PromptAdaptationPlan:
    """The deterministic projection of one authored input for one exact target."""

    ruleset_version: str
    policy_id: str
    family: str
    evidence: str
    profile_ref: Mapping[str, Any] | None
    prompt_dialect: str
    #: ``False`` when StableNew lacks capability evidence for the target: nothing was adapted.
    adaptable: bool
    #: ``True`` when the adapted prompt material differs from the authored input (informational ``not_applied`` notes
    #: about stored settings never count).
    changed: bool
    #: Stable reason when no deterministic adaptation could be made ("" otherwise).
    reason: str
    positive_text: str
    negative_text: str
    positive_embeddings: EmbeddingEntries
    negative_embeddings: EmbeddingEntries
    loras: tuple[tuple[str, float], ...]
    style_lora: tuple[str, float] | None
    style_trigger_phrase: str
    operations: tuple[AdaptationOperation, ...]

    def codes(self) -> tuple[str, ...]:
        return tuple(operation.code for operation in self.operations)

    def operations_for(self, code: str) -> tuple[AdaptationOperation, ...]:
        return tuple(operation for operation in self.operations if operation.code == code)

    def to_diagnostics(self) -> dict[str, Any]:
        """Content-free serialization (identity, flags, ordered operations and counts); safe for logs and evidence."""

        return {
            "ruleset_version": self.ruleset_version,
            "policy_id": self.policy_id,
            "family": self.family,
            "evidence": self.evidence,
            "profile_ref": dict(self.profile_ref) if self.profile_ref else None,
            "prompt_dialect": self.prompt_dialect,
            "adaptable": self.adaptable,
            "changed": self.changed,
            "reason": self.reason,
            "operations": [operation.to_dict() for operation in self.operations],
            "counts": {
                "positive_embeddings": len(self.positive_embeddings),
                "negative_embeddings": len(self.negative_embeddings),
                "loras": len(self.loras),
                "style_lora": 1 if self.style_lora is not None else 0,
                "negative_present": bool(self.negative_text.strip()),
            },
        }


# -- deterministic text rules -----------------------------------------------------------------------------------------


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """Spans of ``<...>`` extra-network tokens and ``[[matrix]]`` markers: not prose, never rewritten."""

    return [(match.start(), match.end()) for match in NON_PROSE_PATTERN.finditer(text)]


def _touches_protected(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    """A match wholly inside a protected span, or only partly overlapping one, is left alone.

    A match that *contains* whole protected spans (``([[hair]]:1.3)``) is fine: those spans are carried over verbatim.
    """

    for span_start, span_end in spans:
        if span_start < end and span_end > start and not (start <= span_start and span_end <= end):
            return True
    return False


def _flatten_weighted_attention(text: str) -> tuple[str, int]:
    total = 0
    for _ in range(_MAX_FLATTEN_PASSES):
        spans = _protected_spans(text)
        count = 0

        def flatten(match: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
            nonlocal count
            if _touches_protected(match.start(), match.end(), spans):
                return match.group(0)
            count += 1
            return match.group("inner")

        text = WEIGHTED_ATTENTION_PATTERN.sub(flatten, text)
        total += count
        if count == 0:
            break
    return text, total


def _normalize_break(text: str) -> tuple[str, int]:
    spans = _protected_spans(text)
    count = 0

    def normalize(match: re.Match[str]) -> str:
        nonlocal count
        if _touches_protected(match.start("word"), match.end("word"), spans):
            return match.group(0)
        count += 1
        return BREAK_REPLACEMENT

    result = _BREAK_WITH_SURROUNDINGS.sub(normalize, text)
    if count:
        result = _PARAGRAPH_EDGES.sub("", result)
    return result, count


def _adapt_text(text: str, scope: str, operations: list[AdaptationOperation]) -> str:
    text, flattened = _flatten_weighted_attention(text)
    if flattened:
        operations.append(AdaptationOperation(OP_WEIGHTED_FLATTENED, scope, EFFECT_REWRITTEN, {"count": flattened}))
    text, normalized = _normalize_break(text)
    if normalized:
        operations.append(AdaptationOperation(OP_BREAK_NORMALIZED, scope, EFFECT_REWRITTEN, {"count": normalized}))
    return text


# -- LoRA projection --------------------------------------------------------------------------------------------------


def _codes(is_style: bool) -> dict[str, str]:
    return {
        "unverified": OP_STYLE_LORA_DROPPED_UNVERIFIED if is_style else OP_LORA_DROPPED_UNVERIFIED,
        "rejected": OP_STYLE_LORA_DROPPED_REJECTED if is_style else OP_LORA_DROPPED_REJECTED,
        "over_limit": OP_STYLE_LORA_DROPPED_OVER_LIMIT if is_style else OP_LORA_DROPPED_OVER_LIMIT,
        "retained": OP_STYLE_LORA_RETAINED if is_style else OP_LORA_RETAINED,
    }


def _project_loras(
    policy: ModelPolicy,
    source: PromptAdaptationInput,
    lora_resolver: LoraResolver | None,
    operations: list[AdaptationOperation],
) -> tuple[tuple[tuple[str, float], ...], tuple[str, float] | None, str]:
    feature = policy.feature("lora", STAGE_TXT2IMG)
    style = source.style_lora
    trigger = source.style_trigger_phrase

    if feature.support is Support.UNSUPPORTED:
        for index, _lora in enumerate(source.loras):
            operations.append(AdaptationOperation(OP_LORA_DROPPED_UNSUPPORTED, SCOPE_LORA, EFFECT_DROPPED, {"index": index}))
        if style is not None or source.style_lora_pending:
            operations.append(
                AdaptationOperation(
                    OP_STYLE_LORA_DROPPED_UNSUPPORTED, SCOPE_STYLE, EFFECT_DROPPED, {"evaluated": style is not None}
                )
            )
        if style is not None and trigger.strip():
            operations.append(AdaptationOperation(OP_STYLE_TRIGGER_DROPPED, SCOPE_STYLE, EFFECT_DROPPED, {}))
        return (), None, ""
    if feature.support is not Support.SUPPORTED:
        # Unverified LoRA support: no destructive guess in either direction.
        return source.loras, style, trigger

    retained: list[tuple[str, float]] = []
    retained_style: tuple[str, float] | None = None
    # Slot LoRAs in authored order; the applied style LoRA is evaluated after every slot LoRA.
    candidates: list[tuple[bool, int, tuple[str, float]]] = [(False, i, lora) for i, lora in enumerate(source.loras)]
    if style is not None:
        candidates.append((True, 0, style))

    for is_style, index, lora in candidates:
        codes = _codes(is_style)
        scope = SCOPE_STYLE if is_style else SCOPE_LORA
        details: dict[str, Any] = {} if is_style else {"index": index}
        assessment = assess_lora_selection(policy, [lora], lora_resolver)
        if assessment.exact and assessment.not_verified:
            operations.append(AdaptationOperation(codes["unverified"], scope, EFFECT_DROPPED, details))
            continue
        if assessment.exact and assessment.blocked:
            operations.append(AdaptationOperation(codes["rejected"], scope, EFFECT_DROPPED, details))
            continue
        if feature.limit is not None and len(retained) >= feature.limit:  # the style LoRA is last, so it counts here too
            operations.append(
                AdaptationOperation(codes["over_limit"], scope, EFFECT_DROPPED, {**details, "limit": feature.limit})
            )
            continue
        if assessment.exact:
            operations.append(AdaptationOperation(codes["retained"], scope, EFFECT_RETAINED, details))
        if is_style:
            retained_style = lora
        else:
            retained.append(lora)

    if source.style_lora_pending and style is None:
        # Never silently accepted: an unevaluated style is not part of the projection, and nothing scans to find out.
        operations.append(
            AdaptationOperation(OP_STYLE_LORA_DROPPED_UNVERIFIED, SCOPE_STYLE, EFFECT_DROPPED, {"reason": "not_evaluated"})
            if feature.compatibility_policy
            else AdaptationOperation(OP_STYLE_LORA_NOT_EVALUATED, SCOPE_STYLE, EFFECT_NOT_APPLIED, {})
        )
    if style is not None and retained_style is None and trigger.strip():
        operations.append(AdaptationOperation(OP_STYLE_TRIGGER_DROPPED, SCOPE_STYLE, EFFECT_DROPPED, {}))
    return tuple(retained), retained_style, trigger if retained_style is not None else ""


# -- entry point ------------------------------------------------------------------------------------------------------


def adapt_prompt_for_target(
    policy: ModelPolicy,
    source: PromptAdaptationInput,
    *,
    lora_resolver: LoraResolver | None = None,
) -> PromptAdaptationPlan:
    """Project ``source`` onto ``policy``. Pure and deterministic; ``source`` is never modified.

    ``lora_resolver`` is the existing cache-only exact-admission evidence (it is only consulted for a policy that
    requires exact admission, and it must never scan, hash or reach the network).
    """

    identity: dict[str, Any] = {
        "ruleset_version": ADAPTATION_RULESET_VERSION,
        "policy_id": policy.policy_id,
        "family": policy.family,
        "evidence": policy.evidence,
        "profile_ref": policy.profile_ref,
        "prompt_dialect": policy.prompt_dialect,
    }
    if target_is_unverified(policy):
        return PromptAdaptationPlan(
            **identity,
            adaptable=False,
            changed=False,
            reason=OP_TARGET_UNVERIFIED,
            positive_text=source.positive_text,
            negative_text=source.negative_text,
            positive_embeddings=source.positive_embeddings,
            negative_embeddings=source.negative_embeddings,
            loras=source.loras,
            style_lora=source.style_lora,
            style_trigger_phrase=source.style_trigger_phrase,
            operations=(AdaptationOperation(OP_TARGET_UNVERIFIED, SCOPE_TARGET, EFFECT_REFUSED, {}),),
        )

    operations: list[AdaptationOperation] = []
    natural_language = policy.prompt_dialect == DIALECT_NATURAL_LANGUAGE

    positive = _adapt_text(source.positive_text, SCOPE_POSITIVE, operations) if natural_language else source.positive_text

    negative_unsupported = policy.feature("negative_prompt").support is Support.UNSUPPORTED
    if negative_unsupported:
        negative = ""
        if source.negative_text.strip():
            operations.append(AdaptationOperation(OP_NEGATIVE_DROPPED, SCOPE_NEGATIVE, EFFECT_DROPPED, {}))
    elif natural_language:
        negative = _adapt_text(source.negative_text, SCOPE_NEGATIVE, operations)
    else:
        negative = source.negative_text

    positive_embeddings, negative_embeddings = source.positive_embeddings, source.negative_embeddings
    if policy.feature("embeddings").support is Support.UNSUPPORTED:
        if positive_embeddings:
            operations.append(
                AdaptationOperation(
                    OP_POSITIVE_EMBEDDING_DROPPED, SCOPE_EMBEDDINGS, EFFECT_DROPPED, {"count": len(positive_embeddings)}
                )
            )
        if negative_embeddings:
            operations.append(
                AdaptationOperation(
                    OP_NEGATIVE_EMBEDDING_DROPPED, SCOPE_EMBEDDINGS, EFFECT_DROPPED, {"count": len(negative_embeddings)}
                )
            )
        positive_embeddings, negative_embeddings = (), ()

    loras, style_lora, style_trigger = _project_loras(policy, source, lora_resolver, operations)

    if source.optimizer_enabled and policy.feature("prompt_optimizer").support is Support.UNSUPPORTED:
        operations.append(AdaptationOperation(OP_OPTIMIZER_NOT_APPLIED, SCOPE_OPTIMIZER, EFFECT_NOT_APPLIED, {}))
    if negative_unsupported and source.global_negative_present:
        operations.append(AdaptationOperation(OP_GLOBAL_NEGATIVE_NOT_APPLIED, SCOPE_NEGATIVE, EFFECT_NOT_APPLIED, {}))

    changed = (
        positive != source.positive_text
        or negative != source.negative_text
        or positive_embeddings != source.positive_embeddings
        or negative_embeddings != source.negative_embeddings
        or loras != source.loras
        or style_lora != source.style_lora
        or style_trigger != source.style_trigger_phrase
    )
    return PromptAdaptationPlan(
        **identity,
        adaptable=True,
        changed=changed,
        reason="",
        positive_text=positive,
        negative_text=negative,
        positive_embeddings=positive_embeddings,
        negative_embeddings=negative_embeddings,
        loras=loras,
        style_lora=style_lora,
        style_trigger_phrase=style_trigger,
        operations=tuple(operations),
    )


__all__ = [
    "ADAPTATION_RULESET_VERSION",
    "BREAK_REPLACEMENT",
    "AdaptationOperation",
    "PromptAdaptationInput",
    "PromptAdaptationPlan",
    "adapt_prompt_for_target",
]
