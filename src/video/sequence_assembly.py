"""Assemble a sequence's frames into one movie with the ASM-332 engine, inside the sequence job (PR-VID-SEQ-330-CORE).

No second job and no second encoder: the frames of every segment, in segment order with each later segment's overlap
frames dropped, are frozen as an ASM-332 *frame sequence* (``MODE_SEQUENCE``: every image is exactly one frame) and
``run_movie_assembly`` encodes them with the shared BT.709 chain and ``VideoEncodeSettings``. The engine re-hashes every
frame before it encodes, honours the job's cancel token and removes any partial output on failure or cancel.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from src.controller.runtime_state import CancelToken
from src.video.movie_assembly_compiler import (
    RESOLUTION_MATCH_FIRST,
    AssemblyIntentClip,
    MovieAssemblyAdmissionError,
    MovieAssemblyIntent,
    freeze_movie_assembly,
)
from src.video.movie_assembly_engine import MovieAssemblyOutcome, run_movie_assembly
from src.video.movie_assembly_models import MODE_SEQUENCE, MovieAssemblySpec
from src.video.sequence_plan import SequencePlan


class SequenceAssemblyError(RuntimeError):
    """The sequence's frames could not be assembled into a movie."""


def freeze_sequence_assembly(frames: Sequence[Path], plan: SequencePlan) -> MovieAssemblySpec:
    """The frozen ASM-332 spec for ``frames`` (already ordered and trimmed) at the plan's frame rate."""

    if not frames:
        raise SequenceAssemblyError("there are no frames to assemble")
    try:
        spec = freeze_movie_assembly(
            MovieAssemblyIntent(
                clips=tuple(AssemblyIntentClip(str(frame)) for frame in frames),
                mode=MODE_SEQUENCE,
                fps=plan.fps,
                resolution=RESOLUTION_MATCH_FIRST,
                transition_seconds=0.0,
                codec=plan.assembly.codec,
                quality=plan.assembly.quality,
                clip_name=plan.assembly.clip_name,
            )
        )
    except MovieAssemblyAdmissionError as exc:
        raise SequenceAssemblyError(str(exc)) from exc
    sizes = {(clip.width, clip.height) for clip in spec.clips}
    if len(sizes) != 1:
        found = ", ".join(f"{width}x{height}" for width, height in sorted(sizes))
        raise SequenceAssemblyError(
            f"the segments' frames are not all one size ({found}); the movie is not assembled from mixed sizes"
        )
    if spec.fps != plan.fps or spec.transition_seconds != 0.0:
        raise SequenceAssemblyError(
            "the frozen assembly does not match the plan's frame rate or cuts"
        )
    return spec


def assemble_sequence_frames(
    frames: Sequence[Path],
    plan: SequencePlan,
    *,
    run_dir: Path,
    job_id: str,
    cancel_token: CancelToken | None = None,
) -> MovieAssemblyOutcome:
    """Encode ``frames`` as one movie under ``run_dir`` (raises ``CancellationError`` on cancel)."""

    spec = freeze_sequence_assembly(frames, plan)
    outcome = run_movie_assembly(spec, run_dir=run_dir, cancel_token=cancel_token, job_id=job_id)
    if outcome.timeline.total_frames != len(frames) or outcome.timeline.fps != plan.fps:
        Path(outcome.output_path).unlink(missing_ok=True)
        raise SequenceAssemblyError(
            f"the assembled timeline ({outcome.timeline.total_frames} frames at {outcome.timeline.fps} fps) does "
            f"not match the {len(frames)} frames at {plan.fps} fps that were handed to the engine"
        )
    if not Path(outcome.output_path).is_file() or Path(outcome.output_path).stat().st_size == 0:
        raise SequenceAssemblyError("the assembly reported success but wrote no movie")
    return outcome


__all__ = ["SequenceAssemblyError", "assemble_sequence_frames", "freeze_sequence_assembly"]
