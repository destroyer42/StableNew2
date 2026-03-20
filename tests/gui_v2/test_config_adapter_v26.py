from __future__ import annotations

from src.gui.app_state_v2 import AppStateV2, PackJobEntry


def test_config_adapter_updates_canonical_layers_from_run_config() -> None:
    app_state = AppStateV2()

    app_state.set_run_config(
        {
            "run_mode": "queue",
            "source": "run",
            "model": "sdxl",
            "steps": 28,
            "pipeline": {"txt2img_enabled": True},
            "randomization_enabled": True,
            "max_variants": 4,
        }
    )

    adapter = app_state.config_adapter

    assert adapter.get_intent_config()["run_mode"] == "queue"
    assert adapter.get_execution_config()["model"] == "sdxl"
    assert adapter.get_run_config_projection()["config_layers"]["execution_config"]["steps"] == 28
    assert adapter.get_randomizer_config()["max_variants"] == 4


def test_config_adapter_derives_backend_options_from_projection_when_layers_empty() -> None:
    app_state = AppStateV2()
    app_state.run_config = {
        "video_workflow": {
            "workflow_id": "ltx_multiframe_anchor_v1",
            "workflow_version": "1.0.0",
            "backend_id": "comfy",
        }
    }

    backend_options = app_state.config_adapter.get_backend_options()

    assert backend_options["video"]["workflow"]["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert backend_options["video"]["workflow"]["backend_id"] == "comfy"


def test_config_adapter_resolves_prompt_pack_context_from_selected_pack_or_draft() -> None:
    app_state = AppStateV2()
    app_state.set_selected_prompt_pack("pack-selected", "Selected Pack")

    prompt_source, prompt_pack_id = app_state.config_adapter.resolve_prompt_pack_context()

    assert (prompt_source, prompt_pack_id) == ("pack", "pack-selected")

    app_state.set_selected_prompt_pack(None, None)
    app_state.job_draft.packs.append(
        PackJobEntry(
            pack_id="pack-draft",
            pack_name="Draft Pack",
            config_snapshot={},
        )
    )

    prompt_source, prompt_pack_id = app_state.config_adapter.resolve_prompt_pack_context()

    assert (prompt_source, prompt_pack_id) == ("pack", "pack-draft")
