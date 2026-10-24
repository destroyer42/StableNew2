"""A verified memory ceiling for bounded children (IMG-QUAL-330).

``run_bounded(memory_limit_mb=...)`` asks the OS container for a committed-memory limit and refuses to start the child
unless the container reports exactly that limit. The model-backed reference-map and Smart Review children use it through
``providers.bounded_runner``. Without the argument nothing changes.
"""

from __future__ import annotations

import inspect
import math
import os
import sys
from typing import Any

import pytest

from src.conditioning.reference_map import providers
from src.review.assist import providers as assist_providers
from src.utils import managed_process
from src.utils.managed_process import ContainmentError, ProcessOutcome, run_bounded
from src.utils.process_container_v2 import (
    NullProcessContainer,
    ProcessContainer,
    ProcessContainerConfig,
)

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

_PY = sys.executable
_ALLOCATE_MB = "x = bytearray({mb} * 1024 * 1024); print(len(x))"


_MB = 1024 * 1024


class _RecordingContainer(NullProcessContainer):
    """A container whose OS read-back says whatever the test wants. ``inspect`` lies on purpose: it must not be trusted."""

    def __init__(
        self, job_id: str, config: ProcessContainerConfig, enforced_bytes: int | None
    ) -> None:
        super().__init__(job_id, config, "test")
        self._enforced = enforced_bytes
        self.torn_down = False

    def enforced_memory_limit_bytes(self) -> int | None:
        return self._enforced

    def inspect(self) -> dict[str, Any]:
        return {"memory_limit_mb": self.config.memory_limit_mb}

    def teardown(self) -> None:
        self.torn_down = True


def _fake_builder(enforced: int | None, built: list[_RecordingContainer]):
    def build(job_id: str, config: ProcessContainerConfig) -> ProcessContainer:
        container = _RecordingContainer(job_id, config, enforced)
        built.append(container)
        return container

    return build


def test_a_limit_the_os_does_not_confirm_means_no_child_even_if_the_container_remembers_asking(
    monkeypatch,
) -> None:
    built: list[_RecordingContainer] = []
    launched: list[object] = []
    monkeypatch.setattr(managed_process, "build_process_container", _fake_builder(None, built))
    monkeypatch.setattr(
        managed_process, "launch_contained", lambda *a, **k: launched.append(a) or None
    )

    outcome = run_bounded(
        [_PY, "-c", "print(1)"], timeout_seconds=5, max_stdout_bytes=1024, memory_limit_mb=512
    )

    assert launched == [], "the child must not start without the confirmed limit"
    assert outcome.returncode is None and "512 MB memory limit" in (outcome.launch_error or "")
    assert built[0].config.memory_limit_mb == 512 and built[0].torn_down is True


def test_a_different_enforced_limit_is_not_confirmation(monkeypatch) -> None:
    built: list[_RecordingContainer] = []
    monkeypatch.setattr(
        managed_process, "build_process_container", _fake_builder(1024 * _MB, built)
    )
    outcome = run_bounded(
        [_PY, "-c", "print(1)"], timeout_seconds=5, max_stdout_bytes=1024, memory_limit_mb=512
    )
    assert outcome.returncode is None and "could not be established" in (outcome.launch_error or "")
    assert built[0].torn_down is True


def test_spawn_raises_containment_error_when_the_limit_is_not_established(monkeypatch) -> None:
    monkeypatch.setattr(managed_process, "build_process_container", _fake_builder(None, []))
    with pytest.raises(ContainmentError):
        managed_process._spawn_contained(  # noqa: SLF001
            [_PY, "-c", "pass"],
            label="x",
            require_containment=False,
            cwd=None,
            env=None,
            memory_limit_mb=256,
        )


def test_without_a_limit_nothing_changes(monkeypatch) -> None:
    configs: list[ProcessContainerConfig] = []
    real = managed_process.build_process_container

    def spy(job_id: str, config: ProcessContainerConfig) -> ProcessContainer:
        configs.append(config)
        return real(job_id, config)

    monkeypatch.setattr(managed_process, "build_process_container", spy)
    outcome = run_bounded([_PY, "-c", "print(7)"], timeout_seconds=30, max_stdout_bytes=1024)
    assert outcome.returncode == 0 and outcome.stdout.strip() == b"7"
    assert [config.memory_limit_mb for config in configs] == [None]


