#ARCHIVE
# Legacy test for Pipeline pack selector actions before Phase 6 diagnostics refactor.
from __future__ import annotations

import pytest

from src.app_factory import build_v2_app


@pytest.mark.gui
def test_pipeline_pack_selector_job_actions_v2() -> None:
    """Test Pipeline tab pack selector job/config tool functionality."""
    try:
        root, app_state, controller, window = build_v2_app()
    except Exception as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        # Get the pipeline tab
        pipeline_tab = getattr(window, "pipeline_tab", None)
        assert pipeline_tab is not None, "Pipeline tab should exist"

        # Get the pack loader compat
        pack_loader = getattr(pipeline_tab, "pack_loader_compat", None)
        assert pack_loader is not None, "Pack loader compat should exist"

        # Check pack list is multi-select
        packs_list = getattr(pack_loader, "packs_list", None)
        assert packs_list is not None, "Packs list should exist"
        assert packs_list.cget("selectmode") == "extended", "Pack list should be multi-select"

        # Check buttons exist
        load_config_btn = getattr(pack_loader, "load_config_button", None)
        assert load_config_btn is not None, "Load config button should exist"

        apply_config_btn = getattr(pack_loader, "apply_config_button", None)
        assert apply_config_btn is not None, "Apply config button should exist"

        add_to_job_btn = getattr(pack_loader, "add_to_job_button", None)
        assert add_to_job_btn is not None, "Add to job button should exist"

        # Check preset combo and menu
        preset_combo = getattr(pack_loader, "preset_combo", None)
        assert preset_combo is not None, "Preset combo should exist"

        preset_menu_button = getattr(pack_loader, "preset_menu_button", None)
        assert preset_menu_button is not None, "Preset menu button should exist"

        # Test pack list population
        test_packs = ["test_pack_1", "test_pack_2", "test_pack_3"]
        pack_loader.set_pack_names(test_packs)
        list_items = packs_list.get(0, "end")
        assert list(list_items) == test_packs, "Pack list should be populated"

        # Test controller methods exist
        assert hasattr(controller, "on_pipeline_pack_load_config"), "Controller should have load config method"
        assert hasattr(controller, "on_pipeline_pack_apply_config"), "Controller should have apply config method"
        assert hasattr(controller, "on_pipeline_add_packs_to_job"), "Controller should have add to job method"
        assert hasattr(controller, "on_pipeline_preset_apply_to_default"), "Controller should have preset apply to default"
        assert hasattr(controller, "on_pipeline_preset_apply_to_packs"), "Controller should have preset apply to packs"
        assert hasattr(controller, "on_pipeline_preset_load_to_stages"), "Controller should have preset load to stages"
        assert hasattr(controller, "on_pipeline_preset_save_from_stages"), "Controller should have preset save from stages"
        assert hasattr(controller, "on_pipeline_preset_delete"), "Controller should have preset delete"

        # Test job draft functionality
        assert hasattr(app_state, "job_draft"), "App state should have job_draft"
        assert hasattr(app_state, "add_packs_to_job_draft"), "App state should have add_packs_to_job_draft"
        assert hasattr(app_state, "clear_job_draft"), "App state should have clear_job_draft"

        # Test preview panel update
        preview_panel = getattr(pipeline_tab, "preview_panel", None)
        assert preview_panel is not None, "Preview panel should exist"
        assert hasattr(preview_panel, "update_from_job_draft"), "Preview panel should have update_from_job_draft"

        # Test adding packs to job draft
        from src.gui.app_state_v2 import PackJobEntry
        entries = [
            PackJobEntry(pack_id="test_pack_1", pack_name="Test Pack 1", config_snapshot={"randomization_enabled": True}),
            PackJobEntry(pack_id="test_pack_2", pack_name="Test Pack 2", config_snapshot={"randomization_enabled": False}),
        ]
        app_state.add_packs_to_job_draft(entries)
        assert len(app_state.job_draft.packs) == 2, "Job draft should have 2 packs"

        # Test preview updates
        preview_panel.update_from_job_draft(app_state.job_draft)
        summary_text = preview_panel.job_count_label.cget("text")
        assert "Job Draft: 2 pack(s)" in summary_text, "Preview should show job draft summary"

        # Test clear job draft
        app_state.clear_job_draft()
        assert len(app_state.job_draft.packs) == 0, "Job draft should be cleared"

    finally:
        try:
            root.destroy()
        except Exception:
            pass
