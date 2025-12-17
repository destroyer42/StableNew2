import json
import tkinter as tk

import pytest

from src.gui.panels_v2.job_explanation_panel_v2 import JobExplanationPanelV2


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def _build_run_snapshot(run_dir):
    config = {"prompt": "a sunset", "negative_prompt": "blurry"}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_id": "job-123",
                "config": config,
                "packs": [{"pack_name": "fantasy"}],
                "stage_outputs": [{"stage": "txt2img"}, {"stage": "upscale"}],
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "prompt": "a sunset over cliffs",
        "final_prompt": "a sunset over cliffs, cinematic",
        "original_negative_prompt": "blurry",
        "final_negative_prompt": "blurry, GLOBAL_BAD",
        "global_negative_terms": "GLOBAL_BAD",
    }
    (run_dir / "txt2img_01.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_job_explanation_panel_shows_manifest(tmp_path, tk_root):
    run_dir = tmp_path / "runs" / "job-123"
    manifest = _build_run_snapshot(run_dir)
    panel = JobExplanationPanelV2("job-123", master=tk_root, base_runs_dir=tmp_path / "runs")
    children = panel.stage_tree.get_children()
    assert children
    values = panel.stage_tree.item(children[0], "values")
    assert manifest["final_prompt"] in values[1]
    assert manifest["final_negative_prompt"] in values[2]
    assert "GLOBAL_BAD" in values[3]
    panel.destroy()


def test_job_explanation_panel_handles_missing_metadata(tmp_path, tk_root):
    panel = JobExplanationPanelV2("missing-job", master=tk_root, base_runs_dir=tmp_path / "runs")
    tree_children = panel.stage_tree.get_children()
    assert tree_children
    assert "Run metadata not found" in panel._origin_text.cget("text")
    panel.destroy()
