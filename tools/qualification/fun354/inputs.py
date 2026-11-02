"""Operator-supplied qualification inputs: a manifest of prepared driving clips plus one reference image.

The manifest is local evidence (paths on the operator's machine); it is read here and never committed.  Each entry names a
``role``, the ``source_type`` it stands for and the exact file, so the plan can pin every byte and Q0 can re-verify it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.video.motion_source_preparation import sha256_file
from tools.qualification.fun354.plan import (
    ROLE_DRIVING,
    ROLE_Q2_DRIVING,
    ROLE_REFERENCE,
    CoverageEntry,
    InputPin,
    QualificationPlan,
    build_plan,
)

#: Roles that are part of Q1/Q2 themselves; every other manifest entry is a Q1C coverage clip.
CORE_ROLES = frozenset({ROLE_DRIVING, ROLE_Q2_DRIVING, ROLE_REFERENCE})


class InputsError(ValueError):
    pass


@dataclass(frozen=True)
class InputSet:
    """Pins for the plan plus the role -> file mapping Q0 and the executor read."""

    driving: InputPin
    reference: InputPin
    extra: tuple[InputPin, ...]
    coverage: tuple[CoverageEntry, ...]
    paths: dict[str, Path]

    def build_plan(self) -> QualificationPlan:
        return build_plan(
            driving_clip_sha256=self.driving.sha256,
            driving_clip_size=self.driving.size,
            reference_sha256=self.reference.sha256,
            reference_size=self.reference.size,
            extra_inputs=self.extra,
            coverage=self.coverage,
        )


def _pin(role: str, path: Path) -> InputPin:
    if not path.is_file():
        raise InputsError(f"The {role} file does not exist: {path.name}.")
    return InputPin(role, sha256_file(path), path.stat().st_size)


def load_input_set(manifest_path: str | Path | None, reference: str | Path | None) -> InputSet:
    """Pin every manifest clip and the reference image.  Re-reads and re-hashes each file."""

    if not manifest_path or not reference:
        raise InputsError("Both an inputs manifest and a reference image are required.")
    entries = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    paths: dict[str, Path] = {ROLE_REFERENCE: Path(reference)}
    pins: dict[str, InputPin] = {}
    coverage: list[CoverageEntry] = []
    for entry in entries:
        role = str(entry["role"])
        if role in paths:
            raise InputsError(f"The role {role} appears twice.")
        paths[role] = Path(entry["path"])
        pins[role] = _pin(role, paths[role])
        if role not in CORE_ROLES:
            coverage.append(CoverageEntry(role, str(entry["source_type"]), str(entry["label"])))
    if ROLE_DRIVING not in pins:
        raise InputsError("The manifest has no driving_clip.")
    extra = tuple(pin for role, pin in pins.items() if role != ROLE_DRIVING)
    return InputSet(
        driving=pins[ROLE_DRIVING],
        reference=_pin(ROLE_REFERENCE, paths[ROLE_REFERENCE]),
        extra=extra,
        coverage=tuple(coverage),
        paths=paths,
    )


def rebuild_plan(record: dict) -> QualificationPlan:
    """The plan a stored proposal describes, rebuilt from the current catalog and tooling."""

    pins = {i["role"]: i for i in record["inputs"]}
    extra = tuple(
        InputPin(i["role"], i["sha256"], int(i["size"]))
        for i in record["inputs"]
        if i["role"] not in (ROLE_DRIVING, ROLE_REFERENCE)
    )
    coverage = tuple(CoverageEntry(**c) for c in record.get("coverage", []))
    return build_plan(
        driving_clip_sha256=pins[ROLE_DRIVING]["sha256"],
        driving_clip_size=pins[ROLE_DRIVING]["size"],
        reference_sha256=pins[ROLE_REFERENCE]["sha256"],
        reference_size=pins[ROLE_REFERENCE]["size"],
        extra_inputs=extra,
        coverage=coverage,
    )
