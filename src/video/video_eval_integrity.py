"""Comparison-integrity vocabulary for controlled-motion eval runs (PR-VID-MOTION-410).

Pure functions over *frozen settings* (the facts a compiled NJR recorded, ``MotionFacts.settings()``), never over display
labels or case ids. They answer two questions the existing three-state ``Comparability`` cannot:

* **What kind of comparison is this?** ``one_variable`` (exactly one declared workflow control differs), ``multi_arm``
  (several settings differ, or an implementation difference such as another workflow version, so the effects are not
  separable) or ``cross_subject`` (the source image is intentionally the only change).
* **Can the evidence be trusted as comparable?** ``IntegrityClass`` extends the existing assessment conventions with the
  reasons a cell or pair cannot be (changed input, changed output, missing evidence, failed or incomplete).

Nothing here ranks arms, rates quality or reads a file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class IntegrityClass(str, Enum):
    VERIFIED_COMPARABLE = "verified_comparable"
    VERIFIED_WITH_DISCLOSED_DIFFERENCES = "verified_with_disclosed_differences"
    INCOMPARABLE = "incomparable"
    MISSING_EVIDENCE = "missing_evidence"
    CHANGED_INPUT = "changed_input"
    CHANGED_OUTPUT = "changed_output"
    FAILED_OR_INCOMPLETE = "failed_or_incomplete"

    @property
    def comparable(self) -> bool:
        return self in (
            IntegrityClass.VERIFIED_COMPARABLE,
            IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES,
        )


class ComparisonKind(str, Enum):
    ONE_VARIABLE = "one_variable"
    MULTI_ARM = "multi_arm"
    CROSS_SUBJECT = "cross_subject"
    #: PR-VID-MOTION-420: the declared spatial alignment is the only intervention.
    ALIGNMENT = "alignment"


INTEGRITY_LABELS = {
    IntegrityClass.VERIFIED_COMPARABLE: "Verified and comparable",
    IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES: "Verified, with disclosed differences",
    IntegrityClass.INCOMPARABLE: "Incomparable",
    IntegrityClass.MISSING_EVIDENCE: "Missing evidence",
    IntegrityClass.CHANGED_INPUT: "Changed input",
    IntegrityClass.CHANGED_OUTPUT: "Changed output",
    IntegrityClass.FAILED_OR_INCOMPLETE: "Failed, cancelled or incomplete",
}
KIND_LABELS = {
    ComparisonKind.ONE_VARIABLE: "One-variable experiment",
    ComparisonKind.MULTI_ARM: "Multi-setting comparison (effects not separable)",
    ComparisonKind.CROSS_SUBJECT: "Cross-subject transfer",
    ComparisonKind.ALIGNMENT: "Spatial alignment comparison",
}

#: Settings that must be identical for two jobs to be compared at all (a different driver, seed or motion prompt is a
#: different experiment, not a configuration of this one).
FIXED_KEYS = ("driver_original_sha256", "seed", "controls.pose_prompt")
#: Settings that may differ but are never hidden: implementation identity, length and rate, and the exact prepared
#: driving derivative (different workflow, version or length is a different preparation contract).
DISCLOSABLE_KEYS = (
    "workflow_id",
    "workflow_version",
    "frame_count",
    "fps",
    "driver_effective_sha256",
    "ordered_frames_sha256",
    "preparation_settings",
    "interpolation",
    "alignment",
    "temporal_plan_sha256",
)
#: What an aligned and an unaligned derivative of the same temporal selection legitimately differ in.
ALIGNMENT_EXPECTED_KEYS = ("alignment", "driver_effective_sha256", "ordered_frames_sha256")
#: Keys that say *which source frames* are consumed; they must not move when only the alignment varies.
TEMPORAL_KEYS = ("temporal_plan_sha256", "preparation_settings")
_FIXED_LABELS = {
    "driver_original_sha256": "driving video",
    "seed": "seed",
    "controls.pose_prompt": "motion prompt",
}
_SEVERITY = (
    IntegrityClass.FAILED_OR_INCOMPLETE,
    IntegrityClass.CHANGED_INPUT,
    IntegrityClass.CHANGED_OUTPUT,
    IntegrityClass.INCOMPARABLE,
    IntegrityClass.MISSING_EVIDENCE,
)


def flatten_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """``controls`` flattened to ``controls.<name>`` so a single declared control is one comparable key."""

    flat: dict[str, Any] = {}
    for key, value in settings.items():
        if key == "controls" and isinstance(value, Mapping):
            flat.update({f"controls.{name}": item for name, item in value.items()})
        else:
            flat[key] = value
    return flat


def differing_keys(base: Mapping[str, Any], cand: Mapping[str, Any]) -> tuple[str, ...]:
    left, right = flatten_settings(base), flatten_settings(cand)
    return tuple(sorted(key for key in {*left, *right} if left.get(key) != right.get(key)))


@dataclass(frozen=True)
class PairIntegrity:
    kind: ComparisonKind
    integrity: IntegrityClass
    #: Settings that differ between the two jobs (the declared variable for a one-variable experiment).
    varied: tuple[str, ...] = ()
    #: Plain statements of every difference that is disclosed rather than excluded.
    disclosed: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def worst(classes: Sequence[IntegrityClass]) -> IntegrityClass | None:
    """The most serious problem among ``classes`` (or ``None`` when every one is comparable)."""

    for candidate in _SEVERITY:
        if candidate in classes:
            return candidate
    return None


def classify_pair(
    base: Mapping[str, Any],
    cand: Mapping[str, Any],
    *,
    cell_problems: Sequence[IntegrityClass] = (),
    problem_reasons: Sequence[str] = (),
) -> PairIntegrity:
    """Classify baseline-versus-candidate from their frozen settings and the two cells' own integrity."""

    varied = differing_keys(base, cand)
    controls = tuple(key for key in varied if key.startswith("controls.") and key not in FIXED_KEYS)
    fixed = tuple(key for key in varied if key in FIXED_KEYS)
    disclosable = tuple(key for key in varied if key in DISCLOSABLE_KEYS)
    other = tuple(key for key in varied if key not in (*controls, *fixed, *disclosable))
    problem = worst(list(cell_problems))
    if problem is not None:
        kind = (
            ComparisonKind.ONE_VARIABLE
            if len(controls) == 1 and not (fixed or disclosable)
            else ComparisonKind.MULTI_ARM
        )
        return PairIntegrity(kind, problem, varied, (), tuple(problem_reasons))
    if fixed or other:
        labels = [_FIXED_LABELS.get(key, key) for key in (*fixed, *other)]
        return PairIntegrity(
            ComparisonKind.MULTI_ARM,
            IntegrityClass.INCOMPARABLE,
            varied,
            (),
            (f"the arms differ in what must stay fixed: {', '.join(labels)}",),
        )
    if "alignment" in varied:
        if any(key in varied for key in TEMPORAL_KEYS):
            return PairIntegrity(
                ComparisonKind.MULTI_ARM,
                IntegrityClass.INCOMPARABLE,
                varied,
                (),
                (
                    "the temporal frame selection differs as well as the spatial alignment, so the "
                    "alignment is not the only intervention",
                ),
            )
        if all(key in ALIGNMENT_EXPECTED_KEYS for key in varied):
            return PairIntegrity(
                ComparisonKind.ALIGNMENT,
                IntegrityClass.VERIFIED_COMPARABLE,
                varied,
                (
                    "only the declared spatial alignment differs: the prepared driving clip differs by "
                    "design, while the original driver, the temporal frame selection, the source image "
                    "and every other setting are identical",
                ),
            )
    if len(controls) == 1 and not disclosable:
        name = controls[0].split(".", 1)[1]
        return PairIntegrity(
            ComparisonKind.ONE_VARIABLE,
            IntegrityClass.VERIFIED_COMPARABLE,
            varied,
            (f"only {name} differs",),
        )
    disclosed: list[str] = []
    if controls:
        names = ", ".join(key.split(".", 1)[1] for key in controls)
        disclosed.append(
            f"{len(controls)} controls differ ({names}); their effects are not separable"
            if len(controls) > 1
            else f"control {names} differs"
        )
    if "workflow_id" in disclosable or "workflow_version" in disclosable:
        disclosed.append(
            "different workflow or version: several implementation differences change together, "
            "so this is not a strict one-variable comparison"
        )
    for key in ("frame_count", "fps", "interpolation"):
        if key in disclosable:
            disclosed.append(f"{key.replace('_', ' ')} differs")
    if "alignment" in disclosable:
        disclosed.append(
            "the spatial alignment differs together with other settings; its effect is not separable"
        )
    if any(
        key in disclosable
        for key in ("driver_effective_sha256", "ordered_frames_sha256", "preparation_settings")
    ):
        disclosed.append(
            "the prepared driving derivative differs (another preparation contract); not identical inputs"
        )
    if not varied:
        return PairIntegrity(
            ComparisonKind.MULTI_ARM,
            IntegrityClass.VERIFIED_COMPARABLE,
            (),
            ("the frozen settings are identical",),
        )
    integrity = (
        IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
        if disclosable or len(controls) > 1
        else IntegrityClass.VERIFIED_COMPARABLE
    )
    return PairIntegrity(ComparisonKind.MULTI_ARM, integrity, varied, tuple(disclosed))


