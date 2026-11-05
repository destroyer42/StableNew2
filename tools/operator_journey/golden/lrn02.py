"""LRN-02: Learning evidence to explicit profile reuse (probe version)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.operator_journey.golden import flow
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.session import GoldenRun, JourneyAbort, file_identity
from tools.operator_journey.observe import job_lifecycle_settled, read_job_rows, read_rating_records

PROMPT = "golden path learning, a lighthouse at dusk, oil painting"
CFG_VALUES = (4.0, 6.0, 8.0)
RATINGS = {4.0: 2, 6.0: 5, 8.0: 3}  # the middle value wins, so a winner is not simply the largest
SEED = 31337
STEPS = 4
SIZE = 512
PACK_NAME = "golden_lrn02"
NEGATIVE = "blurry, low quality"
PROFILE_NAME = "LRN-02 CFG findings"


def _store_root(run: GoldenRun) -> Path:
    return Path(run.controller.generation_profiles.service.store.root)


def _published_files(run: GoldenRun) -> list[str]:
    """Revision files the Learning profile store holds (one immutable file per revision)."""

    return sorted(str(p) for p in _store_root(run).glob("profiles/learning/*/r*.json"))


def _favorites(run: GoldenRun) -> str | None:
    path = _store_root(run) / "favorites.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _configure(run: GoldenRun) -> Any:
    from src.gui.view_contracts.pipeline_composer_contract import STAGE_LABELS
    from tools.operator_journey.golden.gui import set_toggle

    d, w = run.driver, run.window
    d.select_tab(w.center_notebook, "Pipeline")
    pipeline = w.pipeline_tab
    for stage, wanted in (("txt2img", True), ("adetailer", False), ("upscale", False)):
        set_toggle(run, pipeline, STAGE_LABELS[stage], wanted)
    if bool(w.sidebar_panel_v2.stage_states["img2img"].get()):
        w.sidebar_panel_v2.legacy_stage_section.set_expanded(True)
        set_toggle(run, pipeline, STAGE_LABELS["img2img"], False)
    card = pipeline.stage_cards_panel.txt2img_card
    d.set_variable(card.steps_var, STEPS, label="txt2img steps")
    d.set_variable(card.width_var, SIZE, label="txt2img width")
    d.set_variable(card.height_var, SIZE, label="txt2img height")
    d.set_variable(card.seed_var, str(SEED), label="txt2img seed")
    sidebar = w.sidebar_panel_v2
    if bool(sidebar.global_positive_enabled_var.get()):
        set_toggle(run, sidebar, "Enable Global Positive", False)
    d.select_tab(w.center_notebook, "Prompt")
    d.type_in_text(w.prompt_tab.editor, PROMPT, label="Prompt tab editor")

    d.select_tab(w.center_notebook, "Learning - Adv")
    learning = w.learning_tab
    d.select_tab(learning._mode_notebook, "Designed Experiments")
    panel = learning.experiment_panel
    d.select_combobox(panel.stage_combo, "txt2img", label="target stage")
    d.select_combobox(panel.prompt_source_combo, "custom", label="prompt source")
    d.type_in_text(panel.custom_prompt_text, PROMPT, label="custom prompt")
    editor = panel.baseline_editor
    for name in ("sampler_name", "scheduler"):
        if not editor._vars[name].get().strip():
            choices = [str(v) for v in editor._widgets[name].cget("values")]
            run.require(
                "configure",
                f"learning_{name}_choices",
                bool(choices),
                "the backend offered no choices",
            )
            d.select_combobox(editor._widgets[name], choices[0], label=f"Learning baseline {name}")
    d.select_combobox(panel.variable_combo, "CFG Scale", label="variable under test")
    d.set_variable(panel.start_var, CFG_VALUES[0], label="CFG start")
    d.set_variable(panel.end_var, CFG_VALUES[-1], label="CFG end")
    d.set_variable(panel.step_var, CFG_VALUES[1] - CFG_VALUES[0], label="CFG step")
    d.set_variable(panel.images_var, 1, label="images per variant")
    return learning


def run_lrn02(
    run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None
) -> None:
    if physical is not None:
        raise JourneyAbort("LRN-02 has no physical lane")
    ev = run.ev
    run.boot_app()
    d, w = run.driver, run.window
    run.await_models()
    flow.choose_model(run)
    learning = _configure(run)
    panel = learning.experiment_panel
    state = learning.learning_controller.learning_state
    blockers = panel._baseline_blockers()
    ev.observe("baseline_blockers", blockers)
    d.invoke(panel.build_button, label="Build Preview Only")
    d.wait_until(
        lambda: len(state.plan) > 0 or panel.feedback_var.get().startswith(("Validation", "Error")),
        timeout=30,
        description="Build Preview Only produces a plan",
        evidence=lambda: panel.feedback_var.get(),
    )
    ev.observe("plan", [(str(v.param_value), v.status) for v in state.plan])
    ev.observe("feedback", panel.feedback_var.get())
    run.snap("preview")
    repository = run.repository_path
    d.invoke(learning.workflow_bar.primary_button, label="Run Experiment")

    def settled() -> bool:
        rows = read_job_rows(repository, run.ws.root)
        return job_lifecycle_settled(rows, len(state.plan)) and all(
            v.status in {"completed", "failed", "uncontrolled"} for v in state.plan
        )

    d.wait_until(
        settled,
        timeout=run.config.run_timeout,
        description="all experiment jobs reach a terminal state",
    )
    d.pump(2.0)
    ev.observe(
        "job_statuses",
        [(r["variant_index"], r["status"], r["error_message"]) for r in run.job_rows()],
    )
    review = learning.review_panel
    d.invoke(learning.workflow_bar.step_buttons["compare"], label="step 4 Compare")
    d.wait_until(
        lambda: review.variant_summary_list.size() == len(CFG_VALUES),
        timeout=20,
        description="review lists every variant",
    )
    d.invoke(learning.workflow_bar.primary_button, label="Rate Results")
    d.wait_until(
        lambda: review.rate_button.winfo_viewable(),
        timeout=20,
        description="the rating controls are shown",
    )
    publication = review.profile_publication
    section_toggle = publication.winfo_children()[0].toggle_button
    d.invoke(section_toggle, label="Save Findings as Generation Profile (open)")

    def rate(order: list[float], *, first: bool) -> None:
        for index, value in enumerate(order):
            if not (first and index == 0):
                d.invoke(review.next_unrated_button, label="Next Unrated")
            d.pump(0.4)
            d.wait_until(
                lambda: review.image_listbox.size() >= 1,
                timeout=15,
                description="review shows the variant images",
            )
            d.select_listbox_row(review.image_listbox, 0, label="review image list")
            d.invoke(review.rating_buttons[RATINGS[value] - 1], label=f"rating {RATINGS[value]}")
            d.invoke(review.rate_button, label="Save Rating")

    def contexts_equal() -> tuple[bool, list[Any]]:
        fixed = ("model", "steps", "sampler_name", "scheduler", "vae", "seed", "width", "height")
        seen = {
            json.dumps(
                {k: (dict(v.executed_config).get("txt2img") or {}).get(k) for k in fixed},
                sort_keys=True,
                default=str,
            )
            for v in state.plan
        }
        cfgs = [(dict(v.executed_config).get("txt2img") or {}).get("cfg_scale") for v in state.plan]
        return len(seen) == 1, cfgs

    one_context, cfgs = contexts_equal()
    run.check(
        "experiment",
        "only_cfg_scale_varies",
        one_context and [float(c) for c in cfgs] == list(CFG_VALUES),
        f"contexts={one_context} cfg={cfgs}",
    )
    run.check(
        "experiment",
        "no_publication_before_rating",
        not _published_files(run),
        f"{_published_files(run)}",
    )

    def review_findings() -> dict[str, Any]:
        d.invoke(publication.review_button, label="Review Profile Findings")
        d.wait_until(
            lambda: str(publication.review_button.cget("state")) != "disabled"
            and publication._proposal is not None,
            timeout=30,
            description="the findings review answers",
        )
        return {
            "status": publication._status.get(),
            "publish": str(publication.publish_button.cget("state")),
            "details": publication.details.get("1.0", "end-1c"),
            "ready": bool(publication._proposal.ready),
            "blockers": list(publication._proposal.blockers),
        }

    rate([4.0, 6.0], first=True)
    ev.observe(
        "ratings_after_two",
        [
            (r["metadata"].get("variant_value"), r["metadata"].get("user_rating_raw"))
            for r in read_rating_records(run.ws.records_path)
        ],
    )
    refused = review_findings()
    ev.observe("review_after_two", refused)
    run.snap("review_refused")
    run.check(
        "gate",
        "unqualified_findings_cannot_be_published",
        not refused["ready"] and refused["publish"] == "disabled",
        f"{refused}",
    )
    run.check(
        "gate",
        "refusal_says_what_is_missing",
        "1 more controlled rating" in refused["details"],
        f"{refused['details'][:400]}",
    )
    run.check(
        "gate",
        "nothing_published_while_refused",
        not _published_files(run),
        f"{_published_files(run)}",
    )

    rate([8.0], first=False)
    ready = review_findings()
    ev.observe("review_after_three", ready)
    run.snap("review_ready")
    run.require(
        "gate",
        "qualified_findings_unlock_publication",
        ready["ready"] and ready["publish"] == "normal",
        f"{ready}",
    )
    run.check(
        "gate",
        "winner_is_the_best_rated_value",
        "cfg_scale=6.0" in ready["details"],
        f"{ready['details'][:400]}",
    )

    base = w.sidebar_panel_v2.base_generation_panel
    strip = base._profile_strip
    before_values = {"cfg": float(base.cfg_var.get()), "profile": strip.profile_var.get()}
    favorites_before = _favorites(run)
    d.set_variable(publication._profile_name_var, PROFILE_NAME, label="Profile name")
    run.answer_yesno(True)
    d.invoke(publication.publish_button, label="Publish Learning Profile")
    d.wait_until(
        lambda: bool(_published_files(run)),
        timeout=30,
        description="the profile is written to the isolated store",
        evidence=lambda: publication._status.get(),
    )
    d.pump(1.0)
    published = _published_files(run)
    ev.observe("published_files", published)
    ev.observe("publication_status", publication._status.get())
    run.snap("published")
    profile_identity = [dict(file_identity(Path(p))) for p in published]
    root_text = str(Path(run.ws.root).resolve()).lower()
    run.check(
        "publish",
        "profile_written_inside_the_isolated_workspace",
        bool(published) and all(root_text in str(Path(p).resolve()).lower() for p in published),
        f"{published}",
    )
    run.check(
        "publish",
        "exactly_one_immutable_revision",
        len(published) == 1 and published[0].endswith("r0001.json"),
        f"{published}",
    )
    run.check(
        "publish",
        "publication_did_not_favorite_it",
        _favorites(run) == favorites_before,
        f"{favorites_before!r} -> {_favorites(run)!r}",
    )
    after_values = {"cfg": float(base.cfg_var.get()), "profile": strip.profile_var.get()}
    run.check(
        "publish",
        "publication_did_not_apply_the_profile",
        after_values == before_values,
        f"{before_values} -> {after_values}",
    )

    # Restart: ratings and the profile are durable, and nothing is replayed.
    ratings_before = sorted(
        (r["metadata"]["job_id"], r["metadata"]["user_rating_raw"])
        for r in read_rating_records(run.ws.records_path)
    )
    jobs_before = {r["job_id"]: r["status"] for r in run.job_rows()}
    run.shutdown_app()
    run.boot_app()
    d, w = run.driver, run.window
    run.await_models()
    ratings_after = sorted(
        (r["metadata"]["job_id"], r["metadata"]["user_rating_raw"])
        for r in read_rating_records(run.ws.records_path)
    )
    run.check(
        "restart",
        "ratings_survive_restart",
        ratings_after == ratings_before and len(ratings_after) == 3,
        f"{ratings_before} vs {ratings_after}",
    )
    run.check(
        "restart",
        "jobs_survive_restart_unchanged",
        {r["job_id"]: r["status"] for r in run.job_rows()} == jobs_before,
        "job rows changed",
    )
    run.check(
        "restart",
        "published_profile_is_unchanged",
        [dict(file_identity(Path(p))) for p in _published_files(run)] == profile_identity,
        "the stored profile changed",
    )

    # Explicit reuse: the profile applies only when the operator selects it.
    flow.author_pack(run, PACK_NAME, PROMPT, NEGATIVE)
    flow.txt2img_only(run)
    flow.choose_model(run)
    base = w.sidebar_panel_v2.base_generation_panel
    strip = base._profile_strip
    d.pump(1.0)
    choices = [str(v) for v in strip.combo.cget("values")]
    ev.observe("profile_choices_after_restart", choices)
    learned = next((c for c in choices if PROFILE_NAME in c), None)
    run.require("reuse", "learning_profile_is_offered", learned is not None, f"{choices}")
    run.check(
        "reuse",
        "profile_not_selected_until_the_operator_chooses",
        strip.profile_var.get() != learned and float(base.cfg_var.get()) != CFG_VALUES[1],
        f"{strip.profile_var.get()!r} cfg={base.cfg_var.get()}",
    )
    d.select_combobox(strip.combo, learned, label="Profile")
    d.pump(1.0)
    run.snap("profile_selected")
    run.check(
        "reuse",
        "selected_profile_sets_the_learned_cfg",
        float(base.cfg_var.get()) == CFG_VALUES[1],
        f"cfg={base.cfg_var.get()}",
    )
    flow.set_generation(run, steps=STEPS, seed=SEED)
    submitted_before = len(run.submissions.calls)
    preview = flow.preview_pack_job(run, PACK_NAME, PROMPT)
    run.snap("preview")
    run.check(
        "reuse",
        "preview_submits_nothing",
        len(run.submissions.calls) == submitted_before,
        f"{run.submissions.calls}",
    )
    run.check(
        "reuse",
        "preview_shows_the_learned_cfg",
        str(CFG_VALUES[1]) in str(preview.cfg_label.cget("text")),
        f"{preview.cfg_label.cget('text')!r}",
    )
    d.invoke(preview.add_to_queue_button, label="Add to Queue")
    run.assert_plan_agreed()
    d.wait_until(
        lambda: len(run.job_rows()) == len(jobs_before) + 1
        and all(r["status"] in {"completed", "failed", "cancelled"} for r in run.job_rows()),
        timeout=run.config.run_timeout,
        description="the new job reaches a terminal state",
        evidence=lambda: [
            (r["job_id"][:6], r["status"], r["error_message"]) for r in run.job_rows()
        ],
    )
    newest = next(r for r in run.job_rows() if r["job_id"] not in jobs_before)
    run.require(
        "reuse",
        "new_job_completed",
        newest["status"] == "completed",
        f"{newest['status']}: {newest['error_message']}",
    )
    config = (read_njr(run.repository_path, newest["job_id"]).get("workload") or {}).get(
        "config"
    ) or {}
    ev.observe(
        "new_job_frozen", {k: config.get(k) for k in ("model", "cfg_scale", "steps", "seed")}
    )
    run.check(
        "reuse",
        "frozen_njr_carries_the_selected_profile_value",
        float(config.get("cfg_scale") or 0) == CFG_VALUES[1],
        f"{config.get('cfg_scale')!r}",
    )
    run.check(
        "reuse",
        "later_job_is_the_only_new_submission",
        len(run.submissions.calls) == submitted_before + 1,
        f"{run.submissions.calls}",
    )
    run.checkpoint("lrn02_done")
    run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")
