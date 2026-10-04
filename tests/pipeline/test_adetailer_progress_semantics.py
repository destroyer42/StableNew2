"""ADetailer nominal sampling completion is extension activity, not HTTP completion."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src.api.client import DEFAULT_GENERATION_TIMEOUT, ProgressInfo, SDWebUIClient
from src.api.types import GenerateErrorCode
from src.pipeline.executor import (
    EXTERNAL_WEBUI_STALL_ACTION_REQUIRED,
    POST_INTERRUPT_STALL_GRACE_SEC,
    POST_PROGRESS_RESPONSE_STALL_THRESHOLD_SEC,
    STALL_INTERRUPT_THRESHOLD_BY_STAGE,
    Pipeline,
    PipelineStageError,
)
from src.utils import StructuredLogger


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now


class StopAfter:
    def __init__(self, clock, end):
        self.clock, self.end = clock, end

    def is_set(self):
        return self.clock.now > self.end

    def wait(self, duration):
        self.clock.now += duration
        return self.is_set()


@pytest.fixture
def rig(monkeypatch):
    clock = Clock()
    client = Mock(spec=SDWebUIClient)
    client.get_progress.return_value = ProgressInfo(1.0, None, 5, 5, None, {"job_timestamp": "first"})
    interrupts = []
    client.interrupt.side_effect = lambda: interrupts.append(clock.now) or True
    pipeline = Pipeline(client, Mock(spec=StructuredLogger))
    pipeline._current_job_id = "semantics-job"
    monkeypatch.setattr("src.pipeline.executor.time.monotonic", clock.monotonic)
    return SimpleNamespace(clock=clock, client=client, pipeline=pipeline, interrupts=interrupts)


def poll(rig, stage="adetailer", end=599.0, **kwargs):
    rig.pipeline._poll_progress_loop(StopAfter(rig.clock, end), 1.0, None, stage, **kwargs)


@pytest.mark.parametrize("stage", ["txt2img", "img2img"])
def test_ordinary_sampling_and_completion_thresholds_unchanged(rig, stage):
    rig.client.get_progress.return_value = ProgressInfo(0.5, None, 10, 20, None, {})
    poll(rig, stage, end=100.0)
    assert rig.interrupts == [90.0]
    rig.clock.now = 0.0
    rig.interrupts.clear()
    rig.client.get_progress.return_value = ProgressInfo(1.0, None, 20, 20, None, {})
    poll(rig, stage, end=60.0)
    assert POST_PROGRESS_RESPONSE_STALL_THRESHOLD_SEC == 20.0
    assert rig.interrupts == [20.0]


def test_adetailer_genuine_sampling_stall_retains_45_second_protection(rig):
    rig.client.get_progress.return_value = ProgressInfo(0.5, None, 10, 20, None, {})
    poll(rig, end=60.0)
    assert STALL_INTERRUPT_THRESHOLD_BY_STAGE["adetailer"] == 45.0
    assert rig.interrupts == [45.0]


@pytest.mark.parametrize("end", [20.0, 45.0, 90.0, 120.0, 599.0, 700.0])
@pytest.mark.parametrize("completed_by_steps", [False, True])
def test_extension_active_never_uses_percent_or_steps_as_completion_interrupt_authority(
    rig, end, completed_by_steps
):
    # >600 simulated seconds deliberately proves the executor adds no second timer;
    # the separate client test below verifies the actual transport owns 600 seconds.
    rig.client.get_progress.return_value = ProgressInfo(
        0.5 if completed_by_steps else 1.0, None, 5, 5, None, {}
    )
    stalled = threading.Event()
    poll(rig, end=end, stall_detected_event=stalled)
    assert rig.interrupts == [] and not stalled.is_set()


@pytest.mark.parametrize("missing_progress", [None, ProgressInfo(0.1, None, 0, 5, None, {})])
def test_extension_phase_survives_idle_or_counter_reset_without_a_new_marker(rig, missing_progress):
    rig.client.get_progress.side_effect = lambda **_k: (
        ProgressInfo(1.0, None, 5, 5, None, {"job": "same"})
        if rig.clock.now == 0 else missing_progress
    )
    poll(rig, end=599.0)
    assert rig.interrupts == []


@pytest.mark.parametrize("marker_key", ["job_timestamp", "job"])
def test_new_subpass_marker_resets_sampling_liveness_and_can_stall(rig, marker_key):
    rig.client.get_progress.side_effect = lambda **_k: (
        ProgressInfo(1.0, None, 5, 5, None, {marker_key: "first"})
        if rig.clock.now < 120 else ProgressInfo(0.1, None, 1, 12, None, {marker_key: "second"})
    )
    poll(rig, end=180.0)
    assert rig.interrupts == [165.0]  # full 45 seconds from the NEW marker, not the old clock


def test_new_subpass_can_complete_and_reenter_extension_active(rig):
    def progress(**_kwargs):
        if rig.clock.now < 120:
            return ProgressInfo(1.0, None, 5, 5, None, {"job": "first"})
        if rig.clock.now < 140:
            return ProgressInfo(0.1, None, 1, 12, None, {"job": "second"})
        return ProgressInfo(1.0, None, 12, 12, None, {"job": "second"})

    rig.client.get_progress.side_effect = progress
    poll(rig)
    assert rig.interrupts == []


def test_operator_cancellation_has_priority_in_extension_active_and_interrupts_once(rig):
    poll(rig, cancel_token=SimpleNamespace(is_cancelled=lambda: rig.clock.now >= 120.0))
    assert rig.interrupts == [120.0]


@pytest.mark.parametrize("owned", [True, False])
def test_extension_activity_never_restarts_managed_or_external_runtime(rig, monkeypatch, owned):
    manager = Mock(owns_process=owned)
    manager.is_running.return_value = True
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)
    escalation = threading.Event()
    poll(rig, managed_stall_escalation_event=escalation)
    assert rig.interrupts == [] and not escalation.is_set()
    manager.restart_webui.assert_not_called()
    manager.stop.assert_not_called()


@pytest.mark.parametrize("owned", [True, False])
def test_actual_sampling_stall_keeps_bounded_owned_escalation_and_external_manual_action(rig, monkeypatch, owned):
    manager = Mock(owns_process=owned)
    manager.is_running.return_value = True
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)
    rig.client.get_progress.return_value = ProgressInfo(0.5, None, 10, 20, None, {})
    events = []
    rig.pipeline._status_callback = events.append
    poll(rig, end=200.0)
    assert rig.interrupts == [45.0]
    assert POST_INTERRUPT_STALL_GRACE_SEC == 30.0
    if owned:
        manager.restart_webui.assert_called_once_with(wait_ready=True, max_attempts=1)
    else:
        manager.restart_webui.assert_not_called()
        assert len([e for e in events if e.get("event") == EXTERNAL_WEBUI_STALL_ACTION_REQUIRED]) == 1
    manager.stop.assert_not_called()


def test_actual_client_transport_timeout_is_600_and_propagates_unknown_without_replay(monkeypatch):
    client = SDWebUIClient()
    assert client.timeout == DEFAULT_GENERATION_TIMEOUT == 600.0
    calls = []

    def timeout_request(_session, method, url, **kwargs):
        calls.append((method, url, kwargs["timeout"]))
        raise requests.ReadTimeout("response timed out after dispatch")

    monkeypatch.setattr("src.api.client.requests.Session.request", timeout_request)
    client.get_progress = lambda **_kw: ProgressInfo(1.0, None, 5, 5, None, {"job": "ad"})
    pipeline = Pipeline(client, Mock(spec=StructuredLogger))
    pipeline._ensure_webui_true_ready = Mock()
    pipeline._check_webui_health_before_stage = Mock()
    manager = Mock(owns_process=False)
    manager.get_recent_output_tail.return_value = {}
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)

    with pytest.raises(PipelineStageError) as exc:
        pipeline._generate_images_with_progress("adetailer", {"prompt": "frozen", "seed": 424242})

    assert exc.value.error.code is GenerateErrorCode.OUTCOME_UNKNOWN
    assert exc.value.error.details["request_may_have_executed"] is True
    assert len(calls) == 1 and calls[0][0] == "POST"
    assert calls[0][1].endswith("/sdapi/v1/img2img")
    assert calls[0][2][1] == 600.0
    manager.restart_webui.assert_not_called()
