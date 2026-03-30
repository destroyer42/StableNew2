from __future__ import annotations

from datetime import datetime
import tkinter as tk
from unittest.mock import Mock

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.pipeline.job_models_v2 import RuntimeJobStatus, UnifiedJobSummary


def _make_running_job() -> UnifiedJobSummary:
    return UnifiedJobSummary(
        job_id="job-1",
        prompt_pack_id="pack-1",
        prompt_pack_name="Pack",
        prompt_pack_row_index=0,
        positive_prompt_preview="prompt",
        negative_prompt_preview=None,
        lora_preview="",
        embedding_preview="",
        base_model="model.safetensors",
        sampler_name="Euler a",
        cfg_scale=7.0,
        steps=20,
        width=512,
        height=512,
        stage_chain_labels=["svd_native"],
        randomization_enabled=False,
        matrix_mode=None,
        matrix_slot_values_preview="",
        variant_index=0,
        batch_index=0,
        config_variant_label="default",
        config_variant_index=0,
        estimated_image_count=1,
        status="RUNNING",
        created_at=datetime.utcnow(),
        completed_at=None,
    )


def test_running_job_panel_displays_runtime_stage_detail() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()

    try:
        app_state = AppStateV2()
        panel = RunningJobPanelV2(root, app_state=app_state)
        app_state.running_job = _make_running_job()
        app_state.runtime_status = RuntimeJobStatus(
            job_id="job-1",
            current_stage="svd_native",
            stage_detail="postprocess: interpolation",
            stage_index=0,
            total_stages=1,
            progress=0.75,
            eta_seconds=None,
            started_at=datetime.utcnow(),
            actual_seed=123,
            current_step=1,
            total_steps=1,
        )

        panel.update_from_app_state(app_state)

        assert panel.stage_chain_label.cget("text") == "Stage: 1/1 svd_native - postprocess: interpolation"
    finally:
        root.destroy()


def test_running_job_panel_skips_redundant_timeline_clear_for_identical_state() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()

    try:
        app_state = AppStateV2()
        app_state.running_job = _make_running_job()
        panel = RunningJobPanelV2(root, app_state=app_state)
        panel._timeline = Mock()
        panel._timeline_is_clear = False

        panel.update_from_app_state(app_state)
        panel.update_from_app_state(app_state)

        panel._timeline.clear.assert_called_once()
    finally:
        root.destroy()
