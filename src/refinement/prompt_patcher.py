from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.prompting.prompt_splitter import detect_lora_syntax, detect_weight_syntax, split_prompt_chunks
from src.utils.embedding_prompt_utils import extract_embedding_entries


def _normalize_token(value: str) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _is_forbidden_patch_token(token: str) -> bool:
    candidate = str(token or "").strip()
    if not candidate:
        return False
    if candidate.lower().startswith("embedding:"):
        return True
    if detect_lora_syntax(candidate):
        return True
    if detect_weight_syntax(candidate):
        return True
    if extract_embedding_entries(candidate):
        return True
    if "<" in candidate and ">" in candidate:
        return True
    return False


def _coerce_patch_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    return []


def _join_chunks(chunks: list[str]) -> str:
    return ", ".join(chunk for chunk in chunks if str(chunk or "").strip())


@dataclass(frozen=True, slots=True)
class PromptPatchSideResult:
    original: str
    patched: str
    requested_add: list[str]
    requested_remove: list[str]
    applied_add: list[str]
    applied_remove: list[str]
    ignored_tokens: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "patched": self.patched,
            "requested_add": list(self.requested_add),
            "requested_remove": list(self.requested_remove),
            "applied_add": list(self.applied_add),
            "applied_remove": list(self.applied_remove),
            "ignored_tokens": list(self.ignored_tokens),
        }


@dataclass(frozen=True, slots=True)
class PromptPatchApplication:
    positive: PromptPatchSideResult
    negative: PromptPatchSideResult
    requested_patch: dict[str, list[str]]
    applied_patch: dict[str, list[str]]
    ignored_patch: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "positive": self.positive.to_dict(),
            "negative": self.negative.to_dict(),
            "requested_patch": {key: list(value) for key, value in self.requested_patch.items()},
            "applied_patch": {key: list(value) for key, value in self.applied_patch.items()},
            "ignored_patch": {key: list(value) for key, value in self.ignored_patch.items()},
        }

    @property
    def has_requested_patch(self) -> bool:
        return any(self.requested_patch.get(key) for key in self.requested_patch)


def _apply_prompt_side(
    base_prompt: str,
    *,
    add_tokens: list[str],
    remove_tokens: list[str],
) -> PromptPatchSideResult:
    original = str(base_prompt or "").strip()
    chunks = split_prompt_chunks(original)
    normalized_existing = {_normalize_token(chunk) for chunk in chunks}

    requested_add = [token for token in add_tokens if str(token or "").strip()]
    requested_remove = [token for token in remove_tokens if str(token or "").strip()]
    ignored_tokens: list[str] = []

    safe_add: list[str] = []
    for token in requested_add:
        if _is_forbidden_patch_token(token):
            ignored_tokens.append(token)
            continue
        safe_add.append(token.strip())

    safe_remove: list[str] = []
    for token in requested_remove:
        if _is_forbidden_patch_token(token):
            ignored_tokens.append(token)
            continue
        safe_remove.append(token.strip())

    remove_lookup = {_normalize_token(token) for token in safe_remove}
    applied_remove: list[str] = []
    kept_chunks: list[str] = []
    for chunk in chunks:
        normalized = _normalize_token(chunk)
        if normalized in remove_lookup:
            applied_remove.append(chunk)
            continue
        kept_chunks.append(chunk)

    applied_add: list[str] = []
    for token in safe_add:
        normalized = _normalize_token(token)
        if not normalized or normalized in normalized_existing or normalized in {
            _normalize_token(chunk) for chunk in kept_chunks
        }:
            continue
        kept_chunks.append(token)
        applied_add.append(token)

    return PromptPatchSideResult(
        original=original,
        patched=_join_chunks(kept_chunks),
        requested_add=requested_add,
        requested_remove=requested_remove,
        applied_add=applied_add,
        applied_remove=applied_remove,
        ignored_tokens=ignored_tokens,
    )


def apply_prompt_patch(
    positive_prompt: str,
    negative_prompt: str,
    patch_payload: dict[str, Any] | None,
) -> PromptPatchApplication:
    payload = dict(patch_payload or {})
    requested_patch = {
        "add_positive": _coerce_patch_list(payload.get("add_positive")),
        "remove_positive": _coerce_patch_list(payload.get("remove_positive")),
        "add_negative": _coerce_patch_list(payload.get("add_negative")),
        "remove_negative": _coerce_patch_list(payload.get("remove_negative")),
    }
    positive_result = _apply_prompt_side(
        positive_prompt,
        add_tokens=requested_patch["add_positive"],
        remove_tokens=requested_patch["remove_positive"],
    )
    negative_result = _apply_prompt_side(
        negative_prompt,
        add_tokens=requested_patch["add_negative"],
        remove_tokens=requested_patch["remove_negative"],
    )
    applied_patch = {
        "add_positive": list(positive_result.applied_add),
        "remove_positive": list(positive_result.applied_remove),
        "add_negative": list(negative_result.applied_add),
        "remove_negative": list(negative_result.applied_remove),
    }
    ignored_patch = {
        "positive": list(positive_result.ignored_tokens),
        "negative": list(negative_result.ignored_tokens),
    }
    return PromptPatchApplication(
        positive=positive_result,
        negative=negative_result,
        requested_patch=requested_patch,
        applied_patch=applied_patch,
        ignored_patch=ignored_patch,
    )


__all__ = ["PromptPatchApplication", "PromptPatchSideResult", "apply_prompt_patch"]
