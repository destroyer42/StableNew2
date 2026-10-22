"""Freeze a native-SVD sequence plan (PR-VID-SEQ-330-CORE).

Native SVD segments share one model and one configuration; only each segment's seed and frame count differ. The plan
plays at the cadence the first segment's config exports at (RIFE multiplies it), and a loop or ping-pong export is
refused because it changes what "a segment's frames" means.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.video.sequence_admission import freeze_sequence_plan, sha256_file
from src.video.sequence_plan import STAGE_SVD_NATIVE, SequencePlan, SequencePlanError
from src.video.svd_config import SVDConfig
from src.video.svd_models import resolve_svd_model_spec


def svd_sequence_fps(config: SVDConfig) -> int:
    """The frame rate every segment's exported frames play at."""

    base = int(config.inference.fps)
    if config.postprocess.interpolation.enabled:
        return base * int(config.postprocess.interpolation.multiplier)
    return base


def freeze_svd_sequence_plan(
    intent: Mapping[str, Any],
    *,
    config: SVDConfig,
    source_image_path: str | Path | None = None,
    continuity: Mapping[str, Any] | None = None,
    plan_origin: Mapping[str, Any] | None = None,
) -> SequencePlan:
    """The frozen plan for ``intent`` over the already-prepared ``config`` (a concrete seed, a legal frame count).

    ``source_image_path`` is the exact image segment 0 starts from; it is hashed so a change before dispatch is caught."""

    if config.output.loop_mode != "none" or float(config.output.extend_to_seconds) > 0:
        raise SequencePlanError(
            "a loop or ping-pong export changes a segment's frames; turn it off for a sequence"
        )
    spec = resolve_svd_model_spec(config.inference.model_id)
    return freeze_sequence_plan(
        intent,
        stage=STAGE_SVD_NATIVE,
        fps=svd_sequence_fps(config),
        svd_max_frames=int(spec.max_num_frames),
        segment_zero_seed=config.inference.seed,
        model_id=str(config.inference.model_id),
        source=None
        if source_image_path is None
        else {"path": str(source_image_path), "sha256": sha256_file(source_image_path)},
        continuity=continuity,
        plan_origin=plan_origin,
    )


__all__ = ["freeze_svd_sequence_plan", "svd_sequence_fps"]
