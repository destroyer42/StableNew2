"""Physical executor for the Fun Control 5B qualification.  Operator-only; never a production submission path.

Nothing happens at import.  ``python -m tools.qualification.fun354.physical`` is the only entry point and it refuses to touch a
GPU unless ``--authorize-plan`` equals the stored plan's digest and Q0 is READY for that exact plan.  Each case gets a fresh,
owned Comfy runtime (``ComfyProcessManager``), one dispatch, no retry, and a teardown check before the next case may start.
The graph is the catalog's immutable template rendered with the compiler's own renderer, so qualification exercises exactly
what the product would submit.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.video.motion_source_preparation import sha256_file
from src.video.workflow_asset_integrity import model_folders
from src.video.workflow_compiler import _render_template_value
from tools.qualification.fun354 import q0 as q0_module
from tools.qualification.fun354.harness import Authorization, CaseObservation, run_qualification
from tools.qualification.fun354.inputs import rebuild_plan
from tools.qualification.fun354.plan import (
    GEOMETRY,
    PHASE_Q0,
    ROLE_REFERENCE,
    STOP_ALLOCATION,
    STOP_COMMIT,
    STOP_DEVICE_LOSS,
    STOP_IDENTITY,
    STOP_LOW_RAM,
    STOP_TEARDOWN,
    STOP_TELEMETRY,
    STOP_TIMEOUT,
    CasePlan,
    PhasePlan,
    QualificationPlan,
    fun_control_spec,
)

INSTALL = Path("C:/Users/rob/AppData/Local/StableNew/ManagedComfy/v0.38.0-py313")
MODEL_BASE = Path("E:/Users/rober/ComfyUI")  # holds models/{diffusion_models,text_encoders,vae}
EVIDENCE_ROOT = Path("C:/Users/rob/qual/motion354-evidence/fun354-physical")
PORT = 8197
SAVE_NODE = "11"
EXPECTED_RUNTIME = {"comfyui_version": "0.38.0", "pytorch_version": "2.14.0+cu130"}
EXPECTED_PYTHON_PREFIX = "3.13."

COMMIT_STOP_FRACTION = 0.95
COMMIT_STOP_SAMPLES = 2
LOW_RAM_MIB = 1024
LOW_RAM_SECONDS = 10.0
TELEMETRY_GAP_SECONDS = 5.0
SAMPLE_SECONDS = 1.0
TEARDOWN_GRACE_SECONDS = 60.0
VRAM_RELEASE_TOLERANCE_MIB = 512.0
STARTUP_TIMEOUT_SECONDS = 240.0
INTERRUPT_SETTLE_SECONDS = 60.0

DEVICE_LOSS = re.compile(
    r"GPU is lost|GPU has fallen off|CUDA error: (?:unknown|.*device)|device-side assert", re.I
)
ALLOCATION_FAILURE = re.compile(
    r"out.?of.?memory|\bOOM\b|Allocation on device|CUDA.*alloc.*fail|not enough memory", re.I
)
#: Event-log providers/ids that mean the display driver or hardware faulted during a case.
FAULT_EVENT_IDS = frozenset({41, 4101, 6008})
FAULT_PROVIDER_MARKERS = ("nvlddmkm", "whea")


@dataclass(frozen=True)
class Sample:
    elapsed: float
    commit_fraction: float
    available_ram_mib: float
    vram_used_mib: float
    vram_total_mib: float


def scan_log(text: str) -> str:
    """The stop code a Comfy log line demands, or ``""``."""

    if DEVICE_LOSS.search(text):
        return STOP_DEVICE_LOSS
    if ALLOCATION_FAILURE.search(text):
        return STOP_ALLOCATION
    return ""


class StopGuard:
    """Pure stop policy over telemetry samples; thresholds are the plan's, never tuned here."""

    def __init__(self) -> None:
        self._commit_run = 0
        self._low_ram_since: float | None = None
        self._last: float | None = None
        self.peak_commit = 0.0
        self.min_available_mib: float | None = None
        self.peak_vram_mib = 0.0

    def observe(self, sample: Sample) -> str:
        self.peak_commit = max(self.peak_commit, sample.commit_fraction)
        self.peak_vram_mib = max(self.peak_vram_mib, sample.vram_used_mib)
        self.min_available_mib = (
            sample.available_ram_mib
            if self.min_available_mib is None
            else min(self.min_available_mib, sample.available_ram_mib)
        )
        if self._last is not None and sample.elapsed - self._last > TELEMETRY_GAP_SECONDS:
            self._last = sample.elapsed
            return STOP_TELEMETRY
        self._last = sample.elapsed
        self._commit_run = (
            self._commit_run + 1 if sample.commit_fraction >= COMMIT_STOP_FRACTION else 0
        )
        if self._commit_run >= COMMIT_STOP_SAMPLES:
            return STOP_COMMIT
        if sample.available_ram_mib < LOW_RAM_MIB:
            if self._low_ram_since is None:
                self._low_ram_since = sample.elapsed
            if sample.elapsed - self._low_ram_since >= LOW_RAM_SECONDS:
                return STOP_LOW_RAM
        else:
            self._low_ram_since = None
        return ""

    def silent_for(self, now: float) -> bool:
        return self._last is not None and now - self._last > TELEMETRY_GAP_SECONDS


