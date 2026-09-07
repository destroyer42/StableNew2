"""Enforce the version-pinned, non-increasing StableNew Ruff baseline."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "tools" / "ci" / "ruff_baseline.json"


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _ruff_version() -> str:
    result = _run("ruff", "--version")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ruff --version failed")
    parts = result.stdout.strip().split()
    if len(parts) != 2 or parts[0] != "ruff":
        raise RuntimeError(f"unexpected Ruff version output: {result.stdout!r}")
    return parts[1]


def _load_baseline() -> dict[str, Any]:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("unsupported Ruff baseline schema")
    if not isinstance(payload.get("counts"), dict):
        raise RuntimeError("Ruff baseline counts must be an object")
    return payload


def _relative_source_path(filename: str) -> str:
    path = Path(filename)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"Ruff reported a path outside the repository: {path}") from exc


def _current_counts() -> Counter[str]:
    result = _run("ruff", "check", "src", "--output-format", "json")
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "ruff check failed")
    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("could not parse Ruff JSON output") from exc
    if not isinstance(diagnostics, list):
        raise RuntimeError("Ruff JSON output must be a list")

    counts: Counter[str] = Counter()
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            raise RuntimeError("Ruff diagnostic must be an object")
        path = _relative_source_path(str(diagnostic.get("filename", "")))
        code = str(diagnostic.get("code", "")).strip()
        if not code:
            raise RuntimeError(f"Ruff diagnostic for {path} has no rule code")
        counts[f"{path}|{code}"] += 1
    return counts


def main() -> int:
    try:
        baseline = _load_baseline()
        expected_version = str(baseline["ruff_version"])
        actual_version = _ruff_version()
        if actual_version != expected_version:
            raise RuntimeError(
                f"Ruff version mismatch: expected {expected_version}, got {actual_version}"
            )

        allowed = Counter(
            {str(key): int(value) for key, value in baseline["counts"].items()}
        )
        current = _current_counts()
        increases = {
            key: (allowed.get(key, 0), count)
            for key, count in current.items()
            if count > allowed.get(key, 0)
        }
        if increases:
            print("Ruff debt increased:", file=sys.stderr)
            for key, (before, after) in sorted(increases.items()):
                print(f"  {key}: {before} -> {after}", file=sys.stderr)
            return 1

        baseline_total = sum(allowed.values())
        current_total = sum(current.values())
        if baseline_total != int(baseline["total"]):
            raise RuntimeError("Ruff baseline total does not match its counts")
        print(
            "Ruff baseline OK "
            f"(version {actual_version}; findings {current_total}/{baseline_total})"
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Ruff baseline gate failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
