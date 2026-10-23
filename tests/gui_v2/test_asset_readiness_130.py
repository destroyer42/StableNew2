"""Read-only asset readiness view contract (PR-ASSET-130): explicit, off-thread, latest-wins, close-safe."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from typing import Any

import pytest

from src.assets.resource_readiness import InstalledEvidence, build_report
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui_v2.asset_readiness_view import ReadinessSession, headline, project_rows
from tests.assets.readiness_fixtures_130 import file_spec, make_catalog, resource, variant


class _ManualRunner(BackgroundWorkRunner):
    """Holds each unit of work until the test runs it, so ordering is controlled and nothing runs inline."""

    def __init__(self) -> None:
        self.queued: list[tuple[Callable[[], WorkOutcome], Callable[[WorkOutcome], None]]] = []
        super().__init__(spawn=lambda name, target: None, dispatch=lambda fn: fn())

    def start(self, name, work, on_done) -> None:  # type: ignore[override]
        self.queued.append((work, on_done))

    def run(self, index: int) -> None:
        work, on_done = self.queued[index]
        try:
            outcome = work()
        except BaseException as exc:  # mirror the production runner
            outcome = WorkOutcome(error=str(exc))
        on_done(outcome)


def _report(label: str = "r") -> dict[str, Any]:
    catalog = make_catalog(
        resource(label, [file_spec("model_config", [variant("config.json", None)])])
    )
    return build_report(catalog, InstalledEvidence((), "explicit_refresh", True))


def _session(runner, produce, received):
    return ReadinessSession(
        runner, produce, received.append, lambda m: received.append(("error", m))
    )


def test_nothing_runs_until_an_explicit_request() -> None:
    runner, calls, received = _ManualRunner(), [], []
    session = _session(runner, lambda refresh, stale: calls.append(refresh) or _report(), received)

    assert runner.queued == [] and calls == [] and received == []
    session.request(refresh=False)
    assert (
        calls == [] and len(runner.queued) == 1
    )  # queued for a worker, not run on the caller's thread


def test_a_stale_response_from_a_superseded_request_never_updates_the_view() -> None:
    runner, received = _ManualRunner(), []
    seen_stale: list[bool] = []

    def produce(refresh: bool, stale: Callable[[], bool]) -> dict[str, Any]:
        seen_stale.append(stale())
        return _report("first" if refresh else "second")

    session = _session(runner, produce, received)
    session.request(refresh=True)
    session.request(refresh=False)

    runner.run(0)  # the older request finishes after being superseded
    assert received == [] and seen_stale == [True]  # it was also told to cancel its hashing
    runner.run(1)
    assert [item["resources"][0]["id"] for item in received] == ["second"]


def test_a_closed_view_is_never_updated_and_errors_are_reported_once() -> None:
    runner, received = _ManualRunner(), []
    session = _session(runner, lambda refresh, stale: _report(), received)
    session.request(refresh=True)
    session.close()
    runner.run(0)
    session.request(refresh=True)

    assert received == [] and len(runner.queued) == 1

    failing = _session(
        runner, lambda refresh, stale: (_ for _ in ()).throw(RuntimeError("boom")), received
    )
    failing.request(refresh=False)
    runner.run(1)
    assert received == [("error", "boom")]


def test_busy_flag_follows_the_latest_request() -> None:
    runner, received, busy = _ManualRunner(), [], []
    session = ReadinessSession(
        runner, lambda r, s: _report(), received.append, lambda m: None, busy.append
    )
    session.request(refresh=False)
    assert session.busy and busy == [True]
    runner.run(0)
    assert not session.busy and busy == [True, False]


def test_the_real_runner_does_the_work_off_the_calling_thread() -> None:
    delivered = threading.Event()
    worker_threads: list[int] = []
    received: list[dict[str, Any]] = []
    started: list[threading.Thread] = []

    def spawn(name: str, target: Callable[[], None]) -> None:
        thread = threading.Thread(target=target, name=name)
        started.append(thread)
        thread.start()

    runner = BackgroundWorkRunner(spawn=spawn, dispatch=lambda fn: fn())

    def produce(refresh: bool, stale: Callable[[], bool]) -> dict[str, Any]:
        worker_threads.append(threading.get_ident())
        return _report()

    def on_report(report: dict[str, Any]) -> None:
        received.append(report)
        delivered.set()

    ReadinessSession(runner, produce, on_report, lambda m: delivered.set()).request(refresh=True)
    assert delivered.wait(10)
    for thread in started:
        thread.join(10)

    assert worker_threads and worker_threads[0] != threading.get_ident()
    assert received[0]["resources"][0]["id"] == "r"


def test_rows_and_headline_state_what_is_known_and_unknown() -> None:
    complete = _report()
    incomplete = build_report(
        make_catalog(resource("r", [file_spec("model_config", [variant("config.json", None)])])),
        InstalledEvidence((), "cached_snapshot", False, "not_refreshed"),
    )

    (row,) = project_rows(complete)
    assert (row.status, row.status_label) == ("missing", "Missing")
    assert "huggingface.co" in row.detail and row.steps
    assert project_rows(incomplete)[0].status == "incomplete"
    assert "Nothing is downloaded" in headline(complete)
    assert "absence cannot be shown" in headline(incomplete)


def test_the_debug_hub_tab_starts_idle_and_only_requests_on_a_button(
    tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.gui.panels_v2.asset_readiness_tab_v2 import AssetReadinessTab

    runner, produced = _ManualRunner(), []
    tab = AssetReadinessTab(
        tk_root, runner=runner, producer=lambda r, s: produced.append(r) or _report()
    )
    tab.update_idletasks()

    assert runner.queued == [] and produced == []  # constructing and mapping the tab does no work
    tab._refresh_button.invoke()
    assert len(runner.queued) == 1 and produced == []
    runner.run(0)
    tab.update_idletasks()
    assert produced == [True]
    assert "Missing" in tab._text.get("1.0", tk.END)
    tab.destroy()
    assert tab.session._closed is True
