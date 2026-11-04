"""Versioned registries: structured product findings and the critical-workflow coverage matrix.

Both are plain JSON next to this module so they are reviewable in a diff.  The validators fail closed: an unknown
severity, repair status or coverage class, a missing reference or a dangling journey/test/finding link is a problem
string, never silently accepted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.operator_journey.golden.definitions import JOURNEYS
from tools.operator_journey.golden.friction import FRICTION_ACTIONS
from tools.operator_journey.workspace import REPO_ROOT

HERE = Path(__file__).resolve().parent
FINDINGS_PATH = HERE / "findings.v1.json"
COVERAGE_PATH = HERE / "coverage_matrix.v1.json"

SEVERITIES = ("blocking", "major", "minor")
REPAIR_STATUSES = ("UNREPAIRED", "UNCLASSIFIED", "REPAIRED", "WONTFIX")
COVERAGE_CLASSES = (
    "full_desktop_journey",
    "partial_journey",
    "integration_only",
    "untested",
)
_FINDING_REQUIRED = (
    "id",
    "title",
    "severity",
    "category",
    "area",
    "environment",
    "reproduction",
    "expected",
    "observed",
    "harness_workaround",
    "evidence",
    "repair",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_findings(path: Path = FINDINGS_PATH) -> dict[str, Any]:
    return _load(path)


def load_coverage(path: Path = COVERAGE_PATH) -> dict[str, Any]:
    return _load(path)


def finding_problems(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if doc.get("schema") != "stablenew.golden_findings" or not doc.get("version"):
        problems.append("findings: missing schema/version")
    seen: set[str] = set()
    kinds = {kind for kind, _f, _c in FRICTION_ACTIONS.values()}
    for finding in doc.get("findings", []):
        fid = str(finding.get("id", "?"))
        if fid in seen:
            problems.append(f"{fid}: duplicate id")
        seen.add(fid)
        for key in _FINDING_REQUIRED:
            if finding.get(key) in (None, "", [], {}):
                problems.append(f"{fid}: missing {key}")
        if finding.get("severity") not in SEVERITIES:
            problems.append(f"{fid}: unknown severity {finding.get('severity')!r}")
        status = (finding.get("repair") or {}).get("status")
        if status not in REPAIR_STATUSES:
            problems.append(f"{fid}: unknown repair status {status!r}")
        for ref in finding.get("evidence", []):
            if not ref.get("source_hint") or not ref.get("description"):
                problems.append(f"{fid}: evidence needs description and source_hint")
        for kind in finding.get("friction_kinds", []):
            if kind not in kinds:
                problems.append(f"{fid}: unknown friction kind {kind!r}")
    return problems


def coverage_problems(doc: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    if doc.get("schema") != "stablenew.golden_coverage_matrix" or not doc.get("version"):
        problems.append("coverage: missing schema/version")
    journey_ids = {j.id for j in JOURNEYS.values()}
    seen: set[str] = set()
    for row in doc.get("workflows", []):
        wid = str(row.get("id", "?"))
        if wid in seen:
            problems.append(f"{wid}: duplicate id")
        seen.add(wid)
        cls = row.get("coverage")
        if cls not in COVERAGE_CLASSES:
            problems.append(f"{wid}: unknown coverage class {cls!r}")
            continue
        journeys, tests = row.get("journeys", []), row.get("tests", [])
        for journey in journeys:
            if journey not in journey_ids:
                problems.append(f"{wid}: unknown journey {journey!r}")
        for test in tests:
            if not (repo_root / test).is_file():
                problems.append(f"{wid}: test file {test} does not exist")
        if cls in ("full_desktop_journey", "partial_journey") and not journeys:
            problems.append(f"{wid}: {cls} needs at least one journey")
        if cls == "integration_only" and (journeys or not tests):
            problems.append(f"{wid}: integration_only needs tests and no journey")
        if cls == "untested" and (journeys or tests):
            problems.append(f"{wid}: untested must not list journeys or tests")
        if not row.get("limits"):
            problems.append(f"{wid}: limits must be stated")
    return problems


def coverage_summary(doc: dict[str, Any]) -> dict[str, int]:
    counts = dict.fromkeys(COVERAGE_CLASSES, 0)
    for row in doc.get("workflows", []):
        if row.get("coverage") in counts:
            counts[row["coverage"]] += 1
    return counts


__all__ = [
    "COVERAGE_CLASSES",
    "SEVERITIES",
    "coverage_problems",
    "coverage_summary",
    "finding_problems",
    "load_coverage",
    "load_findings",
]
