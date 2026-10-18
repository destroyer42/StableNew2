"""An image saved without provenance says so (audit B9, P3-5)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.pipeline.executor import Pipeline


def _builder(pipeline: Pipeline, tmp_path: Path):
    return pipeline._build_image_metadata_builder(
        image_path=tmp_path / "img_001.png",
        stage="txt2img",
        run_dir=tmp_path,
        manifest={"job_id": "job-1"},
    )


def test_a_failing_metadata_build_is_logged_and_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pipeline = Pipeline(Mock(), Mock())

    def _boom(**_kwargs):
        raise ValueError("payload exploded")

    monkeypatch.setattr(pipeline, "_build_image_metadata_payload", _boom)
    builder = _builder(pipeline, tmp_path)
    with caplog.at_level(logging.WARNING):
        result = builder(Image.new("RGB", (4, 4)))
    assert result is None  # the image is still saved
    assert "img_001.png" in caplog.text and "payload exploded" in caplog.text
    (entry,) = pipeline._provenance_incomplete
    assert entry["stage"] == "txt2img"
    assert entry["image"] == "img_001.png"
    assert entry["reason"] == "metadata_build_failed"
    assert "payload exploded" in entry["error"]


def test_a_successful_build_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = Pipeline(Mock(), Mock())
    monkeypatch.setattr(pipeline, "_build_image_metadata_payload", lambda **_k: {"k": "v"})
    result = _builder(pipeline, tmp_path)(Image.new("RGB", (4, 4)))
    assert isinstance(result, dict) and result
    assert pipeline._provenance_incomplete == []
