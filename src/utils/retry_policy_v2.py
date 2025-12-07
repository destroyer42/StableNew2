"""Retry policy definitions for StableNew WebUI interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BackoffStrategy = Literal["fixed", "exponential", "jitter"]


@dataclass(frozen=True)
class RetryPolicy:
    """Retry configuration for WebUI/API calls."""

    max_attempts: int = 1
    backoff_strategy: BackoffStrategy = "fixed"
    base_delay_sec: float = 0.5
    max_delay_sec: float = 30.0
    jitter_frac: float = 0.0  # default to no jitter for deterministic tests

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 1


TXT2IMG_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    backoff_strategy="exponential",
    base_delay_sec=1.0,
    max_delay_sec=20.0,
    jitter_frac=0.5,
)

IMG2IMG_RETRY_POLICY = RetryPolicy(
    max_attempts=2,
    backoff_strategy="exponential",
    base_delay_sec=1.5,
    max_delay_sec=25.0,
    jitter_frac=0.4,
)

UPSCALE_RETRY_POLICY = RetryPolicy(
    max_attempts=2,
    backoff_strategy="fixed",
    base_delay_sec=2.0,
    max_delay_sec=10.0,
    jitter_frac=0.25,
)

STAGE_RETRY_POLICY: dict[str, RetryPolicy] = {
    "txt2img": TXT2IMG_RETRY_POLICY,
    "img2img": IMG2IMG_RETRY_POLICY,
    "upscale": UPSCALE_RETRY_POLICY,
    "upscale_image": UPSCALE_RETRY_POLICY,
}
