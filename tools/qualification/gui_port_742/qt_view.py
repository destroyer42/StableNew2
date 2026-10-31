"""PySide6 rendering of the qualification workspace; a ``Driver`` over real widgets. Never imported by the Tk child."""

from __future__ import annotations

import threading
import time
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from src.gui.view_contracts.task_navigation_contract import TASK_GROUPS
from src.gui_v2.design_values import Typography
from src.gui_v2.history_browser_model import STATUS_CHOICES, HistoryFilters
from tools.qualification.gui_port_742.model import (
    HISTORY_COLUMNS,
    QUEUE_COLUMNS,
    SELECTED_MARKER,
    WorkspaceModel,
    details_heading,
    history_cells,
    placeholder_body,
    placeholder_title,
    queue_cells,
)
from tools.qualification.gui_port_742.scenario import Observation
from tools.qualification.gui_port_742.wiring import Plumbing

_KEYS = {"Tab": Qt.Key.Key_Tab, "Down": Qt.Key.Key_Down, "Up": Qt.Key.Key_Up}


class RowsModel(QtCore.QAbstractTableModel):
    """Read-only rows of (id, cells); the full cell text is also the tooltip so elision is discoverable."""

    def __init__(self, columns: tuple[str, ...], parent=None) -> None:
        super().__init__(parent)
        self.columns = columns
        self.rows: list[tuple[str, tuple[str, ...]]] = []
        self.index_of: dict[str, int] = {}

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        text = self.rows[index.row()][1][index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return text
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section]
        return None

    def reset_rows(self, rows: list[tuple[str, tuple[str, ...]]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.index_of = {iid: i for i, (iid, _c) in enumerate(rows)}
        self.endResetModel()

    def set_cells(self, row: int, cells: tuple[str, ...]) -> None:
        self.rows[row] = (self.rows[row][0], cells)
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.columns) - 1))


class Shell(QtWidgets.QMainWindow):
    """Main window that records when it has actually painted (never a timestamp for an unmapped window)."""

    def __init__(self) -> None:
        super().__init__()
        self.painted = False

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        self.painted = True


