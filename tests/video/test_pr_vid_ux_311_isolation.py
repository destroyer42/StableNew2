"""PR-VID-UX-311: runtime readiness reads only the app's own settings, never the repository's managed-runtime file.

An isolated operator journey runs the app in a child process, so a pytest fixture cannot stand in for the probes there;
the app itself must take its Comfy launch command from the ConfigManager it was built with. These tests fail on any read
of ``config/managed_comfy_runtime.json`` or any load of its contract from the preflight, the controller path that feeds
the Video Workflow strip, and the global operator-readiness row (with and without a Comfy command configured).
"""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.video_preflight_controller import VideoPreflightControllerMixin
from src.services.operator_readiness_service import (
    OperatorReadinessState,
    configured_comfy_command,
)
from src.video.workflow_preflight import (
    GATE_BLOCKED,
    GATE_OK,
    default_preflight_probes,
    evaluate_workflow_preflight,
)
from src.video.workflow_registry import build_default_workflow_registry
from tests.services.test_operator_readiness_service import _service

PROTECTED = "managed_comfy_runtime"
ANIMATE = ("wan_animate2_drive_i2v_v1", "1.2.0")  # declares required launch flags


class _Settings:
    """The app's own ConfigManager stand-in: settings from memory, no file."""

    def __init__(self, command: list[str] | None) -> None:
        self._values = {"comfy_command": command or [], "comfy_base_url": "http://127.0.0.1:8188"}

    def _load_settings(self) -> dict[str, Any]:
        return dict(self._values)

    def load_settings(self) -> dict[str, Any]:
        return dict(self._values)


@pytest.fixture
def protected_reads(monkeypatch) -> list[str]:
    """Fail on any read of the managed-runtime manifest or load of its contract."""

    seen: list[str] = []

    def _guard(path: Any) -> None:
        if PROTECTED in str(path):
            seen.append(str(path))
            raise AssertionError(f"isolation: read operator-owned file {path}")

    real_open = builtins.open
    real_read_text = Path.read_text
    real_read_bytes = Path.read_bytes

    def _open(file, *args, **kwargs):
        _guard(file)
        return real_open(file, *args, **kwargs)

    def _read_text(self, *args, **kwargs):
        _guard(self)
        return real_read_text(self, *args, **kwargs)

    def _read_bytes(self, *args, **kwargs):
        _guard(self)
        return real_read_bytes(self, *args, **kwargs)

    def _contract(*_a: Any, **_k: Any) -> None:
        seen.append("load_managed_comfy_contract")
        raise AssertionError("isolation: the managed-runtime contract must not be loaded")

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(Path, "read_text", _read_text)
    monkeypatch.setattr(Path, "read_bytes", _read_bytes)
    monkeypatch.setattr("src.video.managed_comfy_runtime.load_managed_comfy_contract", _contract)
    return seen


@pytest.fixture
def offline(monkeypatch) -> None:
    # The suite-wide hermetic stub stands in for the probes; these tests are about the real ones.
    monkeypatch.setattr(
        "src.controller.video_preflight_controller.default_preflight_probes",
        default_preflight_probes,
    )
    monkeypatch.setattr(
        "src.video.comfy_healthcheck.probe_comfy_endpoint", lambda *_a, **_k: "free"
    )
    monkeypatch.setattr(
        "src.video.workflow_readiness._driver_gpu_memory_mib", lambda _i=0: (12282.0, 11000.0)
    )


class _Controller(VideoPreflightControllerMixin):
    def __init__(self, config_manager: Any) -> None:
        self._app_controller = SimpleNamespace(_config_manager=config_manager)
        self._workflow_registry = DefaultWorkflowRegistryPort()
        self._preflight_probes = None


@pytest.mark.parametrize(
    ("command", "flags_state"),
    [([], GATE_BLOCKED), (["python", "main.py"], GATE_BLOCKED)],
)
def test_the_controller_preflight_reads_the_apps_settings_not_the_managed_manifest(
    protected_reads, offline, command, flags_state
) -> None:
    result = _Controller(_Settings(command)).workflow_preflight(*ANIMATE)

    assert protected_reads == []
    gates = {gate.id: gate for gate in result.gates}
    # The flags gate is answered from the configured command alone (no contract needed): a command
    # without the required flags, or none at all, is a proven shortfall; it is not "unknown".
    assert gates["launch_flags"].state == flags_state


def test_a_command_with_the_required_flags_passes_without_the_manifest(
    protected_reads, offline
) -> None:
    spec = build_default_workflow_registry().get_offerable(*ANIMATE)
    from src.video.workflow_readiness import required_launch_flags

    command = ["python", "main.py", *required_launch_flags(spec)]

    result = _Controller(_Settings(command)).workflow_preflight(*ANIMATE)

    assert protected_reads == []
    assert {gate.id: gate for gate in result.gates}["launch_flags"].state == GATE_OK


def test_the_default_probes_take_the_command_from_the_given_settings(
    protected_reads, offline
) -> None:
    probes = default_preflight_probes(config_manager=_Settings(["python", "main.py"]))

    assert protected_reads == []
    assert probes.command == ("python", "main.py")
    assert probes.managed_contract is None
    evaluate_workflow_preflight(build_default_workflow_registry().get_offerable(*ANIMATE), probes)
    assert protected_reads == []


@pytest.mark.parametrize(
    ("command", "state"),
    [((), OperatorReadinessState.OPTIONAL), (("python", "main.py"), OperatorReadinessState.READY)],
)
def test_the_global_readiness_row_never_loads_the_managed_manifest(
    tmp_path, protected_reads, command, state
) -> None:
    record = (
        _service(tmp_path, comfy_command_provider=lambda: command)
        .collect()
        .record_for("comfy_video_runtime")
    )

    assert protected_reads == []
    assert record is not None and record.state is state


def test_the_configured_command_comes_from_the_given_settings(protected_reads, monkeypatch) -> None:
    monkeypatch.delenv("STABLENEW_COMFY_COMMAND", raising=False)

    assert configured_comfy_command(_Settings(["python", "main.py"])) == ("python", "main.py")
    assert configured_comfy_command(_Settings(None)) == ()
    assert protected_reads == []


def test_the_real_managed_contract_still_resolves_outside_the_isolated_paths() -> None:
    """The production contract is unchanged: only the readiness paths stopped reading it."""

    from src.video.managed_comfy_runtime import load_managed_comfy_contract

    contract = load_managed_comfy_contract()

    assert contract.required_flags