@pytest.mark.parametrize("value", [0, -1, -0.5, math.nan, math.inf])
def test_a_nonsense_limit_is_refused_before_anything_is_built(monkeypatch, value) -> None:
    built: list[_RecordingContainer] = []
    monkeypatch.setattr(managed_process, "build_process_container", _fake_builder(None, built))
    with pytest.raises(ValueError):
        run_bounded(
            [_PY, "-c", "pass"], timeout_seconds=5, max_stdout_bytes=1024, memory_limit_mb=value
        )
    assert built == []


@windows_only
def test_a_child_inside_the_limit_runs_and_one_beyond_it_cannot() -> None:
    inside = run_bounded(
        [_PY, "-c", _ALLOCATE_MB.format(mb=16)],
        timeout_seconds=60,
        max_stdout_bytes=1024,
        memory_limit_mb=512,
    )
    assert not inside.launch_error and inside.returncode == 0 and inside.contained

    beyond = run_bounded(
        [_PY, "-c", _ALLOCATE_MB.format(mb=1536)],
        timeout_seconds=60,
        max_stdout_bytes=1024,
        memory_limit_mb=512,
    )
    assert not beyond.launch_error
    assert beyond.returncode != 0, "a child allocating 3x its limit must fail, not succeed"
    assert b"1610612736" not in beyond.stdout

    control = run_bounded(
        [_PY, "-c", _ALLOCATE_MB.format(mb=1536)], timeout_seconds=60, max_stdout_bytes=1024
    )
    assert control.returncode == 0, "the same allocation must succeed without a limit"


@windows_only
def test_a_real_job_object_confirms_the_limit_it_was_given() -> None:
    from src.utils.process_container_v2 import build_process_container

    container = build_process_container("memlimit-probe", ProcessContainerConfig(True, 256))
    try:
        assert container.inspect()["memory_limit_mb"] == 256
    finally:
        container.teardown()


