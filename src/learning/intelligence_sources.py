"""Tolerant, read-only loaders for the evidence intelligence projection.

Corrupt, missing or oversized input degrades to explicit problems; it is never silently skipped and never
repaired. Nothing here writes, locks for write, or reconstructs historical evidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.experiment_execution import thaw_snapshot
from src.learning.experiment_store import LearningExperimentStore
from src.learning.intelligence_contracts import digest
from src.learning.learning_record import evidence_file_lock
from src.learning.model_capabilities import variable_name

RATING_KIND = "learning_experiment_rating"
MAX_LOG_BYTES = 256 * 1024 * 1024
MAX_EXPERIMENTS = 300

STATE_DRAFT = "draft"  # saved, never frozen at Preview
STATE_PREPARED = "prepared"  # frozen, nothing finished
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"


@dataclass(frozen=True)
class RatingLog:
    rows: tuple[Mapping[str, Any], ...] = ()
    problems: tuple[str, ...] = ()
    revision: str = ""


def rating_identity(row: Mapping[str, Any]) -> tuple[str, str, str] | None:
    meta = row.get("metadata") or {}
    ident = (meta.get("experiment_id"), meta.get("job_id"), meta.get("image_path"))
    if all(isinstance(item, str) and item for item in ident):
        return (str(ident[0]), str(ident[1]), str(ident[2]))
    return None


def valid_rating(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and 1.0 <= number <= 5.0 else None


def read_rating_log(path: Path | None) -> RatingLog:
    """Latest saved controlled-experiment rating per image. Other record kinds are not this projection's."""
    if path is None or not path.exists():
        return RatingLog(revision=digest(["no-rating-log"]))
    problems: list[str] = []
    latest: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    unidentified = damaged = 0
    try:
        if path.stat().st_size > MAX_LOG_BYTES:
            return RatingLog(
                problems=(
                    "Learning rating log is larger than the safe read limit; ratings were not read.",
                ),
                revision=digest(["oversized"]),
            )
        with evidence_file_lock(path), path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    damaged += 1
                    continue
                if not isinstance(row, dict) or not isinstance(row.get("metadata"), dict):
                    damaged += 1
                    continue
                if row["metadata"].get("record_kind") != RATING_KIND:
                    continue
                identity = rating_identity(row)
                if identity is None:
                    unidentified += 1
                    continue
                latest[identity] = row  # append order is the durable rating-replacement rule
    except (OSError, UnicodeDecodeError) as exc:
        return RatingLog(
            problems=(f"Learning rating log could not be read ({type(exc).__name__}).",),
            revision=digest(["unreadable"]),
        )
    if damaged:
        problems.append(f"{damaged} damaged rating log line(s) were ignored and are not evidence.")
    if unidentified:
        problems.append(
            f"{unidentified} saved rating(s) lack a durable image identity and were not used."
        )
    revision = digest(
        {
            "ratings": sorted(
                [*ident, (row.get("metadata") or {}).get("user_rating")]
                for ident, row in latest.items()
            ),
            "damaged": damaged,
            "unidentified": unidentified,
        }
    )
    return RatingLog(tuple(latest.values()), tuple(problems), revision)


@dataclass(frozen=True)
class VariantView:
    variant_id: str
    value: Any
    status: str
    image_refs: tuple[str, ...]
    controlled: bool | None  # None: no readback has been recorded
    reason: str
    seeds: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExperimentView:
    experiment_id: str
    state: str
    study_type: str
    stage: str
    variable: str
    values: tuple[Any, ...]
    model_sha: str
    model_family: str
    proposal_id: str
    fixed_digest: str
    prompt_context: str  # opaque; "" when the frozen snapshot carries no prompt
    variants: tuple[VariantView, ...]

    @property
    def images(self) -> tuple[tuple[str, str], ...]:
        """(variant_id, image path) for every completed variant's saved image."""
        return tuple(
            (v.variant_id, ref)
            for v in self.variants
            if v.status == "completed"
            for ref in v.image_refs
        )


@dataclass(frozen=True)
class ExperimentLoad:
    views: tuple[ExperimentView, ...] = ()
    problems: tuple[str, ...] = ()
    revision: str = ""


def _prompt_context(snapshot: Mapping[str, Any]) -> str:
    prompt = snapshot.get("prompt_text")
    if not isinstance(prompt, str) or not prompt.strip():
        return ""
    return "ctx-" + digest([prompt, snapshot.get("negative_prompt_text") or ""])[:12]


