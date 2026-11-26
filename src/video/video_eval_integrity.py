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

from src.video.workflow_conditioning import registered_contracts, takes_motion_prompt


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
    #: PR-VID-MOTION-430: two registered workflows (engines) were compared; several implementation differences change
    #: together (conditioning mechanism, controls, noise semantics, preparation contract), so it is never one variable.
    MULTI_ENGINE = "multi_engine"
    #: PR-VID-MOTION-430: the driving representation (character / silhouette / skeleton) of one verified movement is the
    #: intended difference between cases that share a source image, engine and settings.
    REPRESENTATION = "representation"


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
    ComparisonKind.MULTI_ENGINE: "Multi-engine comparison (effects not separable)",
    ComparisonKind.REPRESENTATION: "Driving-representation comparison",
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


def _engine_name(settings: Mapping[str, Any]) -> str:
    return f"{settings.get('workflow_id') or '?'}@{settings.get('workflow_version') or '?'}"


def engine_disclosures(base: Mapping[str, Any], cand: Mapping[str, Any]) -> list[str]:
    """Plain statements of what changes together when the two jobs ran on different engines (workflow ids)."""

    left, right = flatten_settings(base), flatten_settings(cand)
    notes = [
        f"different engines ({_engine_name(base)} vs {_engine_name(cand)}): several implementation differences change "
        "together, so this is a multi-engine comparison, not a one-variable experiment",
    ]
    contracts = registered_contracts()
    a = contracts.get((str(base.get("workflow_id")), str(base.get("workflow_version"))))
    b = contracts.get((str(cand.get("workflow_id")), str(cand.get("workflow_version"))))
    if a is not None and b is not None:
        if a.mechanism != b.mechanism:
            notes.append(f"conditioning differs: {a.mechanism_label} vs {b.mechanism_label}")
        if left.get("frame_count") is not None and right.get("frame_count") is not None:
            from src.video.workflow_conditioning import envelope_problem, shared_envelope

            envelope = shared_envelope([a, b])
            for label, settings in (("baseline", base), ("candidate", cand)):
                problem = envelope_problem(envelope, settings.get("frame_count"), label=label)
                if problem:
                    notes.append(problem)
    notes.append(
        "the same seed value does not give equivalent noise or conditioning across different architectures"
    )
    if _engine_specific_prompt(base, cand, differing_keys(base, cand)):
        notes.append(
            "one engine takes no separate motion prompt: the case's motion prompt was sent only to the engine that "
            "declares that control, and the other engine is driven by the driving clip and the main prompt"
        )
    own = sorted(
        key.split(".", 1)[1]
        for key in {*left, *right}
        if key.startswith("controls.") and key not in FIXED_KEYS and left.get(key) != right.get(key)
    )
    if own:
        notes.append(
            f"engine-specific controls differ ({', '.join(own)}); none was dropped or reinterpreted"
        )
    return notes


PROMPT_KEY = "controls.pose_prompt"


