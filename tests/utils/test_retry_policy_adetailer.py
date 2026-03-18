"""
PR-HARDEN-006: Tests verifying ADETAILER_RETRY_POLICY is registered and fail-fast.
"""

from src.utils.retry_policy_v2 import (
    ADETAILER_RETRY_POLICY,
    IMG2IMG_RETRY_POLICY,
    STAGE_RETRY_POLICY,
)


def test_adetailer_policy_registered_in_stage_map() -> None:
    """ADETAILER_RETRY_POLICY must be present in STAGE_RETRY_POLICY keyed as 'adetailer'."""
    assert "adetailer" in STAGE_RETRY_POLICY
    assert STAGE_RETRY_POLICY["adetailer"] is ADETAILER_RETRY_POLICY


def test_adetailer_policy_is_fail_fast() -> None:
    """ADETAILER_RETRY_POLICY must have max_attempts=1 (no retries)."""
    assert ADETAILER_RETRY_POLICY.max_attempts == 1


def test_adetailer_policy_does_not_affect_img2img_policy() -> None:
    """IMG2IMG_RETRY_POLICY must remain independent of ADETAILER_RETRY_POLICY."""
    assert ADETAILER_RETRY_POLICY is not IMG2IMG_RETRY_POLICY
    assert IMG2IMG_RETRY_POLICY.max_attempts != 1 or IMG2IMG_RETRY_POLICY is not ADETAILER_RETRY_POLICY


def test_adetailer_policy_zero_delay() -> None:
    """Zero delay/jitter so the single attempt fires immediately on first ADetailer call."""
    assert ADETAILER_RETRY_POLICY.base_delay_sec == 0.0
    assert ADETAILER_RETRY_POLICY.max_delay_sec == 0.0
    assert ADETAILER_RETRY_POLICY.jitter_frac == 0.0
