"""Pure, deterministic validation of model output. Failure is an outcome; nothing is ever repaired or sanitised.

The model's text is untrusted data. It becomes a :class:`AssistSuggestion` only if it is exactly one JSON object of the
frozen schema whose every choice comes from the closed lists the request supplied and whose protected tokens
(``<extra-network>`` and ``[[matrix]]`` markers, the same non-prose rule the deterministic adaptation engine uses) are the
same multiset as the authored text. An instruction hidden in the authored prompt cannot change that: the only way to a
SUGGESTION is through this module.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.ai_assist.contracts import (
    CHANGE_CODES,
    MAX_REFUSAL_REASON_CHARS,
    MAX_TEXT_CHARS,
    SUGGESTION_SCHEMA_ID,
    AssistRequest,
    AssistSuggestion,
    OutcomeCode,
    SuggestionKind,
)
from src.prompting.prompt_compatibility import NON_PROSE_PATTERN

_ALLOWED_KEYS = frozenset(
    {
        "schema",
        "status",
        "kind",
        "positive",
        "negative",
        "target",
        "workflow",
        "changes",
        "refusal_reason",
    }
)
#: A rewrite may not grow without bound relative to what the operator wrote.
_MAX_GROWTH_FACTOR = 4
_GROWTH_ALLOWANCE = 400

#: Conservative: only text that starts like a refusal. A miss becomes MALFORMED (counted), never a guessed refusal.
_REFUSAL_OPENERS = re.compile(
    r"^\W*(?:i\s+(?:can(?:no|['’])t|cannot|won['’]t|will\s+not|am\s+(?:unable|not\s+able)"
    r"|['’]m\s+(?:unable|not\s+able))"
    r"|sorry,?\s+(?:but\s+)?i\s+(?:can(?:no|['’])t|cannot|won['’]t)"
    r"|i\s+apologi[sz]e,?\s+but"
    r"|(?:this|that)\s+(?:request\s+)?(?:violates|goes\s+against)\s+"
    r"|as\s+an\s+ai\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """``code`` is SUGGESTION exactly when ``suggestion`` is set; ``reason`` is a stable machine-readable string."""

    code: OutcomeCode
    reason: str = ""
    suggestion: AssistSuggestion | None = None


def looks_like_refusal(text: str) -> bool:
    """Whether non-schema model text opens like a refusal (first 240 characters only)."""

    return bool(_REFUSAL_OPENERS.match((text or "").strip()[:240]))


def protected_tokens(text: str) -> Counter[str]:
    """The multiset of protected tokens in ``text`` (same rule as the deterministic adaptation engine)."""

    return Counter(match.group(0) for match in NON_PROSE_PATTERN.finditer(text or ""))


def _malformed(reason: str) -> ValidationResult:
    return ValidationResult(OutcomeCode.MALFORMED, reason)


def _has_control_characters(text: str) -> bool:
    return any(
        unicodedata.category(char) in {"Cc", "Cs", "Co", "Cn"} and char not in "\n\t"
        for char in text
    )


def _text_field(value: Any, label: str, *, limit: int) -> tuple[str | None, str]:
    if value is None:
        return None, ""
    if not isinstance(value, str):
        return None, f"{label}_not_text"
    if len(value) > limit:
        return None, f"{label}_too_long"
    if _has_control_characters(value):
        return None, f"{label}_control_characters"
    return value, ""


def validate_output(raw: bytes | str, request: AssistRequest) -> ValidationResult:
    """Classify the model's complete stdout for ``request``."""

    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        return _malformed("not_utf8")
    stripped = text.strip()
    if not stripped:
        return _malformed("empty_output")
    try:
        document = json.loads(stripped)
    except (ValueError, RecursionError):
        if looks_like_refusal(stripped):
            return ValidationResult(OutcomeCode.REFUSED_BY_MODEL, "refusal_text")
        return _malformed("not_json")
    if not isinstance(document, dict):
        return _malformed("not_an_object")
    unknown = set(document) - _ALLOWED_KEYS
    if unknown:
        return _malformed("unknown_fields")
    if document.get("schema") != SUGGESTION_SCHEMA_ID:
        return _malformed("wrong_schema")

    status = document.get("status")
    if status == "refused":
        reason, problem = _text_field(
            document.get("refusal_reason"), "refusal_reason", limit=MAX_REFUSAL_REASON_CHARS
        )
        if problem:
            return _malformed(problem)
        return ValidationResult(OutcomeCode.REFUSED_BY_MODEL, "status_refused")
    if status != "ok":
        return _malformed("unknown_status")
    if document.get("kind") != request.kind.value:
        return _malformed("kind_mismatch")

    changes = document.get("changes", [])
    if not isinstance(changes, list) or len(changes) > len(CHANGE_CODES):
        return _malformed("changes_invalid")
    if not all(isinstance(code, str) and code in CHANGE_CODES for code in changes):
        return _malformed("change_code_not_allowed")

    positive, problem = _text_field(document.get("positive"), "positive", limit=MAX_TEXT_CHARS)
    if problem:
        return _malformed(problem)
    negative, problem = _text_field(document.get("negative"), "negative", limit=MAX_TEXT_CHARS)
    if problem:
        return _malformed(problem)
    target = document.get("target")
    workflow = document.get("workflow")

    if request.kind is SuggestionKind.PROMPT_REWRITE:
        if target is not None or workflow is not None:
            return _malformed("unexpected_choice_field")
        if positive is None or not positive.strip():
            return _malformed("positive_missing")
        negative = negative if negative is not None else ""
        ceiling = _MAX_GROWTH_FACTOR * len(request.positive_text) + _GROWTH_ALLOWANCE
        if len(positive) > ceiling:
            return _malformed("positive_grew_too_much")
        if len(negative) > _MAX_GROWTH_FACTOR * len(request.negative_text) + _GROWTH_ALLOWANCE:
            return _malformed("negative_grew_too_much")
        if protected_tokens(request.positive_text) + protected_tokens(
            request.negative_text
        ) != protected_tokens(positive) + protected_tokens(negative):
            return _malformed("protected_tokens_changed")
    elif request.kind is SuggestionKind.TARGET_FIT_ADVICE:
        if positive is not None or negative is not None or workflow is not None:
            return _malformed("unexpected_text_field")
        if not isinstance(target, str) or target not in request.allowed_targets:
            return _malformed("target_not_in_closed_list")
    else:
        if positive is not None or negative is not None or target is not None:
            return _malformed("unexpected_text_field")
        if not isinstance(workflow, str) or workflow not in request.allowed_workflows:
            return _malformed("workflow_not_in_closed_list")

    suggestion = AssistSuggestion(
        schema=SUGGESTION_SCHEMA_ID,
        kind=request.kind,
        request_id=request.request_id,
        positive_text=positive if request.kind is SuggestionKind.PROMPT_REWRITE else None,
        negative_text=negative if request.kind is SuggestionKind.PROMPT_REWRITE else None,
        target=target if request.kind is SuggestionKind.TARGET_FIT_ADVICE else None,
        workflow=workflow if request.kind is SuggestionKind.WORKFLOW_CHOICE else None,
        changes=tuple(changes),
    )
    return ValidationResult(OutcomeCode.SUGGESTION, "", suggestion)


__all__ = ["ValidationResult", "looks_like_refusal", "protected_tokens", "validate_output"]
