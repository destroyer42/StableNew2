"""PR-GUI-STALL-ATTRIBUTION: a stalled Tk thread is attributed to the call site that is blocking it.

``SystemWatchdogV2`` already notices a heartbeat that stops, but the only evidence it kept was a diagnostics ZIP at
``UI_STALL_S`` behind a cooldown, so stalls shorter than that (or inside the cooldown) left nothing to act on. Every
stall episode is now reduced to one structured log record that names the Tk-thread call sites sampled while it lasted.

Nothing here waits on real time: the heartbeat age is injected and the "Tk thread" is a helper thread parked in a
known function.
"""

from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import pytest

from src.services import watchdog_system_v2
from src.services.watchdog_system_v2 import SystemWatchdogV2
from src.utils.contention_lock import ContentionLock


def _app(*, ui_age_s: float) -> SimpleNamespace:
    return SimpleNamespace(
        last_ui_heartbeat_ts=time.monotonic() - ui_age_s,
        last_queue_activity_ts=time.monotonic(),
        last_runner_activity_ts=time.monotonic(),
        current_operation_label="Refreshing preview from state",
        last_ui_action="_refresh_preview_from_state_async()",
        get_queue_state=lambda: {"queued": 0, "running": 0},
        has_running_jobs=lambda: False,
        _is_shutting_down=False,
    )


class _ParkedThread:
    """A thread blocked inside a recognisable function, standing in for a Tk thread stuck in a callback."""

    def __init__(self) -> None:
        self._release = threading.Event()
        self._parked = threading.Event()
        self.thread = threading.Thread(target=self._outer_callback, name="fake-tk-thread")
        self.thread.start()
        assert self._parked.wait(5.0)

    def _outer_callback(self) -> None:
        self._count_everything_on_disk()

    def _count_everything_on_disk(self) -> None:
        self._parked.set()
        self._release.wait(10.0)

    @property
    def ident(self) -> int:
        assert self.thread.ident is not None
        return self.thread.ident

    def release(self) -> None:
        self._release.set()
        self.thread.join(5.0)


@pytest.fixture
def parked():
    thread = _ParkedThread()
    try:
        yield thread
    finally:
        thread.release()


@pytest.fixture
def stall_records(caplog: pytest.LogCaptureFixture):
    """Callable returning the stall records logged so far (``caplog.records`` is replaced per test phase)."""

    caplog.set_level(logging.WARNING, logger="src.services.watchdog_system_v2")
    return lambda: [r for r in caplog.records if "UI thread stalled" in r.getMessage()]


def test_stalled_thread_is_attributed_to_the_function_it_is_blocked_in(
    parked, stall_records
) -> None:
    app = _app(ui_age_s=3.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)

    watchdog._check()
    app.last_ui_heartbeat_ts = time.monotonic()  # the Tk loop is serviced again
    watchdog._check()

    records = stall_records()
    assert len(records) == 1
    payload = records[0].json_payload
    assert payload["stage"] == "ui_stall"
    assert payload["stall_s"] >= 3.0
    assert payload["operation"] == "Refreshing preview from state"
    hot = payload["stacks"][0]
    assert any("_count_everything_on_disk" in frame for frame in hot["stack"])
    assert any("_outer_callback" in frame for frame in hot["stack"])
    assert hot["innermost"] == hot["stack"][0]
    assert hot["samples"] == 1


def test_repeated_samples_of_one_call_site_are_counted_not_repeated(parked, stall_records) -> None:
    app = _app(ui_age_s=2.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)

    for age in (2.0, 2.5, 3.0, 3.5):
        app.last_ui_heartbeat_ts = time.monotonic() - age
        watchdog._check()
    app.last_ui_heartbeat_ts = time.monotonic()
    watchdog._check()

    (record,) = stall_records()
    stacks = record.json_payload["stacks"]
    assert len(stacks) == 1
    assert stacks[0]["samples"] == 4
    assert record.json_payload["stall_s"] >= 3.5


def test_a_short_gap_is_not_reported(parked, stall_records) -> None:
    app = _app(ui_age_s=0.3)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)

    watchdog._check()
    app.last_ui_heartbeat_ts = time.monotonic()
    watchdog._check()

    assert stall_records() == []


