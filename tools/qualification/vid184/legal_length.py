"""PR-VID-184: legal Wan latent-length handling.

Wan's causal 3D VAE (`comfy/ldm/wan/vae.py`, `WanVAE.encode`, Comfy-Org/ComfyUI, verified directly)
floors any pixel-frame input count down to the nearest `4n+1` value before encoding::

    t = 1 + ((t - 1) // 4) * 4

This runs on **every** `vae.encode()` call `WanAnimate2ToVideo.execute()` makes -- both the
placeholder canvas latent (`vae.encode(image[:, :, :, :3])`, `image` shaped `[length, H, W, 3]`)
and the pose_video driving-conditioning latent (`vae.encode(pose_video[:, :, :, :3])`, also shaped
`[length, H, W, 3]` after the node's own truncate/pad step). Passing a non-`4n+1` `length` silently
drops trailing real driving frames during this internal encode -- a materially different, more
severe problem than the already-documented truncate/pad behavior for `length` vs. driving-frame-
count mismatches (that mismatch is intentional and harmless; this one is an unannounced frame loss).

`WanAnimate2ToVideo`'s own `length` input has no such floor or validation (confirmed from its
`io.Int.Input` schema and `execute()` body) -- it will happily accept and run with an illegal
length, silently losing frames rather than erroring.

This module computes the smallest legal (`4n+1`) generation length that covers a given frozen
evidence-frame count, and trims a decoded output back down to that evidence count post-hoc --
qualification-only handling equivalent in semantics to the official reference workflow (which
always uses default `4n+1` lengths such as 81 and so never hits this edge case), not a ComfyUI
graph change.
"""

from __future__ import annotations

from collections.abc import Sequence


def is_legal_wan_length(length: int) -> bool:
    """True if `length` is already of the form 4n+1 and survives WanVAE.encode's floor unchanged."""

    if length < 1:
        raise ValueError("length must be positive")
    return (length - 1) % 4 == 0


def smallest_legal_wan_length(evidence_frames: int) -> int:
    """Smallest 4n+1 >= evidence_frames -- the internal generation `length` to request so the
    frozen evidence window survives WanVAE.encode's floor with zero frames dropped."""

    if evidence_frames < 1:
        raise ValueError("evidence_frames must be positive")
    if is_legal_wan_length(evidence_frames):
        return evidence_frames
    return 1 + 4 * (((evidence_frames - 1) // 4) + 1)


def trim_to_evidence_window[T](frames: Sequence[T], evidence_frames: int) -> list[T]:
    """Trim a decoded output (or any frame sequence) from the internal legal length back down to
    the frozen evidence-frame count. Drops only trailing frames -- exactly where the node's own
    documented hold-last-frame padding was appended to reach the legal length -- and never touches
    the leading evidence frames, reorders them, or resamples/interpolates between them."""

    if len(frames) < evidence_frames:
        raise ValueError(
            f"cannot trim {len(frames)} frames down to {evidence_frames}: "
            "fewer frames than the evidence window"
        )
    return list(frames[:evidence_frames])


__all__ = ["is_legal_wan_length", "smallest_legal_wan_length", "trim_to_evidence_window"]
