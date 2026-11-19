"""IMG-03's optional steps (QUAL-921): Extend Canvas, Regenerate with Changes and Replay, each through visible controls.

Each step starts from the completed source job, submits exactly one job through the canonical path (Review's frozen
editor, the Pipeline Preview's Add to Queue, or History's Replay Job, all ending at ``JobService.submit_njrs``), waits
for it with the frozen-plan gate consulted, and verifies the frozen NJR, the lineage and the produced artifact.
Internal reads are used only to wait for or verify an outcome, never to perform a step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.operator_journey.golden.gui import select_history_row, wait_text
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.img03 import (
    EditContext,
    _toplevel,
    compare_with_parent,
    evidence_source,
    is_physical,
    open_in_review,
    release_dialog,
    result_images,
    wait_new_job,
)
from tools.operator_journey.golden.img03_frozen import (
    OPTIONAL_STEPS,
    outpaint_preservation,
    outpaint_size,
    pixels_identical,
)
from tools.operator_journey.golden.media import inspect_image
from tools.operator_journey.golden.session import GoldenRun, file_identity

__all__ = ["OPTIONAL_STEPS", "run_outpaint", "run_regenerate", "run_replay"]

_SIDES = ("left", "right", "top", "bottom")


def _config(njr: dict[str, Any]) -> dict[str, Any]:
    return (njr.get("workload") or {}).get("config") or {}


def _source_unchanged(run: GoldenRun, ctx: EditContext, phase: str) -> None:
    run.check(
        phase,
        "source_image_is_byte_identical",
        file_identity(ctx.source) == ctx.source_identity,
        f"{file_identity(ctx.source)} vs {ctx.source_identity}",
    )


def run_outpaint(run: GoldenRun, ctx: EditContext) -> None:
    """Review: Extend Canvas on the source (handed off from History), Preview the frozen job, Add to Queue."""

    from src.gui.outpaint_dialog import OutpaintDialog

    ev, d = run.ev, run.driver
    inputs, parent = ctx.inputs, ctx.parent
    extents = {side: int(inputs["outpaint_extents"][side]) for side in _SIDES}
    width, height = outpaint_size(ctx.settings, inputs)
    review = open_in_review(run, parent["job_id"], ctx.source, "outpaint")
    jobs_before = len(run.job_rows())
    d.invoke(review.extend_canvas_button, label="Review: Extend Canvas...")
    dialog = d.wait_until(
        lambda: _toplevel(run.root, OutpaintDialog),
        timeout=20,
        description="the Extend Canvas dialog opens",
    )
    d.wait_until(
        lambda: not dialog._busy and dialog.preview_button.instate(["!disabled"]),
        timeout=30,
        description="Extend Canvas has loaded the source",
        evidence=lambda: dialog.status.get(),
    )
    support = dialog.support.get()
    ev.observe("outpaint_support", support)
    run.require("outpaint", "outpaint_target_supported", "Supported target" in support, support)
    run.check(
        "outpaint",
        "queue_not_offered_before_preview",
        dialog.queue_button.instate(["disabled"]),
        "Add to Queue enabled before a preview",
    )
    for side in _SIDES:
        if extents[side]:
            d.set_variable(getattr(dialog, side), extents[side], label=f"Extend canvas {side}")
    d.type_in_text(dialog.prompt, inputs["outpaint_prompt"], label="Outpainting prompt")
    d.pump(0.3)
    shown_size = dialog.dimensions.get()
    ev.observe("outpaint_dimensions", shown_size)
    run.check(
        "outpaint",
        "dialog_shows_the_frozen_canvas_size",
        f"{width} × {height}" in shown_size,
        f"{shown_size!r} (expected {width} × {height})",
    )
    run.snap("outpaint_draft")
    d.invoke(dialog.preview_button, label="Extend Canvas: Preview frozen job")
    d.wait_until(
        lambda: dialog.queue_button.instate(["!disabled"]),
        timeout=60,
        description="the frozen outpaint preview is ready",
        evidence=lambda: dialog.status.get(),
    )
    details = dialog.details.get("1.0", "end-1c")
    ev.observe("outpaint_frozen_preview", details[:3000])
    run.snap("outpaint_preview")
    run.check(
        "outpaint",
        "preview_shows_the_expanded_geometry",
        str(width) in details and str(height) in details,
        details[:300],
    )
    run.check(
        "outpaint",
        "preview_queued_nothing",
        len(run.job_rows()) == jobs_before,
        f"{len(run.job_rows())} jobs",
    )
    d.invoke(dialog.queue_button, label="Extend Canvas: Add prepared job to Queue")
    run.assert_plan_agreed()
    child = wait_new_job(run, ctx, "outpaint", "the outpaint job reaches a terminal state")
    run.snap("outpaint_done")

    njr = read_njr(run.repository_path, child["job_id"])
    stage = _config(njr).get("img2img") or {}
    frozen = stage.get("image_edit_inputs") or {}
    record = frozen.get("outpaint") or {}
    source_meta = njr.get("source") or {}
    ev.observe(
        "outpaint_lineage",
        {k: v for k, v in source_meta.items() if "parent" in k}
        | {"edit_operation": stage.get("edit_operation")},
    )
    run.check(
        "outpaint",
        "parent_job_recorded",
        source_meta.get("parent_job_id") == parent["job_id"],
        f"{source_meta}",
    )
    run.check(
        "outpaint",
        "parent_artifact_is_the_source_digest",
        source_meta.get("parent_artifact_id") == f"sha256:{ctx.source_identity['sha256']}",
        f"{source_meta.get('parent_artifact_id')}",
    )
    run.check(
        "outpaint",
        "frozen_extents_and_geometry",
        record.get("extents") == extents
        and record.get("expanded_size") == {"width": width, "height": height}
        and stage.get("edit_operation") == "outpaint",
        f"{record.get('extents')} {record.get('expanded_size')} {stage.get('edit_operation')}",
    )
    outputs = result_images(child, exclude=ctx.source)
    run.require(
        "outpaint", "outpaint_image_recorded", bool(outputs), f"{child['artifact_references']}"
    )
    media = inspect_image(outputs[0])
    ev.observe("outpaint_media", media)
    run.check(
        "outpaint",
        "outpaint_image_has_the_frozen_canvas_size",
        media["valid"] and (media.get("width"), media.get("height")) == (width, height),
        f"{media.get('width')}x{media.get('height')} vs {width}x{height}",
    )
    original = Path(str((frozen.get("original") or {}).get("path") or ctx.source))
    expanded = Path(str((frozen.get("source") or {}).get("path") or ""))
    if media["valid"] and expanded.is_file() and record.get("original_bbox"):
        measure = outpaint_preservation(original, expanded, outputs[0], record["original_bbox"])
        ev.observe("outpaint_preservation", measure, source=evidence_source(run))
        run.check(
            "outpaint",
            "original_pixels_preserved_at_the_frozen_bbox",
            bool(measure.get("original_identical")),
            f"{measure}",
        )
        run.check(
            "outpaint",
            "new_canvas_area_was_generated",
            int(measure.get("exterior_changed_pixels") or 0) > 0,
            f"{measure}",
        )
    else:
        run.check(
            "outpaint", "original_pixels_preserved_at_the_frozen_bbox", False, f"inputs {frozen}"
        )
    _source_unchanged(run, ctx, "outpaint")
    d.invoke(dialog.close_button, label="Extend Canvas: Close")
    release_dialog(run, dialog)
    compare_with_parent(run, parent["job_id"], child["job_id"], "outpaint")


def run_regenerate(run: GoldenRun, ctx: EditContext) -> None:
    """History: Iterate..., Regenerate with Changes; edit the draft (seed, prompt), Preview, Add to Queue."""

    from src.gui.history_iterate_dialog import HistoryIterateDialog

    ev, d, w = run.ev, run.driver, run.window
    inputs, parent = ctx.inputs, ctx.parent
    d.select_tab(w.center_notebook, "Pipeline")
    history = select_history_row(run, parent["job_id"])
    d.invoke(history.iterate_btn, label="History: Iterate...")
    dialog = d.wait_until(
        lambda: _toplevel(run.root, HistoryIterateDialog),
        timeout=15,
        description="the Iterate dialog opens",
    )
    run.snap("regenerate_iterate_dialog")
    run.require(
        "regenerate",
        "regenerate_offered_for_the_completed_txt2img_job",
        not dialog.regenerate_btn.instate(["disabled"]),
        "Regenerate with Changes is disabled for the completed source job",
    )
    jobs_before = len(run.job_rows())
    if run.app_state.has_unsent_pipeline_work():
        # The Pipeline still holds a draft: the product asks before replacing it; the operator confirms.
        run.answer_yesno(True)
        ev.observe("replace_pipeline_draft", "confirmed")
    d.invoke(dialog.regenerate_btn, label="Regenerate with Changes")
    panel = w.pipeline_tab.history_variation_panel
    d.wait_until(
        lambda: bool(panel._body.winfo_manager()),
        timeout=20,
        description="the Pipeline shows the editable variation",
        evidence=lambda: history.replay_status_var.get(),
    )
    d.pump(0.5)
    ev.observe("regenerate_status", history.replay_status_var.get())
    run.check(
        "regenerate",
        "loading_the_draft_queued_nothing",
        len(run.job_rows()) == jobs_before,
        f"{len(run.job_rows())} jobs",
    )
    shown_prompt = panel.positive_text.get("1.0", "end-1c")
    run.check(
        "regenerate",
        "draft_shows_the_source_recipe",
        shown_prompt.startswith(inputs["prompt"])
        and str(panel.seed_var.get()) == str(ctx.settings["seed"]),
        f"prompt {shown_prompt[:60]!r} seed {panel.seed_var.get()!r}",
    )
    new_prompt = shown_prompt + str(inputs["regenerate_prompt_suffix"])
    d.type_in_text(panel.positive_text, new_prompt, label="Variation positive prompt")
    d.type_in_entry(panel.seed_entry, str(inputs["regenerate_seed"]), label="Variation seed")
    d.pump(0.5)
    changes = panel.changes_var.get()
    ev.observe("regenerate_changes", {"summary": changes, "error": panel.error_var.get()})
    run.check(
        "regenerate", "draft_accepts_the_edits", not panel.error_var.get(), panel.error_var.get()
    )
    run.check(
        "regenerate",
        "draft_summarizes_the_changes",
        "seed:" in changes and "positive prompt edited" in changes,
        changes,
    )
    run.snap("regenerate_draft")
    preview = w.pipeline_tab.preview_panel
    d.wait_until(
        lambda: str(preview.job_count_label.cget("text")).strip() == "Job: 1"
        and preview.add_to_queue_button.instate(["!disabled"]),
        timeout=60,
        description="the Preview compiles the edited variation",
        evidence=lambda: f"{preview.job_count_label.cget('text')}",
    )
    wait_text(
        run,
        preview,
        str(inputs["regenerate_prompt_suffix"]).strip(),
        description="the preview shows the edited prompt",
    )
    run.check(
        "regenerate",
        "preview_queued_nothing",
        len(run.job_rows()) == jobs_before,
        f"{len(run.job_rows())} jobs",
    )
    run.snap("regenerate_preview")
    d.invoke(preview.add_to_queue_button, label="Add to Queue (variation)")
    run.assert_plan_agreed()
    child = wait_new_job(run, ctx, "regenerate", "the regenerated job reaches a terminal state")

    njr, parent_njr = (
        read_njr(run.repository_path, child["job_id"]),
        read_njr(run.repository_path, parent["job_id"]),
    )
    config, parent_config = _config(njr), _config(parent_njr)
    source_meta = njr.get("source") or {}
    prompt = str((njr.get("workload") or {}).get("positive_prompt") or config.get("prompt") or "")
    ev.observe(
        "regenerate_njr",
        {
            "lineage": {k: v for k, v in source_meta.items() if "parent" in k},
            "seed": config.get("seed"),
            "steps": config.get("steps"),
            "size": [config.get("width"), config.get("height")],
            "model": config.get("model"),
        },
    )
    run.check(
        "regenerate",
        "parent_job_recorded",
        source_meta.get("parent_job_id") == parent["job_id"]
        and child["job_id"] != parent["job_id"],
        f"{source_meta}",
    )
    run.check(
        "regenerate",
        "parent_artifact_is_the_source_digest",
        source_meta.get("parent_artifact_id") == f"sha256:{ctx.source_identity['sha256']}",
        f"{source_meta.get('parent_artifact_id')}",
    )
    run.check(
        "regenerate",
        "only_the_edited_fields_changed",
        config.get("seed") == inputs["regenerate_seed"]
        and str(inputs["regenerate_prompt_suffix"]) in prompt
        and all(
            config.get(k) == parent_config.get(k)
            for k in ("model", "steps", "width", "height", "cfg_scale", "sampler")
        ),
        f"seed {config.get('seed')} prompt {prompt[:80]!r}",
    )
    outputs = result_images(child, exclude=ctx.source)
    run.require(
        "regenerate", "regenerated_image_recorded", bool(outputs), f"{child['artifact_references']}"
    )
    media = inspect_image(outputs[0])
    ev.observe("regenerate_media", media)
    run.check(
        "regenerate",
        "regenerated_image_decodes_at_the_source_size",
        media["valid"]
        and (media.get("width"), media.get("height"))
        == (ctx.settings["width"], ctx.settings["height"]),
        f"{media}",
    )
    _source_unchanged(run, ctx, "regenerate")
    compare_with_parent(run, parent["job_id"], child["job_id"], "regenerate")


def run_replay(run: GoldenRun, ctx: EditContext) -> None:
    """History: Replay Job on the source; a new NJR whose recorded parent is the source, compared with it."""

    ev, d, w = run.ev, run.driver, run.window
    parent = ctx.parent
    d.select_tab(w.center_notebook, "Pipeline")
    history = select_history_row(run, parent["job_id"])
    run.require(
        "replay",
        "replay_offered_for_the_completed_job",
        not history.replay_btn.instate(["disabled"]),
        "Replay Job is disabled for the completed source job",
    )
    d.invoke(history.replay_btn, label="History: Replay Job")
    run.assert_plan_agreed()
    status = history.replay_status_var.get()
    ev.observe("replay_status", status)
    run.check(
        "replay", "replay_reports_a_new_queued_job", "Replay queued as a new job" in status, status
    )
    child = wait_new_job(run, ctx, "replay", "the replayed job reaches a terminal state")

    njr, parent_njr = (
        read_njr(run.repository_path, child["job_id"]),
        read_njr(run.repository_path, parent["job_id"]),
    )
    config, parent_config = _config(njr), _config(parent_njr)
    source_meta = njr.get("source") or {}
    metadata = (njr.get("provenance") or {}).get("metadata") or {}
    keys = (
        "model",
        "prompt",
        "negative_prompt",
        "seed",
        "steps",
        "width",
        "height",
        "cfg_scale",
        "sampler",
        "scheduler",
    )
    differing = {
        k: (parent_config.get(k), config.get(k))
        for k in keys
        if parent_config.get(k) != config.get(k)
    }
    ev.observe(
        "replay_njr",
        {
            "lineage": {k: v for k, v in source_meta.items() if "parent" in k},
            "replay": metadata.get("replay"),
            "recipe_differences": differing,
        },
    )
    run.check(
        "replay",
        "replay_is_a_new_identity_with_parent_lineage",
        child["job_id"] != parent["job_id"]
        and source_meta.get("parent_job_id") == parent["job_id"]
        and metadata.get("replay") is True,
        f"{source_meta} replay={metadata.get('replay')}",
    )
    run.check("replay", "replay_recipe_equals_the_recorded_parent", not differing, f"{differing}")
    outputs = result_images(child, exclude=ctx.source)
    run.require(
        "replay", "replayed_image_recorded", bool(outputs), f"{child['artifact_references']}"
    )
    media = inspect_image(outputs[0])
    ev.observe("replay_media", media)
    run.check(
        "replay",
        "replayed_image_is_a_new_file",
        media["valid"] and outputs[0].resolve() != ctx.source.resolve(),
        f"{media}",
    )
    reproduced = bool(media["valid"]) and pixels_identical(ctx.source, outputs[0])
    ev.observe(
        "replay_reproduced_the_parent_pixels",
        {
            "reproduced": reproduced,
            "parent_sha256": ctx.source_identity["sha256"],
            "replay_sha256": media.get("sha256"),
        },
        source=evidence_source(run),
    )
    if not is_physical(run):
        # The loopback backend is deterministic in seed and prompt, so an exact replay must give the same pixels; a
        # real backend's determinism is recorded above as a measurement, never required.
        run.check(
            "replay", "replay_reproduced_the_parent_pixels", reproduced, f"{media.get('sha256')}"
        )
    _source_unchanged(run, ctx, "replay")
    compare_with_parent(run, parent["job_id"], child["job_id"], "replay")