def test_each_stall_episode_is_reported_once_when_it_ends(parked, stall_records) -> None:
    app = _app(ui_age_s=2.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)

    watchdog._check()
    assert stall_records() == []  # still stalled: nothing yet
    app.last_ui_heartbeat_ts = time.monotonic()
    watchdog._check()
    app.last_ui_heartbeat_ts = time.monotonic() - 2.0
    watchdog._check()
    app.last_ui_heartbeat_ts = time.monotonic()
    watchdog._check()

    assert len(stall_records()) == 2


def test_the_diagnostics_bundle_context_carries_the_blocked_stack(parked) -> None:
    calls: list[dict] = []

    class _Diagnostics:
        def build_async(self, *, reason: str, context: dict, on_done=None, **_kw) -> None:
            calls.append({"reason": reason, "context": context})
            if on_done is not None:
                on_done()

    app = _app(ui_age_s=SystemWatchdogV2.UI_STALL_S + 5.0)
    watchdog = SystemWatchdogV2(app, _Diagnostics(), ui_thread_ident=parked.ident)

    watchdog._check()

    (call,) = [c for c in calls if c["reason"] == "ui_heartbeat_stall"]
    assert "_count_everything_on_disk" in call["context"]["main_thread_stack"]


def test_a_missing_ui_thread_does_not_break_the_watchdog(stall_records) -> None:
    app = _app(ui_age_s=4.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=2**31 - 1)

    watchdog._check()
    app.last_ui_heartbeat_ts = time.monotonic()
    watchdog._check()

    (record,) = stall_records()
    assert record.json_payload["stacks"] == []


def test_a_starved_watchdog_thread_is_reported_with_every_threads_current_site(
    parked, caplog
) -> None:
    """A GIL-holding call (or a suspended process) delays the watchdog thread as well as Tk: say so."""

    caplog.set_level(logging.WARNING, logger="src.services.watchdog_system_v2")
    app = _app(ui_age_s=0.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)

    assert watchdog._note_loop_gap(0.5) is False  # on time: nothing to say
    assert watchdog._note_loop_gap(0.5 + 0.2) is False  # small jitter
    assert watchdog._note_loop_gap(0.5 + 6.0) is True

    (record,) = [r for r in caplog.records if "Watchdog thread starved" in r.getMessage()]
    payload = record.json_payload
    assert payload["stage"] == "watchdog_starved"
    assert payload["late_by_s"] >= 6.0
    sites = payload["thread_sites"]
    assert sites[parked.thread.name].count("in ") >= 1
    assert "ui_heartbeat_age_s" in payload
    assert isinstance(payload["system"], dict)


def _stall_once(watchdog: SystemWatchdogV2, app: SimpleNamespace) -> None:
    watchdog._check()
    watchdog._check()
    app.last_ui_heartbeat_ts = time.monotonic()
    watchdog._check()


def test_a_stall_records_how_much_cpu_the_tk_thread_and_the_process_used(
    parked, stall_records
) -> None:
    """Near-zero Tk CPU means it was waiting (GIL, modal loop, pause); high means it was working in Tcl."""

    app = _app(ui_age_s=3.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)
    readings = iter([(1.0, 10.0), (1.1, 14.5)])
    watchdog._cpu_times = lambda: next(readings)

    _stall_once(watchdog, app)

    (record,) = stall_records()
    assert record.json_payload["tk_cpu_s"] == pytest.approx(0.1)
    assert record.json_payload["process_cpu_s"] == pytest.approx(4.5)
    assert record.json_payload["observed_s"] >= 0.0


def test_cpu_times_reads_the_watched_thread_and_the_process() -> None:
    watchdog = SystemWatchdogV2(_app(ui_age_s=0.0), None, ui_thread_ident=threading.get_ident())

    reading = watchdog._cpu_times()

    assert reading is not None
    tk_cpu, process_cpu = reading
    assert 0.0 <= tk_cpu <= process_cpu + 1.0


