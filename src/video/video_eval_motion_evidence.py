"""Evidence context of one controlled-motion eval cell (PR-VID-MOTION-410).

For every motion cell this establishes, from recorded facts and the *current* bytes of the bound files, three things:

* what the admitted job really froze (the stored NJR's ``MotionFacts``), checked against the run manifest and the case;
* whether each input is still the one that was frozen (source image, original driver, prepared driving derivative);
* the **driving context digest** that motion judgments are bound to.

A changed driver, derivative or source image changes the digest, so a motion judgment bound to the old digest becomes
*inapplicable* (kept and identifiable, never counted for the new context and never silently reassigned). Hashing is
injected and cancellable by the caller; nothing here decodes a video or writes a file.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.video.video_eval_identity import CellIdentity, Comparability
from src.video.video_eval_motion import (
    MotionFacts,
    as_mapping,
    as_mapping_or_none,
    driving_context_sha256,
)

#: ``path -> sha256`` (``None`` when the file is missing or unreadable). Callers cache and honour cancellation.
Hasher = Callable[[str], str | None]
#: Keys of a manifest job's motion record that describe where things are, not the comparable frozen settings.
_RECORD_ONLY = frozenset(
    {
        "driver_effective_path",
        "driver_original_path",
        "prepared",
        "library_asset",
        "prepared_source_sha256",
        "alignment_detail",
    }
)


@dataclass(frozen=True)
class MotionCellContext:
    case_motion: Mapping[str, Any]
    job_motion: Mapping[str, Any] | None
    facts: MotionFacts | None
    source_sha256: str
    driver_original_current: str | None
    driver_effective_current: str | None
    context_sha256: str | None
    #: Labels of inputs whose current bytes differ from what was frozen.
    changed_inputs: tuple[str, ...] = ()
    #: Labels of inputs that cannot be read now.
    missing_inputs: tuple[str, ...] = ()
    #: The stored NJR or the manifest contradicts what the case bound or what admission froze.
    contradictions: tuple[str, ...] = ()
    #: Facts that could not be established (a stored job that cannot be read, a manifest without them).
    unverified: tuple[str, ...] = ()
    settings: Mapping[str, Any] = field(default_factory=dict)

    @property
    def effective_driver_path(self) -> str | None:
        record = self.job_motion or {}
        return str(record.get("driver_effective_path") or "") or None

    @property
    def prepared(self) -> bool:
        return bool((self.job_motion or {}).get("prepared"))

    @property
    def verified(self) -> bool:
        return not (
            self.changed_inputs or self.missing_inputs or self.contradictions or self.unverified
        )


def build_motion_context(
    case: Mapping[str, Any],
    job: Mapping[str, Any],
    facts: MotionFacts | None,
    *,
    source_sha256: str,
    hasher: Hasher,
) -> MotionCellContext:
    """Verify a motion cell's inputs now against what the case bound, what admission froze and what the NJR recorded."""

    case_motion = as_mapping(case.get("motion"))
    job_motion = as_mapping_or_none(job.get("motion"))
    contradictions: list[str] = []
    unverified: list[str] = []
    changed: list[str] = []
    missing: list[str] = []

    bound = (case_motion.get("driving") or {}) if isinstance(case_motion, Mapping) else {}
    bound_sha = str(bound.get("sha256") or "")
    if job_motion is None:
        unverified.append("the run manifest froze no driving context for this job")
    if facts is None:
        unverified.append("the stored job records no driving context")
    if job_motion is not None and facts is not None:
        for key, value in facts.settings().items():
            if job_motion.get(key) != value:
                contradictions.append(
                    f"the stored job differs from the settings frozen at admission ({key.replace('_', ' ')})"
                )
        if bound_sha and facts.driver_original_sha256 != bound_sha:
            contradictions.append("the stored job used a different driving video than the case")
    settings: Mapping[str, Any] = (
        {key: value for key, value in job_motion.items() if key not in _RECORD_ONLY}
        if job_motion
        else (facts.settings() if facts else {})
    )

    original_current: str | None = None
    effective_current: str | None = None
    if job_motion is not None:
        original_path = str(job_motion.get("driver_original_path") or bound.get("path") or "")
        effective_path = str(job_motion.get("driver_effective_path") or original_path)
        original_frozen = str(job_motion.get("driver_original_sha256") or bound_sha)
        effective_frozen = str(job_motion.get("driver_effective_sha256") or original_frozen)
        original_current = hasher(original_path) if original_path else None
        effective_current = (
            original_current
            if effective_path == original_path
            else (hasher(effective_path) if effective_path else None)
        )
        for label, now, frozen in (
            ("driving video", original_current, original_frozen),
            ("prepared driving video", effective_current, effective_frozen),
        ):
            if label == "prepared driving video" and not job_motion.get("prepared"):
                continue
            if now is None:
                missing.append(label)
            elif frozen and now != frozen:
                changed.append(label)
    if not source_sha256:
        missing.append("source image")

    context: str | None = None
    if (
        job_motion is not None
        and not missing
        and original_current is not None
        and effective_current is not None
    ):
        context = driving_context_sha256(
            source_sha256=source_sha256,
            driver_original_sha256=original_current,
            driver_effective_sha256=effective_current,
            facts_settings=settings,
            motion_prompt=str((settings.get("controls") or {}).get("pose_prompt") or ""),
        )
    return MotionCellContext(
        case_motion=case_motion if isinstance(case_motion, Mapping) else {},
        job_motion=job_motion,
        facts=facts,
        source_sha256=source_sha256,
        driver_original_current=original_current,
        driver_effective_current=effective_current,
        context_sha256=context,
        changed_inputs=tuple(changed),
        missing_inputs=tuple(missing),
        contradictions=tuple(dict.fromkeys(contradictions)),
        unverified=tuple(dict.fromkeys(unverified)),
        settings=dict(settings),
    )


def merge_motion_identity(identity: CellIdentity, ctx: MotionCellContext | None) -> CellIdentity:
    """Fold a motion cell's input and freeze findings into its ordinary cell identity (unchanged for other cells)."""

    if ctx is None:
        return identity
    contradictions = [
        *ctx.contradictions,
        *(f"the {label} changed since admission" for label in ctx.changed_inputs),
    ]
    unverified = [*ctx.unverified, *(f"the {label} is unavailable" for label in ctx.missing_inputs)]
    if contradictions:
        return CellIdentity(
            Comparability.INCOMPARABLE, (*identity.findings, *contradictions, *unverified)
        )
    if unverified and identity.status is Comparability.VERIFIED:
        return CellIdentity(Comparability.NOT_FULLY_VERIFIED, tuple(unverified))
    if unverified:
        return CellIdentity(identity.status, (*identity.findings, *unverified))
    return identity


__all__ = ["Hasher", "MotionCellContext", "build_motion_context", "merge_motion_identity"]
