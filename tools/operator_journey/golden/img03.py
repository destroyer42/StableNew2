"""IMG-03: History iteration and image editing, through visible controls and the canonical queue.

A completed txt2img result is opened from History ("Iterate..." then "Edit Image in Review"), a mask is painted with the
real pointer on the mask canvas, the frozen job is previewed, queued, and the edit is compared with its parent.  The
frozen inputs may select three more steps (``img03_steps``): Extend Canvas (outpaint), Regenerate with Changes and Replay.

Every operator-controlled value (prompts, source settings, mask strokes, denoise, outpaint margins, the regenerate
change, the optional steps) is read from the plan target in a physical run and from ``img03_frozen.default_inputs()``
otherwise.  The simulated Forge returns a synthetic image the size of its init image and does not composite a masked
edit: a simulated run proves orchestration, provenance and the product's own preservation guarantees, never edit quality
or backend compositing (``protected region byte-identical`` is asserted only in a physical run).
"""

from __future__ import annotations

import gc
import json
import os
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.operator_journey.golden import flow
from tools.operator_journey.golden.gui import combo_for, select_history_row
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.img03_frozen import (
    EDIT_PROMPT,
    NEGATIVE,
    PACK_NAME,
    PROMPT,
    SEED,
    SIZE,
    STEPS,
    expected_job_count,
    mask_bbox,
    region_preservation,
    resolved_inputs,
    resolved_settings,
    selected_steps,
)
from tools.operator_journey.golden.media import inspect_image, sha256_file
from tools.operator_journey.golden.session import (
    GoldenRun,
    JourneyAbort,
    JourneyHold,
    file_identity,
)
from tools.operator_journey.tk_driver import iter_widgets

__all__ = [
    "EDIT_PROMPT",
    "NEGATIVE",
    "PACK_NAME",
    "PROMPT",
    "SEED",
    "SIZE",
    "STEPS",
    "EditContext",
    "register_frozen_checkpoint",
    "run_img03",
]

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _toplevel(root: tk.Misc, kind: type) -> Any:
    return next((w for w in iter_widgets(root) if isinstance(w, kind) and w.winfo_exists()), None)


def release_dialog(run: GoldenRun, dialog: Any) -> None:
    """Make sure a closed dialog is destroyed and the destruction has been processed."""

    if dialog is not None and dialog.winfo_exists():
        dialog.destroy()
    run.driver.pump(0.3)


def collect_on_tk_thread() -> None:
    """Collect the closed dialogs of a finished step on the Tk thread.

    A dialog's Tk variables sit in reference cycles; left to the cyclic collector they can be finalized on a worker
    thread, where tkinter reports "main thread is not in main loop" while deleting them.  Called between steps, once
    the step's own references are gone.
    """

    gc.collect()


@dataclass
class EditContext:
    """What the optional steps share with the main edit: the frozen inputs and the completed source job."""

    inputs: dict[str, Any]
    settings: dict[str, int]
    parent: dict[str, Any]
    source: Path
    source_identity: dict[str, Any]
    model_title: str
    known_jobs: list[str] = field(default_factory=list)
    source_siblings: list[str] = field(default_factory=list)


def is_physical(run: GoldenRun) -> bool:
    """Only a true physical run asserts backend behaviour (compositing, determinism); a rehearsal never does."""

    return run.ev.execution_mode == "physical"


def evidence_source(run: GoldenRun) -> str:
    return "observed" if is_physical(run) else "simulated_fixture"


def result_images(row: dict[str, Any], *, exclude: Path | None = None) -> list[Path]:
    """The job's produced still images (never its frozen inputs or the source it edited)."""

    return [
        Path(r)
        for r in row["artifact_references"]
        if Path(r).suffix.lower() in _IMAGE_SUFFIXES
        and "image_edit_inputs" not in Path(r).parts
        and (exclude is None or Path(r).resolve() != exclude.resolve())
    ]


