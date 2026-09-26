"""PR-VID-184 Phase C: the pre-registered scoring contract is frozen before any Animate-2 output
exists. No GPU, no ONNX inference, no network, no real Comfy -- pure stdlib hashing/structure
checks only."""

from __future__ import annotations

from tools.qualification.vid184 import scoring_contract as sc


def test_contract_hash_matches_frozen_constant() -> None:
    # Detects any post-hoc edit to PRIMARY_METRICS/CONTRACT_VERSION made after the contract was
    # frozen (Phase C requires the thresholds exist *before* any Animate-2 output is scored).
    assert sc.contract_sha256() == sc.FROZEN_CONTRACT_SHA256
    sc.verify_contract_unchanged()  # must not raise


def test_pass_fail_metrics_declare_a_numeric_or_bool_threshold() -> None:
    for metric in sc.PRIMARY_METRICS:
        if metric.gate == "pass_fail":
            assert metric.threshold is not None, metric.name


def test_corroborating_and_manual_metrics_declare_no_gate_threshold() -> None:
    for metric in sc.PRIMARY_METRICS:
        if metric.gate in ("corroborating_only", "manual_rubric"):
            assert metric.threshold is None, metric.name


def test_every_metric_has_a_cited_anchor() -> None:
    for metric in sc.PRIMARY_METRICS:
        assert metric.anchor.strip(), metric.name


def test_metric_names_are_unique() -> None:
    names = [metric.name for metric in sc.PRIMARY_METRICS]
    assert len(names) == len(set(names))


def test_reused_metrics_are_flagged_as_such_and_not_detector_dependent() -> None:
    # motion_curve_correlation / identity_hist_mean / camera_drift_px / motion_area_fraction are
    # already implemented in tools/qualification/vid110/metrics.py and run without a person
    # detector; only the *new* metrics need the disposable CPU-only detector environment.
    reused = {m.name: m for m in sc.PRIMARY_METRICS if m.source == "reused"}
    assert reused, "expected at least one reused metric"
    for metric in reused.values():
        if metric.name != "human_visual_rubric":
            assert metric.requires_detector_env is False, metric.name


def test_root_translation_threshold_sits_strictly_between_noise_and_control_signal() -> None:
    # Anchored to PR-VID-181: documented failure case ~= 0 displacement; the driving control's own
    # centroid motion was 0.40 of frame width. The pass threshold must be strictly inside that band.
    assert 0.0 < sc.ROOT_TRANSLATION_FRACTION_PASS < 0.40


def test_motion_curve_correlation_pass_threshold_exceeds_documented_noise_floor() -> None:
    # Anchored to PR-VID-181/180: synthetic-control noise floor measured -0.089 to 0.005.
    assert sc.MOTION_CURVE_CORRELATION_PASS > sc.MOTION_CURVE_CORRELATION_NOISE_FLOOR
    assert sc.MOTION_CURVE_CORRELATION_NOISE_FLOOR > 0.0
