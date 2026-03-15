"""Unit tests for PR-LEARN-010/032: LearningController NJR construction.

Tests:
1. NJR construction with explicit stage card config
2. No prompt duplication in NJR
3. Job submission via JobService (not PackJobEntry)
4. End-to-end config propagation
"""

from pathlib import Path
from unittest.mock import Mock, MagicMock

import pytest
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
from src.pipeline.job_models_v2 import NormalizedJobRecord


class TestLearningControllerNJR:
    """Tests for PR-LEARN-010 NJR construction."""

    @pytest.fixture
    def learning_state(self):
        """Create learning state with test experiment."""
        state = LearningState()
        experiment = LearningExperiment(
            name="TestExperiment",
            stage="txt2img",
            variable_under_test="CFG Scale",
            prompt_text="a beautiful landscape",
        )
        state.current_experiment = experiment
        return state

    @pytest.fixture
    def mock_app_controller(self):
        """Mock app controller with stage cards."""
        app_controller = Mock()
        
        # Mock stage panel
        stage_panel = Mock()
        txt2img_card = Mock()
        txt2img_card.to_config_dict.return_value = {
            "txt2img": {
                "model": "test_model.safetensors",
                "vae": "test_vae.safetensors",
                "sampler_name": "Euler a",
                "scheduler": "normal",
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "seed": -1,
                "clip_skip": 2,
            },
            "pipeline": {
                "batch_size": 1,
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": False,
                "upscale_enabled": False,
            },
        }
        img2img_card = Mock()
        img2img_card.to_config_dict.return_value = {
            "img2img": {
                "model": "test_model.safetensors",
                "vae": "test_vae.safetensors",
                "sampler_name": "Euler a",
                "scheduler": "normal",
                "steps": 18,
                "cfg_scale": 6.5,
                "denoising_strength": 0.35,
            }
        }
        adetailer_card = Mock()
        adetailer_card.to_config_dict.return_value = {
            "adetailer": {
                "model": "test_model.safetensors",
                "vae": "test_vae.safetensors",
                "sampler_name": "DPM++ 2M",
                "scheduler": "Karras",
                "steps": 12,
                "cfg_scale": 5.5,
                "denoising_strength": 0.25,
            }
        }
        upscale_card = Mock()
        upscale_card.to_config_dict.return_value = {
            "upscale": {
                "model": "test_model.safetensors",
                "vae": "test_vae.safetensors",
                "steps": 20,
                "cfg_scale": 7.0,
                "upscale_factor": 2.0,
            }
        }
        stage_panel.txt2img_card = txt2img_card
        stage_panel.img2img_card = img2img_card
        stage_panel.adetailer_card = adetailer_card
        stage_panel.upscale_card = upscale_card
        app_controller._get_stage_cards_panel.return_value = stage_panel
        
        return app_controller

    @pytest.fixture
    def mock_pipeline_controller(self):
        """Mock pipeline controller with job service."""
        pipeline_controller = Mock()
        
        # Mock job service
        job_service = Mock()
        job_service.submit_job_with_run_mode = Mock()
        pipeline_controller._job_service = job_service
        
        # Mock runner
        pipeline_controller._run_job = Mock(return_value={"status": "completed"})
        
        return pipeline_controller

    @pytest.fixture
    def controller(self, learning_state, mock_app_controller, mock_pipeline_controller):
        """Create LearningController with mocks."""
        return LearningController(
            learning_state=learning_state,
            pipeline_controller=mock_pipeline_controller,
            app_controller=mock_app_controller,
        )

    def test_build_variant_njr_with_stage_config(self, controller, learning_state):
        """Test 1: NJR construction with explicit config from stage cards."""
        # Create variant
        variant = LearningVariant(param_value=8.5, planned_images=1)
        experiment = learning_state.current_experiment
        
        # Build NJR
        record = controller._build_variant_njr(variant, experiment)
        
        # Verify NJR is created
        assert isinstance(record, NormalizedJobRecord)
        
        # Verify explicit config fields (from stage cards)
        assert record.base_model == "test_model.safetensors"
        assert record.vae == "test_vae.safetensors"
        assert record.sampler_name == "Euler a"
        assert record.scheduler == "normal"
        assert record.steps == 20
        assert record.width == 512
        assert record.height == 512
        
        # Verify CFG override was applied
        assert record.cfg_scale == 8.5  # variant value, not baseline 7.0
        
        # Verify prompt (NO DUPLICATION)
        assert record.positive_prompt == "a beautiful landscape"
        # Note: negative_prompt comes from experiment or fallback
        
        # Verify learning metadata
        assert record.extra_metadata is not None
        assert record.extra_metadata["learning_enabled"] is True
        assert record.extra_metadata["learning_variable"] == "CFG Scale"
        assert record.extra_metadata["learning_variant_value"] == 8.5

    def test_build_variant_njr_carries_images_per_value_to_images_per_prompt(
        self, controller, learning_state
    ):
        learning_state.current_experiment.images_per_value = 3
        variant = LearningVariant(param_value=8.5, planned_images=3)

        record = controller._build_variant_njr(variant, learning_state.current_experiment)

        assert record.images_per_prompt == 3

    def test_njr_prompt_not_duplicated(self, controller, learning_state):
        """Test 2: Verify single prompt occurrence in NJR."""
        variant = LearningVariant(param_value=7.0, planned_images=1)
        experiment = learning_state.current_experiment
        
        # Build NJR
        record = controller._build_variant_njr(variant, experiment)
        
        # Verify prompt appears exactly once
        assert record.positive_prompt == "a beautiful landscape"
        assert record.positive_prompt.count("a beautiful landscape") == 1
        
        # Verify no prompt in extra_metadata (metadata only)
        metadata = record.extra_metadata
        assert "prompt" not in metadata
        assert "positive_prompt" not in metadata

    def test_build_variant_njr_for_img2img_uses_input_image(self, controller, learning_state, tmp_path: Path):
        input_image = tmp_path / "input.png"
        input_image.write_bytes(b"fake")

        learning_state.current_experiment = LearningExperiment(
            name="ImageExperiment",
            stage="img2img",
            input_image_path=str(input_image),
            variable_under_test="Denoise Strength",
            prompt_text="a beautiful landscape",
            images_per_value=2,
        )
        variant = LearningVariant(param_value=0.45, planned_images=2)

        record = controller._build_variant_njr(variant, learning_state.current_experiment)

        assert isinstance(record, NormalizedJobRecord)
        assert record.start_stage == "img2img"
        assert record.stage_chain[0].stage_type == "img2img"
        assert record.stage_chain[0].denoising_strength == 0.45
        assert record.input_image_paths == [str(input_image), str(input_image)]
        assert record.extra_metadata["learning_stage"] == "img2img"

    def test_build_variant_njr_uses_plan_variant_index(self, controller, learning_state):
        variant_a = LearningVariant(param_value=7.0, planned_images=1)
        variant_b = LearningVariant(param_value=8.5, planned_images=1)
        learning_state.plan.extend([variant_a, variant_b])

        record = controller._build_variant_njr(variant_b, learning_state.current_experiment)

        assert record.learning_context is not None
        assert record.learning_context.variant_index == 1

    def test_submit_variant_job_uses_job_service(self, controller, learning_state, mock_pipeline_controller):
        """Test 3: Job submission via JobService, not PackJobEntry."""
        variant = LearningVariant(param_value=7.0, planned_images=1)
        learning_state.plan.append(variant)
        
        # Submit job
        controller._submit_variant_job(variant)
        
        # Verify JobService was called
        job_service = mock_pipeline_controller._job_service
        assert job_service.submit_job_with_run_mode.called
        
        # Verify job was submitted
        call_args = job_service.submit_job_with_run_mode.call_args
        submitted_job = call_args[0][0]
        
        # Verify job has NJR attached
        assert hasattr(submitted_job, "_normalized_record")
        record = submitted_job._normalized_record
        assert isinstance(record, NormalizedJobRecord)
        
        # Verify config propagation
        assert record.base_model == "test_model.safetensors"
        assert record.vae == "test_vae.safetensors"
        
        # Verify variant status updated
        assert variant.status == "queued"

    def test_learning_job_full_config_propagation(self, controller, learning_state, mock_pipeline_controller):
        """Test 4: End-to-end config propagation from stage cards to NJR."""
        variant = LearningVariant(param_value=9.0, planned_images=1)
        learning_state.plan.append(variant)
        
        # Submit and capture job
        controller._submit_variant_job(variant)
        
        job_service = mock_pipeline_controller._job_service
        submitted_job = job_service.submit_job_with_run_mode.call_args[0][0]
        record = submitted_job._normalized_record
        
        # Verify complete config chain
        assert record.base_model == "test_model.safetensors"
        assert record.vae == "test_vae.safetensors"
        assert record.sampler_name == "Euler a"
        assert record.scheduler == "normal"
        assert record.cfg_scale == 9.0  # variant override
        assert record.steps == 20
        assert record.width == 512
        assert record.height == 512
        
        # Verify job config_snapshot matches NJR
        assert submitted_job.config_snapshot["model"] == "test_model.safetensors"
        assert submitted_job.config_snapshot["vae"] == "test_vae.safetensors"
        assert submitted_job.config_snapshot["sampler"] == "Euler a"
        assert submitted_job.config_snapshot["cfg_scale"] == 9.0

    def test_execute_learning_job(self, controller, mock_pipeline_controller):
        """Test 5: Job execution via pipeline runner."""
        # Create mock job with NJR
        from src.queue.job_model import Job, JobPriority
        
        record = NormalizedJobRecord(
            job_id="test-job",
            positive_prompt="test prompt",
            base_model="model.safetensors",
            vae="vae.safetensors",
            sampler_name="Euler a",
            scheduler="normal",
            steps=20,
            cfg_scale=7.0,
            width=512,
            height=512,
            seed=-1,
            config={},
            path_output_dir="",
            filename_template="",
        )
        
        job = Job(
            job_id="test-job",
            priority=JobPriority.NORMAL,
            run_mode="queue",
            source="learning",
        )
        job._normalized_record = record
        
        # Execute
        result = controller._execute_learning_job(job)
        
        # Verify runner was called
        assert mock_pipeline_controller._run_job.called
        assert result["status"] == "completed"

    def test_no_packjobentry_imports(self, controller):
        """Test 6: Verify no PackJobEntry imports or usage."""
        import inspect
        source = inspect.getsource(controller._submit_variant_job)
        
        # Verify no PackJobEntry references (but comment is OK)
        source_lines = [line for line in source.split('\n') if not line.strip().startswith('#')]
        source_code = '\n'.join(source_lines)
        
        assert "from src.gui.app_state_v2 import PackJobEntry" not in source_code
        assert "job_draft.packs" not in source_code
        assert "on_add_job_to_queue_v2" not in source_code
        
        # Verify NJR usage
        assert "_build_variant_njr" in source
        assert "_njr_to_queue_job" in source
        assert "job_service" in source or "JobService" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
