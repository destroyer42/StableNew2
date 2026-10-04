"""PR-IMG-FORGE-100R: the executor's workload launch policy is capability-aware.

A guarded-profile recommendation is an optimization. It is applied only on a manager that declares the profile;
on a qualified A1111 without that profile, or on Forge, the runtime keeps its command, the recommendation is
recorded as not applied, and the existing pressure/admission checks still decide - unsafe pressure stays
fail-closed. Real managers, no process, no HTTP.
"""

from __future__ import annotations

import copy
import logging
from unittest.mock import Mock

import pytest

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager
from src.config import app_config
from src.pipeline.executor import Pipeline, PipelineStageError

MODEL = "cyberrealisticXL_v90-16fp.safetensors"
# The failed Pair-D chain: the 1.5x upscale of an 832x1216 image, an SDXL checkpoint, a heavy downstream stage.
UPSCALE_PRESSURE = {"status": "normal", "width": 1248, "height": 1824, "batch_size": 1, "steps": 24, "megapixels": 2.276}
QUALIFIED_A1111 = [r"C:\a1111\venv\Scripts\python.exe", "launch.py", "--xformers", "--api", "--port", "7860", "--ui-settings-file", r"C:\q\cfg.json"]
QUALIFIED_FORGE = [r"C:\forge\venv\Scripts\python.exe", "launch.py", "--uv", "--api", "--port", "7871", "--data-dir", r"C:\forge\data", "--skip-install"]


class _Recorder:
    def __init__(self) -> None:
        self.restarts: list[dict] = []

    def attach(self, manager: WebUIProcessManager, *, succeeds: bool = True) -> None:
        def restart(**kwargs):
            self.restarts.append(dict(kwargs))
            return succeeds

        manager.restart_webui = restart  # type: ignore[method-assign]


def _manager(monkeypatch, *, identity: str, command: list[str], profiles=None) -> tuple[WebUIProcessManager, _Recorder]:
    manager = WebUIProcessManager(
        WebUIProcessConfig(command=list(command), working_dir=r"C:\runtime", env_overrides={"X": "1"},
                           base_url="http://127.0.0.1:7860", runtime_identity=identity, launch_profile_commands=profiles)
    )
    recorder = _Recorder()
    recorder.attach(manager)
    monkeypatch.setattr(WebUIProcessManager, "owns_process", property(lambda self: True))
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)
    return manager, recorder


def _pipeline() -> Pipeline:
    client = Mock()
    client.check_connection.return_value = True
    client.get_runtime_failure_state.return_value = {}
    client.get_progress_snapshot.return_value = None
    pipeline = Pipeline(client, Mock())
    pipeline._current_stage_chain = ["txt2img", "adetailer", "upscale"]
    pipeline._current_stage_index = 2
    return pipeline


@pytest.fixture(autouse=True)
def _quiet_host(monkeypatch):
    monkeypatch.setattr("src.pipeline.executor.collect_process_risk_snapshot", lambda: {"status": "normal"})
    before = app_config.get_webui_launch_profile()
    yield
    app_config.set_webui_launch_profile(before)


def _snapshot(manager):
    c = manager._config
    return (tuple(c.command), c.working_dir, dict(c.env_overrides or {}), manager.runtime_identity, c.launch_profile)


@pytest.mark.parametrize(
    ("identity", "command", "profiles"),
    [("a1111_webui", QUALIFIED_A1111, None), ("forge_webui", QUALIFIED_FORGE, None), ("forge_webui", QUALIFIED_FORGE, {})],
)
def test_the_guarded_recommendation_is_not_applied_and_the_qualified_runtime_is_untouched(
    monkeypatch, caplog, identity, command, profiles
):
    manager, recorder = _manager(monkeypatch, identity=identity, command=command, profiles=profiles)
    before = _snapshot(manager)

    with caplog.at_level(logging.WARNING):
        applied = _pipeline()._maybe_apply_workload_launch_policy(
            stage_name="upscale", requested_model=MODEL, pressure_assessment=UPSCALE_PRESSURE
        )

    assert applied == "standard"  # the runtime's own profile, not the recommendation
    assert recorder.restarts == []  # no restart was even requested
    assert _snapshot(manager) == before  # command byte-for-byte, working_dir, env, identity, profile
    assert "workload_launch_profile_unsupported" in caplog.text and "recommendation_not_applied" in caplog.text


def test_a_manager_that_declares_the_profile_still_gets_the_guarded_restart(monkeypatch):
    profiles = app_config.get_webui_launch_profile_commands()
    manager, recorder = _manager(monkeypatch, identity="a1111_webui", command=["webui-user.bat", "--api", "--xformers"], profiles=profiles)

    applied = _pipeline()._maybe_apply_workload_launch_policy(
        stage_name="upscale", requested_model=MODEL, pressure_assessment=UPSCALE_PRESSURE
    )

    assert applied == "sdxl_guarded"  # normal production A1111 behavior is unchanged
    assert [r["profile_override"] for r in recorder.restarts] == ["sdxl_guarded"]


