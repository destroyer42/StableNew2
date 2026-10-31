"""PR-VID-UX-311: read-only readiness gates for a Comfy video workflow, answered before the job is queued.

Setup and dependency gates can block admission; RAM and GPU pressure are advisory. Injected probes only: no ComfyUI,
GPU or process. Dependencies needing a runtime that is not running are ``unknown`` and never block admission.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from src.video.comfy_runtime_setup import ComfyLaunchFacts
from src.video.managed_comfy_runtime import ManagedComfyContract
from src.video.workflow_preflight import (
    GATE_ADVISORY,
    GATE_BLOCKED,
    GATE_OK,
    GATE_UNKNOWN,
    PreflightProbes,
    default_preflight_probes,
    evaluate_workflow_preflight,
)
from src.video.workflow_registry import build_default_workflow_registry

TI2V = ("wan22_ti2v_5b_i2v_v1", "1.2.0")
ANIMATE = ("wan_animate2_drive_i2v_v1", "1.2.0")
FLAGS = ["--disable-pinned-memory", "--disable-auto-launch"]


def _spec(which: tuple[str, str]) -> Any:
    return build_default_workflow_registry().get(*which, allow_experimental=True)


def _object_info(spec: Any, *, drop_node: str | None = None, drop_file: str | None = None) -> dict:
    info: dict[str, Any] = {}
    for dep in spec.dependency_specs:
        if dep.dependency_kind == "stock_node" and dep.locator != drop_node:
            info[dep.locator] = {"input": {"required": {}}}
    for dep in spec.dependency_specs:
        if dep.dependency_kind != "model_file" or dep.locator == drop_file:
            continue
        loader, _, input_name = str(dep.version_hint).partition(".")
        node = info.setdefault(loader, {"input": {"required": {}}})
        node["input"]["required"].setdefault(input_name, [[]])[0].append(dep.locator)
    return info


def _stats(*, held_mib: float = 0.0) -> dict:
    mib = 1024 * 1024
    return {
        "devices": [
            {"type": "cuda", "index": 0, "torch_vram_total": held_mib * mib, "vram_free": 0}
        ]
    }


def _probes(
    spec: Any = None,
    *,
    command: tuple[str, ...] = ("python", "main.py", *FLAGS),
    autostart: bool = True,
    state: str = "free",
    ram_gb: float = 40.0,
    vram: tuple[float, float] | None = (12282.0, 11800.0),
    object_info: Any = "auto",
    stats: Any = None,
    managed: ManagedComfyContract | None = None,
) -> PreflightProbes:
    if object_info == "auto":
        object_info = _object_info(spec) if spec is not None else {}
    return PreflightProbes(
        command=command,
        base_url="http://127.0.0.1:8000",
        autostart=autostart,
        endpoint_state=lambda _url: state,
        fetch_object_info=lambda _url: object_info,
        fetch_system_stats=lambda _url: stats if stats is not None else _stats(),
        ram_probe=lambda: ram_gb,
        gpu_probe=lambda _index: vram,
        managed_contract=managed,
    )


def _gate(result: Any, gate_id: str) -> Any:
    return next(gate for gate in result.gates if gate.id == gate_id)


# ---------------------------------------------------------------------------
# an idle machine, ComfyUI not running
# ---------------------------------------------------------------------------


def test_an_idle_machine_is_queueable_and_the_runtime_only_gates_are_unknown() -> None:
    spec = _spec(TI2V)

    result = evaluate_workflow_preflight(spec, _probes(spec))

    assert result.queueable and result.block_reason == ""
    states = {gate.id: gate.state for gate in result.gates}
    assert states == {
        "runtime": GATE_OK,
        "nodes": GATE_UNKNOWN,
        "model_files": GATE_UNKNOWN,
        "vram": GATE_OK,
        "ram": GATE_OK,
    }
    assert "will start it" in _gate(result, "runtime").detail
    files = _gate(result, "model_files").detail
    assert "wan2.2_ti2v_5B_fp16.safetensors" in files and "SHA-256 456f901338bd9ead" in files


# ---------------------------------------------------------------------------
# launch flags
# ---------------------------------------------------------------------------


def test_missing_launch_flags_block_queue_and_name_the_fix() -> None:
    spec = _spec(ANIMATE)

    result = evaluate_workflow_preflight(spec, _probes(spec, command=("python", "main.py")))

    gate = _gate(result, "launch_flags")
    assert gate.state == GATE_BLOCKED and "--disable-pinned-memory" in gate.detail
    assert not result.queueable
    assert result.block_reason.startswith("Queue is off: Launch flags:")
    assert "Add required flags" in result.block_reason


def test_flags_present_pass_and_a_workflow_without_flags_has_no_such_gate() -> None:
    animate = _spec(ANIMATE)
    ok = evaluate_workflow_preflight(animate, _probes(animate))
    assert _gate(ok, "launch_flags").state == GATE_OK
    ti2v = _spec(TI2V)
    assert "launch_flags" not in {
        g.id for g in evaluate_workflow_preflight(ti2v, _probes(ti2v)).gates
    }


def test_a_running_comfy_with_no_command_cannot_prove_its_flags() -> None:
    spec = _spec(ANIMATE)

    result = evaluate_workflow_preflight(spec, _probes(spec, command=(), state="healthy"))

    gate = _gate(result, "launch_flags")
    assert gate.state == GATE_BLOCKED and "cannot have its flags verified" in gate.detail


# ---------------------------------------------------------------------------
# the runtime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"state": "occupied"}, "not a healthy ComfyUI"),
        ({"command": ()}, "no launch command is configured"),
        ({"autostart": False}, "automatic start is off"),
    ],
)
def test_an_unreachable_runtime_blocks_queue_with_the_reason(kwargs: dict, needle: str) -> None:
    spec = _spec(TI2V)

    result = evaluate_workflow_preflight(spec, _probes(spec, **kwargs))

    gate = _gate(result, "runtime")
    assert gate.state == GATE_BLOCKED and needle in gate.detail
    assert not result.queueable and "Queue is off: ComfyUI:" in result.block_reason


def test_a_healthy_runtime_is_ready_even_without_a_launch_command() -> None:
    spec = _spec(TI2V)

    result = evaluate_workflow_preflight(spec, _probes(spec, command=(), state="healthy"))

    assert _gate(result, "runtime").state == GATE_OK
    assert "running at" in _gate(result, "runtime").detail


# ---------------------------------------------------------------------------
# nodes and model files (only when ComfyUI is serving)
# ---------------------------------------------------------------------------


def test_a_serving_comfy_is_checked_for_every_pinned_node_and_file() -> None:
    spec = _spec(TI2V)

    ok = evaluate_workflow_preflight(spec, _probes(spec, state="healthy"))
    assert _gate(ok, "nodes").state == GATE_OK and _gate(ok, "model_files").state == GATE_OK
    assert "SHA-256" in _gate(ok, "model_files").detail

    no_node = evaluate_workflow_preflight(
        spec,
        _probes(spec, state="healthy", object_info=_object_info(spec, drop_node="CreateVideo")),
    )
    assert _gate(no_node, "nodes").state == GATE_BLOCKED
    assert "CreateVideo" in _gate(no_node, "nodes").detail and not no_node.queueable

    no_file = evaluate_workflow_preflight(
        spec,
        _probes(
            spec,
            state="healthy",
            object_info=_object_info(spec, drop_file="wan2.2_vae.safetensors"),
        ),
    )
    gate = _gate(no_file, "model_files")
    assert gate.state == GATE_BLOCKED and "wan2.2_vae.safetensors" in gate.detail
    assert not no_file.queueable and "Queue is off: Model files:" in no_file.block_reason


def test_an_unreadable_node_list_is_unknown_not_blocking() -> None:
    spec = _spec(TI2V)

    result = evaluate_workflow_preflight(spec, _probes(spec, state="healthy", object_info=None))

    assert _gate(result, "nodes").state == GATE_UNKNOWN
    assert _gate(result, "model_files").state == GATE_UNKNOWN
    assert result.queueable


# ---------------------------------------------------------------------------
# resource floors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ram_gb", [0.5, 4.0, 8.0, 15.0, 16.5])
@pytest.mark.parametrize("state", ["free", "healthy"])
def test_ram_is_advisory_without_a_startup_penalty(ram_gb: float, state: str) -> None:
    spec = _spec(TI2V)
    floor = spec.backend_defaults["resource_readiness"]["min_available_ram_gb"]
    result = evaluate_workflow_preflight(spec, _probes(spec, state=state, ram_gb=ram_gb))
    gate = _gate(result, "ram")
    assert result.queueable and result.block_reason == ""
    assert gate.state == (GATE_ADVISORY if ram_gb < floor else GATE_OK)
    assert f"{ram_gb:.1f} GB" in gate.detail
    assert "advisory" in gate.detail


@pytest.mark.parametrize("state", ["free", "healthy"])
def test_low_or_unreadable_gpu_memory_is_advisory_before_handoff(state: str) -> None:
    spec = _spec(TI2V)
    floor = spec.backend_defaults["resource_readiness"]["min_available_to_comfy_vram_mib"]

    low = evaluate_workflow_preflight(spec, _probes(spec, state=state, vram=(12282.0, floor - 500)))
    assert _gate(low, "vram").state == GATE_ADVISORY and low.queueable
    assert "Close other GPU applications" in _gate(low, "vram").detail
    assert "after runtime handoff" in _gate(low, "vram").detail

    unreadable = evaluate_workflow_preflight(spec, _probes(spec, state=state, vram=None))
    assert _gate(unreadable, "vram").state == GATE_ADVISORY and unreadable.queueable
    assert "could not be read" in _gate(unreadable, "vram").detail


def test_memory_comfy_already_holds_counts_toward_the_gpu_floor() -> None:
    spec = _spec(TI2V)
    floor = spec.backend_defaults["resource_readiness"]["min_available_to_comfy_vram_mib"]

    result = evaluate_workflow_preflight(
        spec,
        _probes(spec, state="healthy", vram=(12282.0, floor - 2000), stats=_stats(held_mib=3000)),
    )

    assert _gate(result, "vram").state == GATE_OK


def test_the_first_blocked_gate_is_the_one_queue_reports() -> None:
    spec = _spec(ANIMATE)

    result = evaluate_workflow_preflight(
        spec, _probes(spec, command=("python", "main.py"), ram_gb=1.0, vram=(12282.0, 100.0))
    )

    assert [g.id for g in result.blocking][:1] == ["launch_flags"]
    assert {g.id for g in result.blocking} == {"launch_flags"}
    assert {g.id for g in result.gates if g.state == GATE_ADVISORY} == {"vram", "ram"}
    assert "Launch flags" in result.block_reason and "System RAM" not in result.block_reason


def test_a_probe_that_raises_is_treated_as_an_endpoint_that_is_not_serving() -> None:
    spec = _spec(TI2V)

    def _boom(_url: str) -> str:
        raise OSError("socket closed")

    probes = _probes(spec)
    probes = PreflightProbes(**{**probes.__dict__, "endpoint_state": _boom})
    result = evaluate_workflow_preflight(spec, probes)

    assert result.runtime_state == "free"
    assert _gate(result, "runtime").state == GATE_OK


# ---------------------------------------------------------------------------
# the probe never acts
# ---------------------------------------------------------------------------


def test_the_default_probes_only_read_and_never_queue_or_start_anything(monkeypatch) -> None:
    spec = _spec(TI2V)
    calls: list[str] = []

    class _SpyClient:
        def __init__(self, base_url: str = "", **_kw: Any) -> None:
            self.base_url = base_url

        def get_object_info(self) -> dict:
            calls.append("get_object_info")
            return _object_info(spec)

        def get_system_stats(self) -> dict:
            calls.append("get_system_stats")
            return _stats()

        def __getattr__(self, name: str) -> Any:  # queue_prompt, upload_image, interrupt, ...
            def _forbidden(*_a: Any, **_k: Any) -> None:
                raise AssertionError(f"the readiness probe must not call {name}")

            return _forbidden

    def _no_process(*_a: Any, **_k: Any) -> None:
        raise AssertionError("the readiness probe must not start a process")

    monkeypatch.setattr("src.video.comfy_api_client.ComfyApiClient", _SpyClient)
    monkeypatch.setattr(
        "src.video.comfy_healthcheck.probe_comfy_endpoint", lambda *_a, **_k: "healthy"
    )
    monkeypatch.setattr(
        "src.video.comfy_process_manager.build_default_comfy_process_config",
        lambda _manager=None: None,
    )
    monkeypatch.setattr(
        "src.video.comfy_process_manager.read_comfy_launch_facts",
        lambda _manager=None: ComfyLaunchFacts(saved_command=()),
    )
    monkeypatch.setattr("psutil.virtual_memory", lambda: SimpleNamespace(available=24e9))
    monkeypatch.setattr(
        "src.video.workflow_readiness._driver_gpu_memory_mib", lambda _i=0: (12282.0, 11000.0)
    )
    monkeypatch.setattr(subprocess, "Popen", _no_process)

    result = evaluate_workflow_preflight(spec, default_preflight_probes())

    assert result.runtime_state == "healthy"
    assert sorted(set(calls)) == ["get_object_info", "get_system_stats"]
    assert _gate(result, "nodes").state == GATE_OK


def test_nothing_is_probed_for_a_serving_endpoint_that_is_not_comfy(monkeypatch) -> None:
    spec = _spec(TI2V)
    probes = _probes(spec, state="occupied")
    fetched: list[str] = []
    probes = PreflightProbes(
        **{
            **probes.__dict__,
            "fetch_object_info": lambda url: fetched.append(url) or {},
            "fetch_system_stats": lambda url: fetched.append(url) or {},
        }
    )

    evaluate_workflow_preflight(spec, probes)

    assert fetched == []  # an occupied endpoint is never asked for its node list
