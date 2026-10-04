"""PR-IMG-116: truthful FLUX.2 Klein controls (Base Generation) and the explicit Review edit selection."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui_v2.klein_projection import project_klein_controls
from src.image_backends.forge_klein_profile import KLEIN_EDIT_METADATA_KEY

KLEIN = "flux-2-klein-4b-fp8.safetensors"


def test_projection_is_pure_and_klein_specific() -> None:
    inactive = project_klein_controls("sdxl.safetensors", "forge_webui")
    assert not inactive.active and inactive.note == "" and inactive.blocking == ""
    active = project_klein_controls(KLEIN, "forge_webui")
    assert active.active and active.blocking == ""
    assert (active.sampler, active.scheduler, active.steps, active.cfg_scale) == ("Euler", "Beta", 4, 1.0)
    assert [(w, h) for _, w, h in active.presets] == [(768, 1024), (1024, 1024)]
    assert "fixed distilled settings" in active.note


def test_projection_on_a1111_is_an_actionable_message_not_a_backend_switch() -> None:
    projection = project_klein_controls(KLEIN, "a1111_webui")
    assert projection.active
    assert "runs only on the Forge WebUI backend" in projection.blocking
    assert "will not switch backends" in projection.blocking


def _panel(tk_root: tk.Tk, backend_id: str) -> BaseGenerationPanelV2:
    panel = BaseGenerationPanelV2(tk_root, models=["sdxl.safetensors", KLEIN], samplers=["Euler", "Euler a"], include_vae=True)
    panel._klein_projection._backend_id_provider = lambda: backend_id
    return panel


def test_selecting_klein_fixes_and_locks_the_controls_then_sdxl_restores_them(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root, "forge_webui")
    try:
        panel.model_var.set("sdxl.safetensors")
        panel.sampler_var.set("Euler a")
        panel.steps_var.set(30)
        panel.cfg_var.set(7.0)
        panel.width_var.set("832")
        panel.height_var.set("1216")
        before_states = {n: str(getattr(panel, n).cget("state")) for n in ("_sampler_combo", "_steps_spin", "_cfg_spin", "_width_combo")}
        before_presets = tuple(panel._preset_combo["values"])
        before_helper = str(panel._helper_label.cget("text"))

        panel.model_var.set(KLEIN)
        assert (panel.sampler_var.get(), panel.scheduler_var.get(), panel.steps_var.get(), panel.cfg_var.get()) == ("Euler", "Beta", 4, 1.0)
        assert (panel.width_var.get(), panel.height_var.get()) == ("768", "1024")  # nearest qualified default
        assert tuple(panel._preset_combo["values"]) == ("768x1024 (3:4)", "1024x1024 (1:1)")
        for name in ("_sampler_combo", "_scheduler_combo", "_steps_spin", "_cfg_spin", "_width_combo", "_height_combo", "_vae_combo"):
            assert str(getattr(panel, name).cget("state")) == "disabled", name
        assert "fixed distilled settings" in str(panel._helper_label.cget("text"))
        overrides = panel.get_overrides()
        assert (overrides["sampler"], overrides["steps"], overrides["cfg_scale"]) == ("Euler", 4, 1.0)

        panel.model_var.set("sdxl.safetensors")
        assert tuple(panel._preset_combo["values"]) == before_presets
        assert {n: str(getattr(panel, n).cget("state")) for n in before_states} == before_states
        assert str(panel._helper_label.cget("text")) == before_helper
        assert "768x1024 (3:4)" not in panel._preset_map
    finally:
        panel.destroy()


def _configure_non_default_sdxl(panel: BaseGenerationPanelV2) -> dict:
    panel.model_var.set("sdxl.safetensors")
    panel.sampler_var.set("Euler a")
    panel.scheduler_var.set("Karras")
    panel.steps_var.set(37)
    panel.cfg_var.set(6.5)
    panel.vae_var.set("sdxl_vae.safetensors")
    panel.width_var.set("1152")
    panel.height_var.set("896")
    panel.resolution_preset_var.set("1152x896 (9:7)")
    return {
        "sampler": panel.sampler_var.get(), "scheduler": panel.scheduler_var.get(), "steps": panel.steps_var.get(),
        "cfg": panel.cfg_var.get(), "vae": panel.vae_var.get(), "width": panel.width_var.get(),
        "height": panel.height_var.get(), "preset": panel.resolution_preset_var.get(),
    }


def _snapshot(panel: BaseGenerationPanelV2) -> dict:
    return {
        "sampler": panel.sampler_var.get(), "scheduler": panel.scheduler_var.get(), "steps": panel.steps_var.get(),
        "cfg": panel.cfg_var.get(), "vae": panel.vae_var.get(), "width": panel.width_var.get(),
        "height": panel.height_var.get(), "preset": panel.resolution_preset_var.get(),
    }


def test_klein_to_sdxl_round_trip_restores_the_exact_previous_non_default_values(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root, "forge_webui")
    try:
        before = _configure_non_default_sdxl(panel)
        panel.model_var.set(KLEIN)
        assert _snapshot(panel) != before and panel.steps_var.get() == 4  # Klein values are in effect
        panel.model_var.set("sdxl.safetensors")
        assert _snapshot(panel) == before
        assert panel._klein_projection._saved_values == {} and panel._klein_projection._saved_states == {}
    finally:
        panel.destroy()


def test_repeated_refresh_while_klein_is_active_never_overwrites_the_snapshot(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root, "forge_webui")
    try:
        before = _configure_non_default_sdxl(panel)
        panel.model_var.set(KLEIN)
        for _ in range(3):
            panel._klein_projection.refresh()
        panel.model_var.set(KLEIN)  # re-selecting Klein is not a new transition either
        panel.model_var.set("sdxl.safetensors")
        assert _snapshot(panel) == before
    finally:
        panel.destroy()


def test_a_second_klein_session_snapshots_the_values_at_that_time(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root, "forge_webui")
    try:
        _configure_non_default_sdxl(panel)
        panel.model_var.set(KLEIN)
        panel.model_var.set("sdxl.safetensors")
        panel.steps_var.set(21)
        panel.cfg_var.set(4.0)
        panel.model_var.set(KLEIN)
        panel.model_var.set("sdxl.safetensors")
        assert (panel.steps_var.get(), panel.cfg_var.get()) == (21, 4.0)
    finally:
        panel.destroy()


def test_a1111_selection_shows_the_blocking_message_in_the_panel(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root, "a1111_webui")
    try:
        panel.model_var.set(KLEIN)
        assert "runs only on the Forge WebUI backend" in str(panel._helper_label.cget("text"))
    finally:
        panel.destroy()


def test_other_models_never_activate_the_projection(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root, "forge_webui")
    try:
        panel.model_var.set("sdxl.safetensors")
        panel.steps_var.set(30)
        assert panel.steps_var.get() == 30
        assert not panel._klein_projection.active
    finally:
        panel.destroy()


def test_review_adapter_marks_each_target_for_the_explicit_klein_edit(tmp_path: Path) -> None:
    targets = [tmp_path / "a.png"]
    marked = ReviewWorkflowAdapter.with_klein_edit_request({str(targets[0]): {"parent_job_id": "p"}}, targets)
    assert marked == {str(targets[0]): {"parent_job_id": "p", KLEIN_EDIT_METADATA_KEY: True}}
    assert ReviewWorkflowAdapter.with_klein_edit_request(None, targets) == {str(targets[0]): {KLEIN_EDIT_METADATA_KEY: True}}


class _RecordingController:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def on_reprocess_images_with_prompt_delta(self, **kwargs: Any) -> int:
        self.calls.append(kwargs)
        return 1


def _review(tk_root: tk.Tk, tmp_path: Path, count: int = 1) -> tuple[ReviewTabFrame, _RecordingController, list[Path]]:
    controller = _RecordingController()
    tab = ReviewTabFrame(tk_root, app_controller=controller)
    images = []
    for i in range(count):
        path = tmp_path / f"r{i}.png"
        Image.new("RGB", (32, 32)).save(path)
        images.append(path)
    tab.selected_images = list(images)
    return tab, controller, images


def test_review_klein_edit_submits_one_image_as_img2img_replace_with_the_explicit_marker(tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tkinter import messagebox

    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    tab, controller, images = _review(tk_root, tmp_path)
    try:
        tab.stage_adetailer_var.set(True)
        tab.klein_edit_var.set(True)
        assert (tab.stage_img2img_var.get(), tab.stage_adetailer_var.get(), tab.stage_upscale_var.get()) == (True, False, False)
        assert tab.prompt_mode_var.get() == "replace"
        tab.prompt_text.insert("1.0", "change only the jacket to deep red leather")
        tab._reprocess(batch_all=True)
        (call,) = controller.calls
        assert call["stages"] == ["img2img"]
        assert call["image_paths"] == [str(images[0])]
        assert (call["prompt_mode"], call["negative_prompt_mode"], call["batch_size"]) == ("replace", "replace", 1)
        assert call["negative_prompt_delta"] == ""
        assert call["source_metadata_by_image"][str(images[0])][KLEIN_EDIT_METADATA_KEY] is True
    finally:
        tab.destroy()


def test_review_klein_edit_requires_exactly_one_image_and_an_edit_prompt(tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tkinter import messagebox

    warnings: list[str] = []
    monkeypatch.setattr(messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    tab, controller, _ = _review(tk_root, tmp_path, count=2)
    try:
        tab.klein_edit_var.set(True)
        tab.prompt_text.insert("1.0", "make it red")
        tab._reprocess(batch_all=True)  # two images -> multi-reference is not supported
        assert controller.calls == [] and "exactly one" in warnings[-1]
        tab.selected_images = tab.selected_images[:1]
        tab.prompt_text.delete("1.0", tk.END)
        tab._reprocess(batch_all=True)
        assert controller.calls == [] and "Describe the desired edit" in warnings[-1]
    finally:
        tab.destroy()


def test_review_without_the_klein_selection_is_the_unchanged_reprocess_path(tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tkinter import messagebox

    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    tab, controller, images = _review(tk_root, tmp_path)
    try:
        tab.stage_img2img_var.set(True)
        tab._reprocess(batch_all=True)
        (call,) = controller.calls
        assert call["stages"] == ["img2img", "adetailer"]
        assert call["prompt_mode"] == "append"
        assert call["source_metadata_by_image"] is None
    finally:
        tab.destroy()
