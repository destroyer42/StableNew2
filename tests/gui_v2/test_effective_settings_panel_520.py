"""PR-GUI-UX-520: the Preview panel's read-only Effective Settings view follows the compiled preview only."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.view_contracts import config_source_contract as contract
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.utils.config import ConfigManager

pytestmark = pytest.mark.gui


def _compiled_jobs(tmp_path: Path, steps: int = 31):
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "g",
    )
    manager.packs_dir.mkdir(parents=True, exist_ok=True)
    (manager.packs_dir / "hero.json").write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": "hero",
                    "slots": [
                        {"index": 0, "text": "a knight", "negative": "", "loras": [["armor", 0.7]]}
                    ],
                    "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                },
                "preset_data": {"txt2img": {"model": "pack_model.safetensors", "steps": steps}},
            }
        ),
        encoding="utf-8",
    )
    controller = PipelineController(app_state=AppStateV2(), config_manager=manager)
    controller._app_state.job_draft.packs = [
        PackJobEntry(
            pack_id="hero",
            pack_name="hero",
            config_snapshot={},
            stage_flags={"txt2img": True},
            randomizer_metadata={"enabled": False},
            pack_row_index=0,
        )
    ]
    controller.refresh_preview_from_state()
    return list(controller._app_state.preview_jobs), controller._app_state


@pytest.fixture
def panel_env(tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "src.gui.preview_panel_v2.PREVIEW_STATE_PATH", tmp_path / "preview_state.json"
    )
    app_state = AppStateV2()
    controller = SimpleNamespace(override_pack_config_enabled=True, main_window=None)
    panel = PreviewPanelV2(tk_root, controller=controller, app_state=app_state)
    panel.update_idletasks()
    yield panel, app_state, controller
    panel.destroy()


def _shown(panel: PreviewPanelV2) -> str:
    panel.update_idletasks()
    return panel.effective_text.get("1.0", "end").strip()


def test_effective_settings_are_hidden_until_requested_and_reachable_by_keyboard(panel_env) -> None:
    panel, _app_state, _ = panel_env
    assert not panel.effective_frame.winfo_manager()
    assert str(panel.effective_toggle.cget("takefocus")) in {"", "1", "ttk::takefocus"}
    assert panel.effective_toggle.cget("text") == "Show effective settings / prompt evidence"


def test_toggle_shows_the_compiled_jobs_settings_and_invalidation_removes_them(
    panel_env, tmp_path: Path
) -> None:
    panel, app_state, _controller = panel_env
    jobs, _ = _compiled_jobs(tmp_path, steps=31)
    assert jobs

    app_state.set_preview_jobs(jobs)
    panel._effective_visible_var.set(True)
    panel._on_effective_toggle()
    text = _shown(panel)

    assert panel.effective_frame.winfo_manager()
    assert "Effective settings of 1 compiled job" in text
    assert "Model" in text and "pack_model.safetensors" in text
    assert "Steps" in text and "31" in text
    # The override choice is part of the stated provenance (read from the controller, not re-derived).
    assert contract.OVERRIDE_ON_TEXT in text
    assert "Compiled Positive:" in text and "a knight" in text
    assert "Execution-time projection unavailable" in text

    app_state.invalidate_preview()  # any source change invalidates the preview
    panel.update_idletasks()
    assert _shown(panel).startswith("No compiled preview yet")
    assert "pack_model.safetensors" not in _shown(panel)

    panel._effective_visible_var.set(False)
    panel._on_effective_toggle()
    assert not panel.effective_frame.winfo_manager()


def test_a_draft_without_compiled_jobs_shows_the_empty_state_not_draft_values(panel_env) -> None:
    panel, app_state, _ = panel_env
    app_state.job_draft.packs = [
        PackJobEntry(
            pack_id="hero",
            pack_name="hero",
            config_snapshot={"txt2img": {"steps": 99, "model": "draft_only.safetensors"}},
            stage_flags={"txt2img": True},
            randomizer_metadata={"enabled": False},
        )
    ]
    panel._effective_visible_var.set(True)
    panel.update_from_job_draft(app_state.job_draft)

    text = _shown(panel)
    assert text.startswith("No compiled preview yet")
    assert "draft_only" not in text and "99" not in text


def test_hidden_content_mode_redacts_lora_names(panel_env, tmp_path: Path) -> None:
    panel, app_state, _ = panel_env
    jobs, _ = _compiled_jobs(tmp_path)
    app_state.set_preview_jobs(jobs)
    panel._effective_visible_var.set(True)
    panel._on_effective_toggle()
    assert "armor @ 0.7" in _shown(panel)

    panel.on_content_visibility_mode_changed("sfw")

    assert "armor" not in _shown(panel)
    assert "names hidden" in _shown(panel)


def test_text_is_read_only_and_scrolls_for_narrow_windows(panel_env, tmp_path: Path) -> None:
    panel, app_state, _ = panel_env
    jobs, _ = _compiled_jobs(tmp_path)
    app_state.set_preview_jobs(jobs)
    panel._effective_visible_var.set(True)
    panel._on_effective_toggle()

    assert str(panel.effective_text.cget("state")) == "disabled"
    scrollbars = [
        w for w in panel.effective_frame.winfo_children() if w.winfo_class() == "TScrollbar"
    ]
    assert scrollbars, "the summary must be reachable by scrolling when the window is narrow"


def test_profile_lines_and_stale_draft_notices_reach_the_effective_view(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR-IMG-PROFILE-630: the view names the working model/profile and warns when the draft predates a change."""
    monkeypatch.setattr(
        "src.gui.preview_panel_v2.PREVIEW_STATE_PATH", tmp_path / "preview_state.json"
    )
    listeners: list = []
    notices: list[str] = []
    profiles = SimpleNamespace(
        effective_lines=lambda: ("Model: m.safetensors (sdxl)", "Profile: none selected"),
        draft_notices=lambda: tuple(notices),
        add_listener=listeners.append,
    )
    app_state = AppStateV2()
    controller = SimpleNamespace(
        override_pack_config_enabled=False, main_window=None, generation_profiles=profiles
    )
    panel = PreviewPanelV2(tk_root, controller=controller, app_state=app_state)
    try:
        jobs, _ = _compiled_jobs(tmp_path)
        app_state.set_preview_jobs(jobs)
        panel._effective_visible_var.set(True)
        panel._on_effective_toggle()
        text = _shown(panel)
        assert "Working model and profile (not part of the compiled jobs)" in text
        assert "Model: m.safetensors (sdxl)" in text
        assert "Preview may be out of date" not in text

        notices.append(
            "The draft was built with different stages than are selected now (adetailer is on now)."
        )
        assert listeners, "the Preview subscribes to profile-state changes"
        listeners[0]()  # a stage toggle / override / profile change tells the Preview to re-read
        text = _shown(panel)
        assert "Preview may be out of date" in text and "adetailer is on now" in text
    finally:
        panel.destroy()