def wait_new_job(run: GoldenRun, ctx: EditContext, phase: str, description: str) -> dict[str, Any]:
    """Wait until exactly one more job is terminal; the frozen-plan gate is consulted on every probe."""

    rows = run.wait_jobs_terminal(len(ctx.known_jobs) + 1, description=description)
    new = [r for r in rows if r["job_id"] not in ctx.known_jobs]
    run.require(phase, "exactly_one_new_job", len(new) == 1, f"{len(new)} new jobs: {new}")
    child = new[0]
    ctx.known_jobs.append(child["job_id"])
    run.ev.observe(
        "job_row", child
    )  # every job row: the physical runner classifies stop conditions from these
    run.require(
        phase,
        f"{phase}_job_completed",
        child["status"] == "completed",
        f"{child['status']}: {child['error_message']}",
    )
    return child


def open_in_review(run: GoldenRun, job_id: str, source: Path, phase: str) -> Any:
    """History: select the row, Iterate..., Edit Image in Review; Review then lists exactly the job's image."""

    from src.gui.history_iterate_dialog import HistoryIterateDialog

    d, w = run.driver, run.window
    d.select_tab(w.center_notebook, "Pipeline")
    history = select_history_row(run, job_id)
    run.require(
        phase,
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
    run.snap(f"{phase}_iterate_dialog")
    d.invoke(d.find_button(dialog, "Edit Image in Review"), label="Edit Image in Review")
    review = w.review_tab
    d.wait_until(
        lambda: [Path(p).resolve() for p in review._image_index_by_row] == [source.resolve()],
        timeout=20,
        description="Review lists the handed-off image",
        evidence=lambda: f"{history.replay_status_var.get()} {list(review._image_index_by_row)}",
    )
    d.pump(1.0)
    d.select_listbox_row(review.images_list, 0, label="Review image row")
    return review


def compare_with_parent(
    run: GoldenRun, parent_id: str, child_id: str, phase: str, *, finding: str = ""
) -> dict[str, Any] | None:
    """History: Compare with Parent for ``child_id``; the read-only viewer must show exactly that direct pair."""

    from src.gui.history_compare_dialog import HistoryCompareDialog

    d, w = run.driver, run.window
    d.select_tab(w.center_notebook, "Pipeline")
    history = select_history_row(run, child_id)
    offered = not history.compare_btn.instate(["disabled"])
    run.check(
        phase,
        "compare_offered_for_the_child" if phase != "compare" else "compare_offered_for_the_edit",
        offered,
        f"{finding}Compare with Parent is disabled for {child_id} (no recorded parent job)",
    )
    run.snap(f"{phase}_compare_state")
    if not offered:
        return None
    jobs_before = len(run.job_rows())
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
    run.snap(f"{phase}_compare")
    differences = [
        " ".join(str(v) for v in viewer.tree.item(i, "values")) for i in viewer.tree.get_children()
    ]
    shown = {
        "parent": viewer.parent_title_var.get(),
        "child": viewer.child_title_var.get(),
        "identity": viewer.identity_var.get(),
        "differences": differences,
    }
    run.ev.observe(f"{phase}_compare_viewer", shown)
    run.check(
        phase,
        "viewer_shows_the_direct_parent_and_the_edit"
        if phase == "compare"
        else "viewer_shows_the_direct_parent_and_the_child",
        parent_id in shown["parent"] and child_id in shown["child"],
        f"{shown}",
    )
    run.check(phase, "viewer_lists_typed_differences", bool(differences), "no differences listed")
    run.check(
        phase,
        "viewer_is_read_only_and_queued_nothing",
        len(run.job_rows()) == jobs_before,
        f"{len(run.job_rows())} jobs, {jobs_before} before",
    )
    release_dialog(run, viewer)
    return shown


def register_frozen_checkpoint(run: GoldenRun, target: dict[str, Any]) -> None:
    """Give the disposable workspace's AssetRegistry byte evidence for the plan's exact checkpoint (physical only).

    A masked edit is offered only for a registry-resolved SDXL base checkpoint, and the isolated workspace starts with
    an empty registry.  The product's own ``AssetRegistry.refresh`` hashes the one frozen file (read-only) into the
    workspace cache; the digest must equal the plan's, and the product's own model policy must resolve it to the SDXL
    base family.  Anything else is a HOLD before the application starts.  Nothing outside the workspace is written,
    and the registry root is an empty workspace folder, so no other model, LoRA or embedding is scanned or hashed.
    """

    from src.assets.registry import AssetRegistry
    from src.image_backends.model_policy import RegistryFamilyLookup, resolve_model_policy
    from src.state.workspace_paths import workspace_paths

    model = target.get("model") or {}
    path = Path(str(model.get("path") or ""))
    if not path.is_file():
        raise JourneyHold(f"the frozen checkpoint {path} is not a file on this host")
    cache = workspace_paths.asset_registry_cache()
    if cache.parent != run.ws.state_dir.resolve():
        raise JourneyAbort(
            "checkpoint evidence must be written inside the activated disposable workspace"
        )
    root = run.ws.root / "frozen-webui-root"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["STABLENEW_WEBUI_ROOT"] = str(root)  # restored when the workspace is released
    registry = AssetRegistry(webui_root=root)
    registry.refresh(checkpoint_paths=[path])
    digest = registry.verified_sha256(path)
    policy = resolve_model_policy(
        str(model.get("name") or path.name), family_lookup=RegistryFamilyLookup(registry)
    )
    run.ev.observe(
        "frozen_checkpoint_registration",
        {
            "path": str(path),
            "plan_sha256": model.get("sha256"),
            "registry_sha256": digest,
            "policy_id": policy.policy_id,
            "registry_root": str(root),
            "from": "product AssetRegistry.refresh of the one frozen file into the disposable workspace",
        },
    )
    if digest != model.get("sha256"):
        raise JourneyHold(
            f"the checkpoint's registry digest {digest} differs from the plan's {model.get('sha256')}"
        )
    if policy.policy_id != "sdxl":
        raise JourneyHold(
            f"the frozen checkpoint resolves to policy {policy.policy_id!r}; masked edits need a registry-resolved "
            "SDXL base checkpoint"
        )


def _set_dimensions(run: GoldenRun, width: int, height: int) -> None:
    """The visible width/height controls; a size the GUI does not offer is a HOLD (as in IMG-01)."""

    base = run.window.sidebar_panel_v2.base_generation_panel
    pipeline = run.window.pipeline_tab
    for variable, wanted, label in (
        (base.width_var, width, "Width"),
        (base.height_var, height, "Height"),
    ):
        if str(variable.get()) == str(wanted):
            continue
        offered = [str(v) for v in combo_for(run, pipeline, variable).cget("values")]
        if str(wanted) not in offered:
            raise JourneyHold(
                f"the plan asks for {label.lower()} {wanted}, which the GUI does not offer ({offered})"
            )
        run.driver.set_variable(variable, str(wanted), label=label)


def _source_job(
    run: GoldenRun, inputs: dict[str, Any], settings: dict[str, int], physical: Any
) -> EditContext:
    """1. A completed image to iterate on: one ordinary txt2img job through the canonical queue."""

    ev, d = run.ev, run.driver
    flow.author_pack(run, inputs["pack_name"], inputs["prompt"], inputs["negative_prompt"])
    flow.txt2img_only(run)
    wanted = ((physical or {}).get("model") or {}).get("name")
    title = flow.choose_model(run, str(wanted) if wanted else None)
    _set_dimensions(run, settings["width"], settings["height"])
    flow.set_generation(run, steps=settings["steps"], seed=settings["seed"])
    preview = flow.preview_pack_job(run, inputs["pack_name"], inputs["prompt"])
    d.invoke(preview.add_to_queue_button, label="Add to Queue")
    run.assert_plan_agreed()
    rows = run.wait_jobs_terminal(1, description="the source job reaches a terminal state")
    parent = rows[0]
    ev.observe("job_row", parent)
    run.require(
        "source",
        "source_job_completed",
        parent["status"] == "completed",
        f"{parent['status']}: {parent['error_message']}",
    )
    images = result_images(parent)
    run.require("source", "source_image_recorded", bool(images), f"{parent['artifact_references']}")
    source = images[0]
    identity = file_identity(source)
    media = inspect_image(source)
    ev.observe(
        "source",
        {
            "job": parent["job_id"],
            "image": str(source),
            "sha256": identity["sha256"],
            "media": media,
        },
    )
    run.check(
        "source",
        "source_geometry_matches_the_frozen_settings",
        (media.get("width"), media.get("height")) == (settings["width"], settings["height"]),
        f"{media.get('width')}x{media.get('height')} vs {settings['width']}x{settings['height']}",
    )
    fake = run.fake_a1111
    if fake is not None:
        run.check(
            "source",
            "source_generated_by_txt2img_only",
            len(fake.txt2img_payloads) == 1 and not fake.img2img_payloads,
            f"{len(fake.txt2img_payloads)} txt2img {len(fake.img2img_payloads)} img2img",
        )
    return EditContext(
        inputs=inputs,
        settings=settings,
        parent=parent,
        source=source,
        source_identity=identity,
        model_title=title,
        known_jobs=[parent["job_id"]],
    )


def _img2img_requests(run: GoldenRun) -> int | None:
    fake = run.fake_a1111
    return None if fake is None else len(fake.img2img_payloads)


def _masked_edit(run: GoldenRun, ctx: EditContext) -> dict[str, Any]:
    """2-9. Iterate into Review, paint the frozen strokes, preview, queue, verify provenance and preservation."""

    from src.gui.mask_editor_dialog import MaskEditorDialog

    ev, d = run.ev, run.driver
    inputs, parent, source = ctx.inputs, ctx.parent, ctx.source
    review = open_in_review(run, parent["job_id"], source, "iterate")
    run.snap("review")
    run.check(
        "iterate",
        "review_holds_exactly_the_source_image",
        [Path(p).resolve() for p in review._image_index_by_row] == [source.resolve()],
        f"{list(review._image_index_by_row)}",
    )
    run.check(
        "iterate",
        "iterating_queued_nothing",
        len(run.job_rows()) == 1 and not _img2img_requests(run),
        f"{len(run.job_rows())} jobs",
    )

    # 4. Edit Mask...: the dialog loads the source, the frozen strokes are painted with the pointer, the prompt is typed.
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
    width, height = canvas.winfo_width(), canvas.winfo_height()
    strokes = [
        ((int(x0 * width), int(y0 * height)), (int(x1 * width), int(y1 * height)))
        for x0, y0, x1, y1 in inputs["mask_strokes"]
    ]
    for start, end in strokes:
        d.drag_stroke(canvas, start, end, label="Mask: paint stroke")
    painted_mask = editor.document.mask.copy()
    painted = sum(1 for value in painted_mask.getdata() if value)
    painted_box = painted_mask.point(lambda v: 255 if v else 0).getbbox()
    ev.observe(
        "mask_painted",
        {
            "pixels": painted,
            "bbox": list(painted_box) if painted_box else None,
            "canvas": [width, height],
            "strokes_on_canvas": strokes,
        },
    )
    run.snap("mask_painted")
    run.require(
        "mask",
        "pointer_strokes_painted_a_mask",
        painted > 0,
        "no mask pixels after the frozen strokes",
    )
    d.type_in_text(editor.prompt, inputs["edit_prompt"], label="Editing prompt")
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
    run.check(
        "preview", "preview_shows_the_edit_prompt", inputs["edit_prompt"] in shown, shown[:300]
    )
    run.check(
        "preview",
        "preview_queued_nothing",
        len(run.job_rows()) == 1 and not _img2img_requests(run),
        f"{len(run.job_rows())} jobs",
    )

    # The frozen denoise is applied after the first preview: a changed draft must invalidate it.
    denoise = float(inputs["edit_denoise"])
    if abs(float(editor.denoise.get()) - denoise) > 1e-9:
        d.set_variable(editor.denoise, denoise, label="Denoising strength")
        d.pump(0.3)
        run.check(
            "preview",
            "changing_a_setting_invalidates_the_preview",
            editor.queue_button.instate(["disabled"]),
            "queue still enabled after a change",
        )
    else:
        ev.observe(
            "invalidation_not_exercised",
            "the frozen denoise equals the editor's default, so no setting was changed after the first preview",
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
    child = wait_new_job(run, ctx, "execute", "the edit job reaches a terminal state")
    ev.observe("edit_job", child)
    run.snap("edit_done")
    run.check(
        "execute",
        "new_job_identity",
        child["job_id"] != parent["job_id"],
        "the edit reused the parent's job id",
    )
    requests = _img2img_requests(run)
    if requests is not None:
        run.check(
            "execute", "exactly_one_edit_request", requests == 1, f"{requests} img2img requests"
        )
        payload = run.fake_a1111.img2img_payloads[0] if requests else {}
        run.check(
            "execute",
            "request_carried_a_mask_and_the_edit_prompt",
            bool(payload.get("mask")) and inputs["edit_prompt"] in str(payload.get("prompt")),
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
        "lineage_is_bound_to_the_verified_source_artifact",
        (njr.get("source") or {}).get("parent_artifact_id")
        == f"sha256:{ctx.source_identity['sha256']}"
        and child["job_id"] != parent["job_id"],
        f"the edit is a distinct job and its parent artifact is the source digest: {lineage}",
    )
    run.check(
        "njr",
        "source_sha256_recorded",
        ctx.source_identity["sha256"] in blob,
        "the edit NJR does not freeze the source digest",
    )
    stage = ((njr.get("workload") or {}).get("config") or {}).get("img2img") or {}
    frozen = stage.get("image_edit_inputs") or {}
    mask_record = frozen.get("mask") or {}
    mask_path = Path(str(mask_record.get("path") or ""))
    mask_ok = mask_path.is_file() and sha256_file(mask_path) == mask_record.get("sha256")
    frozen_box = mask_bbox(mask_path) if mask_ok else None
    ev.observe(
        "mask_geometry",
        {
            "njr_mask": mask_record,
            "frozen_bbox": list(frozen_box) if frozen_box else None,
            "painted_bbox": list(painted_box) if painted_box else None,
            "mask_blur": stage.get("mask_blur"),
            "denoising_strength": stage.get("denoising_strength"),
            "inpaint_full_res": stage.get("inpaint_full_res"),
            "steps": stage.get("steps"),
        },
    )
    run.check(
        "njr",
        "mask_geometry_frozen",
        mask_ok
        and (mask_record.get("width"), mask_record.get("height"))
        == (ctx.settings["width"], ctx.settings["height"])
        and frozen_box is not None
        and frozen_box == painted_box,
        f"NJR mask {mask_record} bbox {frozen_box} vs painted {painted_box}",
    )
    run.check(
        "njr",
        "edit_prompt_frozen",
        inputs["edit_prompt"] in blob,
        "edit prompt missing from the NJR",
    )

    # 8. The edited result is a new, valid image beside the original; the original is untouched.
    edits = result_images(child, exclude=source)
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
        file_identity(source) == ctx.source_identity,
        f"{file_identity(source)} vs {ctx.source_identity}",
    )
    run.check(
        "artifact",
        "no_prior_file_overwritten_or_removed",
        all((source.parent / name).exists() for name in ctx.source_siblings),
        "a file beside the source disappeared",
    )
    if mask_ok and media["valid"]:
        blur = int(stage.get("mask_blur") or 0)
        measure = region_preservation(source, edited, mask_path, margin=4 * blur + 4)
        ev.observe("masked_edit_region_preservation", measure, source=evidence_source(run))
        run.check(
            "artifact",
            "edited_region_changed",
            bool(measure.get("edited_region_changed")),
            f"{measure}",
        )
        if is_physical(run):
            run.check(
                "artifact",
                "protected_region_byte_identical",
                bool(measure.get("protected_identical")),
                f"{measure}",
            )
        else:
            ev.observe(
                "protected_region_not_asserted",
                "the loopback backend returns a whole synthetic image and does not composite a masked edit; "
                "protected-region preservation is asserted only against a real Forge",
                source="simulated_fixture",
            )
    d.invoke(d.find_button(editor, "Close"), label="Mask editor: Close")
    release_dialog(run, editor)
    run.check(
        "mask",
        "closing_the_editor_preserved_the_source",
        file_identity(source) == ctx.source_identity,
        "the source changed on close",
    )
    return child


def _refusals(run: GoldenRun, ctx: EditContext) -> None:
    """10. Unsupported operations refuse honestly: the parent has no parent; Edit Mask needs an image."""

    from src.gui.mask_editor_dialog import MaskEditorDialog

    d, w = run.driver, run.window
    jobs = len(ctx.known_jobs)
    history = select_history_row(run, ctx.parent["job_id"])
    run.check(
        "refuse",
        "compare_not_offered_without_a_parent",
        history.compare_btn.instate(["disabled"]),
        "Compare with Parent is enabled for a job that has no parent",
    )
    review = w.review_tab
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
    run.ev.observe("edit_mask_without_selection", refusal)
    run.snap("refusal")
    run.check(
        "refuse",
        "edit_mask_without_an_image_refuses_with_a_reason",
        any("Select an image first" in r for r in refusal)
        and _toplevel(run.root, MaskEditorDialog) is None,
        f"{refusal}",
    )
    requests = _img2img_requests(run)
    run.check(
        "refuse",
        "refusals_queued_nothing",
        len(run.job_rows()) == jobs and requests in (None, 1),
        f"{len(run.job_rows())} jobs",
    )


def run_img03(
    run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None
) -> None:
    from tools.operator_journey.golden import img03_steps

    ev = run.ev
    inputs = resolved_inputs(physical)
    settings = resolved_settings(physical)
    steps = selected_steps(inputs)
    ev.observe(
        "frozen_inputs",
        {
            **inputs,
            "settings": settings,
            "from": "frozen plan target" if physical is not None else "journey defaults",
        },
    )
    run.boot_app()
    run.await_models()

    ctx = _source_job(run, inputs, settings, physical)
    ctx.source_siblings = sorted(p.name for p in ctx.source.parent.iterdir())
    child = _masked_edit(run, ctx)
    collect_on_tk_thread()

    # 9. History + Compare with Parent: the edit lists as its own entry; the viewer shows parent and edit.
    compare_with_parent(run, ctx.parent["job_id"], child["job_id"], "compare", finding="GP832-F3: ")
    _refusals(run, ctx)
    collect_on_tk_thread()

    # 11-13. The optional steps the frozen inputs select, in a fixed order.
    for name, step in (
        ("outpaint", img03_steps.run_outpaint),
        ("regenerate", img03_steps.run_regenerate),
        ("replay", img03_steps.run_replay),
    ):
        if name in steps:
            step(run, ctx)
            collect_on_tk_thread()
    skipped = [s for s in img03_steps.OPTIONAL_STEPS if s not in steps]
    ev.observe("optional_steps", {"run": list(steps), "not_selected": skipped})

    # Totals, identity and teardown.
    rows = run.job_rows()
    run.check(
        "totals",
        "every_selected_step_submitted_exactly_one_job",
        len(rows) == expected_job_count(inputs)
        and sorted(r["job_id"] for r in rows) == sorted(ctx.known_jobs),
        f"{len(rows)} jobs for {expected_job_count(inputs)} expected",
    )
    run.check(
        "totals",
        "source_image_is_still_byte_identical",
        file_identity(ctx.source) == ctx.source_identity,
        f"{file_identity(ctx.source)} vs {ctx.source_identity}",
    )
    parent_njr = read_njr(run.repository_path, ctx.parent["job_id"])
    njr_model = str(((parent_njr.get("workload") or {}).get("config") or {}).get("model") or "")
    runtime = (physical or {}).get("runtime") or {}
    ev.observe(
        "model_and_runtime_identity",
        {
            "selected_model_title": ctx.model_title,
            "njr_model": njr_model,
            "plan_model": (physical or {}).get("model"),
            "runtime_kind": runtime.get("kind"),
            "runtime_identity": runtime.get("identity"),
            "runtime_ownership": runtime.get("ownership"),
            "base_url": runtime.get("base_url"),
        },
        source=evidence_source(run),
    )
    if physical is not None and (physical.get("model") or {}).get("name"):
        wanted = Path(str(physical["model"]["name"])).stem.lower()
        run.check(
            "totals",
            "model_identity_matches_the_plan",
            wanted in njr_model.lower(),
            f"{njr_model!r}",
        )
    run.checkpoint("img03_done")
    run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")
