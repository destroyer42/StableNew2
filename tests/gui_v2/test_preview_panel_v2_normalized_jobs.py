"""Tests verifying PreviewPanelV2 renders NormalizedJobRecord prompts (PR-CORE1-A3).

Confirms preview panel uses NJR-based display, not pipeline_config.
"""

from __future__ import annotations

import tkinter as tk

from src.gui.preview_panel_v2 import PreviewPanelV2
from src.pipeline.job_models_v2 import NormalizedJobRecord, StagePromptInfo


def _build_test_job() -> NormalizedJobRecord:
    prompt_info = StagePromptInfo(
        original_prompt="pack prompt",
        final_prompt="pack prompt final",
        original_negative_prompt="bad quality",
        final_negative_prompt="bad quality, GLOBAL_BAD",
        global_negative_applied=True,
        global_negative_terms="GLOBAL_BAD",
    )
    return NormalizedJobRecord(
        job_id="job-123",
        config={
            "model": "test-model",
            "prompt": "pack prompt final",
            "negative_prompt": "bad quality, GLOBAL_BAD",
            "sampler": "Euler a",
            "steps": 8,
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


def test_preview_panel_shows_prompt_text() -> None:
    root = tk.Tk()
    root.withdraw()
    panel = PreviewPanelV2(root)
    job = _build_test_job()
    panel.set_jobs([job])

    prompt_value = panel.prompt_text.get("1.0", tk.END).strip()
    negative_value = panel.negative_prompt_text.get("1.0", tk.END).strip()

    assert prompt_value == "pack prompt final"
    assert negative_value == "bad quality, GLOBAL_BAD"

    root.destroy()
