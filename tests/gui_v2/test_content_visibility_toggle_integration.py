from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.gui.app_state_v2 import AppStateV2
from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.photo_optimize.store import PhotoOptimizeStore
from src.pipeline.job_models_v2 import NormalizedJobRecord, StagePromptInfo
from src.services.ui_state_store import UIStateStore
from src.utils.config import ConfigManager
from src.utils.image_metadata import ReadPayloadResult
from tests.helpers.gui_harness_v2 import GuiV2Harness


def _read_text(widget: tk.Text) -> str:
    return widget.get("1.0", tk.END).strip()


def _write_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color=(90, 110, 130)).save(path)


def _build_explicit_preview_job() -> NormalizedJobRecord:
    prompt_info = StagePromptInfo(
        original_prompt="nude portrait",
        final_prompt="nude portrait in studio light",
        original_negative_prompt="bad hands",
        final_negative_prompt="bad hands",
        global_negative_applied=False,
        global_negative_terms="",
    )
    return NormalizedJobRecord(
        job_id="job-visibility-1",
        config={
            "model": "test-model",
            "prompt": "nude portrait in studio light",
            "negative_prompt": "bad hands",
            "sampler": "Euler a",
            "steps": 10,
            "cfg_scale": 7.0,
            "width": 512,
            "height": 512,
        },
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        randomizer_summary=None,
        txt2img_prompt_info=prompt_info,
    )


@pytest.mark.gui
def test_main_window_visibility_setting_moves_into_settings_dialog(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")
    with patch("src.gui.main_window_v2.get_ui_state_store", return_value=store):
        harness = GuiV2Harness(tk_root)
        try:
            assert harness.controller.app_state.content_visibility_mode == "nsfw"
            assert not hasattr(harness.window.header_zone, "visibility_button")

            harness.window.open_engine_settings_dialog(config_manager=ConfigManager(tmp_path / "presets"))
            tk_root.update()
            dialog = next(
                child for child in harness.window.root.winfo_children() if isinstance(child, tk.Toplevel)
            )
            panel = next(child for child in dialog.winfo_children() if isinstance(child, EngineSettingsDialog))
            panel._webui_base_url_var.set("http://127.0.0.1:7860")
            panel._content_visibility_mode_var.set("sfw")
            panel._handle_save()
            tk_root.update()

            assert harness.controller.app_state.content_visibility_mode == "sfw"
        finally:
            harness.cleanup()


@pytest.mark.gui
def test_prompt_tab_filters_pack_list_live_on_mode_change(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    (packs_dir / "safe_pack.txt").write_text("portrait of a traveler", encoding="utf-8")
    (packs_dir / "explicit_pack.txt").write_text("nude portrait reference", encoding="utf-8")

    app_state = AppStateV2()
    tab = PromptTabFrame(tk_root, app_state=app_state)
    try:
        visible_before = list(tab.pack_listbox.get(0, tk.END))
        assert "safe_pack" in visible_before
        assert "explicit_pack" in visible_before

        app_state.set_content_visibility_mode("sfw")
        tk_root.update()

        visible_after = list(tab.pack_listbox.get(0, tk.END))
        assert "safe_pack" in visible_after
        assert "explicit_pack" not in visible_after
    finally:
        tab.destroy()


@pytest.mark.gui
def test_preview_panel_redacts_explicit_preview_text_live(tk_root: tk.Tk) -> None:
    app_state = AppStateV2()
    panel = PreviewPanelV2(tk_root, app_state=app_state)
    try:
        panel.set_jobs([_build_explicit_preview_job()])
        assert "nude portrait" in _read_text(panel.prompt_text)

        app_state.set_content_visibility_mode("sfw")
        tk_root.update()

        assert _read_text(panel.prompt_text) == REDACTED_TEXT
        assert panel.visibility_banner.cget("text") == ""
    finally:
        panel.destroy()


@pytest.mark.gui
def test_review_tab_redacts_source_prompts_live(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    image_path = tmp_path / "review" / "explicit.png"
    _write_image(image_path)
    app_state = AppStateV2()
    tab = ReviewTabFrame(tk_root, app_state=app_state)
    payload = {
        "stage_manifest": {
            "final_prompt": "nude portrait reference",
            "config": {"negative_prompt": "bad anatomy"},
        }
    }
    try:
        with patch(
            "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
            return_value=ReadPayloadResult(payload=payload, status="ok"),
        ):
            tab._show_image(image_path)
        assert "nude portrait" in _read_text(tab.current_prompt_text)

        app_state.set_content_visibility_mode("sfw")
        tk_root.update()

        assert _read_text(tab.current_prompt_text) == REDACTED_TEXT
        assert tab.visibility_banner.cget("text") == ""
    finally:
        tab.destroy()


@pytest.mark.gui
def test_photo_optimize_tab_redacts_baseline_prompts_live(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    store = PhotoOptimizeStore(tmp_path / "photo_optimize")
    image_path = tmp_path / "source" / "portrait.png"
    _write_image(image_path)
    asset = store.import_photo(image_path, baseline_defaults={"prompt": "nude portrait", "negative_prompt": "bad hands"})
    app_state = AppStateV2()
    tab = PhotoOptimizeTabFrameV2(tk_root, app_state=app_state, store=store)
    try:
        tab._show_asset(asset.asset_id)
        assert "nude portrait" in _read_text(tab.current_prompt_text)

        app_state.set_content_visibility_mode("sfw")
        tk_root.update()

        assert _read_text(tab.current_prompt_text) == REDACTED_TEXT
        assert tab.visibility_banner.cget("text") == ""
    finally:
        tab.destroy()
