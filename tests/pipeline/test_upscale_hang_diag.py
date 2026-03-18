from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger


def _make_runner(tmp_path: Path) -> PipelineRunner:
    return PipelineRunner(Mock(), StructuredLogger(output_dir=tmp_path / "logs"), runs_base_dir=str(tmp_path / "runs"))


def _seed_image(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("image")
    return str(path)


def test_runner_processes_upscale_stage_serially_for_each_input_image(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    calls: list[str] = []

    class _FakePipeline:
        def __init__(self):
            self._current_job_id = None
            self._current_njr_sha256 = None
            self._current_stage_chain = []
            self._current_stage_index = 0

        def _begin_run_metrics(self):
            return None

        def get_run_efficiency_metrics(self, _images_processed):
            return {}

        def run_upscale_stage(self, input_image_path, config, output_dir, image_name, cancel_token=None):
            calls.append(str(input_image_path))
            output_path = Path(output_dir) / f"{image_name}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("upscaled")
            return {"path": str(output_path), "stage": "upscale"}

    runner._pipeline = _FakePipeline()
    inputs = [
        _seed_image(tmp_path / "src" / "img_0.png"),
        _seed_image(tmp_path / "src" / "img_1.png"),
        _seed_image(tmp_path / "src" / "img_2.png"),
    ]
    record = NormalizedJobRecord(
        job_id="upscale-serial",
        config={},
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        stage_chain=[StageConfig(stage_type="upscale", enabled=True, extra={"upscaler": "nearest"})],
        input_image_paths=inputs,
        start_stage="upscale",
    )

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert calls == inputs
    assert len(record.output_paths) == 3


def test_runner_skips_missing_upscale_outputs_without_failing_prior_inputs(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    calls: list[str] = []

    class _FakePipeline:
        def __init__(self):
            self._current_job_id = None
            self._current_njr_sha256 = None
            self._current_stage_chain = []
            self._current_stage_index = 0

        def _begin_run_metrics(self):
            return None

        def get_run_efficiency_metrics(self, _images_processed):
            return {}

        def run_upscale_stage(self, input_image_path, config, output_dir, image_name, cancel_token=None):
            calls.append(Path(input_image_path).name)
            if Path(input_image_path).name == "img_1.png":
                return None
            output_path = Path(output_dir) / f"{image_name}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("upscaled")
            return {"path": str(output_path), "stage": "upscale"}

    runner._pipeline = _FakePipeline()
    inputs = [
        _seed_image(tmp_path / "src" / "img_0.png"),
        _seed_image(tmp_path / "src" / "img_1.png"),
        _seed_image(tmp_path / "src" / "img_2.png"),
    ]
    record = NormalizedJobRecord(
        job_id="upscale-partial",
        config={},
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        stage_chain=[StageConfig(stage_type="upscale", enabled=True, extra={"upscaler": "nearest"})],
        input_image_paths=inputs,
        start_stage="upscale",
    )

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert calls == ["img_0.png", "img_1.png", "img_2.png"]
    assert len(record.output_paths) == 2
