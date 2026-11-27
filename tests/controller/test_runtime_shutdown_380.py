"""Shutdown acceptance with fake work, real threads and temporary SQLite."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from src.controller.app_controller_services import shutdown_coordinator as shutdown
from src.gui.history_browser_panel_v2 import HistoryBrowserPanelV2
from src.queue.history_query import HistoryQuery
from src.queue.job_model import JobStatus
from src.services.persistence_worker import PersistenceTask, PersistenceWorker
from src.services.runtime_warm_hold import RuntimeWarmHold
from tests.controller.test_shutdown_quiescence_140 import Harness, _start_active_job


def test_idle_shutdown_releases_only_the_owned_comfy_and_stops_its_warm_watcher(
    tmp_path, monkeypatch, caplog
):
    built = Harness(tmp_path, job_ids=())
    events = built.repository.events
    registry = built.controller._thread_registry
    warm_hold = RuntimeWarmHold()
    built.controller.webui_process_manager = None
    manager = SimpleNamespace(
        owns_process=True, is_running=lambda: False, stop=lambda **_: events.append("comfy.stop")
    )
    monkeypatch.setattr(shutdown, "get_global_comfy_process_manager", lambda: manager)
    warm_hold.hold(
        runtime="comfy",
        key=("synthetic", "1"),
        pid=12345,
        seconds=100,
        release=lambda: pytest.fail("the exit coordinator owns this release"),
    )
    watchers = [
        item.thread
        for item in registry.get_active_threads()
        if item.name == "RuntimeWarmHold-comfy"
    ]
    assert len(watchers) == 1
    try:
        start = time.monotonic()
        built.controller.shutdown_app("idle-380")
        built.controller.shutdown_app("repeated-380")
        elapsed = time.monotonic() - start
        outcome = built.controller._shutdown_outcome
        assert outcome.completed and elapsed < 2
        assert outcome.comfy == "released" and outcome.repository == "closed"
        assert not watchers[0].is_alive()
        assert events.count("comfy.stop") == events.count("repository.close") == 1
        assert "Watchdog deadline" not in caplog.text
    finally:
        built.cleanup()


def test_unowned_comfy_is_never_stopped(monkeypatch):
    external = SimpleNamespace(owns_process=False, stop=lambda **_: pytest.fail("external stop"))
    monkeypatch.setattr(shutdown, "get_global_comfy_process_manager", lambda: external)
    assert shutdown.release_owned_comfy(1.0) == "unowned_or_absent"


def test_owned_comfy_failed_stop_is_reported(monkeypatch):
    owned = SimpleNamespace(owns_process=True, stop=lambda **_: False, is_running=lambda: True)
    monkeypatch.setattr(shutdown, "get_global_comfy_process_manager", lambda: owned)
    assert shutdown.release_owned_comfy(1.0) == "failed"


def test_queue_and_blocked_history_share_deadline_and_keep_resources_open(
    tmp_path, monkeypatch, caplog
):
    built = Harness(tmp_path, ignore_cancel=True)
    controller = built.controller
    tasks = controller._background_tasks
    tasks._run_inline = False
    started = threading.Event()
    release_history = threading.Event()
    delivered = []
    history_reads = []

    def blocked_recent_read(**_):
        history_reads.append("read")
        with built.repository._lock:
            started.set()
            assert release_history.wait(10)
        return []

    monkeypatch.setattr(built.repository, "list_recent_jobs", blocked_recent_read)
    monkeypatch.setattr(
        controller._runtime_projection_coordinator._sink,
        "apply_history_projection",
        delivered.append,
    )
    monkeypatch.setattr(shutdown, "SHUTDOWN_BUDGET_SECONDS", 0.2)
    monkeypatch.setattr(shutdown, "QUEUE_QUIESCE_TIMEOUT_SECONDS", 0.1)
    try:
        _start_active_job(built)
        projection = controller._runtime_projection_coordinator
        projection.publish_history_refresh()
        assert started.wait(2)
        projection.publish_history_refresh()  # superseding yet pending
        with caplog.at_level(logging.WARNING):
            controller.shutdown_app("fake-stalled-380")

        outcome = controller._shutdown_outcome
        assert not outcome.completed and outcome.deadline_expired
        assert not outcome.queue_quiescent and not outcome.background_quiescent
        assert outcome.repository == "left_open" and outcome.comfy == "deferred"
        assert 0.17 <= outcome.elapsed_seconds < 5  # the blocked read alone would take 10 s
        assert "HistoryProjectionRefresh" in outcome.remaining_workers
        assert any(name.startswith("QueueWorker") for name in outcome.remaining_workers)
        assert outcome.cancellation_requested
        assert "phase=queue_deadline" in caplog.text
        assert "blocked_recent_read" in caplog.text
        assert "result=INCOMPLETE_TIMEOUT" in caplog.text
        assert built.repository.close_calls == 0 and not built.started["B"].is_set()
    finally:
        workers = controller._thread_registry.get_active_threads()
        release_history.set()
        for item in workers:
            item.thread.join(2)
        built.cleanup()

    assert history_reads == ["read"] and delivered == []
    assert built.status("A") is JobStatus.CANCELLED
    assert built.status("B") is JobStatus.QUEUED


def test_browsing_history_is_a_tracked_repository_use(tmp_path, monkeypatch):
    built = Harness(tmp_path, job_ids=())
    built.controller.webui_process_manager = None
    entered = threading.Event()
    release = threading.Event()

    def search(query):
        entered.set()
        assert release.wait(2)
        return built.repository.query_history(query)

    panel = SimpleNamespace(
        _registry=built.controller._thread_registry,
        _search_closed=False,
        _search=search,
        _set_busy=lambda busy: None,
        _poll=lambda: None,
        summary_var=SimpleNamespace(set=lambda text: None),
        after=lambda *_args: None,
    )
    monkeypatch.setattr(shutdown, "SHUTDOWN_BUDGET_SECONDS", 0.15)
    try:
        HistoryBrowserPanelV2._submit(panel, HistoryQuery(), append=False)
        assert entered.wait(1)
        built.controller.shutdown_app("history-browser-380")
        outcome = built.controller._shutdown_outcome
        assert "HistoryBrowserSearch" in outcome.remaining_workers
        assert outcome.repository == "left_open"
        assert built.repository.close_calls == 0
    finally:
        release.set()
        future, _append = panel._pending
        assert future.result(2).entries == ()
        built.cleanup()


def test_history_read_leaves_repository_lock_wait_on_shutdown(tmp_path):
    built = Harness(tmp_path, job_ids=())
    stop = threading.Event()
    result = []
    with built.repository._lock:
        worker = threading.Thread(
            target=lambda: result.append(built.repository.list_recent_jobs(stop=stop))
        )
        worker.start()
        stop.set()
        worker.join(1)
        assert not worker.is_alive()
    assert result == [[]]
    built.cleanup()


def test_persistence_stop_drains_all_acknowledged_writes(tmp_path):
    writer = PersistenceWorker()
    start = threading.Event()
    release = threading.Event()
    writer.start()
    paths = [tmp_path / f"{i}.json" for i in range(3)]

    def block_after_first_write():
        start.set()
        assert release.wait(2)

    try:
        assert writer.enqueue(
            PersistenceTask(
                "manifest",
                {"file_path": str(paths[0]), "payload": {"item": 0}},
                block_after_first_write,
            )
        )
        assert start.wait(2)
        for i, path in enumerate(paths[1:], 1):
            assert writer.enqueue(
                PersistenceTask("manifest", {"file_path": str(path), "payload": {"item": i}})
            )
        assert writer.stop(timeout=0) is False
        assert not writer.enqueue(
            PersistenceTask("manifest", {"file_path": str(tmp_path / "late.json")})
        )
    finally:
        release.set()
        assert writer.stop(timeout=2)
    assert all(path.is_file() for path in paths)


def test_gui_close_allows_natural_subprocess_exit_after_cooperative_worker(tmp_path):
    marker = tmp_path / "settled.txt"
    script = """
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from src.utils.graceful_exit import graceful_exit

stop = threading.Event()
def worker():
    stop.wait()
    Path(sys.argv[1]).write_text("settled")
threading.Thread(target=worker).start()
controller = SimpleNamespace(shutdown_app=lambda _: stop.set(), _shutdown_completed=True)
graceful_exit(controller, None, None, logging.getLogger())
print("returned normally", flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(marker)],
        timeout=15,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG": "0"},
    )
    assert "returned normally" in result.stdout
    assert marker.read_text() == "settled"
