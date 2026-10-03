"""Verify an environment against StableNew's exact Windows runtime constraints.

``constraints/windows-py312-cu130.txt`` is the only exact-version authority. This helper reads
its ``name==version`` pins and compares them with the installed distributions through
``importlib.metadata``. It does not import any ML package, so it is cheap and GPU-free.
Packages that are installed but not pinned are ignored.

The file has two profiles. Pins are *core* until a ``# profile: postprocess`` directive starts
the optional local restoration/upscale profile (``# profile-marker: a, b`` names the packages
whose presence means that profile is installed):

- core pins must all be installed at their pin;
- the postprocess profile is required when requested (``--with-postprocess``) or when a marker
  package is installed; otherwise it is absent by design, and any of its packages that happen to
  be installed must still match their pin.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONSTRAINTS = ROOT / "constraints" / "windows-py312-cu130.txt"
_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[A-Za-z0-9][A-Za-z0-9.+!_-]*)$")
_DIRECTIVE = re.compile(r"^#\s*(?P<key>profile|profile-marker)\s*:\s*(?P<value>.+?)\s*$")
CORE = "core"
POSTPROCESS = "postprocess"


class ConstraintsError(ValueError):
    """The constraints file is not a list of exact ``name==version`` pins."""


@dataclass(frozen=True)
class RuntimeProfiles:
    """Exact pins split into the core profile and the optional postprocess profile."""

    core: dict[str, str]
    postprocess: dict[str, str] = field(default_factory=dict)
    postprocess_markers: tuple[str, ...] = ()

    @property
    def all_pins(self) -> dict[str, str]:
        return {**self.core, **self.postprocess}


def normalize_name(name: str) -> str:
    """PEP 503 normalization: ``Pillow``, ``pillow`` and ``typing_extensions`` compare equal."""

    return re.sub(r"[-_.]+", "-", name).lower()


def parse_profiles(text: str) -> RuntimeProfiles:
    """Parse the constraints text; reject anything that is not an exact pin or a directive."""

    core: dict[str, str] = {}
    postprocess: dict[str, str] = {}
    markers: list[str] = []
    seen: set[str] = set()
    profile = CORE
    for number, raw in enumerate(text.splitlines(), start=1):
        directive = _DIRECTIVE.match(raw.strip())
        if directive is not None:
            if directive["key"] == "profile":
                value = directive["value"].lower()
                if value not in (CORE, POSTPROCESS):
                    raise ConstraintsError(f"line {number}: unknown profile {value!r}")
                profile = value
            else:
                markers.extend(
                    normalize_name(item.strip()) for item in directive["value"].split(",") if item.strip()
                )
            continue
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = _PIN.match(line)
        if match is None:
            raise ConstraintsError(f"line {number}: not an exact 'name==version' pin: {raw.strip()!r}")
        name = normalize_name(match["name"])
        if name in seen:
            raise ConstraintsError(f"line {number}: duplicate pin for {name!r}")
        seen.add(name)
        (core if profile == CORE else postprocess)[name] = match["version"]
    return RuntimeProfiles(core, postprocess, tuple(markers))


def parse_constraints(text: str) -> dict[str, str]:
    """Return every pin as ``{normalized name: exact version}`` regardless of profile."""

    return parse_profiles(text).all_pins


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


def postprocess_required(
    profiles: RuntimeProfiles, installed: Mapping[str, str], *, requested: bool
) -> bool:
    """The optional profile is required when requested or when a marker package is installed."""

    return requested or any(marker in installed for marker in profiles.postprocess_markers)


def evaluate(
    profiles: RuntimeProfiles, installed: Mapping[str, str], *, with_postprocess: bool = False
) -> tuple[list[str], str]:
    """Return ``(problems, postprocess state)``; state is ``complete``, ``absent`` or ``incomplete``."""

    problems = [f"[core] {item}" for item in find_mismatches(profiles.core, installed)]
    if postprocess_required(profiles, installed, requested=with_postprocess):
        optional = find_mismatches(profiles.postprocess, installed)
        problems += [f"[postprocess] {item}" for item in optional]
        return problems, "incomplete" if optional else "complete"
    # Absent by design: not an error, but any optional package that is present must not drift.
    present = {name: pin for name, pin in profiles.postprocess.items() if name in installed}
    problems += [f"[postprocess] {item}" for item in find_mismatches(present, installed)]
    return problems, "absent"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    parser.add_argument(
        "--with-postprocess",
        action="store_true",
        help="require the optional postprocess profile instead of treating its absence as valid",
    )
    args = parser.parse_args(argv)
    try:
        profiles = parse_profiles(args.constraints.read_text(encoding="utf-8"))
    except (OSError, ConstraintsError) as exc:
        print(f"RUNTIME CONSTRAINTS UNREADABLE: {args.constraints}: {exc}", file=sys.stderr)
        return 2
    problems, optional_state = evaluate(
        profiles, installed_versions(), with_postprocess=args.with_postprocess
    )
    if problems:
        print(
            f"RUNTIME DRIFT: {len(problems)} pinned package problem(s) against "
            f"{args.constraints.name} (postprocess profile: {optional_state}):",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "Rebuild the environment with scripts/bootstrap_windows.ps1 (add -WithPostprocess for "
            "the optional restoration/upscale stack; use -Recreate only on a dedicated venv path); "
            "do not edit packages by hand.",
            file=sys.stderr,
        )
        return 1
    optional_text = {
        "complete": f"postprocess profile complete ({len(profiles.postprocess)} pins)",
        "absent": "postprocess profile absent (optional, not required)",
    }[optional_state]
    print(f"runtime matches {args.constraints.name}: {len(profiles.core)} core pins; {optional_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
