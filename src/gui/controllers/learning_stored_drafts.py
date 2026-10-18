"""Commit rated review drafts that are sitting in saved Learning sessions (every experiment but the open one).

Drafts are stored with their experiment's session. Those of the experiment open in the tab live in memory and are
committed by ``LearningController.commit_review_drafts``; rewriting that experiment's session from here would be
overwritten by the tab's next save, so it is skipped and reported.

Each rating is appended to the learning records through the same record builder a live Save Rating uses. A session
is rewritten (without the committed drafts) only after its ratings are stored, so an interruption leaves drafts that
a rerun finds already rated and keeps, never a second record.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.learning.draft_commit import DraftCommitSummary, DraftRating, commit_drafts
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_record import LearningRecord, LearningRecordWriter

BuildRecord = Callable[
    [Any, Any, str, int, str, "dict[str, Any] | None"], tuple[LearningRecord, Any, Any]
]


@dataclass(frozen=True)
class StoredDraftsReport:
    """What a pass over the saved sessions found (``apply=False``) or did (``apply=True``)."""

    experiments_with_drafts: int
    skipped_open_experiments: int
    unreadable_sessions: int
    summary: DraftCommitSummary
    applied: bool

    def describe(self) -> str:
        verb = "Saved" if self.applied else "Can save"
        lines = [
            f"{verb} {self.summary.committed} rated draft(s) across {self.experiments_with_drafts} saved experiment(s)."
        ]
        if self.summary.kept:
            lines.append(self.summary.describe())
        if self.skipped_open_experiments:
            lines.append(
                "The open experiment is skipped; use Save All Drafts in the review panel for it."
            )
        if self.unreadable_sessions:
            lines.append(
                f"{self.unreadable_sessions} session(s) could not be read and were left alone."
            )
        return "\n".join(lines)


def commit_stored_drafts(
    *,
    store: LearningExperimentStore,
    writer: LearningRecordWriter,
    build_record: BuildRecord,
    open_experiment_ids: Collection[str] = (),
    apply: bool,
) -> StoredDraftsReport:
    """Dry-run (``apply=False``) or commit the committable drafts of every saved experiment's session."""

    previous_last = store.get_last_experiment_id()
    total = DraftCommitSummary()
    with_drafts = skipped_open = unreadable = 0
    for handle in store.list_handles():
        payload = store.load_session(handle.experiment_id)
        if payload is None or not isinstance(payload.get("review_drafts") or {}, dict):
            unreadable += payload is None
            continue
        if not payload.get("review_drafts"):
            continue
        try:
            state = LearningState.from_dict(payload)
        except Exception:  # noqa: BLE001 - a malformed session is left exactly as it is
            unreadable += 1
            continue
        experiment = state.current_experiment
        if experiment is None:
            unreadable += 1
            continue
        if (
            handle.experiment_id in open_experiment_ids
            or experiment.experiment_id in open_experiment_ids
        ):
            skipped_open += 1
            continue
        rated = writer.get_ratings_for_experiment(experiment.experiment_id)
        plan = list(state.plan or [])

        def find_variant(ref: str, plan: list[LearningVariant] = plan) -> LearningVariant | None:
            return next((variant for variant in plan if ref in variant.image_refs), None)

        def commit(
            ref: str,
            variant: LearningVariant,
            rating: DraftRating,
            experiment: LearningExperiment = experiment,
        ) -> None:
            if not apply:
                return
            record, _flags, _subscores = build_record(
                experiment, variant, ref, rating.rating, rating.notes, rating.details
            )
            if writer.append_record(record) is False:
                raise OSError("the rating could not be written to the learning records file")

        def is_rated(ref: str, rated: dict[str, int] = rated) -> bool:
            return ref in rated

        remaining, summary = commit_drafts(
            state.review_drafts,
            experiment_id=experiment.experiment_id,
            find_variant=find_variant,
            is_rated=is_rated,
            commit=commit,
        )
        total += summary
        with_drafts += 1
        if apply and summary.committed:
            payload["review_drafts"] = remaining
            store.save_session(
                display_name=handle.display_name,
                payload=payload,
                experiment_id=handle.experiment_id,
            )
    if apply:
        store.set_last_experiment_id(previous_last)
    return StoredDraftsReport(
        experiments_with_drafts=with_drafts,
        skipped_open_experiments=skipped_open,
        unreadable_sessions=unreadable,
        summary=total,
        applied=apply,
    )


__all__ = ["StoredDraftsReport", "commit_stored_drafts"]