def _variant(raw: Mapping[str, Any]) -> VariantView:
    meta = raw.get("execution_metadata") if isinstance(raw.get("execution_metadata"), dict) else {}
    controlled = meta.get("controlled_evidence_valid")
    seeds = meta.get("actual_all_seeds")
    return VariantView(
        str(raw.get("variant_id") or ""),
        raw.get("param_value"),
        str(raw.get("status") or "pending"),
        tuple(str(ref) for ref in (raw.get("image_refs") or []) if isinstance(ref, str)),
        controlled if isinstance(controlled, bool) else None,
        str(meta.get("variable_validation_reason") or ""),
        tuple(s for s in seeds if isinstance(s, int) and not isinstance(s, bool))
        if isinstance(seeds, list)
        else (),
    )


def _state(frozen: bool, variants: Iterable[VariantView]) -> str:
    states = [v.status for v in variants]
    if not frozen:
        return STATE_DRAFT
    if states and all(s == "completed" for s in states):
        return STATE_COMPLETED
    if any(s == "failed" for s in states):
        return STATE_FAILED
    if any(s in ("running", "completed") for s in states):
        return STATE_RUNNING
    return STATE_PREPARED


def project_experiment(experiment_id: str, payload: Mapping[str, Any]) -> ExperimentView:
    current = payload.get("current_experiment")
    if not isinstance(current, dict):
        raise ValueError("no experiment definition")
    snapshot_json = current.get("execution_snapshot_json") or ""
    snapshot = thaw_snapshot(snapshot_json) if snapshot_json else {}
    meta = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
    proposal = snapshot.get("evidence_proposal") or meta.get("evidence_proposal") or {}
    identity = snapshot.get("model_identity") or proposal.get("identity") or {}
    variants = tuple(_variant(v) for v in (payload.get("plan") or []) if isinstance(v, dict))
    planning = proposal.get("planning_context") if isinstance(proposal, dict) else {}
    return ExperimentView(
        experiment_id=experiment_id,
        state=_state(bool(snapshot_json), variants),
        study_type=str(snapshot.get("study_type") or meta.get("study_type") or "ordinary"),
        stage=str(snapshot.get("stage") or current.get("stage") or ""),
        variable=variable_name(
            str(snapshot.get("variable_under_test") or current.get("variable_under_test") or "")
        ),
        values=tuple(snapshot.get("variant_values") or current.get("values") or ()),
        model_sha=str(identity.get("sha256") or ""),
        model_family=str(identity.get("family") or ""),
        proposal_id=str(proposal.get("proposal_id") or "") if isinstance(proposal, dict) else "",
        fixed_digest=str((planning or {}).get("fixed_execution_digest") or ""),
        prompt_context=_prompt_context(snapshot),
        variants=variants,
    )


def load_experiments(store: LearningExperimentStore | None) -> ExperimentLoad:
    if store is None:
        return ExperimentLoad(revision=digest(["no-store"]))
    problems: list[str] = []
    views: list[ExperimentView] = []
    try:
        handles = sorted(store.list_handles(), key=lambda h: h.experiment_id)
    except (OSError, ValueError, TypeError) as exc:
        return ExperimentLoad(
            problems=(f"Saved experiments could not be listed ({type(exc).__name__}).",),
            revision=digest(["unlistable"]),
        )
    if len(handles) > MAX_EXPERIMENTS:
        problems.append(
            f"Only the {MAX_EXPERIMENTS} most recently updated of {len(handles)} saved experiments were examined."
        )
        handles = sorted(handles, key=lambda h: (h.updated_at, h.experiment_id), reverse=True)[
            :MAX_EXPERIMENTS
        ]
        handles.sort(key=lambda h: h.experiment_id)
    unreadable = 0
    for handle in handles:
        payload = store.load_session(handle.experiment_id)
        if payload is None:
            unreadable += 1
            continue
        try:
            views.append(project_experiment(handle.experiment_id, payload))
        except (ValueError, TypeError, KeyError, AttributeError):
            unreadable += 1
    if unreadable:
        problems.append(f"{unreadable} saved experiment(s) were unreadable and are not evidence.")
    revision = digest(
        [
            [
                v.experiment_id,
                v.state,
                v.model_sha,
                [
                    [x.variant_id, x.status, x.controlled, x.reason, list(x.image_refs)]
                    for x in v.variants
                ],
            ]
            for v in views
        ]
    )
    return ExperimentLoad(tuple(views), tuple(problems), revision)