@dataclass(frozen=True)
class GroupIntegrity:
    """One motion evaluated across several source subjects under one arm."""

    integrity: IntegrityClass
    distinct_subjects: int
    disclosed: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    kind: ComparisonKind = ComparisonKind.CROSS_SUBJECT


def classify_group(
    settings_by_case: Mapping[str, Mapping[str, Any]],
    subjects: Mapping[str, str],
    *,
    cell_problems: Sequence[IntegrityClass] = (),
    problem_reasons: Sequence[str] = (),
) -> GroupIntegrity:
    """Cross-subject integrity: the source is the only intended change; motion asset and settings stay fixed."""

    distinct = len({subjects.get(case, case) for case in settings_by_case})
    problem = worst(list(cell_problems))
    if problem is not None:
        return GroupIntegrity(problem, distinct, (), tuple(problem_reasons))
    cases = list(settings_by_case)
    if len(cases) < 2:
        return GroupIntegrity(
            IntegrityClass.MISSING_EVIDENCE,
            distinct,
            (),
            ("fewer than two cases share this motion; no cross-subject comparison exists",),
        )
    first = settings_by_case[cases[0]]
    differing = sorted(
        {key for case in cases[1:] for key in differing_keys(first, settings_by_case[case])}
    )
    fixed = [key for key in differing if key not in DISCLOSABLE_KEYS]
    if fixed:
        return GroupIntegrity(
            IntegrityClass.INCOMPARABLE,
            distinct,
            (),
            (f"settings that must stay fixed across subjects differ: {', '.join(fixed)}",),
        )
    if differing:
        return GroupIntegrity(
            IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES,
            distinct,
            (f"subjects were generated under different {', '.join(differing)}",),
        )
    return GroupIntegrity(IntegrityClass.VERIFIED_COMPARABLE, distinct)


__all__ = [
    "ALIGNMENT_EXPECTED_KEYS",
    "DISCLOSABLE_KEYS",
    "FIXED_KEYS",
    "TEMPORAL_KEYS",
    "INTEGRITY_LABELS",
    "KIND_LABELS",
    "ComparisonKind",
    "GroupIntegrity",
    "IntegrityClass",
    "PairIntegrity",
    "classify_group",
    "classify_pair",
    "differing_keys",
    "flatten_settings",
    "worst",
]
