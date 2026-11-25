"""PR-IMG-COMFY-382: the ComfyUI SDXL image path keeps its owned runtime warm between consecutive jobs.

Hermetic: in-memory ComfyUI fakes, an injected warm-hold slot with a fake clock and a recording watcher spawn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.image_backends import image_backend_types as backend_types
from src.image_backends.comfy_image_backend import ComfyImageBackend
from src.services.runtime_transition_service import (
    RuntimeTransitionCoordinator,
    RuntimeTransitionError,
    RuntimeTransitionStatus,
)
from src.services.runtime_warm_hold import RuntimeWarmHold
from tests.helpers.comfy_image_fakes import (
    FakeComfyClient,
    FakeManager,
    FakeTransition,
    Pipeline,
    sdxl_object_info,
)
from tests.image_backends.test_comfy_sdxl_backend_381 import Models, request


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Spawned:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def run_last(self) -> None:
        call = self.calls[-1]
        call["target"](*call["args"])


class Rig:
    """One backend (injected slot, fake owner) so a test can run several jobs and watch the runtime between them."""

    def __init__(self, tmp_path: Path, *, seconds: float = 60.0, transition: Any = None) -> None:
        import random

        self.clock, self.spawned = _Clock(), _Spawned()
        self.slot = RuntimeWarmHold(
            clock=self.clock,
            spawn=self.spawned,
            shutdown_requested=lambda: False,
            add_shutdown_listener=lambda listener: None,
            interpreter_running=lambda: True,
        )
        self.client = FakeComfyClient(info=sdxl_object_info())
        self.manager = FakeManager()
        self.transition = transition or FakeTransition()
        ticks = iter(range(0, 1_000_000))
        jobs = tmp_path / "jobs"
        jobs.mkdir(exist_ok=True)
        from tests.image_backends.test_comfy_sdxl_backend_381 import SDXL_LOOKUP

        self.backend = ComfyImageBackend(
            transition=self.transition,
            process_manager=self.manager,
            client_factory=lambda base_url: self.client,
            clock=lambda: float(next(ticks)),
            sleep=lambda seconds: None,
            rng=random.Random(5),
            temp_root=str(jobs),
            poll_seconds=0,
            family_lookup=SDXL_LOOKUP,
            sdxl_assets=Models(tmp_path).resolver(),
            warm_hold=self.slot,
            keep_warm_seconds=seconds,
        )
        self.tmp_path = tmp_path
        self.count = 0

    def run(self, **changes: Any) -> Any:
        self.count += 1
        changes.setdefault("job_id", f"job-{self.count}")
        changes.setdefault("image_name", f"txt2img_p{self.count:02d}")
        return self.backend.execute(Pipeline(), request(self.tmp_path, **changes))


def test_a_successful_job_holds_the_owned_comfy_instead_of_stopping_it(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    result = rig.run()

    release = result.backend_metadata["runtime_release"]
    assert release["policy"] == "keep_warm_between_jobs" and release["held"] is True
    assert release["released"] is False and release["idle_release_seconds"] == 60
    assert rig.manager.stops == 0 and rig.manager.running is True
    assert rig.slot.snapshot()["pid"] == 4321
    assert "runtime_reuse" not in result.backend_metadata  # nothing was held before this job


def test_the_next_sdxl_job_claims_the_hold_and_reuses_the_running_comfy(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run()
    rig.clock.now += 40

    second = rig.run()

    reuse = second.backend_metadata["runtime_reuse"]
    assert reuse["status"] == "warm" and reuse["pid"] == 4321 and reuse["idle_seconds"] == 40
    assert rig.manager.starts == 1 and rig.manager.stops == 0
    assert (
        second.backend_metadata["runtime_release"]["held"] is True
    )  # held again for the job after it
    assert len(rig.client.payloads) == 2


def test_another_job_preparing_a_runtime_ends_the_hold_through_the_coordinator(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    rig.run()
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None,
        comfy_manager_getter=lambda: None,
        svd_service_factory=lambda: _NoSvd(),
        webui_endpoint_present=lambda: False,
        webui_endpoint_identity=lambda: "none",
        comfy_endpoint_present=lambda: False,
        warm_hold_ender=lambda reason: rig.slot.end(reason=reason),
    )

    coordinator.prepare_for("forge_webui")

    assert rig.manager.stops == 1 and rig.manager.running is False
    assert rig.slot.snapshot() is None
    rig.run()  # the next ComfyUI job is cold again
    assert rig.manager.starts == 2


class _NoSvd:
    def release_cached_state(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


def test_the_idle_grace_elapsing_releases_the_held_comfy(tmp_path: Path) -> None:
    rig = Rig(tmp_path, seconds=90)
    rig.run()

    rig.clock.now += 91
    rig.spawned.run_last()

    assert rig.manager.stops == 1 and rig.manager.running is False
    assert rig.slot.snapshot() is None


def test_a_failed_job_releases_the_comfy_it_claimed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run()
    rig.client.queue_error = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        rig.run()

    assert rig.manager.stops == 1 and rig.manager.running is False
    assert rig.slot.snapshot() is None  # nothing is held after a failure


def test_a_blocked_lease_releases_a_claimed_comfy_and_holds_nothing(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run()
    rig.transition.status = RuntimeTransitionStatus.ACTION_REQUIRED

    with pytest.raises(RuntimeTransitionError):
        rig.run()

    assert rig.manager.stops == 1 and rig.slot.snapshot() is None


def test_a_hold_of_another_workflow_is_released_and_the_job_starts_cold(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    released: list[str] = []
    rig.slot.hold(
        runtime="comfy",
        key=("wan22_i2v_a14b_4step_v1", "1.0.0"),
        pid=4321,
        seconds=120,
        release=lambda: released.append("video") or {"released": True},
    )

    result = rig.run()

    assert released == ["video"]
    assert result.backend_metadata["runtime_reuse"]["status"] == "released"
    assert rig.manager.starts == 1


def test_a_held_process_that_is_no_longer_owned_is_not_reused(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run()
    rig.manager.running = False  # the process died while held

    second = rig.run()

    assert second.backend_metadata["runtime_reuse"]["status"] == "released"
    # Relaunched; the dead process was never "stopped" a second time, and the new one is the one held.
    assert rig.manager.starts == 2 and rig.manager.stops == 0
    assert second.backend_metadata["runtime_release"]["held"] is True


def test_a_zero_grace_keeps_release_after_every_job(tmp_path: Path) -> None:
    rig = Rig(tmp_path, seconds=0)

    result = rig.run()

    assert rig.manager.stops == 1 and result.backend_metadata["runtime_release"]["released"] is True
    assert rig.slot.snapshot() is None


def test_an_unowned_comfy_is_never_held(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.manager.running = False
    rig.manager.healthy = True

    class _External(FakeManager):
        @property
        def owns_process(self) -> bool:  # an external ComfyUI the manager did not launch
            return False

    rig.manager = _External()
    rig.backend._process_manager = rig.manager
    rig.backend._injected_process_manager = rig.manager

    with pytest.raises(Exception, match="launched and owns"):
        rig.run()

    assert rig.slot.snapshot() is None and rig.manager.stops == 0


GIB = 1024**3


def test_a_warm_reused_comfy_is_not_refused_for_the_vram_its_own_model_occupies(
    tmp_path: Path,
) -> None:
    """The physical run 4 failure: the held ComfyUI reports ~4.3 GiB free because it still has the checkpoint loaded."""

    from tests.helpers.comfy_image_fakes import system_stats

    rig = Rig(tmp_path)
    rig.run()
    rig.client.stats = system_stats(vram_free=int(4.3 * GIB))

    second = rig.run()

    assert second.backend_metadata["runtime_reuse"]["status"] == "warm"
    assert len(rig.client.payloads) == 2


def test_a_cold_start_still_refuses_when_another_program_holds_the_gpu(tmp_path: Path) -> None:
    from src.image_backends.comfy_image_readiness import ComfyImageResourceError
    from tests.helpers.comfy_image_fakes import system_stats

    rig = Rig(tmp_path)
    rig.client.stats = system_stats(vram_free=int(4.3 * GIB))

    with pytest.raises(ComfyImageResourceError, match="free GPU memory"):
        rig.run()

    assert rig.client.payloads == []


def test_a_warm_reused_comfy_still_needs_host_ram(tmp_path: Path) -> None:
    from src.image_backends.comfy_image_readiness import ComfyImageResourceError
    from tests.helpers.comfy_image_fakes import system_stats

    rig = Rig(tmp_path)
    rig.run()
    rig.client.stats = system_stats(vram_free=int(4.3 * GIB), ram_free=1 * GIB)

    with pytest.raises(ComfyImageResourceError, match="free host RAM"):
        rig.run()


# -- the configured idle grace -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 60.0),
        ("", 60.0),
        (0, 0.0),
        (-5, 0.0),
        ("abc", 0.0),
        (True, 0.0),
        (float("nan"), 0.0),
        (45, 45.0),
        ("300", 300.0),
        (999999, 3600.0),
    ],
)
def test_the_idle_grace_setting_is_normalised_and_bounded(value: Any, expected: float) -> None:
    assert backend_types.normalize_comfy_image_keep_warm_seconds(value) == expected


def test_unreadable_settings_mean_no_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api import webui_runtime_identity as identity

    def unreadable(*args: Any, **kwargs: Any) -> Any:
        raise identity.WebUIRuntimeConfigurationError("unreadable")

    monkeypatch.setattr(identity, "load_backend_settings", unreadable)

    assert backend_types.configured_comfy_image_keep_warm_seconds() == 0.0


def test_the_configured_setting_is_used_when_no_override_is_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path)
    rig.backend._keep_warm_seconds = None
    monkeypatch.setattr(
        "src.image_backends.comfy_image_backend.configured_comfy_image_keep_warm_seconds",
        lambda: 75.0,
    )

    result = rig.run()

    assert result.backend_metadata["runtime_release"]["idle_release_seconds"] == 75.0
