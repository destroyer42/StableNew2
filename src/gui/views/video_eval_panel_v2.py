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

from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.utils.thread_registry import get_thread_registry
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
        ask_directory: Callable[..., str] = filedialog.askdirectory,
        confirm: Callable[[str, str], bool] = messagebox.askyesno,
        open_report: Callable[[str], Any] = webbrowser.open,
    ) -> None:
        super().__init__(parent, text="Eval suite", padding=6)
        self._get_controller = get_controller
        self._output_dir = output_dir
        self._show_prompts = show_prompts
        self._on_queued = on_queued
        self._runner = runner
        self._ask_open = ask_open
        self._ask_directory = ask_directory
        self._confirm = confirm
        self._open_report = open_report
        self._busy = False
        self._closed = False
        self.status_var = tk.StringVar(
            value="Run a fixed set of images and prompts against several arms, then compare them "
            "side by side. See docs/runbooks/video_eval_kit.md."
        )
        self.queue_button = ttk.Button(
            self, text="Queue eval suite...", command=self.on_queue_suite
        )
        self.queue_button.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.report_button = ttk.Button(
            self, text="Build eval report...", command=self.on_build_report
        )
        self.report_button.grid(row=0, column=1, sticky="w")
        ttk.Label(self, textvariable=self.status_var, wraplength=520, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self.bind("<Destroy>", self._on_destroy, add="+")

    # ------------------------------------------------------------------ actions

    def on_queue_suite(self) -> None:
        if self._busy:
            return
        path = self._ask_open(
            title="Choose a video eval suite",
            filetypes=[("Eval suite", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
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

    def on_build_report(self) -> None:
        if self._busy:
            return
        initial = Path(self._output_dir() or "output") / EVAL_OUTPUT_FOLDER
        run_dir = self._ask_directory(
            title="Choose an eval run folder", initialdir=str(initial) if initial.is_dir() else None
        )
        if not run_dir:
            return
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
        self.status_var.set(report.summary())
        try:
            self._open_report(report.report_path.resolve().as_uri())
        except Exception as exc:  # noqa: BLE001 - a browser problem must not hide the report path
            self.status_var.set(f"{report.summary()} (could not open a browser: {exc})")

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
        self._set_buttons_enabled(False)

        def done(outcome: WorkOutcome) -> None:
            if self._closed:
                return
            try:
                if not self.winfo_exists():
                    return
                self._busy = False
                self._set_buttons_enabled(True)
                finish(outcome)
            except tk.TclError:
                pass  # the widget tree is going away

        self._work_runner().start(name, work, done)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = ["!disabled"] if enabled else ["disabled"]
        self.queue_button.state(state)
        self.report_button.state(state)

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
