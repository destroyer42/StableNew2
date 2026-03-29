from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.gui.content_visibility import ContentVisibilityMode, normalize_content_visibility_mode

CONTENT_VISIBILITY_SCHEMA = "stablenew.content-visibility.v1"
CONTENT_RATING_SFW = "sfw"
CONTENT_RATING_NSFW = "nsfw"
CONTENT_RATING_UNKNOWN = "unknown"
REDACTED_TEXT = "[Hidden in SFW mode]"

_EXPLICIT_TERMS = {
    "adult",
    "areola",
    "boob",
    "boobs",
    "breast",
    "breasts",
    "cum",
    "dick",
    "explicit",
    "genital",
    "genitals",
    "lingerie",
    "naked",
    "nsfw",
    "nude",
    "nudity",
    "penis",
    "porn",
    "pussy",
    "sex",
    "sexual",
    "topless",
    "vagina",
}
_EXPLICIT_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(re.escape(term) for term in _EXPLICIT_TERMS)) + r")\b",
    re.IGNORECASE,
)
_TEXT_KEYS = (
    "name",
    "label",
    "description",
    "prompt",
    "positive_prompt",
    "negative_prompt",
    "positive_preview",
    "negative_preview",
)
_TAG_KEYS = ("tags", "keywords", "content_tags", "visibility_tags", "capability_tags")
_NESTED_MAPPING_KEYS = ("extra_fields", "metadata", "result", "content_visibility")


