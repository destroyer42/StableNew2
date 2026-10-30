"""Fail-closed preparation checks shared by qualification execution entrypoints.

Evidence is supplied independently by the operator. This module grants nothing,
installs nothing, and never converts an attestation to measured evidence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.qualification.ai111.execution_contract import ExecutionSpec
from tools.qualification.ai111.execution_evidence import RETROSPECTIVE_HOST

HOST_MODULES = frozenset({"vcruntime140.dll", "ucrtbase.dll", "ws2_32.dll", "crypt32.dll"})


def bind_capture_evidence(evidence: Mapping[str, Any] | None, monitor: Any) -> dict[str, Any]:
    """Obtain the active capture from the existing admission object, never from a readiness flag."""
    from tools.qualification.ai111.capture_evidence import read_json

    bound = dict(evidence or {})
    admission = getattr(monitor, "admission", None)
    if admission is None:
        return bound
    try:
        bound["capture_manifest"] = read_json(admission.capture_dir / "capture.json")
        supplied = bound.get("canary_proof", {})
        if (
            not admission.proof_path
            or Path(supplied.get("path", "")).resolve() != admission.proof_path.resolve()
        ):
            bound["canary_proof"] = None
    except (OSError, ValueError, TypeError):
        bound["capture_manifest"] = {}
    return bound


def d12a_problems(
    spec: ExecutionSpec,
    result: Mapping[str, Any],
    analysis: Mapping[str, Any] | None,
    executable: str,
) -> list[str]:
    from tools.qualification.ai111.capture_evidence import capture_problems
    from tools.qualification.ai111.d12a import analyze_help
    from tools.qualification.ai111.lfm3_contract import LFM3_ALLOWED_FLAGS

    member = result.get("members", {}).get(executable, {})
    problems = []
    compatibility = member.get("compatibility") or {}
    if (
        not (
            result.get("verdict") == "PASS"
            or (
                result.get("verdict") == "INCONCLUSIVE"
                and result.get("pending_capture_analysis") is True
                and result.get("realtime_verdict") == "PASS"
            )
        )
        or result.get("contract_sha256") != spec.sha256
        or result.get("archive_sha256") != spec.runtime["sha256"]
        or member.get("sha256") != spec.members.get(executable)
        or member.get("verdict") != "PASS"
        or compatibility.get("verdict") != "PASS"
        or compatibility.get("help_truncated_at_cap") is not False
        or result.get("monitor_kind") != RETROSPECTIVE_HOST
    ):
        problems.append("D12a for selected contract/executable absent")
    problems += dependency_problems(result.get("host_dependencies"), verify_files=True)
    deps = result.get("host_dependencies", {})
    if deps.get("capture_id") != result.get("capture_id") or deps.get(
        "runtime_member_sha256"
    ) != spec.members.get(executable):
        problems.append("D12a host dependencies belong to another interval/member")
    rows = []
    for name, measured in result.get("members", {}).items():
        for command in measured.get("commands", []):
            rows.append(
                {
                    **command,
                    "executable": name,
                    "runtime_member_sha256": measured.get("sha256"),
                    "capture_id": result.get("capture_id"),
                    "run_id": result.get("run_id"),
                    "monitor_kind": result.get("monitor_kind"),
                }
            )
    if len(rows) != 2 or [r.get("command", [])[1:] for r in rows] != [["--version"], ["--help"]]:
        problems.append("D12a command evidence incomplete")
    if set(result.get("members", {})) != {executable} or any(
        r.get("returncode") != 0
        or r.get("timed_out") is not False
        or r.get("cancelled") is not False
        or r.get("contained") is not True
        or r.get("output_truncated_at_cap") is not False
        or r.get("launch_error")
        for r in rows
    ):
        problems.append("D12a command failed or has incomplete bounds evidence")
    try:
        root = Path(result["evidence"])
        help_bytes = (root / f"{Path(executable).stem}.help.stdout.txt").read_bytes()
        if not help_bytes:
            help_bytes = (root / f"{Path(executable).stem}.help.stderr.txt").read_bytes()
        if (
            analyze_help(
                help_bytes.decode("utf-8", "strict"),
                truncated=len(help_bytes) > 64 * 1024,
                required_flags=LFM3_ALLOWED_FLAGS,
            )["verdict"]
            != "PASS"
        ):
            problems.append("D12a raw help does not prove every contract flag")
    except (OSError, KeyError, UnicodeError):
        problems.append("D12a raw help unavailable")
    problems += capture_problems(
        Path(str(result.get("evidence", ""))).parent / "capture",
        analysis,
        rows,
        run_id=result.get("run_id"),
        capture_id=result.get("capture_id"),
    )
    return sorted(set(problems))


def dependency_problems(
    report: Mapping[str, Any] | None, *, verify_files: bool = False
) -> list[str]:
    if (
        not report
        or report.get("status") != "MEASURED"
        or report.get("source") != "owned-child-loaded-modules"
    ):
        return ["host dependency closure unmeasured"]
    modules = report.get("modules", [])
    names = [str(r.get("name", "")).lower() for r in modules]
    problems = []
    if not HOST_MODULES <= set(names) or len(set(names)) != len(names):
        problems.append("host dependency set missing or duplicated")
    if report.get("complete") is not True or not report.get("request_numbers"):
        problems.append("host dependency closure incomplete")
    for module in modules:
        if any(not module.get(k) for k in ("name", "path", "version", "sha256", "evidence_source")):
            problems.append("host dependency provenance missing")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(module.get("sha256", "")))
            or Path(str(module.get("path", ""))).name.lower() != str(module.get("name", "")).lower()
        ):
            problems.append("host dependency identity malformed")
        if verify_files:
            path = Path(str(module.get("path", "")))
            try:
                if (
                    path.is_symlink()
                    or not path.is_absolute()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != module.get("sha256")
                ):
                    problems.append("host dependency drift")
            except OSError:
                problems.append("host dependency unreadable")
    return problems


def approval_records(
    spec: ExecutionSpec, evidence: Mapping[str, Any], stage: str, now: datetime
) -> list[str]:
    from tools.qualification.ai111.lfm3_contract import approval_problems

    required = ["S0_download", "S1_license", "S2_d12a_b11960"]
    if stage in ("S3_stage_a", "S4_stage_b"):
        required.append("S3_stage_a")
    if stage == "S4_stage_b":
        required.append("S4_stage_b")
    problems = []
    prior = datetime(2026, 10, 29, tzinfo=UTC)
    for step in required:
        supplied = evidence.get("approval_records", {})
        record = supplied.get(step, {}) if isinstance(supplied, Mapping) else {}
        record = record if isinstance(record, Mapping) else {}
        try:
            issued = datetime.fromisoformat(record["issued_utc"])
            valid_time = issued.tzinfo is not None and prior <= issued <= now
        except (KeyError, TypeError, ValueError):
            valid_time = False
        text = record.get("text", "")
        if (
            record.get("authority") != "owner"
            or record.get("decision") != "APPROVE"
            or not record.get("reference")
            or not valid_time
            or not isinstance(text, str)
            or approval_problems(step, text, spec.document)
        ):
            problems.append(f"independent authorization missing/invalid: {step}")
        if valid_time:
            prior = issued
    return problems


def readiness_problems(
    spec: ExecutionSpec,
    stage: str,
    evidence: Mapping[str, Any] | None,
    *,
    executable: str,
    now: datetime | None = None,
) -> list[str]:
    if spec.selector != "lfm3-v1":
        return []
    from tools.qualification.ai111.lfm3_contract import readiness_blockers

    if stage not in ("S2_d12a_b11960", "S3_stage_a", "S4_stage_b"):
        return ["unknown execution stage"]
    evidence = evidence or {}
    now = now or datetime.now(UTC)
    # The frozen guard still runs. Texts are obtained from independent approval
    # records, never from the contract or a technical capability flag.
    mapped = dict(evidence)
    records = evidence.get("approval_records", {})
    mapped["approvals"] = (
        {k: v.get("text", "") for k, v in records.items() if isinstance(v, Mapping)}
        if isinstance(records, Mapping)
        else {}
    )
    problems = readiness_blockers(stage, mapped, spec.document)
    from tools.qualification.ai111.lfm3_contract import runtime_problems

    supplied_runtime = evidence.get("runtime")
    if (
        not isinstance(supplied_runtime, Mapping)
        or runtime_problems(supplied_runtime, require_members=True)
        or supplied_runtime != spec.runtime
    ):
        problems.append("selected runtime integrity evidence absent")
    problems += approval_records(spec, evidence, stage, now)
    if executable not in spec.members:
        problems.append("explicit permitted executable required")
    for key in ("protected_python", "protected_capture_control"):
        proof = evidence.get(key, {})
        if (
            proof.get("problems") != []
            or proof.get("source") != "capture_control.runtime_trust_problems"
            or not proof.get("path")
            or not proof.get("sha256")
        ):
            problems.append(f"{key} measured protection proof absent")
        else:
            try:
                path = Path(proof["path"])
                if (
                    not path.is_absolute()
                    or path.is_symlink()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != proof["sha256"]
                ):
                    problems.append(f"{key} proof file changed")
            except OSError:
                problems.append(f"{key} proof file unavailable")
    from tools.qualification.ai111.capture_control import tool_sha256

    if evidence.get("protected_capture_control", {}).get("sha256") != tool_sha256():
        problems.append("protected capture copy hash differs from reviewed source")
    attestation = evidence.get("firewall_attestation", {})
    if (
        attestation.get("authority") != "operator"
        or not attestation.get("statement")
        or attestation.get("verified_by_stablenew") is not False
    ):
        problems.append("operator firewall attestation absent (never measured proof)")
    if not isinstance(evidence.get("canary_proof"), Mapping):
        problems.append("fresh applicable canary proof absent")
    else:
        from tools.qualification.ai111.capture_session import CaptureAdmission

        proof = evidence["canary_proof"]
        try:
            path = Path(proof["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != proof["sha256"]:
                problems.append("canary proof file changed")
            admission = CaptureAdmission(Path("."), "", proof_path=path, now=lambda: now)
            problems += admission._proof_problems(dict(evidence.get("capture_manifest", {})))
        except (OSError, KeyError, TypeError, ValueError):
            problems.append("fresh applicable canary proof absent")
    capture = evidence.get("capture_manifest", {})
    runtime = capture.get("runtime", {})
    if (
        capture.get("tool_sha256") != tool_sha256()
        or runtime.get("protection_verified") is not True
        or runtime.get("script") != evidence.get("protected_capture_control", {}).get("path")
        or runtime.get("executable") != evidence.get("protected_python", {}).get("path")
    ):
        problems.append("protected runtime not bound to this capture")
    if stage != "S2_d12a_b11960":
        result = evidence.get("d12a", {})
        problems += d12a_problems(spec, result, evidence.get("d12a_capture"), executable)
    return sorted(set(problems))
