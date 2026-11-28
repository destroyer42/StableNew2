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
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.gui.licence_attestation_dialog import NOT_CONFIRMED, ask_for_jobs
from src.gui.theme_v2 import (
    DARK_COMBOBOX_STYLE,
    MUTED_LABEL_STYLE,
    PRIMARY_BUTTON_STYLE,
    style_text_widget,
)
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.views.video_eval_editor_dialog import VideoEvalEditorDialog
from src.gui.views.video_eval_motion_review_window import open_motion_review
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.state.eval_plans_paths import initialize_eval_plans
from src.state.workspace_paths import workspace_paths
from src.utils.os_shell import open_file
from src.utils.thread_registry import get_thread_registry
from src.video.video_eval_authoring import configured_tool_paths
from src.video.video_eval_catalog import PlanEntry, RunEntry, list_plans, list_runs
from src.video.video_eval_import import import_suite, is_private_suite
from src.video.video_eval_run import EVAL_OUTPUT_FOLDER, EvalRunPlan


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
        confirm: Callable[[str, str], bool] | None = None,
        open_report: Callable[[str], Any] = webbrowser.open,
        confirm_import: Callable[[str, str], bool] = messagebox.askyesno,
        on_run_changed: Callable[[RunEntry | None], None] | None = None,
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
        self._on_run_changed = on_run_changed
        self._editor: VideoEvalEditorDialog | None = None
        self._motion_review: Any = None
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
        self.editor_button = ttk.Button(
            plan_actions, text="Create / Edit Suite…", command=self._open_editor
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
            self.editor_button,
            self.refresh_button,
            self.plan_folder_button,
            self.other_file_button,
        ):
            button.pack(side="left", padx=(0, 4))
        plan_status = ttk.Label(self, textvariable=self.plan_status_var, style=MUTED_LABEL_STYLE)
        plan_status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        bind_wraplength(plan_status)

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
        self.motion_review_button = ttk.Button(
            run_actions, text="Review Motion…", command=self._open_motion_review
        )
        for button in (
            self.report_button,
            self.open_report_button,
            self.motion_review_button,
            self.run_folder_button,
        ):
            button.pack(side="left", padx=(0, 4))
        run_status = ttk.Label(self, textvariable=self.status_var, style=MUTED_LABEL_STYLE)
        run_status.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        bind_wraplength(run_status)
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

    # Public, read-only seams for the Evaluate view's Rate & review section (VID-UX-384 follow-up).
    def selected_run(self) -> RunEntry | None:
        return self._selected_run()

    def open_selected_report(self) -> None:
        self._open_selected_report()

    def open_selected_motion_review(self) -> None:
        self._open_motion_review()

    def refresh(
        self,
        *,
        select_run: str | None = None,
        status: str | None = None,
        select_plan: Path | None = None,
        preview_saved: bool = False,
    ) -> None:
        if self._busy or self._closed or self._editor is not None:
            return
        folder = self._plan_folder()
        output = Path(self._output_dir() or "output")
        plan = self._selected_plan()
        run = self._selected_run()
        current_path = plan.path if plan else None
        run_id = select_run or (run.path.name if run else None)

        def work() -> WorkOutcome:
            # The root setting can change while the editor is open. Select only the file
            # actually published, and keep preview bound to that path even after a root change.
            wanted = current_path
            if select_plan is not None and folder.resolve() == select_plan.parent:
                wanted = folder / select_plan.name
            return WorkOutcome(value=(list_plans(folder), list_runs(output), wanted))

        def finish(outcome: WorkOutcome) -> None:
            if outcome.error:
                self.status_var.set(f"Could not refresh evaluation plans and runs: {outcome.error}")
                if preview_saved and select_plan is not None:
                    self._preview(str(select_plan))
                return
            self._plans, self._runs, plan_path = outcome.value
            self.plan_combo["values"] = [entry.label for entry in self._plans]
            self.run_combo["values"] = [entry.label for entry in self._runs]
            if self._plans:
                default = next((i for i, entry in enumerate(self._plans) if not entry.error), 0)
                self.plan_combo.current(
                    next(
                        (
                            i
                            for i, entry in enumerate(self._plans)
                            if plan_path and entry.path == plan_path
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
            if preview_saved and select_plan is not None:
                self._preview(str(select_plan))

        self._start(
            "VideoEval-Catalog",
            work,
            finish,
            status or "Refreshing evaluation plans and runs…",
        )

    def _on_selection(self, _event: Any = None) -> None:
        plan = self._selected_plan()
        if plan is None:
            self.plan_status_var.set(
                f"No plans in {self._plan_folder()} — Create / Edit Suite… to get started."
            )
        else:
            self.plan_status_var.set(plan.error)
        self._update_controls()
        if self._on_run_changed is not None:
            self._on_run_changed(self._selected_run())

    def _open_editor(self) -> None:
        if self._busy or self._closed:
            return
        if self._editor is not None:
            self._editor.lift()
            self._editor.focus_set()
            return
        plan = self._selected_plan()
        self._editor = VideoEvalEditorDialog(
            self,
            plan_root=self._plan_root(),
            initial_path=plan.path if plan else None,
            runner=self._work_runner(),
            on_saved=self._editor_saved,
            on_close=self._editor_closed,
            ask_open=self._ask_open,
        )
        self._update_controls()

    def _editor_closed(self) -> None:
        self._editor = None
        if not self._closed and self.plan_combo.winfo_exists():
            self._update_controls()

    def _editor_saved(self, path: Path, preview: bool) -> None:
        self.refresh(select_plan=path, preview_saved=preview, status=f"Saved {path}.")

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
        if not self._busy and self._editor is None and plan is not None and not plan.error:
            self._preview(str(plan.path))

    def _choose_other_file(self) -> None:
        if self._busy or self._editor is not None:
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
        question = _preview_text(plan)
        if not plan.eligible:
            self.status_var.set("Eval suite not queued.\n" + plan.summary())
            if self._confirm is None:
                self._show_preview(question, queueable=False)
            return
        if plan.experimental_arms:
            question += "\n\nThe suite opts in to experimental workflows for arms: " + ", ".join(
                plan.experimental_arms
            )
        self._busy = True
        self._update_controls()
        try:
            accepted = (
                self._confirm(
                    "Queue eval suite", question + f"\n\nQueue all {len(plan.jobs)} jobs now?"
                )
                if self._confirm is not None
                else self._show_preview(question, queueable=True)
            )
        finally:
            self._busy = False
            if not self._closed:
                self._update_controls()
        if self._closed:
            return
        if not accepted:
            self.status_var.set("Eval suite preview discarded; nothing was queued.")
            return
        attestation = ask_for_jobs(self, [getattr(job, "njr", None) for job in plan.jobs])
        if attestation is None:
            self.status_var.set(f"Eval suite not queued. {NOT_CONFIRMED}")
            return
        given = {"attestation": attestation} if attestation else {}
        self._start(
            "VideoEval-Queue",
            lambda: WorkOutcome(value=self._controller().submit_eval_run(plan, **given)),
            self._finish_queue,
            f"Queueing {len(plan.jobs)} eval jobs...",
        )

    def _show_preview(self, text: str, *, queueable: bool) -> bool:
        dialog = tk.Toplevel(self)
        dialog.title("Evaluation Jobs Preview")
        dialog.transient(self.winfo_toplevel())
        dialog.geometry("740x480")
        dialog.minsize(440, 260)
        content = ScrolledText(dialog, wrap="word", width=70, height=20)
        style_text_widget(content)
        content.pack(expand=True, fill="both", padx=12, pady=12)
        content.insert("1.0", text)
        content.configure(state="disabled")
        actions = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        accepted = False

        def queue() -> None:
            nonlocal accepted
            accepted = True
            dialog.destroy()

        dismiss = ttk.Button(
            actions, text="Cancel" if queueable else "Close", command=dialog.destroy
        )
        dismiss.pack(side="right")
        if queueable:
            ttk.Button(
                actions, text="Queue All Jobs", style=PRIMARY_BUTTON_STYLE, command=queue
            ).pack(side="right", padx=(0, 8))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dismiss.focus_set()
        dialog.grab_set()
        self.wait_window(dialog)
        return accepted

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

    def _open_motion_review(self) -> None:
        """Open the bounded Motion Review of the selected driving-motion run (it needs a built report)."""

        run = self._selected_run()
        if run is None or not (run.motion and run.built):
            self.status_var.set(
                "Build the report of a driving-motion run first, then review its motion."
            )
            return
        sfw = not self._show_prompts()
        self._motion_review = open_motion_review(
            self.winfo_toplevel(),
            run.path,
            visibility_mode_provider=lambda: "sfw" if sfw else "nsfw",
            runner=self._runner,
        )

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
        free = not self._busy and self._editor is None
        for combo, entries in ((self.plan_combo, self._plans), (self.run_combo, self._runs)):
            combo.configure(state="readonly" if entries and free else "disabled")
        for button, available in (
            (self.queue_button, plan is not None and not plan.error),
            (self.report_button, run is not None),
            (self.open_report_button, run is not None and run.report_path is not None),
            (self.run_folder_button, run is not None),
            (self.motion_review_button, run is not None and run.motion and run.built),
            (self.plan_folder_button, True),
            (self.refresh_button, True),
            (self.other_file_button, True),
        ):
            button.state(["!disabled"] if available and free else ["disabled"])
        self.editor_button.state(["disabled"] if self._busy else ["!disabled"])

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


def _preview_text(plan: EvalRunPlan) -> str:
    lines = [plan.summary(), ""]
    tools = [
        f"{arm.arm_id}: {setting} = {path}"
        for arm in plan.suite.arms
        for setting, path in configured_tool_paths(arm.overrides)
    ]
    if tools:
        lines.extend(
            [
                "Check that you trust these suite-specified executables and model files before queueing.",
                *tools,
                "",
            ]
        )
    if plan.jobs:
        lines.append("Compiled jobs")
    for job in plan.jobs:
        # Use the frozen job identity, including the resolved workflow revision.
        workflow = job.njr.config.get("video_workflow") or {}
        engine = job.backend
        if workflow.get("workflow_id"):
            engine = f"{workflow['workflow_id']} {workflow.get('workflow_version', '')}"
        seeds = job.segment_seeds or (job.seed,)
        lines.append(
            f"{job.case_id} × {job.arm_id}   |   {engine}   |   "
            f"Seed {', '.join(map(str, seeds))}   |   {job.frame_count} frames   |   {job.job_id}"
        )
    return "\n".join(lines)


__all__ = ["VideoEvalPanel"]
