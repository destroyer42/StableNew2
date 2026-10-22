"""Resume and Replay of a sequence job from Job History (PR-VID-SEQ-331A). Toolkit-neutral.

Both actions end in one ``JobService.submit_njrs`` on the controller's existing ``resume_sequence`` /
``replay_sequence``: a NEW job with parent lineage; the parent's record and checkpoint are never touched. A refusal
(a checkpoint that changed, a plan that no longer verifies) comes back as text for the status line, with nothing queued.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from src.video.sequence_plan import SequencePlanError
from src.video.sequence_resume import SequenceResumeError

ACTION_RESUME: Final = "resume"
ACTION_REPLAY: Final = "replay"

_REFUSALS = (SequenceResumeError, SequencePlanError, ValueError, RuntimeError, OSError)


def run_sequence_action(
    app_controller: Any,
    job_id: str,
    action: str,
    *,
    pick_ledger: Callable[[], str | None],
) -> str:
    """Queue the resume or replay of ``job_id`` and return the line History shows."""

    getter = getattr(app_controller, "get_video_workflow_controller", None)
    controller = getter() if callable(getter) else None
    method = getattr(controller, f"{action}_sequence", None)
    if not callable(method):
        return f"{action.capitalize()} Sequence is not available."
    ledger_path: str | None = None
    if action == ACTION_RESUME:
        progress = getattr(controller, "sequence_job_progress", None)
        # A job that recorded no checkpoint (a cancelled one) is found by its job id; only when that fails is the
        # operator asked for the file.
        if callable(progress) and progress(job_id) is None:
            ledger_path = pick_ledger()
            if not ledger_path:
                return "Resume needs the job's sequence_state.json; nothing was queued."
    try:
        new_job = method(job_id, ledger_path=ledger_path) if ledger_path else method(job_id)
    except _REFUSALS as exc:
        return f"{action.capitalize()} Sequence refused: {exc}"
    sync = getattr(app_controller, "sync_queue_state_after_direct_submission", None)
    if callable(sync):
        sync()
    verb = "Queued a resume of" if action == ACTION_RESUME else "Queued a full replay of"
    return f"{verb} job {job_id} as job {new_job}."


__all__ = ["ACTION_REPLAY", "ACTION_RESUME", "run_sequence_action"]