def _normalize_rating(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {CONTENT_RATING_SFW, "safe", "safe_for_work"}:
        return CONTENT_RATING_SFW
    if text in {CONTENT_RATING_NSFW, "adult", "explicit", "unsafe"}:
        return CONTENT_RATING_NSFW
    return CONTENT_RATING_UNKNOWN


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _collect_candidate_mappings(item: Any) -> list[Mapping[str, Any]]:
    mappings: list[Mapping[str, Any]] = []
    if isinstance(item, Mapping):
        mappings.append(item)
        for key in _NESTED_MAPPING_KEYS:
            nested = item.get(key)
            if isinstance(nested, Mapping):
                mappings.append(nested)
    return mappings


def _read_value(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _collect_texts(item: Any) -> list[str]:
    if isinstance(item, str):
        return [item]
    texts: list[str] = []
    for key in _TEXT_KEYS:
        value = _read_value(item, key)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    for mapping in _collect_candidate_mappings(item):
        for key in _TEXT_KEYS:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
    return texts


def _collect_tags(item: Any) -> list[str]:
    tags: list[str] = []
    for key in _TAG_KEYS:
        value = _read_value(item, key)
        if isinstance(value, str):
            tags.extend(part.strip() for part in value.split(",") if part.strip())
        elif isinstance(value, Iterable):
            tags.extend(str(part).strip() for part in value if str(part).strip())
    for mapping in _collect_candidate_mappings(item):
        for key in _TAG_KEYS:
            value = mapping.get(key)
            if isinstance(value, str):
                tags.extend(part.strip() for part in value.split(",") if part.strip())
            elif isinstance(value, Iterable):
                tags.extend(str(part).strip() for part in value if str(part).strip())
    return tags


def _extract_payload(item: Any) -> Mapping[str, Any] | None:
    if isinstance(item, Mapping):
        payload = item.get("content_visibility")
        if isinstance(payload, Mapping):
            return payload
    extra_fields = _read_value(item, "extra_fields")
    if isinstance(extra_fields, Mapping):
        payload = extra_fields.get("content_visibility")
        if isinstance(payload, Mapping):
            return payload
    return None


def _extract_safe_flag(item: Any) -> bool | None:
    payload = _extract_payload(item)
    if isinstance(payload, Mapping):
        safe_flag = _coerce_optional_bool(payload.get("safe_for_work"))
        if safe_flag is not None:
            return safe_flag

    for key in ("safe_for_work", "nsfw", "explicit"):
        value = _read_value(item, key)
        if key == "safe_for_work":
            safe_flag = _coerce_optional_bool(value)
        else:
            explicit_flag = _coerce_optional_bool(value)
            safe_flag = None if explicit_flag is None else (not explicit_flag)
        if safe_flag is not None:
            return safe_flag
    for mapping in _collect_candidate_mappings(item):
        for key in ("safe_for_work", "nsfw", "explicit"):
            value = mapping.get(key)
            if key == "safe_for_work":
                safe_flag = _coerce_optional_bool(value)
            else:
                explicit_flag = _coerce_optional_bool(value)
                safe_flag = None if explicit_flag is None else (not explicit_flag)
            if safe_flag is not None:
                return safe_flag
    return None


def _matched_terms(texts: Iterable[str]) -> tuple[str, ...]:
    matches: set[str] = set()
    for text in texts:
        for match in _EXPLICIT_PATTERN.findall(str(text or "")):
            normalized = str(match).strip().lower()
            if normalized:
                matches.add(normalized)
    return tuple(sorted(matches))


@dataclass(frozen=True)
class ContentVisibilityClassification:
    rating: str = CONTENT_RATING_UNKNOWN
    matched_terms: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    source: str = "heuristic"
    safe_for_work: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": CONTENT_VISIBILITY_SCHEMA,
            "rating": _normalize_rating(self.rating),
            "matched_terms": list(self.matched_terms),
            "reason_codes": list(self.reason_codes),
            "source": self.source,
        }
        if self.safe_for_work is not None:
            payload["safe_for_work"] = self.safe_for_work
        return payload

    @classmethod
    def from_payload(cls, payload: Any) -> ContentVisibilityClassification:
        if not isinstance(payload, Mapping):
            return cls()
        rating = _normalize_rating(
            payload.get("rating")
            or payload.get("classification")
            or payload.get("content_rating")
        )
        safe_flag = _coerce_optional_bool(payload.get("safe_for_work"))
        if safe_flag is False and rating == CONTENT_RATING_UNKNOWN:
            rating = CONTENT_RATING_NSFW
        if safe_flag is True and rating == CONTENT_RATING_UNKNOWN:
            rating = CONTENT_RATING_SFW
        return cls(
            rating=rating,
            matched_terms=tuple(
                sorted(str(term).strip().lower() for term in payload.get("matched_terms") or [] if str(term).strip())
            ),
            reason_codes=tuple(
                str(code).strip() for code in payload.get("reason_codes") or [] if str(code).strip()
            ),
            source=str(payload.get("source") or "payload"),
            safe_for_work=safe_flag,
        )


@dataclass(frozen=True)
class ContentVisibilityDecision:
    mode: ContentVisibilityMode
    visible: bool
    redacted: bool
    classification: ContentVisibilityClassification


class ContentVisibilityResolver:
    """Shared visibility policy for SFW/NSFW collection and text surfaces."""

    def __init__(self, mode: str | ContentVisibilityMode = ContentVisibilityMode.NSFW) -> None:
        self.mode = normalize_content_visibility_mode(mode)

    def classify_item(self, item: Any) -> ContentVisibilityClassification:
        payload = _extract_payload(item)
        payload_classification = ContentVisibilityClassification.from_payload(payload)
        safe_flag = _extract_safe_flag(item)
        terms = _matched_terms([* _collect_texts(item), * _collect_tags(item)])

        if terms:
            return ContentVisibilityClassification(
                rating=CONTENT_RATING_NSFW,
                matched_terms=terms,
                reason_codes=("explicit_terms",),
                source="heuristic",
                safe_for_work=False,
            )
        if payload_classification.rating != CONTENT_RATING_UNKNOWN:
            return payload_classification
        if safe_flag is False:
            return ContentVisibilityClassification(
                rating=CONTENT_RATING_NSFW,
                reason_codes=("explicit_flag",),
                source="heuristic",
                safe_for_work=False,
            )
        if safe_flag is True:
            return ContentVisibilityClassification(
                rating=CONTENT_RATING_SFW,
                reason_codes=("safe_flag",),
                source="heuristic",
                safe_for_work=True,
            )
        return payload_classification

    def decide(self, item: Any, *, allow_redacted: bool = False) -> ContentVisibilityDecision:
        classification = self.classify_item(item)
        if self.mode == ContentVisibilityMode.NSFW:
            return ContentVisibilityDecision(
                mode=self.mode,
                visible=True,
                redacted=False,
                classification=classification,
            )
        if classification.rating == CONTENT_RATING_NSFW:
            return ContentVisibilityDecision(
                mode=self.mode,
                visible=allow_redacted,
                redacted=allow_redacted,
                classification=classification,
            )
        return ContentVisibilityDecision(
            mode=self.mode,
            visible=True,
            redacted=False,
            classification=classification,
        )

    def is_visible(self, item: Any) -> bool:
        return self.decide(item).visible

    def redact_text(self, text: str | None, *, item: Any = None) -> str:
        candidate = str(text or "")
        if not candidate.strip():
            return candidate
        decision = self.decide(item if item is not None else {"prompt": candidate}, allow_redacted=True)
        if decision.redacted:
            return REDACTED_TEXT
        return candidate

    def filter_collection(self, items: Iterable[Any]) -> list[Any]:
        return [item for item in items if self.is_visible(item)]


def build_content_visibility_payload(item: Any) -> dict[str, Any]:
    return ContentVisibilityResolver().classify_item(item).to_payload()


def normalize_content_visibility_payload(payload: Any) -> dict[str, Any]:
    return ContentVisibilityClassification.from_payload(payload).to_payload()


__all__ = [
    "CONTENT_RATING_NSFW",
    "CONTENT_RATING_SFW",
    "CONTENT_RATING_UNKNOWN",
    "CONTENT_VISIBILITY_SCHEMA",
    "REDACTED_TEXT",
    "ContentVisibilityClassification",
    "ContentVisibilityDecision",
    "ContentVisibilityResolver",
    "build_content_visibility_payload",
    "normalize_content_visibility_payload",
]
