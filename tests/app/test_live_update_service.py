"""LAUNCH-UPDATE-1: the update service (switch, rate limit, drain, hand-off, receipt) with fakes only.

No Git, no process and no Tk: the preflight, the queue hold, the busy probe and the updater launch are injected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.app import live_update as lu
from src.app.live_update_service import LiveUpdateService

OLD = "a" * 40
NEW = "b" * 40


class FakeQueue:
    def __init__(self) -> None:
        self.held = False
        self.events: list[str] = []

    def hold_dispatch_for_update(self, *, reason: str) -> bool:
        self.events.append(f"hold:{reason}")
        applied = not self.held
        self.held = True
        return applied

    def release_update_hold(self) -> bool:
        self.events.append("release")
        released = self.held
        self.held = False
        return released


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def ok_preflight(expected_sha):
    return lu.Preflight(True, "", OLD, expected_sha or NEW, commits_ahead=3)


@pytest.fixture
def parts(tmp_path: Path):
    clock = Clock()
    queue = FakeQueue()
    launched: list[lu.UpdaterLaunch] = []
    busy = {"value": False}
    store = lu.LiveUpdateStore(tmp_path / "state")

    def make(preflight=ok_preflight, launch=None, max_wait=3600.0):
        return LiveUpdateService(
            store=store,
            preflight=preflight,
            queue=queue,
            busy=lambda: busy["value"],
            launch_updater=launch or launched.append,
            repo_root=tmp_path / "repo",
            pid=4242,
            clock=clock,
            sleep=clock.sleep,
            max_wait_seconds=max_wait,
            poll_seconds=5.0,
        )

    return make, store, queue, launched, busy, clock


def test_remote_update_is_refused_while_the_switch_is_off(parts):
    make, store, queue, launched, _busy, _clock = parts
    service = make()

    assert service.allow_remote() is False  # off by default
    outcome = service.update(source="remote", expected_sha=NEW, record_id="r1")

    assert (outcome.status, outcome.reason) == ("refused", lu.REMOTE_UPDATE_DISABLED)
    assert launched == [] and queue.events == []
    assert store.read("last_result.json")["reason"] == lu.REMOTE_UPDATE_DISABLED
    assert store.read("last_result.json")["record_id"] == "r1"


def test_desktop_update_does_not_need_the_remote_switch(parts):
    make, _store, _queue, launched, _busy, _clock = parts

    assert make().update(source="desktop", expected_sha=None).status == "restarting"
    assert len(launched) == 1


def test_switch_persists(parts):
    make, _store, _q, _l, _b, _c = parts
    make().set_allow_remote(True)

    assert make().allow_remote() is True


def test_a_preflight_refusal_changes_nothing(parts):
    make, store, queue, launched, _busy, _clock = parts
    service = make(preflight=lambda sha: lu.Preflight(False, lu.DIRTY_CHECKOUT, OLD, ""))
    service.set_allow_remote(True)

    outcome = service.update(source="remote", expected_sha=NEW, record_id="r1")

    assert (outcome.status, outcome.reason) == ("refused", lu.DIRTY_CHECKOUT)
    assert queue.events == [] and launched == [] and store.read("intent.json") is None
    assert not service.exit_requested


def test_already_current_is_reported_without_a_restart(parts):
    make, _store, queue, launched, _busy, _clock = parts
    service = make(preflight=lambda sha: lu.Preflight(False, lu.ALREADY_CURRENT, OLD, OLD))

    outcome = service.update(source="desktop", expected_sha=None)

    assert outcome.status == "already_current" and launched == [] and queue.events == []


def test_success_holds_dispatch_waits_for_the_running_job_writes_intent_and_requests_exit(parts):
    make, store, queue, launched, busy, clock = parts
    service = make()
    service.set_allow_remote(True)
    busy["value"] = True
    polls = {"n": 0}

    def finish_after_three_polls(seconds):
        clock.now += seconds
        polls["n"] += 1
        if polls["n"] == 3:
            busy["value"] = False

    service._sleep = finish_after_three_polls

    outcome = service.update(source="remote", expected_sha=NEW, record_id="r1")

    assert outcome.status == "restarting" and outcome.target_sha == NEW
    assert queue.events == ["hold:live-update"] and queue.held  # kept until the process exits
    intent = store.read("intent.json")
    assert intent["old_sha"] == OLD and intent["target_sha"] == NEW and intent["record_id"] == "r1"
    assert intent["pid"] == 4242 and intent["source"] == "remote"
    assert launched == [lu.UpdaterLaunch(service.repo_root, store.directory, 4242, OLD, NEW)]
    assert service.exit_requested
    assert service.in_progress


def test_busy_timeout_releases_the_hold_and_refuses(parts):
    make, store, queue, launched, busy, _clock = parts
    service = make(max_wait=60.0)
    busy["value"] = True

    outcome = service.update(source="desktop", expected_sha=None)

    assert (outcome.status, outcome.reason) == ("refused", lu.BUSY_TIMEOUT)
    assert queue.events == ["hold:live-update", "release"] and not queue.held
    assert launched == [] and store.read("intent.json") is None and not service.in_progress


def test_a_failed_updater_launch_releases_the_hold_and_clears_the_intent(parts):
    make, store, queue, _launched, _busy, _clock = parts

    def broken(_launch):
        raise OSError("no powershell")

    outcome = make(launch=broken).update(source="desktop", expected_sha=None)

    assert (outcome.status, outcome.reason) == ("refused", lu.UPDATER_FAILED)
    assert not queue.held and store.read("intent.json") is None


def test_only_one_update_at_a_time(parts):
    make, _store, _queue, launched, _busy, _clock = parts
    service = make()
    assert service.update(source="desktop", expected_sha=None).status == "restarting"

    again = service.update(source="desktop", expected_sha=None)

    assert again.reason == lu.UPDATE_IN_PROGRESS and len(launched) == 1


def test_a_pending_intent_from_a_previous_process_blocks_a_new_update(parts):
    make, store, _queue, launched, _busy, _clock = parts
    store.write("intent.json", {"update_id": "x", "old_sha": OLD, "target_sha": NEW})

    assert make().update(source="desktop", expected_sha=None).reason == lu.UPDATE_IN_PROGRESS
    assert launched == []


def test_remote_updates_are_rate_limited(parts):
    make, store, _queue, launched, _busy, clock = parts
    first = make()
    first.set_allow_remote(True)
    assert first.update(source="remote", expected_sha=NEW, record_id="r1").status == "restarting"
    # The restart happened and the new process collected its receipt.
    store.write("result.json", {**store.read("intent.json"), "status": "applied", "new_sha": NEW})
    second = make()
    second.collect_result()
    clock.now += 60

    assert (
        second.update(source="remote", expected_sha=NEW, record_id="r2").reason == lu.RATE_LIMITED
    )
    clock.now += 600
    assert second.update(source="remote", expected_sha=NEW, record_id="r3").status == "restarting"
    assert len(launched) == 2


def test_started_marker_is_written_only_while_an_update_is_pending(parts):
    make, store, _queue, _launched, _busy, _clock = parts
    service = make()
    service.mark_started(NEW)
    assert store.read("started.json") is None

    store.write("intent.json", {"update_id": "u1", "old_sha": OLD, "target_sha": NEW})
    service.mark_started(NEW)

    marker = store.read("started.json")
    assert marker["update_id"] == "u1" and marker["head_sha"] == NEW and marker["pid"] == 4242


def test_collect_result_turns_the_updater_result_into_the_receipt(parts):
    make, store, _queue, _launched, _busy, _clock = parts
    intent = {
        "update_id": "u1",
        "record_id": "r1",
        "source": "remote",
        "old_sha": OLD,
        "target_sha": NEW,
    }
    store.write("intent.json", intent)
    store.write("started.json", {"update_id": "u1"})
    assert make().collect_result() is None  # the updater has not written its result yet

    store.write("result.json", {**intent, "status": "applied", "new_sha": NEW, "finished_at": "t"})
    receipt = make().collect_result()

    assert (
        receipt["status"] == "applied" and receipt["old_sha"] == OLD and receipt["new_sha"] == NEW
    )
    assert receipt["record_id"] == "r1"
    assert store.read("last_result.json") == receipt
    for name in ("intent.json", "started.json", "result.json"):
        assert store.read(name) is None
    assert make().collect_result() is None


def test_collect_result_ignores_a_result_for_another_update(parts):
    make, store, _queue, _launched, _busy, _clock = parts
    store.write("intent.json", {"update_id": "u2", "old_sha": OLD, "target_sha": NEW})
    store.write("result.json", {"update_id": "u1", "status": "applied"})

    assert make().collect_result() is None
    assert store.read("intent.json") is not None


def test_check_is_read_only(parts):
    make, store, queue, launched, _busy, _clock = parts

    result = make().check()

    assert result.ok and result.commits_ahead == 3
    assert queue.events == [] and launched == [] and store.read("intent.json") is None


def test_without_a_queue_that_can_hold_dispatch_every_update_is_refused(tmp_path):
    launched = []
    service = LiveUpdateService(
        store=lu.LiveUpdateStore(tmp_path / "state"),
        preflight=ok_preflight,
        queue=None,
        busy=lambda: False,
        launch_updater=launched.append,
        repo_root=tmp_path,
        pid=1,
    )

    assert service.update(source="desktop", expected_sha=None).reason == lu.QUEUE_UNAVAILABLE
    assert launched == []


def test_updater_command_refuses_a_malformed_sha_and_passes_fixed_arguments(tmp_path):
    good = lu.UpdaterLaunch(tmp_path / "repo", tmp_path / "state", 7, OLD, NEW)

    argv = lu.updater_command(good, powershell="powershell.exe", script=tmp_path / "u.ps1")

    assert argv[:9] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(tmp_path / "u.ps1"),
    ]
    assert argv[argv.index("-OldSha") + 1] == OLD and argv[argv.index("-TargetSha") + 1] == NEW
    assert argv[argv.index("-OldPid") + 1] == "7"
    with pytest.raises(ValueError):
        lu.updater_command(
            lu.UpdaterLaunch(tmp_path, tmp_path, 7, OLD, "main"),
            powershell="p",
            script=tmp_path / "u.ps1",
        )


def test_a_remote_request_must_name_the_commit_it_was_shown(parts):
    make, _store, queue, launched, _busy, _clock = parts
    service = make()
    service.set_allow_remote(True)

    outcome = service.update(source="remote", expected_sha=None, record_id="r1")

    assert outcome.reason == lu.INVALID_REQUEST and launched == [] and queue.events == []


def test_an_intent_the_updater_never_answered_is_abandoned_after_30_minutes(parts):
    make, store, _queue, launched, _busy, clock = parts
    store.write(
        "intent.json",
        {"update_id": "u1", "old_sha": OLD, "target_sha": NEW, "restart_at": clock.now},
    )
    clock.now += 600
    assert make().collect_result() is None  # the updater may still be waiting for health

    clock.now += 1800
    receipt = make().collect_result()

    assert receipt["status"] == "refused" and receipt["reason"] == lu.UPDATER_LOST
    assert store.read("intent.json") is None
    assert make().update(source="desktop", expected_sha=None).status == "restarting"
    assert len(launched) == 1
