"""PR-GUI-STALL-ATTRIBUTION: a lock that names the operation that held it too long.

The queue worker's job claim and the queue projection were logged taking 2-12 s while the repository's single
connection lock was the only shared resource. The lock itself now reports a hold or a wait that long, with the call
site that took it, so the operation that starves everyone else is named in the log instead of inferred.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time

import pytest

from src.utils.contention_lock import ContentionLock, held_locks


@pytest.fixture
def lock_records(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="src.utils.contention_lock")
    return lambda: [r.json_payload for r in caplog.records if hasattr(r, "json_payload")]


def _slow_repository_scan(lock: ContentionLock, seconds: float) -> None:
    with lock:
        time.sleep(seconds)


def test_a_long_hold_is_reported_with_the_site_that_held_it(lock_records) -> None:
    lock = ContentionLock("job_repository", hold_warn_s=0.05, wait_warn_s=10.0)

    _slow_repository_scan(lock, 0.08)

    (record,) = lock_records()
    assert record["lock"] == "job_repository"
    assert record["kind"] == "hold"
    assert record["seconds"] >= 0.05
    assert "_slow_repository_scan" in record["site"]
    assert record["thread"] == threading.current_thread().name


def test_a_short_hold_is_silent(lock_records) -> None:
    lock = ContentionLock("job_repository", hold_warn_s=0.5, wait_warn_s=0.5)

    with lock:
        pass

    assert lock_records() == []


def test_a_reentrant_hold_is_timed_once_at_the_outermost_release(lock_records) -> None:
    lock = ContentionLock("job_repository", hold_warn_s=0.05, wait_warn_s=10.0)

    with lock:
        with lock:
            time.sleep(0.08)
        assert lock_records() == []  # the inner release is not the end of the hold
    assert len(lock_records()) == 1


def test_a_long_wait_is_reported_for_the_waiter_and_names_the_holder(lock_records) -> None:
    lock = ContentionLock("job_repository", hold_warn_s=10.0, wait_warn_s=0.05)
    holding = threading.Event()

    def holder() -> None:
        with lock:
            holding.set()
            time.sleep(0.15)

    thread = threading.Thread(target=holder, name="scan-thread")
    thread.start()
    assert holding.wait(5.0)
    with lock:
        pass
    thread.join(5.0)

    (record,) = lock_records()
    assert record["kind"] == "wait"
    assert record["seconds"] >= 0.05
    assert record["holder_thread"] == "scan-thread"
    assert "holder" in record["holder_site"]


def test_context_manager_frames_are_skipped_when_naming_the_site(lock_records) -> None:
    lock = ContentionLock("job_repository", hold_warn_s=0.02, wait_warn_s=10.0)

    @contextlib.contextmanager
    def transaction():
        with lock:
            yield

    def update_progress() -> None:
        with transaction():
            time.sleep(0.05)

    update_progress()

    (record,) = lock_records()
    assert "update_progress" in record["site"]


def test_non_reentrant_lock_has_the_threading_lock_surface() -> None:
    lock = ContentionLock("job_queue", reentrant=False)

    assert not lock.locked()
    assert lock.acquire()
    assert lock.locked()
    assert lock.acquire(blocking=False) is False
    lock.release()
    assert not lock.locked()


def test_acquire_with_timeout_gives_up_and_reports_false() -> None:
    lock = ContentionLock("job_repository")
    other_has_it = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with lock:
            other_has_it.set()
            release.wait(5.0)

    thread = threading.Thread(target=holder)
    thread.start()
    assert other_has_it.wait(5.0)
    try:
        assert lock.acquire(timeout=0.02) is False
    finally:
        release.set()
        thread.join(5.0)
    assert lock.acquire(timeout=0.5) is True
    lock.release()


def test_logging_never_masks_the_protected_work(
    lock_records, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = ContentionLock("job_repository", hold_warn_s=0.0, wait_warn_s=10.0)

    def exploding(*_a, **_k) -> None:
        raise RuntimeError("log handler failed")

    monkeypatch.setattr("src.utils.contention_lock.log_with_ctx", exploding)

    with lock:
        value = 41 + 1

    assert value == 42
    assert not lock.locked()


def test_a_hold_report_says_how_much_cpu_the_holder_used(lock_records) -> None:
    """A long hold with almost no CPU was waiting (a commit on a busy disk), not computing."""
    lock = ContentionLock("job_repository", hold_warn_s=0.05, wait_warn_s=10.0)

    _slow_repository_scan(lock, 0.2)

    (record,) = lock_records()
    assert record["cpu_s"] < 0.1 <= record["seconds"]


def test_held_locks_names_long_holders_only_while_they_hold() -> None:
    lock = ContentionLock("job_repository_probe")
    held, release = threading.Event(), threading.Event()

    def holder() -> None:
        with lock:
            held.set()
            release.wait(5.0)

    thread = threading.Thread(target=holder, name="progress_poll_probe")
    thread.start()
    try:
        assert held.wait(5.0)
        time.sleep(0.06)
        (entry,) = [e for e in held_locks(0.05) if e["lock"] == "job_repository_probe"]
        assert entry["thread"] == "progress_poll_probe" and entry["held_s"] >= 0.05
        assert "holder" in entry["site"]
        assert not [e for e in held_locks(30.0) if e["lock"] == "job_repository_probe"]
    finally:
        release.set()
        thread.join(5.0)
    assert not [e for e in held_locks(0.0) if e["lock"] == "job_repository_probe"]
