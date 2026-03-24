from __future__ import annotations

import json
import tkinter as tk

import pytest

from src.gui.artifact_metadata_inspector_dialog import ArtifactMetadataInspectorDialog


@pytest.mark.gui
def test_artifact_metadata_inspector_dialog_renders_sections(tk_root: tk.Tk) -> None:
    payload = {
        "artifact_path": "C:/images/sample.png",
        "normalized_generation_summary": {"stage": "txt2img", "model": "modelA"},
        "normalized_review_summary": {"user_rating": 4, "quality_label": "good"},
        "source_diagnostics": {"active_review_precedence": "embedded_review_metadata"},
        "raw_embedded_payload": {"stage": "txt2img"},
        "raw_embedded_review_payload": {"user_rating": 4},
        "raw_sidecar_review_payload": None,
        "raw_internal_review_summary": None,
    }

    dialog = ArtifactMetadataInspectorDialog(tk_root, inspection_payload=payload)
    try:
        assert "sample.png" in dialog._artifact_var.get()  # noqa: SLF001
        normalized = dialog._normalized_text.get("1.0", "end-1c")  # noqa: SLF001
        raw = dialog._raw_text.get("1.0", "end-1c")  # noqa: SLF001
        assert '"model": "modelA"' in normalized
        assert '"user_rating": 4' in normalized
        assert '"raw_embedded_review_payload"' in raw
    finally:
        dialog.destroy()


@pytest.mark.gui
def test_artifact_metadata_inspector_dialog_copy_actions_use_clipboard(tk_root: tk.Tk) -> None:
    payload = {
        "artifact_path": "C:/images/sample.png",
        "normalized_generation_summary": {"stage": "txt2img"},
        "normalized_review_summary": {"user_rating": 5},
        "source_diagnostics": {},
        "raw_embedded_payload": {"foo": "bar"},
        "raw_embedded_review_payload": None,
        "raw_sidecar_review_payload": None,
        "raw_internal_review_summary": None,
    }

    dialog = ArtifactMetadataInspectorDialog(tk_root, inspection_payload=payload)
    try:
        dialog._copy_normalized_summary()  # noqa: SLF001
        normalized_clipboard = dialog.clipboard_get()
        assert json.loads(normalized_clipboard)["normalized_review_summary"]["user_rating"] == 5

        dialog._copy_raw_json()  # noqa: SLF001
        raw_clipboard = dialog.clipboard_get()
        assert json.loads(raw_clipboard)["raw_embedded_payload"]["foo"] == "bar"
    finally:
        dialog.destroy()