"""Toolkit-neutral state of the Video Workflow "Multi-shot sequence" section (PR-VID-SEQ-331A).

The section turns an ordered list of shots into one ``sequence_intent`` and hands it to the controller's
``submit_sequence_job``, which freezes the typed plan (refusing anything illegal before an NJR exists) and admits ONE
job through ``JobService.submit_njrs``. This module imports no Tk, starts no process and never touches a queue:

* ``submit`` reports every refusal as inline text, never as a modal and never as a half-queued job;
* ``check_progress`` reads the checkpoint ledger of the job it queued (evidence only; the repository owns the job).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.video.sequence_plan import SequencePlanError
from src.video.sequence_shots import ShotDraft, build_sequence_intent, shot_problems


@dataclass(frozen=True, slots=True)
class SequenceSubmitOutcome:
    ok: bool
    message: str
    job_id: str = ""


def sequence_block_reason(
    *, has_frame_counts: bool, source_image_path: str, shots: Sequence[ShotDraft]
) -> str:
    """Why Queue Sequence is off right now, or an empty string. Cheap checks only; admission is the authority."""

    if not has_frame_counts:
        return "The selected workflow declares no length policy, so it cannot run as a sequence."
    if not source_image_path.strip():
        return "Choose a source image first: shot 1 starts from it."
    problems = shot_problems(shots)
    return problems[0] if problems else ""


class SequenceSession:
    def __init__(self, *, get_controller: Callable[[], Any]) -> None:
        self._get_controller = get_controller
        self.job_id = ""
        self.status = ""

    def submit(
        self,
        *,
        source_image_path: str,
        form_data: Mapping[str, Any],
        shots: Sequence[ShotDraft],
        clip_name: str = "",
    ) -> SequenceSubmitOutcome:
        controller = self._get_controller()
        submit = getattr(controller, "submit_sequence_job", None)
        if not callable(submit):
            return self._say(SequenceSubmitOutcome(False, "Sequence submission is not available."))
        try:
            intent = build_sequence_intent(shots, clip_name=clip_name)
            job_id = submit(
                source_image_path=source_image_path,
                form_data=dict(form_data),
                sequence_intent=intent,
            )
        except (SequencePlanError, ValueError, RuntimeError, OSError) as exc:
            return self._say(SequenceSubmitOutcome(False, f"Not queued: {exc}"))
        self.job_id = str(job_id)
        count = len(shots)
        return self._say(
            SequenceSubmitOutcome(
                True, f"Queued a {count}-shot sequence as job {job_id}.", job_id=self.job_id
            )
        )

    def check_progress(self) -> str:
        if not self.job_id:
            return self._say_text("No sequence has been queued from this tab yet.")
        reader = getattr(self._get_controller(), "sequence_job_progress", None)
        found = reader(self.job_id) if callable(reader) else None
        if not found:
            return self._say_text(
                "No checkpoint yet: the first segment has not finished (or the job has not started)."
            )
        done, total, state = found
        return self._say_text(f"Sequence {self.job_id}: {done} of {total} segments done ({state}).")

    def _say(self, outcome: SequenceSubmitOutcome) -> SequenceSubmitOutcome:
        self.status = outcome.message
        return outcome

    def _say_text(self, text: str) -> str:
        self.status = text
        return text


__all__ = ["SequenceSession", "SequenceSubmitOutcome", "sequence_block_reason"]
