"""Toolkit-neutral guide for the Designed Experiments workflow: Design, Preview, Run, Compare, Rate.

This is presentation state only. Every call derives the steps from the live experiment, plan and rating facts the
Learning subsystem already owns (snapshot, job associations, variant statuses, saved ratings and drafts); nothing
here is persisted, counts as an admission, or queues anything. Reaching a step never completes it: a step is
``completed`` only when the facts say so.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.learning.experiment_lifecycle import classify_experiment_lifecycle

STEP_DESIGN = "design"
STEP_PREVIEW = "preview"
STEP_RUN = "run"
STEP_COMPARE = "compare"
STEP_RATE = "rate"
STEP_ORDER: tuple[str, ...] = (STEP_DESIGN, STEP_PREVIEW, STEP_RUN, STEP_COMPARE, STEP_RATE)
STEP_LABELS: dict[str, str] = {
    STEP_DESIGN: "Design",
    STEP_PREVIEW: "Preview",
    STEP_RUN: "Run",
    STEP_COMPARE: "Compare",
    STEP_RATE: "Rate",
}
STEP_PURPOSE: dict[str, str] = {
    STEP_DESIGN: "Choose what to test",
    STEP_PREVIEW: "Check the frozen plan",
    STEP_RUN: "Send it to the queue",
    STEP_COMPARE: "Look at the results",
    STEP_RATE: "Rate what you see",
}

STATUS_COMPLETED = "completed"
STATUS_AVAILABLE = "available"
STATUS_WAITING = "waiting"
STATUS_ATTENTION = "attention"
STATUS_LOCKED = "locked"

ACTION_BUILD_PREVIEW = "build_preview"
ACTION_RUN = "run_experiment"
ACTION_VIEW_PROGRESS = "view_progress"
ACTION_REVIEW_RESULTS = "review_results"
ACTION_RATE = "rate_results"
ACTION_SAVE_NEXT = "save_and_next"
ACTION_RECOMMENDATIONS = "view_recommendations"
ACTION_NONE = "none"

TONE_NEUTRAL = "neutral"
TONE_INFO = "info"
TONE_SUCCESS = "success"
TONE_WARNING = "warning"
TONE_ERROR = "error"

_IN_FLIGHT = {"pending", "queued", "running"}
_FAILED = {"failed", "cancelled", "canceled"}


@dataclass(frozen=True)
class RatingProgress:
    """Where the review stands. ``drafts`` are unsaved: they are never counted as evidence."""

    saved: int = 0
    drafts: int = 0
    unrated: int = 0
    missing: int = 0
    awaiting: int = 0
    uncontrolled: int = 0

    @property
    def reviewable(self) -> int:
        """Completed results that exist and can be rated now."""
        return self.saved + self.drafts + self.unrated

    @property
    def to_rate(self) -> int:
        return self.drafts + self.unrated

    @property
    def review_complete(self) -> bool:
        return self.saved > 0 and self.to_rate == 0 and self.missing == 0 and self.awaiting == 0

    def describe(self) -> str:
        parts = [f"{self.saved} saved", f"{self.drafts} draft", f"{self.unrated} unrated"]
        if self.missing:
            parts.append(f"{self.missing} unavailable")
        if self.awaiting:
            parts.append(f"{self.awaiting} still generating")
        if self.uncontrolled:
            parts.append(f"{self.uncontrolled} uncontrolled")
        return " | ".join(parts)


def build_rating_progress(
    plan: Iterable[Any],
    *,
    is_saved: Callable[[str], bool],
    has_draft: Callable[[str], bool],
    exists: Callable[[str], bool] = lambda _ref: True,
) -> RatingProgress:
    """Count saved, draft, unrated, unavailable and not-yet-produced results of a plan.

    A saved rating is counted as saved even if its file has since gone missing; an unsaved result whose file is
    gone is ``missing`` and stays visible instead of being skipped silently.
    """
    saved = drafts = unrated = missing = awaiting = uncontrolled = 0
    for variant in plan:
        status = str(getattr(variant, "status", "") or "").lower()
        refs = [str(ref) for ref in list(getattr(variant, "image_refs", []) or [])]
        if status == "completed":
            for ref in refs:
                if is_saved(ref):
                    saved += 1
                elif not exists(ref):
                    missing += 1
                elif has_draft(ref):
                    drafts += 1
                else:
                    unrated += 1
        elif status == "uncontrolled":
            uncontrolled += len(refs)
        elif status in _IN_FLIGHT:
            awaiting += max(0, int(getattr(variant, "planned_images", 0) or 0))
    return RatingProgress(
        saved=saved,
        drafts=drafts,
        unrated=unrated,
        missing=missing,
        awaiting=awaiting,
        uncontrolled=uncontrolled,
    )


@dataclass(frozen=True)
class WorkflowFacts:
    """Everything the guide needs, read from existing state."""

    previewed: bool = False
    preview_stale: bool = False
    study_type: str = "controlled_variable"
    variants: int = 0
    admitted: int = 0
    unadmitted: int = 0
    in_flight: int = 0
    failed: int = 0
    uncontrolled_variants: int = 0
    attention: int = 0
    lifecycle: str = "Draft/Legacy Draft"
    rating: RatingProgress = RatingProgress()
    evidence_message: str = ""
    evidence_ready: bool = False
    design_blocker: str = ""

    @property
    def recommends(self) -> bool:
        """Only one-variable experiments produce parameter recommendations."""
        return self.study_type == "controlled_variable"

    @property
    def run_blocked_by_stale_preview(self) -> bool:
        return self.preview_stale and self.admitted == 0


def build_workflow_facts(
    experiment: Any | None,
    plan: Iterable[Any],
    *,
    rating: RatingProgress,
    preview_stale: bool = False,
    study_type: str = "controlled_variable",
    evidence_message: str = "",
    evidence_ready: bool = False,
    design_blocker: str = "",
) -> WorkflowFacts:
    """Fold the live experiment and plan into :class:`WorkflowFacts` (no I/O, no mutation)."""
    variants = list(plan or [])
    statuses = [str(getattr(v, "status", "") or "").lower() for v in variants]
    metadata = dict(getattr(experiment, "metadata", {}) or {})
    payload = {
        "plan": [
            {
                "job_id": getattr(v, "job_id", ""),
                "status": status,
                "completed_images": getattr(v, "completed_images", 0),
                "execution_metadata": dict(getattr(v, "execution_metadata", {}) or {}),
            }
            for v, status in zip(variants, statuses, strict=True)
        ],
        "current_experiment": {"metadata": metadata},
    }
    attention = sum(
        status == "requires_attention"
        or bool(
            (getattr(v, "execution_metadata", {}) or {}).get("action_required")
            or (getattr(v, "execution_metadata", {}) or {}).get("admission_error")
        )
        for v, status in zip(variants, statuses, strict=True)
    )
    if metadata.get("resume_persistence_error"):
        attention = max(attention, 1)
    admitted = sum(bool(str(getattr(v, "job_id", "") or "").strip()) for v in variants)
    return WorkflowFacts(
        previewed=bool(
            experiment is not None
            and getattr(experiment, "execution_snapshot_json", "")
            and variants
        ),
        preview_stale=bool(preview_stale),
        study_type=study_type,
        variants=len(variants),
        admitted=admitted,
        unadmitted=len(variants) - admitted,
        in_flight=sum(
            status in _IN_FLIGHT and bool(getattr(v, "job_id", ""))
            for v, status in zip(variants, statuses, strict=True)
        ),
        failed=sum(status in _FAILED for status in statuses),
        uncontrolled_variants=sum(status == "uncontrolled" for status in statuses),
        attention=attention,
        lifecycle=classify_experiment_lifecycle(payload, saved_rating_count=rating.saved),
        rating=rating,
        evidence_message=evidence_message,
        evidence_ready=evidence_ready,
        design_blocker=design_blocker,
    )


@dataclass(frozen=True)
class StepView:
    step: str
    label: str
    purpose: str
    status: str
    detail: str
    is_viewed: bool
    is_recommended: bool

    @property
    def navigable(self) -> bool:
        return self.status != STATUS_LOCKED


@dataclass(frozen=True)
class PrimaryAction:
    action: str
    label: str
    enabled: bool
    reason: str = ""


@dataclass(frozen=True)
class GuidedWorkflowProjection:
    steps: tuple[StepView, ...]
    recommended_step: str
    viewed_step: str
    headline: str
    primary: PrimaryAction
    status_label: str
    status_tone: str
    flags: tuple[str, ...]
    notices: tuple[str, ...]
    rating: RatingProgress

    def step(self, step_id: str) -> StepView:
        return next(item for item in self.steps if item.step == step_id)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _step_statuses(facts: WorkflowFacts) -> dict[str, tuple[str, str]]:
    rating = facts.rating
    out: dict[str, tuple[str, str]] = {}

    if facts.design_blocker and not facts.previewed:
        out[STEP_DESIGN] = (STATUS_ATTENTION, facts.design_blocker)
    elif facts.run_blocked_by_stale_preview:
        out[STEP_DESIGN] = (STATUS_ATTENTION, "Changed since the last Preview; build it again.")
    elif facts.previewed:
        out[STEP_DESIGN] = (STATUS_COMPLETED, "Design is frozen in a Preview.")
    else:
        out[STEP_DESIGN] = (STATUS_AVAILABLE, "Choose what to test, then build a Preview.")

    if not facts.previewed:
        out[STEP_PREVIEW] = (STATUS_LOCKED, "Build a Preview first.")
    elif facts.run_blocked_by_stale_preview:
        out[STEP_PREVIEW] = (STATUS_ATTENTION, "Out of date; this Preview cannot be run.")
    elif facts.admitted:
        out[STEP_PREVIEW] = (
            STATUS_COMPLETED,
            f"{_plural(facts.admitted, 'job')} sent to the queue.",
        )
    else:
        out[STEP_PREVIEW] = (STATUS_AVAILABLE, "Ready to run; nothing is queued yet.")

    if not facts.previewed or facts.run_blocked_by_stale_preview:
        out[STEP_RUN] = (STATUS_LOCKED, "Needs a current Preview.")
    elif not facts.admitted:
        out[STEP_RUN] = (STATUS_AVAILABLE, "Not sent yet.")
    elif facts.attention:
        out[STEP_RUN] = (STATUS_ATTENTION, f"{_plural(facts.attention, 'job')} need attention.")
    elif facts.unadmitted:
        out[STEP_RUN] = (STATUS_ATTENTION, f"{_plural(facts.unadmitted, 'variant')} not admitted.")
    elif facts.in_flight:
        out[STEP_RUN] = (
            STATUS_WAITING,
            f"{facts.in_flight} of {facts.variants} still queued or running.",
        )
    elif facts.failed:
        out[STEP_RUN] = (
            STATUS_ATTENTION,
            f"{_plural(facts.failed, 'variant')} failed or cancelled.",
        )
    else:
        out[STEP_RUN] = (STATUS_COMPLETED, "All variants finished.")

    results = rating.reviewable
    if results:
        if rating.review_complete:
            out[STEP_COMPARE] = (STATUS_COMPLETED, "Every result is rated.")
        else:
            out[STEP_COMPARE] = (
                STATUS_AVAILABLE,
                f"{_plural(results, 'result')} to look at (optional).",
            )
    elif facts.in_flight or rating.awaiting:
        out[STEP_COMPARE] = (STATUS_WAITING, "Waiting for the first results.")
    else:
        out[STEP_COMPARE] = (STATUS_LOCKED, "No results to compare yet.")

    if rating.missing and not rating.to_rate and rating.saved:
        out[STEP_RATE] = (STATUS_ATTENTION, f"{_plural(rating.missing, 'result')} unavailable.")
    elif rating.review_complete:
        out[STEP_RATE] = (STATUS_COMPLETED, f"{rating.saved} saved.")
    elif rating.to_rate:
        out[STEP_RATE] = (STATUS_AVAILABLE, f"{rating.to_rate} to rate.")
    elif rating.awaiting:
        out[STEP_RATE] = (STATUS_WAITING, "Waiting for results.")
    elif rating.missing:
        out[STEP_RATE] = (STATUS_ATTENTION, f"{_plural(rating.missing, 'result')} unavailable.")
    elif rating.uncontrolled:
        out[STEP_RATE] = (
            STATUS_ATTENTION,
            "Results are uncontrolled evidence and cannot be rated here.",
        )
    else:
        out[STEP_RATE] = (STATUS_LOCKED, "No results to rate yet.")
    return out


def _recommended_step(facts: WorkflowFacts) -> str:
    if not facts.previewed or facts.run_blocked_by_stale_preview:
        return STEP_DESIGN
    if not facts.admitted:
        return STEP_PREVIEW
    rating = facts.rating
    if facts.attention or facts.unadmitted or (facts.in_flight and not rating.reviewable):
        return STEP_RUN
    if rating.reviewable or rating.missing or rating.saved:
        return STEP_RATE if (rating.saved or rating.drafts) else STEP_COMPARE
    return STEP_RUN


def _status(facts: WorkflowFacts) -> tuple[str, str, tuple[str, ...]]:
    flags: list[str] = []
    if facts.rating.uncontrolled or facts.uncontrolled_variants:
        flags.append("Uncontrolled evidence")
    if facts.rating.missing:
        flags.append("Missing artifact")
    if not facts.previewed:
        return "Draft - not previewed", TONE_NEUTRAL, tuple(flags)
    if facts.run_blocked_by_stale_preview:
        return "Preview out of date", TONE_WARNING, tuple(flags)
    if not facts.admitted:
        return "Preview ready - not queued", TONE_INFO, tuple(flags)
    label = {
        "Requires Attention": "Requires attention",
        "Running": "Running",
        "Queued": "Queued",
        "Failed": "Failed",
        "Review Needed": "Review needed",
        "Complete": "Complete",
    }.get(facts.lifecycle, facts.lifecycle)
    tone = {
        "Requires attention": TONE_ERROR,
        "Failed": TONE_ERROR,
        "Running": TONE_INFO,
        "Queued": TONE_INFO,
        "Review needed": TONE_WARNING,
        "Complete": TONE_SUCCESS,
    }.get(label, TONE_NEUTRAL)
    if label == "Complete" and flags:
        label, tone = "Complete with issues", TONE_WARNING
    return label, tone, tuple(flags)


def _notices(facts: WorkflowFacts) -> tuple[str, ...]:
    notes: list[str] = []
    if facts.attention:
        notes.append(
            f"{_plural(facts.attention, 'job')} need attention. Nothing is retried automatically; "
            "see the Status detail column for the required action."
        )
    if facts.failed:
        notes.append(f"{_plural(facts.failed, 'variant')} failed or were cancelled.")
    if facts.rating.uncontrolled:
        notes.append(
            f"{_plural(facts.rating.uncontrolled, 'result')} could not be verified as controlled "
            "and never count toward recommendations."
        )
    if facts.rating.missing:
        notes.append(
            f"{_plural(facts.rating.missing, 'result')} could not be found on disk and remain unrated."
        )
    return tuple(notes)


def _headline(step: str, facts: WorkflowFacts) -> str:
    rating = facts.rating
    if step == STEP_DESIGN:
        if facts.design_blocker and not facts.previewed:
            return facts.design_blocker
        if facts.run_blocked_by_stale_preview:
            return "The design changed after Preview. Build Preview again before running."
        if facts.admitted:
            return (
                "This experiment is already queued. Building a new Preview starts a new experiment "
                "and leaves the queued one untouched."
            )
        return "Test several values of one setting while the other settings stay the same. Then build a Preview."
    if step == STEP_PREVIEW:
        if not facts.previewed:
            return "Nothing to preview yet. Design the experiment and build a Preview."
        if facts.run_blocked_by_stale_preview:
            return "This Preview no longer matches the design. Build it again; it cannot be run."
        if facts.admitted:
            return "This Preview has been sent to the queue. Open Run to follow it."
        return (
            f"Building the Preview queued nothing. Run Experiment sends {_plural(facts.variants, 'job')} "
            "to the queue in one step."
        )
    if step == STEP_RUN:
        if not facts.admitted:
            return (
                "Nothing has been sent to the queue yet."
                if facts.previewed
                else "Build a Preview first."
            )
        if facts.attention:
            return "Some jobs need attention. Nothing is retried automatically."
        if facts.in_flight:
            return f"{facts.in_flight} of {facts.variants} variants are queued or running. Results appear as they finish."
        if rating.reviewable:
            return "The run is finished. Review the results."
        return "No results are available yet."
    if step == STEP_COMPARE:
        if rating.reviewable:
            return (
                "Compare the results of different values side by side. Differences you see are not proof of "
                "cause. You can rate without comparing."
            )
        return "Results appear here once jobs finish."
    if not rating.reviewable and not rating.missing:
        return "Results appear here once jobs finish."
    if rating.to_rate:
        text = f"Rate {rating.to_rate} remaining result{'s' if rating.to_rate != 1 else ''}."
    else:
        text = "Every available result is rated."
    if facts.recommends and facts.evidence_message:
        text += " " + facts.evidence_message
    elif not facts.recommends:
        text += " These ratings are descriptive and never become recommendations."
    return text


def _primary(step: str, facts: WorkflowFacts) -> PrimaryAction:
    rating = facts.rating
    if step == STEP_DESIGN:
        return PrimaryAction(ACTION_BUILD_PREVIEW, "Build Preview", True)
    if step == STEP_PREVIEW:
        if facts.admitted:
            return PrimaryAction(ACTION_VIEW_PROGRESS, "View Progress", True)
        if not facts.previewed:
            return PrimaryAction(ACTION_RUN, "Run Experiment", False, "Build a Preview first.")
        if facts.run_blocked_by_stale_preview:
            return PrimaryAction(
                ACTION_RUN, "Run Experiment", False, "The design changed; build the Preview again."
            )
        return PrimaryAction(ACTION_RUN, "Run Experiment", True)
    if step == STEP_RUN:
        if rating.reviewable:
            return PrimaryAction(ACTION_REVIEW_RESULTS, "Review Results", True)
        if facts.admitted:
            return PrimaryAction(ACTION_VIEW_PROGRESS, "View Progress", True)
        return PrimaryAction(
            ACTION_RUN, "Run Experiment", False, "Nothing has been sent to the queue."
        )
    if step == STEP_COMPARE:
        return PrimaryAction(
            ACTION_RATE,
            "Rate Results",
            rating.reviewable > 0,
            "" if rating.reviewable else "No results to rate yet.",
        )
    if rating.to_rate:
        return PrimaryAction(ACTION_SAVE_NEXT, "Save & Next", True)
    if facts.recommends and rating.saved:
        return PrimaryAction(ACTION_RECOMMENDATIONS, "View Recommendations", True)
    return PrimaryAction(ACTION_NONE, "All results rated", False, "Nothing left to rate.")


def project_guided_workflow(
    facts: WorkflowFacts, viewed_step: str | None = None
) -> GuidedWorkflowProjection:
    """Project the guide. ``viewed_step`` is the page the operator is on; it defaults to the recommended one."""
    recommended = _recommended_step(facts)
    viewed = viewed_step if viewed_step in STEP_ORDER else recommended
    statuses = _step_statuses(facts)
    steps = tuple(
        StepView(
            step=step,
            label=STEP_LABELS[step],
            purpose=STEP_PURPOSE[step],
            status=statuses[step][0],
            detail=statuses[step][1],
            is_viewed=step == viewed,
            is_recommended=step == recommended,
        )
        for step in STEP_ORDER
    )
    label, tone, flags = _status(facts)
    return GuidedWorkflowProjection(
        steps=steps,
        recommended_step=recommended,
        viewed_step=viewed,
        headline=_headline(viewed, facts),
        primary=_primary(viewed, facts),
        status_label=label,
        status_tone=tone,
        flags=flags,
        notices=_notices(facts),
        rating=facts.rating,
    )


def study_type_of(experiment: Any | None) -> str:
    """The study type recorded in the experiment's metadata (ordinary experiments omit nothing)."""
    metadata: Mapping[str, Any] = getattr(experiment, "metadata", None) or {}
    return str(metadata.get("study_type") or "controlled_variable")


__all__ = [
    "ACTION_BUILD_PREVIEW",
    "ACTION_NONE",
    "ACTION_RATE",
    "ACTION_RECOMMENDATIONS",
    "ACTION_REVIEW_RESULTS",
    "ACTION_RUN",
    "ACTION_SAVE_NEXT",
    "ACTION_VIEW_PROGRESS",
    "GuidedWorkflowProjection",
    "PrimaryAction",
    "RatingProgress",
    "STATUS_ATTENTION",
    "STATUS_AVAILABLE",
    "STATUS_COMPLETED",
    "STATUS_LOCKED",
    "STATUS_WAITING",
    "STEP_COMPARE",
    "STEP_DESIGN",
    "STEP_LABELS",
    "STEP_ORDER",
    "STEP_PREVIEW",
    "STEP_RATE",
    "STEP_RUN",
    "StepView",
    "WorkflowFacts",
    "build_rating_progress",
    "build_workflow_facts",
    "project_guided_workflow",
    "study_type_of",
]
