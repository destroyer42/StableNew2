"""PR-RUNTIME-NO-IMPLICIT-REPLAY: ReplayEngine invokes ``run_njr`` at most once per attempt.

Runner compatibility is resolved from the signature *before* invocation. A ``TypeError`` raised from the execution
body is an execution failure, never a signal to dispatch the same job again.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.pipeline.job_models_v2 import StageConfig
from src.pipeline.replay_engine import ReplayEngine
from src.queue.job_model import Job, JobPriority, JobStatus
from tests.helpers.njr_factory import make_pipeline_njr


def _njr(job_id: str = "once-001"):
    return make_pipeline_njr(
        job_id=job_id,
        positive_prompt="castle",
        stage_chain=[StageConfig(stage_type="txt2img", enabled=True)],
    )


def _job(job_id: str = "once-001") -> Job:
    return Job(job_id=job_id, priority=JobPriority.NORMAL)


class _DispatchThenTypeError:
    """Starts work (records a dispatch), then fails with a TypeError from inside execution."""

    def __init__(self) -> None:
        self.dispatches = 0

    def run_njr(self, njr, cancel_token=None, run_plan=None, log_fn=None, checkpoint_callback=None):
        self.dispatches += 1
        raise TypeError("unsupported operand inside the execution body")


def test_execution_body_type_error_is_not_retried() -> None:
    runner = _DispatchThenTypeError()
    engine = ReplayEngine(runner)

    with pytest.raises(TypeError, match="execution body"):
        engine.replay_njr(_njr(), job=_job())

    assert runner.dispatches == 1


def test_execution_body_type_error_is_not_retried_without_job() -> None:
    runner = _DispatchThenTypeError()

    with pytest.raises(TypeError, match="execution body"):
        ReplayEngine(runner).replay_njr(_njr())

    assert runner.dispatches == 1


def test_runner_without_checkpoint_keyword_is_never_invoked_twice() -> None:
    calls: list[dict[str, Any]] = []

    class _Legacy:
        def run_njr(self, njr, cancel_token=None, run_plan=None):
            calls.append({"run_plan": run_plan})
            return {"status": "ok"}

    result = ReplayEngine(_Legacy()).replay_njr(_njr(), job=_job())

    assert result == {"status": "ok"}
    assert len(calls) == 1
    assert calls[0]["run_plan"] is not None


def test_legacy_runner_that_raises_type_error_after_start_runs_once() -> None:
    calls = 0

    class _LegacyFails:
        def run_njr(self, njr, cancel_token=None, run_plan=None):
            nonlocal calls
            calls += 1
            raise TypeError("failed after start")

    with pytest.raises(TypeError, match="failed after start"):
        ReplayEngine(_LegacyFails()).replay_njr(_njr(), job=_job())

    assert calls == 1


def test_checkpoint_rejecting_runner_is_never_attempted_with_the_keyword() -> None:
    attempts: list[dict[str, Any]] = []

    def legacy_signature(njr, cancel_token=None, run_plan=None):
        raise NotImplementedError

    def recording(*args: Any, **kwargs: Any) -> dict[str, str]:
        attempts.append(dict(kwargs))
        return {"status": "ok"}

    # Exposes the legacy signature but records the kwargs of every real call.
    recording.__signature__ = inspect.signature(legacy_signature)  # type: ignore[attr-defined]
    runner = SimpleNamespace(run_njr=recording)

    ReplayEngine(runner).replay_njr(_njr(), job=_job())

    assert len(attempts) == 1
    assert "checkpoint_callback" not in attempts[0]


def test_incompatible_runner_is_refused_before_invocation() -> None:
    calls = 0

    class _Incompatible:
        def run_njr(self, njr):  # cannot accept cancel_token/run_plan at all
            nonlocal calls
            calls += 1

    with pytest.raises(Exception) as excinfo:
        ReplayEngine(_Incompatible()).replay_njr(_njr(), job=_job())

    assert calls == 0
    assert "run_njr" in str(excinfo.value)


def test_runner_with_var_keyword_receives_checkpoint_callback_once() -> None:
    seen: list[dict[str, Any]] = []

    class _Kwargs:
        def run_njr(self, njr, *args, **kwargs):
            seen.append(kwargs)
            return {"status": "ok"}

    ReplayEngine(_Kwargs()).replay_njr(_njr(), job=_job())

    assert len(seen) == 1
    assert callable(seen[0]["checkpoint_callback"])


def test_supported_runner_receives_callback_once_and_checkpoint_is_persisted() -> None:
    persisted: list[int] = []
    job = _job()
    job._persist_runtime_state = lambda: persisted.append(
        len(job.execution_metadata.stage_checkpoints)
    )
    calls = 0

    class _Runner:
        def run_njr(
            self, njr, cancel_token=None, run_plan=None, log_fn=None, checkpoint_callback=None
        ):
            nonlocal calls
            calls += 1
            checkpoint_callback("txt2img", ["out/a.png"], {"image_count": 1})
            return {"status": "ok"}

    ReplayEngine(_Runner()).replay_njr(_njr(), job=job)

    assert calls == 1
    assert [c.stage_name for c in job.execution_metadata.stage_checkpoints] == ["txt2img"]
    assert job.execution_metadata.stage_checkpoints[0].output_paths == ["out/a.png"]
    assert persisted == [1]


def test_malformed_njr_fails_before_runner_invocation() -> None:
    calls = 0

    class _Runner:
        def run_njr(self, njr, cancel_token=None, run_plan=None, checkpoint_callback=None):
            nonlocal calls
            calls += 1

    with pytest.raises(ValueError, match="enabled stage"):
        ReplayEngine(_Runner()).replay_njr(
            SimpleNamespace(job_id="malformed"), job=_job("malformed")
        )

    assert calls == 0


@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("bad"), KeyError("k")])
def test_other_execution_exceptions_propagate_with_one_invocation(exc: Exception) -> None:
    calls = 0

    class _Runner:
        def run_njr(self, njr, cancel_token=None, run_plan=None, checkpoint_callback=None):
            nonlocal calls
            calls += 1
            raise exc

    with pytest.raises(type(exc)):
        ReplayEngine(_Runner()).replay_njr(_njr(), job=_job())

    assert calls == 1


def test_queue_path_does_not_replay_a_type_error_failure() -> None:
    runner = _DispatchThenTypeError()
    controller = JobExecutionController(replay_runner=runner)
    job = _job("queue-once")
    record = _njr("queue-once")
    job._normalized_record = record
    job.snapshot = {"normalized_job": record.to_dict()}
    controller.get_queue().submit(job)

    with pytest.raises(RuntimeError, match="NJR execution failed"):
        controller.get_runner().run_once(job)

    assert runner.dispatches == 1
    stored = controller.get_queue().get_job("queue-once")
    assert stored is not None and stored.status is JobStatus.FAILED
    assert (
        controller.get_queue().get_job("queue-once").execution_metadata.return_to_queue_count == 0
    )


def test_execute_job_adapter_wrapping_a_runner_resolves_before_calling() -> None:
    attempts: list[dict[str, Any]] = []

    class _Inner:
        def __call__(self, njr):
            raise AssertionError("the wrapped runner's run_njr must be preferred")

        def run_njr(self, njr, cancel_token=None, run_plan=None):
            attempts.append({"run_plan": run_plan})
            raise TypeError("failed after start")

    controller = JobExecutionController(execute_job=_Inner())
    job = _job("adapter-once")
    record = _njr("adapter-once")
    job._normalized_record = record
    job.snapshot = {"normalized_job": record.to_dict()}
    controller.get_queue().submit(job)

    with pytest.raises(RuntimeError, match="failed after start"):
        controller.get_runner().run_once(job)

    assert len(attempts) == 1
