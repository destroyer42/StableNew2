"""Opt-in Qt child: one QApplication, synthetic data, no production composition."""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
import threading
import time
import traceback

from tools.qualification.gui_port_740.common import (
    emit,
    forbid_tk,
    import_probe,
    isolation_guard,
    memory,
    process_dpi_setup,
    rows,
    runtime,
    summary,
    window_dpi,
)


def run(args):
    forbid_tk()
    isolation_guard()
    process_dpi_setup()
    from PySide6 import QtCore, QtGui, QtWidgets

    from src.controller.ports.ui_dispatcher import UiDispatcher
    from src.gui.view_contracts.task_navigation_contract import all_tab_ids, get_destination
    from tools.qualification.gui_port_740.qt_dispatcher import QtUiDispatcher

    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    ui = threading.get_ident()
    checks = {}
    data = {
        "runtime": runtime(),
        "toolkit": "qt",
        "qt": QtCore.qVersion(),
        "pyside": importlib.metadata.version("PySide6"),
        "platform_plugin": app.platformName(),
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
    results = {}
    workers = []
    errors = []
    heartbeats = []
    last = [time.perf_counter()]
    heartbeat = QtCore.QTimer(app)
    heartbeat.setInterval(5)

    def beat():
        now = time.perf_counter()
        heartbeats.append((now - last[0]) * 1000)
        last[0] = now

    heartbeat.timeout.connect(beat)
    heartbeat.start()

    def safe(fn):
        def invoke():
            try:
                fn()
            except Exception:  # noqa: BLE001 - bounded child reports failures instead of hanging
                errors.append(traceback.format_exc())
                app.quit()

        return invoke

    class Shell(QtWidgets.QMainWindow):
        def __init__(self, on_paint=None):
            super().__init__()
            self.painted = False
            self.on_paint = on_paint
            self.dispatcher = None
            self.setWindowTitle("GUI-PORT-740 — synthetic read-only Qt proof")
            self.resize(1000, 650)
            body = QtWidgets.QWidget(self)
            self.setCentralWidget(body)
            layout = QtWidgets.QVBoxLayout(body)
            self.nav = QtWidgets.QComboBox(body)
            for tab_id in all_tab_ids():
                self.nav.addItem(get_destination(tab_id).display_label, tab_id)
            self.nav.setCurrentIndex(all_tab_ids().index("pipeline"))
            layout.addWidget(self.nav)
            self.status = QtWidgets.QLabel("Synthetic only: no application runtime", body)
            layout.addWidget(self.status)
            self.tables = []
            start = time.perf_counter()
            for title in ("Synthetic queue", "Synthetic history"):
                layout.addWidget(QtWidgets.QLabel(title, body))
                table = QtWidgets.QTableWidget(0, 3, body)
                table.setHorizontalHeaderLabels(["ID", "Status", "Summary"])
                table.setColumnWidth(0, 180)
                table.setColumnWidth(1, 140)
                table.horizontalHeader().setStretchLastSection(True)
                table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
                table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
                layout.addWidget(table)
                self.tables.append(table)
            self.project(0)
            self.populate_ms = (time.perf_counter() - start) * 1000
            self.nav.currentIndexChanged.connect(
                lambda _i: self.status.setText("Active: " + self.nav.currentData())
            )
            self.tables[0].itemSelectionChanged.connect(self.selection_status)
            self.tables[0].selectRow(min(50, args.rows - 1))

        def selection_status(self):
            row = self.tables[0].currentRow()
            if row >= 0:
                self.status.setText("Synthetic selection: " + self.tables[0].item(row, 0).text())

        def project(self, revision):
            for table in self.tables:
                selected = table.item(table.currentRow(), 0)
                selected = selected.text() if selected else None
                table.setRowCount(args.rows)
                for index, values in enumerate(rows(args.rows, revision)):
                    for column, value in enumerate(values):
                        table.setItem(index, column, QtWidgets.QTableWidgetItem(value))
                    if values[0] == selected:
                        table.selectRow(index)

        def paintEvent(self, event):
            super().paintEvent(event)
            if not self.painted:
                self.painted = True
                if self.on_paint:
                    QtCore.QTimer.singleShot(0, safe(self.on_paint))

        def closeEvent(self, event):
            if self.dispatcher is not None:
                self.dispatcher.dispose()
            super().closeEvent(event)

    shell = Shell()
    dispatcher: UiDispatcher = QtUiDispatcher(shell)
    shell.dispatcher = dispatcher
    state = None

    def lifecycle_tests():
        nonlocal state
        checks["imports_core_gui_widgets"] = all((QtCore, QtGui, QtWidgets))
        checks["qapplication_qwidget_qmainwindow"] = isinstance(
            shell.centralWidget(), QtWidgets.QWidget
        )
        checks["visible_painted"] = (
            shell.isVisible() and shell.painted and shell.windowHandle().isExposed()
        )
        checks["navigation"] = (
            len(all_tab_ids()) == 9 and get_destination("invalid-proof-id") is None
        )
        data["import_closures"] = {
            name: import_probe(name)
            for name in (
                "src.controller.ports.presentation_actions",
                "src.gui.app_state_v2",
                "src.gui.ui_tokens",
                "src.review.workflow_adapter",
                "src.state.content_visibility",
            )
        }
        marker = []
        dispatcher.run_on_ui_thread(lambda: marker.append(threading.get_ident()))
        checks["inline_ui_semantics"] = marker == [ui]
        dispatcher.schedule(lambda: marker.append("queued"))
        checks["schedule_ui_is_queued"] = marker == [ui]

        def fail():
            raise ValueError("intentional synthetic callback failure")

        dispatcher.schedule(fail)
        dispatcher.schedule(
            lambda: checks.update(callback_error_does_not_stop_pump=len(dispatcher.errors) == 1)
        )

        def worker():
            dispatcher.run_on_ui_thread(
                lambda: checks.update(worker_affinity=threading.get_ident() == ui)
            )
            dispatcher.invoke_later(
                30, lambda: checks.update(worker_delay_affinity=threading.get_ident() == ui)
            )

        thread = threading.Thread(target=worker, name="740-dispatch-test")
        workers.append(thread)
        thread.start()
        started = time.perf_counter()
        dispatcher.invoke_later(
            35, lambda: checks.update(delay_elapsed_ms=(time.perf_counter() - started) * 1000)
        )
        # Actual AppState, with Tk imports forbidden throughout this entire child.
        if data["import_closures"]["src.gui.app_state_v2"]["status"] == "PASS":
            from src.gui.app_state_v2 import AppStateV2

            state = AppStateV2()
            state.set_invoker(dispatcher)
            deliveries = []

            def listener():
                deliveries.append(threading.get_ident())

            state.subscribe("proof", listener)
            state.subscribe("queue_status", listener)

            def state_worker():
                state._notify("proof")
                state.set_queue_status("synthetic")

            thread = threading.Thread(target=state_worker, name="740-state-test")
            workers.append(thread)
            thread.start()

            def state_done():
                checks["actual_appstate_notifications"] = len(deliveries) == 2 and set(
                    deliveries
                ) == {ui}
                state.unsubscribe("proof", listener)
                state.unsubscribe("queue_status", listener)
                state._notify("proof")
                state.set_queue_status("synthetic-after-unsubscribe")
                checks["subscription_cleanup"] = not state._listeners
                state.disable_notifications()

            QtCore.QTimer.singleShot(160, safe(state_done))
        # Separate owners let destructive cases run without ending the shell.
        destroyed = []
        receiver = QtWidgets.QWidget(shell)
        owned = QtUiDispatcher(receiver)
        owned.invoke_later(300, lambda: destroyed.append("late mutation"))
        QtCore.QTimer.singleShot(
            20, lambda: checks.update(native_timer_pending_before_destruction=bool(owned._timers))
        )
        QtCore.QTimer.singleShot(40, receiver.deleteLater)
        direct = QtUiDispatcher(shell)
        direct._bridge.deleteLater()
        disposed = QtUiDispatcher(shell)
        disposed.schedule(lambda: destroyed.append("queued after dispose"))
        disposed.invoke_later(400, lambda: destroyed.append("timer after dispose"))
        disposed.dispose()
        disposed.dispose()
        # Submission and disposal from a worker are linearized against a running
        # callback, not merely against its earlier queue-admission check.
        concurrent = QtUiDispatcher(shell)
        active, finished, returned = threading.Event(), threading.Event(), threading.Event()

        def active_callback():
            active.set()
            time.sleep(0.02)
            finished.set()

        def concurrent_dispose():
            if not active.wait(2):
                return
            concurrent.dispose()
            checks["worker_dispose_waits_for_active_callback"] = finished.is_set()
            returned.set()
            concurrent.schedule(lambda: destroyed.append("late after worker disposal"))

        dispose_thread = threading.Thread(target=concurrent_dispose, name="740-concurrent-dispose")
        workers.append(dispose_thread)
        dispose_thread.start()
        concurrent.schedule(active_callback)
        thread = threading.Thread(
            target=lambda: (
                disposed.schedule(lambda: destroyed.append("worker late")),
                direct.schedule(lambda: destroyed.append("receiver late")),
            ),
            name="740-late-test",
        )

        def late():
            workers.append(thread)
            thread.start()

        QtCore.QTimer.singleShot(70, safe(late))

        def teardown_done():
            checks["concurrent_disposal_completed"] = returned.is_set()
            checks["dispose_destroyed_receiver_no_late_mutation"] = (
                not destroyed and disposed._closed and owned._closed and direct._closed
            )
            checks["delayed_not_early"] = checks.get("delay_elapsed_ms", 0) >= 30
            begin_burst()

        QtCore.QTimer.singleShot(460, safe(teardown_done))

    def begin_burst():
        data["idle_memory"] = memory()
        selection = shell.tables[0].item(shell.tables[0].currentRow(), 0).text()
        shell.project(1)
        checks["projection_add_remove_status_and_selection"] = (
            shell.tables[0].rowCount() == args.rows
            and shell.tables[0].item(shell.tables[0].currentRow(), 0).text() == selection
            and shell.tables[0].item(0, 0).text() == rows(args.rows, 1)[0][0]
        )
        latencies, delivered = [], []

        def worker():
            for index in range(args.burst):
                submitted = time.perf_counter()

                def update(index=index, submitted=submitted):
                    assert threading.get_ident() == ui
                    latencies.append((time.perf_counter() - submitted) * 1000)
                    delivered.append(index)
                    shell.status.setText(f"Synthetic update {index}; selection {selection}")
                    if len(delivered) == args.burst:
                        QtCore.QTimer.singleShot(30, safe(finish))

                dispatcher.schedule(update)

        thread = threading.Thread(target=worker, name="740-burst")
        workers.append(thread)
        thread.start()

        def finish():
            checks["burst_no_loss_duplicate_or_wrong_thread"] = len(set(delivered)) == args.burst
            data.update(
                latency_ms=summary(latencies),
                peak_backlog=dispatcher.peak_backlog,
                update_memory=memory(),
                populate_ms=shell.populate_ms,
                heartbeat_ms=summary(heartbeats),
                dpi=window_dpi(shell.winId()),
            )
            if args.screenshot:
                assert shell.grab().save(args.screenshot)
            # A second shell within the same interpreter is the explicit warm sample.
            warm_start = time.perf_counter()

            def warm_painted():
                data["warm_visible_rendered"] = warm.isVisible() and warm.windowHandle().isExposed()
                data["warm_shell_first_paint_ms"] = (time.perf_counter() - warm_start) * 1000
                warm.close()
                shutdown()

            warm = Shell(warm_painted)
            results["warm"] = warm
            warm.show()

    def shutdown():
        data["close_started_ns"] = time.perf_counter_ns()
        pending = []
        results["pending"] = pending
        dispatcher.invoke_later(1000, lambda: pending.append("late-on-exit"))
        dispatcher.schedule(lambda: pending.append("queued-on-exit"))

        def after_close_worker():
            dispatcher.schedule(lambda: pending.append("worker-during-shutdown"))

        # All variants intentionally cancel pending work; only owned synthetic objects.
        if args.close_mode == "delete":
            dispatcher.dispose()
            shell.deleteLater()
        elif args.close_mode == "quit":
            app.quit()
        else:
            shell.close()
            if args.close_mode == "repeat":
                shell.close()
        thread = threading.Thread(target=after_close_worker, name="740-shutdown-worker")
        workers.append(thread)
        thread.start()
        for thread in workers:
            thread.join(timeout=2)
        checks["no_python_worker_leak"] = not any(thread.is_alive() for thread in workers)
        checks["no_late_shutdown_mutation"] = not pending
        app.quit()

    def first_painted():
        data["startup_heartbeat_ms"] = summary(heartbeats) if heartbeats else None
        heartbeats.clear()
        last[0] = time.perf_counter()
        emit("first_visible", visible=shell.isVisible(), exposed=shell.windowHandle().isExposed())
        if args.mode == "contracts":
            lifecycle_tests()
        else:
            QtCore.QTimer.singleShot(150, safe(begin_burst))

    shell.on_paint = first_painted
    shell.show()
    QtCore.QTimer.singleShot(15000, lambda: (errors.append("internal timeout"), app.quit()))
    rc = app.exec()
    dispatcher.dispose()
    if state:
        state.disable_notifications()
    checks["event_loop_exit"] = rc == 0 and dispatcher._closed
    checks["callback_faults_accounted"] = len(dispatcher.errors) == int(args.mode == "contracts")
    checks["no_late_shutdown_mutation"] = not results.get("pending", [])
    checks["tkinter_absent"] = "tkinter" not in sys.modules
    checks["optional_qt_modules_unused"] = not any(
        name.startswith(
            ("PySide6.QtWebEngine", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf")
        )
        for name in sys.modules
    )
    bool_checks = {key: value for key, value in checks.items() if isinstance(value, bool)}
    emit(
        "result",
        status="PASS" if all(bool_checks.values()) and not errors else "FAIL",
        checks=checks,
        errors=errors,
        expected_callback_errors=dispatcher.errors,
        **data,
    )
    return 0 if all(bool_checks.values()) and not errors else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("contracts", "benchmark"), default="contracts")
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--burst", type=int, default=2000)
    parser.add_argument(
        "--close-mode", choices=("normal", "repeat", "quit", "delete"), default="normal"
    )
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    if not 64 <= args.rows <= 2000 or not 1 <= args.burst <= 3000:
        parser.error("bounded proof inputs required")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
