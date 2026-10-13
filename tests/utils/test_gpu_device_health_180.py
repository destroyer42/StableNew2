"""PR-QUEUE-GPU-180: read-only host GPU evidence and the accelerator-fault vocabulary (pure, offline)."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from src.utils import gpu_device_health as health
from src.utils.gpu_device_health import AcceleratorFault, HostGpuState

# Real incident output (GPU-20261012-2228): stdout of ``nvidia-smi`` and the bounded query's stderr.
INCIDENT_NO_DEVICES = "No devices were found\n"
INCIDENT_GPU_LOST = (
    "Unable to determine the device handle for GPU0: 0000:01:00.0: GPU is lost.  "
    "Reboot the system to recover this GPU\n\n"
)
HEALTHY_ROW = "0, NVIDIA GeForce RTX 4070 Ti, 00000000:01:00.0, 12282, 1508\n"


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "state", "reason"),
    [
        (6, INCIDENT_NO_DEVICES, "", HostGpuState.DEVICE_LOST, "no_devices_found"),
        (15, "", INCIDENT_GPU_LOST, HostGpuState.DEVICE_LOST, "gpu_is_lost"),
        (15, HEALTHY_ROW, INCIDENT_GPU_LOST, HostGpuState.DEVICE_LOST, "gpu_is_lost"),
        (0, HEALTHY_ROW, "", HostGpuState.HEALTHY, "gpu_enumerated"),
        (0, HEALTHY_ROW + HEALTHY_ROW.replace("0,", "1,", 1), "", HostGpuState.HEALTHY, "gpu_enumerated"),
        (0, "0, NVIDIA GeForce RTX 4070 Ti, 00000000:01:00.0, [Unknown Error], [Unknown Error]\n", "",
         HostGpuState.UNAVAILABLE, "device_fields_unreadable"),
        (0, "0, NVIDIA GeForce RTX 4070 Ti, 00000000:01:00.0, ERR!, ERR!\n", "",
         HostGpuState.UNAVAILABLE, "device_fields_unreadable"),
        (9, "", "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver. "
              "Make sure that the latest NVIDIA driver is installed and running.\n",
         HostGpuState.UNAVAILABLE, "driver_communication_failed"),
        (15, "", "Unable to determine the device handle for GPU0: 0000:01:00.0: Unknown Error\n",
         HostGpuState.UNAVAILABLE, "device_handle_unavailable"),
        (0, "", "", HostGpuState.UNAVAILABLE, "unrecognized_output"),
        (0, "something unexpected\n", "", HostGpuState.UNAVAILABLE, "unrecognized_output"),
    ],
)
def test_nvidia_smi_output_is_classified_into_typed_host_state(returncode, stdout, stderr, state, reason):
    evidence = health.classify_nvidia_smi_output(returncode, stdout, stderr)
    assert (evidence.state, evidence.reason) == (state, reason)
    if state is HostGpuState.HEALTHY:
        assert evidence.device_count == stdout.count("\n")
    else:
        assert evidence.device_count == 0


def test_evidence_projection_is_content_free():
    evidence = health.classify_nvidia_smi_output(15, "", INCIDENT_GPU_LOST)
    projected = evidence.to_dict()
    assert projected == {
        "source": "nvidia-smi",
        "state": "device_lost",
        "reason": "gpu_is_lost",
        "device_count": 0,
    }
    assert "0000:01:00.0" not in repr(projected)


def _runner(result=None, raises=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if raises is not None:
            raise raises
        return result

    return run, calls


def test_probe_is_one_bounded_read_only_query():
    run, calls = _runner(SimpleNamespace(returncode=0, stdout=HEALTHY_ROW, stderr=""))
    evidence = health.probe_host_gpu(timeout_s=2.5, which=lambda name: f"C:/bin/{name}.exe", run=run)
    assert evidence.state is HostGpuState.HEALTHY and evidence.device_count == 1
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[0] == "C:/bin/nvidia-smi.exe"
    # Query/format flags only: nothing that resets, persists, kills or reconfigures.
    assert all(arg.startswith(("--query-gpu=", "--format=")) for arg in argv[1:])
    assert kwargs["timeout"] == 2.5 and kwargs["check"] is False and kwargs["capture_output"] is True


@pytest.mark.parametrize(
    ("which", "raises", "reason"),
    [
        (lambda _name: None, None, "nvidia_smi_missing"),
        (lambda name: name, subprocess.TimeoutExpired("nvidia-smi", 1.0), "probe_timeout"),
        (lambda name: name, OSError("denied"), "probe_error"),
    ],
)
def test_unobtainable_evidence_is_unavailable_never_lost(which, raises, reason):
    run, _calls = _runner(raises=raises)
    evidence = health.probe_host_gpu(which=which, run=run)
    assert (evidence.state, evidence.reason) == (HostGpuState.UNAVAILABLE, reason)


def test_default_probe_honours_the_environment_switch(monkeypatch):
    monkeypatch.setenv("STABLENEW_GPU_HOST_PROBE", "0")
    monkeypatch.setattr(
        health, "probe_host_gpu", lambda **_k: pytest.fail("a disabled probe must not run nvidia-smi")
    )
    evidence = health.default_host_probe()
    assert (evidence.state, evidence.reason) == (HostGpuState.UNAVAILABLE, "host_probe_disabled")


@pytest.mark.parametrize(
    "text",
    [
        "txt2img error: AcceleratorError: CUDA error: unknown error\nCUDA kernel errors might be asynchronously reported",
        "CUDA error: unspecified launch failure",
        "RuntimeError: CUDA error: an illegal memory access was encountered",
        "CUDA error: device-side assert triggered",
        "CUDA error: the launch timed out and was terminated",
        "torch.AcceleratorError: something new",
        "No CUDA GPUs are available",
        "NVML_ERROR_GPU_IS_LOST",
        "GPU is lost. Reboot the system to recover this GPU",
    ],
)
def test_device_fault_signatures(text):
    assert health.classify_accelerator_fault(text) is AcceleratorFault.DEVICE_FAULT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB", AcceleratorFault.OUT_OF_MEMORY),
        ("CUDA error: out of memory", AcceleratorFault.OUT_OF_MEMORY),
        # An OOM that happens to carry the generic asynchronous-error advice is still just an OOM.
        ("CUDA out of memory.\nCUDA kernel errors might be asynchronously reported at some other API call",
         AcceleratorFault.OUT_OF_MEMORY),
        ("NansException: A tensor with NaNs was produced in Unet", AcceleratorFault.NUMERIC_FAULT),
        ("HTTP 500 Internal Server Error", None),
        ("HTTP 422 unprocessable entity: sampler not found", None),
        ("Connection refused", None),
        ("", None),
        (None, None),
    ],
)
def test_ordinary_failures_are_not_device_faults(text, expected):
    assert health.classify_accelerator_fault(text) is expected


def test_device_fault_wins_over_numeric_and_oom_text_but_ignores_generic_advice_alone():
    assert (
        health.classify_accelerator_fault("tensor with nans", "CUDA error: unknown error")
        is AcceleratorFault.DEVICE_FAULT
    )
    assert health.classify_accelerator_fault("CUDA kernel errors might be asynchronously reported") is None
