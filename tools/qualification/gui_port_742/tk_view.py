"""Tk rendering of the qualification workspace; a ``Driver`` over real ttk widgets. Never imported by Qt children."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from src.gui import design_system_v2 as ds
from src.gui.view_contracts.task_navigation_contract import TASK_GROUPS
from src.gui_v2.history_browser_model import STATUS_CHOICES, HistoryFilters
from tools.qualification.gui_port_742.model import (
    HISTORY_COLUMNS,
    QUEUE_COLUMNS,
    SELECTED_MARKER,
    Notice,
    WorkspaceModel,
    details_heading,
    history_cells,
    placeholder_body,
    placeholder_title,
    queue_cells,
)
from tools.qualification.gui_port_742.scenario import Observation
from tools.qualification.gui_port_742.wiring import Plumbing


class TkWorkspace:
    name = "tk"
    capabilities = frozenset({"keyboard", "geometry"})

    def __init__(
        self, master: tk.Misc, dispatcher: Any, *, count: int = 500, px_scale: float = 1.0
    ) -> None:
        self.master = master
        self.toplevel = master.winfo_toplevel()
        self.dispatcher = dispatcher
        self.count = count
        self.px_scale = px_scale
        self.model = WorkspaceModel()
        self.ui_thread = threading.get_ident()
        self.closed = False
        self.late_mutations: list[str] = []
        self.status_deliveries: list[tuple[int, int]] = []
        self.render_ms: dict[str, list[float]] = {"history": [], "queue": [], "status": []}
        self._cells: dict[str, dict[str, tuple[str, ...]]] = {"history": {}, "queue": {}}
        self._suppress = False
        self._workers: list[threading.Thread] = []
        self.names: dict[str, str] = {}
        self._build()
        self.plumbing = Plumbing(
            dispatcher,
            on_history=self._on_history,
            on_queue=self._on_queue,
            on_status=self._on_status,
            count=count,
        )

    # ------------------------------------------------------------------------------------------------ construction
    def px(self, value: int) -> int:
        return max(1, round(value * self.px_scale))

    def _register(self, name: str, widget: tk.Misc) -> tk.Misc:
        self.names[str(widget)] = name
        return widget

    def _table(self, parent: tk.Misc, name: str, columns: tuple[str, ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        widths = (self.px(150), self.px(90), self.px(140), self.px(420))
        for column, width in zip(columns, widths, strict=True):
            tree.heading(column, text=column)
            tree.column(column, width=width, minwidth=self.px(60), stretch=column == "Summary")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self._register(name, tree)
        setattr(self, f"_{name}_frame", frame)
        setattr(self, f"_{name}_bar", bar)
        return tree

    def _build(self) -> None:
        m = self.master
        pad = self.px(ds.Spacing.MD)
        m.grid_columnconfigure(1, weight=1)
        m.grid_rowconfigure(0, weight=1)
        # navigation -------------------------------------------------------------------------------------------
        self.nav = ttk.Treeview(m, show="tree", selectmode="browse", height=12)
        self.nav.column("#0", width=self.px(230), stretch=False)
        self.nav.tag_configure("group", font=(ds.Typography.FAMILY, ds.Typography.SM, "bold"))
        for group in TASK_GROUPS:
            self.nav.insert(
                "",
                "end",
                iid=f"group:{group.group_id}",
                text=group.label,
                open=True,
                tags=("group",),
            )
            for destination in group.destinations:
                self.nav.insert(
                    f"group:{group.group_id}",
                    "end",
                    iid=destination.tab_id,
                    text=destination.display_label,
                )
        self.nav.grid(row=0, column=0, sticky="ns", padx=(pad, 0), pady=pad)
        self._register("nav", self.nav)
        self.nav.bind("<<TreeviewSelect>>", self._on_nav_select)
        # content ---------------------------------------------------------------------------------------------
        content = ttk.Frame(m)
        content.grid(row=0, column=1, sticky="nsew", padx=pad, pady=pad)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.pipeline = ttk.Frame(content)
        self.placeholder = ttk.Frame(content)
        for page in (self.pipeline, self.placeholder):
            page.grid(row=0, column=0, sticky="nsew")
        self._build_pipeline(pad)
        self.placeholder_title = ttk.Label(self.placeholder, style=ds.HEADING_LABEL)
        self.placeholder_body = ttk.Label(
            self.placeholder, style=ds.BODY_LABEL, wraplength=self.px(640), justify="left"
        )
        self.placeholder_title.grid(row=0, column=0, sticky="w", pady=pad)
        self.placeholder_body.grid(row=1, column=0, sticky="w")
        self.status_line = ttk.Label(m, style=ds.MUTED_LABEL, anchor="w")
        self.status_line.grid(row=1, column=0, columnspan=2, sticky="ew", padx=pad, pady=(0, pad))
        self._register("status_line", self.status_line)
        self.placeholder.grid_remove()
        self.nav.selection_set("pipeline")
        self.render_status("Queue status: (none)")

    def _build_pipeline(self, pad: int) -> None:
        p = self.pipeline
        p.grid_columnconfigure(0, weight=1)
        bar = ttk.Frame(p)
        bar.grid(row=0, column=0, sticky="ew")
        self.search = ttk.Entry(bar, width=26)
        self.status_box = ttk.Combobox(bar, values=list(STATUS_CHOICES), state="readonly", width=11)
        self.status_box.set("Any")
        self.date_from = ttk.Entry(bar, width=12)
        self.date_to = ttk.Entry(bar, width=12)
        self.apply_button = ttk.Button(
            bar, text="Apply", style=ds.PRIMARY_BUTTON, command=self._apply_clicked
        )
        self.clear_button = ttk.Button(
            bar, text="Clear", style=ds.SECONDARY_BUTTON, command=self._clear_clicked
        )
        col = 0
        for label, widget, name in (
            ("Search", self.search, "search"),
            ("Status", self.status_box, "status"),
            ("From", self.date_from, "date_from"),
            ("To", self.date_to, "date_to"),
        ):
            ttk.Label(bar, text=label, style=ds.MUTED_LABEL).grid(
                row=0, column=col, padx=(0, self.px(4))
            )
            widget.grid(row=0, column=col + 1, padx=(0, pad))
            self._register(name, widget)
            col += 2
        self.apply_button.grid(row=0, column=col, padx=(0, self.px(4)))
        self.clear_button.grid(row=0, column=col + 1)
        self._register("apply", self.apply_button)
        self._register("clear", self.clear_button)
        # inline notice: the production notice styles carry the role word and tint
        self.notice_frame = ttk.Frame(p)
        self.notice_frame.grid(row=1, column=0, sticky="ew", pady=(self.px(6), self.px(6)))
        self.notice_frame.grid_columnconfigure(2, weight=1)
        self.notice_bar = ttk.Frame(self.notice_frame, width=self.px(4))
        self.notice_prefix = ttk.Label(self.notice_frame)
        self.notice_message = ttk.Label(self.notice_frame, wraplength=self.px(760), justify="left")
        self.notice_bar.grid(row=0, column=0, sticky="ns")
        self.notice_prefix.grid(row=0, column=1, padx=(self.px(8), self.px(6)))
        self.notice_message.grid(row=0, column=2, sticky="w")
        self._register("notice", self.notice_frame)
        # tables ----------------------------------------------------------------------------------------------
        ttk.Label(p, text="Queue", style=ds.HEADING_LABEL).grid(row=2, column=0, sticky="w")
        self.queue_tree = self._table(p, "queue_table", QUEUE_COLUMNS)
        self._queue_table_frame.grid(row=3, column=0, sticky="nsew")
        ttk.Label(p, text="History", style=ds.HEADING_LABEL).grid(row=4, column=0, sticky="w")
        self.history_tree = self._table(p, "history_table", HISTORY_COLUMNS)
        self._history_table_frame.grid(row=5, column=0, sticky="nsew")
        self.result_label = ttk.Label(p, style=ds.MUTED_LABEL, anchor="w")
        self.result_label.grid(row=6, column=0, sticky="ew")
        self._register("result_line", self.result_label)
        self.detail_heading = ttk.Label(p, style=ds.SUBHEADING_LABEL, anchor="w")
        self.detail_heading.grid(row=7, column=0, sticky="ew")
        self.details = tk.Text(
            p,
            height=7,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=1,
            background=ds.Colors.ELEVATED_SURFACE,
            foreground=ds.Colors.TEXT_PRIMARY,
            highlightthickness=2,
            highlightbackground=ds.Colors.BORDER,
            highlightcolor=ds.Colors.FOCUS_RING,
            takefocus=1,
            font=(ds.Typography.FAMILY, ds.Typography.SM),
        )
        # a read-only Text would otherwise swallow Tab; keep keyboard traversal out of it
        self.details.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
        self.details.grid(row=8, column=0, sticky="nsew")
        self._register("details", self.details)
        p.grid_rowconfigure(3, weight=2)
        p.grid_rowconfigure(5, weight=3)
        p.grid_rowconfigure(8, weight=1)
        for tree in (self.queue_tree, self.history_tree):
            tree.configure(height=4)
        self.history_tree.bind("<<TreeviewSelect>>", self._on_history_select)
        self.render_notice()
        self.render_details()

    # ------------------------------------------------------------------------------------------------ renderers
    def _timed(self, key: str, fn) -> None:
        started = time.perf_counter()
        fn()
        self.render_ms[key].append((time.perf_counter() - started) * 1000)

    def _fill(self, tree: ttk.Treeview, kind: str, rows: list[tuple[str, tuple[str, ...]]]) -> None:
        cache = self._cells[kind]
        ids = [iid for iid, _ in rows]
        if list(tree.get_children()) == ids:
            for iid, cells in rows:
                if cache.get(iid) != cells:
                    tree.item(iid, values=cells)
        else:
            tree.delete(*tree.get_children())
            for iid, cells in rows:
                tree.insert("", "end", iid=iid, values=cells)
        self._cells[kind] = dict(rows)

    def render_history(self) -> None:
        def go() -> None:
            sel = self.model.selected_id
            rows = [(e.job_id, history_cells(e, e.job_id == sel)) for e in self.model.visible]
            self._suppress = True
            try:
                self._fill(self.history_tree, "history", rows)
                if sel and self.history_tree.exists(sel):
                    self.history_tree.selection_set(sel)
                    self.history_tree.focus(
                        sel
                    )  # ttk arrow-key navigation starts from the focus item
                    self.history_tree.see(sel)
                else:
                    self.history_tree.selection_set(())
            finally:
                self._suppress = False
            self.render_result()

        self._timed("history", go)

    def render_queue(self) -> None:
        self._timed(
            "queue",
            lambda: self._fill(
                self.queue_tree, "queue", [(j.job_id, queue_cells(j)) for j in self.model.queue]
            ),
        )

    def render_result(self) -> None:
        self.result_label.configure(text=self.model.result_line)

    def render_details(self) -> None:
        entry = self.model.selected_entry()
        self.detail_heading.configure(text=details_heading(entry) if entry else "Details")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", self.model.details())
        self.details.configure(state="disabled")

    def render_notice(self) -> None:
        notice: Notice = self.model.notice
        names = ds.notice_style_names(notice.kind)
        self.notice_frame.configure(style=names.frame)
        self.notice_bar.configure(style=names.bar)
        self.notice_prefix.configure(style=names.prefix, text=notice.word)
        self.notice_message.configure(style=names.message, text=notice.text)

    def render_status(self, text: str) -> None:
        self.status_line.configure(text=text)

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
            text=self.search.get(),
            status_label=self.status_box.get(),
            date_from=self.date_from.get(),
            date_to=self.date_to.get(),
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

    def _on_history_select(self, _event: object = None) -> None:
        if self._suppress or not self._guard("select"):
            return
        picked = self.history_tree.selection()
        job = picked[0] if picked else None
        if job == self.model.selected_id:
            return
        previous = self.model.selected_id
        if not self.model.select(job):
            return
        for iid in (previous, job):  # only the two affected rows change their marker
            entry = next((e for e in self.model.visible if e.job_id == iid), None)
            if entry is not None and self.history_tree.exists(iid):
                cells = history_cells(entry, iid == job)
                self.history_tree.item(iid, values=cells)
                self._cells["history"][iid] = cells
        self.render_details()

    def _on_nav_select(self, _event: object = None) -> None:
        if self._suppress or not self._guard("nav"):
            return
        picked = self.nav.selection()
        if not picked:
            return
        iid = picked[0]
        if iid == self.model.tab_id:
            return  # ttk re-fires <<TreeviewSelect>> on every selection_set; an unchanged target is a no-op
        if iid.startswith("group:"):
            self.model.navigate_group(iid.split(":", 1)[1])
        else:
            self.model.navigate(iid)
        self._show_page()

    def _show_page(self) -> None:
        tab = self.model.tab_id
        if tab == "pipeline":
            self.placeholder.grid_remove()
            self.pipeline.grid()
        else:
            self.pipeline.grid_remove()
            self.placeholder.grid()
            self.placeholder_title.configure(text=placeholder_title(tab))
            self.placeholder_body.configure(text=placeholder_body(tab))
        if self.nav.selection() != (tab,):
            self.nav.selection_set(tab)

    # ------------------------------------------------------------------------------------------------ Driver
    def observe(self) -> Observation:
        pipeline_shown = bool(self.pipeline.winfo_ismapped())
        picked = self.nav.selection()
        leaves = tuple(
            self.nav.item(child, "text")
            for group in self.nav.get_children()
            for child in self.nav.get_children(group)
        )
        history_ids = self.history_tree.get_children()
        first_cells = (
            tuple(str(v) for v in self.history_tree.item(history_ids[0], "values"))
            if history_ids
            else ()
        )
        selected = self.history_tree.selection()
        markers = tuple(
            iid
            for iid in history_ids
            if str(self.history_tree.item(iid, "values")[0]).startswith(SELECTED_MARKER)
        )
        return Observation(
            tab_id=picked[0]
            if picked and not picked[0].startswith("group:")
            else self.model.tab_id,
            page_title="Pipeline" if pipeline_shown else self.placeholder_title.cget("text"),
            page_body="" if pipeline_shown else self.placeholder_body.cget("text"),
            nav_labels=leaves,
            queue_rows=len(self.queue_tree.get_children()),
            history_rows=len(history_ids),
            history_first=tuple(history_ids[:3]),
            history_first_cells=first_cells,
            selected_id=selected[0] if selected else None,
            marker_ids=markers,
            detail_heading=self.detail_heading.cget("text") if selected else "",
            detail_text=self.details.get("1.0", "end-1c"),
            notice_word=self.notice_prefix.cget("text"),
            notice_text=self.notice_message.cget("text"),
            result_line=self.result_label.cget("text"),
            status_line=self.status_line.cget("text"),
        )

    def first_history_id(self) -> str | None:
        ids = self.history_tree.get_children()
        return ids[0] if ids else None

    def navigate_group(self, group_id: str) -> bool:
        if not self.nav.exists(f"group:{group_id}"):
            return False
        self.nav.selection_set(f"group:{group_id}")
        self.toplevel.update()
        picked = (
            self.nav.selection()
        )  # the handler replaces the group row with its default destination
        return bool(picked) and picked != (f"group:{group_id}",)

    def navigate(self, tab_id: str) -> bool:
        if not self.nav.exists(tab_id) or tab_id.startswith("group:"):
            return False
        self.nav.selection_set(tab_id)
        self.toplevel.update()
        return self.model.tab_id == tab_id

    def set_filters(self, filters: HistoryFilters) -> None:
        for entry, value in (
            (self.search, filters.text),
            (self.date_from, filters.date_from),
            (self.date_to, filters.date_to),
        ):
            entry.delete(0, "end")
            entry.insert(0, value)
        self.status_box.set(filters.status_label)

    def apply_filters(self) -> None:
        self.apply_button.invoke()

    def clear_filters(self) -> None:
        self.set_filters(HistoryFilters())

    def select(self, job_id: str) -> bool:
        if not self.history_tree.exists(job_id):
            return False
        self.history_tree.selection_set(job_id)
        self.history_tree.focus(job_id)
        self.history_tree.see(job_id)
        self._on_history_select()
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
            self.toplevel.update()
            if predicate():
                return True
            time.sleep(0.002)
        self.toplevel.update()
        return bool(predicate())

    def flush(self) -> None:
        self.toplevel.update()

    def sink_metrics(self) -> dict[str, Any]:
        return self.plumbing.sink.get_metrics_snapshot()

    def _focus_name(self) -> str:
        widget = self.toplevel.focus_lastfor()
        return self.names.get(str(widget), "other:" + str(widget))

    def focus_first(self) -> str:
        self.nav.focus_force()
        self.toplevel.update()
        return self._focus_name()

    def press(self, key: str) -> str:
        widget = self.toplevel.focus_lastfor()
        widget.event_generate(f"<{key}>")
        self.toplevel.update()
        return self._focus_name()

    def row_visible(self, job_id: str) -> bool:
        return bool(self.history_tree.exists(job_id) and self.history_tree.bbox(job_id))

    def history_scrollbar_visible(self) -> bool:
        first, last = self.history_tree.yview()
        return bool(self._history_table_bar.winfo_ismapped()) and (first > 0.0 or last < 1.0)

    # ------------------------------------------------------------------------------------------------ geometry
    def set_viewport(self, width: int | None, height: int | None) -> tuple[int, int]:
        """Fixed client size, or maximized when ``width`` is None; returns the achieved client size."""

        if width is None:
            self.toplevel.state("zoomed")
        else:
            self.toplevel.state("normal")
            self.toplevel.geometry(f"{width}x{height}+0+0")
        self.toplevel.update()
        time.sleep(0.05)
        self.toplevel.update()
        return self.toplevel.winfo_width(), self.toplevel.winfo_height()

    def controls(self) -> dict[str, dict[str, Any]]:
        top = self.toplevel
        origin_x, origin_y = top.winfo_rootx(), top.winfo_rooty()
        face = tkfont.nametofont("TkDefaultFont")
        out: dict[str, dict[str, Any]] = {}
        for path, name in self.names.items():
            w = top.nametowidget(path)
            clipped = False
            if name in {"apply", "clear"}:
                clipped = (
                    face.measure(w.cget("text")) + self.px(2 * ds.Spacing.MD) > w.winfo_width()
                )
            elif name in {"result_line", "status_line"}:
                clipped = face.measure(w.cget("text")) > w.winfo_width() > 1
            elif name == "nav":
                width = int(w.column("#0", "width"))
                clipped = any(
                    face.measure(label) + self.px(48) > width for label in self.observe().nav_labels
                )
            elif name in {"history_table", "queue_table"}:
                clipped = any(
                    face.measure(str(w.heading(c, "text"))) + self.px(16)
                    > int(w.column(c, "width"))
                    for c in w["columns"]
                )
            out[name] = {
                "x": w.winfo_rootx() - origin_x,
                "y": w.winfo_rooty() - origin_y,
                "w": w.winfo_width(),
                "h": w.winfo_height(),
                "visible": bool(w.winfo_viewable()),
                "text_clipped": clipped,
            }
        return out

    def cell_discoverability(self) -> dict[str, Any]:
        face = tkfont.nametofont("TkDefaultFont")
        column = int(self.history_tree.column("Summary", "width"))
        widest = max((face.measure(c[3]) for c in self._cells["history"].values()), default=0)
        return {
            "summary_cells_wider_than_column": widest > column,
            "native_tooltip": False,
            "full_text_reachable_via_details": True,
        }

    def window_state(self) -> dict[str, Any]:
        top = self.toplevel
        return {
            "client": [top.winfo_width(), top.winfo_height()],
            "root": [top.winfo_rootx(), top.winfo_rooty()],
            "screen": [top.winfo_screenwidth(), top.winfo_screenheight()],
            "hwnd": top.winfo_id(),
            "tk_scaling": float(top.tk.call("tk", "scaling")),
            "state": top.state(),
        }

    def widget_rect(self, name: str) -> tuple[int, int, int, int]:
        path = next(p for p, n in self.names.items() if n == name)
        w = self.toplevel.nametowidget(path)
        return w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()

    def focus_to(self, name: str) -> None:
        path = next(p for p, n in self.names.items() if n == name)
        self.toplevel.nametowidget(path).focus_force()
        self.toplevel.update()

    def focused_name(self) -> str:
        return self._focus_name()

    def backlog(self) -> int:
        invoker = getattr(self.dispatcher, "_invoker", None)
        if invoker is None:
            return 0
        with invoker._lock:
            return len(invoker._pending)

    def start_heartbeat(self, interval_ms: int = 5) -> None:
        # A token per run: a still-pending ``after`` from a stopped run must never feed (or extend) the next run.
        self._gaps: list[float] = []
        self._beat_token = token = object()
        self._last = time.perf_counter()
        deadline = [self._last]

        def beat() -> None:
            if self._beat_token is not token:
                return
            now = time.perf_counter()
            self._gaps.append((now - self._last) * 1000)
            self._last = now
            # deadline-compensated like a repeating QTimer: lateness is not added to every later interval
            deadline[0] += interval_ms / 1000
            if deadline[0] < now:
                deadline[0] = now
            self.toplevel.after(max(1, round((deadline[0] - now) * 1000)), beat)

        self.toplevel.after(interval_ms, beat)

    def stop_heartbeat(self) -> list[float]:
        self._beat_token = None
        return self._gaps

    def second_window(self, count: int) -> dict[str, Any]:
        """Same-process construction of a second full workspace, verified mapped before it is timed."""

        from tools.qualification.gui_port_742.fixture import history_entries, queue_summaries

        started = time.perf_counter()
        top = tk.Toplevel(self.toplevel)
        top.geometry("1000x650")
        second = TkWorkspace(top, self.dispatcher, count=count, px_scale=self.px_scale)
        second.populate_direct(history_entries(count, 0), queue_summaries(count, 0))
        constructed = time.perf_counter()
        deadline = constructed + 5
        while time.perf_counter() < deadline and not (
            top.winfo_ismapped() and top.winfo_viewable()
        ):
            top.update()
            time.sleep(0.002)
        top.update_idletasks()
        mapped = bool(top.winfo_ismapped() and top.winfo_viewable())
        painted = time.perf_counter()
        rows = second.observe_rows()
        second.close()
        top.destroy()
        return {
            "construct_ms": (constructed - started) * 1000,
            "to_painted_ms": (painted - started) * 1000,
            "rendered": mapped and rows == (count, count),
        }

    def observe_rows(self) -> tuple[int, int]:
        return len(self.history_tree.get_children()), len(self.queue_tree.get_children())

    def accessibility(self) -> dict[str, Any]:
        return {
            "in_process_api": None,
            "note": "Tk exposes no per-widget accessibility objects; see the external UI Automation inspection",
        }

    # ------------------------------------------------------------------------------------------------ lifecycle
    def populate_direct(self, history, queue) -> None:
        """Synchronous population used for construction timing (bypasses the 75 ms notification window)."""

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
