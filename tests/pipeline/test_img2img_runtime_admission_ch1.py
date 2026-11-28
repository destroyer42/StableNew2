"""CODE-HEALTH (e): img2img passes the same runtime admission as the other WebUI stages before it dispatches.

img2img was the only WebUI stage with no pressure assessment or runtime admission (``IMAGE_PIPELINE.md`` already
described admission as common to every stage). A reprocess, photo-optimize or Klein-edit job whose first stage is
img2img therefore reached Forge with no admission at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.api.types import GenerateError, GenerateErrorCode
from src.pipeline.executor import Pipeline, PipelineStageError
from src.utils import StructuredLogger


class _Client:
    options_write_enabled = True

    def get_current_model(self) -> str:
        return "model.safetensors"

    def get_current_vae(self) -> str:
        return "vae.pt"


def _fake_save_image(_data: str, path: Path, metadata_builder=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("image", encoding="utf-8")
    return path


def _pipeline(
    tmp_path: Path, monkeypatch, admission: Any
) -> tuple[Pipeline, list[str], list[dict[str, Any]]]:
    pipeline = Pipeline(client=_Client(), structured_logger=StructuredLogger())
    events: list[str] = []
    admissions: list[dict[str, Any]] = []
    monkeypatch.setattr(
        pipeline, "_ensure_model_and_vae", lambda *_a, **_k: events.append("model_sync")
    )
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_load_image_base64", lambda _path: "INPUT_BASE64")

    def _admit(*, stage_name: str, pressure_assessment: Any = None) -> dict[str, Any]:
        events.append("admission")
        admissions.append(
            {"stage_name": stage_name, "pressure_assessment": dict(pressure_assessment or {})}
        )
        return admission(stage_name)

    def _fail_launch_policy(**_kwargs: Any) -> None:
        raise AssertionError("img2img has no launch-policy profile; it must not restart WebUI")

    def _generate(stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        events.append("dispatch")
        return {
            "images": ["ignored"],
            "info": {"seed": 1, "subseed": 2, "all_seeds": [1], "all_subseeds": [2]},
        }

    monkeypatch.setattr(pipeline, "_ensure_runtime_admissible", _admit)
    monkeypatch.setattr(pipeline, "_maybe_apply_workload_launch_policy", _fail_launch_policy)
    monkeypatch.setattr(pipeline, "_generate_images", _generate)
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)
    (tmp_path / "input.png").write_bytes(b"")
    return pipeline, events, admissions


def _run(pipeline: Pipeline, tmp_path: Path) -> dict[str, Any] | None:
    return pipeline.run_img2img_stage(
        input_image_path=tmp_path / "input.png",
        prompt="clean up",
        config={
            "model": "model.safetensors",
            "steps": 30,
            "denoising_strength": 0.3,
            "width": 1024,
            "height": 1536,
        },
        output_dir=tmp_path,
        image_name="cleanup",
    )


def test_img2img_is_admitted_before_model_sync_and_dispatch(tmp_path: Path, monkeypatch) -> None:
    pipeline, events, admissions = _pipeline(
        tmp_path, monkeypatch, lambda _stage: {"status": "healthy"}
    )

    result = _run(pipeline, tmp_path)

    assert result is not None
    assert events == ["admission", "model_sync", "dispatch"]
    assert admissions[0]["stage_name"] == "img2img"
    pressure = admissions[0]["pressure_assessment"]
    assert (pressure["stage"], pressure["width"], pressure["height"], pressure["steps"]) == (
        "img2img",
        1024,
        1536,
        30,
    )
    assert result["runtime_admission"] == {"status": "healthy"}
    assert result["pressure_assessment"]["stage"] == "img2img"
    assert "runtime_warnings" not in result


def test_img2img_refused_by_admission_dispatches_nothing(tmp_path: Path, monkeypatch) -> None:
    def _refuse(stage: str) -> dict[str, Any]:
        message = f"Runtime admission refused before {stage}: poisoned"
        raise PipelineStageError(
            GenerateError(code=GenerateErrorCode.CONNECTION, message=message, stage=stage)
        )

    pipeline, events, _admissions = _pipeline(tmp_path, monkeypatch, _refuse)

    with pytest.raises(PipelineStageError, match="Runtime admission refused before img2img"):
        _run(pipeline, tmp_path)

    assert "dispatch" not in events
    assert "model_sync" not in events


def test_img2img_degraded_admission_is_recorded_as_a_runtime_warning(
    tmp_path: Path, monkeypatch
) -> None:
    pipeline, _events, _admissions = _pipeline(
        tmp_path, monkeypatch, lambda _stage: {"status": "degraded", "reasons": ["slow probe"]}
    )

    result = _run(pipeline, tmp_path)

    assert result is not None
    assert result["runtime_warnings"] == [
        {"type": "runtime_admission", "status": "degraded", "reasons": ["slow probe"]}
    ]
