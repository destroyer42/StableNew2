"""IMG-02: PromptPack, model profiles and effective settings, through visible controls and the canonical queue.

Models are synthetic registry fixtures, never real checkpoints: two declared-SDXL checkpoints (compatible, one
research profile), one declared-SD1 checkpoint (the product labels the family but has no qualified profile) and the
exact name the FLUX.2 Klein 4B profile resolves (which fixes sampler, steps, CFG and refuses a negative prompt).  A name
alone never establishes compatibility; each expectation below is checked against what StableNew itself shows.
"""

from __future__ import annotations

import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.golden import flow
from tools.operator_journey.golden.gui import select_history_row
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.media import inspect_image
from tools.operator_journey.golden.session import GoldenRun, JourneyAbort, file_identity
from tools.operator_journey.tk_driver import iter_widgets

PACK_NAME = "golden_img02"
PROMPT = "golden path profiles, a harbour at dawn, watercolour"
EDITED_PROMPT = "golden path profiles, a harbour at dawn, watercolour, gulls overhead"
DRAFT_PROMPT = "UNSAVED DRAFT that must not survive a reload"
NEGATIVE = "blurry, low quality"
SEED = 202602
STEPS_OVERRIDE = 12
ALT, LEGACY, KLEIN = "operator-journey-alt", "operator-journey-legacy", "flux-2-klein-4b-fp8"


def _visible_labels(run: GoldenRun, pattern: str) -> list[str]:
    found: list[str] = []
    for widget in iter_widgets(run.root):
        try:
            if isinstance(widget, (ttk.Label, tk.Label)) and widget.winfo_viewable():
                text = str(widget.cget("text"))
                if re.search(pattern, text):
                    found.append(text[:300])
        except tk.TclError:
            continue
    return found


def _effective(run: GoldenRun) -> dict[str, Any]:
    base = run.window.sidebar_panel_v2.base_generation_panel
    strip = base._profile_strip
    return {
        "model": str(base.model_var.get()),
        "profile_choices": [str(v) for v in strip.combo.cget("values")],
        "profile": str(strip.profile_var.get()),
        "status": str(strip.status_label.cget("text")),
        "sampler": str(base.sampler_var.get()),
        "scheduler": str(base.scheduler_var.get()),
        "steps": int(base.steps_var.get()),
        "cfg": float(base.cfg_var.get()),
        "width": str(base.width_var.get()),
        "height": str(base.height_var.get()),
    }


def _pack_document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _preview_facts(run: GoldenRun, preview: Any) -> dict[str, Any]:
    """What the Preview panel shows for the compiled draft (read-only), including its effective-settings evidence."""

    d = run.driver
    if not preview.effective_toggle.instate(["selected"]):
        d.invoke(preview.effective_toggle, label="Show effective settings / prompt evidence")
        d.pump(0.5)
    return {
        "model": str(preview.model_label.cget("text")),
        "sampler": str(preview.sampler_label.cget("text")),
        "steps": str(preview.steps_label.cget("text")),
        "cfg": str(preview.cfg_label.cget("text")),
        "seed": str(preview.seed_label.cget("text")),
        "negative": str(preview.negative_prompt_label.cget("text")),
        "adaptation": str(preview.adaptation_label.cget("text")),
        "error": str(preview.preview_error_label.cget("text")),
        "effective_text": preview.effective_text.get("1.0", "end-1c")[:2000],
    }


