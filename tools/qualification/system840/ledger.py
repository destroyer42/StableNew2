"""The source-backed capability/qualification ledger: load, validate, derive status, reconcile with live code.

``ledger.v1.json`` records, per capability: identity, reachability, evidence (offline, standalone feasibility, production
workflow, owner decision), the resource/quality/integration qualification, current governance, holds, the next smallest
admissible test and the provenance of every claim.  The rules below make the ledger refuse the inferences the campaign
forbids: a status is derived from applicable physical evidence (never from merged source, green CI or a decodable
artifact), evidence for a different model/workflow/runtime identity does not count, an unverified source can never support
QUALIFIED, and a driver-path run can never make integration QUALIFIED (only the normal operator GUI can).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.operator_journey.workspace import REPO_ROOT
from tools.qualification.system840.arms import ARM_BY_ID, ARMS
from tools.qualification.system840.statuses import (
    NON_EXECUTABLE,
    Confidence,
    EvidenceKind,
    Status,
)

LEDGER_PATH = Path(__file__).with_name("ledger.v1.json")
SCHEMA = "stablenew.qual-system-840.ledger.v1"
DIMENSIONS = ("resource", "quality", "integration")
#: Dimension values the ledger may record.
DIMENSION_STATUSES = frozenset(
    {
        Status.QUALIFIED,
        Status.PARTIALLY_QUALIFIED,
        Status.FEASIBLE,
        Status.INCONCLUSIVE,
        Status.NOT_TESTED,
        Status.NO_GO,
    }
)
#: Declared statuses that are decisions rather than derivations from the dimensions.
OVERRIDES = frozenset({Status.HOLD, Status.NO_GO, Status.UNSUPPORTED, Status.INCONCLUSIVE})
UNVERIFIED_PREFIX = "unverified"


@dataclass(frozen=True)
class Entry:
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def arm(self) -> str:
        return str(self.data["arm_id"])

    @property
    def status(self) -> Status:
        return Status(self.data["status"])

    @property
    def identity(self) -> dict[str, Any]:
        return dict(self.data.get("identity") or {})

    @property
    def evidence(self) -> list[dict[str, Any]]:
        return list(self.data.get("evidence") or [])

    def dimension(self, name: str) -> Status:
        return Status(self.data["qualification"][name])


class Ledger:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = dict(document)
        self._entries = [Entry(dict(c)) for c in document.get("capabilities", [])]
        self._by_id = {e.id: e for e in self._entries}

    def __iter__(self) -> Iterator[Entry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, capability_id: str) -> Entry | None:
        return self._by_id.get(capability_id)

    def for_arm(self, arm_id: str) -> list[Entry]:
        return [e for e in self._entries if e.arm == arm_id]

    @property
    def standing_holds(self) -> dict[str, dict[str, Any]]:
        return {h["id"]: h for h in self.document.get("standing_holds", [])}


def load_ledger(path: Path | str | None = None) -> Ledger:
    document = json.loads(Path(path or LEDGER_PATH).read_text(encoding="utf-8"))
    return Ledger(document)


# --------------------------------------------------------------------------------------------------------------------
# Evidence rules
# --------------------------------------------------------------------------------------------------------------------


def evidence_kind(item: Mapping[str, Any]) -> EvidenceKind:
    return EvidenceKind(item["kind"])


def evidence_applies(item: Mapping[str, Any], identity: Mapping[str, Any]) -> bool:
    """Evidence counts only for the exact identity it was taken on (model, workflow, runtime, profile...)."""

    return all(identity.get(key) == value for key, value in (item.get("applies_to") or {}).items())


def is_verified_source(item: Mapping[str, Any]) -> bool:
    exact = str(item.get("exact_source") or "")
    return bool(exact) and not exact.lower().startswith(UNVERIFIED_PREFIX)


def is_failed_attempt(item: Mapping[str, Any]) -> bool:
    """A recorded attempt that ended NO-GO or FAIL: it is history, never evidence that the workflow works."""

    result = str(item.get("result") or "").upper().replace("_", "-")
    return "NO-GO" in result or "FAIL" in result


def applicable_physical(entry: Entry) -> list[dict[str, Any]]:
    return [
        e
        for e in entry.evidence
        if evidence_kind(e).physical and evidence_applies(e, entry.identity)
    ]


def derive_status(entry: Entry) -> Status:
    """The status the dimensions and applicable physical evidence support (overrides are checked separately)."""

    dims = [entry.dimension(d) for d in DIMENSIONS]
    if all(d == Status.QUALIFIED for d in dims):
        return Status.QUALIFIED
    if any(d in (Status.QUALIFIED, Status.PARTIALLY_QUALIFIED) for d in dims):
        return Status.PARTIALLY_QUALIFIED
    if applicable_physical(entry):
        return Status.FEASIBLE
    return Status.NOT_TESTED


# --------------------------------------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------------------------------------


def validate_ledger(
    ledger: Ledger, *, repo_root: Path = REPO_ROOT, check_paths: bool = True
) -> list[str]:
    """Completeness and consistency problems (empty means the ledger is valid)."""

    problems: list[str] = []
    document = ledger.document
    if document.get("schema") != SCHEMA:
        problems.append(f"ledger schema is not {SCHEMA}")
    holds = ledger.standing_holds
    seen: set[str] = set()
    for entry in ledger:
        cid, data = entry.id, entry.data
        if cid in seen:
            problems.append(f"{cid}: duplicate capability id")
        seen.add(cid)
        if entry.arm not in ARM_BY_ID:
            problems.append(f"{cid}: unknown arm {entry.arm}")
            continue
        if not cid.startswith(f"{entry.arm}."):
            problems.append(f"{cid}: id must start with its arm ({entry.arm}.)")
        for key in (
            "version",
            "title",
            "identity",
            "reachability",
            "evidence",
            "qualification",
            "status",
            "governance",
            "next_test",
            "confidence",
            "sources",
        ):
            if not data.get(key):
                problems.append(f"{cid}: {key} is required")
        try:
            Confidence(data.get("confidence"))
            status = entry.status
            dims = {d: entry.dimension(d) for d in DIMENSIONS}
        except (ValueError, KeyError) as exc:
            problems.append(f"{cid}: {exc}")
            continue
        for name, value in dims.items():
            if value not in DIMENSION_STATUSES:
                problems.append(f"{cid}: {name} may not be {value.value}")
        for item in entry.evidence:
            problems += _evidence_problems(cid, item)
        physical = applicable_physical(entry)
        for name, value in dims.items():
            if (
                value in (Status.QUALIFIED, Status.PARTIALLY_QUALIFIED, Status.FEASIBLE)
                and not physical
            ):
                problems.append(
                    f"{cid}: {name} is {value.value} without applicable physical evidence"
                )
        # Status rules.
        if status in OVERRIDES:
            if status == Status.HOLD and not data.get("holds"):
                problems.append(f"{cid}: HOLD must name its holds")
            if status == Status.INCONCLUSIVE and not physical:
                problems.append(f"{cid}: INCONCLUSIVE needs a physical attempt on record")
            if status == Status.NO_GO and not entry.evidence:
                problems.append(f"{cid}: NO-GO needs evidence or a recorded decision")
        else:
            derived = derive_status(entry)
            if derived != status:
                problems.append(
                    f"{cid}: declared {status.value} but the evidence supports {derived.value}"
                )
        for hold_id in data.get("holds") or []:
            if hold_id not in holds:
                problems.append(f"{cid}: hold {hold_id} is not a standing hold")
        if status == Status.QUALIFIED:
            problems += _qualified_problems(entry)
        nxt = data.get("next_test") or {}
        if nxt.get("arm_id") not in ARM_BY_ID:
            problems.append(f"{cid}: next_test names an unknown arm")
        if (
            status in NON_EXECUTABLE
            and nxt.get("admissible")
            and nxt.get("needs_owner_authorization")
        ):
            problems.append(
                f"{cid}: a {status.value} capability cannot have an authorizable next test"
            )
        if check_paths:
            problems += _path_problems(cid, entry, repo_root)
    for arm in ARMS:
        if not ledger.for_arm(arm.arm_id):
            problems.append(f"arm {arm.arm_id} has no capability in the ledger")
        for hold in arm.holds:
            if hold.hold_id not in holds:
                problems.append(
                    f"arm {arm.arm_id}: hold {hold.hold_id} is not a standing hold in the ledger"
                )
            for target in hold.targets:
                if ledger.get(target) is None:
                    problems.append(
                        f"arm {arm.arm_id}: hold {hold.hold_id} names unknown capability {target}"
                    )
    return problems


def _evidence_problems(cid: str, item: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    try:
        kind = evidence_kind(item)
    except ValueError:
        return [f"{cid}/{item.get('id')}: unknown evidence kind {item.get('kind')!r}"]
    for key in ("id", "claim", "source", "date"):
        if not item.get(key):
            problems.append(f"{cid}/{item.get('id')}: {key} is required")
    if kind.physical and not item.get("exact_source"):
        problems.append(
            f"{cid}/{item.get('id')}: physical evidence must record its exact source (SHA or location)"
        )
    if kind.physical and item.get("surface") not in (None, "gui", "driver"):
        problems.append(f"{cid}/{item.get('id')}: surface must be gui or driver")
    return problems


def _qualified_problems(entry: Entry) -> list[str]:
    cid = entry.id
    problems: list[str] = []
    physical = applicable_physical(entry)
    if any(not is_verified_source(e) for e in physical):
        problems.append(
            f"{cid}: QUALIFIED cannot rest on physical evidence with an unverified source"
        )
    if not any(
        evidence_kind(e) == EvidenceKind.PRODUCTION_WORKFLOW
        and e.get("surface") == "gui"
        and not is_failed_attempt(e)
        for e in physical
    ):
        problems.append(
            f"{cid}: QUALIFIED needs production-workflow evidence taken through the operator GUI"
        )
    return problems


def _path_problems(cid: str, entry: Entry, repo_root: Path) -> list[str]:
    paths = list(entry.data.get("sources") or [])
    paths += [e["source"] for e in entry.evidence if e.get("source")]
    paths += list((entry.data.get("reachability") or {}).get("modules") or [])
    paths.append((entry.data.get("governance") or {}).get("source", ""))
    return [
        f"{cid}: cited path {p} does not exist"
        for p in sorted(set(paths))
        if p and not (repo_root / p).exists()
    ]


# --------------------------------------------------------------------------------------------------------------------
# Reconciliation with live code (current repository evidence outranks the recorded claims)
# --------------------------------------------------------------------------------------------------------------------


def _live_workflow_states() -> dict[tuple[str, str], dict[str, Any]]:
    from src.video.workflow_catalog import build_builtin_workflow_specs

    states: dict[tuple[str, str], dict[str, Any]] = {}
    for spec in build_builtin_workflow_specs():
        readiness = (spec.backend_defaults or {}).get("resource_readiness") or {}
        states[(spec.workflow_id, spec.workflow_version)] = {
            "governance": str(spec.governance_state),
            "qualification": readiness.get("qualification_status"),
        }
    return states


def _ai_registry(repo_root: Path) -> dict[str, dict[str, Any]]:
    path = repo_root / "config" / "ai_model_registry.json"
    return {
        m["model_id"]: m for m in json.loads(path.read_text(encoding="utf-8")).get("models", [])
    }


def reconcile_with_live(ledger: Ledger, *, repo_root: Path = REPO_ROOT) -> list[dict[str, str]]:
    """Differences between recorded claims and live catalog/registry state.  Live state wins; drift must be re-recorded."""

    drift: list[dict[str, str]] = []
    states = _live_workflow_states()
    registry = _ai_registry(repo_root)
    for entry in ledger:
        gov = str((entry.data.get("governance") or {}).get("state", "")).lower()
        claimed = (
            "approved"
            if gov.startswith("approved")
            else "experimental"
            if gov.startswith("experimental")
            else None
        )
        workflow = str(entry.identity.get("workflow") or "")
        if claimed and workflow:
            for ident, live in _workflow_selection(workflow, states):
                if live["governance"] != claimed:
                    drift.append(
                        {
                            "capability": entry.id,
                            "field": f"governance[{ident}]",
                            "recorded": claimed,
                            "live": live["governance"],
                        }
                    )
                if "not_qualified" in gov and live["qualification"] != "not_qualified":
                    drift.append(
                        {
                            "capability": entry.id,
                            "field": f"qualification[{ident}]",
                            "recorded": "not_qualified",
                            "live": str(live["qualification"]),
                        }
                    )
        model_id = entry.identity.get("model_id")
        if model_id:
            live_model = registry.get(str(model_id))
            if live_model is None:
                if str(model_id).startswith("qwen"):
                    drift.append(
                        {
                            "capability": entry.id,
                            "field": "registry",
                            "recorded": "present",
                            "live": "absent",
                        }
                    )
                continue
            if str(model_id).startswith("lfm3"):
                drift.append(
                    {
                        "capability": entry.id,
                        "field": "registry",
                        "recorded": "contract-only",
                        "live": "registered",
                    }
                )
            if live_model.get("sha256") != entry.identity.get("model_sha256"):
                drift.append(
                    {
                        "capability": entry.id,
                        "field": "model_sha256",
                        "recorded": str(entry.identity.get("model_sha256")),
                        "live": str(live_model.get("sha256")),
                    }
                )
            if live_model.get("bytes") != entry.identity.get("size"):
                drift.append(
                    {
                        "capability": entry.id,
                        "field": "size",
                        "recorded": str(entry.identity.get("size")),
                        "live": str(live_model.get("bytes")),
                    }
                )
            if live_model.get("qualified") and entry.status != Status.QUALIFIED:
                drift.append(
                    {
                        "capability": entry.id,
                        "field": "qualified",
                        "recorded": entry.status.value,
                        "live": "qualified=true",
                    }
                )
    return drift


def _workflow_selection(
    workflow: str, states: Mapping[tuple[str, str], dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    """``id@v1|v2`` selects those versions of one workflow; ``idA|idB`` selects every version of each id."""

    if "@" in workflow:
        wid, versions = workflow.split("@", 1)
        wanted = set(versions.split("|"))
        return [(f"{k[0]}@{k[1]}", v) for k, v in states.items() if k[0] == wid and k[1] in wanted]
    ids = set(workflow.split("|"))
    return [(f"{k[0]}@{k[1]}", v) for k, v in states.items() if k[0] in ids]


def summarize(ledger: Ledger) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_arm: dict[str, dict[str, int]] = {}
    for entry in ledger:
        by_status[entry.status.value] = by_status.get(entry.status.value, 0) + 1
        arm = by_arm.setdefault(entry.arm, {})
        arm[entry.status.value] = arm.get(entry.status.value, 0) + 1
    return {"capabilities": len(ledger), "by_status": by_status, "by_arm": by_arm}
