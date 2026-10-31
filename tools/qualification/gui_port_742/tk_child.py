"""Opt-in Tk child: the qualification workspace over the production Tk theme and dispatcher. No application runtime."""

from __future__ import annotations

import sys
import threading
import time
import traceback

from tools.qualification.gui_port_740.common import (
    emit,
    isolation_guard,
    memory,
    process_dpi_setup,
    runtime,
)
from tools.qualification.gui_port_742 import child_common as cc
from tools.qualification.gui_port_742.drive import run_benchmark, run_matrix
from tools.qualification.gui_port_742.fixture import (
    fixture_fingerprint,
)


def run(args) -> int:
    cc.forbid(cc.FORBIDDEN_FOR_TK)
    isolation_guard()
    process_dpi_setup()
    import tkinter as tk

    from src.gui import theme_v2
    from src.gui.ui_dispatcher import release_tk_dispatcher, tk_dispatcher_for
    from tools.qualification.gui_port_742.tk_view import TkWorkspace

    errors: list[str] = []
    data: dict = {
        "toolkit": "tk",
        "runtime": runtime(),
        "mode": args.mode,
        "fixture": fixture_fingerprint(args.rows),
    }
    checks: dict = {}
    root = tk.Tk()
    root.withdraw()
    root.title("GUI-PORT-742 — Tk qualification workspace (read-only)")
    scale = args.sim_scale
    if scale != 1.0:
        root.tk.call("tk", "scaling", float(root.tk.call("tk", "scaling")) * scale)
    theme_v2.apply_theme(root)
    width, height = cc.parse_viewport(args.viewport)
    if width is None:
        root.state("zoomed")
    else:
        root.geometry(f"{round(width * scale)}x{round(height * scale)}+0+0")
    root.attributes("-topmost", True)
    dispatcher = tk_dispatcher_for(root)
    t0 = time.perf_counter()
    view = TkWorkspace(root, dispatcher, count=args.rows, px_scale=scale)
    constructed = time.perf_counter()
    view.plumbing.publish(0)
    ready = view.wait_until(lambda: view.observe_rows() == (args.rows, args.rows), 10000)
    populated = time.perf_counter()
    root.deiconify()
    deadline = time.perf_counter() + 10
    while time.perf_counter() < deadline and not (root.winfo_ismapped() and root.winfo_viewable()):
        root.update()
        time.sleep(0.002)
    root.update_idletasks()
    root.update()
    painted = time.perf_counter()
    visible = bool(root.winfo_ismapped() and root.winfo_viewable())
    emit("first_visible", visible=visible)
    build_info = {
        "construct_ms": (constructed - t0) * 1000,
        "populate_ms": (populated - constructed) * 1000,
        "show_to_paint_ms": (painted - populated) * 1000,
        "initial_render_ms": {
            "history": view.render_ms["history"][0] if view.render_ms["history"] else None,
            "queue": view.render_ms["queue"][0] if view.render_ms["queue"] else None,
        },
        "populated": ready,
    }
    hwnd = root.winfo_id()
    closed_state: dict = {}

    def on_close() -> None:
        closed_state["started_ns"] = time.perf_counter_ns()
        view.close()
        release_tk_dispatcher(root)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        if args.mode == "matrix":
            cc.activate(hwnd)
            data["matrix"] = run_matrix(
                view,
                count=args.rows,
                viewport=(None, None)
                if width is None
                else (round(width * scale), round(height * scale)),
                capture=cc.screen_capture,
                active_probe=lambda: cc.foreground_matches(hwnd),
            )
            if args.screenshot:
                top = view.window_state()
                box = (
                    top["root"][0],
                    top["root"][1],
                    top["root"][0] + top["client"][0],
                    top["root"][1] + top["client"][1],
                )
                cc.screen_capture(box).save(args.screenshot)
        elif args.mode == "benchmark":
            data["benchmark"] = run_benchmark(view, build_info, memory, args.rows)
        else:
            view.flush()
            emit("inspect_ready", pid=__import__("os").getpid(), hwnd=hwnd)
            import os

            end = time.perf_counter() + 40
            while time.perf_counter() < end and not os.path.exists(args.hold_file):
                root.update()
                time.sleep(0.02)
            checks["hold_released"] = os.path.exists(args.hold_file)
        data["build"] = build_info
        data["dpi"] = cc.dpi_record(
            hwnd,
            simulated_factor=None if scale == 1.0 else scale,
            requested=args.requested_dpi,
            toolkit_scale=float(root.tk.call("tk", "scaling")) * 72 / 96,
        )
        data["screen"] = {"work_area": cc.work_area(), "foreground": cc.foreground_matches(hwnd)}
        data["tk"] = root.tk.call("info", "patchlevel")
        data["tk_scaling"] = float(root.tk.call("tk", "scaling"))
        # Pending notifications at close: delayed, queued and worker-originated work must all be dropped.
        marks: list[str] = []
        dispatcher.invoke_later(1000, lambda: marks.append("delayed"))
        dispatcher.schedule(lambda: marks.append("queued"))
        view.publish_from_worker(20, drop=frozenset(), sink_revision=900)
        view.stream_status_from_worker(10, first_revision=2000)
        on_close()
        post = threading.Thread(
            target=lambda: dispatcher.schedule(lambda: marks.append("after-close-worker"))
        )
        post.start()
        post.join(timeout=2)
        checks["pending_dropped_at_close"] = not marks and not view.late_mutations
        data["late"] = {"marks": marks, "view": list(view.late_mutations)}
    except Exception:  # noqa: BLE001 - the bounded child reports failures instead of hanging
        errors.append(traceback.format_exc())
        try:
            on_close()
        except Exception:  # noqa: BLE001
            pass
    checks["pyside_absent"] = not any(m.startswith(("PySide6", "shiboken6")) for m in sys.modules)
    checks["no_python_worker_leak"] = not any(t.is_alive() for t in view._workers)
    ok = all(v for v in checks.values() if isinstance(v, bool)) and not errors
    emit(
        "result",
        status="PASS" if ok else "FAIL",
        checks=checks,
        errors=errors,
        close_started_ns=closed_state.get("started_ns"),
        warm_visible_rendered=(
            data.get("benchmark", {}).get("second_window", {}).get("rendered")
            if args.mode == "benchmark"
            else None
        ),
        **data,
    )
    return 0 if ok else 1


def main() -> int:
    parser = cc.build_parser(__doc__ or "")
    args = parser.parse_args()
    cc.validate_args(parser, args)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
