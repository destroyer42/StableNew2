"""Explicit, deterministic, policy-driven prompt adaptation (PR-IMG-130C).

One pure answer to "how would this authored prompt material be adapted for that exact model target?". It consumes the
canonical ``ModelPolicy`` (PR-IMG-130A) and the existing exact LoRA admission (``assess_lora_selection`` over an injected
resolver, PR-IMG-117) and returns an immutable, versioned ``PromptAdaptationPlan``. It reproduces none of those rules and
contains no family, model-name or Klein conditional: a synthetic future policy adapts correctly.

Authored versus projected: the input is the operator's durable authoring material and is never modified; the plan is a
transient projection for one target. Nothing here touches a PromptPack, a workspace, a queue, a compiler or a runner; there
is no Tk, file, network, asset scan, hashing, model, LLM/VLM or process access. The Prompt tab previews the plan today; the
PromptPack compiler (PR-PROMPT-140) calls ``adapt_structured_prompt`` on structured intent components *before* executable
string rendering, so preview and execution share one rule implementation and cannot become two interpretation systems.
The compile entry point is *compile-safe*: only definitive policy facts and definitive ``incompatible`` LoRA evidence delete
an authored component; absent, stale, unverified or conflicting evidence preserves it (the plan is then marked incomplete and
the backend's fail-closed admission stays final).

Deterministic compatibility adaptation only: explicit A1111 weighted-attention syntax is flattened, an upper-case ``BREAK``
becomes a paragraph boundary, and channels/assets the target does not support are omitted from the projection. There is no
semantic strength inference, no negative-to-positive inversion, no quality-tag rewriting and no prompt enhancement. Plans
carry stable operation codes and structured details (counts, indices, limits), never prompt text or asset names, so they are
safe to log and to freeze later into experiment evidence.

Trigger ownership: actor and Style Consistency trigger phrases are structurally paired with their LoRA and are dropped with
it. A PromptPack-row LoRA has no authoritative trigger metadata, so no authored prose is ever guessed or deleted for it.
``<lora:...>`` tokens and ``[[matrix]]`` markers typed into authored text are left exactly as written.
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
ADAPTATION_RULESET_VERSION = "140.1"

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
OP_LORA_DROPPED_INCOMPATIBLE = "lora_dropped_incompatible"
OP_LORA_RETAINED_UNVERIFIED = "lora_retained_unverified"
OP_LORA_RETAINED_CONFLICTING = "lora_retained_conflicting"
OP_STYLE_LORA_DROPPED_UNSUPPORTED = "style_lora_dropped_unsupported"
OP_STYLE_LORA_DROPPED_UNVERIFIED = "style_lora_dropped_unverified"
OP_STYLE_LORA_DROPPED_REJECTED = "style_lora_dropped_rejected"
OP_STYLE_LORA_DROPPED_OVER_LIMIT = "style_lora_dropped_over_limit"
OP_STYLE_LORA_RETAINED = "style_lora_retained_compatible"
OP_STYLE_LORA_DROPPED_INCOMPATIBLE = "style_lora_dropped_incompatible"
OP_STYLE_LORA_RETAINED_UNVERIFIED = "style_lora_retained_unverified"
OP_STYLE_LORA_RETAINED_CONFLICTING = "style_lora_retained_conflicting"
OP_STYLE_LORA_NOT_EVALUATED = "style_lora_not_evaluated"
OP_STYLE_TRIGGER_DROPPED = "style_trigger_dropped_with_lora"
OP_ACTOR_TRIGGER_DROPPED = "actor_trigger_dropped_with_lora"
OP_PACK_TRIGGER_UNOWNED = "pack_lora_trigger_not_tracked"
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

MODE_PREVIEW = "preview"
MODE_COMPILE = "compile"

KIND_SLOT = "slot"
KIND_ACTOR = "actor"
KIND_PACK = "pack"
KIND_STYLE = "style"

STATUS_COMPATIBLE = "compatible"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_CONFLICTING = "conflicting"

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
    mode: str = MODE_PREVIEW
    #: ``False`` when a contribution could not be decided from definitive evidence (it was preserved, never guessed away)
    #: or when the target itself lacks capability evidence. A preview plan is complete whenever it is adaptable.
    complete: bool = True

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
            "mode": self.mode,
            "adaptable": self.adaptable,
            "complete": self.complete,
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


def _adapt_texts(texts: tuple[str, ...], scope: str, operations: list[AdaptationOperation]) -> tuple[str, ...]:
    """Apply the dialect rules to each prose component on its own; one summed operation per rule (never per component)."""

    flattened = normalized = 0
    adapted: list[str] = []
    for text in texts:
        text, count = _flatten_weighted_attention(text)
        flattened += count
        text, count = _normalize_break(text)
        normalized += count
        adapted.append(text)
    if flattened:
        operations.append(AdaptationOperation(OP_WEIGHTED_FLATTENED, scope, EFFECT_REWRITTEN, {"count": flattened}))
    if normalized:
        operations.append(AdaptationOperation(OP_BREAK_NORMALIZED, scope, EFFECT_REWRITTEN, {"count": normalized}))
    return tuple(adapted)


def _adapt_text(text: str, scope: str, operations: list[AdaptationOperation]) -> str:
    return _adapt_texts((text,), scope, operations)[0]


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


# -- compile-safe structured entry point (PR-PROMPT-140) -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoraContribution:
    """One structured LoRA contribution in *execution order*: actor, then PromptPack row, then Style Consistency."""

    name: str
    weight: float
    kind: str


@dataclass(frozen=True, slots=True)
class TriggerContribution:
    """A structured trigger phrase and the LoRA(s) that own it (``owners`` empty: not LoRA-owned, always kept)."""

    text: str
    kind: str
    owners: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuredPromptInput:
    """Pre-render PromptPack intent: prose components keep their order and role; nothing is a rendered string yet."""

    #: Ordered positive prose components (Matrix already expanded).
    positive_prose: tuple[str, ...] = ()
    #: Ordered negative prose components (those that participate; a global negative that is not applied is absent).
    negative_prose: tuple[str, ...] = ()
    positive_embeddings: EmbeddingEntries = ()
    negative_embeddings: EmbeddingEntries = ()
    loras: tuple[LoraContribution, ...] = ()
    triggers: tuple[TriggerContribution, ...] = ()
    #: Source facts the target may make inapplicable (recorded as ``not_applied`` evidence, values never touched).
    optimizer_enabled: bool = False
    global_negative_present: bool = False


@dataclass(frozen=True, slots=True)
class StructuredAdaptation:
    """The adapted structured intent plus the versioned, content-free plan that explains it."""

    plan: PromptAdaptationPlan
    positive_prose: tuple[str, ...]
    negative_prose: tuple[str, ...]
    positive_embeddings: EmbeddingEntries
    negative_embeddings: EmbeddingEntries
    loras: tuple[LoraContribution, ...]
    triggers: tuple[TriggerContribution, ...]
    #: ``False`` when the target's policy omits the whole negative channel (nothing may be rendered into it).
    negative_channel: bool


def _lora_codes(kind: str) -> dict[str, str]:
    style = kind == KIND_STYLE
    return {
        "unsupported": OP_STYLE_LORA_DROPPED_UNSUPPORTED if style else OP_LORA_DROPPED_UNSUPPORTED,
        "incompatible": OP_STYLE_LORA_DROPPED_INCOMPATIBLE if style else OP_LORA_DROPPED_INCOMPATIBLE,
        "over_limit": OP_STYLE_LORA_DROPPED_OVER_LIMIT if style else OP_LORA_DROPPED_OVER_LIMIT,
        "retained": OP_STYLE_LORA_RETAINED if style else OP_LORA_RETAINED,
        "unverified": OP_STYLE_LORA_RETAINED_UNVERIFIED if style else OP_LORA_RETAINED_UNVERIFIED,
        "conflicting": OP_STYLE_LORA_RETAINED_CONFLICTING if style else OP_LORA_RETAINED_CONFLICTING,
    }


def _select_compile_loras(
    policy: ModelPolicy,
    loras: tuple[LoraContribution, ...],
    lora_resolver: LoraResolver | None,
    operations: list[AdaptationOperation],
) -> tuple[tuple[LoraContribution, ...], int]:
    """Compile-safe selection in the given (execution) order: ``(retained, uncertain_count)``.

    Deleted only on a definitive fact: the policy says LoRA is unsupported, the existing exact evidence says
    ``incompatible``, or a *compatible* LoRA exceeds the target's finite limit. ``unverified`` / ``conflicting`` / missing
    evidence is preserved (and consumes a slot) so the backend's fail-closed admission stays the final authority.
    """

    feature = policy.feature("lora", STAGE_TXT2IMG)
    if feature.support is Support.UNSUPPORTED:
        for position, lora in enumerate(loras):
            scope = SCOPE_STYLE if lora.kind == KIND_STYLE else SCOPE_LORA
            details = {"index": position, "kind": lora.kind}
            operations.append(AdaptationOperation(_lora_codes(lora.kind)["unsupported"], scope, EFFECT_DROPPED, details))
        return (), 0
    if feature.support is not Support.SUPPORTED:
        return loras, 0  # unverified LoRA support: no destructive guess

    retained: list[LoraContribution] = []
    uncertain = 0
    for position, lora in enumerate(loras):
        codes = _lora_codes(lora.kind)
        scope = SCOPE_STYLE if lora.kind == KIND_STYLE else SCOPE_LORA
        details: dict[str, Any] = {"index": position, "kind": lora.kind}
        assessment = assess_lora_selection(policy, [(lora.name, lora.weight)], lora_resolver)
        status = assessment.statuses.get(lora.name) if assessment.exact else STATUS_COMPATIBLE
        if status == STATUS_INCOMPATIBLE:
            operations.append(AdaptationOperation(codes["incompatible"], scope, EFFECT_DROPPED, details))
            continue
        if status != STATUS_COMPATIBLE:
            uncertain += 1
            code = codes["conflicting"] if status == STATUS_CONFLICTING else codes["unverified"]
            operations.append(
                AdaptationOperation(code, scope, EFFECT_RETAINED, {**details, "status": status or "unverified"})
            )
            retained.append(lora)
            continue
        if feature.limit is not None and len(retained) >= feature.limit:
            operations.append(
                AdaptationOperation(codes["over_limit"], scope, EFFECT_DROPPED, {**details, "limit": feature.limit})
            )
            continue
        if assessment.exact:
            operations.append(AdaptationOperation(codes["retained"], scope, EFFECT_RETAINED, details))
        retained.append(lora)
    return tuple(retained), uncertain


def adapt_structured_prompt(
    policy: ModelPolicy,
    source: StructuredPromptInput,
    *,
    lora_resolver: LoraResolver | None = None,
) -> StructuredAdaptation:
    """Compile-safe adaptation of structured PromptPack intent for ``policy``. Pure; ``source`` is never modified.

    Same rule set as :func:`adapt_prompt_for_target` (one implementation of every dialect, negative, embedding and LoRA
    rule), with the stricter compile contract described in the module docstring. Unverified targets are returned unchanged
    with ``target_unverified_no_adaptation``.
    """

    identity: dict[str, Any] = {
        "ruleset_version": ADAPTATION_RULESET_VERSION,
        "policy_id": policy.policy_id,
        "family": policy.family,
        "evidence": policy.evidence,
        "profile_ref": policy.profile_ref,
        "prompt_dialect": policy.prompt_dialect,
        "mode": MODE_COMPILE,
    }

    def build(
        *,
        adaptable: bool,
        complete: bool,
        reason: str,
        positive: tuple[str, ...],
        negative: tuple[str, ...],
        pos_emb: EmbeddingEntries,
        neg_emb: EmbeddingEntries,
        loras: tuple[LoraContribution, ...],
        triggers: tuple[TriggerContribution, ...],
        operations: list[AdaptationOperation],
        channel: bool,
    ) -> StructuredAdaptation:
        style = next((lora for lora in loras if lora.kind == KIND_STYLE), None)
        style_trigger = next((t.text for t in triggers if t.kind == KIND_STYLE), "")
        changed = (
            positive != source.positive_prose
            or negative != source.negative_prose
            or pos_emb != source.positive_embeddings
            or neg_emb != source.negative_embeddings
            or loras != source.loras
            or triggers != source.triggers
        )
        plan = PromptAdaptationPlan(
            **identity,
            adaptable=adaptable,
            complete=complete,
            changed=changed,
            reason=reason,
            positive_text=" ".join(part for part in positive if part),
            negative_text=", ".join(part for part in negative if part),
            positive_embeddings=pos_emb,
            negative_embeddings=neg_emb,
            loras=tuple((lora.name, lora.weight) for lora in loras if lora.kind != KIND_STYLE),
            style_lora=(style.name, style.weight) if style is not None else None,
            style_trigger_phrase=style_trigger if style is not None else "",
            operations=tuple(operations),
        )
        return StructuredAdaptation(plan, positive, negative, pos_emb, neg_emb, loras, triggers, channel)

    if target_is_unverified(policy):
        return build(
            adaptable=False,
            complete=False,
            reason=OP_TARGET_UNVERIFIED,
            positive=source.positive_prose,
            negative=source.negative_prose,
            pos_emb=source.positive_embeddings,
            neg_emb=source.negative_embeddings,
            loras=source.loras,
            triggers=source.triggers,
            channel=True,
            operations=[AdaptationOperation(OP_TARGET_UNVERIFIED, SCOPE_TARGET, EFFECT_REFUSED, {})],
        )

    operations: list[AdaptationOperation] = []
    natural_language = policy.prompt_dialect == DIALECT_NATURAL_LANGUAGE
    positive = (
        _adapt_texts(source.positive_prose, SCOPE_POSITIVE, operations) if natural_language else source.positive_prose
    )

    channel = policy.feature("negative_prompt").support is not Support.UNSUPPORTED
    if not channel:
        negative = tuple("" for _ in source.negative_prose)
        if any(text.strip() for text in source.negative_prose):
            operations.append(AdaptationOperation(OP_NEGATIVE_DROPPED, SCOPE_NEGATIVE, EFFECT_DROPPED, {}))
    elif natural_language:
        negative = _adapt_texts(source.negative_prose, SCOPE_NEGATIVE, operations)
    else:
        negative = source.negative_prose

    pos_emb, neg_emb = source.positive_embeddings, source.negative_embeddings
    if policy.feature("embeddings").support is Support.UNSUPPORTED:
        if pos_emb:
            operations.append(
                AdaptationOperation(OP_POSITIVE_EMBEDDING_DROPPED, SCOPE_EMBEDDINGS, EFFECT_DROPPED, {"count": len(pos_emb)})
            )
        if neg_emb:
            operations.append(
                AdaptationOperation(OP_NEGATIVE_EMBEDDING_DROPPED, SCOPE_EMBEDDINGS, EFFECT_DROPPED, {"count": len(neg_emb)})
            )
        pos_emb, neg_emb = (), ()
    if not channel:
        neg_emb = ()  # the whole channel is omitted: nothing may be rendered into it

    retained, uncertain = _select_compile_loras(policy, source.loras, lora_resolver, operations)
    kept = {lora.name.lower() for lora in retained}
    triggers: list[TriggerContribution] = []
    for position, trigger in enumerate(source.triggers):
        if not trigger.owners or any(owner.lower() in kept for owner in trigger.owners):
            triggers.append(trigger)
            continue
        is_style = trigger.kind == KIND_STYLE
        operations.append(
            AdaptationOperation(
                OP_STYLE_TRIGGER_DROPPED if is_style else OP_ACTOR_TRIGGER_DROPPED,
                SCOPE_STYLE if is_style else SCOPE_LORA,
                EFFECT_DROPPED,
                {"index": position},
            )
        )
    if any(lora.kind == KIND_PACK and lora not in retained for lora in source.loras):
        # Honest limitation: a PromptPack-row LoRA has no trigger metadata, so authored prose is never guessed or deleted.
        operations.append(AdaptationOperation(OP_PACK_TRIGGER_UNOWNED, SCOPE_LORA, EFFECT_NOT_APPLIED, {}))

    if source.optimizer_enabled and policy.feature("prompt_optimizer").support is Support.UNSUPPORTED:
        operations.append(AdaptationOperation(OP_OPTIMIZER_NOT_APPLIED, SCOPE_OPTIMIZER, EFFECT_NOT_APPLIED, {}))
    if not channel and source.global_negative_present:
        operations.append(AdaptationOperation(OP_GLOBAL_NEGATIVE_NOT_APPLIED, SCOPE_NEGATIVE, EFFECT_NOT_APPLIED, {}))
    return build(
        adaptable=True,
        complete=uncertain == 0,
        reason="",
        positive=positive,
        negative=negative,
        pos_emb=pos_emb,
        neg_emb=neg_emb,
        loras=retained,
        triggers=tuple(triggers),
        operations=operations,
        channel=channel,
    )


__all__ = [
    "ADAPTATION_RULESET_VERSION",
    "BREAK_REPLACEMENT",
    "AdaptationOperation",
    "PromptAdaptationInput",
    "LoraContribution",
    "PromptAdaptationPlan",
    "StructuredAdaptation",
    "StructuredPromptInput",
    "TriggerContribution",
    "adapt_structured_prompt",
    "adapt_prompt_for_target",
]
