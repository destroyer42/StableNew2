"""PR-VID-130 acceptance harness: guaranteed, ownership-safe teardown (no GPU, no Comfy, no queue).

The real run once orphaned the StableNew-launched Comfy because cleanup only covered ``run_once``.
These tests prove cleanup happens on every exit path after the runtime stack exists, releases only
a process the managed manager owns, and never masks or flips the run's own outcome.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.video.comfy_process_manager import ComfyProcessConfig, ComfyProcessManager
from tools.acceptance import vid130_wan_acceptance as harness


class _Manager:
    def __init__(self, *, owned: bool) -> None:
        self.owns_process = owned
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


def _registry(manager: object | None):
    backend = SimpleNamespace(_managed_process_manager=manager)
    return SimpleNamespace(get=lambda name: backend if name == "comfy" else None)


class _Fakes:
    """Counting stand-ins for the queue-side objects the harness must always release."""

    def __init__(self, manager: _Manager | None) -> None:
        self.manager = manager
        self.runner_stops = 0
        self.repo_closes = 0
        self.order: list[str] = []
        self.service = SimpleNamespace(runner=SimpleNamespace(stop=self._runner_stop))
        self.repository = SimpleNamespace(close=self._repo_close)

    def _runner_stop(self) -> None:
        self.runner_stops += 1
        self.order.append("runner")

    def _repo_close(self) -> None:
        self.repo_closes += 1
        self.order.append("repository")

    def populate(self, stack: harness._Stack) -> None:
        stack.registry = _registry(self.manager)
        stack.service = self.service
        stack.repository = self.repository


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(harness, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    return tmp_path / "reports" / "acceptance.json"


def _args() -> argparse.Namespace:
    return argparse.Namespace(source="s.png", prompt="p", dry=False)


def test_an_exception_after_run_njr_still_stops_the_owned_comfy_and_releases_everything(
    monkeypatch, isolated
) -> None:
    fakes = _Fakes(_Manager(owned=True))
    ran: list[str] = []

    def run_then_fail_in_evidence_processing(stack, args, evidence, workspace):
        fakes.populate(stack)
        ran.append("run_njr completed")  # the job itself succeeded ...
        evidence["status"] = "completed"
        raise OSError("artifact inspection failed")  # ... then closeout work raised

    monkeypatch.setattr(harness, "_run", run_then_fail_in_evidence_processing)
    with pytest.raises(OSError, match="artifact inspection failed"):  # failure is not swallowed
        harness.run_acceptance(_args())

    assert ran == ["run_njr completed"]
    assert fakes.manager.stop_calls == 1  # the owned Comfy is not orphaned
    assert fakes.runner_stops == 1 and fakes.repo_closes == 1
    evidence = json.loads(isolated.read_text(encoding="utf-8"))  # partial evidence preserved
    assert evidence["status"] == "completed" and "artifact inspection failed" in evidence["aborted"]
    assert evidence["managed_comfy_owned"] is True and evidence["teardown_errors"] == []


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit, RuntimeError])
def test_teardown_runs_for_every_exception_kind_including_interrupts(
    monkeypatch, isolated, exception
) -> None:
    fakes = _Fakes(_Manager(owned=True))

    def fail(stack, *_a):
        fakes.populate(stack)
        raise exception()

    monkeypatch.setattr(harness, "_run", fail)
    with pytest.raises(exception):
        harness.run_acceptance(_args())
    assert (fakes.manager.stop_calls, fakes.runner_stops, fakes.repo_closes) == (1, 1, 1)


def test_a_partially_built_stack_is_still_torn_down(monkeypatch, isolated) -> None:
    manager = _Manager(owned=True)

    def fail_mid_build(stack, *_a):
        stack.registry = _registry(manager)  # service/repository were never created
        raise RuntimeError("controller construction failed")

    monkeypatch.setattr(harness, "_run", fail_mid_build)
    with pytest.raises(RuntimeError, match="controller construction"):
        harness.run_acceptance(_args())
    assert manager.stop_calls == 1


def test_an_external_or_unowned_comfy_is_never_stopped(monkeypatch, isolated) -> None:
    for manager in (_Manager(owned=False), None):  # adopted/external, or nothing managed at all
        fakes = _Fakes(manager)

        def run(stack, *_a, _fakes=fakes):
            _fakes.populate(stack)
            return 0

        monkeypatch.setattr(harness, "_run", run)
        assert harness.run_acceptance(_args()) == 0
        if manager is not None:
            assert manager.stop_calls == 0  # not even asked to stop
        assert fakes.runner_stops == 1 and fakes.repo_closes == 1


def test_the_real_manager_never_terminates_a_process_it_does_not_own() -> None:
    """Belt and braces: even if ``stop`` were called, a non-owning manager leaves the process alone."""

    process = Mock()
    process.poll.return_value = None  # a live external Comfy
    manager = ComfyProcessManager(ComfyProcessConfig(command=["comfy"], base_url="http://x"))
    manager._process = process
    manager._owns_process = False  # adopted/external: never launched by this manager
    assert manager.owns_process is False
    assert harness._stop_owned_comfy(_registry(manager)) is False
    manager.stop()
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


def test_the_real_manager_terminates_only_the_process_it_launched() -> None:
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0
    manager = ComfyProcessManager(ComfyProcessConfig(command=["comfy"], base_url="http://x"))
    manager._process = process
    manager._owns_process = True  # launched by this manager's own start()
    assert harness._stop_owned_comfy(_registry(manager)) is True
    process.terminate.assert_called_once()
    assert manager.owns_process is False


def test_a_failing_teardown_step_does_not_skip_the_rest_and_never_masks_the_outcome(
    monkeypatch, isolated, capsys
) -> None:
    fakes = _Fakes(_Manager(owned=True))
    fakes.manager.stop = Mock(side_effect=RuntimeError("stop failed"))

    def succeed(stack, *_a):
        fakes.populate(stack)
        return 0

    monkeypatch.setattr(harness, "_run", succeed)
    assert harness.run_acceptance(_args()) == 1  # success is downgraded, not hidden
    assert fakes.runner_stops == 1 and fakes.repo_closes == 1  # later steps still ran
    assert "stop_owned_comfy: RuntimeError: stop failed" in capsys.readouterr().err

    # ... and it cannot replace the run's own exception.
    def fail(stack, *_a):
        fakes.populate(stack)
        raise ValueError("the real failure")

    monkeypatch.setattr(harness, "_run", fail)
    with pytest.raises(ValueError, match="the real failure"):
        harness.run_acceptance(_args())


def test_cleanup_never_turns_a_failed_acceptance_into_success(monkeypatch, isolated) -> None:
    fakes = _Fakes(_Manager(owned=True))

    def failed_job(stack, *_a):
        fakes.populate(stack)
        return 1

    monkeypatch.setattr(harness, "_run", failed_job)
    assert harness.run_acceptance(_args()) == 1
    assert fakes.manager.stop_calls == 1


def test_main_stops_before_building_anything_when_an_external_comfy_is_serving(
    monkeypatch, capsys
) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_acceptance", lambda *_a: built.append("ran") or 0)
    assert harness.main(["s.png", "p"]) == 3
    assert built == []  # no stack, no launch, nothing stopped
    assert "never adopts or restarts" in capsys.readouterr().out


def test_real_run_path_cleans_up_when_evidence_processing_fails_after_a_successful_job(
    monkeypatch, isolated, tmp_path: Path
) -> None:
    """The real ``_run`` (controller -> NJR -> queue -> run_njr -> backend) with a fake Comfy backend:
    the job completes, *then* post-run evidence processing raises; the owned Comfy is still stopped."""

    from PIL import Image

    from src.video import video_backend_registry as registry_module
    from src.video.video_backend_registry import VideoBackendRegistry
    from src.video.video_backend_types import (
        CONTROL_NEGATIVE_PROMPT,
        CONTROL_PROMPT_TEXT,
        CONTROL_SOURCE_IMAGE,
        VideoBackendCapabilities,
        VideoExecutionResult,
    )

    manager = _Manager(owned=True)
    executed: list[str] = []

    class _FakeComfy:
        backend_id = "comfy"
        capabilities = VideoBackendCapabilities(
            backend_id="comfy",
            controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
            required_controls=(CONTROL_SOURCE_IMAGE,),
        )
        _managed_process_manager = manager

        def execute(self, pipeline, request):
            executed.append(request.job_id)
            video = Path(request.output_dir) / "wan.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"mp4")
            return VideoExecutionResult.from_stage_result(
                backend_id="comfy",
                stage_name=request.stage_name,
                result={"path": str(video), "video_path": str(video), "output_paths": [str(video)]},
            )

    def fake_registry() -> VideoBackendRegistry:
        registry = VideoBackendRegistry()
        registry.register(_FakeComfy())
        return registry

    monkeypatch.setattr(registry_module, "build_default_video_backend_registry", fake_registry)
    monkeypatch.setattr(harness, "_collect_completed_evidence", Mock(side_effect=OSError("boom")))
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "navy").save(source)

    with pytest.raises(OSError, match="boom"):
        harness.run_acceptance(argparse.Namespace(source=str(source), prompt="the child waves"))

    assert len(executed) == 1  # run_njr really executed the job before the failure
    assert manager.stop_calls == 1  # ... and the owned Comfy was still stopped
    evidence = json.loads(isolated.read_text(encoding="utf-8"))
    assert evidence["status"] == "completed" and evidence["managed_comfy_owned"] is True
    assert evidence["njr_video_execution"]["experimental_opt_in"] is True
