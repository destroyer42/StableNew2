"""Opt-in Tk child for GUI-SEAM-743: the 742 qualification workspace under one injected production-pump configuration.

One process = one condition. The production ``TkInvoker._pump`` is the only scheduler; this child changes its three tuning
attributes (before the first timer is armed) and records pump entries around it. No application runtime, backend or data.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
import traceback
from collections import Counter
from typing import Any

from tools.qualification.gui_port_740.common import (
    emit,
    isolation_guard,
    memory,
    process_dpi_setup,
    runtime,
)
from tools.qualification.gui_port_742 import child_common as cc
from tools.qualification.gui_port_742.drive import (
    measure_filters,
    measure_refresh,
    measure_selection,
    measure_sustained,
)
from tools.qualification.gui_port_742.evidence import summarize
from tools.qualification.gui_port_742.fixture import fixture_fingerprint
from tools.qualification.gui_seam_743.config import WORKLOAD, ConfigError, PumpConfig
from tools.qualification.gui_seam_743.inject import (
    PumpLog,
    dispatcher_with_config,
    production_defaults,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--interval-ms", type=int, required=True)
    parser.add_argument("--max-callbacks", type=int, required=True)
    parser.add_argument("--max-pump-ms", type=float, required=True)
    return parser


def config_from_args(args: argparse.Namespace) -> PumpConfig:
    return PumpConfig(args.name, args.interval_ms, args.max_callbacks, args.max_pump_ms).validate()


def run_loop_for(root: Any, seconds: float) -> None:
    """A real Tk main loop for a bounded time (the production idle/dispatch environment, not an update() poll)."""

    root.after(round(seconds * 1000), root.quit)
    root.mainloop()


def periods_ms(starts: list[float]) -> list[float]:
    return [(b - a) * 1000 for a, b in zip(starts, starts[1:], strict=False)]


def measure_idle(root: Any, log: PumpLog, seconds: float) -> dict[str, Any]:
    """Pump cadence and process/host CPU with nothing queued, under a real main loop."""

    import psutil

    process = psutil.Process()
    run_loop_for(root, 0.3)  # settle
    first = len(log.starts)
    psutil.cpu_percent(None)
    cpu0, wall0 = process.cpu_times(), time.perf_counter()
    run_loop_for(root, seconds)
    cpu1, wall1 = process.cpu_times(), time.perf_counter()
    host = psutil.cpu_percent(None)
    starts = log.starts[first:]
    periods = periods_ms(starts)
    spent = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
    return {
        "window_s": wall1 - wall0,
        "pump_count": len(starts),
        "pump_hz": len(starts) / (wall1 - wall0),
        "period_ms": summarize(periods, label="idle pump period") if periods else None,
        "process_cpu_percent": 100.0 * spent / (wall1 - wall0),
        "host_cpu_percent": host,
    }


def measure_burst(root: Any, view: Any, log: PumpLog, n: int) -> dict[str, Any]:
    """n independent lightweight callbacks from one worker thread, delivered by the real pump under a real main loop."""

    ui = view.ui_thread
    latency: list[float] = []
    work: list[float] = []
    delivered: list[int] = []
    pumps: list[int] = []
    wrong: list[int] = []
    peak = [0]
    first_submit: list[float] = []
    last_end: list[float] = []
    guard = root.after(30000, root.quit)

    def worker() -> None:
        first_submit.append(time.perf_counter())
        for index in range(n):
            submitted = time.perf_counter()

            def callback(index=index, submitted=submitted) -> None:
                begin = time.perf_counter()
                if threading.get_ident() != ui:
                    wrong.append(index)
                latency.append((begin - submitted) * 1000)
                delivered.append(index)
                pumps.append(log.current)
                view.render_status(
                    f"Synthetic update {index}"
                )  # one label update: no table re-render
                end = time.perf_counter()
                work.append((end - begin) * 1000)
                last_end.append(end)
                if len(delivered) >= n:
                    root.quit()

            view.dispatcher.schedule(callback)
            peak[0] = max(peak[0], view.backlog())

    thread = threading.Thread(target=worker, name="743-burst")
    thread.start()
    root.mainloop()
    thread.join(timeout=5)
    root.after_cancel(guard)
    problem = None if len(delivered) >= n else f"only {len(delivered)} of {n} callbacks arrived"
    counts = Counter(pumps)
    spans = log.durations_ms[min(counts) : max(counts) + 1] if counts else []
    return {
        "arrived": len(delivered) >= n,
        "problem": problem,
        "expected": n,
        "delivered": len(delivered),
        "missing": len(set(range(n)) - set(delivered)),
        "duplicates": len(delivered) - len(set(delivered)),
        "out_of_order": sum(1 for a, b in zip(delivered, delivered[1:], strict=False) if b < a),
        "wrong_thread": len(wrong),
        "peak_backlog": peak[0],
        "total_ms": (last_end[-1] - first_submit[0]) * 1000 if last_end and first_submit else None,
        "pumps_used": len(counts),
        "latency_ms": summarize(latency, label="burst dispatch latency") if latency else None,
        "callback_ms": summarize(work, label="burst callback cost") if work else None,
        "batch_sizes": summarize(list(counts.values()), label="callbacks per pump")
        if counts
        else None,
        "pump_ms": summarize(spans, label="burst pump duration") if spans else None,
    }


def run(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    cc.forbid(cc.FORBIDDEN_FOR_TK)
    isolation_guard()
    process_dpi_setup()
    import tkinter as tk

    from src.gui import theme_v2
    from src.gui.ui_dispatcher import release_tk_dispatcher, tk_dispatcher_for
    from tools.qualification.gui_port_742.tk_view import TkWorkspace

    rows = WORKLOAD["rows"]
    errors: list[str] = []
    checks: dict[str, bool] = {}
    data: dict[str, Any] = {
        "toolkit": "tk",
        "runtime": runtime(),
        "fixture": fixture_fingerprint(rows),
        "workload": dict(WORKLOAD),
    }
    root = tk.Tk()
    root.withdraw()
    root.title("GUI-SEAM-743 — Tk dispatcher budget qualification (read-only)")
    theme_v2.apply_theme(root)
    root.geometry("1366x768+0+0")
    root.attributes("-topmost", True)
    dispatcher, log, effective = dispatcher_with_config(root, config)
    data["config"] = {
        "name": config.name,
        "requested": config.parameters(),
        "effective": effective,
        "production_defaults": production_defaults(),
    }
    view = TkWorkspace(root, dispatcher, count=rows)
    view.plumbing.publish(0)
    populated = view.wait_until(lambda: view.observe_rows() == (rows, rows), 10000)
    root.deiconify()
    deadline = time.perf_counter() + 10
    while time.perf_counter() < deadline and not (root.winfo_ismapped() and root.winfo_viewable()):
        root.update()
        time.sleep(0.002)
    root.update_idletasks()
    root.update()
    visible = bool(root.winfo_ismapped() and root.winfo_viewable())
    emit("first_visible", visible=visible)
    invoker = dispatcher._invoker
    closed: dict[str, Any] = {}

    def on_close() -> None:
        closed.setdefault("started_ns", time.perf_counter_ns())
        view.close()
        release_tk_dispatcher(root)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        checks["populated"] = bool(populated)
        checks["single_dispatcher_per_root"] = (
            tk_dispatcher_for(root) is dispatcher and dispatcher._invoker is invoker
        )
        view.wait_until(lambda: False, 300)  # settle
        data["idle"] = measure_idle(root, log, WORKLOAD["idle_quiet_seconds"])
        data["idle_memory"] = memory()
        data["interaction"] = measure_filters(view) | measure_selection(view)
        data["refresh"] = _refresh(view, rows)
        data["sustained"] = _sustained(view, log)
        data["burst"] = measure_burst(root, view, log, WORKLOAD["burst_callbacks"])
        # Pending notifications at close: delayed, queued and worker-originated work must all be dropped.
        marks: list[str] = []
        dispatcher.invoke_later(1000, lambda: marks.append("delayed"))
        dispatcher.schedule(lambda: marks.append("queued"))
        view.publish_from_worker(20, drop=frozenset(), sink_revision=900)
        view.stream_status_from_worker(10, first_revision=2000)
        on_close()
        dispatcher.dispose()  # the dispatcher's disposal and release are idempotent
        release_tk_dispatcher(root)
        post = threading.Thread(
            target=lambda: dispatcher.schedule(lambda: marks.append("after-close-worker")),
            name="743-post-close",
        )
        post.start()
        post.join(timeout=2)
        time.sleep(0.2)
        main = threading.main_thread()
        alive = [t.name for t in threading.enumerate() if t is not main and t.is_alive()]
        data["lifecycle"] = {
            "pending_dropped_at_close": not marks,
            "no_late_mutations": not view.late_mutations,
            "no_python_worker_leak": not alive and not any(t.is_alive() for t in view._workers),
            "pyside_absent": not any(m.startswith(("PySide6", "shiboken6")) for m in sys.modules),
            "single_dispatcher_per_root": checks.pop("single_dispatcher_per_root"),
            "dispatcher_disposed": bool(invoker._disposed and dispatcher.disposed),
            "dispatcher_queue_empty": not invoker._pending and not invoker._pending_ids,
            "dispatcher_timers_empty": not invoker._timers,
            "marks": marks,
            "alive_threads": alive,
            "late_view_mutations": list(view.late_mutations),
        }
    except Exception:  # noqa: BLE001 - the bounded child reports failures instead of hanging
        errors.append(traceback.format_exc())
        try:
            on_close()
        except Exception:  # noqa: BLE001
            pass
    lifecycle = data.get("lifecycle") or {}
    ok = (
        not errors
        and visible
        and all(checks.values())
        and bool(lifecycle)
        and all(v for k, v in lifecycle.items() if isinstance(v, bool))
    )
    emit(
        "result",
        status="PASS" if ok else "FAIL",
        checks=checks,
        errors=errors,
        close_started_ns=closed.get("started_ns"),
        **data,
    )
    return 0 if ok else 1


def _refresh(view: Any, rows: int) -> dict[str, Any]:
    raw = measure_refresh(view, rows)
    return {
        "arrived": raw["refresh_arrived"],
        "to_visible_ms": raw["refresh_to_visible_ms"],
        "renders": raw["refresh_renders"],
        "render_ms_median": raw["refresh_render_ms_median"],
        "selection_kept": raw["refresh_selection_kept"],
        "heartbeat": raw["refresh_loaded_heartbeat"],
    }


def _sustained(view: Any, log: PumpLog) -> dict[str, Any]:
    first = len(log.starts)
    raw = measure_sustained(view, WORKLOAD["sustained_seconds"], WORKLOAD["sustained_interval_s"])
    spans = log.durations_ms[first:]
    return {
        "heartbeat": raw["sustained_heartbeat"],
        "publishes": raw["sustained_publishes"],
        "renders": raw["sustained_renders"],
        "render_ms_median": raw["sustained_render_ms_median"],
        "pump_count": len(log.starts) - first,
        "pump_ms": summarize(spans, label="sustained pump duration") if spans else None,
        "pump_period_ms_median": (
            statistics.median(periods_ms(log.starts[first:]))
            if len(log.starts) - first > 1
            else None
        ),
    }


def main() -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args())
    except ConfigError as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    sys.exit(main())
