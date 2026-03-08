"""Test PipelineRunResult success flag propagation."""
import pytest
from src.pipeline.pipeline_runner import PipelineRunResult


class TestPipelineRunResultState:
    """Test PipelineRunResult state management and serialization."""
    
    def test_pipeline_result_variants_always_list(self):
        """PipelineRunResult to_dict() must always return variants as a list."""
        result = PipelineRunResult(
            run_id="test",
            success=True,
            error=None,
            variants=[],
            learning_records=[],
        )
        
        result_dict = result.to_dict()
        assert isinstance(result_dict["variants"], list)
        assert len(result_dict["variants"]) == 0
    
    def test_pipeline_result_with_variants(self):
        """PipelineRunResult with variants should serialize properly."""
        variants = [
            {"path": "/path/to/image1.png", "metadata": {}},
            {"path": "/path/to/image2.png", "metadata": {}},
        ]
        
        result = PipelineRunResult(
            run_id="test",
            success=True,
            error=None,
            variants=variants,
            learning_records=[],
        )
        
        result_dict = result.to_dict()
        assert isinstance(result_dict["variants"], list)
        assert len(result_dict["variants"]) == 2
        assert result_dict["variants"][0]["path"] == "/path/to/image1.png"
    
    def test_pipeline_result_error_sets_success_false(self):
        """PipelineRunResult with error should have success=False."""
        result = PipelineRunResult(
            run_id="test",
            success=False,
            error="Stage failed",
            variants=[],
            learning_records=[],
        )
        
        result_dict = result.to_dict()
        assert result_dict["success"] is False
        assert result_dict["error"] == "Stage failed"
    
    def test_pipeline_result_no_error_with_success(self):
        """PipelineRunResult with success=True should have no error."""
        result = PipelineRunResult(
            run_id="test",
            success=True,
            error=None,
            variants=[{"path": "/path/to/image.png"}],
            learning_records=[],
        )
        
        result_dict = result.to_dict()
        assert result_dict["success"] is True
        assert result_dict["error"] is None
    
    def test_pipeline_result_from_dict_roundtrip(self):
        """PipelineRunResult from_dict should reconstruct object correctly."""
        original_dict = {
            "run_id": "test123",
            "success": True,
            "error": None,
            "variants": [{"path": "/test.png"}],
            "learning_records": [],
            "randomizer_mode": "sweep",
            "randomizer_plan_size": 5,
            "metadata": {"key": "value"},
            "stage_events": [{"stage": "txt2img", "event": "complete"}],
        }
        
        result = PipelineRunResult.from_dict(original_dict)
        result_dict = result.to_dict()
        
        assert result_dict["run_id"] == "test123"
        assert result_dict["success"] is True
        assert result_dict["variants"] == [{"path": "/test.png"}]
        assert result_dict["randomizer_mode"] == "sweep"
        assert result_dict["randomizer_plan_size"] == 5
    
    def test_pipeline_result_empty_variants_is_valid(self):
        """Empty variants list should be valid (e.g., for failed runs)."""
        result = PipelineRunResult(
            run_id="test",
            success=False,
            error="No images generated",
            variants=[],
            learning_records=[],
        )
        
        result_dict = result.to_dict()
        assert isinstance(result_dict["variants"], list)
        assert len(result_dict["variants"]) == 0
        assert result_dict["success"] is False
        assert result_dict["error"] == "No images generated"
