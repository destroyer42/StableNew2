"""Toolkit-neutral state of the Video Workflow "Recent outputs" section (PR-VID-UX-314).

The session lists the newest finished clips the canonical repository knows about and carries out the three
file actions on the selected one.  It imports no Tk and starts no process of its own:

* listing is an injected callable the injected ``BackgroundWorkRunner`` runs on a worker (it reads the
  repository and checks that each file exists); the outcome returns on the UI thread and is ignored when it
  went stale (a newer refresh started, or the section was closed);
* Open and Reveal call the injected shell helpers and report a failure as inline text;
* Send to Movie hands the recorded bundle to the injected router, which only transfers intent.

A refresh never changes what was recorded, queues anything or repairs a missing file.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.utils.os_shell import ShellResult, open_file, reveal_in_file_manager
from src.video.recent_video_outputs import RecentVideoOutput

EMPTY_TEXT = "No finished clips yet. Queue a video and it appears here when it completes."


class RecentOutputsSession:
    def __init__(
        self,
        *,
        list_outputs: Callable[[], Sequence[RecentVideoOutput]],
        runner: BackgroundWorkRunner,
        on_change: Callable[[], None] | None = None,
        send_to_movie: Callable[[RecentVideoOutput], Any] | None = None,
        open_path: Callable[[str], ShellResult] = open_file,
        reveal_path: Callable[[str], ShellResult] = reveal_in_file_manager,
    ) -> None:
        self._list_outputs = list_outputs
        self._runner = runner
        self._on_change = on_change
        self._send_to_movie = send_to_movie
        self._open_path = open_path
        self._reveal_path = reveal_path
        self._token = 0
        self._closed = False
        self.outputs: tuple[RecentVideoOutput, ...] = ()
        self.selected_job_id = ""
        self.busy = False
        self.status = EMPTY_TEXT
        self.loaded = False

    # ------------------------------------------------------------------ queries

    @property
    def selected(self) -> RecentVideoOutput | None:
        for output in self.outputs:
            if output.job_id == self.selected_job_id:
                return output
        return None

    @property
    def can_send_to_movie(self) -> bool:
        return self._send_to_movie is not None and self.selected is not None

    # ------------------------------------------------------------------ commands (UI thread)

    def refresh(self) -> None:
        """Re-read the newest clips on a worker; the previous selection is kept when it is still listed."""

        if self._closed:
            return
        self._token += 1
        token = self._token
        self.busy = True
        self._notify()
        list_outputs = self._list_outputs
        self._runner.start(
            "video-recent-outputs",
            lambda: WorkOutcome(value=tuple(list_outputs())),
            lambda outcome: self._finish(token, outcome),
        )

    def select(self, job_id: str) -> RecentVideoOutput | None:
        self.selected_job_id = str(job_id or "")
        self._notify()
        return self.selected

    def open_selected(self) -> ShellResult:
        return self._run_file_action(self._open_path, "Opened")

    def reveal_selected(self) -> ShellResult:
        return self._run_file_action(self._reveal_path, "Showing")

    def send_selected_to_movie(self) -> ShellResult:
        output = self.selected
        if output is None or self._send_to_movie is None:
            return self._say(ShellResult(False, "Select a finished clip first."))
        try:
            self._send_to_movie(output)
        except (ValueError, RuntimeError, OSError) as exc:
            return self._say(ShellResult(False, f"Could not send to Movie Clips: {exc}"))
        return self._say(ShellResult(True, f"Sent {output.file_name} to Movie Clips."))

    def close(self) -> None:
        self._closed = True
        self._token += 1
        self._on_change = None

    # ------------------------------------------------------------------ internals

    def _run_file_action(self, action: Callable[[str], ShellResult], verb: str) -> ShellResult:
        output = self.selected
        if output is None:
            return self._say(ShellResult(False, "Select a finished clip first."))
        result = action(output.video_path)
        return self._say(ShellResult(True, f"{verb} {output.file_name}.") if result.ok else result)

    def _say(self, result: ShellResult) -> ShellResult:
        self.status = result.message or self.status
        self._notify()
        return result

    def _finish(self, token: int, outcome: WorkOutcome) -> None:
        if self._closed or token != self._token:
            return
        self.busy = False
        self.loaded = True
        if outcome.error:
            self.status = f"Recent outputs could not be read: {outcome.error}"
        else:
            self.outputs = tuple(outcome.value or ())
            listed = {output.job_id for output in self.outputs}
            if self.selected_job_id not in listed:
                self.selected_job_id = self.outputs[0].job_id if self.outputs else ""
            self.status = f"{len(self.outputs)} recent clip(s)." if self.outputs else EMPTY_TEXT
        self._notify()

    def _notify(self) -> None:
        callback = self._on_change
        if callback is not None:
            callback()


__all__ = ["EMPTY_TEXT", "RecentOutputsSession"]
