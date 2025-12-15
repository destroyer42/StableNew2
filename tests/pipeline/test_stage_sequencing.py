# Subsystem: Pipeline
# Role: Tests for PR-107 StageSequencer + StageExecutionPlan backbone

"""Tests for stage sequencing and plan-based pipeline execution.

This module tests:
1. StageSequencer.build_plan() - stage ordering and metadata
2. PipelineRunner execution with StageExecutionPlan
3. Invalid configuration detection (ADetailer without generation)
4. last_image_meta chaining between stages
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.stage_models import (
    InvalidStagePlanError,
    StageType,
)
from src.pipeline.stage_sequencer import (
    StageSequencer,
    build_stage_execution_plan,
)
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


def _base_config() -> dict[str, Any]:
    """Base config with txt2img enabled."""
    return {
        "txt2img": {
            "enabled": True,
            "model": "sd_xl_base_1.0",
            "sampler_name": "Euler a",
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
        },
        "img2img": {
            "enabled": False,
            "model": "sd_xl_base_1.0",
            "sampler_name": "Euler a",
            "steps": 15,
        },
        "upscale": {
            "enabled": False,
            "upscaler": "R-ESRGAN 4x+",
        },
        "adetailer": {
            "enabled": False,
        },
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "upscale_enabled": False,
            "adetailer_enabled": False,
        },
        "hires_fix": {
            "enabled": False,
        },
    }


# -----------------------------------------------------------------------------
# Unit Tests: StageSequencer.build_plan()
# -----------------------------------------------------------------------------


class TestStageSequencerBuildPlan:
    """Tests for StageSequencer.build_plan() method."""

    def test_txt2img_only(self):
        """Basic txt2img only - returns single stage."""
        sequencer = StageSequencer()
        config = _base_config()

        plan = sequencer.build_plan(config)

        assert not plan.is_empty()
        assert len(plan.stages) == 1
        assert plan.stages[0].stage_type == "txt2img"
        assert plan.stages[0].order_index == 0
        assert plan.stages[0].requires_input_image is False
        assert plan.stages[0].produces_output_image is True

    def test_full_chain_txt2img_upscale_adetailer(self):
        """Full chain: txt2img + upscale + ADetailer."""
        sequencer = StageSequencer()
        config = _base_config()
        config["upscale"]["enabled"] = True
        config["pipeline"]["upscale_enabled"] = True
        config["adetailer"]["enabled"] = True
        config["pipeline"]["adetailer_enabled"] = True

        plan = sequencer.build_plan(config)

        assert len(plan.stages) == 3
        assert [s.stage_type for s in plan.stages] == ["txt2img", "upscale", "adetailer"]
        # Verify ordering
        assert plan.stages[0].order_index == 0
        assert plan.stages[1].order_index == 1
        assert plan.stages[2].order_index == 2
        # ADetailer should be last
        assert plan.stages[-1].stage_type == "adetailer"

    def test_txt2img_img2img_upscale_adetailer(self):
        """Full 4-stage chain: txt2img + img2img + upscale + ADetailer."""
        sequencer = StageSequencer()
        config = _base_config()
        config["img2img"]["enabled"] = True
        config["pipeline"]["img2img_enabled"] = True
        config["upscale"]["enabled"] = True
        config["pipeline"]["upscale_enabled"] = True
        config["adetailer"]["enabled"] = True
        config["pipeline"]["adetailer_enabled"] = True

        plan = sequencer.build_plan(config)

        assert len(plan.stages) == 4
        assert [s.stage_type for s in plan.stages] == [
            "txt2img",
            "img2img",
            "upscale",
            "adetailer",
        ]

    def test_img2img_with_upscale_no_txt2img(self):
        """Img2img with upscale, no txt2img."""
        sequencer = StageSequencer()
        config = _base_config()
        config["txt2img"]["enabled"] = False
        config["pipeline"]["txt2img_enabled"] = False
        config["img2img"]["enabled"] = True
        config["pipeline"]["img2img_enabled"] = True
        config["upscale"]["enabled"] = True
        config["pipeline"]["upscale_enabled"] = True

        plan = sequencer.build_plan(config)

        assert len(plan.stages) == 2
        assert [s.stage_type for s in plan.stages] == ["img2img", "upscale"]
        assert plan.stages[0].requires_input_image is True

    def test_adetailer_without_generation_raises(self):
        """ADetailer enabled without any generation stage should raise."""
        sequencer = StageSequencer()
        config = _base_config()
        config["txt2img"]["enabled"] = False
        config["pipeline"]["txt2img_enabled"] = False
        config["img2img"]["enabled"] = False
        config["pipeline"]["img2img_enabled"] = False
        config["adetailer"]["enabled"] = True
        config["pipeline"]["adetailer_enabled"] = True

        with pytest.raises(InvalidStagePlanError):
            sequencer.build_plan(config)

    def test_empty_plan_raises(self):
        """No stages enabled should raise ValueError."""
        sequencer = StageSequencer()
        config = _base_config()
        config["txt2img"]["enabled"] = False
        config["pipeline"]["txt2img_enabled"] = False

        with pytest.raises(ValueError, match="no enabled stages"):
            sequencer.build_plan(config)

    def test_refiner_metadata_on_txt2img(self):
        """Refiner metadata should be attached to txt2img stage."""
        sequencer = StageSequencer()
        config = _base_config()
        config["txt2img"]["refiner_enabled"] = True
        config["txt2img"]["refiner_model_name"] = "sd_xl_refiner_1.0"
        config["txt2img"]["refiner_switch_at"] = 0.8

        plan = sequencer.build_plan(config)

        assert len(plan.stages) == 1
        metadata = plan.stages[0].config.metadata
        assert metadata.refiner_enabled is True
        assert metadata.refiner_model_name == "sd_xl_refiner_1.0"
        assert metadata.refiner_switch_at == 0.8

    def test_hires_metadata_on_txt2img(self):
        """Hires fix metadata should be attached to txt2img stage."""
        sequencer = StageSequencer()
        config = _base_config()
        config["hires_fix"] = {
            "enabled": True,
            "upscale_factor": 1.5,
            "denoise_strength": 0.4,
            "steps": 10,
        }

        plan = sequencer.build_plan(config)

        assert len(plan.stages) == 1
        metadata = plan.stages[0].config.metadata
        assert metadata.hires_enabled is True
        assert metadata.hires_upscale_factor == 1.5
        assert metadata.hires_denoise == 0.4
        assert metadata.hires_steps == 10

    def test_has_generation_stage(self):
        """has_generation_stage() should return True when txt2img/img2img present."""
        sequencer = StageSequencer()
        config = _base_config()

        plan = sequencer.build_plan(config)

        assert plan.has_generation_stage() is True

    def test_get_stage_types(self):
        """get_stage_types() should return ordered list of stage type strings."""
        sequencer = StageSequencer()
        config = _base_config()
        config["upscale"]["enabled"] = True
        config["pipeline"]["upscale_enabled"] = True

        plan = sequencer.build_plan(config)

        assert plan.get_stage_types() == ["txt2img", "upscale"]


class TestBuildStageExecutionPlanFunction:
    """Tests for the standalone build_stage_execution_plan() function."""

    def test_function_matches_sequencer(self):
        """build_stage_execution_plan() should produce same result as StageSequencer."""
        config = _base_config()

        plan_func = build_stage_execution_plan(config)
        plan_class = StageSequencer().build_plan(config)

        assert [s.stage_type for s in plan_func.stages] == [s.stage_type for s in plan_class.stages]

    def test_run_id_propagation(self):
        """run_id should be propagated from config metadata."""
        config = _base_config()
        config["metadata"] = {"run_id": "test-run-123"}

        plan = build_stage_execution_plan(config)

        assert plan.run_id == "test-run-123"

    def test_one_click_action_propagation(self):
        """one_click_action should be propagated from config metadata."""
        config = _base_config()
        config["metadata"] = {"one_click_action": "generate"}

        plan = build_stage_execution_plan(config)

        assert plan.one_click_action == "generate"


# -----------------------------------------------------------------------------
# Stub Executor for Runner Smoke Tests
# -----------------------------------------------------------------------------


class StubExecutor:
    """Stub executor for testing PipelineRunner without real SD/WebUI calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run_stage(self, stage_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Record the stage call and return mock output."""
        self.calls.append((stage_type, payload))
        return {
            "images": [f"{stage_type}_image_output"],
            "path": f"/tmp/{stage_type}_output.png",
            "meta": {"stage": stage_type},
        }


class StubPipeline:
    """Stub Pipeline class for testing without real API calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._stage_events: list[dict[str, Any]] = []

    def reset_stage_events(self) -> None:
        self._stage_events = []

    def get_stage_events(self) -> list[dict[str, Any]]:
        return self._stage_events

    def run_txt2img_stage(
        self, prompt: str, negative_prompt: str, payload: dict, run_dir, **kwargs
    ) -> dict[str, Any]:
        self.calls.append(("txt2img", payload))
        return {"images": ["txt2img_output"], "path": str(run_dir / "txt2img.png")}

    def run_img2img_stage(
        self, input_image, prompt: str, payload: dict, run_dir, image_name: str | None = None, **kwargs
    ) -> dict[str, Any]:
        self.calls.append(("img2img", {"input": str(input_image), **payload}))
        return {"images": ["img2img_output"], "path": str(run_dir / "img2img.png")}

    def run_upscale_stage(
        self, input_image, payload: dict, run_dir, **kwargs
    ) -> dict[str, Any]:
        self.calls.append(("upscale", {"input": str(input_image), **payload}))
        return {"images": ["upscale_output"], "path": str(run_dir / "upscale.png")}

    def run_adetailer_stage(
        self, input_image, payload: dict, run_dir, **kwargs
    ) -> dict[str, Any]:
        self.calls.append(("adetailer", {"input": str(input_image), **payload}))
        return {"images": ["adetailer_output"], "path": str(run_dir / "adetailer.png")}

    def _load_image_base64(self, path) -> str:
        return "base64_encoded_image"


# -----------------------------------------------------------------------------
# Runner Smoke Tests
# -----------------------------------------------------------------------------


class TestPipelineRunnerWithPlan:
    """Smoke tests for PipelineRunner executing NJR-based plans."""

    @pytest.fixture
    def mock_api_client(self):
        return MagicMock()

    @pytest.fixture
    def mock_logger(self):
        return MagicMock()

    def test_runner_executes_full_plan_in_order(self, mock_api_client, mock_logger, tmp_path):
        """Runner should honor the enabled stage chain."""
        runner = PipelineRunner(mock_api_client, mock_logger, runs_base_dir=str(tmp_path))
        stub_pipeline = StubPipeline()
        runner._pipeline = stub_pipeline

        stage_chain = [
            make_stage_config(stage_type=StageType.TXT2IMG),
            make_stage_config(stage_type=StageType.UPSCALE),
            make_stage_config(stage_type=StageType.ADETAILER),
        ]
        njr = make_pipeline_njr(
            stage_chain=stage_chain,
            positive_prompt="a beautiful sunset",
            base_model="sd_xl_base_1.0",
            config={"prompt": "a beautiful sunset", "model": "sd_xl_base_1.0"},
        )

        cancel_token = MagicMock()
        cancel_token.is_cancelled.return_value = False

        result = runner.run_njr(njr, cancel_token)

        assert stub_pipeline.calls[0][0] == "txt2img"
        assert result.stage_plan is not None
        assert result.stage_plan.enabled_stages == ["txt2img", "upscale", "adetailer"]

    def test_runner_with_sequencer_injection(self, mock_api_client, mock_logger, tmp_path):
        """Runner should use injected StageSequencer."""
        sequencer = StageSequencer()
        runner = PipelineRunner(
            mock_api_client,
            mock_logger,
            runs_base_dir=str(tmp_path),
            sequencer=sequencer,
        )

        assert runner._sequencer is sequencer

    def test_runner_last_image_meta_chaining(self, mock_api_client, mock_logger, tmp_path):
        runner = PipelineRunner(mock_api_client, mock_logger, runs_base_dir=str(tmp_path))
        stub_pipeline = StubPipeline()
        runner._pipeline = stub_pipeline

        stage_chain = [
            make_stage_config(stage_type=StageType.TXT2IMG),
            make_stage_config(stage_type=StageType.UPSCALE),
        ]
        njr = make_pipeline_njr(
            stage_chain=stage_chain,
            positive_prompt="test",
            base_model="model",
            config={"prompt": "test", "model": "model"},
        )

        cancel_token = MagicMock()
        cancel_token.is_cancelled.return_value = False

        result = runner.run_njr(njr, cancel_token)

        assert any(call[0] == "txt2img" for call in stub_pipeline.calls)
        assert result.stage_plan is not None
        assert result.stage_plan.enabled_stages == ["txt2img", "upscale"]


class TestStageModelsIntegration:
    """Tests for stage_models.py types."""

    def test_stage_type_enum_values(self):
        """StageType enum should have correct values."""
        assert StageType.TXT2IMG.value == "txt2img"
        assert StageType.IMG2IMG.value == "img2img"
        assert StageType.UPSCALE.value == "upscale"
        assert StageType.ADETAILER.value == "adetailer"

    def test_stage_type_is_generation_stage(self):
        """is_generation_stage() should return True for txt2img/img2img."""
        assert StageType.TXT2IMG.is_generation_stage() is True
        assert StageType.IMG2IMG.is_generation_stage() is True
        assert StageType.UPSCALE.is_generation_stage() is False
        assert StageType.ADETAILER.is_generation_stage() is False

    def test_invalid_stage_plan_error(self):
        """InvalidStagePlanError should be a ValueError subclass."""
        assert issubclass(InvalidStagePlanError, ValueError)

        error = InvalidStagePlanError("test error")
        assert str(error) == "test error"
