"""Focused operator-truth contracts for the live queue and history panels."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.queue.job_history_store import (
    INTERRUPTED_RESTART_ACTION_REQUIRED,
    JobHistoryEntry,
    JobStatus,
)
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from tests.helpers.job_helpers import make_test_njr


class _QueueController:
    def __init__(self, *, remove_result: bool = True, clear_result: int = 1) -> None:
        self.calls: list[object] = []
        self.remove_result = remove_result
        self.clear_result = clear_result

    def on_set_auto_run_v2(self, enabled: bool) -> None:
        self.calls.append(("auto", enabled))

    def on_pause_queue_v2(self) -> None:
        self.calls.append("pause")

    def on_resume_queue_v2(self) -> None:
        self.calls.append("resume")

    def on_queue_send_job_v2(self) -> bool:
        self.calls.append("send")
        return True

    def on_queue_remove_job_v2(self, job_id: str) -> bool:
        self.calls.append(("remove", job_id))
        return self.remove_result

    def on_queue_clear_v2(self) -> int:
        self.calls.append("clear")
        return self.clear_result


def _queue_job(job_id: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        job_id=job_id,
        status=status,
        get_display_summary=lambda: job_id,
    )


@pytest.mark.gui
def test_queue_actions_require_capability_and_truthful_outcomes(tk_root) -> None:
    app_state = AppStateV2()
    app_state.set_auto_run_queue(False)
    controller = _QueueController()
    panel = QueuePanelV2(tk_root, controller=controller, app_state=app_state)
    queued = _queue_job("queued", "QUEUED")
    running = _queue_job("running", "RUNNING")
    panel.update_jobs([queued])
    panel.job_listbox.selection_set(0)
    panel._update_button_states()

    assert panel.send_job_button.instate(["!disabled"])
    panel._on_send_job()
    assert controller.calls == ["send"]

    panel._is_queue_paused = True
    panel._update_button_states()
    assert panel.send_job_button.instate(["disabled"])
    panel._on_send_job()
    assert controller.calls == ["send"]

    panel._is_queue_paused = False
    app_state.running_job = running
    panel._update_button_states()
    assert panel.send_job_button.instate(["disabled"])
    app_state.running_job = None

    panel.auto_run_var.set(True)
    panel._on_auto_run_changed()
    panel._on_pause_resume()
    assert controller.calls[-2:] == [("auto", True), "pause"]

    feedback: list[str] = []
    panel._emit_status_message = lambda message, **_kwargs: feedback.append(message)
    panel.controller = _QueueController(remove_result=False, clear_result=0)
    panel._is_queue_paused = False
    panel._update_button_states()
    panel._on_remove()
    panel._on_clear()
    assert not any(message.startswith("Removed") for message in feedback)
    assert not any(message.startswith("Cleared ") for message in feedback)

    panel.controller = _QueueController()
    panel.update_jobs([running, queued])
    panel.job_listbox.selection_set(0)
    panel._update_button_states()
    assert panel.remove_button.instate(["disabled"])
    assert panel.clear_button.instate(["!disabled"])
    panel.destroy()


def test_queue_keyboard_handlers_cannot_bypass_missing_boundaries() -> None:
    class ButtonState:
        def __init__(self) -> None:
            self.disabled = False

        def state(self, values: list[str]) -> None:
            self.disabled = "disabled" in values

    panel = object.__new__(QueuePanelV2)
    queued = _queue_job("queued", "QUEUED")
    panel.controller = None
    panel.app_state = SimpleNamespace(running_job=None)
    panel._jobs = [queued]
    panel._is_queue_paused = False
    panel._get_selected_index = lambda: 0
    panel._get_selected_job = lambda: queued
    panel._selected_queued_position = lambda: (0, [0])
    panel._job_status_value = lambda job: str(job.status).lower()
    panel._has_queued_jobs = lambda: True
    for name in (
        "auto_run_check",
        "pause_resume_button",
        "send_job_button",
        "move_to_front_button",
        "move_up_button",
        "move_down_button",
        "move_to_back_button",
        "remove_button",
        "clear_button",
    ):
        setattr(panel, name, ButtonState())
    panel._emit_status_message = lambda *_args, **_kwargs: None
    panel._on_send_job()
    panel._on_remove()
    panel._on_clear()
    assert all(
        getattr(panel, name).disabled
        for name in (
            "auto_run_check",
            "pause_resume_button",
            "send_job_button",
            "remove_button",
            "clear_button",
        )
    )


class _HistoryController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def on_replay_history_job_v2(self, job_id: str) -> None:
        self.calls.append(("replay", job_id))

    def send_history_job_image_to_svd(self, job_id: str) -> None:
        self.calls.append(("svd", job_id))

    def send_history_job_image_to_video_workflow(self, job_id: str) -> None:
        self.calls.append(("workflow", job_id))

    def send_history_job_to_movie_clips(self, job_id: str) -> None:
        self.calls.append(("movie", job_id))

    def explain_job(self, job_id: str) -> None:
        self.calls.append(("explain", job_id))


def _history_entry(
    job_id: str,
    *,
    result: dict[str, object],
    replayable: bool = True,
    status: JobStatus = JobStatus.COMPLETED,
) -> JobHistoryEntry:
    snapshot = None
    if replayable:
        snapshot = {
            "normalized_job": make_test_njr(
                job_id=job_id,
                prompt_source="manual",
                prompt_pack_id="",
            ).to_dict()
        }
    return JobHistoryEntry(
        job_id=job_id,
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status=status,
        payload_summary="",
        result=result,
        snapshot=snapshot,
    )


def _select_history_entry(panel: JobHistoryPanelV2, entry: JobHistoryEntry) -> None:
    panel._entries = {entry.job_id: entry}
    panel._selected_job_id = entry.job_id
    panel._update_action_buttons(entry)


@pytest.mark.gui
def test_history_actions_require_evidence_capability_and_context_parity(tk_root, tmp_path) -> None:
    image_path = tmp_path / "run" / "portrait.png"
    image_path.parent.mkdir()
    image_path.write_bytes(b"png")
    controller = _HistoryController()
    panel = JobHistoryPanelV2(
        tk_root,
        controller=controller,
        app_state=AppStateV2(),
        folder_opener=lambda _folder: None,
    )
    image_entry = _history_entry(
        "image-job",
        result={
            "artifact": {
                "schema": "stablenew.artifact.v2.6",
                "artifact_type": "image",
                "primary_path": str(image_path),
                "output_paths": [str(image_path)],
            }
        },
    )
    _select_history_entry(panel, image_entry)

    for button in (
        panel.open_btn,
        panel.replay_btn,
        panel.svd_btn,
        panel.video_workflow_btn,
        panel.movie_clips_btn,
        panel.explain_btn,
    ):
        assert button.instate(["!disabled"])
    for label in (
        "Animate with SVD",
        "Send to Video Workflow",
        "Send to Movie Clips",
        "Explain This Job",
    ):
        assert panel._history_menu.entrycget(label, "state") == "normal"

    panel.controller = object()
    panel._update_action_buttons(image_entry)
    assert panel.open_btn.instate(["!disabled"])
    for button in (
        panel.replay_btn,
        panel.svd_btn,
        panel.video_workflow_btn,
        panel.movie_clips_btn,
        panel.explain_btn,
    ):
        assert button.instate(["disabled"])
    panel.controller = controller

    image_path.unlink()
    panel._update_action_buttons(image_entry)
    assert panel.open_btn.instate(["disabled"])
    assert panel.svd_btn.instate(["disabled"])
    assert panel.video_workflow_btn.instate(["disabled"])
    assert panel.movie_clips_btn.instate(["disabled"])
    assert panel._history_menu.entrycget("Animate with SVD", "state") == "disabled"
    panel._on_send_to_svd()
    assert controller.calls == []

    video_path = tmp_path / "run" / "clip.mp4"
    thumbnail_path = tmp_path / "run" / "thumb.png"
    video_path.write_bytes(b"video")
    thumbnail_path.write_bytes(b"png")
    video_entry = _history_entry(
        "video-job",
        result={
            "video_bundle": {
                "artifact_type": "video",
                "primary_path": str(video_path),
                "output_paths": [str(video_path)],
                "thumbnail_path": str(thumbnail_path),
            }
        },
    )
    _select_history_entry(panel, video_entry)
    assert panel.svd_btn.instate(["disabled"])
    assert panel.video_workflow_btn.instate(["!disabled"])
    assert panel.movie_clips_btn.instate(["!disabled"])

    malformed = _history_entry("malformed", result={}, replayable=False)
    malformed.snapshot = {"normalized_job": {"not": "an njr"}}
    _select_history_entry(panel, malformed)
    assert panel.replay_btn.instate(["disabled"])

    interrupted = _history_entry("interrupted", result={}, status=JobStatus.FAILED)
    interrupted.error_envelope = UnifiedErrorEnvelope(
        error_type=INTERRUPTED_RESTART_ACTION_REQUIRED,
        subsystem="queue_recovery",
        severity="ERROR",
        message="action required",
        cause=None,
        stack="",
        job_id=interrupted.job_id,
        stage=None,
    )
    _select_history_entry(panel, interrupted)
    assert panel.replay_btn.instate(["!disabled"])
    panel.destroy()


def test_controller_handoff_uses_canonical_direct_image_artifact(tmp_path) -> None:
    image_path = tmp_path / "portrait.png"
    image_path.write_bytes(b"png")
    entry = _history_entry(
        "controller-image",
        result={
            "artifact": {
                "schema": "stablenew.artifact.v2.6",
                "artifact_type": "image",
                "primary_path": str(image_path),
                "output_paths": [str(image_path)],
            }
        },
    )

    assert AppController.__new__(AppController)._get_history_image_path(entry) == str(image_path)
