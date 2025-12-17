from __future__ import annotations

from pathlib import Path
from typing import Any

from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.utils.config import ConfigManager

DEFAULT_PACK_CONFIG: dict[str, Any] = {
    "pipeline": {
        "images_per_prompt": 1,
        "loop_count": 1,
        "loop_type": "pipeline",
        "variant_mode": "standard",
        "apply_global_negative_txt2img": True,
    },
    "txt2img": {
        "model": "model.safetensors",
        "sampler_name": "Euler",
        "scheduler": "DDIM",
        "steps": 24,
        "cfg_scale": 7.5,
        "width": 512,
        "height": 512,
        "negative_prompt": "",
    },
    "randomization": {"enabled": False},
    "aesthetic": {"enabled": False},
}


class PreviewConfigManager(ConfigManager):
    """ConfigManager override that feeds the prompt-pack builder a deterministic config."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(presets_dir=tmp_path / "presets")
        self.packs_dir = tmp_path / "packs"
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        self._pack_config = dict(DEFAULT_PACK_CONFIG)

    def load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        return dict(self._pack_config)

    def resolve_config(
        self,
        *,
        pack_overrides: dict[str, Any] | None = None,
        runtime_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(self._pack_config)
        if pack_overrides:
            merged.update(pack_overrides)
        if runtime_params:
            merged.update(runtime_params)
        return merged

    def get_global_negative_prompt(self) -> str:
        return "global-negative"


def _make_pack_entry(prompt_text: str = "A fantasy woman in armor") -> PackJobEntry:
    return PackJobEntry(
        pack_id="preview-pack",
        pack_name="Preview Pack",
        config_snapshot={"txt2img": {"model": "model.safetensors", "steps": 30}},
        prompt_text=prompt_text,
        negative_prompt_text=None,
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )


def _make_controller(tmp_path: Path) -> PipelineController:
    config_manager = PreviewConfigManager(tmp_path)
    app_state = AppStateV2()
    return PipelineController(app_state=app_state, config_manager=config_manager)


def test_preview_jobs_built_from_pack_draft_single_entry(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    entry = _make_pack_entry("A fantasy woman in armor")
    controller._app_state.job_draft.packs = [entry]

    controller.refresh_preview_from_state()
    preview_jobs = controller._app_state.preview_jobs
    assert preview_jobs, "Preview builder should produce records from packs"

    record = preview_jobs[0]
    assert "fantasy woman" in record.positive_prompt.lower()
    assert record.base_model == "model.safetensors"


def test_preview_jobs_fall_back_when_no_packs(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    expected = controller._build_normalized_jobs_from_state()

    called: dict[str, bool] = {"value": False}

    def fallback(
        base_config=None,  # type: ignore[override]
    ) -> list[Any]:
        called["value"] = True
        return expected

    controller._build_normalized_jobs_from_state = fallback  # type: ignore[attr-defined]
    preview_jobs = controller.get_preview_jobs()
    assert called["value"], "Fallback builder should run when no prompt-pack entries exist"
    assert preview_jobs == expected


def test_preview_jobs_switch_from_manual_to_pack_when_draft_added(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    controller.refresh_preview_from_state()
    initial_prompts = [job.positive_prompt for job in controller._app_state.preview_jobs]

    entry = _make_pack_entry("A radiant sorceress with lightning")
    controller._app_state.job_draft.packs = [entry]
    controller.refresh_preview_from_state()

    preview_jobs = controller._app_state.preview_jobs
    assert preview_jobs, "Preview jobs should refresh once a pack draft exists"
    assert "sorceress" in preview_jobs[0].positive_prompt.lower()
    assert preview_jobs[0].base_model == "model.safetensors"
    assert preview_jobs[0].positive_prompt not in initial_prompts