def _engine_specific_prompt(
    base: Mapping[str, Any], cand: Mapping[str, Any], varied: Sequence[str]
) -> bool:
    """True when the motion prompt differs only because one engine takes no separate motion prompt at all.

    Both sides carrying a (different) prompt stays incomparable; the case's prompt is never forced into an engine that
    declares no such control."""

    if PROMPT_KEY not in varied or base.get("workflow_id") == cand.get("workflow_id"):
        return False
    left, right = flatten_settings(base), flatten_settings(cand)
    one_missing = (left.get(PROMPT_KEY) in (None, "")) != (right.get(PROMPT_KEY) in (None, ""))
    absent_side = base if left.get(PROMPT_KEY) in (None, "") else cand
    return one_missing and not takes_motion_prompt(
        str(absent_side.get("workflow_id")), str(absent_side.get("workflow_version"))
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
    engine_prompt = _engine_specific_prompt(base, cand, varied)
    controls = tuple(key for key in varied if key.startswith("controls.") and key not in FIXED_KEYS)
    fixed = tuple(
        key for key in varied if key in FIXED_KEYS and not (engine_prompt and key == PROMPT_KEY)
    )
    disclosable = tuple(key for key in varied if key in DISCLOSABLE_KEYS)
    other = tuple(
        key
        for key in varied
        if key not in (*controls, *fixed, *disclosable)
        and not (engine_prompt and key == PROMPT_KEY)
    )
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
    engine_change = "workflow_id" in disclosable
    if engine_change:
        disclosed.extend(engine_disclosures(base, cand))
    elif "workflow_id" in disclosable or "workflow_version" in disclosable:
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
    return PairIntegrity(
        ComparisonKind.MULTI_ENGINE if engine_change else ComparisonKind.MULTI_ARM,
        integrity,
        varied,
        tuple(disclosed),
    )


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


#: Settings that must be identical across the cases of a driving-representation comparison (the engine, its controls, the
#: length and the seed); only the driver derivative and what depends on its bytes may differ.
REPRESENTATION_FIXED_KEYS = (
    "workflow_id",
    "workflow_version",
    "frame_count",
    "fps",
    "seed",
    "interpolation",
)
REPRESENTATION_EXPECTED_KEYS = (
    "driver_original_sha256",
    "driver_effective_sha256",
    "ordered_frames_sha256",
    "preparation_settings",
    "temporal_plan_sha256",
    "alignment",
)


def classify_representation_group(
    settings_by_case: Mapping[str, Mapping[str, Any]],
    representations: Mapping[str, Mapping[str, Any] | None],
    subjects: Mapping[str, str],
    *,
    cell_problems: Sequence[IntegrityClass] = (),
    problem_reasons: Sequence[str] = (),
) -> GroupIntegrity:
    """Cases that share a source image, engine and settings and differ in the driving representation of one movement.

    ``representations`` maps each case to the verified ``representation`` block of its library binding (``None`` for a local
    video or an unverified clip).  A relationship that is not verified is never a controlled comparison."""

    distinct = len({subjects.get(case, case) for case in settings_by_case})

    def result(
        integrity: IntegrityClass, disclosed: Sequence[str] = (), reasons: Sequence[str] = ()
    ) -> GroupIntegrity:
        return GroupIntegrity(
            integrity, distinct, tuple(disclosed), tuple(reasons), ComparisonKind.REPRESENTATION
        )

    problem = worst(list(cell_problems))
    if problem is not None:
        return result(problem, reasons=problem_reasons)
    cases = list(settings_by_case)
    if len(cases) < 2:
        return result(
            IntegrityClass.MISSING_EVIDENCE,
            reasons=("fewer than two cases; no representation comparison exists",),
        )
    blocks = {case: representations.get(case) for case in cases}
    if any(not block for block in blocks.values()):
        return result(
            IntegrityClass.MISSING_EVIDENCE,
            reasons=(
                "not every driver is a verified representation of a library movement; the comparison is "
                "exploratory (for example unrelated footage against a skeleton render)",
            ),
        )
    kinds = {str(b.get("representation")) for b in blocks.values() if b}
    if len(kinds) < 2:
        return result(
            IntegrityClass.MISSING_EVIDENCE,
            reasons=("every case uses the same driving representation",),
        )
    if len({str(b.get("movement_key")) for b in blocks.values() if b}) != 1:
        return result(
            IntegrityClass.INCOMPARABLE,
            reasons=(
                "the drivers were not rendered from the same movement under identical parameters",
            ),
        )
    if distinct != 1:
        return result(
            IntegrityClass.INCOMPARABLE,
            reasons=(
                "the source image differs between cases; it must stay fixed in a representation comparison",
            ),
        )
    first = settings_by_case[cases[0]]
    differing = sorted(
        {key for case in cases[1:] for key in differing_keys(first, settings_by_case[case])}
    )
    broken = [k for k in differing if k in REPRESENTATION_FIXED_KEYS or k.startswith("controls.")]
    other = [k for k in differing if k not in broken and k not in REPRESENTATION_EXPECTED_KEYS]
    if broken or other:
        return result(
            IntegrityClass.INCOMPARABLE,
            reasons=(f"settings that must stay fixed differ: {', '.join([*broken, *other])}",),
        )
    disclosed = [
        "the driving representation differs by design; each driver is its own verified derivative of one movement"
    ]
    if "alignment" in differing:
        disclosed.append(
            "the spatial alignment differs between cases; that is an additional intervention, not a pure "
            "representation effect"
        )
    if "preparation_settings" in differing or "temporal_plan_sha256" in differing:
        disclosed.append("the frame selection or preparation settings differ between drivers")
    return result(
        IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
        if len(disclosed) > 1
        else IntegrityClass.VERIFIED_COMPARABLE,
        disclosed,
    )


__all__ = [
    "REPRESENTATION_EXPECTED_KEYS",
    "REPRESENTATION_FIXED_KEYS",
    "classify_representation_group",
    "engine_disclosures",
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