def test_a_mainloop_only_sample_also_records_what_the_other_threads_were_doing(
    parked, stall_records, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no Python frame on the Tk thread, a GIL holder shows up only on another thread.

    Only the sampling thread and the Tk thread are left out, by identity. Whatever else is alive is listed, including
    threads other tests (or another watchdog) left running, so this asserts on its own two threads only.
    """

    app = _app(ui_age_s=3.0)
    # However many threads this test process has accumulated, none is cut from the list.
    monkeypatch.setattr(watchdog_system_v2, "_OTHER_THREADS", 10_000)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=-1)
    watchdog._capture_ui_stack = lambda: ("__init__.py:1625 in mainloop", "src/main.py:757 in main")
    release = threading.Event()
    # Unrelated threads, as a shared test process (or the app) has: one even carries the watchdog's own thread name.
    bystanders = [
        threading.Thread(target=release.wait, args=(10.0,), name=name)
        for name in ("SystemWatchdogV2", *(f"bystander-{index}" for index in range(10)))
    ]
    for thread in bystanders:
        thread.start()
    sampler = threading.Thread(target=_stall_once, args=(watchdog, app), name="own-sampler")
    try:
        sampler.start()
        sampler.join(10.0)
    finally:
        release.set()
        for thread in bystanders:
            thread.join(5.0)

    (record,) = stall_records()
    listed = {item["site"].split(":", 1)[0]: item for item in record.json_payload["other_threads"]}
    assert "own-sampler" not in listed
    assert "_count_everything_on_disk" in listed["fake-tk-thread"]["site"]
    assert listed["fake-tk-thread"]["samples"] == 2


def test_an_attributed_stall_does_not_list_other_threads(parked, stall_records) -> None:
    app = _app(ui_age_s=3.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)

    _stall_once(watchdog, app)

    (record,) = stall_records()
    assert record.json_payload["other_threads"] == []


def test_a_late_thread_is_not_cut_from_the_list_of_a_process_with_many_threads(
    stall_records,
) -> None:
    """Every waiting thread counts as often as a GIL holder, so a short list would drop it by start order."""

    app = _app(ui_age_s=3.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=-1)
    watchdog._capture_ui_stack = lambda: ("__init__.py:1625 in mainloop", "src/main.py:757 in main")
    sites = [f"idle-{index}: wait" for index in range(24)] + ["late-worker: busy"]
    watchdog._other_thread_sites = lambda: list(sites)

    _stall_once(watchdog, app)

    (record,) = stall_records()
    assert "late-worker: busy" in [item["site"] for item in record.json_payload["other_threads"]]


def test_a_stall_records_long_lock_holds_and_the_io_done_while_it_lasted(
    parked, stall_records
) -> None:
    """STARTUP-STALL-2: two completion stalls coincided with a 4.5 s commit and showed only ``mainloop``."""
    app = _app(ui_age_s=3.0)
    watchdog = SystemWatchdogV2(app, None, ui_thread_ident=parked.ident)
    readings = iter([(100.0, 900.0, 5.0), (164.0, 5400.0, 7.5)])
    watchdog._io_counters = lambda: next(readings)
    lock = ContentionLock("job_repository", hold_warn_s=30.0)
    held, release = threading.Event(), threading.Event()

    def commit_progress() -> None:
        with lock:
            held.set()
            release.wait(5.0)

    holder = threading.Thread(target=commit_progress, name="progress_poll_0")
    holder.start()
    try:
        assert held.wait(5.0)
        time.sleep(0.6)
        watchdog._check()
    finally:
        release.set()
        holder.join(5.0)
    app.last_ui_heartbeat_ts = time.monotonic()
    watchdog._check()

    (record,) = stall_records()
    payload = record.json_payload
    (hold,) = [h for h in payload["held_locks"] if h["lock"] == "job_repository"]
    assert hold["thread"] == "progress_poll_0" and "commit_progress" in hold["site"]
    assert payload["io"] == {
        "disk_write_mb": 64.0,
        "disk_write_ms": 4500.0,
        "process_write_mb": 2.5,
    }


def test_io_counters_can_be_read_on_this_machine() -> None:
    watchdog = SystemWatchdogV2(_app(ui_age_s=0.0), None)

    reading = watchdog._io_counters()

    assert reading is None or len(reading) == 3
