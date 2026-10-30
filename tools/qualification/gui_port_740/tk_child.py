"""Comparable minimal Tk shell in its own process; never launches the application."""

from __future__ import annotations

import argparse
import sys
import threading
import time

from tools.qualification.gui_port_740.common import (
    emit,
    isolation_guard,
    memory,
    process_dpi_setup,
    rows,
    runtime,
    summary,
    window_dpi,
)


def run(args):
    process_dpi_setup()
    isolation_guard()
    import tkinter as tk
    from tkinter import ttk

    from src.gui.ui_dispatcher import release_tk_dispatcher, tk_dispatcher_for
    from src.gui.view_contracts.task_navigation_contract import all_tab_ids, get_destination

    root = tk.Tk()
    root.title("GUI-PORT-740 — synthetic read-only Tk proof")
    root.geometry("1000x650")
    dispatcher = tk_dispatcher_for(root)
    ui = threading.get_ident()
    status = tk.StringVar(value="Synthetic only: no application runtime")
    selection = "synthetic-00050"
    data = {"toolkit": "tk", "runtime": runtime(), "tk": root.tk.call("info", "patchlevel")}
    checks = {}
    nav = ttk.Combobox(
        root, state="readonly", values=[get_destination(i).display_label for i in all_tab_ids()]
    )
    nav.current(all_tab_ids().index("pipeline"))
    nav.pack(fill="x")
    nav.bind(
        "<<ComboboxSelected>>", lambda _e: status.set("Active: " + all_tab_ids()[nav.current()])
    )
    ttk.Label(root, textvariable=status).pack(fill="x")
    tables = []
    start = time.perf_counter()
    for title in ("Synthetic queue", "Synthetic history"):
        ttk.Label(root, text=title).pack(fill="x")
        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True)
        table = ttk.Treeview(
            frame, columns=("id", "status", "summary"), show="headings", selectmode="browse"
        )
        for column in ("id", "status", "summary"):
            table.heading(column, text=column.title())
        scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        scroll.pack(side="right", fill="y")
        table.configure(yscrollcommand=scroll.set)
        table.pack(fill="both", expand=True)
        for values in rows(args.rows):
            table.insert("", "end", iid=values[0], values=values)
        tables.append(table)
    data["populate_ms"] = (time.perf_counter() - start) * 1000
    tables[0].selection_set(selection)
    tables[0].bind(
        "<<TreeviewSelect>>",
        lambda _e: status.set("Synthetic selection: " + str(tables[0].selection())),
    )
    latencies, delivered, beats = [], [], []
    last = [time.perf_counter()]
    alive = [True]
    threads = []
    close_started = [None]
    peak_backlog = [0]

    def beat():
        now = time.perf_counter()
        beats.append((now - last[0]) * 1000)
        last[0] = now
        if alive[0]:
            root.after(5, beat)

    root.after(5, beat)

    def close():
        close_started[0] = time.perf_counter_ns()
        alive[0] = False
        release_tk_dispatcher(root)
        root.quit()

    root.protocol("WM_DELETE_WINDOW", close)

    def begin():
        data["idle_memory"] = memory()
        for table in tables:
            selected = table.selection()
            table.delete(*table.get_children())
            for values in rows(args.rows, 1):
                table.insert("", "end", iid=values[0], values=values)
            if selected:
                table.selection_set(selected)
        checks["projection_add_remove_status_and_selection"] = (
            tables[0].selection() == (selection,) and len(tables[0].get_children()) == args.rows
        )

        def worker():
            for index in range(args.burst):
                submitted = time.perf_counter()

                def update(index=index, submitted=submitted):
                    assert threading.get_ident() == ui
                    latencies.append((time.perf_counter() - submitted) * 1000)
                    delivered.append(index)
                    status.set(f"Synthetic update {index}; selection {selection}")
                    if len(delivered) == args.burst:
                        root.after(30, finish)

                dispatcher.schedule(update)
                with dispatcher._invoker._lock:
                    peak_backlog[0] = max(peak_backlog[0], len(dispatcher._invoker._pending))

        thread = threading.Thread(target=worker, name="740-tk-burst")
        threads.append(thread)
        thread.start()

    def finish():
        checks["burst_no_loss_duplicate_or_wrong_thread"] = len(set(delivered)) == args.burst
        data.update(
            latency_ms=summary(latencies),
            update_memory=memory(),
            heartbeat_ms=summary(beats),
            dpi=window_dpi(root.winfo_id()),
            tk_scaling=float(root.tk.call("tk", "scaling")),
            peak_backlog=peak_backlog[0],
        )
        # Same controls and rows, within the same interpreter: explicit warm shell.
        warm_start = time.perf_counter()
        warm = tk.Toplevel(root)
        warm.geometry("1000x650")
        ttk.Combobox(
            warm, values=[get_destination(i).display_label for i in all_tab_ids()], state="readonly"
        ).pack(fill="x")
        ttk.Label(warm, text="Synthetic warm shell").pack(fill="x")
        for _ in range(2):
            ttk.Label(warm, text="Synthetic projection").pack(fill="x")
            frame = ttk.Frame(warm)
            frame.pack(fill="both", expand=True)
            table = ttk.Treeview(
                frame, columns=("id", "status", "summary"), show="headings", selectmode="browse"
            )
            for column in ("id", "status", "summary"):
                table.heading(column, text=column.title())
            scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
            scroll.pack(side="right", fill="y")
            table.configure(yscrollcommand=scroll.set)
            table.pack(fill="both", expand=True)
            for values in rows(args.rows):
                table.insert("", "end", values=values)

        def warm_painted():
            if not warm.winfo_ismapped() or not warm.winfo_viewable():
                warm.after(5, warm_painted)
                return
            warm.update_idletasks()
            data["warm_visible_rendered"] = True
            data["warm_shell_first_paint_ms"] = (time.perf_counter() - warm_start) * 1000
            warm.destroy()
            close()

        warm.after(0, warm_painted)

    def visible():
        if not root.winfo_ismapped() or not root.winfo_viewable():
            root.after(5, visible)
            return
        root.update_idletasks()
        data["startup_heartbeat_ms"] = summary(beats) if beats else None
        beats.clear()
        last[0] = time.perf_counter()
        emit("first_visible", visible=bool(root.winfo_ismapped()))
        root.after(150, begin)

    root.after(0, visible)
    root.after(15000, close)
    root.mainloop()
    for thread in threads:
        thread.join(timeout=2)
    checks["no_python_worker_leak"] = not any(thread.is_alive() for thread in threads)
    data["close_started_ns"] = close_started[0]
    root.destroy()
    checks["qt_absent"] = "PySide6" not in sys.modules
    emit("result", status="PASS" if all(checks.values()) else "FAIL", checks=checks, **data)
    return 0 if all(checks.values()) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--burst", type=int, default=2000)
    args = parser.parse_args()
    if not 64 <= args.rows <= 2000 or not 1 <= args.burst <= 3000:
        parser.error("bounded proof inputs required")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
