"""PR-VID-184 pre-registered scoring contract.

This freezes the evaluation plan for the Wan-Animate-2 reference-capability gate
(Phase C) *before* any Animate-2 output is generated. Pure stdlib only:
importable from the StableNew ``.venv`` for deterministic tests. It defines
what will be measured and the pass/fail thresholds; it deliberately does not
implement detector-dependent metrics (primary-subject continuity, ghost-actor
tracking), which require the disposable CPU-only detector environment used by
``tools/qualification/vid181/`` and are out of scope until Phase D/E execution
is separately authorized.

Threshold anchors are taken from already-accepted PR-VID-181/183 evidence
(see ``docs/Subsystems/Video/PR-VID-181_...md`` and
``docs/Subsystems/Video/PR-VID-183_...md``), not invented:

- ``motion_curve_correlation``: PR-VID-181 Case A (accepted gesture transfer)
  measured 0.419; Case B (accepted locomotion failure, planted subject) measured
  -0.132; the synthetic-control noise floor (PR-VID-180) measured -0.089 to
  0.005. A pass threshold of 0.30 sits clearly above the noise floor and at the
  accepted-pass anchor; a value at or below 0.10 is within the documented
  noise floor and is treated as non-adherent.
- ``root_translation_fraction``: PR-VID-181's own driving-control centroid
  moved 0.29 -> 0.69 of frame width (a fraction of 0.40); the accepted failure
  case produced an effectively planted subject (fraction ~= 0). A minimum
  fraction of 0.15 is set well above zero and well below the documented
  control signal, so it cannot be satisfied by a planted subject while still
  being achievable by partial, imperfect locomotion transfer.
- ``camera_drift_px`` / ``motion_area_fraction``: PR-VID-181 records these as
  *corroborating only* -- its own text states background hallucination
  contaminates optical flow, and the accepted background-instability finding
  (``BACKGROUND_INSTABILITY_CROSS_CASE``) was reached by direct visual
  inspection, not by this proxy. No pass/fail gate is set on these; they are
  recorded for trend comparison only.
- ``identity_hist_mean``: PR-VID-181 treats this explicitly as corroboration,
  not sole truth. No independent gate is set here either.

Metrics tagged ``requires_detector_env=True`` need the disposable CPU-only
person-detector environment (see ``tools/qualification/vid181/preprocess_launcher.py``)
and are not executable from the StableNew ``.venv``; their thresholds are
still frozen here so they cannot be tuned after seeing results.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

CONTRACT_VERSION = "PR-VID-184.v1"

MOTION_CURVE_CORRELATION_PASS = 0.30
MOTION_CURVE_CORRELATION_NOISE_FLOOR = 0.10
ROOT_TRANSLATION_FRACTION_PASS = 0.15
ROOT_TRANSLATION_DIRECTION_MUST_MATCH = True
GHOST_ACTOR_MAX_PERSISTENT_FRAMES = (
    2  # a distinct second track present in >2 consecutive frames fails
)
PRIMARY_SUBJECT_MIN_TRACK_COVERAGE = (
    0.90  # fraction of frames with the reference-matched track present
)


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    description: str
    gate: str  # "pass_fail", "corroborating_only", or "manual_rubric"
    threshold: float | int | bool | None
    anchor: str
    requires_detector_env: bool
    source: str  # "reused" (existing tool) or "new"


PRIMARY_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        name="primary_subject_continuity",
        description=(
            "Fraction of output frames in which a person-track matching the reference "
            "identity is present and spatially coherent frame-to-frame."
        ),
        gate="pass_fail",
        threshold=PRIMARY_SUBJECT_MIN_TRACK_COVERAGE,
        anchor="New metric; no prior PR-181/183 numeric anchor. Threshold set high "
        "because a planted-but-present subject (the documented PR-181 Case B failure "
        "mode) still satisfies mere presence -- this metric alone cannot detect "
        "planted subjects and must be read together with root_translation_fraction.",
        requires_detector_env=True,
        source="new",
    ),
    MetricSpec(
        name="ghost_actor_persistence",
        description=(
            "Maximum number of consecutive frames containing a second, non-reference "
            "person track distinct from the primary subject."
        ),
        gate="pass_fail",
        threshold=GHOST_ACTOR_MAX_PERSISTENT_FRAMES,
        anchor="PR-VID-181 Case B and PR-VID-180 A/B documented a persistent second "
        "'ghost' figure performing the driven motion while the reference subject stayed "
        "planted; a value at or below 2 consecutive frames is treated as transient/"
        "noise rather than a real second actor.",
        requires_detector_env=True,
        source="new",
    ),
    MetricSpec(
        name="root_translation_fraction",
        description=(
            "Normalized reference-subject centroid displacement across the clip, as a "
            "fraction of frame width, direction-matched against the driving control."
        ),
        gate="pass_fail",
        threshold=ROOT_TRANSLATION_FRACTION_PASS,
        anchor="PR-VID-181's own driving control moved 0.40 of frame width; the "
        "accepted failure case (planted subject) produced ~0 displacement. 0.15 is set "
        "above zero/noise and below the full control signal.",
        requires_detector_env=True,
        source="new",
    ),
    MetricSpec(
        name="motion_curve_correlation",
        description="Correlation between control motion-energy curve and output motion-energy curve.",
        gate="pass_fail",
        threshold=MOTION_CURVE_CORRELATION_PASS,
        anchor="PR-VID-181 Case A (accepted pass) = 0.419; Case B (accepted fail) = "
        "-0.132; synthetic noise floor (PR-VID-180) = -0.089 to 0.005.",
        requires_detector_env=False,
        source="reused",  # tools/qualification/vid110/metrics.py: motion_curve + curve_correlation
    ),
    MetricSpec(
        name="identity_hist_mean",
        description="Framewise HSV-histogram similarity to the reference image.",
        gate="corroborating_only",
        threshold=None,
        anchor="PR-VID-181 treats this explicitly as corroboration, not sole truth; no "
        "independent pass/fail anchor exists in accepted evidence.",
        requires_detector_env=False,
        source="reused",  # tools/qualification/vid110/metrics.py: clip_metrics
    ),
    MetricSpec(
        name="camera_drift_px",
        description="Optical-flow-based background/camera drift proxy.",
        gate="corroborating_only",
        threshold=None,
        anchor="PR-VID-181 states background hallucination contaminates optical flow; "
        "the accepted BACKGROUND_INSTABILITY_CROSS_CASE finding was reached by direct "
        "visual inspection, not this proxy.",
        requires_detector_env=False,
        source="reused",  # tools/qualification/vid110/metrics.py: clip_metrics
    ),
    MetricSpec(
        name="motion_area_fraction",
        description="Fraction of frame area with detected motion (optical-flow proxy).",
        gate="corroborating_only",
        threshold=None,
        anchor="Same corroborating-only status as camera_drift_px.",
        requires_detector_env=False,
        source="reused",  # tools/qualification/vid110/metrics.py: clip_metrics
    ),
    MetricSpec(
        name="human_visual_rubric",
        description=(
            "Raw 1-5 human ratings for identity, anatomy, limb/foot progression, "
            "subject-bound motion, root translation, ghost actors, background "
            "stability, and overall usefulness -- not averaged, per PR-VID-181/183 "
            "convention."
        ),
        gate="manual_rubric",
        threshold=None,
        anchor="Same rubric structure and 1-5 raw-score convention as PR-VID-181/183.",
        requires_detector_env=False,
        source="reused",
    ),
)


def _canonical_payload() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "metrics": [asdict(metric) for metric in PRIMARY_METRICS],
    }


def contract_sha256() -> str:
    """Deterministic SHA-256 of the frozen contract, for post-hoc-mutation detection."""

    canonical = json.dumps(_canonical_payload(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Frozen at authoring time. A test asserts this still matches contract_sha256();
# any edit to PRIMARY_METRICS/CONTRACT_VERSION after this point must update this
# constant deliberately, in a reviewed commit, not silently.
FROZEN_CONTRACT_SHA256 = "30608f7a3595d5db000946fbb4941918fdf6dd09cdf8fa1387a7953ed706543c"


def verify_contract_unchanged() -> None:
    """Raise if the contract was edited after being frozen (post-hoc-mutation guard)."""

    actual = contract_sha256()
    if actual != FROZEN_CONTRACT_SHA256:
        raise RuntimeError(
            "PR-VID-184 scoring contract hash mismatch: expected "
            f"{FROZEN_CONTRACT_SHA256}, got {actual}. If this change is deliberate and "
            "reviewed, update FROZEN_CONTRACT_SHA256; do not silently accept a drifted "
            "contract before Animate-2 outputs have been scored."
        )


__all__ = [
    "CONTRACT_VERSION",
    "FROZEN_CONTRACT_SHA256",
    "GHOST_ACTOR_MAX_PERSISTENT_FRAMES",
    "MOTION_CURVE_CORRELATION_NOISE_FLOOR",
    "MOTION_CURVE_CORRELATION_PASS",
    "PRIMARY_METRICS",
    "PRIMARY_SUBJECT_MIN_TRACK_COVERAGE",
    "ROOT_TRANSLATION_DIRECTION_MUST_MATCH",
    "ROOT_TRANSLATION_FRACTION_PASS",
    "MetricSpec",
    "contract_sha256",
    "verify_contract_unchanged",
]
