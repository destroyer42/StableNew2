"""Turn rated review drafts into saved ratings, without ever overriding a rating that is already saved.

A draft is resumable UI state until it is committed. Only a draft with an overall rating can be committed, and only
for an image that has no saved rating: editing a saved rating stays an explicit Save Rating (which asks before
overriding). Anything not committed stays a draft, so nothing is lost.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.learning.rating_schema import blend_rating


@dataclass(frozen=True)
class DraftRating:
    """The arguments ``record_rating`` takes, recovered from a stored draft."""

    rating: int
    notes: str
    details: dict[str, Any]


@dataclass(frozen=True)
class DraftCommitSummary:
    committed: int = 0
    already_rated: int = 0
    unrated: int = 0
    orphaned: int = 0
    failed: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def kept(self) -> int:
        return self.already_rated + self.unrated + self.orphaned + self.failed

    def __add__(self, other: DraftCommitSummary) -> DraftCommitSummary:
        return DraftCommitSummary(
            committed=self.committed + other.committed,
            already_rated=self.already_rated + other.already_rated,
            unrated=self.unrated + other.unrated,
            orphaned=self.orphaned + other.orphaned,
            failed=self.failed + other.failed,
            errors=(*self.errors, *other.errors)[:20],
        )

    def describe(self) -> str:
        parts = [f"{self.committed} saved"]
        for count, reason in (
            (self.already_rated, "already rated (kept as drafts)"),
            (self.unrated, "without a rating (kept as drafts)"),
            (self.orphaned, "no longer in the plan (kept as drafts)"),
            (self.failed, "failed (kept as drafts)"),
        ):
            if count:
                parts.append(f"{count} {reason}")
        return "; ".join(parts) + "."


def parse_draft(draft: Mapping[str, Any]) -> DraftRating | None:
    """The rating a draft holds, or ``None`` when it has no overall rating to save."""

    try:
        rating = int(draft.get("overall_rating") or 0)
    except (TypeError, ValueError):
        return None
    if rating <= 0:
        return None
    subscores: dict[str, int] = {}
    for key, value in dict(draft.get("subscores") or {}).items():
        try:
            score = int(value or 0)
        except (TypeError, ValueError):
            continue
        if score > 0:
            subscores[str(key)] = score
    return DraftRating(
        rating=rating,
        notes=str(draft.get("notes") or ""),
        details={
            "context_flags": dict(draft.get("context_flags") or {}),
            "subscores": subscores,
            "blended_rating": blend_rating(rating, subscores),
        },
    )


def commit_drafts(
    drafts: Mapping[str, Mapping[str, Any]],
    *,
    experiment_id: str,
    find_variant: Callable[[str], Any | None],
    is_rated: Callable[[str], bool],
    commit: Callable[[str, Any, DraftRating], None],
) -> tuple[dict[str, dict[str, Any]], DraftCommitSummary]:
    """Commit the committable drafts of ``experiment_id``; return ``(remaining drafts, summary)``.

    Drafts of other experiments pass through untouched. ``commit`` must raise when the rating was not stored.
    """

    prefix = f"{experiment_id}:"
    remaining: dict[str, dict[str, Any]] = {}
    summary = DraftCommitSummary()
    for key, draft in drafts.items():
        if not key.startswith(prefix) or not isinstance(draft, Mapping):
            remaining[key] = dict(draft) if isinstance(draft, Mapping) else {}
            continue
        image_ref = key[len(prefix) :]
        parsed = parse_draft(draft)
        if parsed is None:
            summary += DraftCommitSummary(unrated=1)
        elif is_rated(image_ref):
            summary += DraftCommitSummary(already_rated=1)
        else:
            variant = find_variant(image_ref)
            if variant is None:
                summary += DraftCommitSummary(orphaned=1)
            else:
                try:
                    commit(image_ref, variant, parsed)
                except Exception as exc:  # noqa: BLE001 - kept as a draft and reported, never lost
                    summary += DraftCommitSummary(failed=1, errors=(f"{image_ref}: {exc}"[:200],))
                else:
                    summary += DraftCommitSummary(committed=1)
                    continue
        remaining[key] = dict(draft)
    return remaining, summary


__all__ = ["DraftCommitSummary", "DraftRating", "commit_drafts", "parse_draft"]
