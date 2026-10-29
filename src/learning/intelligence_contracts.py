"""Toolkit-neutral value types for the read-only Learning evidence intelligence projection.

Nothing here reads files, runs a backend or imports a GUI toolkit. Every type is a frozen value that can be
compared and hashed; ordinal ranking inputs are integers and are never presented as probabilities.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

CONTRACT = "learning_evidence_intelligence/1"

# Where a finding comes from. The four classes are never merged into one score.
SOURCE_POLICY = "policy_fact"
SOURCE_RESEARCH = "research_claim"
SOURCE_CONTROLLED = "controlled_observation"
SOURCE_PREFERENCE = "subjective_preference"
SOURCE_CLASSES = (SOURCE_POLICY, SOURCE_RESEARCH, SOURCE_CONTROLLED, SOURCE_PREFERENCE)

# What is currently known. "unknown" and "conflicting" are first-class and never rounded to a value.
STATUS_ESTABLISHED = "established"
STATUS_CLAIMED = "claimed"
STATUS_CONFLICTING = "conflicting"
STATUS_UNKNOWN = "unknown"
STATUS_OBSERVED = "observed"
STATUS_INSUFFICIENT = "insufficient"
STATUS_EXCLUDED = "excluded"
STATUSES = (
    STATUS_ESTABLISHED,
    STATUS_CLAIMED,
    STATUS_CONFLICTING,
    STATUS_UNKNOWN,
    STATUS_OBSERVED,
    STATUS_INSUFFICIENT,
    STATUS_EXCLUDED,
)

# Action kinds, in the documented class order used by the priority rule.
ACTION_COMPLETE_RATINGS = "complete_ratings"
ACTION_INVESTIGATE_EXECUTION = "investigate_execution"
ACTION_RESOLVE_IDENTITY = "resolve_identity"
ACTION_REVIEW_RECOMMENDATION = "review_recommendation"
ACTION_RUN_EXPERIMENT = "run_experiment"
ACTION_REPEAT_EXPERIMENT = "repeat_experiment"
ACTION_RESEARCH_EVIDENCE = "research_evidence"
ACTION_NO_SAFE_EXPERIMENT = "no_safe_experiment"
ACTION_KINDS = (
    ACTION_COMPLETE_RATINGS,
    ACTION_INVESTIGATE_EXECUTION,
    ACTION_RESOLVE_IDENTITY,
    ACTION_REVIEW_RECOMMENDATION,
    ACTION_RUN_EXPERIMENT,
    ACTION_REPEAT_EXPERIMENT,
    ACTION_RESEARCH_EVIDENCE,
    ACTION_NO_SAFE_EXPERIMENT,
)

# Existing operator workflows an action may point at. None of them is started by this projection.
WORKFLOW_PROPOSED_EXPERIMENTS = "proposed_experiments"
WORKFLOW_DRAFT_PREPARATION = "draft_preparation"
WORKFLOW_LEARNING_REVIEW = "learning_review"
WORKFLOW_RECOMMENDATION_APPLY = "recommendation_apply"
WORKFLOW_IDENTITY_VERIFICATION = "identity_verification"
WORKFLOW_CATALOG_RESEARCH = "catalog_research"
WORKFLOW_NONE = "none"

ELIGIBILITY_READY = "ready"  # an existing workflow can be opened now
ELIGIBILITY_OPERATOR = (
    "operator_task"  # needs an operator step outside generation (verify, research)
)
ELIGIBILITY_BLOCKED = "blocked"  # explanatory only; never executable

# Preference verdicts. There is deliberately no "learned" or "best" verdict.
VERDICT_INSUFFICIENT = "insufficient"
VERDICT_NO_CLEAR = "no_clear_preference"
VERDICT_COMPETING = "competing"
VERDICT_OBSERVED = "observed_preference"

MAX_IMAGE_COST = 24  # bounded generation cost for one suggested experiment
MAX_ALTERNATIVES = 3


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
        ).encode()
    ).hexdigest()


class StaleActionError(ValueError):
    """The evidence an action identifier was derived from has changed; refresh before acting."""


@dataclass(frozen=True)
class EvidenceFinding:
    """One statement with its provenance. Every field below the statement is mandatory context."""

    finding_id: str
    topic: str
    source_class: str
    status: str
    statement: str
    source_ref: str  # stable identity of the source (catalog record, policy id, experiment id, ...)
    applicability: str  # which model/context the statement is true for
    freshness: str  # revision token the statement was derived from
    limitation: str  # the named reason this must not be over-read

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ValueSummary:
    value: Any
    ratings: int
    mean: float
    low: float
    high: float
    subscore_means: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class PreferenceGroup:
    """Ratings that are genuinely comparable: one exact checkpoint, setting, prompt context and category."""

    group_id: str
    setting: str
    prompt_context: str  # opaque; the prompt text itself never leaves the rating's frozen snapshot
    category: str
    experiments: int
    ratings: int
    values: tuple[ValueSummary, ...]
    verdict: str
    leading_value: Any
    margin: float | None
    statement: str
    limitation: str
    insufficiency: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreferenceSummary:
    groups: tuple[PreferenceGroup, ...] = ()
    excluded: tuple[
        tuple[str, int], ...
    ] = ()  # (reason, count): evidence that was deliberately not pooled
    considered: int = 0
    limitation: str = (
        "Ratings describe the tested prompts and the exact checkpoint only. They are not a general "
        "claim about quality, other prompts or other models."
    )


@dataclass(frozen=True)
class NextAction:
    action_id: str
    kind: str
    target_id: str
    purpose: str
    reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]
    addresses: str  # the uncertainty this action reduces, in words
    addresses_code: str
    eligibility: str
    blockers: tuple[str, ...]
    workflow: str
    workload: tuple[tuple[str, int | None], ...]
    context_fingerprint: str
    confirmation: str  # the operator step that must still happen; empty means none is promised
    evidence_refs: tuple[str, ...] = ()
    severity: int = 1
    relevance: int = 1
    note: str = "No improvement is promised; the action asks a question."

    @property
    def executable(self) -> bool:
        return self.eligibility == ELIGIBILITY_READY

    def workload_map(self) -> dict[str, int | None]:
        return dict(self.workload)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["workload"] = self.workload_map()
        data["executable"] = self.executable
        return data


@dataclass(frozen=True)
class NextActionSet:
    fingerprint: str
    actions: tuple[NextAction, ...] = ()
    suppressed: tuple[
        tuple[str, str], ...
    ] = ()  # (target, reason): proposals not offered, e.g. duplicates
    problems: tuple[str, ...] = ()

    @property
    def primary(self) -> NextAction | None:
        return self.actions[0] if self.actions else None

    @property
    def alternatives(self) -> tuple[NextAction, ...]:
        return self.actions[1 : 1 + MAX_ALTERNATIVES]

    def find(self, action_id: str) -> NextAction | None:
        return next((a for a in self.actions if a.action_id == action_id), None)

    def revalidate(self, action_id: str) -> NextAction:
        """The identifier must exist in a set freshly derived from current evidence."""
        action = self.find(action_id)
        if action is None:
            raise StaleActionError(
                "This suggestion is out of date: model, catalog, policy, resources or ratings "
                "changed. Refresh What Should I Test Next?."
            )
        return action


@dataclass(frozen=True)
class ExperimentConclusion:
    experiment_id: str
    status: str  # "supported" | "inconclusive" | "insufficient"
    text: str
    limitation: str
    prompt_context: str = ""


@dataclass(frozen=True)
class IntelligenceReport:
    """Everything the surface needs: what is known, what is not, preferences, and the next actions."""

    model_ref: str
    display_name: str
    family: str
    identity_verified: bool
    findings: tuple[EvidenceFinding, ...]
    conclusions: tuple[ExperimentConclusion, ...]
    preference: PreferenceSummary
    actions: NextActionSet
    problems: tuple[str, ...] = ()
    fingerprint: str = ""
    coverage: Mapping[str, str] = field(default_factory=dict)

    def finding(self, finding_id: str) -> EvidenceFinding | None:
        return next((f for f in self.findings if f.finding_id == finding_id), None)
