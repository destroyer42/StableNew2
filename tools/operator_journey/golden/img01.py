"""IMG-01: Prompt -> generated image -> History, through visible controls and the canonical queue."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.golden.gui import combo_for, select_history_row, set_toggle, wait_text
from tools.operator_journey.golden.media import inspect_image
from tools.operator_journey.golden.provenance import settings_report, text_identity
from tools.operator_journey.golden.session import GoldenRun, JourneyAbort, JourneyHold

PACK_NAME = "golden_img01"
PROMPT = "golden path image, a lighthouse at dusk, oil painting"
NEGATIVE = "blurry, low quality"
STEPS = 6
SEED = 424242
WIDTH = HEIGHT = 512


def read_njr(repository_path: Path, job_id: str) -> dict[str, Any]:
    """The immutable NJR snapshot exactly as the repository stored it (read-only connection)."""

    connection = sqlite3.connect(f"file:{repository_path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        row = connection.execute(
            "SELECT njr_snapshot FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    finally:
        connection.close()
    return (json.loads(row[0] or "{}").get("normalized_job") or {}) if row else {}


def run_img01(
    run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None
) -> None:
    from src.gui.view_contracts.pipeline_composer_contract import STAGE_LABELS

    ev, d, w = run.ev, None, None
    # A physical run reads every operator-controlled value from its frozen plan; simulated runs use the defaults.
    frozen = physical or {}
    frozen_settings, frozen_inputs = frozen.get("settings") or {}, frozen.get("inputs") or {}
    prompt = str(frozen_inputs.get("prompt") or PROMPT)
    negative = str(frozen_inputs.get("negative_prompt") or NEGATIVE)
    pack_name = str(frozen_inputs.get("pack_name") or PACK_NAME)
    steps = int(frozen_settings.get("steps", STEPS))
    seed = int(frozen_settings.get("seed", SEED))
    run.boot_app()
    d, w = run.driver, run.window
    source = "simulated_fixture" if simulated else "observed"
    run.await_models()

    # 2-3. Prompt tab: author a one-slot PromptPack (New, type positive and negative prompt, Save).
    d.select_tab(w.center_notebook, "Prompt")
    tab = w.prompt_tab
    run.answer_string(pack_name)
    d.invoke(d.find_button(tab, "New"), label="Prompt: New pack")
    d.type_in_text(tab.editor, prompt, label="Prompt editor")
    d.type_in_text(tab.negative_editor, negative, label="Negative prompt editor")
    run.snap("prompt")
    run.require(
        "prompt",
        "prompt_visible_in_editor",
        tab.editor.get("1.0", "end-1c").strip() == prompt,
        "the editor does not show the typed prompt",
    )
    pack_file = run.ws.packs_dir / f"{pack_name}.json"
    run.answer_file(str(pack_file))
    d.invoke(d.find_button(tab, "Save"), label="Prompt: Save pack")
    d.wait_until(pack_file.is_file, timeout=10, description="the PromptPack file is saved")

    # 4-6. Pipeline tab: txt2img only, a compatible model, the applied profile, one adjusted setting.
    d.select_tab(w.center_notebook, "Pipeline")
    pipeline = w.pipeline_tab
    for stage, wanted in (("txt2img", True), ("adetailer", False), ("upscale", False)):
        set_toggle(run, pipeline, STAGE_LABELS[stage], wanted)
    base = w.sidebar_panel_v2.base_generation_panel
    models = [str(v) for v in combo_for(run, pipeline, base.model_var).cget("values")]
    run.require("model", "models_offered", bool(models), "the model list is empty")
    wanted_model = ((physical or {}).get("model") or {}).get("name") or models[0]
    match = next((m for m in models if wanted_model.lower() in m.lower()), None)
    if match is None:
        raise JourneyHold(f"model {wanted_model!r} is not selectable in StableNew ({models[:5]})")
    d.select_combobox(combo_for(run, pipeline, base.model_var), match, label="Model")
    profile_text = str(base._profile_strip.status_label.cget("text"))
    ev.observe("generation_profile_status", profile_text)
    ev.observe("requested_model", match, source=source)
    d.set_variable(base.steps_var, steps, label="Steps")
    for variable, wanted, label in (
        (base.width_var, frozen_settings.get("width"), "Width"),
        (base.height_var, frozen_settings.get("height"), "Height"),
    ):
        if wanted is None or str(variable.get()) == str(wanted):
            continue
        offered = [str(v) for v in combo_for(run, pipeline, variable).cget("values")]
        if str(wanted) not in offered:
            raise JourneyHold(
                f"the plan asks for {label.lower()} {wanted}, which the GUI does not offer ({offered})"
            )
        d.set_variable(variable, str(wanted), label=label)
    d.set_variable(base.seed_var, str(seed), label="Seed")
    run.require(
        "settings",
        "gui_reflects_adjustment",
        int(base.steps_var.get()) == steps and str(base.seed_var.get()) == str(seed),
        f"steps={base.steps_var.get()} seed={base.seed_var.get()}",
    )

    # 7-8. Select the pack, let the current stage settings apply, Add to Job; the preview panel shows the plan.
    sidebar = w.sidebar_panel_v2
    d.invoke(sidebar.refresh_packs_button, label="Pack list Refresh")
    d.pump(0.3)
    ev.observe("pack_refresh_feedback", str(sidebar.refresh_packs_button.cget("text")))
    run.snap("after_refresh")
    d.wait_until(
        lambda: pack_name in sidebar._current_pack_names,
        timeout=15,
        description="the saved pack is listed",
        evidence=lambda: f"refresh button text {sidebar.refresh_packs_button.cget('text')!r}; listed packs {list(sidebar._current_pack_names)}; packs dir {sorted(p.name for p in run.ws.packs_dir.iterdir())}",
    )
    d.select_listbox_row(
        sidebar.pack_listbox, sidebar._current_pack_names.index(pack_name), label="Pack list"
    )
    # The pack takes the visible settings only by an explicit, confirmed "Apply to PromptPack" (never implicitly).
    run.answer_yesno(True)
    d.invoke(sidebar.apply_config_button, label="Apply current settings to PromptPack")
    d.wait_until(
        lambda: sidebar._pack_has_saved_config(pack_name),
        timeout=15,
        description="the pack stores the applied settings",
    )
    d.invoke(sidebar.add_to_job_button, label="Add to Job")
    preview = pipeline.preview_panel
    d.wait_until(
        lambda: str(preview.job_count_label.cget("text")).strip() == "Job: 1",
        timeout=60,
        description="the preview panel reports one draft job",
        evidence=lambda: f"{preview.job_count_label.cget('text')}; Add to Job {sidebar.add_to_job_button.cget('state')}",
    )
    d.wait_until(
        lambda: preview.add_to_queue_button.instate(["!disabled"]),
        timeout=60,
        description="Add to Queue becomes available once the preview is compiled",
    )
    wait_text(run, preview, prompt[:30], description="the preview shows the typed prompt")
    run.snap("preview")
    preview_model = str(preview.model_label.cget("text"))
    run.check(
        "preview",
        "preview_shows_selected_model",
        match.split(" [")[0].lower() in preview_model.lower(),
        f"preview model label {preview_model!r}",
    )
    run.check(
        "preview",
        "nothing_queued_by_preview",
        not run.submissions.calls,
        f"{run.submissions.calls}",
    )

    # 9. Submit through the normal GUI control.
    d.invoke(preview.add_to_queue_button, label="Add to Queue")
    run.assert_plan_agreed()
    rows = run.wait_jobs_terminal(1, description="the image job reaches a terminal state")
    run.snap("queue_done")
    job = rows[0]
    ev.observe("job_row", job)
    run.require(
        "execute",
        "job_completed",
        job["status"] == "completed",
        f"{job['status']}: {job['error_message']}",
    )
    run.check(
        "execute",
        "submitted_once_through_job_service",
        len(run.submissions.calls) == 1,
        f"submit_njrs calls: {run.submissions.calls}",
    )

    # 10. NJR reflects the visible intent.
    njr = read_njr(run.repository_path, job["job_id"])
    ev.observe("njr_job_id", job["job_id"])
    run.check(
        "njr",
        "prompt_matches_visible_intent",
        job["njr_positive_prompt"].startswith(prompt),
        f"njr prompt {job['njr_positive_prompt']!r}",
    )
    run.check(
        "njr", "seed_matches_visible_intent", job["njr_seed"] == seed, f"njr seed {job['njr_seed']}"
    )
    blob = json.dumps(njr, default=str)
    run.check("njr", "negative_prompt_in_njr", negative in blob, "negative prompt missing from NJR")
    run.check(
        "njr",
        "model_in_njr",
        match.split(" [")[0].replace(".safetensors", "") in blob,
        f"model {match!r} missing from NJR",
    )

    # 11. Artifact: a decodable image with the requested geometry; backend readback agrees.
    images = [
        Path(r)
        for r in job["artifact_references"]
        if Path(r).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    run.require(
        "artifact",
        "image_artifact_recorded",
        len(images) == 1,
        f"artifact refs {job['artifact_references']}",
    )
    media = inspect_image(images[0])
    ev.observe("image_media", media)
    run.check("artifact", "image_decodes", media["valid"], str(media.get("error")))
    if simulated:
        ev.observe(
            "fixture_image_generator",
            "FakeA1111 solid-colour PNG at the requested size",
            source="simulated_fixture",
        )
    # Requested versus observed settings, read back from the frozen NJR (the same in every mode).
    njr_config = (njr.get("workload") or {}).get("config") or {}
    requested = {
        "model": match.split(" [")[0].replace(".safetensors", ""),
        "steps": steps,
        "seed": seed,
        "prompt": text_identity(prompt),
        "negative_prompt_contained": negative,
    }
    if frozen_settings.get("width") is not None:
        requested["width"] = int(frozen_settings["width"])
        requested["height"] = int(frozen_settings["height"])
    njr_negative = str(njr_config.get("negative_prompt") or "")
    observed = {
        "model": str(njr_config.get("model") or "").replace(".safetensors", ""),
        "steps": njr_config.get("steps"),
        "seed": njr_config.get("seed"),
        "prompt": text_identity(str(njr_config.get("prompt") or "")[: len(prompt)]),
        "negative_prompt_contained": negative if negative in njr_negative else njr_negative,
    }
    if "width" in requested:
        observed["width"], observed["height"] = njr_config.get("width"), njr_config.get("height")
    ev.observe("requested_settings", requested)
    ev.observe("observed_settings", {**observed, "from": "frozen NJR"})
    ev.observe("settings_report", settings_report(requested, observed))
    if run.fake_a1111 is not None:
        payloads = run.fake_a1111.txt2img_payloads
        run.check(
            "backend",
            "one_generation_request",
            len(payloads) == 1,
            f"{len(payloads)} txt2img requests",
        )
        if payloads:
            p0 = payloads[0]
            ev.observe(
                "backend_readback",
                {
                    "steps": p0.get("steps"),
                    "seed": p0.get("seed"),
                    "width": p0.get("width"),
                    "height": p0.get("height"),
                    "from": "request received by the loopback backend",
                },
            )
            run.check(
                "backend",
                "backend_readback_matches_intent",
                p0.get("seed") == seed
                and p0.get("steps") == steps
                and str(p0.get("prompt", "")).startswith(prompt),
                f"payload seed={p0.get('seed')} steps={p0.get('steps')}",
            )
            run.check(
                "artifact",
                "image_geometry_matches_request",
                (media.get("width"), media.get("height")) == (p0.get("width"), p0.get("height")),
                f"{media.get('width')}x{media.get('height')} vs {p0.get('width')}x{p0.get('height')}",
            )

    # 12-13. History record: select the row, show the recorded image, check provenance text.
    d.select_tab(w.center_notebook, "Pipeline")
    panel = select_history_row(run, job["job_id"])
    if not panel.show_artifact_var.get():
        d.invoke(d.find(panel, (ttk.Checkbutton,), text="Show media"), label="History Show media")
    d.wait_until(
        lambda: panel._shown_artifact_path,
        timeout=15,
        description="History shows the recorded artifact",
    )
    run.snap("history")
    run.check(
        "history",
        "history_artifact_is_the_job_image",
        Path(str(panel._shown_artifact_path)).resolve() == images[0].resolve(),
        f"{panel._shown_artifact_path} != {images[0]}",
    )
    run.check(
        "history",
        "open_control_enabled",
        str(panel.artifact_open_btn.cget("state")) != "disabled",
        "Open is disabled for a recorded image",
    )
    ev.observe(
        "history_open_not_clicked",
        "Open launches the system viewer; enabled state verified instead",
    )
    entry = panel._entries.get(job["job_id"])
    run.check(
        "history",
        "history_record_present",
        entry is not None and str(entry.status).lower().endswith("completed"),
        f"history entry {entry!r}",
    )
    run.checkpoint("img01_done")
    run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")
