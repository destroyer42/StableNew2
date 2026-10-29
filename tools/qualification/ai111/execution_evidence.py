"""Qualification evidence adapters; never launch, own, terminate or discover a process."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from functools import cache
from typing import Any

from src.ai_assist.framing import FramingError, render_prompt
from tools.qualification.ai111.plan import digest

RETROSPECTIVE_HOST = "host_retrospective"


def monitor_problems(monitor: Any) -> list[str]:
    """A label is insufficient: require the existing Windows capture/ownership implementation."""
    from tools.qualification.ai111.capture_session import (
        RETROSPECTIVE,
        CaptureAdmission,
        CaptureWindowProvider,
        RetrospectiveMonitor,
    )
    from tools.qualification.ai111.ownership import CHANNELS

    if type(monitor) is not RetrospectiveMonitor:
        return ["authentic retrospective capture monitor required"]
    if (
        monitor.kind != RETROSPECTIVE_HOST
        or monitor.forbid_elevation is not True
        or type(monitor.admission) is not CaptureAdmission
    ):
        return ["retrospective monitor provenance/capabilities mismatch"]
    if (
        len(monitor.providers) != len(CHANNELS)
        or {p.channel for p in monitor.providers} != set(CHANNELS)
        or any(
            type(p) is not CaptureWindowProvider
            or p.coverage != RETROSPECTIVE
            or p._admission is not monitor.admission
            for p in monitor.providers
        )
    ):
        return ["retrospective monitor providers/coverage mismatch"]
    return monitor.provider_problems()


@cache
def childless_proof(case_id: str) -> dict[str, str] | None:
    # Independently rederive from the frozen corpus and the production framing
    # function. Neither an outcome string nor the operator's row creates this permission.
    from tools.qualification.ai111.final_plan import final_corpus

    case = next((c for c in final_corpus() if c.case_id == case_id), None)
    if case is None or case.expected_outcome != "invalid_request":
        return None
    try:
        render_prompt(case.request("qualification-prelaunch-proof"))
    except FramingError:
        return {
            "path": "AiRuntime.render_prompt",
            "outcome": "invalid_request",
            "reason": "reserved_marker_in_text",
            "case_sha256": digest(asdict(case)),
        }
    return None


def childless_record_problems(row: Mapping[str, Any]) -> list[str]:
    expected = childless_proof(str(row.get("case_id", "")))
    if (
        expected is None
        or row.get("prelaunch_refusal") != expected
        or row.get("outcome") != expected["outcome"]
        or row.get("reason") != expected["reason"]
    ):
        return ["childless outcome is not the frozen deterministic prelaunch refusal"]
    if (
        not {
            "monitor_request_numbers",
            "process_complete",
            "active_after_teardown",
            "process_observations",
        }
        <= row.keys()
        or row.get("details", {}).get("child_observed") is True
        or row.get("execution_state") != "not_launched"
        or row.get("monitor_request_numbers") != []
        or row.get("process_complete") is not None
        or row.get("active_after_teardown") is not None
        or row.get("process_observations", []) != []
    ):
        return ["childless outcome claims or lacks explicit no-process evidence"]
    return []


def prelaunch_only(rows: Sequence[Mapping[str, Any]]) -> bool:
    return bool(rows) and all(
        row.get("execution_state") == "not_launched" and not childless_record_problems(row)
        for row in rows
    )


def session_teardown_problems(
    result: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Absence of a child is explicit N/A, never a fabricated successful teardown."""
    if result.get("abort_reason") != "":
        return ["capture aborted or teardown ambiguous"]
    if prelaunch_only(rows):
        return (
            []
            if result.get("no_processes_launched") is True
            and result.get("teardown_verified") is None
            else ["prelaunch-only capture disposition missing or contradictory"]
        )
    return (
        []
        if result.get("teardown_verified") is True
        and result.get("no_processes_launched") is not True
        else ["capture aborted or teardown ambiguous"]
    )


def ownership_problems(records: Sequence[Any]) -> list[str]:
    if not records:
        return ["owned child process observation missing"]
    problems = []
    if len(records) != 1:
        problems.append("request has ambiguous owned execution intervals")
    for record in records:
        process = getattr(record, "process", None)
        if (
            not isinstance(process, Mapping)
            or process.get("complete") is not True
            or process.get("active_after_teardown") != 0
            or process.get("problems", []) != []
        ):
            problems.append("owned child tree not verified gone")
        violations = getattr(record, "violations", None)
        if not isinstance(violations, list) or violations:
            problems.append("ownership violation or unreadable ownership findings")
    return problems


def observed_fields(records: Sequence[Any]) -> dict[str, Any]:
    processes = [dict(r.process) for r in records]
    active = [p.get("active_after_teardown") for p in processes]
    return {
        "monitor_request_numbers": [r.number for r in records],
        "process_observations": processes,
        "process_complete": all(p.get("complete") is True for p in processes)
        if processes
        else None,
        "active_after_teardown": sum(active)
        if active and all(type(n) is int for n in active)
        else None,
    }


def record_execution(
    case_id: str, outcome: str, reason: str, records: Sequence[Any]
) -> tuple[dict[str, Any], list[str]]:
    fields = {"execution_state": "launched", **observed_fields(records)}
    expected = childless_proof(case_id)
    if (
        not records
        and expected is not None
        and (outcome, reason) == (expected["outcome"], expected["reason"])
    ):
        fields.update(execution_state="not_launched", prelaunch_refusal=dict(expected))
        return fields, []
    problems = ownership_problems(records)
    if records and expected is not None:
        problems.append("a deterministic prelaunch refusal unexpectedly launched a child")
    return fields, problems


def fence_monitor(monitor: Any, reason: str) -> None:
    from tools.qualification.ai111.capture_session import RetrospectiveMonitor

    if isinstance(monitor, RetrospectiveMonitor):
        monitor.block_executable_work(reason)


def verified_contract_rows(
    rows: Sequence[Mapping[str, Any]], problems: Sequence[str]
) -> list[dict[str, Any]]:
    """Derived copies only: callers must first verify the capture and each raw owned interval."""
    result = []
    for row in rows:
        copy = dict(row)
        if not problems and row.get("monitor_kind") == RETROSPECTIVE_HOST:
            copy["monitor_implementation"] = RETROSPECTIVE_HOST
            copy["monitor_kind"] = "host"
            copy["details"] = {**row.get("details", {}), "egress_connections": 0}
        result.append(copy)
    return result
