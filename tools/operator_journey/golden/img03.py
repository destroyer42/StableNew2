"""IMG-03: History iteration and a masked image edit, through visible controls and the canonical queue.

A completed txt2img result is opened from History ("Iterate..." then "Edit Image in Review"), a mask is painted with the
real pointer on the mask canvas, the frozen job is previewed, queued, and the edit is compared with its parent.  The
simulated Forge returns a synthetic image the size of its init image: this journey proves orchestration, provenance
and preservation, never edit quality.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import Any

from tools.operator_journey.golden import flow
from tools.operator_journey.golden.gui import select_history_row
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.media import inspect_image
from tools.operator_journey.golden.session import GoldenRun, JourneyAbort, file_identity
from tools.operator_journey.tk_driver import iter_widgets

PACK_NAME = "golden_img03"
PROMPT = "golden path edit, a lighthouse on a rocky coast, watercolour"
NEGATIVE = "blurry, low quality"
EDIT_PROMPT = "a bright red buoy floating near the rocks"
SEED = 303303
STEPS = 8
SIZE = 512


def _toplevel(root: tk.Misc, kind: type) -> Any:
    return next((w for w in iter_widgets(root) if isinstance(w, kind) and w.winfo_exists()), None)


def run_img03(
    run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None
) -> None:
    from src.gui.history_compare_dialog import HistoryCompareDialog
    from src.gui.history_iterate_dialog import HistoryIterateDialog
    from src.gui.mask_editor_dialog import MaskEditorDialog

    if physical is not None:
        raise JourneyAbort("IMG-03 has no physical lane")
    ev = run.ev
    run.boot_app()
    d, w = run.driver, run.window
    run.await_models()

    # 1. A completed image to iterate on: one ordinary txt2img job through the canonical queue.
    flow.author_pack(run, PACK_NAME, PROMPT, NEGATIVE)
    flow.txt2img_only(run)
    flow.choose_model(run)
    card = w.pipeline_tab.stage_cards_panel.txt2img_card
    d.set_variable(card.width_var, SIZE, label="txt2img width")
    d.set_variable(card.height_var, SIZE, label="txt2img height")
    flow.set_generation(run, steps=STEPS, seed=SEED)
    preview = flow.preview_pack_job(run, PACK_NAME, PROMPT)
    d.invoke(preview.add_to_queue_button, label="Add to Queue")
    run.assert_plan_agreed()
    rows = run.wait_jobs_terminal(1, description="the source job reaches a terminal state")
    parent = rows[0]
    run.require(
        "source",
        "source_job_completed",
        parent["status"] == "completed",
        f"{parent['status']}: {parent['error_message']}",
    )
    images = [
        Path(r)
        for r in parent["artifact_references"]
        if Path(r).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    run.require("source", "source_image_recorded", bool(images), f"{parent['artifact_references']}")
    source = images[0]
    source_identity = file_identity(source)
    parent_siblings = sorted(p.name for p in source.parent.iterdir())
    ev.observe(
        "source",
        {
            "job": parent["job_id"],
            "image": str(source),
            "sha256": source_identity["sha256"],
            "media": inspect_image(source),
        },
    )
    fake = run.fake_a1111
    run.check(
        "source",
        "source_generated_by_txt2img_only",
        len(fake.txt2img_payloads) == 1 and not fake.img2img_payloads,
        f"{len(fake.txt2img_payloads)} txt2img {len(fake.img2img_payloads)} img2img",
    )

    # 2-3. History: select the row, Iterate..., Edit Image in Review (nothing is queued by either choice).
    d.select_tab(w.center_notebook, "Pipeline")
    history = select_history_row(run, parent["job_id"])
    run.snap("history_selected")
    run.require(
        "iterate",
        "iterate_offered_for_the_completed_job",
        not history.iterate_btn.instate(["disabled"]),
        "Iterate... is disabled for a completed image job",
    )
    d.invoke(history.iterate_btn, label="History: Iterate...")
    dialog = d.wait_until(
        lambda: _toplevel(run.root, HistoryIterateDialog),
        timeout=15,
        description="the Iterate dialog opens",
    )
    run.snap("iterate_dialog")
    d.invoke(d.find_button(dialog, "Edit Image in Review"), label="Edit Image in Review")
    review = w.review_tab
    d.wait_until(
        lambda: bool(review.images_list.size()),
        timeout=20,
        description="Review lists the handed-off image",
        evidence=lambda: str(history.replay_status_var.get()),
    )
    d.pump(1.0)
    run.snap("review")
    listed = [str(p) for p in review._image_index_by_row]
    run.check(
        "iterate",
        "review_holds_exactly_the_source_image",
        [Path(p).resolve() for p in listed] == [source.resolve()],
        f"{listed}",
    )
    run.check(
        "iterate",
        "iterating_queued_nothing",
        len(run.job_rows()) == 1 and not fake.img2img_payloads,
        f"{len(run.job_rows())} jobs",
    )
    d.select_listbox_row(review.images_list, 0, label="Review image row")

    # 4. Edit Mask...: the dialog loads the source, a stroke is painted with the pointer, the prompt describes the edit.
    d.invoke(review.edit_mask_button, label="Review: Edit Mask...")
    editor = d.wait_until(
        lambda: _toplevel(run.root, MaskEditorDialog),
        timeout=20,
        description="the mask editor opens",
    )
    d.wait_until(
        lambda: editor.document is not None and not editor._busy,
        timeout=30,
        description="the mask editor has loaded the source",
        evidence=lambda: editor.status.get(),
    )
    d.pump(0.8)
    run.check(
        "mask",
        "preview_is_not_offered_before_any_work_is_queued",
        editor.queue_button.instate(["disabled"]),
        "queue enabled before a preview",
    )
    canvas = editor.canvas
    cx, cy = canvas.winfo_width() // 2, canvas.winfo_height() // 2
    d.drag_stroke(canvas, (cx - 70, cy - 30), (cx + 70, cy + 30), label="Mask: paint stroke")
    d.drag_stroke(canvas, (cx - 70, cy + 30), (cx + 70, cy - 30), label="Mask: paint stroke")
    painted = sum(1 for value in editor.document.mask.getdata() if value)
    ev.observe("mask_painted_pixels", painted)
    run.snap("mask_painted")
    run.require(
        "mask", "pointer_strokes_painted_a_mask", painted > 0, "no mask pixels after two strokes"
    )
    d.type_in_text(editor.prompt, EDIT_PROMPT, label="Editing prompt")
    d.pump(0.3)
    run.check(
        "mask",
        "unpreviewed_draft_cannot_be_queued",
        editor.queue_button.instate(["disabled"]),
        "queue enabled before Preview",
    )

    # 5. Preview the frozen job: source identity, mask and effective settings are shown; nothing is queued yet.
    ev.observe(
        "editor_before_preview",
        {
            "status": editor.status.get(),
            "preview_state": list(editor.preview_button.state()),
            "busy": editor._busy,
        },
    )
    d.invoke(editor.preview_button, label="Preview frozen job")
    d.wait_until(
        lambda: not editor.queue_button.instate(["disabled"]),
        timeout=60,
        description="the frozen preview is ready",
        evidence=lambda: editor.status.get(),
    )
    shown = editor.details.get("1.0", "end-1c")
    run.snap("mask_preview")
    ev.observe("frozen_preview", shown[:3000])
    run.check(
        "preview",
        "preview_names_the_source",
        str(source) in shown or source.name in shown,
        shown[:300],
    )
    run.check("preview", "preview_shows_the_edit_prompt", EDIT_PROMPT in shown, shown[:300])
    run.check(
        "preview",
        "preview_queued_nothing",
        len(run.job_rows()) == 1 and not fake.img2img_payloads,
        f"{len(run.job_rows())} jobs",
    )

    # A changed draft invalidates the preview (the frozen job must be re-previewed).
    d.set_variable(editor.denoise, 0.5, label="Denoising strength")
    d.pump(0.3)
    run.check(
        "preview",
        "changing_a_setting_invalidates_the_preview",
        editor.queue_button.instate(["disabled"]),
        "queue still enabled after a change",
    )
    d.invoke(editor.preview_button, label="Preview frozen job (again)")
    d.wait_until(
        lambda: not editor.queue_button.instate(["disabled"]),
        timeout=60,
        description="the second preview is ready",
        evidence=lambda: editor.status.get(),
    )

    # 6. Queue it; the edit is a new job with its own identity.
    d.invoke(editor.queue_button, label="Add prepared job to Queue")
    run.assert_plan_agreed()
    d.wait_until(
        lambda: len(run.job_rows()) >= 2,
        timeout=60,
        description="the edit job is queued",
        evidence=lambda: editor.status.get(),
    )
    rows = run.wait_jobs_terminal(2, description="the edit job reaches a terminal state")
    child = next(r for r in rows if r["job_id"] != parent["job_id"])
    ev.observe("edit_job", child)
    run.snap("edit_done")
    run.require(
        "execute",
        "edit_job_completed",
        child["status"] == "completed",
        f"{child['status']}: {child['error_message']}",
    )
    run.check(
        "execute",
        "new_job_identity",
        child["job_id"] != parent["job_id"],
        "the edit reused the parent's job id",
    )
    run.check(
        "execute",
        "exactly_one_edit_request",
        len(fake.img2img_payloads) == 1,
        f"{len(fake.img2img_payloads)} img2img requests",
    )
    payload = fake.img2img_payloads[0] if fake.img2img_payloads else {}
    run.check(
        "execute",
        "request_carried_a_mask_and_the_edit_prompt",
        bool(payload.get("mask")) and EDIT_PROMPT in str(payload.get("prompt")),
        f"keys={sorted(payload)[:20]}",
    )

    # 7. Provenance: frozen NJR lineage, mask geometry, source identity.
    njr = read_njr(run.repository_path, child["job_id"])
    blob = json.dumps(njr, default=str)
    ev.observe("edit_njr_keys", sorted(njr))
    lineage = {
        k: v
        for k, v in (njr.get("source") or {}).items()
        if "parent" in k or k in {"source_path", "source_artifact_id"}
    }
    ev.observe("edit_lineage_fields", lineage)
    run.check(
        "njr",
        "parent_job_recorded",
        (njr.get("source") or {}).get("parent_job_id") == parent["job_id"],
        f"GP832-F3: the masked edit's frozen source carries {lineage}",
    )
    run.check(
        "njr",
        "source_sha256_recorded",
        source_identity["sha256"] in blob,
        "the edit NJR does not freeze the source digest",
    )
    run.check("njr", "mask_geometry_frozen", "mask" in blob.lower(), "no mask recorded in the NJR")
    run.check("njr", "edit_prompt_frozen", EDIT_PROMPT in blob, "edit prompt missing from the NJR")

    # 8. The edited result is a new, valid image beside the original; the original is untouched.
    edits = [
        Path(r)
        for r in child["artifact_references"]
        if Path(r).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        and Path(r).resolve() != source.resolve()
        and "image_edit_inputs" not in Path(r).parts
    ]
    run.require("artifact", "edited_image_recorded", bool(edits), f"{child['artifact_references']}")
    edited = edits[0]
    media = inspect_image(edited)
    ev.observe("edited_media", media)
    run.check("artifact", "edited_image_decodes", media["valid"], str(media.get("error")))
    run.check(
        "artifact",
        "edited_image_is_a_different_file",
        edited.resolve() != source.resolve(),
        "the edit overwrote the source path",
    )
    run.check(
        "artifact",
        "source_image_is_byte_identical",
        file_identity(source) == source_identity,
        f"{file_identity(source)} vs {source_identity}",
    )
    run.check(
        "artifact",
        "no_prior_file_overwritten_or_removed",
        all((source.parent / name).exists() for name in parent_siblings),
        "a file beside the source disappeared",
    )

    d.invoke(d.find_button(editor, "Close"), label="Mask editor: Close")
    d.pump(0.3)
    run.check(
        "mask",
        "closing_the_editor_preserved_the_source",
        file_identity(source) == source_identity,
        "the source changed on close",
    )

    # 9. History + Compare with Parent: the edit lists as its own entry; the viewer shows parent and edit.
    d.select_tab(w.center_notebook, "Pipeline")
    history = select_history_row(run, child["job_id"])
    offered = not history.compare_btn.instate(["disabled"])
    run.check(
        "compare",
        "compare_offered_for_the_edit",
        offered,
        "GP832-F3: Compare with Parent is disabled for the masked edit (no recorded parent job)",
    )
    run.snap("compare_state")
    if offered:
        d.invoke(history.compare_btn, label="History: Compare with Parent")
        viewer = d.wait_until(
            lambda: _toplevel(run.root, HistoryCompareDialog),
            timeout=15,
            description="the compare viewer opens",
        )
        d.wait_until(
            lambda: len(viewer.tree.get_children()) > 0,
            timeout=30,
            description="the compare viewer lists differences",
            evidence=lambda: str(viewer.limits_var.get()),
        )
        d.pump(1.0)
        run.snap("compare")
        differences = [
            " ".join(str(v) for v in viewer.tree.item(i, "values"))
            for i in viewer.tree.get_children()
        ]
        ev.observe("compare_differences", differences)
        run.check(
            "compare", "viewer_lists_typed_differences", bool(differences), "no differences listed"
        )
        run.check(
            "compare",
            "viewer_is_read_only_and_queued_nothing",
            len(run.job_rows()) == 2 and len(fake.img2img_payloads) == 1,
            f"{len(run.job_rows())} jobs",
        )
        viewer.destroy()
        d.pump(0.3)

    # 10. Unsupported operations refuse honestly: the parent job has no parent to compare with.
    history = select_history_row(run, parent["job_id"])
    run.check(
        "refuse",
        "compare_not_offered_without_a_parent",
        history.compare_btn.instate(["disabled"]),
        "Compare with Parent is enabled for a job that has no parent",
    )
    d.select_tab(w.center_notebook, "Review - Adv")
    d.invoke(d.find_button(review, "Clear"), label="Review: Clear")
    d.pump(0.3)
    dialogs, responder = run.seam, run.responder
    before = len(dialogs.history), len(responder.seen) if responder is not None else 0
    d.invoke(review.edit_mask_button, label="Review: Edit Mask... (nothing selected)")
    d.pump(0.5)
    refusal = [f"{r.title}: {r.message}" for r in dialogs.history[before[0] :]]
    if responder is not None:  # the Windows driver meets the real native message box
        refusal += [f"{seen['title']}: {seen['text']}" for seen in responder.seen[before[1] :]]
    ev.observe("edit_mask_without_selection", refusal)
    run.snap("refusal")
    run.check(
        "refuse",
        "edit_mask_without_an_image_refuses_with_a_reason",
        any("Select exactly one" in r for r in refusal)
        and _toplevel(run.root, MaskEditorDialog) is None,
        f"{refusal}",
    )
    run.check(
        "refuse",
        "refusals_queued_nothing",
        len(run.job_rows()) == 2 and len(fake.img2img_payloads) == 1,
        f"{len(run.job_rows())} jobs",
    )
    run.checkpoint("img03_done")
    run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")
