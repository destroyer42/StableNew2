"""Toolkit-neutral preview model for the explicit Prompt-tab "Adapt for Target" action (PR-IMG-130C).

Pure (no Tk, no I/O). It only *describes* a ``PromptAdaptationPlan`` the pure adaptation engine already produced: every fact
(what changed, what was dropped, why) comes from the plan's stable operation codes, and every sentence here is presentation.
There is no second transformation anywhere in the GUI.

Content visibility: hidden positive/negative text is replaced by a placeholder, and asset identities (LoRA, embedding and
style names) are never shown at all in any mode (counts only), so a preview, its steps and its serialized plan cannot leak
hidden content. Nothing here reads or writes a PromptPack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.prompting import prompt_adaptation as pa

HIDDEN_PLACEHOLDER = "(hidden by the content-visibility mode)"

_NONE = "none"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _scope_word(scope: str) -> str:
    return {"positive": "positive", "negative": "negative"}.get(scope, scope)


def _describe(operation: pa.AdaptationOperation) -> str:
    code, scope, details = operation.code, operation.scope, operation.details
    count = details.get("count")
    index = details.get("index")
    limit = details.get("limit")
    ordinal = f"LoRA #{int(index) + 1}" if index is not None else "LoRA"
    table: dict[str, str] = {
        pa.OP_WEIGHTED_FLATTENED: f"Flattened {count} weighted-attention group(s) such as (phrase:1.2) to plain text in the {_scope_word(scope)} prompt.",
        pa.OP_BREAK_NORMALIZED: f"Replaced {count} BREAK separator(s) with a paragraph break in the {_scope_word(scope)} prompt.",
        pa.OP_NEGATIVE_DROPPED: "Omitted the negative prompt: this target does not support one.",
        pa.OP_POSITIVE_EMBEDDING_DROPPED: f"Omitted {count} positive embedding(s): this target does not support embeddings.",
        pa.OP_NEGATIVE_EMBEDDING_DROPPED: f"Omitted {count} negative embedding(s): this target does not support embeddings.",
        pa.OP_LORA_DROPPED_UNSUPPORTED: f"Omitted {ordinal}: this target does not support LoRAs.",
        pa.OP_LORA_DROPPED_UNVERIFIED: f"Omitted {ordinal}: it is not verified for this target.",
        pa.OP_LORA_DROPPED_REJECTED: f"Omitted {ordinal}: this target would reject it.",
        pa.OP_LORA_DROPPED_OVER_LIMIT: f"Omitted {ordinal}: this target admits at most {limit} (slot LoRAs first, then Style Consistency).",
        pa.OP_LORA_RETAINED: f"Kept {ordinal}: verified for this target.",
        pa.OP_STYLE_LORA_DROPPED_UNSUPPORTED: "Omitted the Style Consistency LoRA: this target does not support LoRAs.",
        pa.OP_STYLE_LORA_DROPPED_UNVERIFIED: (
            "Omitted the Style Consistency LoRA: its availability has not been evaluated yet (nothing is scanned here)."
            if details.get("reason") == "not_evaluated"
            else "Omitted the Style Consistency LoRA: it is not verified for this target."
        ),
        pa.OP_STYLE_LORA_DROPPED_REJECTED: "Omitted the Style Consistency LoRA: this target would reject it.",
        pa.OP_STYLE_LORA_DROPPED_OVER_LIMIT: f"Omitted the Style Consistency LoRA: this target admits at most {limit} LoRA(s) in total.",
        pa.OP_STYLE_LORA_RETAINED: "Kept the Style Consistency LoRA: verified for this target.",
        pa.OP_STYLE_LORA_NOT_EVALUATED: "The Style Consistency LoRA has not been evaluated yet, so it is not part of this preview.",
        pa.OP_STYLE_TRIGGER_DROPPED: "Omitted the Style Consistency trigger phrase together with its LoRA.",
        pa.OP_OPTIMIZER_NOT_APPLIED: "The Prompt Optimizer is enabled in your settings but is not applied for this target (setting unchanged).",
        pa.OP_GLOBAL_NEGATIVE_NOT_APPLIED: "The stored global negative is not applied for this target (setting unchanged).",
        pa.OP_TARGET_UNVERIFIED: "StableNew lacks sufficient capability evidence for this model, so nothing is adapted.",
    }
    return table.get(code, f"Applied adaptation step '{code}'.")


#: Operations whose existence or counts are derived from the prompt *text*: never itemized for hidden text.
_TEXT_DERIVED = {pa.OP_WEIGHTED_FLATTENED, pa.OP_BREAK_NORMALIZED, pa.OP_NEGATIVE_DROPPED}
_HIDDEN_STEP = "Some prompt text is hidden by the content-visibility mode, so text-level steps are not itemized."


def _text_hidden(operation: pa.AdaptationOperation, positive_hidden: bool, negative_hidden: bool) -> bool:
    if operation.code not in _TEXT_DERIVED:
        return False
    return positive_hidden if operation.scope == pa.SCOPE_POSITIVE else negative_hidden


@dataclass(frozen=True, slots=True)
class AdaptationPreviewModel:
    target_label: str
    adaptable: bool
    changed: bool
    summary: str
    original_positive: str
    adapted_positive: str
    original_negative: str
    adapted_negative: str
    embeddings: str
    loras: str
    #: One concise explanation per adaptation operation, in the plan's order.
    steps: tuple[str, ...]
    notes: tuple[str, ...]
    hidden_placeholder: str
    #: The content-free serialized plan (identity, ordered operations, counts) this preview describes.
    plan: dict[str, Any]


def build_adaptation_preview(
    plan: pa.PromptAdaptationPlan,
    source: pa.PromptAdaptationInput,
    *,
    target_label: str,
    positive_hidden: bool = False,
    negative_hidden: bool = False,
) -> AdaptationPreviewModel:
    if not plan.adaptable:
        summary = (
            f"{target_label}. No deterministic adaptation is available because StableNew lacks sufficient capability "
            "evidence for this model. Your prompt is unchanged. Your PromptPack is not changed."
        )
    elif plan.changed:
        summary = (
            f"{target_label}. This is how the current prompt would be adapted for this target. "
            "Your PromptPack is not changed."
        )
    else:
        summary = f"{target_label}. Adaptation would make no changes for this target. Your PromptPack is not changed."

    original_positive = HIDDEN_PLACEHOLDER if positive_hidden else (source.positive_text or "(empty)")
    adapted_positive = HIDDEN_PLACEHOLDER if positive_hidden else (plan.positive_text or "(empty)")

    authored_negative = bool(source.negative_text.strip())
    kept_negative = bool(plan.negative_text.strip())
    if negative_hidden:
        original_negative = adapted_negative = HIDDEN_PLACEHOLDER
    else:
        original_negative = "none" if not authored_negative else "present"
        if not authored_negative:
            adapted_negative = "none"
        elif kept_negative:
            adapted_negative = "kept"
        else:
            adapted_negative = "omitted — not supported by this target"

    src_pos, src_neg = len(source.positive_embeddings), len(source.negative_embeddings)
    out_pos, out_neg = len(plan.positive_embeddings), len(plan.negative_embeddings)
    if not (src_pos or src_neg):
        embeddings = _NONE
    else:
        verdict = "all retained" if (src_pos, src_neg) == (out_pos, out_neg) else "some dropped"
        embeddings = f"positive {src_pos} → {out_pos}, negative {src_neg} → {out_neg} ({verdict})"

    src_loras = len(source.loras) + (1 if source.style_lora is not None else 0)
    out_loras = len(plan.loras) + (1 if plan.style_lora is not None else 0)
    if not src_loras:
        loras = _NONE
    else:
        loras = f"{_count(src_loras, 'LoRA')} authored → {_count(out_loras, 'LoRA')} retained"
        if source.style_lora is not None:
            loras += " (including the Style Consistency LoRA in the count)"

    dropped_lora = any("lora" in operation.code and operation.effect == pa.EFFECT_DROPPED for operation in plan.operations)
    notes: list[str] = ["Preview only: automatic adaptation during generation is not enabled."]
    if dropped_lora:
        notes.append(
            "A trigger phrase typed into your prompt text for an omitted LoRA is not removed by this preview "
            "(only the Style Consistency trigger phrase is tracked with its LoRA)."
        )
    shown = [op for op in plan.operations if not _text_hidden(op, positive_hidden, negative_hidden)]
    suppressed = len(shown) != len(plan.operations)
    steps = tuple(_describe(operation) for operation in shown) + ((_HIDDEN_STEP,) if suppressed else ())
    diagnostics = plan.to_diagnostics()
    if suppressed or negative_hidden:
        diagnostics["operations"] = [operation.to_dict() for operation in shown]
        diagnostics["counts"]["negative_present"] = None if negative_hidden else diagnostics["counts"]["negative_present"]
    return AdaptationPreviewModel(
        target_label=target_label,
        adaptable=plan.adaptable,
        changed=plan.changed,
        summary=summary,
        original_positive=original_positive,
        adapted_positive=adapted_positive,
        original_negative=original_negative,
        adapted_negative=adapted_negative,
        embeddings=embeddings,
        loras=loras,
        steps=steps,
        notes=tuple(notes),
        hidden_placeholder=HIDDEN_PLACEHOLDER,
        plan=diagnostics,
    )


__all__ = ["HIDDEN_PLACEHOLDER", "AdaptationPreviewModel", "build_adaptation_preview"]
