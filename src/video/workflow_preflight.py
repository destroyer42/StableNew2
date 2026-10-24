"""Read-only readiness gates for a Comfy video workflow, answered before the job is queued (PR-VID-UX-311).

Every gate here is something ``ComfyWorkflowVideoBackend.execute`` would otherwise refuse *after* the click, inside the
queue: the launch flags the workflow requires, a ComfyUI that can be reached or started, the pinned nodes and model
files, and the host resource floors. ``evaluate_workflow_preflight`` runs them against injected probes and returns plain
data, so the Video Workflow tab can show each gate and keep Queue disabled with the reason instead.

It observes only. It never queues a prompt, starts, stops or adopts a process, writes a file or changes a setting: the
only network traffic is ``GET`` of ComfyUI's own ``/system_stats`` and ``/object_info`` on an endpoint that is already
serving, and the only host reads are RAM, the NVIDIA driver's memory figures and the configured launch command. A gate it
cannot answer without starting something is ``unknown`` (shown, never blocking); only a *proven* shortfall is ``blocked``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.video.comfy_dependency_probe import ComfyDependencyProbe
from src.video.comfy_runtime_setup import (
    ACTION_FIX_COMFY_SETUP,
    ENV_COMMAND_VARIABLE,
    SOURCE_ENVIRONMENT,
    ComfyLaunchFacts,
    command_missing_flags,
    setup_notices,
)
from src.video.managed_comfy_runtime import ManagedComfyContract, assess_comfy_command
from src.video.workflow_readiness import WorkflowResourceReadiness, required_launch_flags

GATE_OK = "ok"
GATE_BLOCKED = "blocked"
GATE_UNKNOWN = "unknown"

ENDPOINT_FREE = "free"
ENDPOINT_HEALTHY = "healthy"
ENDPOINT_OCCUPIED = "occupied"

# Host memory ComfyUI itself takes while it starts (observed: 17.06 GB available before the process, 15.7 GB
# when the backend's own readiness check ran after it). Counted against the RAM floor while ComfyUI is not
# running, so a gate shown green here is not refused one step later.
STARTUP_RAM_ALLOWANCE_GB = 1.5

ENGINE_SETTINGS_HINT = "Engine Settings > Video runtime (ComfyUI)"


@dataclass(frozen=True)
class PreflightGate:
    id: str
    label: str
    state: str
    detail: str
    fix: str = ""
    #: ``ACTION_FIX_COMFY_SETUP`` when Engine Settings can repair this gate; empty for every other kind of shortfall.
    action: str = ""


@dataclass(frozen=True)
class WorkflowPreflight:
    workflow_id: str
    workflow_version: str
    gates: tuple[PreflightGate, ...]
    runtime_state: str = ENDPOINT_FREE
    #: Setup facts that are not gates (an environment override, a saved change waiting for a restart).
    notices: tuple[str, ...] = ()

    @property
    def setup_repair_available(self) -> bool:
        """A blocked gate that Engine Settings > Video runtime (ComfyUI) can plausibly resolve."""

        return any(gate.action == ACTION_FIX_COMFY_SETUP for gate in self.blocking)

    @property
    def setup_repair_reason(self) -> str:
        """What Engine Settings should be opened for: the first repairable blocked gate, with its fix."""

        for gate in self.blocking:
            if gate.action == ACTION_FIX_COMFY_SETUP:
                return f"{gate.label}: {gate.detail} {gate.fix}".strip()
        return ""

    @property
    def blocking(self) -> tuple[PreflightGate, ...]:
        return tuple(gate for gate in self.gates if gate.state == GATE_BLOCKED)

    @property
    def queueable(self) -> bool:
        return not self.blocking

    @property
    def block_reason(self) -> str:
        """One line for the Queue button: the first blocked gate and what to do about it."""

        blocked = self.blocking
        if not blocked:
            return ""
        first = blocked[0]
        text = f"Queue is off: {first.label}: {first.detail}"
        if first.fix:
            text += f" {first.fix}"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "queueable": self.queueable,
            "runtime_state": self.runtime_state,
            "notices": list(self.notices),
            "gates": [
                {
                    "id": gate.id,
                    "label": gate.label,
                    "state": gate.state,
                    "detail": gate.detail,
                    "fix": gate.fix,
                    "action": gate.action,
                }
                for gate in self.gates
            ],
        }


@dataclass(frozen=True)
class PreflightProbes:
    """Everything the gates read, injected so tests (and the app) choose the sources."""

    command: tuple[str, ...]
    base_url: str
    autostart: bool
    endpoint_state: Callable[[str], str]
    fetch_object_info: Callable[[str], Mapping[str, Any] | None]
    fetch_system_stats: Callable[[str], Mapping[str, Any] | None]
    ram_probe: Callable[[], float]
    gpu_probe: Callable[[int], tuple[float, float] | None]
    managed_contract: ManagedComfyContract | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)
    #: Saved / environment / active launch evidence. ``None`` (a bare ``command``) means nothing is known about the
    #: launcher or about who owns a serving endpoint, and is reported that way.
    launch: ComfyLaunchFacts | None = None


def _launch_facts(probes: PreflightProbes) -> ComfyLaunchFacts:
    if probes.launch is not None:
        return probes.launch
    return ComfyLaunchFacts(saved_command=tuple(probes.command))


def _launch_flags_gate(spec: Any, probes: PreflightProbes, state: str) -> PreflightGate | None:
    """Required launch flags, judged on the command a launch from this process would run and on who owns a serving endpoint.

    The saved command is never evidence about a process StableNew did not launch, and a saved change is never
    evidence about the launcher this session already registered.
    """

    required = required_launch_flags(spec)
    if not required:
        return None
    flags = " ".join(required)
    facts = _launch_facts(probes)
    in_force = facts.command_in_force
    if not in_force:
        return PreflightGate(
            "launch_flags",
            "Launch flags",
            GATE_BLOCKED,
            f"this workflow needs a StableNew-launched ComfyUI started with {flags}, and no launch "
            "command is configured"
            + (
                " (a ComfyUI that is already running cannot have its flags verified)."
                if state == ENDPOINT_HEALTHY
                else "."
            ),
            f"Open {ENGINE_SETTINGS_HINT} and choose the managed install.",
            ACTION_FIX_COMFY_SETUP,
        )
    missing = command_missing_flags(in_force, required)
    if missing:
        missing_text = " ".join(missing)
        if facts.active_command is not None and not command_missing_flags(
            facts.effective_command, required
        ):
            return PreflightGate(
                "launch_flags",
                "Launch flags",
                GATE_BLOCKED,
                f"the ComfyUI launcher of this session was started without {missing_text}; the saved "
                "command has it, but StableNew has not applied it yet.",
                "Restart StableNew to apply the saved command.",
            )
        if facts.effective_source == SOURCE_ENVIRONMENT:
            return PreflightGate(
                "launch_flags",
                "Launch flags",
                GATE_BLOCKED,
                f"the ComfyUI command from {ENV_COMMAND_VARIABLE} (it overrides Engine Settings) is "
                f"missing {missing_text}.",
                f"Remove or change {ENV_COMMAND_VARIABLE} outside StableNew and restart StableNew.",
            )
        return PreflightGate(
            "launch_flags",
            "Launch flags",
            GATE_BLOCKED,
            f"the configured ComfyUI command is missing {missing_text}.",
            f"Open {ENGINE_SETTINGS_HINT} and use Add required flags.",
            ACTION_FIX_COMFY_SETUP,
        )
    if state == ENDPOINT_HEALTHY:
        if facts.owns_runtime:
            return PreflightGate(
                "launch_flags",
                "Launch flags",
                GATE_OK,
                f"the ComfyUI StableNew launched is serving and its command carries {flags}.",
            )
        return PreflightGate(
            "launch_flags",
            "Launch flags",
            GATE_BLOCKED,
            "a ComfyUI that StableNew did not launch is serving, so its launch flags cannot be verified "
            f"({flags} is needed); StableNew will not adopt, stop or restart it.",
            "Stop that ComfyUI yourself and refresh; StableNew then starts its own from the configured command.",
        )
    return PreflightGate(
        "launch_flags",
        "Launch flags",
        GATE_OK,
        f"{flags} present in the command StableNew will launch.",
    )


def _runtime_gate(probes: PreflightProbes, state: str) -> PreflightGate:
    url = probes.base_url
    if state == ENDPOINT_HEALTHY:
        return PreflightGate("runtime", "ComfyUI", GATE_OK, f"running at {url}.")
    if state == ENDPOINT_OCCUPIED:
        return PreflightGate(
            "runtime",
            "ComfyUI",
            GATE_BLOCKED,
            f"{url} is answering but is not a healthy ComfyUI, so StableNew cannot start its own.",
            "Close whatever is using that port (StableNew will not stop it) and refresh.",
        )
    # The endpoint is free: a configured command that autostart may launch is fine; anything else is not.
    command = _launch_facts(probes).command_in_force
    if not command:
        return PreflightGate(
            "runtime",
            "ComfyUI",
            GATE_BLOCKED,
            f"nothing is serving {url} and no launch command is configured.",
            f"Open {ENGINE_SETTINGS_HINT} and choose the managed install, or start ComfyUI yourself.",
            ACTION_FIX_COMFY_SETUP,
        )
    if not probes.autostart:
        return PreflightGate(
            "runtime",
            "ComfyUI",
            GATE_BLOCKED,
            f"ComfyUI is not running at {url} and automatic start is off.",
            f"Turn on automatic start in {ENGINE_SETTINGS_HINT}, or start ComfyUI yourself.",
        )
    assessment = (
        assess_comfy_command(command, probes.managed_contract)
        if probes.managed_contract is not None
        else None
    )
    which = {"managed": "the managed install", "custom": "your configured command"}.get(
        assessment.kind if assessment else "", "the configured command"
    )
    return PreflightGate(
        "runtime",
        "ComfyUI",
        GATE_OK,
        f"not running; StableNew will start it from {which} at {url}.",
    )


def _dependency_gates(
    spec: Any, probes: PreflightProbes, state: str
) -> tuple[PreflightGate, PreflightGate, Mapping[str, Any] | None]:
    nodes = [d for d in spec.dependency_specs if d.dependency_kind == "stock_node"]
    files = [d for d in spec.dependency_specs if d.dependency_kind == "model_file"]
    file_lines = ", ".join(f"{d.locator} (SHA-256 {_digest(d)})" for d in files)
    if state != ENDPOINT_HEALTHY:
        when = "checked when ComfyUI starts"
        return (
            PreflightGate(
                "nodes", "Workflow nodes", GATE_UNKNOWN, f"{len(nodes)} stock nodes, {when}."
            ),
            PreflightGate(
                "model_files",
                "Model files",
                GATE_UNKNOWN,
                f"{len(files)} pinned file(s), {when}: {file_line_or_none(file_lines)}",
            ),
            None,
        )
    object_info = probes.fetch_object_info(probes.base_url)
    if object_info is None:
        unreadable = "ComfyUI is running but its node list could not be read."
        return (
            PreflightGate("nodes", "Workflow nodes", GATE_UNKNOWN, unreadable),
            PreflightGate("model_files", "Model files", GATE_UNKNOWN, unreadable),
            None,
        )
    result = ComfyDependencyProbe().probe_workflow(spec, object_info=object_info)
    details = result.details
    missing_nodes = sorted(
        details[key]["locator"]
        for key in result.missing_required
        if details[key]["dependency_kind"] == "stock_node"
    )
    missing_files = sorted(
        details[key]["locator"]
        for key in result.missing_required
        if details[key]["dependency_kind"] == "model_file"
    )
    node_gate = (
        PreflightGate(
            "nodes",
            "Workflow nodes",
            GATE_BLOCKED,
            f"this ComfyUI lacks {', '.join(missing_nodes)}.",
            "Use a ComfyUI release that provides them (the managed install does).",
        )
        if missing_nodes
        else PreflightGate("nodes", "Workflow nodes", GATE_OK, f"{len(nodes)} stock nodes present.")
    )
    file_gate = (
        PreflightGate(
            "model_files",
            "Model files",
            GATE_BLOCKED,
            f"missing from ComfyUI's model folders: {', '.join(missing_files)}.",
            "Place the pinned files (SHA-256 in the workflow catalog) in the declared folders and refresh.",
        )
        if missing_files
        else PreflightGate(
            "model_files",
            "Model files",
            GATE_OK,
            f"{len(files)} pinned file(s) present: {file_lines}",
        )
    )
    return node_gate, file_gate, object_info


def file_line_or_none(text: str) -> str:
    return text or "none declared."


def _digest(dependency: Any) -> str:
    description = str(getattr(dependency, "description", "") or "")
    marker = "sha256 "
    if marker in description:
        return description.split(marker, 1)[1].split("...", 1)[0].split(",", 1)[0] + "..."
    return "not pinned"


def _resource_gates(spec: Any, probes: PreflightProbes, state: str) -> tuple[PreflightGate, ...]:
    readiness = WorkflowResourceReadiness(ram_probe=probes.ram_probe, gpu_probe=probes.gpu_probe)
    policy = readiness.policy_for(spec)
    if policy is None:
        return ()
    stats: Mapping[str, Any] | None = None
    if state == ENDPOINT_HEALTHY:
        stats = probes.fetch_system_stats(probes.base_url)
    if stats is None:
        # ComfyUI is not running (nothing of the GPU is Comfy's yet): the driver's free figure is all there is.
        stats = {"devices": [{"type": "cuda", "index": 0, "torch_vram_total": 0, "vram_free": 0}]}
    # The RAM figure ComfyUI will see is what is free after its own start-up, not before it.
    allowance = 0.0 if state == ENDPOINT_HEALTHY else STARTUP_RAM_ALLOWANCE_GB
    adjusted = WorkflowResourceReadiness(
        ram_probe=lambda: probes.ram_probe() - allowance, gpu_probe=probes.gpu_probe
    )
    result = adjusted.evaluate(spec, system_stats=stats)
    observed = result.observations
    gates: list[PreflightGate] = []
    vram_blocks = [text for text in result.blocking if "GPU" in text or "NVIDIA" in text]
    ram_blocks = [text for text in result.blocking if "system RAM" in text]
    if "vram_floor_mib" in observed or vram_blocks:
        detail = (
            f"{observed.get('vram_available_to_comfy_mib', '?')} MiB available to ComfyUI "
            f"(needs {observed.get('vram_floor_mib', '?')} MiB)."
        )
        gates.append(
            PreflightGate(
                "vram",
                "GPU memory",
                GATE_BLOCKED if vram_blocks else GATE_OK,
                vram_blocks[0] if vram_blocks else detail,
            )
        )
    if "ram_floor_gb" in observed or ram_blocks:
        note = (
            ""
            if state == ENDPOINT_HEALTHY
            else f" once ComfyUI has started (counting the {STARTUP_RAM_ALLOWANCE_GB:g} GB it takes)"
        )
        detail = (
            f"{observed.get('ram_available_gb', '?')} GB available{note}; "
            f"needs {observed.get('ram_floor_gb', '?')} GB."
        )
        gates.append(
            PreflightGate(
                "ram",
                "System RAM",
                GATE_BLOCKED if ram_blocks else GATE_OK,
                detail,
                "Close memory-heavy applications and refresh." if ram_blocks else "",
            )
        )
    return tuple(gates)


def evaluate_workflow_preflight(spec: Any, probes: PreflightProbes) -> WorkflowPreflight:
    """Run every gate for ``spec``; never raises for a probe that fails (that gate is ``unknown`` or ``blocked``)."""

    state = _endpoint_state(probes)
    gates: list[PreflightGate] = []
    flags = _launch_flags_gate(spec, probes, state)
    if flags is not None:
        gates.append(flags)
    gates.append(_runtime_gate(probes, state))
    node_gate, file_gate, _info = _dependency_gates(spec, probes, state)
    gates.extend((node_gate, file_gate))
    gates.extend(_resource_gates(spec, probes, state))
    return WorkflowPreflight(
        workflow_id=str(spec.workflow_id),
        workflow_version=str(spec.workflow_version),
        gates=tuple(gates),
        runtime_state=state,
        notices=setup_notices(probes.launch),
    )


def _endpoint_state(probes: PreflightProbes) -> str:
    try:
        state = str(probes.endpoint_state(probes.base_url))
    except Exception:  # noqa: BLE001 - an unreadable endpoint is treated as not serving
        return ENDPOINT_FREE
    return (
        state
        if state in {ENDPOINT_FREE, ENDPOINT_HEALTHY, ENDPOINT_OCCUPIED}
        else ENDPOINT_OCCUPIED
    )


def default_preflight_probes(
    *,
    comfy_command: Sequence[str] | None = None,
    base_url: str | None = None,
    autostart: bool | None = None,
    managed_contract: ManagedComfyContract | None = None,
    config_manager: Any = None,
) -> PreflightProbes:
    """The app's probes: the configured launch command, a 1 s endpoint check and read-only ``GET``s of a serving ComfyUI."""

    import psutil

    from src.video.comfy_api_client import ComfyApiClient
    from src.video.comfy_healthcheck import probe_comfy_endpoint
    from src.video.comfy_process_manager import (
        build_default_comfy_process_config,
        read_comfy_launch_facts,
    )
    from src.video.workflow_readiness import _driver_gpu_memory_mib

    config = build_default_comfy_process_config(config_manager)
    launch = read_comfy_launch_facts(config_manager)
    command = (
        tuple(comfy_command)
        if comfy_command is not None
        else tuple(getattr(config, "command", None) or ())
    )
    if comfy_command is not None:
        launch = ComfyLaunchFacts(saved_command=tuple(comfy_command))
    url = base_url or str(getattr(config, "base_url", "") or "http://127.0.0.1:8188")
    auto = bool(getattr(config, "autostart_enabled", False)) if autostart is None else autostart

    def _object_info(target: str) -> Mapping[str, Any] | None:
        try:
            return ComfyApiClient(base_url=target).get_object_info()
        except Exception:  # noqa: BLE001 - reported as an unknown gate
            return None

    def _system_stats(target: str) -> Mapping[str, Any] | None:
        try:
            return ComfyApiClient(base_url=target).get_system_stats()
        except Exception:  # noqa: BLE001
            return None

    return PreflightProbes(
        command=command,
        base_url=url,
        autostart=auto,
        endpoint_state=lambda target: probe_comfy_endpoint(target, timeout=1.0),
        fetch_object_info=_object_info,
        fetch_system_stats=_system_stats,
        ram_probe=lambda: float(psutil.virtual_memory().available) / 1e9,
        gpu_probe=_driver_gpu_memory_mib,
        managed_contract=managed_contract,
        launch=launch,
    )


__all__ = [
    "ENDPOINT_FREE",
    "ENDPOINT_HEALTHY",
    "ENDPOINT_OCCUPIED",
    "GATE_BLOCKED",
    "GATE_OK",
    "GATE_UNKNOWN",
    "STARTUP_RAM_ALLOWANCE_GB",
    "PreflightGate",
    "PreflightProbes",
    "WorkflowPreflight",
    "default_preflight_probes",
    "evaluate_workflow_preflight",
]
