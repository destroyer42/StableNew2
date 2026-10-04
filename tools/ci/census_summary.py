"""Summarize a pytest JUnit XML into a test-census report (PR-DEVEX-CI-110). Standard library only.

    python tools/ci/census_summary.py census.xml [--top 200] [--json out.json] >> "$GITHUB_STEP_SUMMARY"

Produce the XML with ``pytest --junitxml=census.xml -o junit_family=xunit2 -o junit_duration_report=total`` so each
testcase time includes setup and teardown. Reports totals, the slowest tests, time by file and by top-level test area,
and a skipped-test reason summary. Measurement only: it never changes or filters a test run.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def module_file_from_classname(classname: str) -> str:
    """``tests.system.test_x.TestY`` -> ``tests/system/test_x.py`` (the first ``test_*`` segment ends the module path)."""

    parts = [p for p in classname.split(".") if p]
    for index, part in enumerate(parts):
        if part.startswith("test_"):
            return "/".join(parts[: index + 1]) + ".py"
    return "/".join(parts) + ".py" if parts else "(unknown)"


def area_of(test_file: str) -> str:
    parts = test_file.split("/")
    if len(parts) >= 3 and parts[0] == "tests":
        return parts[1]
    return "(top-level)"


def summarize(xml_path: Path, *, top: int = 200) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    cases: list[dict[str, Any]] = []
    suite_wall = 0.0
    for suite in suites:
        suite_wall += float(suite.get("time") or 0.0)
        for case in suite.iter("testcase"):
            file = module_file_from_classname(case.get("classname") or "")
            status = "passed"
            reason = ""
            for child in case:
                if child.tag in {"failure", "error"}:
                    status = child.tag
                elif child.tag == "skipped":
                    status = "skipped"
                    reason = (child.get("message") or "").strip().splitlines()[0][:100] if child.get("message") else "(no reason)"
            cases.append({
                "id": f"{file}::{case.get('name')}", "file": file, "area": area_of(file),
                "time": float(case.get("time") or 0.0), "status": status, "reason": reason,
            })
    by_file: dict[str, dict[str, float]] = defaultdict(lambda: {"tests": 0, "seconds": 0.0})
    by_area: dict[str, dict[str, float]] = defaultdict(lambda: {"tests": 0, "seconds": 0.0})
    for case in cases:
        for bucket, key in ((by_file, case["file"]), (by_area, case["area"])):
            bucket[key]["tests"] += 1
            bucket[key]["seconds"] += case["time"]
    statuses = Counter(case["status"] for case in cases)
    total_seconds = sum(case["time"] for case in cases)
    slowest = sorted(cases, key=lambda c: c["time"], reverse=True)[:top]
    return {
        "collected": len(cases),
        "passed": statuses["passed"], "failed": statuses["failure"], "errors": statuses["error"], "skipped": statuses["skipped"],
        "suite_wall_seconds": round(suite_wall, 1),
        "sum_test_seconds": round(total_seconds, 1),
        "slowest": [{"id": c["id"], "seconds": round(c["time"], 2)} for c in slowest],
        "by_file": sorted(({"file": k, "tests": int(v["tests"]), "seconds": round(v["seconds"], 1)} for k, v in by_file.items()), key=lambda r: r["seconds"], reverse=True),
        "by_area": sorted(({"area": k, "tests": int(v["tests"]), "seconds": round(v["seconds"], 1)} for k, v in by_area.items()), key=lambda r: r["seconds"], reverse=True),
        "skipped_reasons": Counter(c["reason"] for c in cases if c["status"] == "skipped").most_common(),
    }


def render_markdown(summary: dict[str, Any], *, top_files: int = 25, top_tests: int = 40) -> str:
    out = [
        "## Test census",
        "",
        f"collected {summary['collected']}: {summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['errors']} errors, {summary['skipped']} skipped; suite wall {summary['suite_wall_seconds']} s "
        f"(sum of test times {summary['sum_test_seconds']} s)",
        "",
        "### Time by top-level area",
        "| area | tests | seconds |",
        "|---|---:|---:|",
        *(f"| {r['area']} | {r['tests']} | {r['seconds']} |" for r in summary["by_area"]),
        "",
        f"### Slowest {top_files} files",
        "| file | tests | seconds |",
        "|---|---:|---:|",
        *(f"| {r['file']} | {r['tests']} | {r['seconds']} |" for r in summary["by_file"][:top_files]),
        "",
        f"### Slowest {top_tests} tests (full list of {len(summary['slowest'])} in the JSON artifact)",
        "| test | seconds |",
        "|---|---:|",
        *(f"| {r['id']} | {r['seconds']} |" for r in summary["slowest"][:top_tests]),
        "",
        "### Skipped reasons",
        *(f"- {count} x {reason}" for reason, count in summary["skipped_reasons"]),
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("xml", type=Path)
    parser.add_argument("--top", type=int, default=200)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = summarize(args.xml, top=args.top)
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sys.stdout.write(render_markdown(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
