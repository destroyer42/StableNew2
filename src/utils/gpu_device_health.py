"""Read-only host GPU evidence and the accelerator-fault vocabulary (PR-QUEUE-GPU-180).

Two small, pure-ish building blocks for GPU device-loss containment:

* :func:`probe_host_gpu` asks NVIDIA's own tool one bounded, read-only question ("which devices enumerate, with
  readable memory fields?") and returns a typed, content-free :class:`HostGpuEvidence`. It never resets a driver,
  never starts, stops or signals a process and never runs a workload.
* :func:`classify_accelerator_fault` maps failure *text* (a WebUI response body, an exception message) to a fixed
  vocabulary of codes. The code is a *suspicion* that gates the host probe; it is never, by itself, proof of device
  loss. Only host evidence confirms a loss.

Nothing here owns queue, lifecycle or process authority.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

SCHEMA = "stablenew.gpu-host-evidence.v1"
#: Production honours this switch; deterministic pytest pins it off (``tests/conftest.py``).
PROBE_ENV = "STABLENEW_GPU_HOST_PROBE"
DEFAULT_TIMEOUT_S = 4.0
_QUERY = "--query-gpu=index,name,pci.bus_id,memory.total,memory.used"
_FORMAT = "--format=csv,noheader,nounits"
_FIELD_COUNT = 5
_MAX_TEXT = 8000


class HostGpuState(str, Enum):
    #: Every queried device enumerates with readable memory fields.
    HEALTHY = "healthy"
    #: NVIDIA's tool itself reports the device as lost / no longer enumerable.
    DEVICE_LOST = "device_lost"
    #: The question could not be answered (tool missing, timeout, driver not answering, unreadable fields).
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class HostGpuEvidence:
    state: HostGpuState
    #: Stable reason code (never raw tool output, device names or bus identifiers).
    reason: str
    device_count: int = 0
    source: str = "nvidia-smi"

    @property
    def positive_recovery(self) -> bool:
        """Healthy enumeration is the only positive evidence that a recovered device is present."""

        return self.state is HostGpuState.HEALTHY and self.device_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "state": self.state.value,
            "reason": self.reason,
            "device_count": self.device_count,
        }


def _unavailable(reason: str) -> HostGpuEvidence:
    return HostGpuEvidence(HostGpuState.UNAVAILABLE, reason)


def _field_is_unreadable(value: str) -> bool:
    lowered = value.strip().lower()
    return not lowered or "error" in lowered or lowered in {"err!", "n/a", "[n/a]", "unknown"}


def _parse_rows(stdout: str) -> tuple[int, int]:
    """Return ``(valid_rows, malformed_rows)`` over the query's CSV rows (rows of another shape are ignored)."""

    valid = malformed = 0
    for row in csv.reader(io.StringIO(stdout or ""), skipinitialspace=True):
        if len(row) != _FIELD_COUNT:
            continue
        index, name, bus, total, used = (field.strip() for field in row)
        try:
            readable = (
                not any(_field_is_unreadable(field) for field in (index, name, bus, total, used))
                and int(index) >= 0
                and float(total) > 0
                and float(used) >= 0
            )
        except ValueError:
            readable = False
        if readable:
            valid += 1
        else:
            malformed += 1
    return valid, malformed


def classify_nvidia_smi_output(returncode: int, stdout: str, stderr: str) -> HostGpuEvidence:
    """Pure classification of the bounded query's outcome (incident output shapes are covered by tests)."""

    text = f"{(stdout or '')[:_MAX_TEXT]}\n{(stderr or '')[:_MAX_TEXT]}".lower()
    if "gpu is lost" in text or "fallen off the bus" in text:
        return HostGpuEvidence(HostGpuState.DEVICE_LOST, "gpu_is_lost")
    if "no devices were found" in text:
        return HostGpuEvidence(HostGpuState.DEVICE_LOST, "no_devices_found")
    if "couldn't communicate with the nvidia driver" in text:
        return _unavailable("driver_communication_failed")
    if "unable to determine the device handle" in text:
        return _unavailable("device_handle_unavailable")
    valid, malformed = _parse_rows(stdout)
    if malformed:
        return _unavailable("device_fields_unreadable")
    if returncode == 0 and valid > 0:
        return HostGpuEvidence(HostGpuState.HEALTHY, "gpu_enumerated", device_count=valid)
    return _unavailable("unrecognized_output")


#: Extra time the caller waits after the query's own timeout (kill + collect) before it abandons the query.
_HARD_BOUND_GRACE_S = 1.0


