"""PR-VID-UX-340: Comfy launch configuration truth, ownership-aware flag gating and the guided-repair projection.

Toolkit-neutral. Saved / environment / active / observed evidence are driven through ``ComfyLaunchFacts`` and injected
probes; no ComfyUI, GPU, network or process is touched, and every test that reads the app's own readers proves that
nothing was started, stopped or queued.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.view_contracts.video_runtime_readiness_contract import RuntimeReadinessSession
from src.utils.config import ConfigManager
from src.video import comfy_process_manager as cpm
from src.video.comfy_process_manager import (
    ComfyProcessConfig,
    ComfyProcessManager,
    build_default_comfy_process_config,
    clear_global_comfy_process_manager,
    read_comfy_launch_facts,
)
from src.video.comfy_runtime_setup import (
    ACTION_FIX_COMFY_SETUP,
    ComfyLaunchFacts,
    environment_override_notice,
    resolve_launch_command,
    restart_pending_notice,
)
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.managed_comfy_runtime import (
    load_managed_comfy_contract,
    with_required_flags,
)
from src.video.workflow_preflight import (
    GATE_BLOCKED,
    GATE_OK,
    PreflightProbes,
    evaluate_workflow_preflight,
)
from src.video.workflow_registry import build_default_workflow_registry

TI2V = ("wan22_ti2v_5b_i2v_v1", "1.2.0")
ANIMATE = ("wan_animate2_drive_i2v_v1", "1.2.0")
PIN = "--disable-pinned-memory"
AUTO = "--disable-auto-launch"
GOOD = ("python", "main.py", PIN, AUTO)
BARE = ("python", "main.py")


def _spec(which: tuple[str, str]) -> Any:
    return build_default_workflow_registry().get(*which, allow_experimental=True)


def _probes(
    launch: ComfyLaunchFacts | None,
    *,
    state: str = "free",
    autostart: bool = True,
    ram_gb: float = 40.0,
    vram: tuple[float, float] | None = (12282.0, 11800.0),
    object_info: Any = None,
) -> PreflightProbes:
    command = launch.effective_command if launch is not None else ()
    return PreflightProbes(
        command=command,
        base_url="http://127.0.0.1:8000",
        autostart=autostart,
        endpoint_state=lambda _url: state,
        fetch_object_info=lambda _url: object_info,
        fetch_system_stats=lambda _url: None,
        ram_probe=lambda: ram_gb,
        gpu_probe=lambda _index: vram,
        launch=launch,
    )


def _gate(result: Any, gate_id: str) -> Any:
    return next(gate for gate in result.gates if gate.id == gate_id)


def _facts(**kw: Any) -> ComfyLaunchFacts:
    return ComfyLaunchFacts(**kw)


# --------------------------------------------------------------------------- the projection itself


def test_the_environment_override_wins_over_the_saved_command_as_documented() -> None:
    assert resolve_launch_command(GOOD, ("python", "env.py")).command == ("python", "env.py")
    assert resolve_launch_command(GOOD, ("python", "env.py")).source == "environment"
    assert resolve_launch_command(GOOD, ()).source == "settings"
    assert resolve_launch_command((), ()).source == "none"


def test_saved_active_and_environment_facts_stay_distinct() -> None:
    saved_only = _facts(saved_command=GOOD)
    assert saved_only.active_command is None and not saved_only.restart_pending
    assert (
        saved_only.command_in_force == GOOD
    )  # no launcher yet: a launch would use what startup resolves

    stale = _facts(saved_command=GOOD, active_command=BARE)
    assert stale.restart_pending and stale.command_in_force == BARE
    assert "restart" in restart_pending_notice(stale).lower()

    overridden = _facts(saved_command=GOOD, environment_command=BARE, active_command=BARE)
    assert overridden.effective_command == BARE and overridden.environment_overrides_saved
    assert not overridden.restart_pending  # the launcher already runs the environment command
    assert "STABLENEW_COMFY_COMMAND" in environment_override_notice(overridden)
    assert "outside StableNew" in environment_override_notice(overridden)
    assert environment_override_notice(saved_only) == ""


# --------------------------------------------------------------------------- real readers


class _Settings:
    def __init__(self, command: list[str] | None) -> None:
        self._values = {"comfy_command": command or [], "comfy_base_url": "http://127.0.0.1:8188"}

    def _load_settings(self) -> dict[str, Any]:
        return dict(self._values)

    def load_settings(self) -> dict[str, Any]:
        return dict(self._values)


@pytest.fixture(autouse=True)
def _no_global_manager_or_env(monkeypatch):
    monkeypatch.delenv("STABLENEW_COMFY_COMMAND", raising=False)
    clear_global_comfy_process_manager()
    yield
    clear_global_comfy_process_manager()


def test_startup_resolution_and_the_default_config_agree_the_environment_wins(monkeypatch) -> None:
    monkeypatch.setenv("STABLENEW_COMFY_COMMAND", "python env_main.py")

    config = build_default_comfy_process_config(_Settings(list(GOOD)))

    assert config is not None and config.command == ["python", "env_main.py"]
    facts = read_comfy_launch_facts(_Settings(list(GOOD)))
    assert facts.saved_command == GOOD and facts.effective_command == ("python", "env_main.py")
    assert facts.effective_source == "environment" and facts.environment_overrides_saved


def test_active_facts_come_from_the_registered_launcher_and_reading_never_starts_it() -> None:
    def _no_launch(*_a: Any, **_k: Any) -> None:
        raise AssertionError("reading the launch facts must not start a process")

    manager = ComfyProcessManager(
        ComfyProcessConfig(command=list(BARE), base_url="http://127.0.0.1:8188"),
        process_factory=_no_launch,
    )

    facts = read_comfy_launch_facts(_Settings(list(GOOD)))

    assert facts.active_command == BARE and facts.saved_command == GOOD
    assert facts.restart_pending and not facts.owns_runtime  # registered, but nothing launched
    assert not manager.owns_process and manager.pid is None


def test_a_released_launcher_still_pins_the_active_command_until_restart() -> None:
    manager = ComfyProcessManager(ComfyProcessConfig(command=list(BARE)))
    manager.stop()  # a runtime released after a job unregisters the manager

    facts = read_comfy_launch_facts(_Settings(list(GOOD)))

    assert facts.active_command == BARE and not facts.owns_runtime
    assert facts.restart_pending and facts.command_in_force == BARE


def test_a_command_with_spaces_round_trips_through_settings_exactly(tmp_path) -> None:
    command = [
        r"C:\Program Files\Stable New\venv\Scripts\python.exe",
        r"D:\My Models\ComfyUI source\main.py",
        "--extra-model-paths-config",
        r"D:\My Models\extra model paths.yaml",
        AUTO,
    ]
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "settings.json").write_text(json.dumps({"comfy_command": command}), encoding="utf-8")
    manager = ConfigManager(presets_dir=presets, packs_dir=tmp_path / "packs")

    config = build_default_comfy_process_config(manager)
    assert config is not None and config.command == command
    assert read_comfy_launch_facts(manager).saved_command == tuple(command)

    repaired = with_required_flags(command, load_managed_comfy_contract().required_flags)
    assert repaired == [*command, PIN]  # each argument exactly once, nothing re-split or re-ordered
    assert with_required_flags(repaired, [PIN, AUTO]) == repaired  # a second repair adds nothing


def test_the_pinned_managed_policy_is_unchanged() -> None:
    assert load_managed_comfy_contract().required_flags == (PIN, AUTO)


# --------------------------------------------------------------------------- the launch-flags gate


def test_no_launch_configuration_is_a_repairable_blocker() -> None:
    spec = _spec(ANIMATE)

    result = evaluate_workflow_preflight(spec, _probes(_facts()))

    gate = _gate(result, "launch_flags")
    assert gate.state == GATE_BLOCKED and gate.action == ACTION_FIX_COMFY_SETUP
    assert "no launch command is configured" in gate.detail and "managed install" in gate.fix
    assert result.setup_repair_available and not result.queueable
    assert result.setup_repair_reason.startswith("Launch flags:")


def test_a_command_missing_the_flag_is_repairable_and_a_present_flag_is_not_a_blocker() -> None:
    spec = _spec(ANIMATE)

    missing = evaluate_workflow_preflight(spec, _probes(_facts(saved_command=BARE)))
    assert _gate(missing, "launch_flags").state == GATE_BLOCKED
    assert _gate(missing, "launch_flags").action == ACTION_FIX_COMFY_SETUP
    assert PIN in missing.block_reason and "Add required flags" in missing.block_reason

    ok = evaluate_workflow_preflight(spec, _probes(_facts(saved_command=GOOD)))
    assert _gate(ok, "launch_flags").state == GATE_OK and ok.queueable
    assert (
        "will start" in _gate(ok, "runtime").detail
    )  # ready for managed startup, not "already running"
    assert not ok.setup_repair_available


def test_a_saved_fix_is_not_proof_that_the_running_launcher_has_the_flag() -> None:
    spec = _spec(ANIMATE)
    facts = _facts(saved_command=GOOD, active_command=BARE)

    result = evaluate_workflow_preflight(spec, _probes(facts))

    gate = _gate(result, "launch_flags")
    assert gate.state == GATE_BLOCKED and not result.queueable
    assert "not applied" in gate.detail or "not applied it" in gate.detail
    assert "Restart StableNew" in gate.fix
    assert gate.action == "" and not result.setup_repair_available  # the repair is already saved
    assert result.notices and "must restart" in result.notices[0]


def test_an_environment_override_missing_the_flag_is_not_hidden_by_a_good_saved_command() -> None:
    spec = _spec(ANIMATE)
    facts = _facts(saved_command=GOOD, environment_command=BARE)

    result = evaluate_workflow_preflight(spec, _probes(facts))

    gate = _gate(result, "launch_flags")
    assert gate.state == GATE_BLOCKED and "STABLENEW_COMFY_COMMAND" in gate.detail
    assert "outside StableNew" in gate.fix and gate.action == ""  # Engine Settings cannot change it
    assert any("overrides Engine Settings" in note for note in result.notices)


def test_an_environment_command_with_the_flag_passes_and_says_where_it_came_from() -> None:
    spec = _spec(ANIMATE)
    facts = _facts(saved_command=BARE, environment_command=GOOD)

    result = evaluate_workflow_preflight(spec, _probes(facts))

    assert _gate(result, "launch_flags").state == GATE_OK
    assert any("STABLENEW_COMFY_COMMAND" in note for note in result.notices)


def test_an_unowned_serving_comfy_is_never_qualified_by_the_saved_command() -> None:
    spec = _spec(ANIMATE)

    external = evaluate_workflow_preflight(
        spec, _probes(_facts(saved_command=GOOD), state="healthy", object_info={})
    )
    gate = _gate(external, "launch_flags")
    assert gate.state == GATE_BLOCKED and "did not launch" in gate.detail
    assert "will not adopt, stop or restart" in gate.detail
    assert (
        gate.action == "" and not external.queueable
    )  # an operator-side stop, not an Engine Settings fix

    owned = evaluate_workflow_preflight(
        spec,
        _probes(
            _facts(saved_command=GOOD, active_command=GOOD, owns_runtime=True),
            state="healthy",
            object_info={},
        ),
    )
    assert (
        _gate(owned, "launch_flags").state == GATE_OK
        and "StableNew launched" in _gate(owned, "launch_flags").detail
    )

    unknown = evaluate_workflow_preflight(
        spec, _probes(None, state="healthy", object_info={})
    )  # a bare command-less probe: nothing is known about ownership either
    assert _gate(unknown, "launch_flags").state == GATE_BLOCKED


def test_a_workflow_without_special_flags_is_unaffected_by_ownership_and_configuration() -> None:
    spec = _spec(TI2V)

    for facts, state in (
        (_facts(), "free"),
        (_facts(saved_command=GOOD), "healthy"),
        (_facts(saved_command=BARE, active_command=BARE), "free"),
    ):
        result = evaluate_workflow_preflight(spec, _probes(facts, state=state, object_info={}))
        assert "launch_flags" not in {gate.id for gate in result.gates}

    healthy = evaluate_workflow_preflight(
        spec, _probes(_facts(saved_command=GOOD), state="healthy", object_info={})
    )
    assert _gate(healthy, "runtime").state == GATE_OK  # no ownership claim is made or needed


def test_an_occupied_endpoint_reports_the_port_and_offers_no_setup_repair() -> None:
    spec = _spec(ANIMATE)
    result = evaluate_workflow_preflight(
        spec, _probes(_facts(saved_command=GOOD), state="occupied")
    )

    runtime = _gate(result, "runtime")
    assert runtime.state == GATE_BLOCKED and "not a healthy ComfyUI" in runtime.detail
    assert "StableNew will not stop it" in runtime.fix and runtime.action == ""
    assert not result.setup_repair_available


@pytest.mark.parametrize(
    ("kwargs", "gate_id"),
    [({"ram_gb": 4.0}, "ram"), ({"vram": (12282.0, 500.0)}, "vram"), ({"vram": None}, "vram")],
)
def test_resource_blockers_never_offer_the_setup_repair(kwargs: dict, gate_id: str) -> None:
    spec = _spec(ANIMATE)

    result = evaluate_workflow_preflight(spec, _probes(_facts(saved_command=GOOD), **kwargs))

    assert _gate(result, gate_id).state == GATE_BLOCKED
    assert not result.setup_repair_available
    assert result.setup_repair_reason == ""
    assert (
        _gate(result, "launch_flags").state == GATE_OK
    )  # the flags are fine, and the strip says so


def test_missing_nodes_or_model_files_never_offer_the_setup_repair() -> None:
    spec = _spec(ANIMATE)

    result = evaluate_workflow_preflight(
        spec,
        _probes(
            _facts(saved_command=GOOD, active_command=GOOD, owns_runtime=True),
            state="healthy",
            object_info={"SomeOtherNode": {"input": {"required": {}}}},
        ),
    )

    blocked = {gate.id for gate in result.blocking}
    assert blocked & {"nodes", "model_files"}
    assert all(gate.action == "" for gate in result.gates if gate.id in {"nodes", "model_files"})
    assert not result.setup_repair_available


def test_the_projection_survives_to_dict_for_diagnostics() -> None:
    result = evaluate_workflow_preflight(
        _spec(ANIMATE), _probes(_facts(saved_command=GOOD, active_command=BARE))
    )

    data = result.to_dict()
    assert data["notices"] and {"id", "action"} <= set(data["gates"][0])


# --------------------------------------------------------------------------- agreement with the backend


@pytest.mark.parametrize("command", [BARE, GOOD, ("python", "main.py", PIN), ()])
def test_preflight_and_backend_admission_agree_about_the_active_launchers_flags(command) -> None:
    """The strip blocks exactly when ``_verify_required_launch_flags`` would refuse, for the same launcher."""

    spec = _spec(ANIMATE)
    manager = SimpleNamespace(
        _config=SimpleNamespace(base_url="http://x", command=list(command)),
        owns_process=False,
        is_running=lambda: False,
    )
    backend = ComfyWorkflowVideoBackend(client=SimpleNamespace(), process_manager=manager)
    try:
        backend._verify_required_launch_flags(spec)
        backend_refuses = False
    except RuntimeError:
        backend_refuses = True

    preflight = evaluate_workflow_preflight(
        spec,
        _probes(_facts(saved_command=tuple(command), active_command=tuple(command))),
    )

    assert (_gate(preflight, "launch_flags").state == GATE_BLOCKED) is backend_refuses


def test_diagnosing_the_setup_never_starts_stops_queues_or_installs(monkeypatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(ComfyProcessManager, "start", lambda *_a, **_k: started.append("start"))
    monkeypatch.setattr(ComfyProcessManager, "stop", lambda *_a, **_k: started.append("stop"))
    monkeypatch.setattr(ComfyProcessManager, "restart", lambda *_a, **_k: started.append("restart"))
    monkeypatch.setattr(
        ComfyProcessManager, "ensure_running", lambda *_a, **_k: started.append("run")
    )
    monkeypatch.setattr(cpm, "ManagedProcess", lambda *_a, **_k: started.append("process"))
    ComfyProcessManager(ComfyProcessConfig(command=list(BARE)))

    for facts in (
        _facts(),
        _facts(saved_command=BARE),
        read_comfy_launch_facts(_Settings(list(GOOD))),
        _facts(saved_command=GOOD, environment_command=BARE),
    ):
        for state in ("free", "healthy", "occupied"):
            evaluate_workflow_preflight(_spec(ANIMATE), _probes(facts, state=state, object_info={}))

    assert started == []


# --------------------------------------------------------------------------- stale-result safety


def test_the_repair_action_never_leaks_onto_a_newer_selection() -> None:
    results = {
        "a": evaluate_workflow_preflight(_spec(ANIMATE), _probes(_facts())),
        "b": evaluate_workflow_preflight(_spec(TI2V), _probes(_facts(saved_command=GOOD))),
    }
    session = RuntimeReadinessSession(evaluate=lambda wf, _v: results[wf])

    work_a = session.refresh("a", "1")
    assert work_a is not None
    assert session.refresh("b", "1") is None  # a worker is running: it will follow up
    follow_up = session.finish(work_a, session.run(work_a))  # a's answer is stale and discarded
    assert follow_up is not None and follow_up.workflow_id == "b"
    assert not session.view().repair_available and session.block_reason() == ""

    session.finish(follow_up, session.run(follow_up))
    view = session.view()
    assert not view.repair_available and view.notices == ()

    work_a = session.refresh("a", "1")
    session.finish(work_a, session.run(work_a))
    assert session.view().repair_available and session.view().repair_reason
