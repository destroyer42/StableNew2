"""LRN-01: designed experiment -> queued variants -> review -> ratings -> close, reopen, persistence.

The experiment phases are the existing reference journey's (``learning_lora_strength``): the same visible controls and
checks, driven through whichever desktop driver the run chose.  This module adds the close/reopen persistence proof.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from tools.operator_journey.golden.session import GoldenRun, JourneyAbort
from tools.operator_journey.journeys.learning_lora_strength import (
    _RATINGS,
    _STRENGTHS,
    DEFAULT_LORA,
    JourneyConfig,
    _Journey,
)
from tools.operator_journey.observe import SubmissionObserver, read_job_rows, read_rating_records
from tools.operator_journey.preflight import BackendInfo
from tools.operator_journey.tk_driver import is_disabled, iter_widgets


def _bridge(run: GoldenRun) -> _Journey:
    """The reference journey's phase methods, bound to this run's app, driver and evidence."""

    fake = run.fake_a1111
    info = BackendInfo(
        base_url=fake.base_url,
        reachable=True,
        models=list(fake.model_names),
        loras=list(fake.loras),
        active_checkpoint=fake.title(fake.model),
        version="operator-journey-fake",
    )
    config = JourneyConfig(
        backend="fake",
        fixture_sdxl=True,
        timeout=run.config.run_timeout,
        show_window=not run.config.hide_window,
    )
    journey = _Journey(config, run.ev, run.ws, fake, info)
    journey.driver, journey.window, journey.controller = run.driver, run.window, run.controller
    journey.app_state, journey.trace = run.app_state, run.trace
    journey.submissions = SubmissionObserver()
    return journey


def _analytics_row(run: GoldenRun, experiment_name: str) -> tuple[str, ...]:
    from src.gui.views.learning_analytics_panel import LearningAnalyticsPanel

    d = run.driver
    review = run.window.learning_tab.review_panel
    d.invoke(review.analytics_button, label="View Analytics")
    window = d.wait_until(
        lambda: next(
            (
                c
                for c in iter_widgets(d.root)
                if isinstance(c, tk.Toplevel) and c.title() == "Learning Analytics"
            ),
            None,
        ),
        timeout=15,
        description="Learning Analytics window opens",
    )
    tree = d.find(window, LearningAnalyticsPanel).experiments_tree  # type: ignore[attr-defined]
    d.wait_until(
        lambda: any(tree.item(k, "text") == experiment_name for k in tree.get_children()),
        timeout=15,
        description="Analytics lists the experiment",
    )
    return tuple(
        str(v)
        for v in next(
            tree.item(k, "values")
            for k in tree.get_children()
            if tree.item(k, "text") == experiment_name
        )
    )


def _reopen_saved_experiment(run: GoldenRun, experiment_name: str) -> None:
    """After a restart the tab starts on a fresh design: open the saved experiment from the Experiment Library."""

    from tkinter import ttk

    d, learning = run.driver, run.window.learning_tab
    d.invoke(d.find_button(learning.header_frame, "Experiment Library"), label="Experiment Library")
    library = d.wait_until(
        lambda: next(
            (
                c
                for c in iter_widgets(d.root)
                if isinstance(c, tk.Toplevel) and c.title() == "Learning Experiment Library"
            ),
            None,
        ),
        timeout=15,
        description="the Experiment Library opens",
    )
    tree = d.find(library, ttk.Treeview)
    d.wait_until(
        lambda: any(tree.item(k, "text") == experiment_name for k in tree.get_children()),
        timeout=15,
        description="the Library lists the saved experiment",
    )
    row = next(k for k in tree.get_children() if tree.item(k, "text") == experiment_name)
    d.select_tree_row(tree, row, label="Library row (saved experiment)")
    d.invoke(d.find_button(library, "Open / Review"), label="Library: Open / Review")
    review = learning.review_panel
    d.wait_until(
        lambda: learning.experiment_panel is not None
        and bool(learning.learning_controller.learning_state.current_experiment),
        timeout=15,
        description="the saved experiment is open",
    )
    if (
        not review.analytics_button.winfo_viewable()
    ):  # land on the results step like an operator would
        bar = learning.workflow_bar
        for step in ("rate", "compare"):
            if not is_disabled(bar.step_buttons[step]):
                d.invoke(bar.step_buttons[step], label=f"step {step}")
                break
        d.wait_until(
            lambda: review.analytics_button.winfo_viewable(),
            timeout=15,
            description="the review step shows View Analytics",
        )


def run_lrn01(run: GoldenRun, *, simulated: bool = True, physical: dict | None = None) -> None:
    ev = run.ev
    run.boot_app()
    journey = _bridge(run)
    journey._preflight()
    journey._configure()
    journey._build_preview()
    journey._run_experiment()
    journey._verify_execution()
    journey._review_and_rate()
    ev.observe("experiment_id", ev.summary.get("experiment_id"))
    experiment_name = journey.state.current_experiment.name
    jobs_before = {r["job_id"]: r["status"] for r in run.job_rows()}
    ratings_before = {
        (r["metadata"] or {}).get("job_id"): (r["metadata"] or {}).get("user_rating_raw")
        for r in read_rating_records(run.ws.records_path)
    }
    run.check(
        "persist",
        "no_recommendation_applied_or_published",
        not any(Path(run.ws.root).glob("**/published_profiles*")),
        "a profile publication artifact exists",
    )
    row_before = _analytics_row(run, experiment_name)
    submitted_before = len(run.submissions.calls)
    run.snap("before_close")

    # Close through the application's exit path, then reopen the same workspace.
    run.shutdown_app()
    run.boot_app()
    run.await_models()
    d, w = run.driver, run.window
    d.select_tab(w.center_notebook, "Learning - Adv")
    d.pump(1.0)
    rows_after = {r["job_id"]: r["status"] for r in read_job_rows(run.repository_path, run.ws.root)}
    ratings_after = {
        (r["metadata"] or {}).get("job_id"): (r["metadata"] or {}).get("user_rating_raw")
        for r in read_rating_records(run.ws.records_path)
    }
    run.check(
        "persist",
        "jobs_preserved_after_reopen",
        rows_after == jobs_before and len(rows_after) == len(_STRENGTHS),
        f"before {jobs_before} after {rows_after}",
    )
    run.check(
        "persist",
        "ratings_preserved_after_reopen",
        ratings_after == ratings_before and sorted(ratings_after.values()) == sorted(_RATINGS),
        f"before {ratings_before} after {ratings_after}",
    )
    _reopen_saved_experiment(run, experiment_name)
    row_after = _analytics_row(run, experiment_name)
    run.check(
        "persist",
        "reopened_analytics_row_unchanged",
        row_after == row_before,
        f"{row_before} vs {row_after}",
    )
    run.check(
        "persist",
        "reopen_resubmitted_nothing",
        len(run.submissions.calls) == submitted_before,
        f"{run.submissions.calls[submitted_before:]}: reopening must not resubmit work",
    )
    run.check(
        "persist",
        "reopen_created_no_new_jobs",
        len(run.job_rows()) == len(jobs_before),
        "job count changed",
    )
    ev.observe("fixture_backend", f"FakeA1111 with LoRA {DEFAULT_LORA}", source="simulated_fixture")
    run.snap("after_reopen")
    run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")