def test_the_model_runner_passes_the_documented_ceiling(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake(command, **kwargs):
        captured.update(kwargs)
        return ProcessOutcome(0)

    monkeypatch.setattr(providers, "run_bounded", fake)
    providers.bounded_runner(
        ["python"], timeout_seconds=1.0, max_stdout_bytes=1, cancel=None, env={}
    )
    assert providers.WORKER_MEMORY_LIMIT_MB == 6144
    assert captured["memory_limit_mb"] == 6144
    assert captured["allow_unenforced_memory_limit"] is True  # honoured off Windows only


def test_every_model_child_uses_the_capped_runner_by_default() -> None:
    assert providers.Context.__dataclass_fields__["runner"].default is providers.bounded_runner
    default = (
        inspect.signature(assist_providers._ChildAdapter.__init__).parameters["runner"].default
    )  # noqa: SLF001
    assert default is providers.bounded_runner
    from src.conditioning.reference_map.service import ReferenceMapService

    service_default = inspect.signature(ReferenceMapService.__init__).parameters["runner"].default
    assert service_default is providers.bounded_runner


@pytest.mark.parametrize(
    ("enforced_delta", "starts"),
    [
        (0, True),  # exact (job object)
        (4096, True),  # a cgroup rounds the limit down to a page
        (-4096, False),  # the OS holds a LAXER limit than asked for
        (64 * 1024, False),  # more than page rounding below the request
        (512 * _MB, False),
    ],
)
def test_only_the_requested_limit_up_to_page_rounding_is_accepted(
    monkeypatch, enforced_delta, starts
) -> None:
    requested = 512
    built: list[_RecordingContainer] = []
    launched: list[object] = []
    monkeypatch.setattr(
        managed_process,
        "build_process_container",
        _fake_builder(requested * _MB - enforced_delta, built),
    )
    monkeypatch.setattr(
        managed_process,
        "launch_contained",
        lambda *a, **k: launched.append(k)
        or managed_process._Spawned(None, a and k["container"], True),  # noqa: SLF001
    )
    # the stand-in launch returns no process, so run the spawn step directly
    try:
        managed_process._spawn_contained(  # noqa: SLF001
            [_PY, "-c", "pass"],
            label="x",
            require_containment=False,
            cwd=None,
            env=None,
            memory_limit_mb=requested,
        )
    except ContainmentError:
        assert not starts and launched == []
    else:
        assert starts and len(launched) == 1
        assert launched[0]["require_suspended"] is True


def test_the_cgroup_limit_is_read_back_from_memory_max(tmp_path) -> None:
    from src.utils.cgroup_v2 import LinuxCGroupV2

    cgroup = object.__new__(LinuxCGroupV2)
    cgroup._path = tmp_path  # noqa: SLF001
    cgroup._memory_limit_mb = 6144  # noqa: SLF001 - what was asked for; must not be what is reported
    assert cgroup.enforced_memory_limit_bytes() is None, "no memory.max file"
    for text, expected in [
        ("max\n", None),  # unlimited: the write was refused or never happened
        ("", None),
        ("garbage", None),
        ("0", None),
        ("6442450944\n", 6144 * _MB),
    ]:
        (tmp_path / "memory.max").write_text(text)
        assert cgroup.enforced_memory_limit_bytes() == expected, text


def test_the_base_container_confirms_nothing() -> None:
    container = NullProcessContainer("x", ProcessContainerConfig(True, 512), "test")
    assert container.enforced_memory_limit_bytes() is None


@windows_only
def test_a_real_job_object_reads_the_limit_back_from_the_os() -> None:
    from src.utils.process_container_v2 import build_process_container

    container = build_process_container("memlimit-readback", ProcessContainerConfig(True, 256))
    try:
        assert container.enforced_memory_limit_bytes() == 256 * _MB
    finally:
        container.teardown()
    assert container.enforced_memory_limit_bytes() is None, "a closed job confirms nothing"


@windows_only
def test_a_limit_the_os_refuses_is_not_started_even_though_the_job_object_survives(
    monkeypatch,
) -> None:
    from src.utils import win_jobobject

    real = win_jobobject.WindowsJobObject._set_limits  # noqa: SLF001

    def refuse_memory(self, info):
        if info.BasicLimitInformation.LimitFlags & win_jobobject.JOB_OBJECT_LIMIT_JOB_MEMORY:
            return False
        return real(self, info)

    monkeypatch.setattr(win_jobobject.WindowsJobObject, "_set_limits", refuse_memory)
    outcome = run_bounded(
        [_PY, "-c", "print(1)"], timeout_seconds=30, max_stdout_bytes=1024, memory_limit_mb=256
    )
    assert outcome.returncode is None and not outcome.stdout
    assert "could not be established" in (outcome.launch_error or "")


@windows_only
def test_a_limit_changed_behind_our_back_is_detected(monkeypatch) -> None:
    from src.utils.process_container_v2 import build_process_container

    def tampered(job_id: str, config: ProcessContainerConfig) -> ProcessContainer:
        container = build_process_container(job_id, config)
        inner = container._inner  # noqa: SLF001
        inner._memory_limit_mb = 1  # noqa: SLF001
        inner._apply_limits()  # noqa: SLF001 - the OS now holds 1 MB while the config says otherwise
        inner._memory_limit_mb = config.memory_limit_mb  # noqa: SLF001
        return container

    monkeypatch.setattr(managed_process, "build_process_container", tampered)
    outcome = run_bounded(
        [_PY, "-c", "print(1)"], timeout_seconds=30, max_stdout_bytes=1024, memory_limit_mb=256
    )
    assert outcome.returncode is None and "could not be established" in (outcome.launch_error or "")


@pytest.mark.parametrize("path", ["depth", "openpose", "sam2", "florence2"])
def test_each_model_backed_path_reaches_run_bounded_with_the_ceiling(
    monkeypatch, tmp_path, path
) -> None:
    """The four model children, built the way production builds them (default runner), all pass 6,144 MB per child."""

    import numpy as np

    from src.conditioning.reference_map import auxiliary
    from src.conditioning.reference_map.contracts import ReferenceMapError
    from src.conditioning.reference_map.providers import Context, run_worker
    from src.review.assist.contracts import AssistError, PointPrompt, SourceIdentity
    from src.review.assist.identity import LoadedSource

    captured: list[dict[str, Any]] = []

    def fake_run_bounded(command, **kwargs):
        captured.append(kwargs)
        return ProcessOutcome(0)  # no result.json: the call fails after the child "ran"

    monkeypatch.setattr(providers, "run_bounded", fake_run_bounded)
    rgb = np.zeros((8, 8, 3), np.uint8)
    if path in {"depth", "openpose"}:
        job = tmp_path / "job"
        job.mkdir()
        context = Context(registry=None, cancel=lambda: False)  # the default runner
        with pytest.raises(ReferenceMapError):
            run_worker(job, path, path, {}, rgb, context)
    else:
        monkeypatch.setattr(assist_providers, "runtime_reasons", lambda capability: ())
        monkeypatch.setattr(
            auxiliary,
            "verify_resource",
            lambda registry, modality, cancelled=None: auxiliary.VerifiedResource(modality, ()),
        )
        monkeypatch.setattr(
            auxiliary,
            "stage_resource",
            lambda resource, root, destination, cancelled=None: destination.mkdir(parents=True)
            or {},
        )
        registry = type("Registry", (), {"webui_root": tmp_path})()
        source = LoadedSource(SourceIdentity("0" * 64, 1, 8, 8, 1, "PNG"), rgb)
        with pytest.raises(AssistError):
            if path == "sam2":
                assist_providers.ChildSegmentAdapter(
                    lambda: registry, temp_root=str(tmp_path)
                ).segment(source, [PointPrompt(1, 1, True)], [], lambda: False)
            else:
                assist_providers.ChildCaptionAdapter(
                    lambda: registry, temp_root=str(tmp_path)
                ).caption(source, lambda: False)

    assert [call["memory_limit_mb"] for call in captured] == [6144]


def _no_container(monkeypatch) -> None:
    """A host with no container at all, like a Linux runner without cgroup v2; containment is not required there."""

    monkeypatch.setattr(
        managed_process,
        "build_process_container",
        lambda job_id, config: NullProcessContainer(
            job_id, config, "construction_failed: linux cgroup v2: CGroup v2 root not found"
        ),
    )
    monkeypatch.setattr(managed_process, "containment_required", lambda: False)


def _marker_command(marker) -> list[str]:
    return [_PY, "-c", f"open({str(marker)!r}, 'w').write('x')"]


def test_a_non_windows_host_that_cannot_enforce_the_cap_runs_the_child_with_a_loud_warning(
    monkeypatch, tmp_path, caplog
) -> None:
    _no_container(monkeypatch)
    monkeypatch.setattr(managed_process, "_unenforced_fallback_allowed", lambda: True)
    marker = tmp_path / "ran"
    with caplog.at_level("WARNING", logger=managed_process.logger.name):
        outcome = run_bounded(
            _marker_command(marker),
            timeout_seconds=30,
            max_stdout_bytes=1024,
            memory_limit_mb=512,
            allow_unenforced_memory_limit=True,
        )
    assert outcome.returncode == 0 and not outcome.launch_error and marker.exists()
    assert outcome.memory_limit_enforced is False
    assert any("WITHOUT a memory limit" in record.getMessage() for record in caplog.records)


def test_without_the_opt_in_a_host_that_cannot_enforce_the_cap_still_starts_nothing(
    monkeypatch, tmp_path
) -> None:
    _no_container(monkeypatch)
    monkeypatch.setattr(managed_process, "_unenforced_fallback_allowed", lambda: True)
    marker = tmp_path / "ran"
    outcome = run_bounded(
        _marker_command(marker), timeout_seconds=30, max_stdout_bytes=1024, memory_limit_mb=512
    )
    assert outcome.returncode is None and "could not be established" in outcome.launch_error
    assert outcome.memory_limit_enforced is None and not marker.exists()


@windows_only
def test_windows_never_runs_a_child_without_the_cap_even_when_the_caller_allows_it(
    monkeypatch, tmp_path
) -> None:
    from src.utils import win_jobobject

    real = win_jobobject.WindowsJobObject._set_limits  # noqa: SLF001

    def refuse_memory(self, info):
        if info.BasicLimitInformation.LimitFlags & win_jobobject.JOB_OBJECT_LIMIT_JOB_MEMORY:
            return False
        return real(self, info)

    monkeypatch.setattr(win_jobobject.WindowsJobObject, "_set_limits", refuse_memory)
    marker = tmp_path / "ran"
    outcome = providers.bounded_runner(
        _marker_command(marker),
        timeout_seconds=30,
        max_stdout_bytes=1024,
        cancel=None,
        env=providers.worker_environment(),
    )
    assert outcome.returncode is None and "could not be established" in outcome.launch_error
    assert not marker.exists(), "Windows must never run a model child outside the cap"


@windows_only
def test_an_established_cap_is_reported_as_enforced() -> None:
    outcome = run_bounded(
        [_PY, "-c", "print(1)"],
        timeout_seconds=30,
        max_stdout_bytes=1024,
        memory_limit_mb=512,
        allow_unenforced_memory_limit=True,
    )
    assert outcome.returncode == 0 and outcome.memory_limit_enforced is True


@pytest.mark.skipif(
    os.name == "nt" or os.path.exists("/sys/fs/cgroup/stablenew"),
    reason="needs a POSIX host with no StableNew cgroup root",
)
def test_a_real_host_without_a_cgroup_runs_the_model_runner_uncapped_and_says_so(tmp_path) -> None:
    marker = tmp_path / "ran"
    outcome = providers.bounded_runner(
        _marker_command(marker),
        timeout_seconds=30,
        max_stdout_bytes=1024,
        cancel=None,
        env=providers.worker_environment(),
    )
    assert outcome.returncode == 0 and marker.exists()
    assert outcome.memory_limit_enforced is False


def test_run_worker_marks_its_result_when_the_child_ran_without_the_cap(tmp_path) -> None:
    import json
    from pathlib import Path

    import numpy as np

    from src.conditioning.reference_map.providers import (
        MEMORY_UNENFORCED_KEY,
        Context,
        run_worker,
        unenforced_warnings,
    )

    def make_runner(enforced):
        def runner(command, *, timeout_seconds, max_stdout_bytes, cancel, env):
            (Path(command[-1]) / "result.json").write_text(json.dumps({"ok": True}))
            return ProcessOutcome(0, memory_limit_enforced=enforced)

        return runner

    rgb = np.zeros((2, 2, 3), np.uint8)
    for enforced, marked in [(False, True), (True, False), (None, False)]:
        job = tmp_path / f"job-{enforced}"
        job.mkdir()
        context = Context(registry=None, cancel=lambda: False, runner=make_runner(enforced))
        document = run_worker(job, "depth", "depth", {}, rgb, context)
        assert (document.get(MEMORY_UNENFORCED_KEY) is True) is marked
        assert bool(unenforced_warnings(document)) is marked


def test_the_warning_reaches_the_operator_in_both_features() -> None:
    from src.conditioning.reference_map.contracts import WARNING_MEMORY_UNENFORCED, warning_text
    from src.review.assist.contracts import CAPABILITY_SEGMENT, ModelIdentity

    text = warning_text(WARNING_MEMORY_UNENFORCED)
    assert text.startswith("WARNING:") and "without one" in text and "Windows enforces" in text
    plain = ModelIdentity(CAPABILITY_SEGMENT, "sam-2-1-small", "local child process, CPU")
    flagged = ModelIdentity(
        CAPABILITY_SEGMENT,
        "sam-2-1-small",
        "local child process, CPU",
        warnings=(WARNING_MEMORY_UNENFORCED,),
    )
    assert "NOT ENFORCED" not in plain.label and "MEMORY LIMIT NOT ENFORCED" in flagged.label


def test_the_smart_review_adapters_carry_the_warning_into_the_model_identity(
    monkeypatch, tmp_path
) -> None:
    import json
    from pathlib import Path

    import numpy as np

    from src.conditioning.reference_map import auxiliary
    from src.conditioning.reference_map.contracts import WARNING_MEMORY_UNENFORCED
    from src.review.assist.contracts import PointPrompt, SourceIdentity
    from src.review.assist.identity import LoadedSource

    monkeypatch.setattr(assist_providers, "runtime_reasons", lambda capability: ())
    monkeypatch.setattr(
        auxiliary,
        "verify_resource",
        lambda registry, modality, cancelled=None: auxiliary.VerifiedResource(modality, ()),
    )
    monkeypatch.setattr(
        auxiliary,
        "stage_resource",
        lambda resource, root, destination, cancelled=None: destination.mkdir(parents=True) or {},
    )

    def runner(command, *, timeout_seconds, max_stdout_bytes, cancel, env):
        job = Path(command[-1])
        (job / "result.json").write_text(json.dumps({"ok": True, "shape": [2, 2], "score": 0.5}))
        (job / "logits.f32").write_bytes(np.ones((2, 2), "<f4").tobytes())
        return ProcessOutcome(0, memory_limit_enforced=False)

    registry = type("Registry", (), {"webui_root": tmp_path})()
    adapter = assist_providers.ChildSegmentAdapter(
        lambda: registry, runner=runner, temp_root=str(tmp_path)
    )
    source = LoadedSource(
        SourceIdentity("0" * 64, 1, 8, 8, 1, "PNG"), np.zeros((8, 8, 3), np.uint8)
    )
    output = adapter.segment(source, [PointPrompt(1, 1, True)], [], lambda: False)
    assert WARNING_MEMORY_UNENFORCED in output.model.warnings
    assert "MEMORY LIMIT NOT ENFORCED" in output.model.label
