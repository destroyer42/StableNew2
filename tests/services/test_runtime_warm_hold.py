"""VID-WARM-373: the single idle warm-hold slot for a StableNew-owned runtime.

Deterministic: an injected clock and a spawn that records the watcher instead of starting a thread.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from src.services.runtime_warm_hold import (
    CLAIM_NONE,
    CLAIM_RELEASED,
    CLAIM_WARM,
    RuntimeWarmHold,
)

KEY = ("wan22_i2v_a14b_4step_v1", "1.0.0")


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


class _Releases:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> dict[str, Any]:
        self.count += 1
        return {"released": True, "pid": 4101}


def _slot(**overrides: Any) -> tuple[RuntimeWarmHold, _Clock, _Spawned, list[Any]]:
    clock, spawned, listeners = _Clock(), _Spawned(), []
    kwargs: dict[str, Any] = {
        "clock": clock,
        "spawn": spawned,
        "shutdown_requested": lambda: False,
        "add_shutdown_listener": listeners.append,
        "interpreter_running": lambda: True,
    }
    kwargs.update(overrides)
    return RuntimeWarmHold(**kwargs), clock, spawned, listeners


def test_the_same_workflow_on_the_same_owned_process_claims_the_hold_warm() -> None:
    slot, clock, spawned, _ = _slot()
    release = _Releases()

    record = slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)
    clock.now += 30
    claim = slot.claim(runtime="comfy", key=KEY, current_pid=lambda: 4101)

    assert record["held"] is True and record["idle_release_seconds"] == 120
    assert spawned.calls[0]["name"] == "RuntimeWarmHold-comfy"
    assert claim.status == CLAIM_WARM and claim.warm and claim.idle_seconds == 30
    assert release.count == 0
    assert slot.snapshot() is None  # the claim consumed the slot


def test_a_different_workflow_releases_the_held_runtime_before_it_starts() -> None:
    slot, _, _, _ = _slot()
    release = _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)

    claim = slot.claim(
        runtime="comfy", key=("wan22_ti2v_5b_i2v_v1", "1.3.0"), current_pid=lambda: 4101
    )

    assert claim.status == CLAIM_RELEASED and not claim.warm
    assert release.count == 1
    assert claim.release is not None and claim.release["warm_hold_end"] == "claimed_by_another_job"


def test_a_restarted_or_stopped_process_is_never_treated_as_warm() -> None:
    slot, _, _, _ = _slot()
    release = _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)

    claim = slot.claim(runtime="comfy", key=KEY, current_pid=lambda: None)

    assert claim.status == CLAIM_RELEASED and release.count == 1


def test_an_unreadable_owner_is_not_warm() -> None:
    slot, _, _, _ = _slot()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=_Releases())

    def broken() -> int:
        raise RuntimeError("manager unreadable")

    assert slot.claim(runtime="comfy", key=KEY, current_pid=broken).status == CLAIM_RELEASED


def test_an_empty_slot_claims_nothing() -> None:
    slot, _, _, _ = _slot()

    assert slot.claim(runtime="comfy", key=KEY, current_pid=lambda: 4101).status == CLAIM_NONE
    assert slot.end(reason="runtime transition") is None


def test_the_idle_grace_releases_the_hold_once() -> None:
    slot, clock, spawned, _ = _slot()
    release = _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)

    clock.now += 121
    spawned.run_last()  # the watcher finds the deadline passed and releases

    assert release.count == 1
    assert slot.snapshot() is None
    assert slot.claim(runtime="comfy", key=KEY, current_pid=lambda: 4101).status == CLAIM_NONE


def test_a_claimed_hold_is_not_released_by_its_watcher() -> None:
    slot, clock, spawned, _ = _slot()
    release = _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)
    slot.claim(runtime="comfy", key=KEY, current_pid=lambda: 4101)

    clock.now += 500
    spawned.run_last()

    assert release.count == 0


def test_a_stale_watcher_never_releases_a_newer_hold() -> None:
    slot, clock, spawned, _ = _slot()
    first, second = _Releases(), _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=first)
    slot.claim(runtime="comfy", key=KEY, current_pid=lambda: 4101)
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=second)

    clock.now += 500
    spawned.calls[0]["target"](*spawned.calls[0]["args"])

    assert first.count == 0 and second.count == 0
    assert slot.snapshot() is not None


def test_another_runtime_being_prepared_ends_the_hold_through_its_release() -> None:
    slot, _, _, _ = _slot()
    release = _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)

    outcome = slot.end(reason="runtime transition to forge_webui")

    assert release.count == 1
    assert outcome is not None and outcome["warm_hold_end"] == "runtime transition to forge_webui"


def test_a_failing_release_is_reported_not_raised() -> None:
    slot, _, _, _ = _slot()

    def boom() -> dict[str, Any]:
        raise OSError("stop failed")

    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=boom)

    outcome = slot.end(reason="test")

    assert outcome is not None and outcome["released"] is False and "OSError" in outcome["error"]


def test_shutdown_cancels_the_watcher_without_releasing() -> None:
    slot, clock, spawned, listeners = _slot()
    release = _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)

    listeners[0]()  # ThreadRegistry.shutdown_all runs its listeners
    clock.now += 500
    spawned.run_last()

    assert release.count == 0
    assert (
        slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=release)["held"] is False
    )


def test_the_watcher_stops_when_the_interpreter_shuts_down() -> None:
    running = [True]
    slot, _, spawned, _ = _slot(interpreter_running=lambda: running[0])
    release = _Releases()
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=3600, release=release)
    running[0] = False

    worker = threading.Thread(target=spawned.run_last)
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert release.count == 0


def test_nothing_is_held_when_shutdown_was_already_requested() -> None:
    slot, _, spawned, _ = _slot(shutdown_requested=lambda: True)

    record = slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=_Releases())

    assert record == {"held": False, "reason": "shutdown_requested"}
    assert spawned.calls == []


def test_nothing_is_held_when_the_watcher_cannot_start() -> None:
    def no_threads(**_kwargs: Any) -> None:
        raise RuntimeError("no threads")

    slot, _, _, _ = _slot(spawn=no_threads)

    record = slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=120, release=_Releases())

    assert record["held"] is False and "no threads" in record["reason"]
    assert slot.snapshot() is None


def test_a_hold_needs_a_positive_grace() -> None:
    slot, _, _, _ = _slot()

    with pytest.raises(ValueError):
        slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=0, release=_Releases())


def test_a_real_watcher_thread_releases_after_a_short_grace() -> None:
    released = threading.Event()

    def release() -> dict[str, Any]:
        released.set()
        return {"released": True}

    def spawn(**kwargs: Any) -> threading.Thread:
        thread = threading.Thread(target=kwargs["target"], args=kwargs["args"], name=kwargs["name"])
        thread.start()
        return thread

    slot = RuntimeWarmHold(
        spawn=spawn,
        shutdown_requested=lambda: False,
        add_shutdown_listener=lambda _listener: None,
    )
    slot.hold(runtime="comfy", key=KEY, pid=4101, seconds=0.05, release=release)

    assert released.wait(timeout=5)