def run_img02(run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None) -> None:
    if physical is not None:
        raise JourneyAbort("IMG-02 has no physical lane")
    ev = run.ev
    run.boot_app()
    d, w = run.driver, run.window
    run.await_models()

    # 1-2. Prompt tab: create and save a pack; reload it (an unsaved draft must not survive); edit; save; reopen.
    pack_file = flow.author_pack(run, PACK_NAME, PROMPT, NEGATIVE)
    tab = w.prompt_tab
    first = _pack_document(pack_file)
    first_identity = file_identity(pack_file)
    ev.observe("pack_document_keys", sorted(first))
    run.require(
        "pack",
        "saved_pack_holds_both_prompts",
        PROMPT in json.dumps(first) and NEGATIVE in json.dumps(first),
        "the saved PromptPack does not contain the typed prompts",
    )

    def load_from_list() -> None:
        names = [info.name for info in tab._visible_pack_infos]
        run.require("pack", "pack_listed_in_prompt_tab", PACK_NAME in names, f"{names}")
        d.select_listbox_row(tab.pack_listbox, names.index(PACK_NAME), label="Prompt pack list")
        d.invoke(d.find_button(tab, "Load"), label="Prompt: Load pack")
        d.pump(0.5)

    d.type_in_text(tab.editor, DRAFT_PROMPT, label="Prompt editor (unsaved draft)")
    load_from_list()
    run.check(
        "pack",
        "reload_discards_the_unsaved_draft",
        tab.editor.get("1.0", "end-1c").strip() == PROMPT,
        f"editor shows {tab.editor.get('1.0', 'end-1c')!r}",
    )
    d.type_in_text(tab.editor, EDITED_PROMPT, label="Prompt editor (edit)")
    d.invoke(d.find_button(tab, "Save"), label="Prompt: Save pack")
    d.wait_until(
        lambda: file_identity(pack_file)["sha256"] != first_identity["sha256"],
        timeout=10,
        description="the edited PromptPack is saved",
    )
    edited = _pack_document(pack_file)
    run.check("pack", "identity_survives_edit", edited.get("name") == first.get("name") and pack_file.name == f"{PACK_NAME}.json", f"{first.get('name')!r} -> {edited.get('name')!r}")
    run.check("pack", "edit_is_in_the_saved_file", EDITED_PROMPT in json.dumps(edited), "the edit is not in the saved file")
    d.select_tab(w.center_notebook, "Pipeline")
    d.select_tab(w.center_notebook, "Prompt")
    d.type_in_text(tab.editor, DRAFT_PROMPT, label="Prompt editor (unsaved draft)")
    load_from_list()
    run.check("pack", "reopened_pack_shows_the_edit", tab.editor.get("1.0", "end-1c").strip() == EDITED_PROMPT, f"{tab.editor.get('1.0', 'end-1c')!r}")
    run.snap("pack_reopened")

    # 3-6. Pipeline tab: each model shows its own profile and settings; nothing leaks from the previous selection.
    flow.txt2img_only(run)
    seen: dict[str, dict[str, Any]] = {}
    for key, wanted in (("main", None), ("alt", ALT), ("legacy", LEGACY), ("klein", KLEIN), ("alt_again", ALT)):
        title = flow.choose_model(run, wanted)
        d.pump(1.5)
        seen[key] = {"title": title, **_effective(run)}
        run.snap(f"model_{key}")
    ev.observe("model_profiles", seen)
    main, alt, legacy, klein, again = (seen[k] for k in ("main", "alt", "legacy", "klein", "alt_again"))
    sdxl_values = {k: main[k] for k in ("sampler", "scheduler", "steps", "cfg")}
    run.check("profiles", "declared_sdxl_gets_the_sdxl_research_profile", "SDXL" in main["profile"] and "SDXL" in main["status"], f"{main['profile']!r} / {main['status']!r}")
    run.check("profiles", "second_compatible_model_gets_the_same_profile", alt["profile"] == main["profile"], f"{alt['profile']!r} vs {main['profile']!r}")
    run.check("profiles", "unqualified_family_has_no_profile", legacy["profile_choices"] == ["No profile (keep current settings)"] and "not qualified" in legacy["status"], f"{legacy['profile_choices']} / {legacy['status']!r}")
    run.check("profiles", "unqualified_family_keeps_current_settings", {k: legacy[k] for k in sdxl_values} == sdxl_values, f"{legacy}")
    run.check("profiles", "klein_profile_fixes_its_sampling", (klein["sampler"], klein["scheduler"], klein["steps"], klein["cfg"]) == ("Euler", "Beta", 4, 1.0), f"{klein}")
    run.check("profiles", "no_klein_setting_leaks_into_the_next_sdxl_model", {k: again[k] for k in sdxl_values} == sdxl_values, f"{again} vs {sdxl_values}")

    # 7. Model-aware prompting: with Klein selected the Prompt tab explains what does not apply (never rewrites).
    flow.choose_model(run, KLEIN)
    d.select_tab(w.center_notebook, "Prompt")
    d.pump(1.0)
    notices = _visible_labels(run, r"(?i)klein|negative|optimizer")
    ev.observe("klein_prompt_notices", notices)
    run.snap("prompt_klein")
    joined = " ".join(notices).lower()
    run.check("prompting", "negative_prompt_notice_for_klein", "negative" in joined and "not support" in joined, f"{notices}")
    run.check("prompting", "optimizer_notice_for_klein", "optimizer" in joined, f"{notices}")
    run.check("prompting", "authored_text_is_not_rewritten", tab.editor.get("1.0", "end-1c").strip() == EDITED_PROMPT, f"{tab.editor.get('1.0', 'end-1c')!r}")

    # 8. Preview the effective Klein job: nothing is submitted; the compiler states what it adapted.
    d.select_tab(w.center_notebook, "Pipeline")
    preview = flow.preview_pack_job(run, PACK_NAME, EDITED_PROMPT)
    klein_preview = _preview_facts(run, preview)
    ev.observe("klein_preview", klein_preview)
    run.snap("klein_preview")
    run.check("preview", "preview_shows_klein_sampling", "Euler" in klein_preview["sampler"] and "4" in klein_preview["steps"], f"{klein_preview}")
    run.check("preview", "nothing_submitted_by_preview", not run.submissions.calls, f"{run.submissions.calls}")
    d.invoke(preview.clear_draft_button, label="Clear Draft")
    d.wait_until(lambda: str(preview.job_count_label.cget("text")).strip() != "Job: 1", timeout=15, description="the Klein draft is cleared")

    # 9. Back to an SDXL model with its own settings, preview, then submit through the normal queue.
    title = flow.choose_model(run, ALT)
    flow.set_generation(run, steps=STEPS_OVERRIDE, seed=SEED)
    preview = flow.preview_pack_job(run, PACK_NAME, EDITED_PROMPT)
    sdxl_preview = _preview_facts(run, preview)
    ev.observe("sdxl_preview", sdxl_preview)
    run.snap("sdxl_preview")
    run.check("preview", "preview_shows_selected_model", ALT in sdxl_preview["model"], f"{sdxl_preview['model']!r}")
    run.check("preview", "preview_shows_the_adjusted_steps", str(STEPS_OVERRIDE) in sdxl_preview["steps"], f"{sdxl_preview['steps']!r}")
    run.check("preview", "negative_prompt_back_for_sdxl", NEGATIVE in sdxl_preview["negative"] or NEGATIVE in sdxl_preview["effective_text"], f"{sdxl_preview['negative']!r}")
    run.check("preview", "still_nothing_submitted", not run.submissions.calls, f"{run.submissions.calls}")
    d.invoke(preview.add_to_queue_button, label="Add to Queue")
    run.assert_plan_agreed()
    rows = run.wait_jobs_terminal(1, description="the image job reaches a terminal state")
    job = rows[0]
    ev.observe("job_row", job)
    run.require("execute", "job_completed", job["status"] == "completed", f"{job['status']}: {job['error_message']}")

    # 10. The frozen NJR carries what the operator saw.
    njr = read_njr(run.repository_path, job["job_id"])
    config = (njr.get("workload") or {}).get("config") or {}
    blob = json.dumps(njr, default=str)
    frozen_sampler = config.get("sampler_name") or config.get("sampler")
    ev.observe("frozen_settings", {**{k: config.get(k) for k in ("model", "scheduler", "steps", "cfg_scale", "seed", "width", "height")}, "sampler": frozen_sampler, "config_keys": sorted(config)})
    run.check("njr", "model_matches_the_gui", ALT in str(config.get("model")), f"{config.get('model')!r}")
    run.check("njr", "steps_match_the_gui", config.get("steps") == STEPS_OVERRIDE, f"{config.get('steps')!r}")
    run.check("njr", "sampler_matches_the_gui", str(frozen_sampler) == again["sampler"], f"{frozen_sampler!r} vs {again['sampler']!r}")
    run.check("njr", "cfg_matches_the_gui", float(config.get("cfg_scale") or 0) == again["cfg"], f"{config.get('cfg_scale')!r} vs {again['cfg']!r}")
    run.check("njr", "edited_prompt_is_frozen", job["njr_positive_prompt"].startswith(EDITED_PROMPT), f"{job['njr_positive_prompt']!r}")
    run.check("njr", "negative_prompt_is_frozen", NEGATIVE in blob, "the negative prompt is missing from the NJR")
    run.check("njr", "no_klein_profile_on_an_sdxl_job", "flux2_klein" not in blob, "a Klein profile reference leaked into the SDXL job")
    run.check("njr", "pack_identity_in_provenance", PACK_NAME in blob, "the PromptPack name is not in the NJR")
    run.check("queue", "submitted_exactly_once", len(run.submissions.calls) == 1, f"{run.submissions.calls}")

    # 11. Output and History.
    images = [Path(r) for r in job["artifact_references"] if Path(r).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    run.require("artifact", "one_image_recorded", len(images) == 1, f"{job['artifact_references']}")
    media = inspect_image(images[0])
    ev.observe("image_media", media)
    run.check("artifact", "image_decodes", media["valid"], str(media.get("error")))
    payloads = run.fake_a1111.txt2img_payloads if run.fake_a1111 else []
    run.check("backend", "one_generation_request", len(payloads) == 1, f"{len(payloads)}")
    if payloads:
        run.check("backend", "backend_received_the_adjusted_steps", payloads[0].get("steps") == STEPS_OVERRIDE and payloads[0].get("seed") == SEED, f"steps={payloads[0].get('steps')} seed={payloads[0].get('seed')}")
    d.select_tab(w.center_notebook, "Pipeline")
    panel = select_history_row(run, job["job_id"])
    entry = panel._entries.get(job["job_id"])
    run.check("history", "history_record_completed", entry is not None and str(entry.status).lower().endswith("completed"), f"{entry!r}")
    run.snap("history")
    run.check("pack", "pack_identity_unchanged_by_the_job", _pack_document(pack_file).get("name") == first.get("name"), "the pack name changed")
    run.checkpoint("img02_done")
    run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")