class QtWorkspace:
    name = "qt"
    capabilities = frozenset({"keyboard", "geometry"})

    def __init__(
        self, app, dispatcher_factory, *, count: int = 500, owner: str = "primary"
    ) -> None:
        self.app = app
        self.count = count
        self.model = WorkspaceModel()
        self.ui_thread = threading.get_ident()
        self.closed = False
        self.late_mutations: list[str] = []
        self.status_deliveries: list[tuple[int, int]] = []
        self.render_ms: dict[str, list[float]] = {"history": [], "queue": [], "status": []}
        self._cells: dict[str, dict[str, tuple[str, ...]]] = {"history": {}, "queue": {}}
        self._suppress = False
        self._workers: list[threading.Thread] = []
        self.named: dict[str, QtWidgets.QWidget] = {}
        self.window = Shell()
        self.window.setWindowTitle(
            f"GUI-PORT-742 — Qt qualification workspace ({owner}, read-only)"
        )
        self._build()
        self.dispatcher = dispatcher_factory(self.window)
        self.plumbing = Plumbing(
            self.dispatcher,
            on_history=self._on_history,
            on_queue=self._on_queue,
            on_status=self._on_status,
            count=count,
        )

    # ------------------------------------------------------------------------------------------------ construction
    def _name(
        self, name: str, widget: QtWidgets.QWidget, accessible: str | None = None
    ) -> QtWidgets.QWidget:
        self.named[name] = widget
        widget.setObjectName(name)
        widget.setAccessibleName(accessible or name.replace("_", " ").title())
        return widget

    def _table(self, name: str, columns: tuple[str, ...]) -> tuple[QtWidgets.QTableView, RowsModel]:
        view = QtWidgets.QTableView()
        model = RowsModel(columns, view)
        view.setModel(model)
        view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        view.setWordWrap(False)
        view.setTabKeyNavigation(
            False
        )  # QTableView otherwise walks cells with Tab and traps keyboard traversal
        view.verticalHeader().hide()
        view.verticalHeader().setDefaultSectionSize(24)
        view.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
        header = view.horizontalHeader()
        header.setStretchLastSection(True)
        for column, width in enumerate((150, 90, 140, 420)):
            view.setColumnWidth(column, width)
        view.setMinimumHeight(70)
        self._name(name, view, name.replace("_", " ").title())
        return view, model

    def _build(self) -> None:
        body = QtWidgets.QWidget()
        self.window.setCentralWidget(body)
        outer = QtWidgets.QVBoxLayout(body)
        outer.setContentsMargins(8, 8, 8, 8)
        row = QtWidgets.QHBoxLayout()
        outer.addLayout(row, 1)
        self.nav = QtWidgets.QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setFixedWidth(230)
        self.nav.setIndentation(18)
        bold = QtGui.QFont(Typography.FAMILY, Typography.SM)
        bold.setBold(True)
        for group in TASK_GROUPS:
            top = QtWidgets.QTreeWidgetItem([group.label])
            top.setData(0, Qt.ItemDataRole.UserRole, f"group:{group.group_id}")
            top.setFont(0, bold)
            self.nav.addTopLevelItem(top)
            for destination in group.destinations:
                leaf = QtWidgets.QTreeWidgetItem([destination.display_label])
                leaf.setData(0, Qt.ItemDataRole.UserRole, destination.tab_id)
                top.addChild(leaf)
            top.setExpanded(True)
        self._name("nav", self.nav, "Task navigation")
        row.addWidget(self.nav)
        self.stack = QtWidgets.QStackedWidget()
        row.addWidget(self.stack, 1)
        self.pipeline = QtWidgets.QWidget()
        self.placeholder = QtWidgets.QWidget()
        self.stack.addWidget(self.pipeline)
        self.stack.addWidget(self.placeholder)
        self._build_pipeline()
        ph = QtWidgets.QVBoxLayout(self.placeholder)
        self.placeholder_title = QtWidgets.QLabel()
        self.placeholder_title.setProperty("heading", True)
        self.placeholder_body = QtWidgets.QLabel()
        self.placeholder_body.setWordWrap(True)
        ph.addWidget(self.placeholder_title)
        ph.addWidget(self.placeholder_body)
        ph.addStretch(1)
        self.status_line = QtWidgets.QLabel()
        self.status_line.setProperty("muted", True)
        self._name("status_line", self.status_line, "Queue status")
        outer.addWidget(self.status_line)
        self.nav.currentItemChanged.connect(self._on_nav_changed)
        self.nav.setCurrentItem(self._leaf("pipeline"))
        self.render_status("Queue status: (none)")

    def _leaf(self, tab_id: str) -> QtWidgets.QTreeWidgetItem | None:
        for g in range(self.nav.topLevelItemCount()):
            top = self.nav.topLevelItem(g)
            if top.data(0, Qt.ItemDataRole.UserRole) == tab_id:
                return top
            for c in range(top.childCount()):
                if top.child(c).data(0, Qt.ItemDataRole.UserRole) == tab_id:
                    return top.child(c)
        return None

    def _build_pipeline(self) -> None:
        lay = QtWidgets.QVBoxLayout(self.pipeline)
        lay.setContentsMargins(8, 0, 0, 0)
        bar = QtWidgets.QHBoxLayout()
        lay.addLayout(bar)
        self.search = QtWidgets.QLineEdit()
        self.search.setMinimumWidth(220)
        self.status_box = QtWidgets.QComboBox()
        self.status_box.addItems(list(STATUS_CHOICES))
        self.date_from = QtWidgets.QLineEdit()
        self.date_to = QtWidgets.QLineEdit()
        for edit in (self.date_from, self.date_to):
            edit.setFixedWidth(110)
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setProperty("primary", True)
        self.clear_button = QtWidgets.QPushButton("Clear")
        for label, widget, name in (
            ("Search", self.search, "search"),
            ("Status", self.status_box, "status"),
            ("From", self.date_from, "date_from"),
            ("To", self.date_to, "date_to"),
        ):
            caption = QtWidgets.QLabel(label)
            caption.setProperty("muted", True)
            bar.addWidget(caption)
            bar.addWidget(widget)
            self._name(name, widget)
        bar.addWidget(self.apply_button)
        bar.addWidget(self.clear_button)
        bar.addStretch(1)
        self.apply_button.clicked.connect(self._apply_clicked)
        self.clear_button.clicked.connect(self._clear_clicked)
        self._name("apply", self.apply_button, "Apply filters")
        self._name("clear", self.clear_button, "Clear filters")
        self.notice_box = QtWidgets.QWidget()
        nl = QtWidgets.QHBoxLayout(self.notice_box)
        nl.setContentsMargins(0, 4, 0, 4)
        self.notice_prefix = QtWidgets.QLabel()
        self.notice_prefix.setStyleSheet("font-weight: bold;")
        self.notice_message = QtWidgets.QLabel()
        self.notice_message.setWordWrap(True)
        nl.addWidget(self.notice_prefix)
        nl.addWidget(self.notice_message, 1)
        self._name("notice", self.notice_box, "Notice")
        lay.addWidget(self.notice_box)
        head = QtWidgets.QLabel("Queue")
        head.setProperty("heading", True)
        lay.addWidget(head)
        self.queue_view, self.queue_model = self._table("queue_table", QUEUE_COLUMNS)
        lay.addWidget(self.queue_view, 2)
        head = QtWidgets.QLabel("History")
        head.setProperty("heading", True)
        lay.addWidget(head)
        self.history_view, self.history_model = self._table("history_table", HISTORY_COLUMNS)
        lay.addWidget(self.history_view, 3)
        self.result_label = QtWidgets.QLabel()
        self.result_label.setProperty("muted", True)
        self._name("result_line", self.result_label, "Result summary")
        lay.addWidget(self.result_label)
        self.detail_heading = QtWidgets.QLabel()
        self.detail_heading.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.detail_heading)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setTabChangesFocus(True)
        self.details.setMinimumHeight(
            8 * QtGui.QFontMetrics(self.details.font()).lineSpacing() + 12
        )
        self._name("details", self.details, "Job details")
        lay.addWidget(self.details, 1)
        self.history_view.selectionModel().selectionChanged.connect(self._on_history_select)
        self.render_notice()
        self.render_details()

    # ------------------------------------------------------------------------------------------------ renderers
    def _timed(self, key: str, fn) -> None:
        started = time.perf_counter()
        fn()
        self.render_ms[key].append((time.perf_counter() - started) * 1000)

    def _fill(self, model: RowsModel, kind: str, rows: list[tuple[str, tuple[str, ...]]]) -> None:
        cache = self._cells[kind]
        if [iid for iid, _ in model.rows] == [iid for iid, _ in rows]:
            for i, (iid, cells) in enumerate(rows):
                if cache.get(iid) != cells:
                    model.set_cells(i, cells)
        else:
            model.reset_rows(rows)
        self._cells[kind] = dict(rows)

    def render_history(self) -> None:
        def go() -> None:
            sel = self.model.selected_id
            rows = [(e.job_id, history_cells(e, e.job_id == sel)) for e in self.model.visible]
            self._suppress = True
            try:
                self._fill(self.history_model, "history", rows)
                row = self.history_model.index_of.get(sel) if sel else None
                if row is not None:
                    index = self.history_model.index(row, 0)
                    self.history_view.setCurrentIndex(index)
                    self.history_view.scrollTo(index)
                else:
                    self.history_view.clearSelection()
            finally:
                self._suppress = False
            self.render_result()

        self._timed("history", go)

    def render_queue(self) -> None:
        self._timed(
            "queue",
            lambda: self._fill(
                self.queue_model, "queue", [(j.job_id, queue_cells(j)) for j in self.model.queue]
            ),
        )

    def render_result(self) -> None:
        self.result_label.setText(self.model.result_line)

    def render_details(self) -> None:
        entry = self.model.selected_entry()
        self.detail_heading.setText(details_heading(entry) if entry else "Details")
        self.details.setPlainText(self.model.details())

    def render_notice(self) -> None:
        notice = self.model.notice
        for label in (self.notice_prefix, self.notice_message):
            label.setProperty("noticeKind", notice.kind)
            label.style().unpolish(label)
            label.style().polish(label)
        self.notice_prefix.setText(notice.word)
        self.notice_message.setText(notice.text)

    def render_status(self, text: str) -> None:
        self.status_line.setText(text)

    def _guard(self, label: str) -> bool:
        if self.closed:
            self.late_mutations.append(label)
            return False
        return True

    # ------------------------------------------------------------------------------------------------ callbacks
    def _on_history(self) -> None:
        if not self._guard("history"):
            return
        self.model.set_projection(tuple(self.plumbing.state.history_items), self.model.queue)
        self.render_history()
        self.render_details()
        self.render_notice()

    def _on_queue(self) -> None:
        if not self._guard("queue"):
            return
        self.model.queue = tuple(self.plumbing.state.queue_jobs)
        self.render_queue()

    def _on_status(self) -> None:
        if not self._guard("status"):
            return
        value = self.plumbing.state.queue_status
        self._timed("status", lambda: self.render_status(f"Queue status: {value}"))
        self.status_deliveries.append(
            (int(value.rsplit("-", 1)[1]), 1 if threading.get_ident() == self.ui_thread else 0)
        )

    def _filters(self) -> HistoryFilters:
        return HistoryFilters(
            text=self.search.text(),
            status_label=self.status_box.currentText(),
            date_from=self.date_from.text(),
            date_to=self.date_to.text(),
        )

    def _apply_clicked(self) -> None:
        if not self._guard("apply"):
            return
        self.model.apply_filters(self._filters())
        self.render_history()
        self.render_details()
        self.render_notice()

    def _clear_clicked(self) -> None:
        self.clear_filters()
        self._apply_clicked()

    def _selected_row_id(self) -> str | None:
        rows = self.history_view.selectionModel().selectedRows()
        return self.history_model.rows[rows[0].row()][0] if rows else None

    def _on_history_select(self, *_args) -> None:
        if self._suppress or not self._guard("select"):
            return
        job = self._selected_row_id()
        if job == self.model.selected_id:
            return
        previous = self.model.selected_id
        if not self.model.select(job):
            return
        for iid in (previous, job):
            entry = next((e for e in self.model.visible if e.job_id == iid), None)
            row = self.history_model.index_of.get(iid) if iid else None
            if entry is not None and row is not None:
                cells = history_cells(entry, iid == job)
                self.history_model.set_cells(row, cells)
                self._cells["history"][iid] = cells
        self.render_details()

    def _on_nav_changed(self, current, _previous) -> None:
        if self._suppress or current is None or not self._guard("nav"):
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key == self.model.tab_id:
            return
        if key.startswith("group:"):
            self.model.navigate_group(key.split(":", 1)[1])
        else:
            self.model.navigate(key)
        self._show_page()

    def _show_page(self) -> None:
        tab = self.model.tab_id
        if tab == "pipeline":
            self.stack.setCurrentWidget(self.pipeline)
        else:
            self.placeholder_title.setText(placeholder_title(tab))
            self.placeholder_body.setText(placeholder_body(tab))
            self.stack.setCurrentWidget(self.placeholder)
        leaf = self._leaf(tab)
        if leaf is not None and self.nav.currentItem() is not leaf:
            self.nav.setCurrentItem(leaf)

    # ------------------------------------------------------------------------------------------------ Driver
    def observe(self) -> Observation:
        pipeline_shown = self.stack.currentWidget() is self.pipeline
        current = self.nav.currentItem()
        key = current.data(0, Qt.ItemDataRole.UserRole) if current else self.model.tab_id
        leaves = tuple(
            self.nav.topLevelItem(g).child(c).text(0)
            for g in range(self.nav.topLevelItemCount())
            for c in range(self.nav.topLevelItem(g).childCount())
        )
        rows = self.history_model.rows
        selected = self._selected_row_id()
        return Observation(
            tab_id=self.model.tab_id if str(key).startswith("group:") else key,
            page_title="Pipeline" if pipeline_shown else self.placeholder_title.text(),
            page_body="" if pipeline_shown else self.placeholder_body.text(),
            nav_labels=leaves,
            queue_rows=self.queue_model.rowCount(),
            history_rows=self.history_model.rowCount(),
            history_first=tuple(iid for iid, _ in rows[:3]),
            history_first_cells=tuple(rows[0][1]) if rows else (),
            selected_id=selected,
            marker_ids=tuple(iid for iid, cells in rows if cells[0].startswith(SELECTED_MARKER)),
            detail_heading=self.detail_heading.text() if selected else "",
            detail_text=self.details.toPlainText(),
            notice_word=self.notice_prefix.text(),
            notice_text=self.notice_message.text(),
            result_line=self.result_label.text(),
            status_line=self.status_line.text(),
        )

    def navigate_group(self, group_id: str) -> bool:
        item = self._leaf(f"group:{group_id}")
        if item is None:
            return False
        self.nav.setCurrentItem(item)
        self.app.processEvents()
        current = self.nav.currentItem()
        return (
            current is not None and current.data(0, Qt.ItemDataRole.UserRole) != f"group:{group_id}"
        )

    def navigate(self, tab_id: str) -> bool:
        item = self._leaf(tab_id)
        if item is None or tab_id.startswith("group:"):
            return False
        self.nav.setCurrentItem(item)
        self.app.processEvents()
        return self.model.tab_id == tab_id

    def set_filters(self, filters: HistoryFilters) -> None:
        self.search.setText(filters.text)
        self.date_from.setText(filters.date_from)
        self.date_to.setText(filters.date_to)
        self.status_box.setCurrentText(filters.status_label)

    def apply_filters(self) -> None:
        self.apply_button.click()

    def clear_filters(self) -> None:
        self.set_filters(HistoryFilters())

    def select(self, job_id: str) -> bool:
        row = self.history_model.index_of.get(job_id)
        if row is None:
            return False
        index = self.history_model.index(row, 0)
        self.history_view.setCurrentIndex(index)
        self.history_view.scrollTo(index)
        return True

    def _spawn(self, name: str, target) -> threading.Thread:
        thread = threading.Thread(target=target, name=name)
        self._workers.append(thread)
        thread.start()
        return thread

    def publish_from_worker(
        self, data_revision: int, *, drop: frozenset[str], sink_revision: int
    ) -> None:
        self._spawn(
            "742-publish",
            lambda: self.plumbing.publish(data_revision, drop=drop, sink_revision=sink_revision),
        )

    def stream_status_from_worker(
        self, count: int, *, first_revision: int
    ) -> list[tuple[int, int]]:
        def work() -> None:
            for index in range(count):
                self.plumbing.publish_status(index, revision=first_revision + index)
                time.sleep(0.004)

        self._spawn("742-status", work)
        return self.status_deliveries

    def wait_until(self, predicate, timeout_ms: int) -> bool:
        end = time.perf_counter() + timeout_ms / 1000
        while time.perf_counter() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.002)
        self.app.processEvents()
        return bool(predicate())

    def flush(self) -> None:
        """Drain pending events and coalesced paint requests (dirty regions only), like Tk's ``update()``."""

        self.app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.UpdateRequest.value)

    def sink_metrics(self) -> dict[str, Any]:
        return self.plumbing.sink.get_metrics_snapshot()

    def focused_name(self) -> str:
        focus = self.app.focusWidget()
        for name, widget in self.named.items():
            if widget is focus:
                return name
        return "other:" + (type(focus).__name__ if focus is not None else "none")

    def focus_first(self) -> str:
        self.nav.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        return self.focused_name()

    def press(self, key: str) -> str:
        target = self.app.focusWidget() or self.window
        code = _KEYS[key]
        for kind in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease):
            self.app.sendEvent(target, QtGui.QKeyEvent(kind, code, Qt.KeyboardModifier.NoModifier))
        self.app.processEvents()
        return self.focused_name()

    def row_visible(self, job_id: str) -> bool:
        row = self.history_model.index_of.get(job_id)
        if row is None:
            return False
        rect = self.history_view.visualRect(self.history_model.index(row, 0))
        return bool(rect.isValid() and self.history_view.viewport().rect().contains(rect))

    def history_scrollbar_visible(self) -> bool:
        bar = self.history_view.verticalScrollBar()
        return bool(bar.isVisible() and bar.maximum() > 0)

    # ------------------------------------------------------------------------------------------------ geometry
    def set_viewport(self, width: int | None, height: int | None) -> tuple[int, int]:
        if width is None:
            self.window.showMaximized()
        else:
            self.window.showNormal()
            self.window.resize(width, height)
            self.window.move(0, 0)
        self.app.processEvents()
        time.sleep(0.05)
        self.app.processEvents()
        return self.window.width(), self.window.height()

    def controls(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, widget in self.named.items():
            origin = widget.mapTo(self.window, QtCore.QPoint(0, 0))
            metrics = QtGui.QFontMetrics(widget.font())
            clipped = False
            if name in {"apply", "clear"}:
                clipped = metrics.horizontalAdvance(widget.text()) + 16 > widget.width()
            elif name in {"result_line", "status_line"}:
                clipped = metrics.horizontalAdvance(widget.text()) > widget.width() > 1
            elif name == "nav":
                clipped = any(
                    metrics.horizontalAdvance(label) + 48 > widget.viewport().width()
                    for label in self.observe().nav_labels
                )
            elif name in {"history_table", "queue_table"}:
                header = widget.horizontalHeader()
                clipped = any(
                    metrics.horizontalAdvance(
                        str(widget.model().headerData(i, Qt.Orientation.Horizontal))
                    )
                    + 16
                    > header.sectionSize(i)
                    for i in range(widget.model().columnCount())
                )
            out[name] = {
                "x": origin.x(),
                "y": origin.y(),
                "w": widget.width(),
                "h": widget.height(),
                "visible": widget.isVisible(),
                "text_clipped": clipped,
            }
        return out

    def cell_discoverability(self) -> dict[str, Any]:
        metrics = QtGui.QFontMetrics(self.history_view.font())
        column = self.history_view.columnWidth(3)
        widest = max(
            (metrics.horizontalAdvance(c[3]) for c in self._cells["history"].values()), default=0
        )
        sample = self.history_model.index(0, 3)
        tooltip_full = (
            bool(self.history_model.rows)
            and self.history_model.data(sample, Qt.ItemDataRole.ToolTipRole)
            == self.history_model.rows[0][1][3]
        )
        return {
            "summary_cells_wider_than_column": widest > column,
            "native_tooltip": bool(tooltip_full),
            "full_text_reachable_via_details": True,
        }

    def window_state(self) -> dict[str, Any]:
        window, screen = self.window, self.window.screen()
        return {
            "client": [window.width(), window.height()],
            "root": [window.x(), window.y()],
            "screen": [screen.size().width(), screen.size().height()],
            "hwnd": int(window.winId()),
            "device_pixel_ratio": window.devicePixelRatioF(),
            "screen_dpr": screen.devicePixelRatio(),
            "logical_dpi": screen.logicalDotsPerInch(),
            "state": "maximized" if window.isMaximized() else "normal",
        }

    def widget_rect(self, name: str) -> tuple[int, int, int, int]:
        widget = self.named[name]
        dpr = self.window.devicePixelRatioF()
        origin = widget.mapToGlobal(QtCore.QPoint(0, 0))
        return (
            round(origin.x() * dpr),
            round(origin.y() * dpr),
            round(widget.width() * dpr),
            round(widget.height() * dpr),
        )

    def focus_to(self, name: str) -> None:
        self.named[name].setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()

    # ------------------------------------------------------------------------------------------------ misc
    def backlog(self) -> int:
        return len(getattr(self.dispatcher, "_pending", ()))

    def start_heartbeat(self, interval_ms: int = 5) -> None:
        self._gaps: list[float] = []
        self._last = time.perf_counter()
        self._hb = QtCore.QTimer(self.window)
        self._hb.setInterval(interval_ms)

        def beat() -> None:
            now = time.perf_counter()
            self._gaps.append((now - self._last) * 1000)
            self._last = now

        self._hb.timeout.connect(beat)
        self._hb.start()

    def stop_heartbeat(self) -> list[float]:
        self._hb.stop()
        return self._gaps

    def second_window(self, count: int) -> dict[str, Any]:
        from tools.qualification.gui_port_742.fixture import history_entries, queue_summaries

        started = time.perf_counter()
        second = QtWorkspace(
            self.app, lambda w: _SameDispatcher(self.dispatcher), count=count, owner="second"
        )
        second.populate_direct(history_entries(count, 0), queue_summaries(count, 0))
        constructed = time.perf_counter()
        second.window.resize(1000, 650)
        second.window.show()
        deadline = constructed + 5
        while time.perf_counter() < deadline and not (
            second.window.isVisible() and second.window.painted
        ):
            self.app.processEvents()
            time.sleep(0.002)
        handle = second.window.windowHandle()
        rendered = bool(
            second.window.isVisible()
            and second.window.painted
            and handle is not None
            and handle.isExposed()
        )
        painted = time.perf_counter()
        rows = (second.history_model.rowCount(), second.queue_model.rowCount())
        second.close()
        second.window.close()
        second.window.deleteLater()
        self.app.processEvents()
        return {
            "construct_ms": (constructed - started) * 1000,
            "to_painted_ms": (painted - started) * 1000,
            "rendered": rendered and rows == (count, count),
        }

    def accessibility(self) -> dict[str, Any]:
        """In-process QAccessible evidence only; this is not a screen-reader or UI Automation client test."""

        report: dict[str, Any] = {"in_process_api": "QAccessible", "widgets": {}}
        for name, widget in self.named.items():
            iface = QtGui.QAccessible.queryAccessibleInterface(widget)
            if iface is None:
                report["widgets"][name] = None
                continue
            report["widgets"][name] = {
                "role": str(iface.role()).split(".")[-1],
                "name": iface.text(QtGui.QAccessible.Text.Name),
                "focusable": bool(iface.state().focusable),
            }
        report["named_widgets"] = sum(1 for v in report["widgets"].values() if v and v["name"])
        report["total_widgets"] = len(report["widgets"])
        return report

    def populate_direct(self, history, queue) -> None:
        self.model.set_projection(tuple(history), tuple(queue))
        self.render_history()
        self.render_queue()
        self.render_details()
        self.render_notice()

    def close(self) -> None:
        self.closed = True
        self.plumbing.close()
        for thread in self._workers:
            thread.join(timeout=2)


class _SameDispatcher:
    """Lets the second window share the primary window's dispatcher without owning (or disposing) it."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def schedule(self, fn) -> None:
        self._inner.schedule(fn)

    def invoke_later(self, delay_ms, fn) -> None:
        self._inner.invoke_later(delay_ms, fn)

    def run_on_ui_thread(self, fn) -> None:
        self._inner.run_on_ui_thread(fn)
