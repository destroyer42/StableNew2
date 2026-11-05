"""Reusable operator flows for the advanced journeys (visible controls only; IMG-01 keeps its own inline copy).

Each helper clicks, types and selects exactly what a person would.  Internal reads (widget state, repository rows) are
used only to wait for or to verify an outcome, never to perform a step.
"""

from __future__ import annotations

from typing import Any

from tools.operator_journey.golden.gui import combo_for, set_toggle, wait_text
from tools.operator_journey.golden.session import GoldenRun, JourneyHold


def author_pack(run: GoldenRun, pack_name: str, prompt: str, negative: str) -> Any:
    """Prompt tab: New pack (named in the dialog), type both prompts, Save.  Returns the saved pack path."""

    d, w = run.driver, run.window
    d.select_tab(w.center_notebook, "Prompt")
    tab = w.prompt_tab
    run.answer_string(pack_name)
    d.invoke(d.find_button(tab, "New"), label="Prompt: New pack")
    d.type_in_text(tab.editor, prompt, label="Prompt editor")
    d.type_in_text(tab.negative_editor, negative, label="Negative prompt editor")
    pack_file = run.ws.packs_dir / f"{pack_name}.json"
    run.answer_file(str(pack_file))
    d.invoke(d.find_button(tab, "Save"), label="Prompt: Save pack")
    d.wait_until(pack_file.is_file, timeout=10, description="the PromptPack file is saved")
    return pack_file


def txt2img_only(run: GoldenRun) -> None:
    """Pipeline tab with only the txt2img stage on (the stages the simulated backend supports)."""

    from src.gui.view_contracts.pipeline_composer_contract import STAGE_LABELS

    run.driver.select_tab(run.window.center_notebook, "Pipeline")
    for stage, wanted in (("txt2img", True), ("adetailer", False), ("upscale", False)):
        set_toggle(run, run.window.pipeline_tab, STAGE_LABELS[stage], wanted)


def model_choices(run: GoldenRun) -> list[str]:
    base = run.window.sidebar_panel_v2.base_generation_panel
    return [str(v) for v in combo_for(run, run.window.pipeline_tab, base.model_var).cget("values")]


def choose_model(run: GoldenRun, wanted: str | None = None) -> str:
    """Select ``wanted`` (substring) in the Model combobox, else the first model; returns the title chosen."""

    base = run.window.sidebar_panel_v2.base_generation_panel
    models = model_choices(run)
    run.require("model", "models_offered", bool(models), "the model list is empty")
    match = next((m for m in models if wanted is None or wanted.lower() in m.lower()), None)
    if match is None:
        raise JourneyHold(f"model {wanted!r} is not selectable in StableNew ({models[:5]})")
    run.driver.select_combobox(
        combo_for(run, run.window.pipeline_tab, base.model_var), match, label="Model"
    )
    return match


def set_generation(run: GoldenRun, *, steps: int, seed: int) -> None:
    base = run.window.sidebar_panel_v2.base_generation_panel
    run.driver.set_variable(base.steps_var, steps, label="Steps")
    run.driver.set_variable(base.seed_var, str(seed), label="Seed")


def preview_pack_job(run: GoldenRun, pack_name: str, prompt: str, *, jobs: int = 1) -> Any:
    """Select the pack, apply the visible settings to it (confirmed), Add to Job, wait for the compiled preview.

    Returns the preview panel.  Nothing is queued: ``Add to Queue`` is the operator's separate, final act.
    """

    d = run.driver
    sidebar = run.window.sidebar_panel_v2
    pipeline = run.window.pipeline_tab
    d.invoke(sidebar.refresh_packs_button, label="Pack list Refresh")
    d.pump(0.3)
    d.wait_until(
        lambda: pack_name in sidebar._current_pack_names,
        timeout=15,
        description="the saved pack is listed",
    )
    d.select_listbox_row(
        sidebar.pack_listbox, sidebar._current_pack_names.index(pack_name), label="Pack list"
    )
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
        lambda: str(preview.job_count_label.cget("text")).strip() == f"Job: {jobs}",
        timeout=60,
        description=f"the preview panel reports {jobs} draft job(s)",
        evidence=lambda: f"{preview.job_count_label.cget('text')}",
    )
    d.wait_until(
        lambda: preview.add_to_queue_button.instate(["!disabled"]),
        timeout=60,
        description="Add to Queue becomes available once the preview is compiled",
    )
    wait_text(run, preview, prompt[:30], description="the preview shows the typed prompt")
    return preview
