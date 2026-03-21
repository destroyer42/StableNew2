from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from PIL import Image

from .secondary_motion_models import SecondaryMotionIntent, SecondaryMotionPolicy


SECONDARY_MOTION_APPLY_SCHEMA_V1 = "stablenew.secondary-motion-apply.v1"


@dataclass(frozen=True, slots=True)
class SecondaryMotionApplyResult:
    schema: str = SECONDARY_MOTION_APPLY_SCHEMA_V1
    status: str = "disabled"
    policy_id: str = ""
    application_path: str = "shared_postprocess_engine"
    backend_mode: str = "disabled"
    frames_in: int = 0
    frames_out: int = 0
    seed: int | None = None
    regions_applied: tuple[str, ...] = ()
    skip_reason: str = ""
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "policy_id": self.policy_id,
            "application_path": self.application_path,
            "backend_mode": self.backend_mode,
            "frames_in": self.frames_in,
            "frames_out": self.frames_out,
            "seed": self.seed,
            "regions_applied": list(self.regions_applied),
            "skip_reason": self.skip_reason,
            "metrics": dict(self.metrics or {}),
        }


def _derive_seed(seed: int | None, policy: SecondaryMotionPolicy) -> int:
    if seed is not None:
        return int(seed)
    digest = hashlib.sha256(policy.policy_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _resolve_application_path(policy: SecondaryMotionPolicy) -> str:
    if "native" in str(policy.backend_mode or ""):
        return "native_candidate"
    return "shared_postprocess_engine"


def _compute_offsets(
    *,
    index: int,
    seed: int,
    policy: SecondaryMotionPolicy,
) -> tuple[int, int]:
    cap = max(0, int(policy.cap_pixels))
    if cap <= 0:
        return 0, 0
    amplitude = min(float(cap), max(0.0, float(cap) * float(policy.intensity)))
    amplitude *= max(0.0, min(1.0, float(policy.damping))) ** max(0, index)
    phase = ((seed % 360) + index + 1) * max(0.05, float(policy.frequency_hz) or 0.05)
    dx = int(round(math.sin(phase) * amplitude))
    dy = int(round(math.cos(phase * 0.5) * min(amplitude * 0.35, cap)))
    return max(-cap, min(cap, dx)), max(-cap, min(cap, dy))


def _translate_frame(frame: Image.Image, dx: int, dy: int) -> Image.Image:
    rgba = frame.convert("RGBA")
    shifted = rgba.transform(
        rgba.size,
        Image.AFFINE,
        (1, 0, -dx, 0, 1, -dy),
        resample=Image.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    return shifted.convert(frame.mode if frame.mode else "RGBA")


def apply_secondary_motion_to_frames(
    frames: list[Image.Image],
    *,
    policy: SecondaryMotionPolicy,
    intent: SecondaryMotionIntent | None = None,
    seed: int | None = None,
) -> tuple[list[Image.Image], SecondaryMotionApplyResult]:
    motion_intent = intent or SecondaryMotionIntent()
    frames_in = len(frames)
    resolved_seed = _derive_seed(seed if seed is not None else motion_intent.seed, policy)
    regions = tuple(motion_intent.regions)
    application_path = _resolve_application_path(policy)

    if frames_in <= 0:
        return [], SecondaryMotionApplyResult(
            status="not_applicable",
            policy_id=policy.policy_id,
            application_path=application_path,
            backend_mode=policy.backend_mode,
            frames_in=0,
            frames_out=0,
            seed=resolved_seed,
            regions_applied=regions,
            skip_reason="no_frames",
            metrics={"applied_frame_count": 0},
        )

    if not policy.enabled:
        return [frame.copy() for frame in frames], SecondaryMotionApplyResult(
            status="disabled",
            policy_id=policy.policy_id,
            application_path=application_path,
            backend_mode=policy.backend_mode,
            frames_in=frames_in,
            frames_out=frames_in,
            seed=resolved_seed,
            regions_applied=regions,
            skip_reason="policy_disabled",
            metrics={"applied_frame_count": 0},
        )

    if str(policy.backend_mode or "").startswith("observe"):
        return [frame.copy() for frame in frames], SecondaryMotionApplyResult(
            status="observe",
            policy_id=policy.policy_id,
            application_path="policy_observation_only",
            backend_mode=policy.backend_mode,
            frames_in=frames_in,
            frames_out=frames_in,
            seed=resolved_seed,
            regions_applied=regions,
            skip_reason="observe_only",
            metrics={"applied_frame_count": 0},
        )

    if float(policy.intensity) <= 0.0 or int(policy.cap_pixels) <= 0:
        return [frame.copy() for frame in frames], SecondaryMotionApplyResult(
            status="not_applicable",
            policy_id=policy.policy_id,
            application_path=application_path,
            backend_mode=policy.backend_mode,
            frames_in=frames_in,
            frames_out=frames_in,
            seed=resolved_seed,
            regions_applied=regions,
            skip_reason="zero_effect",
            metrics={"applied_frame_count": 0},
        )

    output_frames: list[Image.Image] = []
    dx_values: list[int] = []
    dy_values: list[int] = []
    for index, frame in enumerate(frames):
        dx, dy = _compute_offsets(index=index, seed=resolved_seed, policy=policy)
        dx_values.append(dx)
        dy_values.append(dy)
        output_frames.append(_translate_frame(frame, dx, dy))

    applied_count = sum(1 for dx, dy in zip(dx_values, dy_values) if dx or dy)
    metrics = {
        "applied_frame_count": applied_count,
        "avg_abs_dx": round(sum(abs(dx) for dx in dx_values) / max(1, frames_in), 4),
        "avg_abs_dy": round(sum(abs(dy) for dy in dy_values) / max(1, frames_in), 4),
        "max_abs_dx": max(abs(dx) for dx in dx_values) if dx_values else 0,
        "max_abs_dy": max(abs(dy) for dy in dy_values) if dy_values else 0,
        "intensity": round(float(policy.intensity), 4),
        "damping": round(float(policy.damping), 4),
        "frequency_hz": round(float(policy.frequency_hz), 4),
        "cap_pixels": int(policy.cap_pixels),
    }
    return output_frames, SecondaryMotionApplyResult(
        status="applied",
        policy_id=policy.policy_id,
        application_path=application_path,
        backend_mode=policy.backend_mode,
        frames_in=frames_in,
        frames_out=len(output_frames),
        seed=resolved_seed,
        regions_applied=regions,
        skip_reason="",
        metrics=metrics,
    )


__all__ = [
    "SECONDARY_MOTION_APPLY_SCHEMA_V1",
    "SecondaryMotionApplyResult",
    "apply_secondary_motion_to_frames",
]