def test_a_qualification_a1111_that_supplies_its_own_guarded_command_keeps_its_own_flags(monkeypatch):
    own = {"sdxl_guarded": [*QUALIFIED_A1111, "--medvram-sdxl"]}
    manager, recorder = _manager(monkeypatch, identity="a1111_webui", command=QUALIFIED_A1111, profiles=own)

    assert _pipeline()._maybe_apply_workload_launch_policy(
        stage_name="upscale", requested_model=MODEL, pressure_assessment=UPSCALE_PRESSURE
    ) == "sdxl_guarded"
    assert [r["profile_override"] for r in recorder.restarts] == ["sdxl_guarded"]
    # applying through the real manager (not the recorder) yields the qualification command, never webui-user.bat
    real = WebUIProcessManager(WebUIProcessConfig(command=QUALIFIED_A1111, launch_profile_commands=own))
    assert real.set_launch_profile("sdxl_guarded") and real._config.command == own["sdxl_guarded"]
    assert "webui-user.bat" not in real._config.command


def test_a_direct_recovery_request_with_an_unsupported_profile_is_skipped_without_touching_the_runtime(monkeypatch):
    manager, recorder = _manager(monkeypatch, identity="forge_webui", command=QUALIFIED_FORGE)
    before = _snapshot(manager)

    assert _pipeline()._attempt_webui_recovery(stage="upscale", reason="x", profile_override="sdxl_guarded") is False

    assert recorder.restarts == [] and _snapshot(manager) == before


def test_heavy_but_not_unsafe_pressure_proceeds_degraded_on_an_unsupported_runtime_without_a_restart(monkeypatch):
    manager, recorder = _manager(monkeypatch, identity="forge_webui", command=QUALIFIED_FORGE)
    before = _snapshot(manager)

    state = _pipeline()._ensure_runtime_admissible(stage_name="upscale", pressure_assessment={"status": "high_pressure"})

    assert state["status"] == "degraded"  # admitted exactly as an external/unguarded runtime always was
    assert "unguarded_heavy_workload" in [c["code"] for c in state["runtime_causes"]]
    assert {"step": "launch_profile_unsupported", "profile": "sdxl_guarded", "applied": False} in state["recovery_trace"]
    assert recorder.restarts == [] and _snapshot(manager) == before


def test_unsafe_pressure_remains_fail_closed_when_the_guarded_profile_cannot_be_applied(monkeypatch):
    """The repair must not weaken admission: unsafe upscale pressure is refused, never waved through."""

    manager, recorder = _manager(monkeypatch, identity="a1111_webui", command=QUALIFIED_A1111)
    before = _snapshot(manager)

    with pytest.raises(PipelineStageError, match="Runtime admission refused before upscale"):
        _pipeline()._ensure_runtime_admissible(stage_name="upscale", pressure_assessment={"status": "unsafe"})

    assert recorder.restarts == [] and _snapshot(manager) == before


def test_unsafe_pressure_on_a_supporting_manager_still_attempts_the_guarded_restart(monkeypatch):
    profiles = app_config.get_webui_launch_profile_commands()
    manager, recorder = _manager(monkeypatch, identity="a1111_webui", command=["webui-user.bat", "--api"], profiles=profiles)

    try:
        _pipeline()._ensure_runtime_admissible(stage_name="upscale", pressure_assessment={"status": "unsafe"})
    except PipelineStageError:
        pass  # the fake restart does not change the (mocked) pressure; only the attempt matters here

    assert [r["profile_override"] for r in recorder.restarts] == ["sdxl_guarded"]


def test_a_poisoned_runtime_is_still_recovered_with_its_own_command_when_guarded_is_unsupported(monkeypatch):
    manager, recorder = _manager(monkeypatch, identity="forge_webui", command=QUALIFIED_FORGE)
    pipeline = _pipeline()
    alive = {"up": False}
    pipeline.client.check_connection.side_effect = lambda **_k: alive["up"]

    def restart(**kwargs):
        recorder.restarts.append(dict(kwargs))
        alive["up"] = True
        return True

    manager.restart_webui = restart  # type: ignore[method-assign]
    before = _snapshot(manager)

    state = pipeline._ensure_runtime_admissible(stage_name="adetailer", pressure_assessment={"status": "high_pressure"})

    assert state["status"] in {"healthy", "degraded"}
    assert [r["profile_override"] for r in recorder.restarts] == [None]  # a plain restart: no profile swap
    assert _snapshot(manager) == before


def test_policy_decisions_never_mutate_a_shared_profile_map(monkeypatch):
    shared = app_config.get_webui_launch_profile_commands()
    frozen = copy.deepcopy(shared)
    manager, _ = _manager(monkeypatch, identity="a1111_webui", command=["webui-user.bat"], profiles=shared)
    manager.set_launch_profile("sdxl_guarded")
    manager._config.command.append("--mutated")

    assert shared == frozen  # the manager copies the declared command; the map is not aliased