class ProbeGate:
    """Single-flight guard for the host query.

    ``subprocess.run(timeout=...)`` kills the child and then waits for it *without* a bound, so a query stuck in an
    uninterruptible driver call (the very failure this feature exists for) could block its caller indefinitely. The
    query therefore runs on a daemon thread that the caller abandons at a hard deadline, and a still-stuck thread is
    never stacked under a second one: while it lives, further probes answer ``probe_busy`` immediately.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def launch(self, target: Callable[[], None]) -> threading.Thread | None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return None
            thread = threading.Thread(target=target, name="GpuHostProbe", daemon=True)
            self._thread = thread
            thread.start()
            return thread


_DEFAULT_GATE = ProbeGate()


def probe_host_gpu(
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., Any] = subprocess.run,
    gate: ProbeGate | None = None,
) -> HostGpuEvidence:
    """One read-only NVIDIA enumeration query, hard-bounded; failure to obtain evidence is ``UNAVAILABLE``."""

    executable = which("nvidia-smi")
    if not executable:
        return _unavailable("nvidia_smi_missing")
    bound = max(0.5, float(timeout_s))
    outcome: dict[str, Any] = {}

    def query() -> None:
        try:
            outcome["completed"] = run(
                [executable, _QUERY, _FORMAT],
                capture_output=True,
                text=True,
                timeout=bound,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            outcome["reason"] = "probe_timeout"
        except Exception:  # noqa: BLE001 - evidence is best-effort; a failed query is "unavailable"
            outcome["reason"] = "probe_error"

    worker = (gate or ProbeGate()).launch(query)
    if worker is None:
        return _unavailable("probe_busy")
    worker.join(bound + _HARD_BOUND_GRACE_S)
    if worker.is_alive():
        return _unavailable("probe_timeout")  # abandoned; the gate answers probe_busy until it ends
    completed = outcome.get("completed")
    if completed is None:
        return _unavailable(str(outcome.get("reason") or "probe_error"))
    return classify_nvidia_smi_output(
        int(getattr(completed, "returncode", 1)),
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    )


def default_host_probe() -> HostGpuEvidence:
    """The production probe seam (injectable everywhere it is used; disabled by the environment switch)."""

    if os.environ.get(PROBE_ENV, "").strip().lower() in {"0", "false", "no", "off"}:
        return _unavailable("host_probe_disabled")
    return probe_host_gpu(gate=_DEFAULT_GATE)


class AcceleratorFault(str, Enum):
    #: The accelerator runtime reported a device-level fault (unknown error, launch failure, illegal access, ...).
    DEVICE_FAULT = "device_fault"
    #: Allocation failure: the driver answered, so the device is demonstrably still there.
    OUT_OF_MEMORY = "out_of_memory"
    #: Numerical model/precision failure.
    NUMERIC_FAULT = "numeric_fault"


_DEVICE_FAULT_MARKERS = (
    "cuda error: unknown error",
    "cuda unknown error",
    "cuda error: unspecified launch failure",
    "illegal memory access",
    "device-side assert",
    "cuda error: the launch timed out",
    "cuda error: launch failure",
    "uncorrectable ecc error",
    "no cuda-capable device",
    "no cuda gpus are available",
    "cuda driver error",
    "gpu is lost",
    "fallen off the bus",
    "nvml_error_gpu_is_lost",
)
_OOM_MARKERS = (
    "cuda out of memory",
    "cuda error: out of memory",
    "outofmemoryerror",
    "out of memory",
)
_NUMERIC_MARKERS = (
    "nansexception",
    "tensor with nans",
    "not enough precision to represent the picture",
    "does not support half type",
)
#: ``torch.AcceleratorError`` is the exception class of a CUDA runtime failure; counted only when no allocation
#: failure explains it.
_GENERIC_ACCELERATOR_MARKER = "acceleratorerror"


def classify_accelerator_fault(*texts: Any) -> AcceleratorFault | None:
    """Fixed-vocabulary classification of failure text; returns only a code (never the text)."""

    combined = " | ".join(str(text)[:_MAX_TEXT] for text in texts if text).lower()
    if not combined:
        return None
    if any(marker in combined for marker in _DEVICE_FAULT_MARKERS):
        return AcceleratorFault.DEVICE_FAULT
    if any(marker in combined for marker in _OOM_MARKERS):
        return AcceleratorFault.OUT_OF_MEMORY
    if _GENERIC_ACCELERATOR_MARKER in combined:
        return AcceleratorFault.DEVICE_FAULT
    if any(marker in combined for marker in _NUMERIC_MARKERS):
        return AcceleratorFault.NUMERIC_FAULT
    return None


__all__ = [
    "PROBE_ENV",
    "SCHEMA",
    "AcceleratorFault",
    "HostGpuEvidence",
    "HostGpuState",
    "ProbeGate",
    "classify_accelerator_fault",
    "classify_nvidia_smi_output",
    "default_host_probe",
    "probe_host_gpu",
]
