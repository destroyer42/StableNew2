"""Small qualification review presenter over the existing rating/draft writer.

The pair is a navigation unit only. Each save remains one ordinary image rating.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.learning.qualification_review import QualificationPair, valid_rating
from src.learning.rating_schema import blend_rating


class QualificationReviewSession:
    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.experiment = controller.learning_state.current_experiment
        self.closed = False

    @property
    def live(self) -> bool:
        return (
            not self.closed and self.controller.learning_state.current_experiment is self.experiment
        )

    def payload(self, ref: str) -> tuple[dict[str, Any], str]:
        if not self.live:
            return {}, "Unavailable — experiment switched"
        saved = self.controller.get_rating_details_for_image(ref)
        draft = self.controller.get_review_draft(ref)
        if draft is not None:
            return dict(draft), "Unsaved draft" + (
                f" (saved: {saved['overall_rating']}/5)" if saved else ""
            )
        if saved:
            return dict(saved), f"Saved: {saved['overall_rating']}/5"
        return {}, "Unrated"

    def stage(self, ref: str, payload: dict[str, Any]) -> None:
        if self.live:
            saved = self.controller.get_rating_details_for_image(ref) or {}
            if self._equal(saved, payload):
                if self.controller.get_review_draft(ref) is not None:
                    self.controller.discard_review_draft(ref)
                return
            if payload.get("overall_rating") or payload.get("notes") or payload.get("subscores"):
                self.controller.save_review_draft(ref, {**payload, "dirty": True})

    @staticmethod
    def _equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
        a_flags, b_flags = a.get("context_flags") or {}, b.get("context_flags") or {}
        if any(bool(a_flags.get(k)) != bool(b_flags.get(k)) for k in set(a_flags) | set(b_flags)):
            return False
        return all(
            a.get(k, default) == b.get(k, default)
            for k, default in (
                ("overall_rating", 0),
                ("notes", ""),
                ("subscores", {}),
            )
        )

    def save(
        self, ref: str, payload: dict[str, Any], confirm: Callable[[str], bool]
    ) -> tuple[bool, str]:
        if not self.live:
            return False, "Experiment switched or closed; reopen its review."
        self.stage(ref, payload)
        rating = valid_rating(payload.get("overall_rating"))
        if rating is None:
            return False, "Choose an overall rating from 1 to 5. Draft retained."
        saved = self.controller.get_rating_details_for_image(ref)
        if saved and self._equal(saved, payload):
            self.controller.discard_review_draft(ref)
            return True, "Already saved — no change."
        if saved and not confirm(ref):
            return False, "Override cancelled; draft retained."
        try:
            self.controller.record_rating(
                ref,
                rating,
                str(payload.get("notes") or ""),
                {
                    "context_flags": dict(payload.get("context_flags") or {}),
                    "subscores": dict(payload.get("subscores") or {}),
                    "blended_rating": blend_rating(rating, payload.get("subscores") or {}),
                },
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return False, f"Not saved: {exc}. Draft retained."
        return True, "Saved successfully."

    def remember(self, pair: QualificationPair) -> None:
        if self.live:
            self.experiment.metadata["qualification_review_position"] = list(pair.identity)
            self.controller._notify_resume_state_changed()

    def position(self, pairs: tuple[QualificationPair, ...]) -> int:
        identity = tuple(self.experiment.metadata.get("qualification_review_position") or ())
        return next((i for i, p in enumerate(pairs) if p.identity == identity), 0)
