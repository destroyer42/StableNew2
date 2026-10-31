"""The scripted operator journey and its expected outcomes, written once for both toolkits.

A toolkit child implements ``Driver`` over its real widgets (``observe`` reads widgets, never the model). The expected
values here are computed from the fixture independently of the views. ``ModelDriver`` runs the same steps with no
toolkit so the scenario itself is covered by ordinary CI.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from src.controller.ports.ui_dispatcher import ImmediateUiDispatcher
from src.gui_v2.history_browser_model import HistoryFilters
from tools.qualification.gui_port_742.fixture import history_entries
from tools.qualification.gui_port_742.model import (
    NO_SELECTION_TEXT,
    SELECTED_MARKER,
    WorkspaceModel,
    nav_entries,
    placeholder_body,
    placeholder_title,
)
from tools.qualification.gui_port_742.wiring import STATUS_PREFIX, Plumbing

FOCUS_ORDER = (
    "search",
    "status",
    "date_from",
    "date_to",
    "apply",
    "clear",
    "queue_table",
    "history_table",
    "details",
)
FIRST_FOCUS = "nav"
STATUS_STREAM = 40


@dataclass(frozen=True)
class Observation:
    """What the user can see, read from widgets. Every field is plain data so toolkits compare for equality."""

    tab_id: str
    page_title: str
    page_body: str
    nav_labels: tuple[str, ...]
    queue_rows: int
    history_rows: int
    history_first: tuple[str, ...]
    history_first_cells: tuple[str, ...]
    selected_id: str | None
    marker_ids: tuple[str, ...]
    detail_heading: str
    detail_text: str
    notice_word: str
    notice_text: str
    result_line: str
    status_line: str


class Driver(Protocol):
    name: str
    capabilities: frozenset[str]  # "keyboard", "geometry"

    def observe(self) -> Observation: ...
    def navigate_group(self, group_id: str) -> bool: ...
    def navigate(self, tab_id: str) -> bool: ...
    def set_filters(self, filters: HistoryFilters) -> None: ...
    def apply_filters(self) -> None: ...
    def clear_filters(self) -> None: ...
    def select(self, job_id: str) -> bool: ...
    def publish_from_worker(
        self, data_revision: int, *, drop: frozenset[str], sink_revision: int
    ) -> None: ...
    def stream_status_from_worker(
        self, count: int, *, first_revision: int
    ) -> list[tuple[int, int]]: ...
    def wait_until(self, predicate: Callable[[], bool], timeout_ms: int) -> bool: ...
    def sink_metrics(self) -> dict[str, Any]: ...
    def focus_first(self) -> str: ...
    def press(self, key: str) -> str: ...
    def row_visible(self, job_id: str) -> bool: ...
    def history_scrollbar_visible(self) -> bool: ...


@dataclass
class StepRecord:
    name: str
    ok: bool
    expected: Any = None
    observed: Any = None
    ms: float = 0.0
    note: str = ""

    def semantic(self) -> dict[str, Any]:
        """The toolkit-independent part used for cross-toolkit parity (timing and notes excluded)."""

        return {
            "name": self.name,
            "ok": self.ok,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass
class ScenarioContext:
    initial_revision: int = 0
    steps: list[StepRecord] = field(default_factory=list)


def brute_ids(entries, *, text: str = "", status: str | None = None) -> list[str]:
    """Independent reference filter (plain substring + status), deliberately not ``fixture_matches``."""

    terms = text.lower().split()
    return [
        e.job_id
        for e in entries
        if (status is None or e.status.value == status)
        and all(term in e.payload_summary.lower() for term in terms)
    ]


def _record(
    ctx: ScenarioContext, name: str, started: float, ok: bool, expected, observed, note: str = ""
):
    ctx.steps.append(
        StepRecord(name, bool(ok), expected, observed, (time.perf_counter() - started) * 1000, note)
    )


def _brief(o: Observation) -> dict[str, Any]:
    d = asdict(o)
    d["detail_text"] = d["detail_text"][:80]
    d["nav_labels"] = len(d["nav_labels"])
    return d


def run_scenario(driver: Driver, *, count: int = 500) -> list[StepRecord]:
    ctx = ScenarioContext()
    rev0 = history_entries(count, 0)
    nav = tuple(label for _id, label in nav_entries())

    # 1. startup -------------------------------------------------------------------------------------------------
    t = time.perf_counter()
    o = driver.observe()
    expected = {
        "tab_id": "pipeline",
        "nav_labels": nav,
        "queue_rows": count,
        "history_rows": count,
        "first": rev0[0].job_id,
        "notice_word": "Note",
    }
    ok = (
        o.tab_id == "pipeline"
        and o.nav_labels == nav
        and len(o.nav_labels) == 9
        and o.queue_rows == count
        and o.history_rows == count
        and o.history_first[:1] == (rev0[0].job_id,)
        and "Character Training (HOLD)" in o.nav_labels
        and o.notice_word == "Note"
    )
    _record(
        ctx,
        "startup",
        t,
        ok,
        expected,
        {
            k: _brief(o)[k]
            for k in ("tab_id", "queue_rows", "history_rows", "history_first", "notice_word")
        },
    )

    # 2. text + status filter ------------------------------------------------------------------------------------
    t = time.perf_counter()
    want = brute_ids(rev0, text="dragon", status="failed")
    driver.set_filters(HistoryFilters(text="dragon", status_label="Failed"))
    driver.apply_filters()
    o = driver.observe()
    ok = (
        len(want) > 3
        and o.history_rows == len(want)
        and list(o.history_first[:3]) == want[:3]
        and o.result_line == f"{len(want)} jobs shown. End of history."
    )
    _record(
        ctx,
        "filter_text_and_status",
        t,
        ok,
        {"rows": len(want), "head": want[:3]},
        {"rows": o.history_rows, "head": list(o.history_first[:3]), "line": o.result_line},
    )

    # 3. select + details (long error text must be reachable) ----------------------------------------------------
    t = time.perf_counter()
    job = want[2]
    selected = driver.select(job)
    o = driver.observe()
    ok = (
        selected
        and o.selected_id == job
        and o.detail_heading == f"Selected {job} (Failed)"
        and "CUDA out of memory" in o.detail_text
        and o.marker_ids == (job,)
    )
    _record(
        ctx,
        "select_and_inspect",
        t,
        ok,
        {"selected": job, "marker": [job]},
        {"selected": o.selected_id, "heading": o.detail_heading, "marker": list(o.marker_ids)},
    )

    # 4. clear filters, select a job whose status changes, refresh while it is selected -------------------------
    t = time.perf_counter()
    driver.clear_filters()
    driver.apply_filters()
    steady = "job-00251"  # completed at revision 0, failed at revision 2
    driver.select(steady)
    before = driver.observe()
    driver.publish_from_worker(2, drop=frozenset(), sink_revision=3)
    first_id = history_entries(count, 2)[0].job_id
    arrived = driver.wait_until(lambda: driver.observe().history_first[:1] == (first_id,), 4000)
    o = driver.observe()
    ok = (
        arrived
        and before.detail_heading == f"Selected {steady} (Completed)"
        and o.selected_id == steady
        and o.detail_heading == f"Selected {steady} (Failed)"
        and o.marker_ids == (steady,)
        and o.history_rows == count
    )
    _record(
        ctx,
        "refresh_preserves_selection",
        t,
        ok,
        {"first": first_id, "selected": steady, "heading_after": f"Selected {steady} (Failed)"},
        {
            "arrived": arrived,
            "selected": o.selected_id,
            "heading": o.detail_heading,
            "first": o.history_first[:1],
        },
    )

    # 5. the selected job leaves the projection -----------------------------------------------------------------
    t = time.perf_counter()
    driver.publish_from_worker(3, drop=frozenset({steady}), sink_revision=4)
    arrived = driver.wait_until(lambda: driver.observe().history_rows == count - 1, 4000)
    o = driver.observe()
    ok = (
        arrived
        and o.selected_id is None
        and o.marker_ids == ()
        and o.detail_text == NO_SELECTION_TEXT
        and o.notice_word == "Warning"
        and steady in o.notice_text
    )
    _record(
        ctx,
        "selection_removed_warns",
        t,
        ok,
        {"rows": count - 1, "selected": None, "notice_word": "Warning"},
        {"rows": o.history_rows, "selected": o.selected_id, "notice": o.notice_word},
    )

    # 6. a stale revision is skipped by the real sink ------------------------------------------------------------
    t = time.perf_counter()
    skipped_before = driver.sink_metrics().get("skipped_counts", {}).get("history", 0)
    driver.publish_from_worker(2, drop=frozenset(), sink_revision=3)
    driver.wait_until(lambda: False, 250)  # outlast the 75 ms notification coalescing window
    o = driver.observe()
    skipped = driver.sink_metrics().get("skipped_counts", {}).get("history", 0) - skipped_before
    ok = skipped == 1 and o.history_rows == count - 1
    _record(
        ctx,
        "stale_revision_skipped",
        t,
        ok,
        {"skipped": 1, "rows": count - 1},
        {"skipped": skipped, "rows": o.history_rows},
    )

    # 7. navigation, including the truthful HOLD ----------------------------------------------------------------
    t = time.perf_counter()
    seen: dict[str, Any] = {}
    ok = True
    for group, tab in (("edit", "review"), ("motion", "video_workflow"), ("learn", "learning")):
        ok &= driver.navigate_group(group)
        o = driver.observe()
        seen[group] = (o.tab_id, o.page_title)
        ok &= (
            o.tab_id == tab
            and o.page_title == placeholder_title(tab)
            and o.page_body == placeholder_body(tab)
        )
    ok &= driver.navigate("character_training")
    o = driver.observe()
    hold_body = placeholder_body("character_training")
    seen["hold"] = (o.tab_id, o.page_body)
    ok &= (
        o.tab_id == "character_training"
        and o.page_body == hold_body
        and o.page_body.startswith("HOLD:")
    )
    rejected = not driver.navigate("not-a-tab")
    ok &= rejected and driver.observe().tab_id == "character_training"
    ok &= driver.navigate("pipeline")
    o = driver.observe()
    ok &= o.tab_id == "pipeline" and o.history_rows == count - 1 and o.queue_rows == count
    _record(
        ctx,
        "navigation_and_hold",
        t,
        ok,
        {"hold_body": hold_body, "invalid_rejected": True},
        {**seen, "invalid_rejected": rejected, "back": (o.tab_id, o.history_rows)},
    )

    # 8. controlled invalid filter -------------------------------------------------------------------------------
    t = time.perf_counter()
    rows_before = driver.observe().history_rows
    driver.set_filters(HistoryFilters(date_from="2026-13-45"))
    driver.apply_filters()
    o = driver.observe()
    ok = (
        o.notice_word == "Error"
        and o.notice_text == "From must be a date like 2026-10-18."
        and o.history_rows == rows_before
    )
    bad = (o.notice_word, o.notice_text, o.history_rows)
    driver.set_filters(HistoryFilters(text="harbor"))
    driver.apply_filters()
    o = driver.observe()
    want = brute_ids(history_entries(count, 3, frozenset({steady})), text="harbor")
    ok &= o.notice_word != "Error" and o.history_rows == len(want)
    _record(
        ctx,
        "invalid_filter_feedback",
        t,
        ok,
        {
            "error": ["Error", "From must be a date like 2026-10-18."],
            "rows_unchanged": rows_before,
            "recovered_rows": len(want),
        },
        {"error": list(bad[:2]), "rows_unchanged": bad[2], "recovered_rows": o.history_rows},
    )
    driver.clear_filters()
    driver.apply_filters()

    # 9. keyboard, focus order and scroll-to-control ------------------------------------------------------------
    if "keyboard" in driver.capabilities:
        t = time.perf_counter()
        order = [driver.focus_first()]
        order += [driver.press("Tab") for _ in FOCUS_ORDER]
        ok = order == [FIRST_FOCUS, *FOCUS_ORDER]
        _record(ctx, "keyboard_focus_order", t, ok, [FIRST_FOCUS, *FOCUS_ORDER], order)

        t = time.perf_counter()
        driver.select("job-00100")
        # Focus the table by tabbing from the nav (real traversal), then arrow within it.
        driver.focus_first()
        for _ in range(8):
            driver.press("Tab")
        focused = driver.observe()
        down = driver.press("Down")
        o_down = driver.observe()
        driver.press("Up")
        o_up = driver.observe()
        ok = (
            focused.selected_id == "job-00100"
            and down == "history_table"
            and o_down.selected_id == "job-00099"
            and o_down.detail_heading.startswith("Selected job-00099")
            and o_up.selected_id == "job-00100"
        )
        _record(
            ctx,
            "keyboard_row_navigation",
            t,
            ok,
            {"down": "job-00099", "up": "job-00100"},
            {"down": o_down.selected_id, "up": o_up.selected_id},
        )

        t = time.perf_counter()
        driver.select("job-00020")  # the oldest rows sit far below the first screenful
        o_far = driver.observe()
        ok = (
            driver.history_scrollbar_visible()
            and driver.row_visible("job-00020")
            and o_far.selected_id == "job-00020"
        )
        _record(
            ctx,
            "scroll_to_selection",
            t,
            ok,
            {"selected": "job-00020", "scrollbar": True, "visible": True},
            {
                "selected": o_far.selected_id,
                "scrollbar": driver.history_scrollbar_visible(),
                "visible": driver.row_visible("job-00020"),
            },
        )

    # 10. worker-originated status stream -----------------------------------------------------------------------
    t = time.perf_counter()
    delivered = driver.stream_status_from_worker(STATUS_STREAM, first_revision=1)
    last = f"Queue status: {STATUS_PREFIX}{STATUS_STREAM - 1:03d}"
    arrived = driver.wait_until(lambda: driver.observe().status_line == last, 4000)
    indexes = [index for index, _thread in delivered]
    ok = (
        arrived
        and indexes == sorted(set(indexes))
        and indexes[-1:] == [STATUS_STREAM - 1]
        and all(thread == 1 for _index, thread in delivered)
    )
    _record(
        ctx,
        "worker_status_stream",
        t,
        ok,
        {"last": last, "ui_thread_only": True, "monotonic": True},
        {
            "last": driver.observe().status_line,
            "deliveries": len(delivered),
            "ui_thread_only": all(th == 1 for _i, th in delivered),
        },
    )
    return ctx.steps


class ModelDriver:
    """Toolkit-free ``Driver`` over ``WorkspaceModel`` and the real sink/AppState, for ordinary CI."""

    name = "model"
    capabilities: frozenset[str] = frozenset()

    def __init__(self, count: int = 500) -> None:
        self.model = WorkspaceModel()
        self._filters = HistoryFilters()
        self.status = "Queue status: (none)"
        self.status_deliveries: list[tuple[int, int]] = []
        self.plumbing = Plumbing(
            ImmediateUiDispatcher(),
            on_history=self._history,
            on_queue=self._queue,
            on_status=self._status,
            count=count,
        )
        self.plumbing.publish(0)

    def _history(self) -> None:
        self.model.set_projection(tuple(self.plumbing.state.history_items), self.model.queue)

    def _queue(self) -> None:
        self.model.queue = tuple(self.plumbing.state.queue_jobs)

    def _status(self) -> None:
        value = self.plumbing.state.queue_status
        self.status = f"Queue status: {value}"
        self.status_deliveries.append((int(value.rsplit("-", 1)[1]), 1))

    def observe(self) -> Observation:
        m = self.model
        dest_title = placeholder_title(m.tab_id) if m.tab_id != "pipeline" else "Pipeline"
        body = placeholder_body(m.tab_id) if m.tab_id != "pipeline" else ""
        entry = m.selected_entry()
        details = m.details()
        return Observation(
            tab_id=m.tab_id,
            page_title=dest_title,
            page_body=body,
            nav_labels=tuple(label for _tab, label in nav_entries()),
            queue_rows=len(m.queue),
            history_rows=len(m.visible),
            history_first=tuple(e.job_id for e in m.visible[:3]),
            history_first_cells=(m.visible[0].job_id,) if m.visible else (),
            selected_id=m.selected_id,
            marker_ids=(m.selected_id,) if m.selected_id else (),
            detail_heading=details.splitlines()[0] if entry else "",
            detail_text=details,
            notice_word=m.notice.word,
            notice_text=m.notice.text,
            result_line=m.result_line,
            status_line=self.status,
        )

    def navigate_group(self, group_id: str) -> bool:
        return self.model.navigate_group(group_id)

    def navigate(self, tab_id: str) -> bool:
        return self.model.navigate(tab_id)

    def set_filters(self, filters: HistoryFilters) -> None:
        self._filters = filters

    def apply_filters(self) -> None:
        self.model.apply_filters(self._filters)

    def clear_filters(self) -> None:
        self._filters = HistoryFilters()

    def select(self, job_id: str) -> bool:
        return self.model.select(job_id)

    def publish_from_worker(
        self, data_revision: int, *, drop: frozenset[str], sink_revision: int
    ) -> None:
        self.plumbing.publish(data_revision, drop=drop, sink_revision=sink_revision)

    def stream_status_from_worker(
        self, count: int, *, first_revision: int
    ) -> list[tuple[int, int]]:
        for index in range(count):
            self.plumbing.publish_status(index, revision=first_revision + index)
        return list(self.status_deliveries)

    def wait_until(self, predicate: Callable[[], bool], timeout_ms: int) -> bool:
        return bool(predicate())

    def sink_metrics(self) -> dict[str, Any]:
        return self.plumbing.sink.get_metrics_snapshot()

    def focus_first(self) -> str:  # pragma: no cover - not offered without "keyboard"
        raise NotImplementedError

    def press(self, key: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def row_visible(self, job_id: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def history_scrollbar_visible(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:
        self.plumbing.close()


__all__ = [
    "FOCUS_ORDER",
    "FIRST_FOCUS",
    "SELECTED_MARKER",
    "STATUS_STREAM",
    "Driver",
    "ModelDriver",
    "Observation",
    "StepRecord",
    "brute_ids",
    "run_scenario",
]
