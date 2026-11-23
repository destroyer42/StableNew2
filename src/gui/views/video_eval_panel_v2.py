"""Video Workflow tab: queue an eval suite and build its contact sheet (PR-VID-EVAL-320).

Intent capture only. Loading the suite, building NJRs, admission and measuring clips all run in the
Video Workflow controller on an owned worker thread; results come back through ``TkUiDispatcher``.
Queueing always asks for confirmation and names every experimental arm the suite opts in.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.gui.theme_v2 import DARK_COMBOBOX_STYLE, MUTED_LABEL_STYLE, PRIMARY_BUTTON_STYLE
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.state.eval_plans_paths import initialize_eval_plans
from src.state.workspace_paths import workspace_paths
from src.utils.os_shell import open_file
from src.utils.thread_registry import get_thread_registry
from src.video.video_eval_catalog import PlanEntry, RunEntry, list_plans, list_runs
from src.video.video_eval_import import import_suite, is_private_suite
from src.video.video_eval_run import EVAL_OUTPUT_FOLDER


class VideoEvalPanel(ttk.LabelFrame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        get_controller: Callable[[], Any],
        output_dir: Callable[[], str],
        show_prompts: Callable[[], bool],
        on_queued: Callable[[list[str]], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
        ask_open: Callable[..., str] = filedialog.askopenfilename,
        eval_plans_dir: Callable[[], str] = lambda: "",
        confirm: Callable[[str, str], bool] = messagebox.askyesno,
        open_report: Callable[[str], Any] = webbrowser.open,
        confirm_import: Callable[[str, str], bool] = messagebox.askyesno,
    ) -> None:
        super().__init__(parent, text="Eval suite", padding=6)
        self._get_controller = get_controller
        self._output_dir = output_dir
        self._show_prompts = show_prompts
        self._on_queued = on_queued
        self._runner = runner
        self._ask_open = ask_open
        self._eval_plans_dir = eval_plans_dir
        self._confirm = confirm
        self._confirm_import = confirm_import
        self._open_report = open_report
        self._busy = False
        self._closed = False
        self._plans: list[PlanEntry] = []
        self._runs: list[RunEntry] = []
        self.status_var = tk.StringVar(master=self)
        self.plan_status_var = tk.StringVar(master=self)
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Plan", style=MUTED_LABEL_STYLE).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.plan_combo = ttk.Combobox(self, width=24, style=DARK_COMBOBOX_STYLE, state="disabled")
        self.plan_combo.grid(row=0, column=1, sticky="ew")
        self.plan_combo.bind("<<ComboboxSelected>>", self._on_selection)
        plan_actions = ttk.Frame(self)
        plan_actions.grid(row=1, column=1, sticky="w", pady=(4, 0))
        self.queue_button = ttk.Button(
            plan_actions, text="Queue…", style=PRIMARY_BUTTON_STYLE, command=self.on_queue_suite
        )
        self.refresh_button = ttk.Button(plan_actions, text="Refresh", command=self.refresh)
        self.plan_folder_button = ttk.Button(
            plan_actions, text="Open folder", command=self._open_plan_folder
        )
        self.other_file_button = ttk.Button(
            plan_actions, text="Other file…", command=self._choose_other_file
        )
        for button in (
            self.queue_button,
            self.refresh_button,
            self.plan_folder_button,
            self.other_file_button,
        ):
            button.pack(side="left", padx=(0, 4))
        ttk.Label(
            self, textvariable=self.plan_status_var, wraplength=460, style=MUTED_LABEL_STYLE
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(self, text="Run", style=MUTED_LABEL_STYLE).grid(
            row=3, column=0, sticky="w", padx=(0, 6)
        )
        self.run_combo = ttk.Combobox(self, width=24, style=DARK_COMBOBOX_STYLE, state="disabled")
        self.run_combo.grid(row=3, column=1, sticky="ew")
        self.run_combo.bind("<<ComboboxSelected>>", self._on_selection)
        run_actions = ttk.Frame(self)
        run_actions.grid(row=4, column=1, sticky="w", pady=(4, 0))
        self.report_button = ttk.Button(
            run_actions, text="Build report", command=self.on_build_report
        )
        self.open_report_button = ttk.Button(
            run_actions, text="Open report", command=self._open_selected_report
        )
        self.run_folder_button = ttk.Button(
            run_actions, text="Open folder", command=self._open_run_folder
        )
        for button in (self.report_button, self.open_report_button, self.run_folder_button):
            button.pack(side="left", padx=(0, 4))
        ttk.Label(self, textvariable=self.status_var, wraplength=460, style=MUTED_LABEL_STYLE).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self._update_controls()
        self.bind("<Map>", lambda _event: self.refresh(), add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _plan_root(self) -> Path:
        return workspace_paths.eval_plans_root(self._output_dir(), override=self._eval_plans_dir())

    def _plan_folder(self) -> Path:
        return workspace_paths.eval_plans_dir(
            "video", self._output_dir(), override=self._eval_plans_dir()
        )

    def _selected_plan(self) -> PlanEntry | None:
        index = self.plan_combo.current()
        return self._plans[index] if index >= 0 else None

    def _selected_run(self) -> RunEntry | None:
        index = self.run_combo.current()
        return self._runs[index] if index >= 0 else None

    def refresh(self, *, select_run: str | None = None, status: str | None = None) -> None:
        if self._busy or self._closed:
            return
        folder = self._plan_folder()
        output = Path(self._output_dir() or "output")
        plan = self._selected_plan()
        run = self._selected_run()
        run_id = select_run or (run.path.name if run else None)

        def finish(outcome: WorkOutcome) -> None:
            if outcome.error:
                self.status_var.set(f"Could not refresh evaluation plans and runs: {outcome.error}")
                return
            self._plans, self._runs = outcome.value
            self.plan_combo["values"] = [entry.label for entry in self._plans]
            self.run_combo["values"] = [entry.label for entry in self._runs]
            if self._plans:
                default = next((i for i, entry in enumerate(self._plans) if not entry.error), 0)
                self.plan_combo.current(
                    next(
                        (
                            i
                            for i, entry in enumerate(self._plans)
                            if plan and entry.path == plan.path
                        ),
                        default,
                    )
                )
            else:
                self.plan_combo.set("")
            if self._runs:
                self.run_combo.current(
                    next((i for i, entry in enumerate(self._runs) if entry.path.name == run_id), 0)
                )
            else:
                self.run_combo.set("")
            self._on_selection()
            self.status_var.set(
                status or ("" if self._runs else f"No runs in {output / EVAL_OUTPUT_FOLDER}")
            )

        self._start(
            "VideoEval-Catalog",
            lambda: WorkOutcome(value=(list_plans(folder), list_runs(output))),
            finish,
            status or "Refreshing evaluation plans and runs…",
        )

    def _on_selection(self, _event: Any = None) -> None:
        plan = self._selected_plan()
        if plan is None:
            self.plan_status_var.set(
                f"No plans in {self._plan_folder()} — Open folder or Other file… to import."
            )
        else:
            self.plan_status_var.set(plan.error)
        self._update_controls()

    def _open_plan_folder(self) -> None:
        root = self._plan_root()
        folder = self._plan_folder()

        def work() -> WorkOutcome:
            initialize_eval_plans(root)
            return WorkOutcome(value=open_file(folder))

        self._start("VideoEval-OpenFolder", work, self._finish_open_folder, "Opening plans folder…")

    def _open_run_folder(self) -> None:
        run = self._selected_run()
        if run is not None:
            self._finish_open_folder(WorkOutcome(value=open_file(run.path)))

    def _finish_open_folder(self, outcome: WorkOutcome) -> None:
        error = outcome.error or outcome.value.message
        self.status_var.set(str(error) if error else "")

    def on_queue_suite(self) -> None:
        plan = self._selected_plan()
        if not self._busy and plan is not None and not plan.error:
            self._preview(str(plan.path))

    def _choose_other_file(self) -> None:
        if self._busy:
            return
        folder = self._plan_folder()
        selected = self._ask_open(
            title="Choose a video eval suite",
            initialdir=str(folder),
            filetypes=[("Eval suite", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return
        source = Path(selected)
        if (
            source.parent == folder
            or is_private_suite(source)
            or not self._confirm_import(
                "Import eval suite",
                f"Copy {source.name} into Evaluation Plans before previewing it? "
                "Choose No to preview it from its current location.",
            )
        ):
            self._preview(selected)
            return
        root = self._plan_root()
        self._start(
            "VideoEval-Import",
            lambda: WorkOutcome(value=import_suite(source, root, apply=True)),
            self._finish_import,
            f"Importing {source.name}…",
        )

    def _finish_import(self, outcome: WorkOutcome) -> None:
        if outcome.error:
            self.status_var.set(f"Eval suite import failed: {outcome.error}")
            return
        self._preview(str(outcome.value))

    def _preview(self, path: str) -> None:
        self._start(
            "VideoEval-Preview",
            lambda: WorkOutcome(value=self._controller().preview_eval_run(path)),
            self._finish_preview,
            f"Building the eval run for {Path(path).name}...",
        )

    def _finish_preview(self, outcome: WorkOutcome) -> None:
        if outcome.error:
            self.status_var.set(f"Eval suite not queued: {outcome.error}")
            return
        plan = outcome.value
        if not plan.eligible:
            self.status_var.set("Eval suite not queued.\n" + plan.summary())
            return
        question = plan.summary() + f"\n\nQueue all {len(plan.jobs)} jobs now?"
        if plan.experimental_arms:
            question += "\n\nThe suite opts in to experimental workflows for arms: " + ", ".join(
                plan.experimental_arms
            )
        if not self._confirm("Queue eval suite", question):
            self.status_var.set("Eval suite preview discarded; nothing was queued.")
            return
        self._start(
            "VideoEval-Queue",
            lambda: WorkOutcome(value=self._controller().submit_eval_run(plan)),
            self._finish_queue,
            f"Queueing {len(plan.jobs)} eval jobs...",
        )

    def _finish_queue(self, outcome: WorkOutcome) -> None:
        if outcome.error:
            self.status_var.set(f"Eval suite not queued: {outcome.error}")
            if self._on_queued is not None:
                self._on_queued([])  # queue state is re-read, never assumed
            return
        admission = outcome.value
        self.status_var.set(
            f"Queued {len(admission.job_ids)} eval jobs as run {admission.run_id}. When they finish, "
            f"use Build eval report on {admission.run_dir}."
        )
        if self._on_queued is not None:
            self._on_queued(list(admission.job_ids))
        self.refresh(select_run=admission.run_id, status=self.status_var.get())

    def on_build_report(self) -> None:
        if self._busy:
            return
        run = self._selected_run()
        if run is None:
            return
        run_dir = str(run.path)
        show_prompts = bool(self._show_prompts())  # read on Tk, before the worker starts
        self._start(
            "VideoEval-Report",
            lambda: WorkOutcome(
                value=self._controller().build_eval_report(run_dir, show_prompts=show_prompts)
            ),
            self._finish_report,
            f"Measuring the clips of {Path(run_dir).name}...",
        )

    def _finish_report(self, outcome: WorkOutcome) -> None:
        if outcome.error:
            self.status_var.set(f"Eval report not built: {outcome.error}")
            return
        report = outcome.value
        self._show_report(report.report_path, report.summary())
        self.refresh(status=self.status_var.get())

    def _open_selected_report(self) -> None:
        run = self._selected_run()
        if run and run.report_path is not None:
            self._show_report(run.report_path, str(run.report_path))

    def _show_report(self, path: Path, status: str) -> None:
        try:
            self._open_report(path.resolve().as_uri())
        except Exception as exc:  # noqa: BLE001 - keep the report path visible on browser failure
            status = f"{status} (could not open {path}: {exc})"
        self.status_var.set(status)

    # ------------------------------------------------------------------ worker plumbing

    def _controller(self) -> Any:
        controller = self._get_controller()
        if controller is None:
            raise RuntimeError("The Video Workflow controller is not connected.")
        return controller

    def _start(
        self,
        name: str,
        work: Callable[[], WorkOutcome],
        finish: Callable[[WorkOutcome], None],
        status: str,
    ) -> None:
        self._busy = True
        self.status_var.set(status)
        self._update_controls()

        def done(outcome: WorkOutcome) -> None:
            if self._closed:
                return
            try:
                if not self.winfo_exists():
                    return
                self._busy = False
                self._update_controls()
                finish(outcome)
            except tk.TclError:
                pass  # the widget tree is going away

        self._work_runner().start(name, work, done)

    def _update_controls(self) -> None:
        plan = self._selected_plan()
        run = self._selected_run()
        for combo, entries in ((self.plan_combo, self._plans), (self.run_combo, self._runs)):
            combo.configure(state="readonly" if entries and not self._busy else "disabled")
        for button, available in (
            (self.queue_button, plan is not None and not plan.error),
            (self.report_button, run is not None),
            (self.open_report_button, run is not None and run.report_path is not None),
            (self.run_folder_button, run is not None),
            (self.plan_folder_button, True),
            (self.refresh_button, True),
            (self.other_file_button, True),
        ):
            button.state(["!disabled"] if available and not self._busy else ["disabled"])

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Build, queue or measure a video eval run without blocking Tk",
                ),
                dispatch=dispatcher.invoke,
            )
        return self._runner

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True


__all__ = ["VideoEvalPanel"]
