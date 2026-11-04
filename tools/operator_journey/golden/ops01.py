"""OPS-01: failed backend and safe operator recovery, through visible controls and the existing backend boundary.

Every case submits through the normal GUI, lets the production queue and runner meet a deterministic failure injected
at the loopback HTTP seam, and then verifies what the operator can see and what the repository recorded.  No case
replays, restarts or adopts an external runtime, and none touches a completed artifact.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.golden import flow
from tools.operator_journey.golden.session import GoldenRun, JourneyAbort, file_identity
from tools.operator_journey.tk_driver import iter_widgets

PACK_NAME = "golden_ops01"
PROMPT = "golden path recovery, a lighthouse in a storm, oil painting"
NEGATIVE = "blurry, low quality"
STEPS = 4
SEED = 777001
TXT2IMG = "/sdapi/v1/txt2img"
TERMINAL = {"completed", "failed", "cancelled"}


class _Ctx:
    def __init__(self, run: GoldenRun) -> None:
        self.run = run
        self.fake = run.fake_a1111
        self.known: set[str] = set()
        self.outcomes: dict[str, Any] = {}
        self.queued_by_operator = 0

    def new_rows(self) -> list[dict[str, Any]]:
        return [r for r in self.run.job_rows() if r["job_id"] not in self.known]

    def settle(self, description: str) -> dict[str, Any]:
        """Wait for exactly one new job to reach a terminal state; return its row (and remember it)."""

        run, holder = self.run, {}

        def done() -> bool:
            run.assert_plan_agreed()
            fresh = self.new_rows()
            if len(fresh) == 1 and fresh[0]["status"] in TERMINAL:
                holder["row"] = fresh[0]
                return True
            return False

        run.driver.wait_until(
            done,
            timeout=run.config.run_timeout,
            description=description,
            evidence=lambda: [(r["job_id"], r["status"]) for r in run.job_rows()],
        )
        run.driver.pump(1.5)  # a duplicate dispatch or an automatic retry would show up as extra rows or requests here
        self.known.add(holder["row"]["job_id"])
        return holder["row"]

    def queue_one(self) -> None:
        preview = flow.preview_pack_job(self.run, PACK_NAME, PROMPT)
        self.run.driver.invoke(preview.add_to_queue_button, label="Add to Queue")
        self.queued_by_operator += 1

    def posts(self) -> int:
        return self.fake.requests_to("POST", TXT2IMG)


def _label_texts(run: GoldenRun, pattern: str) -> list[str]:
    """Visible label text matching ``pattern`` (what the operator can read right now)."""

    found: list[str] = []
    for widget in iter_widgets(run.root):
        try:
            if isinstance(widget, (ttk.Label, tk.Label)) and widget.winfo_viewable():
                text = str(widget.cget("text"))
                if re.search(pattern, text):
                    found.append(text[:200])
        except tk.TclError:
            continue
    return found


def run_ops01(run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None) -> None:
    if physical is not None:
        raise JourneyAbort("OPS-01 injects failures into the loopback backend and has no physical lane")
    ev = run.ev
    ctx = _Ctx(run)
    fake = ctx.fake
    if fake is None:
        raise JourneyAbort("OPS-01 needs the loopback backend")
    run.boot_app()
    d = run.driver
    run.await_models()
    flow.author_pack(run, PACK_NAME, PROMPT, NEGATIVE)
    flow.txt2img_only(run)
    flow.choose_model(run)
    flow.set_generation(run, steps=STEPS, seed=SEED)
    queue = run.window.pipeline_tab.queue_panel

    # Control: one healthy job gives the completed artifact the later cases must leave untouched.
    ctx.queue_one()
    control = ctx.settle("the control job reaches a terminal state")
    run.require("control", "control_completed", control["status"] == "completed", f"{control['status']}: {control['error_message']}")
    completed = [file_identity(Path(p)) for p in control["artifact_references"]]
    ev.observe("completed_artifacts_before", completed)
    ctx.outcomes["control"] = {"status": control["status"], "posts": ctx.posts()}

    # A. The backend is unreachable before dispatch: the job is held with a visible reason and nothing is dispatched.
    fake.stop()
    posts = ctx.posts()
    ctx.queue_one()
    d.pump(10.0)
    held_text = _label_texts(run, r"(?i)webui jobs are held|WebUI: Disconnected")
    rows = ctx.new_rows()
    ctx.outcomes["unreachable_before_dispatch"] = {
        "visible": held_text,
        "statuses_while_down": [r["status"] for r in rows],
        "queue_status": str(queue.queue_status_label.cget("text")),
    }
    run.snap("unreachable")
    run.check("unreachable", "operator_told_jobs_are_held", any("held" in t for t in held_text), f"{held_text}")
    run.check("unreachable", "job_not_terminal_while_down", all(r["status"] not in TERMINAL for r in rows), f"{[r['status'] for r in rows]}")
    fake.start()
    row = ctx.settle("the held job runs once the backend is reachable")
    ctx.outcomes["unreachable_before_dispatch"].update(final=row["status"], posts=ctx.posts() - posts)
    run.check("unreachable", "completed_once_after_recovery", row["status"] == "completed" and ctx.posts() - posts == 1, f"{row['status']} posts={ctx.posts() - posts}")

    # E. The generation POST outcome is ambiguous (connection dropped after the request was read).
    fake.inject("POST", TXT2IMG, "drop")
    posts = ctx.posts()
    ctx.queue_one()
    row = ctx.settle("the ambiguous-dispatch job reaches a terminal state")
    d.pump(3.0)
    ctx.outcomes["ambiguous_dispatch"] = {"status": row["status"], "error": row["error_message"], "posts": ctx.posts() - posts}
    run.snap("ambiguous")
    run.check("ambiguous", "job_failed", row["status"] == "failed", row["status"])
    run.check("ambiguous", "dispatched_once_never_replayed", ctx.posts() - posts == 1, f"{ctx.posts() - posts} POSTs")
    run.check("ambiguous", "error_explains_no_automatic_resubmission", "did not automatically" in str(row["error_message"]), str(row["error_message"]))

    # F. Cancellation before dispatch: a paused queue holds the job; removing it cancels it without any dispatch.
    d.invoke(queue.pause_resume_button, label="Pause Queue")
    posts = ctx.posts()
    ctx.queue_one()
    d.wait_until(lambda: len(ctx.new_rows()) == 1, timeout=30, description="the paused queue holds the new job")
    held = ctx.new_rows()[0]
    d.wait_until(lambda: queue.job_listbox.size() >= 1, timeout=15, description="the queue lists the held job")
    d.select_listbox_row(queue.job_listbox, 0, label="Queue list")
    d.invoke(queue.remove_button, label="Remove from queue")
    d.pump(2.0)
    after = {r["job_id"]: r for r in run.job_rows()}.get(held["job_id"])
    ctx.outcomes["cancel_before_dispatch"] = {
        "status_before": held["status"],
        "status_after": (after or {}).get("status"),
        "posts": ctx.posts() - posts,
    }
    d.invoke(queue.pause_resume_button, label="Resume Queue")
    d.pump(3.0)
    final = {r["job_id"]: r for r in run.job_rows()}.get(held["job_id"])
    ctx.outcomes["cancel_before_dispatch"].update(final=(final or {}).get("status"), posts_after_resume=ctx.posts() - posts)
    if final:
        ctx.known.add(held["job_id"])
    run.snap("cancelled")

    # B. The backend fails while the job is being prepared (health/readback requests are refused).
    for path in ("/sdapi/v1/options", "/sdapi/v1/sd-models", "/sdapi/v1/progress"):
        fake.inject("GET", path, "status:503", times=400)
    posts = ctx.posts()
    ctx.queue_one()
    d.pump(15.0)
    mid = ctx.new_rows()
    ctx.outcomes["preparation_outage"] = {
        "statuses_while_failing": [(r["status"], r["error_message"]) for r in mid],
        "visible": _label_texts(run, r"(?i)webui|backend|fail|error"),
        "posts_while_failing": ctx.posts() - posts,
    }
    run.snap("preparation")
    fake.clear_faults()
    row = ctx.settle("the job reaches a terminal state after the backend recovers")
    ctx.outcomes["preparation_outage"].update(final=row["status"], error=row["error_message"], posts=ctx.posts() - posts)
    run.check("preparation", "nothing_dispatched_while_preparation_fails", ctx.outcomes["preparation_outage"]["posts_while_failing"] == 0, f"{ctx.outcomes['preparation_outage']['posts_while_failing']}")
    run.check("preparation", "job_held_not_lost_while_failing", all(s[0] in {"queued", "running"} for s in ctx.outcomes["preparation_outage"]["statuses_while_failing"]), f"{ctx.outcomes['preparation_outage']['statuses_while_failing']}")
    run.check("preparation", "completed_once_after_recovery", row["status"] == "completed" and ctx.posts() - posts == 1, f"{row['status']} posts={ctx.posts() - posts}")

    # C. The model the operator chose is no longer offered by the backend.
    chosen = flow.choose_model(run, "alt")
    fake.remove_model("operator-journey-alt")
    posts = ctx.posts()
    ctx.queue_one()
    row = ctx.settle("the changed-model job reaches a terminal state")
    ctx.outcomes["changed_model"] = {"model": chosen, "status": row["status"], "error": row["error_message"], "posts": ctx.posts() - posts}
    run.snap("changed_model")
    ctx.outcomes["changed_model"]["operator_log"] = [str(x)[:260] for x in list(run.app_state.operator_log)[-8:]]
    ctx.outcomes["changed_model"]["logs"] = [
        f"{r['level']} {r['logger']}: {r['message'][:260]}"
        for r in (run.faults.logs if run.faults is not None else [])
        if re.search(r"(?i)model|checkpoint", r["message"])
    ][-8:]
    ctx.outcomes["changed_model"]["visible"] = _label_texts(run, r"(?i)fail|error|model.*(missing|unavailable|not)")
    from tools.operator_journey.golden.gui import select_history_row

    d.select_tab(run.window.center_notebook, "Pipeline")
    history = select_history_row(run, row["job_id"])
    d.pump(1.0)
    history_text = [
        str(w.cget("text"))[:300]
        for w in iter_widgets(history)
        if isinstance(w, (ttk.Label, tk.Label)) and str(w.cget("text")).strip()
    ]
    ctx.outcomes["changed_model"]["history_labels"] = history_text
    ctx.outcomes["changed_model"]["history_entry"] = repr(history._entries.get(row["job_id"]))[:600]
    run.snap("changed_model_history")
    cause = " ".join([str(row["error_message"] or ""), *history_text]).lower()
    run.check("changed_model", "job_failed", row["status"] == "failed", row["status"])
    run.check("changed_model", "no_generation_with_the_wrong_checkpoint", ctx.outcomes["changed_model"]["posts"] == 0, f"{ctx.outcomes['changed_model']['posts']} POSTs")
    # The operator must be able to learn why: the cause is only in the log today (finding GP832-F1).
    run.check("changed_model", "failure_cause_visible_to_operator", "alt" in cause or "checkpoint" in cause or "model" in cause, f"error {row['error_message']!r}; History shows {history_text}")

    # G/H. Close the application while a generation is in flight, then reopen and reconcile.
    flow.choose_model(run)
    fake.inject("POST", TXT2IMG, "delay", delay=45.0)
    posts = ctx.posts()
    ctx.queue_one()
    d.wait_until(lambda: ctx.posts() > posts, timeout=60, description="the generation request reaches the backend")
    inflight = ctx.new_rows()
    ctx.outcomes["close_with_pending_work"] = {"status_at_close": [r["status"] for r in inflight]}
    run.snap("before_close")
    run.shutdown_app()
    after_close = {r["job_id"]: r["status"] for r in run.job_rows()}
    ctx.outcomes["close_with_pending_work"]["interrupts"] = fake.interrupts
    ctx.outcomes["close_with_pending_work"]["status_after_close"] = [after_close.get(r["job_id"]) for r in inflight]
    run.boot_app()
    d = run.driver
    d.pump(12.0)
    reopened = {r["job_id"]: (r["status"], r["error_message"]) for r in run.job_rows()}
    ctx.outcomes["close_with_pending_work"]["after_reopen"] = [reopened.get(r["job_id"]) for r in inflight]
    ctx.outcomes["close_with_pending_work"]["posts_after_reopen"] = ctx.posts() - posts
    run.snap("reopened")
    pending = ctx.outcomes["close_with_pending_work"]
    run.check("close", "work_was_in_flight_at_close", pending["status_at_close"] == ["running"], f"{pending['status_at_close']}")
    run.check("close", "backend_interrupt_requested", fake.interrupts >= 1, f"{fake.interrupts} /interrupt requests")
    run.check("close", "closed_job_recorded_cancelled", pending["status_after_close"] == ["cancelled"], f"{pending['status_after_close']}")
    run.check("reopen", "not_replayed_after_reopen", pending["posts_after_reopen"] == 1 and [s[0] for s in pending["after_reopen"]] == ["cancelled"], f"{pending}")

    ev.observe("ops_outcomes", ctx.outcomes)
    after_files = [file_identity(Path(p)) for p in control["artifact_references"]]
    ev.observe("completed_artifacts_after", after_files)
    run.check("integrity", "completed_artifact_unmodified", after_files == completed and bool(completed), f"{completed} != {after_files}")
    control_paths = [r for _, r in fake.requests if re.search(r"(?i)shutdown|restart|reload|kill|stop-server|server-restart", r)]
    run.check("runtime", "external_runtime_never_controlled", not control_paths and not fake.unhandled, f"{control_paths} unhandled={fake.unhandled}")
    run.check("queue", "no_unexpected_submissions", len(run.submissions.calls) == ctx.queued_by_operator, f"{len(run.submissions.calls)} submit_njrs calls for {ctx.queued_by_operator} operator submissions")
    ev.observe("resource_preflight_refusal", "NOT EXERCISED here: the image path has no resource preflight; see the video workflow readiness gate")
    run.shutdown_app()
