from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.artifact_metadata_inspector_dialog import ArtifactMetadataInspectorDialog
from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
from src.gui.panels_v2.job_explanation_panel_v2 import JobExplanationPanelV2
from src.gui.theme_v2 import BACKGROUND_DARK
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


def _build_inspector_payload() -> dict[str, object]:
    return {
        "artifact_path": "C:/images/sample.png",
        "normalized_generation_summary": {"stage": "txt2img", "model": "modelA"},
        "normalized_review_summary": {"user_rating": 4, "quality_label": "good"},
        "source_diagnostics": {"active_review_precedence": "embedded_review_metadata"},
        "raw_embedded_payload": {"stage": "txt2img"},
        "raw_embedded_review_payload": {"user_rating": 4},
        "raw_sidecar_review_payload": None,
        "raw_internal_review_summary": None,
    }


def _build_learning_records() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            timestamp="2026-03-26T12:00:00",
            prompt_summary="very long prompt summary " * 8,
            pipeline_summary="model-x",
            rating=4,
            tags=["tag1", "tag2"],
        )
    ]


def _build_run_snapshot(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_id": "job-123",
                "config": {"prompt": "a sunset", "negative_prompt": "blurry"},
                "packs": [{"pack_name": "fantasy"}],
                "stage_outputs": [{"stage": "txt2img"}, {"stage": "upscale"}],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "txt2img_01.json").write_text(
        json.dumps(
            {
                "final_prompt": "a sunset over cliffs, cinematic",
                "final_negative_prompt": "blurry, GLOBAL_BAD",
                "global_negative_terms": "GLOBAL_BAD",
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.gui
def test_gui_consistency_secondary_surfaces_have_theme_minsize_and_scrollability(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    inspector = ArtifactMetadataInspectorDialog(
        tk_root,
        inspection_payload=_build_inspector_payload(),
    )
    review_dialog = LearningReviewDialogV2(
        tk_root,
        controller=object(),
        records=_build_learning_records(),
    )
    runs_dir = tmp_path / "runs"
    _build_run_snapshot(runs_dir / "job-123")
    explanation = JobExplanationPanelV2("job-123", master=tk_root, base_runs_dir=runs_dir)
    try:
        assert inspector.cget("bg") == BACKGROUND_DARK
        assert review_dialog.cget("bg") == BACKGROUND_DARK
        assert explanation.cget("bg") == BACKGROUND_DARK

        assert tuple(map(int, inspector.minsize())) == (720, 560)
        assert tuple(map(int, review_dialog.minsize())) == (720, 360)
        assert tuple(map(int, explanation.minsize())) == (640, 480)

        assert inspector._normalized_text.cget("wrap") == "none"  # noqa: SLF001
        assert len(inspector._normalized_text.master.winfo_children()) == 3  # noqa: SLF001

        assert review_dialog._body_canvas is not None  # noqa: SLF001
        body_children = review_dialog._body_canvas.master.winfo_children()  # noqa: SLF001
        assert len(body_children) == 2
        assert any(child.winfo_class() == "TScrollbar" for child in body_children)

        assert explanation._stage_scrollbar.winfo_exists()  # noqa: SLF001
        assert explanation._metadata_y_scrollbar.winfo_exists()  # noqa: SLF001
        assert explanation._metadata_x_scrollbar.winfo_exists()  # noqa: SLF001
    finally:
        inspector.destroy()
        review_dialog.destroy()
        explanation.destroy()


@pytest.mark.gui
def test_gui_consistency_pipeline_workspace_keeps_shared_minimum_width_contract(
    tk_root: tk.Tk,
) -> None:
    tab = PipelineTabFrame(tk_root, app_state=AppStateV2())
    try:
        tk_root.update_idletasks()
        assert tab.MIN_COLUMN_WIDTH > 0
        for idx in range(3):
            assert tab.columnconfigure(idx)["minsize"] == tab.MIN_COLUMN_WIDTH
    finally:
        tab.destroy()
