"""PR-IMG-FORGE-100R: stage-aware completion-response grace for the progress watchdog.

WebUI reporting 100 % does not mean the blocking request is complete, but a slow response after completion gets
the stage-appropriate bounded grace before StableNew interrupts it. ADetailer's detection/inpaint units keep the
progress report at 100 % while real work continues in one request, so it must never get a completion grace
shorter than its own hard-stall threshold (45 s). The generic 20 s grace, the ordinary no-progress stall, operator
cancellation, bounded managed escalation, external-runtime non-mutation and non-replay are preserved. Simulated
clocks and events only: nothing sleeps for real tens of seconds.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.api.client import ProgressInfo, SDWebUIClient
from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome
from src.pipeline import executor
from src.pipeline.executor import (
    EXTERNAL_WEBUI_STALL_ACTION_REQUIRED,
    POST_INTERRUPT_STALL_GRACE_SEC,
    POST_PROGRESS_RESPONSE_STALL_THRESHOLD_SEC,
    STALL_INTERRUPT_THRESHOLD_BY_STAGE,
    Pipeline,
    PipelineStageError,
    post_progress_response_threshold,
)
from src.utils import StructuredLogger


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _StopAfter:
    def __init__(self, clock: _Clock, *, stop_after: float) -> None:
        self._clock, self._stop_after, self._set = clock, stop_after, False

    def is_set(self) -> bool:
        return self._set

    def wait(self, duration: float) -> bool:
        self._clock.now += duration
        self._set = self._clock.now > self._stop_after
        return self._set


class _Event:
    def __init__(self, clock: _Clock) -> None:
        self._clock, self.times = clock, []

    def set(self) -> None:
        self.times.append(self._clock.now)


@pytest.fixture
def rig(monkeypatch):
    clock = _Clock()
    client = Mock(spec=SDWebUIClient)
    interrupts: list[float] = []
    client.interrupt.side_effect = lambda: interrupts.append(clock.now) or True
    # WebUI at 100 %: the last step is done, the blocking request has not returned.
    client.get_progress.return_value = ProgressInfo(1.0, None, 5, 5, None, {})
    pipeline = Pipeline(client, Mock(spec=StructuredLogger))
    pipeline._current_job_id = "grace-job"
    monkeypatch.setattr("src.pipeline.executor.time.monotonic", clock.monotonic)
    return SimpleNamespace(clock=clock, client=client, pipeline=pipeline, interrupts=interrupts)


def _poll(rig, stage: str, *, stop_after: float, **kwargs) -> None:
    rig.pipeline._poll_progress_loop(_StopAfter(rig.clock, stop_after=stop_after), 1.0, None, stage, **kwargs)


# --- the policy itself ------------------------------------------------------------------------------


def test_the_adetailer_completion_grace_is_derived_from_its_stage_hard_stall_not_invented():
    assert POST_PROGRESS_RESPONSE_STALL_THRESHOLD_SEC == 20.0  # the generic default is unchanged
    assert post_progress_response_threshold("txt2img") == 20.0
    assert post_progress_response_threshold("img2img") == 20.0
    assert post_progress_response_threshold("upscale") == 20.0
    assert post_progress_response_threshold(None) == 20.0
    assert post_progress_response_threshold("adetailer") == STALL_INTERRUPT_THRESHOLD_BY_STAGE["adetailer"] == 45.0


def test_a_stage_never_gets_a_completion_grace_shorter_than_its_own_hard_stall(monkeypatch):
    monkeypatch.setattr(executor, "STALL_INTERRUPT_THRESHOLD_BY_STAGE", {"adetailer": 70.0})
    assert post_progress_response_threshold("adetailer") == 70.0  # follows the stage policy
    monkeypatch.setattr(executor, "STALL_INTERRUPT_THRESHOLD_BY_STAGE", {"adetailer": 5.0})
    assert post_progress_response_threshold("adetailer") == 20.0  # but never below the generic default


# --- generic behavior retained ------------------------------------------------------------------------


@pytest.mark.parametrize(("stop_after", "expected"), [(19.0, []), (20.0, [20.0]), (60.0, [20.0])])
def test_txt2img_completion_stall_keeps_the_generic_20_second_behavior(rig, stop_after, expected):
    _poll(rig, "txt2img", stop_after=stop_after)

    assert rig.interrupts == expected  # at most one interrupt, at exactly the generic threshold


# --- ADetailer ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("stop_after", [20.0, 30.0, 44.0])
def test_adetailer_at_100_percent_between_20_and_45_seconds_is_not_interrupted(rig, stop_after):
    stalled = _Event(rig.clock)

    _poll(rig, "adetailer", stop_after=stop_after, stall_detected_event=stalled)

    assert rig.interrupts == []  # the span that interrupted the failed Pair-D run
    assert stalled.times == []  # not even flagged as a completion stall yet


def test_adetailer_wedged_beyond_its_completion_threshold_is_interrupted_exactly_once(rig):
    stalled = _Event(rig.clock)

    _poll(rig, "adetailer", stop_after=70.0, stall_detected_event=stalled)

    assert rig.interrupts == [45.0]
    assert stalled.times[0] == 45.0


def test_the_ordinary_adetailer_no_progress_stall_is_unchanged(rig):
    rig.client.get_progress.return_value = ProgressInfo(0.5, None, 10, 20, None, {})

    _poll(rig, "adetailer", stop_after=60.0)

    assert rig.interrupts == [45.0]  # the existing hard threshold, from last meaningful progress


# --- escalation stays bounded and ownership-aware ---------------------------------------------------------


def _manager(managed: bool):
    return SimpleNamespace(
        owns_process=managed, restarts=[],
        is_running=lambda: managed,
        restart_webui=lambda **kw: manager_restarts.append(kw) or True,
    )


manager_restarts: list[dict] = []


@pytest.fixture(autouse=True)
def _reset_restarts():
    manager_restarts.clear()


def test_after_the_interrupt_a_managed_runtime_gets_the_bounded_grace_and_one_plain_restart(rig, monkeypatch):
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: _manager(True))
    escalation = threading.Event()

    _poll(rig, "adetailer", stop_after=300.0, managed_stall_escalation_event=escalation)

    assert rig.interrupts == [45.0]
    assert manager_restarts == [{"wait_ready": True, "max_attempts": 1}]  # no profile_override: command untouched
    assert escalation.is_set()


@pytest.mark.parametrize(("stop_after", "restarts"), [(74.0, 0), (75.0, 1)])
def test_the_managed_restart_waits_exactly_the_post_interrupt_grace_after_the_adetailer_interrupt(
    rig, monkeypatch, stop_after, restarts
):
    assert POST_INTERRUPT_STALL_GRACE_SEC == 30.0
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: _manager(True))

    _poll(rig, "adetailer", stop_after=stop_after, managed_stall_escalation_event=threading.Event())

    assert rig.interrupts == [45.0] and len(manager_restarts) == restarts


def test_an_external_runtime_is_never_restarted_or_killed_it_is_reported_once(rig, monkeypatch):
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: _manager(False))
    events: list[dict] = []
    rig.pipeline._status_callback = lambda status: status.get("event") == EXTERNAL_WEBUI_STALL_ACTION_REQUIRED and events.append(status)

    _poll(rig, "adetailer", stop_after=300.0, managed_stall_escalation_event=threading.Event())

    assert rig.interrupts == [45.0]
    assert manager_restarts == []  # nothing was restarted
    assert len(events) == 1 and events[0]["recovery_mode"] == "external_manual" and events[0]["interrupt_sent"] is True


# --- operator cancellation is never delayed by the grace ---------------------------------------------------


def test_operator_cancellation_interrupts_promptly_and_is_not_delayed_by_the_adetailer_grace(rig):
    token = SimpleNamespace(is_cancelled=lambda: rig.clock.now >= 5.0)

    _poll(rig, "adetailer", stop_after=100.0, cancel_token=token)

    assert rig.interrupts == [5.0]  # on the first poll after the request, long before 45 s; one interrupt only


# --- ambiguous dispatched POST is never replayed -----------------------------------------------------------


class _WedgedAdetailerClient:
    def __init__(self) -> None:
        self.release, self.posts, self.interrupts = threading.Event(), 0, 0

    def generate_images(self, *, stage: str, payload: dict) -> GenerateOutcome:
        self.posts += 1
        assert self.release.wait(timeout=5.0)
        return GenerateOutcome(error=GenerateError(code=GenerateErrorCode.OUTCOME_UNKNOWN, message="connection broke", stage=stage))

    def get_progress(self, *, skip_current_image: bool = True) -> ProgressInfo:
        return ProgressInfo(1.0, None, 5, 5, None, {"job_timestamp": "adetailer-wedge"})

    def interrupt(self) -> bool:
        self.interrupts += 1
        return True


def test_a_managed_adetailer_wedge_restarts_once_and_never_replays_the_dispatched_post(monkeypatch):
    client = _WedgedAdetailerClient()
    managed = SimpleNamespace(owns_process=True, is_running=lambda: True, restarts=0)

    def restart(**_kw):
        managed.restarts += 1
        client.release.set()
        return True

    managed.restart_webui = restart
    pipeline = Pipeline(client, Mock(spec=StructuredLogger))
    pipeline._current_job_id = "wedge-job"
    pipeline._ensure_webui_true_ready = Mock()
    pipeline._check_webui_health_before_stage = Mock()
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: managed)
    # real-time, millisecond-scale policy (the exact boundaries are pinned on the simulated clock above)
    monkeypatch.setattr("src.pipeline.executor.POST_PROGRESS_RESPONSE_STALL_THRESHOLD_SEC", 0.01)
    monkeypatch.setattr("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {"adetailer": 0.02})
    monkeypatch.setattr("src.pipeline.executor.POST_INTERRUPT_STALL_GRACE_SEC", 0.03)

    with pytest.raises(PipelineStageError) as error:
        pipeline._generate_images_with_progress("txt2img", {"prompt": "wedge", "steps": 20}, poll_interval=0.01, stage_label="adetailer")

    assert error.value.error.code is GenerateErrorCode.OUTCOME_UNKNOWN
    assert client.posts == 1  # the dispatched POST is never replayed
    assert client.interrupts == 1 and managed.restarts == 1
