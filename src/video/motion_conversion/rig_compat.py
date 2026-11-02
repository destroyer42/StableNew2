"""Bone-name compatibility between an animation's skeleton and a character (PR-VID-MOTION-354).

This is deliberately *not* a retargeting engine.  Animation may be applied to a character only when every bone the animation
drives exists on the character under the same name (after removing one known namespace prefix) and the character offers every
core humanoid bone.  Anything else is refused with the bones named; no bone is guessed, renamed or dropped silently.  The
only tolerated gap is an *optional* extremity (fingers, end markers), and each is recorded in the result.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

FAMILY_MIXAMO = "mixamo"
FAMILY_UNKNOWN = "unknown"
_NAMESPACE = re.compile(r"^(mixamorig\d*)[:_]?", re.IGNORECASE)
_OPTIONAL = re.compile(
    r"(thumb|index|middle|ring|pinky|_end$|end$|toe_end|toebase_end)", re.IGNORECASE
)
#: The Mixamo core every compatible humanoid must expose (suffix after the namespace is compared case-insensitively).
CORE_HUMANOID_BONES = (
    "Hips",
    "Spine",
    "Spine1",
    "Spine2",
    "Neck",
    "Head",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
    "LeftToeBase",
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
    "RightToeBase",
)
MAX_REPORTED = 12


@dataclass(frozen=True, slots=True)
class RigIdentity:
    family: str
    bone_count: int
    #: SHA-256 of the sorted, namespace-normalized bone names; equal fingerprints mean the same bone-name set.
    fingerprint: str

    def to_record(self) -> dict[str, object]:
        return {
            "family": self.family,
            "bone_count": self.bone_count,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class BindingPlan:
    """Verdict of binding one skeleton's animation to a character.  ``mapping`` is source -> character bone name."""

    compatible: bool
    mapping: tuple[tuple[str, str], ...] = ()
    missing_core: tuple[str, ...] = ()
    unmapped_required: tuple[str, ...] = ()
    dropped_optional: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    reason: str = ""

    def to_record(self) -> dict[str, object]:
        return {
            "compatible": self.compatible,
            "mapped_bones": len(self.mapping),
            "dropped_optional": list(self.dropped_optional),
            "reason": self.reason,
        }


def normalize_bone(name: str) -> str:
    """``mixamorig:Hips`` / ``mixamorig1:Hips`` -> ``hips``; any other name is only lower-cased."""

    text = str(name or "").strip()
    return _NAMESPACE.sub("", text).lower()


def identify_rig(bone_names: Iterable[str]) -> RigIdentity:
    names = [str(n) for n in bone_names if str(n)]
    normalized = sorted({normalize_bone(n) for n in names})
    core = {c.lower() for c in CORE_HUMANOID_BONES}
    mixamo_prefixed = sum(1 for n in names if _NAMESPACE.match(n))
    family = (
        FAMILY_MIXAMO
        if names and mixamo_prefixed >= max(10, len(names) * 9 // 10) and core <= set(normalized)
        else FAMILY_UNKNOWN
    )
    digest = hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()
    return RigIdentity(family=family, bone_count=len(names), fingerprint=digest)


def _shorten(values: list[str]) -> tuple[str, ...]:
    return tuple(values[:MAX_REPORTED])


def plan_binding(source_bones: Iterable[str], character_bones: Iterable[str]) -> BindingPlan:
    """Decide, without guessing, whether the source's animation can drive the character's bones."""

    source = [str(b) for b in source_bones if str(b)]
    character = [str(b) for b in character_bones if str(b)]
    if not source:
        return BindingPlan(False, reason="The animation file declares no skeleton bones.")
    if not character:
        return BindingPlan(False, reason="The character has no skeleton bones.")

    by_key: dict[str, list[str]] = {}
    for name in character:
        by_key.setdefault(normalize_bone(name), []).append(name)
    source_keys: dict[str, list[str]] = {}
    for name in source:
        source_keys.setdefault(normalize_bone(name), []).append(name)

    ambiguous = sorted(k for k, v in {**by_key}.items() if len(v) > 1) + sorted(
        k for k, v in source_keys.items() if len(v) > 1
    )
    if ambiguous:
        return BindingPlan(
            False,
            ambiguous=_shorten(ambiguous),
            reason="Bone names are ambiguous after namespace removal: "
            + ", ".join(ambiguous[:MAX_REPORTED])
            + ".",
        )

    missing_core = [
        c for c in CORE_HUMANOID_BONES if c.lower() not in by_key or c.lower() not in source_keys
    ]
    if missing_core:
        return BindingPlan(
            False,
            missing_core=_shorten(missing_core),
            reason="Core humanoid bones are missing from the source or the character: "
            + ", ".join(missing_core[:MAX_REPORTED])
            + ".",
        )

    mapping: list[tuple[str, str]] = []
    unmapped: list[str] = []
    dropped: list[str] = []
    for key, names in sorted(source_keys.items()):
        target = by_key.get(key)
        if target is not None:
            mapping.append((names[0], target[0]))
        elif _OPTIONAL.search(key):
            dropped.append(names[0])
        else:
            unmapped.append(names[0])
    if unmapped:
        return BindingPlan(
            False,
            unmapped_required=_shorten(unmapped),
            reason="The animation drives bones the character does not have: "
            + ", ".join(unmapped[:MAX_REPORTED])
            + ".",
        )
    return BindingPlan(True, mapping=tuple(mapping), dropped_optional=tuple(dropped))
