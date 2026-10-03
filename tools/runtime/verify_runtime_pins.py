"""Verify an environment against StableNew's exact Windows runtime constraints.

``constraints/windows-py312-cu130.txt`` is the only exact-version authority. This helper reads
its ``name==version`` pins and compares them with the installed distributions through
``importlib.metadata``. It does not import any ML package, so it is cheap and GPU-free.
Packages that are installed but not pinned are ignored; only missing or different pinned
packages fail.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONSTRAINTS = ROOT / "constraints" / "windows-py312-cu130.txt"
_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[A-Za-z0-9][A-Za-z0-9.+!_-]*)$")


class ConstraintsError(ValueError):
    """The constraints file is not a list of exact ``name==version`` pins."""


def normalize_name(name: str) -> str:
    """PEP 503 normalization: ``Pillow``, ``pillow`` and ``typing_extensions`` compare equal."""

    return re.sub(r"[-_.]+", "-", name).lower()


def parse_constraints(text: str) -> dict[str, str]:
    """Return ``{normalized name: exact version}``; reject anything that is not an exact pin."""

    pins: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = _PIN.match(line)
        if match is None:
            raise ConstraintsError(f"line {number}: not an exact 'name==version' pin: {raw.strip()!r}")
        name = normalize_name(match["name"])
        if name in pins:
            raise ConstraintsError(f"line {number}: duplicate pin for {name!r}")
        pins[name] = match["version"]
    return pins


def versions_equal(installed: str, pinned: str) -> bool:
    """PEP 440 equality, so ``2.14.0+cu130`` only equals ``2.14.0+cu130`` (not ``2.14.0``)."""

    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:  # pragma: no cover - packaging is itself a pinned dependency
        return installed.strip().lower() == pinned.strip().lower()
    try:
        return Version(installed) == Version(pinned)
    except InvalidVersion:
        return installed.strip().lower() == pinned.strip().lower()


def installed_versions() -> dict[str, str]:
    return {
        normalize_name(dist.metadata["Name"]): dist.version
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }


def find_mismatches(pins: Mapping[str, str], installed: Mapping[str, str]) -> list[str]:
    """Human-readable problems; empty when every pinned package is installed at its pin."""

    problems = []
    for name, pinned in sorted(pins.items()):
        have = installed.get(name)
        if have is None:
            problems.append(f"{name}: missing (expected {pinned})")
        elif not versions_equal(have, pinned):
            problems.append(f"{name}: installed {have}, expected {pinned}")
    return problems




def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    args = parser.parse_args(argv)
    try:
        pins = parse_constraints(args.constraints.read_text(encoding="utf-8"))
    except (OSError, ConstraintsError) as exc:
        print(f"RUNTIME CONSTRAINTS UNREADABLE: {args.constraints}: {exc}", file=sys.stderr)
        return 2
    problems = find_mismatches(pins, installed_versions())
    if problems:
        print(
            f"RUNTIME DRIFT: {len(problems)} of {len(pins)} pinned package(s) differ from "
            f"{args.constraints.name}:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "Rebuild the environment with scripts/bootstrap_windows.ps1 (use -Recreate only on a "
            "dedicated venv path); do not edit packages by hand.",
            file=sys.stderr,
        )
        return 1
    print(f"runtime matches {args.constraints.name}: {len(pins)} pinned packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
