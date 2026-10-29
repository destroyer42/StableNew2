"""Versioned, deterministic, size-bounded evidence summary for a future advisory caller.

This is data only. It is not a trust grant, invokes no AI, and exposes nothing beyond what is needed to explain
and rank the allowed actions: opaque identifiers, closed-vocabulary classifications and bounded numbers. Prompt
text, notes, image or file paths and absolute locations cannot be represented here: every string leaf must be a
short lowercase token, which ``validate_ai_summary`` enforces before a summary can leave this module.

A later AI answer must be revalidated against freshly derived evidence with ``resolve_ai_candidate``; an
identifier that is absent from the current set is refused as stale.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.learning.intelligence_contracts import (
    SOURCE_CLASSES,
    STATUSES,
    IntelligenceReport,
    NextAction,
    NextActionSet,
    StaleActionError,
    digest,
)

SCHEMA = "stablenew.learning-evidence-summary.v1"
MAX_BYTES = 12 * 1024
MAX_CANDIDATES = 12
MAX_GROUPS = 8
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.:\-]{0,63}$")
LIMITS = (
    "advisory_only",
    "no_confidence_probabilities",
    "revalidate_against_current_evidence",
    "operator_confirmation_required",
)


class UnsafeSummaryError(ValueError):
    """A value that is not a short opaque token or a finite number reached an AI-facing summary."""


def candidate_id(action: NextAction) -> str:
    """Opaque and tied to the evidence fingerprint: it changes whenever the evidence does."""
    return "cand-" + digest([action.context_fingerprint, action.kind, action.target_id, "ai"])[:16]


def _candidate(action: NextAction) -> dict[str, Any]:
    work = action.workload_map()
    return {
        "id": candidate_id(action),
        "kind": action.kind,
        "workflow": action.workflow,
        "eligibility": action.eligibility,
        "severity": action.severity,
        "relevance": action.relevance,
        "images_to_generate": work.get("images_to_generate"),
        "images_to_rate": work.get("images_to_rate"),
        "reasons": list(action.reason_codes),
        "addresses": action.addresses_code,
        "blocked": bool(action.blockers) or action.eligibility == "blocked",
        "confirmation_required": bool(action.confirmation),
    }


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9_.\-]+", "_", str(value).lower()).strip("_")[:48] or "none"


def build_ai_summary(report: IntelligenceReport) -> dict[str, Any]:
    """The bounded summary. Deterministic: identical evidence yields byte-identical JSON."""
    actions: NextActionSet = report.actions
    ordered = list(actions.actions)
    candidates = [_candidate(a) for a in ordered[:MAX_CANDIDATES]]
    kinds = Counter((f.source_class, f.status) for f in report.findings)
    evidence = {
        source: {status: kinds[(source, status)] for status in STATUSES if kinds[(source, status)]}
        for source in SOURCE_CLASSES
    }
    groups = [
        {
            "id": g.group_id,
            "setting": _slug(g.setting),
            "category": _slug(g.category),
            "verdict": g.verdict,
            "experiments": g.experiments,
            "ratings": g.ratings,
            "values": len(g.values),
            "margin": None if g.margin is None else round(g.margin, 2),
        }
        for g in report.preference.groups[:MAX_GROUPS]
    ]
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "context": actions.fingerprint[:24],
        "model": {
            "ref": report.model_ref,
            "family": _slug(report.family),
            "identity_verified": report.identity_verified,
        },
        "coverage": {_slug(k): _slug(v) for k, v in sorted(report.coverage.items())},
        "evidence": {k: v for k, v in evidence.items() if v},
        "preference": {
            "considered": report.preference.considered,
            "excluded": {_slug(k): v for k, v in report.preference.excluded},
            "groups": groups,
        },
        "candidates": candidates,
        "degraded": bool(report.problems),
        "truncated": len(ordered) > len(candidates) or len(report.preference.groups) > len(groups),
        "limits": list(LIMITS),
    }
    while len(json.dumps(summary, separators=(",", ":"))) > MAX_BYTES and summary["candidates"]:
        summary["candidates"].pop()
        summary["truncated"] = True
    validate_ai_summary(summary)
    return summary


def candidate_index(actions: NextActionSet) -> dict[str, str]:
    """Opaque candidate id -> action id, kept by the caller to map an AI answer back to an action."""
    return {candidate_id(a): a.action_id for a in actions.actions[:MAX_CANDIDATES]}


def resolve_ai_candidate(
    answer_id: str, issued: Mapping[str, str], current: NextActionSet
) -> NextAction:
    """An AI-chosen candidate is only a request: it must exist in both the issued and the current set."""
    action_id = issued.get(answer_id)
    if action_id is None:
        raise StaleActionError("The suggested candidate was not offered and is refused.")
    action = current.revalidate(action_id)
    if not action.executable:
        raise StaleActionError("The suggested candidate is not currently eligible.")
    return action


def validate_ai_summary(summary: object, *, _depth: int = 0) -> None:
    """Structural privacy guarantee: only short opaque tokens, booleans, null and finite numbers."""
    if _depth > 6:
        raise UnsafeSummaryError("Summary nesting exceeds the contract.")
    if isinstance(summary, Mapping):
        for key, value in summary.items():
            if not isinstance(key, str) or not _TOKEN.match(key):
                raise UnsafeSummaryError("Summary key is not an opaque token.")
            validate_ai_summary(value, _depth=_depth + 1)
    elif isinstance(summary, (list, tuple)):
        for item in summary:
            validate_ai_summary(item, _depth=_depth + 1)
    elif isinstance(summary, str):
        if not _TOKEN.match(summary):
            raise UnsafeSummaryError("Summary text is not an opaque token.")
    elif isinstance(summary, bool) or summary is None:
        return
    elif isinstance(summary, (int, float)):
        if isinstance(summary, float) and not math.isfinite(summary):
            raise UnsafeSummaryError("Summary number is not finite.")
    else:
        raise UnsafeSummaryError("Summary contains an unsupported value type.")
    if _depth == 0 and len(json.dumps(summary, separators=(",", ":"))) > MAX_BYTES:
        raise UnsafeSummaryError("Summary exceeds its size bound.")
