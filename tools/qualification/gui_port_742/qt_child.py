"""Opt-in Qt child: the qualification workspace over the shared design values. tkinter is refused outright."""

from __future__ import annotations

import importlib.metadata
import os
import sys
import threading
import time
import traceback

from tools.qualification.gui_port_740.common import (
    emit,
    forbid_tk,
    isolation_guard,
    memory,
    process_dpi_setup,
    runtime,
)
from tools.qualification.gui_port_742 import child_common as cc
from tools.qualification.gui_port_742.drive import run_benchmark, run_matrix
from tools.qualification.gui_port_742.fixture import fixture_fingerprint


def run(args) -> int:
    forbid_tk()
    isolation_guard()
    process_dpi_setup()
    from PySide6 import QtCore, QtWidgets

    from tools.qualification.gui_port_740.qt_dispatcher import QtUiDispatcher
    from tools.qualification.gui_port_742.qt_dispatchers import TkPolicyQtDispatcher
    from tools.qualification.gui_port_742.qt_style import build_stylesheet
    from tools.qualification.gui_port_742.qt_view import QtWorkspace

    errors: list[str] = []
    checks: dict = {}
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())
    data: dict = {
        "toolkit": "qt",
        "runtime": runtime(),
        "mode": args.mode,
        "qt": QtCore.qVersion(),
        "pyside": importlib.metadata.version("PySide6"),
        "platform_plugin": app.platformName(),
        "dispatcher": args.dispatcher,
        "fixture": fixture_fingerprint(args.rows),
        "qt_scale_factor_env": os.environ.get("QT_SCALE_FACTOR"),
        "screens": [
            {
                "name": s.name(),
                "dpr": s.devicePixelRatio(),
                "logical_dpi": s.logicalDotsPerInch(),
                "size": [s.size().width(), s.size().height()],
            }
            for s in app.screens()
        ],
    }
    factory = (
        (lambda w: QtUiDispatcher(w))
        if args.dispatcher == "native"
        else (lambda w: TkPolicyQtDispatcher(w))
    )
    width, height = cc.parse_viewport(args.viewport)
    t0 = time.perf_counter()
    view = QtWorkspace(app, factory, count=args.rows)
    window, dispatcher = view.window, view.dispatcher
    window.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
    constructed = time.perf_counter()
    view.plumbing.publish(0)
    ready = view.wait_until(
        lambda: (view.history_model.rowCount(), view.queue_model.rowCount())
        == (args.rows, args.rows),
        10000,
    )
    populated = time.perf_counter()
    if width is None:
        window.showMaximized()
    else:
        window.resize(width, height)
        window.move(0, 0)
        window.show()
    deadline = time.perf_counter() + 10
    while time.perf_counter() < deadline and not (window.isVisible() and window.painted):
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()
    painted = time.perf_counter()
    handle = window.windowHandle()
    visible = bool(
        window.isVisible() and window.painted and handle is not None and handle.isExposed()
    )
    emit("first_visible", visible=visible, exposed=bool(handle is not None and handle.isExposed()))
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
    hwnd = int(window.winId())
    closed_state: dict = {}

    def on_close() -> None:
        closed_state["started_ns"] = time.perf_counter_ns()
        view.close()
        dispatcher.dispose()
        window.close()

    try:
        if args.mode == "matrix":
            cc.activate(hwnd)
            data["matrix"] = run_matrix(
                view,
                count=args.rows,
                viewport=(width, height),
                capture=cc.screen_capture,
                active_probe=lambda: cc.foreground_matches(hwnd),
            )
            if args.screenshot:
                state = view.window_state()
                dpr = state["device_pixel_ratio"]
                origin = window.mapToGlobal(QtCore.QPoint(0, 0))
                box = (
                    round(origin.x() * dpr),
                    round(origin.y() * dpr),
                    round(origin.x() * dpr) + round(state["client"][0] * dpr),
                    round(origin.y() * dpr) + round(state["client"][1] * dpr),
                )
                cc.screen_capture(box).save(args.screenshot)
        elif args.mode == "benchmark":
            data["benchmark"] = run_benchmark(view, build_info, memory, args.rows)
        else:
            view.flush()
            emit("inspect_ready", pid=os.getpid(), hwnd=hwnd)
            end = time.perf_counter() + 40
            while time.perf_counter() < end and not os.path.exists(args.hold_file):
                app.processEvents()
                time.sleep(0.02)
            checks["hold_released"] = os.path.exists(args.hold_file)
        data["build"] = build_info
        data["dpi"] = cc.dpi_record(
            hwnd,
            simulated_factor=None if args.sim_scale == 1.0 else args.sim_scale,
            requested=args.requested_dpi,
            toolkit_scale=window.devicePixelRatioF(),
        )
        data["screen"] = {"work_area": cc.work_area(), "foreground": cc.foreground_matches(hwnd)}
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
        app.processEvents()
        checks["pending_dropped_at_close"] = not marks and not view.late_mutations
        data["late"] = {"marks": marks, "view": list(view.late_mutations)}
        data["dispatcher_stats"] = {
            "delivered": getattr(dispatcher, "delivered", None),
            "canceled": getattr(dispatcher, "canceled", None),
            "peak_backlog": getattr(dispatcher, "peak_backlog", None),
            "errors": list(getattr(dispatcher, "errors", [])),
        }
        checks["dispatcher_closed"] = bool(dispatcher._closed)
        checks["dispatcher_no_errors"] = not getattr(dispatcher, "errors", [])
    except Exception:  # noqa: BLE001 - the bounded child reports failures instead of hanging
        errors.append(traceback.format_exc())
        try:
            on_close()
        except Exception:  # noqa: BLE001
            pass
    checks["tkinter_absent"] = "tkinter" not in sys.modules
    checks["optional_qt_modules_unused"] = not any(
        m.startswith(
            ("PySide6.QtWebEngine", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf")
        )
        for m in sys.modules
    )
    checks["no_python_worker_leak"] = not any(t.is_alive() for t in view._workers)
    app.quit()
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
