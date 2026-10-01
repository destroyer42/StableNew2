"""PR-RUNTIME-110: healthy long Comfy execution is not a queue-runner stall.

The real backend wait loop runs against a fake Comfy client on a fake clock.  Its liveness reports
travel through the real ``AppController`` runtime-status merge and are judged by the real
``SystemWatchdogV2`` at every simulated tick; no second progress/watchdog authority is involved.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.services.watchdog_system_v2 import SystemWatchdogV2
from src.video import ComfyWorkflowVideoBackend
from src.video.comfy_workflow_backend import _LIVENESS_REPORT_INTERVAL_S, _prompt_is_live

PROMPT_ID = "prompt-1"
OWNER_JOB = "job-1"
MONO0 = 10_000.0  # arbitrary monotonic origin shared by the fake clock and watchdog


class _Clock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def time(self) -> float:
        return 1_000.0 + self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds
        self.after_sleep(self.elapsed)

    def after_sleep(self, _elapsed: float) -> None:  # replaced by the harness
        return None


class _FakeComfy:
    """``mode``: running (alive until ``done_at``), vanished (responsive, prompt unknown),
    unreachable (queue endpoint errors), stuck (reports running forever), failed (terminal
    history), nonterminal (explicit running history), or ambiguous (history without live status)."""

    def __init__(self, clock: _Clock, *, mode: str = "running", done_at: float = 0.0) -> None:
        self.clock = clock
        self.mode = mode
        self.done_at = done_at
        self.history_calls = 0
        self.queue_calls = 0

    def get_history(self, prompt_id: str | None = None, **_kwargs: Any) -> dict[str, Any]:
        self.history_calls += 1
        if self.mode == "failed":
            return {PROMPT_ID: {"outputs": {}, "status": {"status_str": "error", "completed": False}}}
        if self.mode == "ambiguous":
            return {PROMPT_ID: {"outputs": {}, "status": {}}}
        if self.mode == "nonterminal" and self.clock.elapsed < self.done_at:
            return {
                PROMPT_ID: {"outputs": {}, "status": {"status_str": "running", "completed": False}}
            }
        if self.mode in {"running", "nonterminal"} and self.clock.elapsed >= self.done_at:
            return {
                PROMPT_ID: {
                    "outputs": {"9": {"videos": [{"filename": "clip.mp4"}]}},
                    "status": {"completed": True},
                }
            }
        return {}

    def get_queue(self, **_kwargs: Any) -> dict[str, Any]:
        self.queue_calls += 1
        if self.mode == "unreachable":
            raise ConnectionError("Comfy not answering")
        if self.mode in {"vanished", "nonterminal", "ambiguous"}:
            return {"queue_running": [], "queue_pending": []}
        return {"queue_running": [[0, PROMPT_ID, {}, {}, []]], "queue_pending": []}


class _Harness:
    """Real status-callback merge + real watchdog, both driven by the fake clock."""

    def __init__(self, monkeypatch, clock: _Clock, *, request_job_id: str = OWNER_JOB) -> None:
        self.clock = clock
        self.effective_timeout: float | None = None
        self.stall_ticks: list[float] = []
        self.emissions: list[dict[str, Any]] = []
        self.app = SimpleNamespace(
            last_runner_activity_ts=MONO0,
            _last_runtime_status=SimpleNamespace(
                job_id=OWNER_JOB,
                current_stage="video_workflow",
                stage_detail=None,
                stage_index=0,
                total_stages=1,
                progress=0.0,
                eta_seconds=None,
                started_at=datetime(2026, 9, 29),
                actual_seed=None,
                current_step=0,
                total_steps=0,
            ),
            job_service=SimpleNamespace(
                runner=SimpleNamespace(current_job=SimpleNamespace(job_id=OWNER_JOB))
            ),
            app_state=SimpleNamespace(running_job=None),
            has_running_jobs=lambda: True,
        )
        app = self.app
        app._get_latest_runtime_status = lambda: app._last_runtime_status
        app._infer_runtime_stage_name = lambda: "video_workflow"
        app._infer_runtime_stage_count = lambda: 1
        app._infer_runtime_stage_index = lambda _stage: 0
        app._coerce_runtime_status_started_at = AppController._coerce_runtime_status_started_at
        app._queue_runtime_status_update = lambda status: setattr(
            app, "_last_runtime_status", status
        )
        merge = AppController._get_runtime_status_callback(app)

        def _emit(status_data: dict[str, Any]) -> None:
            self.emissions.append(dict(status_data))
            merge(status_data)

        self.pipeline = SimpleNamespace(_emit_status_update=_emit)
        self.request = SimpleNamespace(job_id=request_job_id, stage_name="video_workflow")
        self.watchdog = SystemWatchdogV2(app, diagnostics_service=None)
        clock.after_sleep = self._tick
        monkeypatch.setattr(
            "src.video.comfy_workflow_backend.time",
            SimpleNamespace(time=clock.time, sleep=clock.sleep),
        )

    def _tick(self, elapsed: float) -> None:
        if self.watchdog._queue_running_but_stalled(MONO0 + elapsed):
            self.stall_ticks.append(elapsed)

    def wait(
        self,
        comfy: _FakeComfy,
        *,
        timeout: float | None = None,
        workflow: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        backend = ComfyWorkflowVideoBackend(history_poll_interval=1.0)
        if workflow is not None:
            workflow_id, version = workflow
            spec = backend._workflow_registry.get(
                workflow_id, version, allow_experimental=True
            )
            self.effective_timeout = backend._history_timeout_for(spec)
        else:
            self.effective_timeout = timeout
        return backend._wait_for_history_entry(
            comfy,
            prompt_id=PROMPT_ID,
            report_liveness=backend._liveness_reporter(self.pipeline, self.request),
            timeout=self.effective_timeout,
        )


@pytest.mark.parametrize(
    ("duration_s", "workflow", "expected_bound"),
    [
        (94.0, ("wan22_ti2v_5b_i2v_v1", "1.1.0"), 600.0),
        (221.0, ("wan22_ti2v_5b_i2v_v1", "1.1.0"), 600.0),
        (600.0, ("wan_animate2_prompt_i2v_v1", "1.1.0"), 1200.0),
    ],
)
def test_healthy_comfy_execution_beyond_the_runner_stall_interval_is_not_a_stall(
    monkeypatch, duration_s: float, workflow: tuple[str, str], expected_bound: float
) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)
    comfy = _FakeComfy(clock, done_at=duration_s)

    entry = harness.wait(comfy, workflow=workflow)

    assert duration_s > SystemWatchdogV2.RUNNER_STALL_S
    assert harness.effective_timeout == expected_bound
    assert entry["status"]["completed"] is True  # normal completion path
    assert harness.stall_ticks == []


def test_liveness_is_bounded_reported_and_invents_no_generation_progress(monkeypatch) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)
    harness.app._last_runtime_status.progress = 0.25
    harness.app._last_runtime_status.current_step = 7
    harness.app._last_runtime_status.total_steps = 10

    harness.wait(_FakeComfy(clock, done_at=221.0), workflow=("wan22_ti2v_5b_i2v_v1", "1.1.0"))

    assert 1 < len(harness.emissions) <= 221 / _LIVENESS_REPORT_INTERVAL_S + 1
    assert _LIVENESS_REPORT_INTERVAL_S < SystemWatchdogV2.RUNNER_STALL_S
    for emission in harness.emissions:
        assert emission["job_id"] == OWNER_JOB
        assert emission["stage_detail"].startswith("comfy executing")
        assert "progress" not in emission and "current_step" not in emission
    status = harness.app._last_runtime_status
    assert (status.progress, status.current_step, status.total_steps) == (0.25, 7, 10)
    assert status.job_id == OWNER_JOB


def test_liveness_from_another_job_cannot_keep_the_runner_owned_job_alive(monkeypatch) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock, request_job_id="next-queued-job")

    harness.wait(_FakeComfy(clock, done_at=200.0), workflow=("wan22_ti2v_5b_i2v_v1", "1.1.0"))

    assert harness.stall_ticks, "a foreign job's heartbeat must not count for the runner owner"
    assert harness.stall_ticks[0] > SystemWatchdogV2.RUNNER_STALL_S


@pytest.mark.parametrize("mode", ["unreachable", "vanished"])
def test_frozen_or_unconfirmed_comfy_execution_still_stalls_and_fails_within_bound(
    monkeypatch, mode: str
) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)
    comfy = _FakeComfy(clock, mode=mode)

    with pytest.raises(TimeoutError):
        harness.wait(comfy, timeout=300.0)

    assert harness.emissions == []
    assert harness.stall_ticks
    assert SystemWatchdogV2.RUNNER_STALL_S < harness.stall_ticks[0] <= 93.0
    assert clock.elapsed <= 300.0 + 1.0


def test_endless_running_responses_cannot_suppress_failure_past_the_backend_bound(
    monkeypatch,
) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)
    comfy = _FakeComfy(clock, mode="stuck")

    with pytest.raises(TimeoutError):
        harness.wait(comfy, timeout=300.0)

    assert harness.emissions  # confirmed-alive reports were made ...
    assert harness.stall_ticks == []  # ... which is the accepted liveness contract ...
    assert clock.elapsed <= 300.0 + 1.0  # ... and the wait still ends at the backend bound
    assert comfy.history_calls <= 302


def test_terminal_failed_history_never_emits_liveness_even_with_stale_queue_membership(
    monkeypatch,
) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)
    comfy = _FakeComfy(clock, mode="failed")

    with pytest.raises(RuntimeError, match="Comfy workflow failed"):
        harness.wait(comfy, timeout=300.0)

    assert harness.emissions == []
    assert comfy.queue_calls == 0


def test_explicit_nonterminal_history_can_report_liveness_without_queue_membership(
    monkeypatch,
) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)

    entry = harness.wait(_FakeComfy(clock, mode="nonterminal", done_at=120.0), timeout=300.0)

    assert entry["status"]["completed"] is True
    assert harness.emissions
    assert harness.stall_ticks == []


def test_ambiguous_history_without_queue_membership_remains_stall_detectable(
    monkeypatch,
) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)

    with pytest.raises(TimeoutError):
        harness.wait(_FakeComfy(clock, mode="ambiguous"), timeout=120.0)

    assert harness.emissions == []
    assert harness.stall_ticks


def test_liveness_reporting_is_off_without_a_job_or_a_status_path() -> None:
    request = SimpleNamespace(job_id="job-1", stage_name="video_workflow")

    assert ComfyWorkflowVideoBackend._liveness_reporter(SimpleNamespace(), request) is None
    assert (
        ComfyWorkflowVideoBackend._liveness_reporter(
            SimpleNamespace(_emit_status_update=lambda _s: None),
            SimpleNamespace(job_id="", stage_name="video_workflow"),
        )
        is None
    )


def test_prompt_liveness_needs_the_server_to_list_the_prompt() -> None:
    class _Client:
        def __init__(self, queue: Any) -> None:
            self.queue = queue

        def get_queue(self) -> Any:
            if isinstance(self.queue, Exception):
                raise self.queue
            return self.queue

    running = {"queue_running": [[3, PROMPT_ID, {}, {}, []]], "queue_pending": []}
    pending = {"queue_running": [], "queue_pending": [[4, PROMPT_ID, {}, {}, []]]}
    other = {"queue_running": [[3, "someone-else", {}, {}, []]], "queue_pending": []}

    assert _prompt_is_live(_Client(running), PROMPT_ID)
    assert _prompt_is_live(_Client(pending), PROMPT_ID)
    assert not _prompt_is_live(_Client(other), PROMPT_ID)
    assert not _prompt_is_live(_Client({}), PROMPT_ID)
    assert not _prompt_is_live(_Client(["not", "a", "mapping"]), PROMPT_ID)
    assert not _prompt_is_live(_Client(ConnectionError("down")), PROMPT_ID)


def test_a_failing_status_path_cannot_break_a_healthy_generation_wait(monkeypatch) -> None:
    clock = _Clock()
    harness = _Harness(monkeypatch, clock)

    def _boom(_status: dict[str, Any]) -> None:
        raise RuntimeError("status sink down")

    harness.pipeline = SimpleNamespace(_emit_status_update=_boom)

    entry = harness.wait(_FakeComfy(clock, done_at=30.0), workflow=("wan22_ti2v_5b_i2v_v1", "1.1.0"))

    assert entry["status"]["completed"] is True
