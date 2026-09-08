"""Enforce StableNew's top-level controller physical-line ratchet."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = Path("tools/ci/controller_surface_baseline.json")
CONTROLLER_DIR = Path("src/controller")


@dataclass(frozen=True, order=True)
class ControllerSurfaceIssue:
    """One deterministic controller-surface failure."""

    code: str
    path: str
    detail: str

    def format(self) -> str:
        return f"{self.code}: {self.path}: {self.detail}"


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _load_baseline(path: Path) -> tuple[int, dict[str, int]]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported controller baseline schema")
    if payload.get("metric") != "physical_lines":
        raise ValueError("controller baseline metric must be physical_lines")

    new_limit = payload.get("new_controller_limit")
    raw_ceilings = payload.get("ceilings")
    if not isinstance(new_limit, int) or new_limit < 1:
        raise ValueError("new_controller_limit must be a positive integer")
    if not isinstance(raw_ceilings, dict):
        raise ValueError("controller ceilings must be an object")

    ceilings: dict[str, int] = {}
    for raw_path, raw_ceiling in raw_ceilings.items():
        path_key = str(raw_path).replace("\\", "/")
        if not isinstance(raw_ceiling, int) or raw_ceiling < 1:
            raise ValueError(f"ceiling for {path_key} must be a positive integer")
        if Path(path_key).parent.as_posix() != CONTROLLER_DIR.as_posix():
            raise ValueError(f"ceiling is not a top-level controller: {path_key}")
        ceilings[path_key] = raw_ceiling
    return new_limit, ceilings


def inspect_controller_surfaces(
    root: Path | str,
    baseline_path: Path | str | None = None,
) -> list[ControllerSurfaceIssue]:
    """Return growth, stale-ratchet, and new-oversized-controller failures."""

    repo_root = Path(root).resolve()
    baseline_file = (
        Path(baseline_path).resolve()
        if baseline_path is not None
        else repo_root / DEFAULT_BASELINE
    )
    new_limit, ceilings = _load_baseline(baseline_file)
    issues: list[ControllerSurfaceIssue] = []

    for relative_path, ceiling in sorted(ceilings.items()):
        source_path = repo_root / relative_path
        if not source_path.is_file():
            issues.append(
                ControllerSurfaceIssue(
                    "RATCHET_TARGET_MISSING",
                    relative_path,
                    "remove or revise the checked-in ceiling with the controller change",
                )
            )
            continue
        actual = _line_count(source_path)
        if actual > ceiling:
            issues.append(
                ControllerSurfaceIssue(
                    "CONTROLLER_GROWTH",
                    relative_path,
                    f"physical lines grew from ceiling {ceiling} to {actual}",
                )
            )
        elif actual < ceiling:
            issues.append(
                ControllerSurfaceIssue(
                    "CEILING_NOT_LOWERED",
                    relative_path,
                    f"physical lines fell to {actual}; lower the checked-in ceiling from {ceiling}",
                )
            )

    controller_root = repo_root / CONTROLLER_DIR
    for source_path in sorted(controller_root.glob("*.py")):
        relative_path = source_path.relative_to(repo_root).as_posix()
        if relative_path in ceilings:
            continue
        actual = _line_count(source_path)
        if actual > new_limit:
            issues.append(
                ControllerSurfaceIssue(
                    "NEW_OVERSIZED_CONTROLLER",
                    relative_path,
                    f"{actual} physical lines exceeds the new-controller limit {new_limit}",
                )
            )

    return sorted(issues)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="repository root")
    parser.add_argument("--baseline", help="baseline file; defaults inside the root")
    args = parser.parse_args(argv)

    try:
        issues = inspect_controller_surfaces(args.root, args.baseline)
        baseline_path = (
            Path(args.baseline).resolve()
            if args.baseline
            else Path(args.root).resolve() / DEFAULT_BASELINE
        )
        new_limit, ceilings = _load_baseline(baseline_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Controller surface ratchet failed: {exc}", file=sys.stderr)
        return 2

    if issues:
        print(f"Controller surface ratchet FAILED ({len(issues)} issue(s))", file=sys.stderr)
        for issue in issues:
            print(f"  {issue.format()}", file=sys.stderr)
        return 1

    print(
        "Controller surface ratchet OK "
        f"({len(ceilings)} ratcheted; new-controller limit {new_limit} physical lines)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