class Monitor:
    """Samples on a thread, and a watchdog stops the owned runtime the moment telemetry goes quiet or a stop fires."""

    def __init__(
        self,
        *,
        sample_fn: Callable[[], Sample],
        log_fn: Callable[[], str],
        stop_fn: Callable[[], None],
        journal: Path,
        interval: float = SAMPLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sample_fn, self._log_fn, self._stop_fn = sample_fn, log_fn, stop_fn
        self._journal, self._interval, self._clock = journal, interval, clock
        self.guard = StopGuard()
        self.stop_code = ""
        self.error = ""
        self.samples = 0
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._threads: list[threading.Thread] = []
        self._epoch = clock()
        self._last_done = clock()

    def abort(self, code: str, detail: str = "") -> None:
        with self._lock:
            first = not self.stop_code
            if first:
                self.stop_code = code
                self.error = detail or self.error
        if first:
            self._stop_fn()  # only the manager's own child; never an unowned process

    def _once(self) -> None:
        sample = self._sample_fn()
        code = self.guard.observe(sample) or scan_log(self._log_fn())
        self.samples += 1
        with self._journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"sample": asdict(sample), "stop": code}) + "\n")
            handle.flush()
        self._last_done = self._clock()
        if code:
            self.abort(code)

    def _loop(self) -> None:
        while not self._halt.wait(self._interval):
            try:
                self._once()
            except BaseException as exc:  # noqa: BLE001 - missing telemetry is itself a stop
                self.abort(STOP_TELEMETRY, f"{type(exc).__name__}: {exc}")
                return

    def _watch(self) -> None:
        while not self._halt.wait(0.2):
            if self._clock() - self._last_done > TELEMETRY_GAP_SECONDS:
                self.abort(STOP_TELEMETRY, "telemetry was silent for more than 5 s")
                return

    def start(self) -> None:
        self._once()  # a complete baseline sample is required before anything launches
        if self.stop_code:
            raise RuntimeError(f"stop before launch: {self.stop_code}")
        for target, name in ((self._loop, "fun354-telemetry"), (self._watch, "fun354-watchdog")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def close(self) -> None:
        self._halt.set()
        for thread in self._threads:
            thread.join(timeout=10)

    @property
    def complete(self) -> bool:
        return self.samples > 0 and self.stop_code != STOP_TELEMETRY


def write_json(path: Path, value: Any) -> None:
    """Evidence is written once; an existing file is never replaced."""

    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
        handle.flush()


def render_graph(
    plan: QualificationPlan, case: CasePlan, *, reference_name: str, driving_name: str
) -> dict[str, Any]:
    """The catalog template, rendered by the compiler's renderer for this case."""

    template = deepcopy(fun_control_spec().backend_defaults["prompt_template"])
    context = {
        "input": {
            "source_image": reference_name,
            "prompt": plan.prompt,
            "negative_prompt": plan.negative_prompt,
            "seed": case.seed,
            "target_width": plan.width,
            "target_height": plan.height,
            "frame_count": case.frames,
            "pose_video": driving_name,
        },
        "request": {"job_id": case.case_id, "stage_name": "qualification", "image_name": ""},
    }
    graph = _render_template_value(template, context)
    if "{{" in json.dumps(graph):
        raise RuntimeError("The rendered graph still has unresolved placeholders.")
    return graph


def template_digest() -> str:
    import hashlib

    template = fun_control_spec().backend_defaults["prompt_template"]
    blob = json.dumps(template, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def validate_schema(info: Mapping[str, Any], graph: Mapping[str, Any]) -> None:
    """Every node, input and enumerated option the graph uses must exist in the running Comfy."""

    for node in graph.values():
        schema = info.get(node["class_type"])
        if not isinstance(schema, dict):
            raise RuntimeError("Missing stock node: " + node["class_type"])
        inputs = schema.get("input", {})
        required = inputs.get("required", {})
        declared = {**required, **inputs.get("optional", {})}
        if set(required) - set(node["inputs"]):
            raise RuntimeError("Missing required node inputs: " + node["class_type"])
        for key, value in node["inputs"].items():
            if key not in declared:
                raise RuntimeError("Unsupported node input: " + node["class_type"] + "." + key)
            descriptor = declared[key]
            if (
                isinstance(value, str)
                and descriptor
                and isinstance(descriptor[0], list)
                and value not in descriptor[0]
            ):
                raise RuntimeError("Unavailable node option: " + value)


def validate_frames(
    history: Mapping[str, Any], output_root: Path, frames: int, size: tuple[int, int]
) -> list[dict[str, Any]]:
    """Exact frame count, exact geometry, every file inside the owned output folder."""

    from PIL import Image

    images = history.get("outputs", {}).get(SAVE_NODE, {}).get("images", [])
    if len(images) != frames:
        raise RuntimeError(f"Expected {frames} PNG frames, found {len(images)}")
    root = output_root.resolve()
    seen: set[Path] = set()
    records: list[dict[str, Any]] = []
    for image in images:
        path = (output_root / image.get("subfolder", "") / image["filename"]).resolve()
        if (
            image.get("type") != "output"
            or not path.is_relative_to(root)
            or path in seen
            or path.suffix.lower() != ".png"
        ):
            raise RuntimeError("Escaped, duplicate or invalid frame path")
        seen.add(path)
        with Image.open(path) as frame:
            frame.load()
            if frame.size != size or frame.mode not in ("RGB", "RGBA"):
                raise RuntimeError(f"Invalid frame geometry or channels: {frame.size} {frame.mode}")
        records.append(
            {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        )
    return records


def fault_events(events: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Event-log rows that mean the driver or hardware faulted (display-driver, WHEA, unexpected power loss)."""

    rows = events.get("events") or []
    if isinstance(rows, dict):
        rows = [rows]
    return [
        row
        for row in rows
        if int(row.get("Id", 0)) in FAULT_EVENT_IDS
        or any(m in str(row.get("ProviderName", "")).lower() for m in FAULT_PROVIDER_MARKERS)
    ]


def launch_command(runtime: Path) -> list[str]:
    command = [
        str(INSTALL / "venv/Scripts/python.exe"),
        str(INSTALL / "source/main.py"),
        "--listen",
        "127.0.0.1",
        "--port",
        str(PORT),
    ]
    for folder in ("input", "output", "temp", "user"):
        command += [f"--{folder}-directory", str(runtime / folder)]
    command += [
        "--extra-model-paths-config",
        str(runtime / "extra_model_paths.yaml"),
        "--disable-pinned-memory",
        "--disable-auto-launch",
        "--disable-all-custom-nodes",
    ]
    return command


def write_model_paths(runtime: Path) -> None:
    paths = {
        "fun354": {
            "base_path": (MODEL_BASE / "models").as_posix(),
            **{k: k for k in ("diffusion_models", "text_encoders", "vae")},
        }
    }
    (runtime / "extra_model_paths.yaml").write_text(
        json.dumps(paths), encoding="utf-8"
    )  # JSON is YAML


# ---- real-world seams -------------------------------------------------------------------------------------------------


def gpu_memory() -> tuple[float, float]:
    out = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            "0",
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=2,
        check=True,
    ).stdout
    used, total = (float(v) for v in out.strip().split(","))
    return used, total


def system_memory() -> tuple[float, float]:
    from tools.qualification.vid160c.win_memory import read_system_commit

    commit = read_system_commit()
    return commit.commit_percent / 100.0, commit.physical_available_gb * 1024.0


def git_head(source: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def event_log(since: datetime) -> dict[str, Any]:
    from tools.qualification.wan321f.physical import event_log as read_event_log

    return read_event_log(since)


def real_manager(config: Any) -> Any:
    from src.video.comfy_process_manager import ComfyProcessManager

    return ComfyProcessManager(config)


def real_client(base_url: str) -> Any:
    from src.video.comfy_api_client import ComfyApiClient

    return ComfyApiClient(base_url=base_url)


def pid_exists(pid: int) -> bool:
    import psutil

    return psutil.pid_exists(pid)


def child_pids(pid: int) -> list[int]:
    import psutil

    try:
        return [p.pid for p in psutil.Process(pid).children(recursive=True)]
    except psutil.Error:
        return []


@dataclass
class Seams:
    """Everything that touches the machine; tests substitute fakes so no GPU or process is needed."""

    manager_factory: Callable[[Any], Any] = real_manager
    client_factory: Callable[[str], Any] = real_client
    gpu_memory: Callable[[], tuple[float, float]] = gpu_memory
    system_memory: Callable[[], tuple[float, float]] = system_memory
    git_head: Callable[[Path], str] = git_head
    event_log: Callable[[datetime], dict[str, Any]] = event_log
    pid_exists: Callable[[int], bool] = pid_exists
    child_pids: Callable[[int], list[int]] = child_pids
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    monitor_interval: float = SAMPLE_SECONDS


@dataclass
class _CaseState:
    stop_code: str = ""
    identity_ok: bool = True
    telemetry_ok: bool = True
    teardown_ok: bool = True
    completed: bool = False
    launched: bool = False
    delivered: int = 0
    wall: float = 0.0
    notes: list[str] = field(default_factory=list)


class PhysicalExecutor:
    """Runs one case in one fresh owned runtime.  Implements ``harness.CaseExecutor``."""

    def __init__(
        self,
        *,
        inputs: Mapping[str, Path],
        evidence_root: Path,
        seams: Seams | None = None,
        install: Path = INSTALL,
    ) -> None:
        self.inputs = dict(inputs)
        self.evidence_root = evidence_root
        self.seams = seams or Seams()
        self.install = install

    # -- identity -----------------------------------------------------------------------------------------------------
    def _identity_problems(
        self, plan: QualificationPlan, case: CasePlan, command: list[str]
    ) -> list[str]:
        problems: list[str] = []
        head = self.seams.git_head(self.install / "source")
        if head != plan.runtime_commit:
            problems.append(
                f"ComfyUI source is {head[:12]}, the plan pins {plan.runtime_commit[:12]}"
            )
        if template_digest() != plan.graph_sha256:
            problems.append("the catalog template no longer hashes to the plan's graph digest")
        for flag in plan.launch_flags:
            if flag not in command:
                problems.append(f"launch flag {flag} is missing")
        pins = {p.role: p for p in plan.inputs}
        for role in (case.driving_role, ROLE_REFERENCE):
            pin, path = pins.get(role), self.inputs.get(role)
            if pin is None or not pin.sha256:
                problems.append(f"{role} is not pinned")
            elif path is None or not Path(path).is_file():
                problems.append(f"{role} file is missing")
            elif sha256_file(Path(path)) != pin.sha256:
                problems.append(f"{role} bytes differ from the pinned SHA-256")
        if (plan.width, plan.height) != GEOMETRY:
            problems.append("the plan geometry is not the portrait default")
        return problems

    # -- one case -----------------------------------------------------------------------------------------------------
    def run_case(
        self, plan: QualificationPlan, phase: PhasePlan, case: CasePlan
    ) -> CaseObservation:
        if phase.phase_id == PHASE_Q0:
            raise RuntimeError("Q0 never executes")
        root = self.evidence_root / case.case_id
        root.mkdir(parents=True)  # a case id is used once; no reuse, no restart
        runtime = root / "runtime"
        for folder in ("input", "output", "temp", "user"):
            (runtime / folder).mkdir(parents=True)
        write_model_paths(runtime)
        command = launch_command(runtime)
        state = _CaseState()
        monitor: Monitor | None = None
        manager = None
        client = None
        started = datetime.now(UTC)
        pid: int | None = None
        pids: set[int] = set()
        baseline_vram = 0.0
        peak: dict[str, float | None] = {"commit": None, "ram": None, "vram": None}

        problems = self._identity_problems(plan, case, command)
        if problems:
            write_json(root / "identity-refusal.json", {"problems": problems})
            return CaseObservation(
                phase.phase_id,
                case.case_id,
                False,
                case.frames,
                0,
                stop_code=STOP_IDENTITY,
                identity_verified=False,
                note="; ".join(problems),
            )
        try:
            write_json(root / "events-before.json", self.seams.event_log(started))
            baseline_vram = self.seams.gpu_memory()[0]
            write_json(root / "plan-case.json", {"case": asdict(case), "plan_digest": plan.digest})

            reference = Path(self.inputs[ROLE_REFERENCE])
            driving = Path(self.inputs[case.driving_role])
            reference_name = f"fun354_reference{reference.suffix.lower()}"
            driving_name = f"fun354_driving{driving.suffix.lower()}"
            shutil.copyfile(reference, runtime / "input" / reference_name)
            shutil.copyfile(driving, runtime / "input" / driving_name)
            if sha256_file(runtime / "input" / driving_name) != sha256_file(driving):
                raise RuntimeError("The staged driving clip differs from the source.")
            graph = render_graph(
                plan, case, reference_name=reference_name, driving_name=driving_name
            )
            write_json(root / "graph.json", graph)

            from src.video.comfy_process_manager import ComfyProcessConfig

            base_url = f"http://127.0.0.1:{PORT}"
            manager = self.seams.manager_factory(
                ComfyProcessConfig(
                    command=command,
                    working_dir=str(self.install / "source"),
                    base_url=base_url,
                    log_path=root / "comfy.log",
                    startup_timeout_seconds=STARTUP_TIMEOUT_SECONDS,
                )
            )
            client = self.seams.client_factory(base_url)

            def sample() -> Sample:
                commit, available = self.seams.system_memory()
                used, total = self.seams.gpu_memory()
                return Sample(self.seams.clock() - t0, commit, available, used, total)

            def logs() -> str:
                return "\n".join(manager.get_stdout_tail() + manager.get_stderr_tail())

            def hard_stop() -> None:
                if manager.owns_process:
                    manager.stop(grace_seconds=0)

            t0 = self.seams.clock()
            monitor = Monitor(
                sample_fn=sample,
                log_fn=logs,
                stop_fn=hard_stop,
                journal=root / "telemetry.jsonl",
                interval=self.seams.monitor_interval,
                clock=self.seams.clock,
            )
            monitor.start()
            if manager.owns_process:
                raise RuntimeError("Qualification requires a fresh manager with no prior child")
            manager.start()
            if not manager.owns_process or not manager.contained:
                raise RuntimeError("Owned process containment was not established")
            state.launched = True
            pid = manager.pid
            if pid:
                pids.add(pid)
                pids.update(self.seams.child_pids(pid))
            manager.check_health()
            stats = client.get_system_stats(timeout=5)
            write_json(root / "runtime-stats.json", stats)
            system = stats.get("system", {})
            if any(system.get(k) != v for k, v in EXPECTED_RUNTIME.items()) or not str(
                system.get("python_version", "")
            ).startswith(EXPECTED_PYTHON_PREFIX):
                state.identity_ok = False
                raise RuntimeError("Pinned runtime identity mismatch")
            info = client.get_object_info(timeout=30)
            validate_schema(info, graph)

            submitted = self.seams.clock()
            reply = client.queue_prompt({"prompt": graph})
            prompt_id = str(reply["prompt_id"])
            write_json(root / "dispatch.json", {"prompt_id": prompt_id})
            history = self._await(client, monitor, prompt_id, case, phase, submitted, state)
            state.wall = self.seams.clock() - submitted
            if history is not None:
                write_json(root / "history.json", history)
            if monitor.stop_code:
                state.stop_code = monitor.stop_code
            elif case.cancel_after_seconds:
                self._finish_cancel(client, history, state, root)
            elif history is not None:
                self._finish_run(history, runtime, case, plan, state, root)
            if pid:
                pids.update(self.seams.child_pids(pid))
        except BaseException as exc:  # noqa: BLE001 - recorded as evidence, never retried
            state.notes.append(f"{type(exc).__name__}: {exc}")
            if monitor is not None and monitor.stop_code:
                state.stop_code = monitor.stop_code
            elif not state.identity_ok:
                state.stop_code = STOP_IDENTITY
            elif ALLOCATION_FAILURE.search(str(exc)):
                state.stop_code = STOP_ALLOCATION
            else:
                state.stop_code = state.stop_code or "executor_error"
            state.completed = False
        finally:
            self._teardown(manager, client, monitor, pids, baseline_vram, state, root, started)
            if monitor is not None:
                peak = {
                    "commit": monitor.guard.peak_commit or None,
                    "ram": monitor.guard.min_available_mib,
                    "vram": monitor.guard.peak_vram_mib or None,
                }
                state.telemetry_ok = state.telemetry_ok and monitor.complete
                if monitor.stop_code and not state.stop_code:
                    state.stop_code = monitor.stop_code
            else:
                state.telemetry_ok = False

        cancel = bool(case.cancel_after_seconds)
        return CaseObservation(
            phase.phase_id,
            case.case_id,
            state.completed,
            0 if cancel else case.frames,
            state.delivered,
            stop_code=state.stop_code,
            identity_verified=state.identity_ok,
            telemetry_complete=state.telemetry_ok,
            teardown_clean=state.teardown_ok,
            peak_host_commit_fraction=peak["commit"],
            min_available_ram_mib=int(peak["ram"]) if peak["ram"] is not None else None,
            peak_vram_mib=int(peak["vram"]) if peak["vram"] is not None else None,
            wall_seconds=round(state.wall, 1),
            note=" | ".join(state.notes),
        )

    def _await(
        self,
        client: Any,
        monitor: Monitor,
        prompt_id: str,
        case: CasePlan,
        phase: PhasePlan,
        submitted: float,
        state: _CaseState,
    ) -> dict[str, Any] | None:
        s = self.seams
        cancelled = False
        while True:
            if monitor.stop_code:
                return None
            elapsed = s.clock() - submitted
            if case.cancel_after_seconds and not cancelled and elapsed >= case.cancel_after_seconds:
                client.interrupt(prompt_id)
                cancelled = True
                state.notes.append(f"interrupt sent at {elapsed:.0f}s")
            record = client.get_history(prompt_id, timeout=5).get(prompt_id)
            if record:
                status = record.get("status", {})
                if status.get("completed") or status.get("status_str") == "error":
                    return record
            if cancelled and elapsed >= case.cancel_after_seconds + INTERRUPT_SETTLE_SECONDS:
                state.notes.append("the interrupt did not settle in time")
                monitor.abort(STOP_TIMEOUT)
                return None
            if elapsed > phase.wall_limit_seconds:
                try:
                    client.interrupt(prompt_id)
                finally:
                    monitor.abort(STOP_TIMEOUT)
                return None
            s.sleep(0.5)

    def _finish_run(
        self,
        history: Mapping[str, Any],
        runtime: Path,
        case: CasePlan,
        plan: QualificationPlan,
        state: _CaseState,
        root: Path,
    ) -> None:
        status = history.get("status", {})
        if status.get("status_str") == "error":
            detail = json.dumps(status)[-3000:]
            if ALLOCATION_FAILURE.search(detail):
                state.stop_code = STOP_ALLOCATION
            raise RuntimeError("Comfy execution error: " + detail)
        records = validate_frames(
            history, runtime / "output", case.frames, (plan.width, plan.height)
        )
        write_json(root / "frames.json", records)
        state.delivered = len(records)
        state.completed = True

    def _finish_cancel(
        self, client: Any, history: Mapping[str, Any] | None, state: _CaseState, root: Path
    ) -> None:
        if history is None:
            raise RuntimeError("The cancelled prompt produced no history entry.")
        status = history.get("status", {})
        images = history.get("outputs", {}).get(SAVE_NODE, {}).get("images", [])
        interrupted = any(
            m and m[0] == "execution_interrupted" for m in (status.get("messages") or [])
        )
        if status.get("completed") and not interrupted and images:
            state.notes.append("the generation finished before the interrupt took effect")
            state.completed = False  # the cancel path was not exercised; INCONCLUSIVE
            return
        queue = client.get_queue(timeout=5)
        write_json(root / "queue-after-cancel.json", queue)
        if queue.get("queue_running"):
            raise RuntimeError("Comfy still reports a running prompt after the interrupt.")
        state.completed = True  # a cancel case "delivers" zero frames by design
        state.delivered = 0

    def _teardown(
        self,
        manager: Any,
        client: Any,
        monitor: Monitor | None,
        pids: set[int],
        baseline_vram: float,
        state: _CaseState,
        root: Path,
        started: datetime,
    ) -> None:
        s = self.seams
        try:
            if manager is not None and manager.owns_process:
                manager.stop(grace_seconds=5.0)
        except Exception as exc:  # noqa: BLE001
            state.notes.append(f"stop failed: {exc}")
        if monitor is not None:
            monitor.close()
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        deadline = s.clock() + TEARDOWN_GRACE_SECONDS
        alive = sorted(p for p in pids if s.pid_exists(p))
        while alive and s.clock() < deadline:
            s.sleep(1.0)
            alive = sorted(p for p in pids if s.pid_exists(p))
        vram_after = None
        released = True
        if state.launched:
            while True:
                try:
                    vram_after = s.gpu_memory()[0]
                except Exception as exc:  # noqa: BLE001
                    state.notes.append(f"vram read failed: {exc}")
                    state.telemetry_ok = False
                    released = False
                    break
                released = vram_after <= baseline_vram + VRAM_RELEASE_TOLERANCE_MIB
                if released or s.clock() >= deadline:
                    break
                s.sleep(1.0)
        verified = not alive and (bool(pids) or not state.launched)
        write_json(
            root / "teardown.json",
            {
                "owned_pids": sorted(pids),
                "surviving_pids": alive,
                "baseline_vram_mib": baseline_vram,
                "vram_after_mib": vram_after,
                "vram_released": released,
                "verified": verified and released,
            },
        )
        if not verified or not released:
            state.teardown_ok = False
            state.stop_code = state.stop_code or STOP_TEARDOWN
        try:
            events = s.event_log(started)
            write_json(root / "events-after.json", events)
            faults = fault_events(events)
            if faults:
                state.stop_code = state.stop_code or STOP_DEVICE_LOSS
                state.notes.append(f"{len(faults)} fault event(s) in the system log")
        except Exception as exc:  # noqa: BLE001
            state.telemetry_ok = False
            state.notes.append(f"event log unavailable: {exc}")


# ---- CLI ----------------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from tools.qualification.fun354.inputs import load_input_set

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="the stored plan json from `propose`")
    parser.add_argument("--inputs-manifest", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--authorize-plan", required=True, help="the plan digest being authorized")
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--evidence-root", default=str(EVIDENCE_ROOT))
    args = parser.parse_args(argv)

    record = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    plan = rebuild_plan(record)
    if plan.digest != record.get("digest"):
        raise SystemExit("The stored plan does not match the current catalog and tooling.")
    if args.authorize_plan != plan.digest:
        raise SystemExit("The authorization does not match this plan's digest.")
    input_set = load_input_set(args.inputs_manifest, args.reference)
    if input_set.build_plan().digest != plan.digest:
        raise SystemExit("The inputs on disk no longer produce this plan.")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = Path(args.evidence_root) / stamp
    evidence.mkdir(parents=True)
    write_json(
        evidence / "authorization.json",
        {
            "plan_digest": plan.digest,
            "authorized_by": args.authorized_by,
            "scope": "physical_execution",
        },
    )
    write_json(evidence / "plan.json", {**plan.to_record(), "digest": plan.digest})

    folders = model_folders(["--base-directory", str(MODEL_BASE)], str(INSTALL / "source"))
    report = q0_module.run_q0(
        plan,
        folders=folders,
        host=q0_module.read_host_facts(evidence),
        inputs=input_set.paths,
        runtime_commit=git_head(INSTALL / "source"),
    )
    write_json(evidence / "q0.json", report.to_record())
    print(f"Q0 {report.status}")
    for check in report.checks:
        print(f"  [{check.status}] {check.check_id}: {check.detail}", flush=True)
    executor = PhysicalExecutor(inputs=input_set.paths, evidence_root=evidence / "cases")
    (evidence / "cases").mkdir()
    outcome = run_qualification(
        plan, report, executor, Authorization(plan.digest, args.authorized_by)
    )
    write_json(evidence / "outcome.json", outcome.to_record())
    print(f"{outcome.verdict}: {outcome.reason}")
    for obs in outcome.observations:
        print(
            f"  {obs.case_id}: completed={obs.completed} frames={obs.frames_delivered}/{obs.frames_expected} "
            f"stop={obs.stop_code or '-'} wall={obs.wall_seconds}s vram={obs.peak_vram_mib} "
            f"commit={obs.peak_host_commit_fraction} ram_min={obs.min_available_ram_mib} {obs.note[:160]}",
            flush=True,
        )
    return 0 if outcome.verdict == "FEASIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
