"""Measurement and matrix procedures shared by both toolkit children (identical boundaries, identical clocks).

Everything here talks to the view only through its ``Driver`` surface, so Tk and Qt are timed by the same code. Clocks
are ``time.perf_counter`` inside the child and ``perf_counter_ns`` events across processes (one system-wide monotonic
clock on Windows).
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import asdict
from typing import Any

from src.gui_v2.history_browser_model import HistoryFilters
from tools.qualification.gui_port_742.evidence import (
    EvidenceError,
    evaluate_reachability,
    summarize,
    validate_sequence,
)
from tools.qualification.gui_port_742.fixture import history_entries
from tools.qualification.gui_port_742.scenario import run_scenario

FILTER_CYCLE = (
    HistoryFilters(text="dragon"),
    HistoryFilters(status_label="Failed"),
    HistoryFilters(text="harbor", status_label="Completed"),
    HistoryFilters(),
)
REFRESH_REVISIONS = 12
BURST = 2000


def _median(values: list[float]) -> float:
    return statistics.median(values)


def measure_filters(view, repeats: int = 3) -> dict[str, float]:
    handler, visible = [], []
    for _ in range(repeats):
        for filters in FILTER_CYCLE:
            view.set_filters(filters)
            view.flush()
            started = time.perf_counter()
            view.apply_filters()
            handled = time.perf_counter()
            view.flush()
            done = time.perf_counter()
            handler.append((handled - started) * 1000)
            visible.append((done - started) * 1000)
    return {
        "filter_handler_ms": _median(handler),
        "filter_visible_ms": _median(visible),
        "filter_ops": len(handler),
    }


def measure_selection(view, count: int = 20) -> dict[str, float]:
    ids = [e.job_id for e in view.model.visible]
    picks = [ids[(i * 23) % len(ids)] for i in range(count)]
    handler, visible = [], []
    for job in picks:
        started = time.perf_counter()
        view.select(job)
        handled = time.perf_counter()
        view.flush()
        done = time.perf_counter()
        observed = view.observe()
        if observed.selected_id != job or not observed.detail_heading.startswith(f"Selected {job}"):
            raise EvidenceError(f"selection of {job} not reflected in details")
        handler.append((handled - started) * 1000)
        visible.append((done - started) * 1000)
    return {
        "select_handler_ms": _median(handler),
        "select_visible_ms": _median(visible),
        "select_ops": count,
    }


def measure_refresh(view, count: int = 500) -> dict[str, Any]:
    """A worker publishes REFRESH_REVISIONS projections back-to-back plus a status stream while the UI stays live."""

    view.clear_filters()
    view.apply_filters()
    view.flush()
    keep = view.model.visible[len(view.model.visible) // 2].job_id
    view.select(keep)
    renders_before = len(view.render_ms["history"])
    view.start_heartbeat()
    first_id = history_entries(count, REFRESH_REVISIONS)[0].job_id
    base_sink = view.sink_metrics().get("surface_revisions", {}).get("history", 0)

    def work() -> None:
        for step in range(1, REFRESH_REVISIONS + 1):
            view.plumbing.publish(step, sink_revision=base_sink + step)
            view.plumbing.publish_status(step, revision=1000 + step)

    started = time.perf_counter()
    thread = threading.Thread(target=work, name="742-refresh")
    thread.start()
    arrived = view.wait_until(lambda: view.observe().history_first[:1] == (first_id,), 15000)
    elapsed = (time.perf_counter() - started) * 1000
    thread.join(timeout=5)
    view.flush()
    gaps = view.stop_heartbeat()
    observed = view.observe()
    renders = view.render_ms["history"][renders_before:]
    return {
        "refresh_to_visible_ms": elapsed,
        "refresh_arrived": arrived,
        "refresh_renders": len(renders),
        "refresh_render_ms_median": _median(renders) if renders else None,
        "refresh_selection_kept": observed.selected_id == keep,
        "refresh_loaded_heartbeat": summarize(gaps, label="loaded heartbeat") if gaps else None,
    }


def measure_sustained(view, seconds: float = 1.5, interval_s: float = 0.02) -> dict[str, Any]:
    """Fixed-duration worker load (about 50 projections/s plus 75 ms notification coalescing) with the UI heartbeat live."""

    base_sink = view.sink_metrics().get("surface_revisions", {}).get("history", 0)
    stop, published = threading.Event(), [0]

    def work() -> None:
        index = 0
        while not stop.is_set():
            view.plumbing.publish(13 + (index % 24), sink_revision=base_sink + 1 + index)
            published[0] += 1
            index += 1
            stop.wait(interval_s)

    renders_before = len(view.render_ms["history"])
    view.start_heartbeat()
    thread = threading.Thread(target=work, name="742-sustained")
    thread.start()
    view.wait_until(lambda: False, int(seconds * 1000))
    stop.set()
    gaps = view.stop_heartbeat()
    thread.join(timeout=5)
    view.wait_until(lambda: False, 300)
    renders = view.render_ms["history"][renders_before:]
    return {
        "sustained_heartbeat": summarize(gaps, label="sustained heartbeat"),
        "sustained_publishes": published[0],
        "sustained_renders": len(renders),
        "sustained_render_ms_median": _median(renders) if renders else None,
    }


def measure_burst(view, n: int = BURST) -> dict[str, Any]:
    ui = view.ui_thread
    latency, work, delivered, wrong = [], [], [], []
    peak = [0]

    def worker() -> None:
        for index in range(n):
            submitted = time.perf_counter()

            def callback(index=index, submitted=submitted) -> None:
                begin = time.perf_counter()
                if threading.get_ident() != ui:
                    wrong.append(index)
                latency.append((begin - submitted) * 1000)
                delivered.append(index)
                view.render_status(f"Synthetic update {index}")
                work.append((time.perf_counter() - begin) * 1000)

            view.dispatcher.schedule(callback)
            peak[0] = max(peak[0], view.backlog())

    started = time.perf_counter()
    thread = threading.Thread(target=worker, name="742-burst")
    thread.start()
    arrived = view.wait_until(lambda: len(delivered) >= n, 30000)
    total = (time.perf_counter() - started) * 1000
    thread.join(timeout=5)
    flush_started = time.perf_counter()
    view.flush()
    flush_ms = (time.perf_counter() - flush_started) * 1000
    problem = None
    try:
        validate_sequence(n, delivered, lossless=True)
        if wrong:
            raise EvidenceError(f"{len(wrong)} callbacks ran off the UI thread")
    except EvidenceError as error:
        problem = str(error)
    return {
        "burst_arrived": arrived,
        "burst_problem": problem,
        "burst_total_ms": total,
        "burst_flush_ms": flush_ms,
        "burst_peak_backlog": peak[0],
        "burst_dispatch_ms": summarize(latency, label="dispatch latency") if latency else None,
        "burst_callback_ms": summarize(work, label="callback work") if work else None,
    }


def idle_heartbeat(view, ms: int = 500) -> dict[str, Any]:
    view.start_heartbeat()
    view.wait_until(lambda: False, ms)
    return summarize(view.stop_heartbeat(), label="idle heartbeat")


def run_benchmark(view, build_info: dict[str, Any], memory, count: int = 500) -> dict[str, Any]:
    """Everything after the window is verified visible. ``build_info`` carries the pre-show timings."""

    out: dict[str, Any] = dict(build_info)
    view.wait_until(lambda: False, 300)  # settle before the idle working set
    out["idle_memory"] = memory()
    out["idle_heartbeat"] = idle_heartbeat(view)
    out.update(measure_filters(view))
    out.update(measure_selection(view))
    out.update(measure_refresh(view, count))
    out.update(measure_sustained(view))
    out.update(measure_burst(view))
    out["second_window"] = view.second_window(count)
    out["update_memory"] = memory()
    return out


# ----- matrix -------------------------------------------------------------------------------------------------------
def step_dicts(steps) -> list[dict[str, Any]]:
    return [s.semantic() | {"ms": s.ms} for s in steps]


def run_matrix(
    view, *, count: int, viewport: tuple[int | None, int | None], capture, active_probe
) -> dict[str, Any]:
    requested = {"width": viewport[0], "height": viewport[1], "maximized": viewport[0] is None}
    client = view.set_viewport(*viewport)
    view.wait_until(lambda: False, 150)
    state_before = view.window_state()
    controls = view.controls()
    issues = evaluate_reachability(controls, (client[0], client[1]))
    steps = run_scenario(view, count=count)
    view.flush()
    after_controls = view.controls()
    issues_after = evaluate_reachability(after_controls, (client[0], client[1]))
    focus = focus_evidence(view, capture, active_probe)
    return {
        "requested": requested,
        "client": list(client),
        "window": state_before,
        "controls_before": controls,
        "controls_after": after_controls,
        "reachability_issues": sorted(set(issues + issues_after)),
        "steps": step_dicts(steps),
        "focus": focus,
        "discoverability": view.cell_discoverability(),
        "accessibility": view.accessibility(),
    }


def focus_evidence(view, capture, active_probe) -> dict[str, Any]:
    """Pixel change when a control takes keyboard focus (programmatic evidence of a visible indicator)."""

    result: dict[str, Any] = {"window_active": bool(active_probe()), "controls": {}}
    for name in ("search", "apply", "history_table"):
        view.focus_to("nav")
        view.wait_until(lambda: False, 60)
        x, y, w, h = view.widget_rect(name)
        box = (x - 4, y - 4, x + w + 4, y + h + 4)
        before = capture(box)
        view.focus_to(name)
        view.wait_until(lambda: False, 120)
        after = capture(box)
        changed = sum(1 for a, b in zip(before.getdata(), after.getdata(), strict=True) if a != b)
        result["controls"][name] = {
            "changed_pixels": changed,
            "focused": view.focused_name() == name,
        }
    result["visible_indicator"] = all(
        c["changed_pixels"] >= 40 and c["focused"] for c in result["controls"].values()
    )
    return result


def observation_dict(view) -> dict[str, Any]:
    return asdict(view.observe())
