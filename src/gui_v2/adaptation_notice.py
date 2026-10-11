"""Compact, content-free adaptation notice for the job Preview (PR-IMG-MODELS-159).

Toolkit-neutral and pure: it reads the frozen ``prompt_adaptation`` manifest (operation codes and counts, never prompt
text) of an already-compiled NJR and says in one short line what the compiler adapted or omitted for the target, so the
operator can see why the previewed prompt and settings differ from the authored ones. It decides nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_PHRASES = {
    "global_positive_composed": "global positive composed into the prompt",
    "global_positive_not_applied": "global positive disabled (not applied)",
    "negative_prompt_dropped_unsupported": "negative prompt omitted",
    "global_negative_not_applied": "global negative omitted",
    "optimizer_not_applied": "prompt optimizer off",
    "weighted_attention_flattened": "weighted syntax flattened",
    "break_separator_normalized": "BREAK normalized",
    "positive_embedding_dropped_unsupported": "embeddings omitted",
    "negative_embedding_dropped_unsupported": "embeddings omitted",
    "lora_dropped_unsupported": "LoRAs omitted",
}
#: Prompt channels the compiler cleared for the target (never their content), by the setting that carried them. The
#: global negative is deliberately absent: whether it was omitted by adaptation is stated by its own operation, so a
#: stored-but-disabled global negative is never described as omitted.
_CLEARED_PHRASES = {
    "negative_prompt": "negative prompt omitted",
}
_MAX_PHRASES = 5


def manifest_from_effective_configuration(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """Adapt the generic builder's ``effective_configuration/1`` evidence to the same operation vocabulary."""

    if not isinstance(evidence, Mapping):
        return {}
    operations: list[dict[str, Any]] = [
        {"code": "profile_value_normalized", "details": dict(change)}
        for change in evidence.get("normalized") or ()
        if isinstance(change, Mapping)
    ]
    operations.extend(
        dict(operation) for operation in evidence.get("operations") or () if isinstance(operation, Mapping)
    )
    status = str(evidence.get("global_positive") or "")
    if status == "composed":
        operations.append({"code": "global_positive_composed", "details": {}})
    elif status == "not_applied":
        operations.append({"code": "global_positive_not_applied", "details": {}})
    if str(evidence.get("global_negative") or "") == "omitted":
        operations.append({"code": "global_negative_not_applied", "details": {}})
    return {"operations": operations}


def compact_adaptation_notice(manifest: Mapping[str, Any] | None) -> str:
    """One short line for a ``prompt_adaptation`` manifest, or ``""`` when nothing was adapted."""

    if not isinstance(manifest, Mapping):
        return ""
    operations = manifest.get("operations")
    if not isinstance(operations, (list, tuple)):
        return ""
    phrases: list[str] = []
    settings: list[str] = []
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        code = str(operation.get("code") or "")
        if code == "profile_value_normalized":
            details = operation.get("details")
            details = details if isinstance(details, Mapping) else {}
            name = str(details.get("setting") or "")
            if details.get("cleared"):
                phrase = _CLEARED_PHRASES.get(name)
                if phrase and phrase not in phrases:
                    phrases.append(phrase)
            elif name and not name.startswith(("global_", "apply_global_")) and name != "prompt_optimizer":
                settings.append(name)
            continue
        phrase = _PHRASES.get(code)
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    if settings:
        phrases.append("profile values set: " + ", ".join(dict.fromkeys(settings)))
    if not phrases:
        return ""
    shown = phrases[:_MAX_PHRASES]
    extra = len(phrases) - len(shown)
    return "Adapted for target: " + "; ".join(shown) + (f"; +{extra} more" if extra else "")


__all__ = ["compact_adaptation_notice", "manifest_from_effective_configuration"]
