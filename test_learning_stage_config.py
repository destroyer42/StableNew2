"""Test that learning controller retrieves stage card configuration properly.

This test verifies the bugfix where learning jobs were getting empty/null
configuration values because the learning controller couldn't access the stage cards.
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from src.models.state.learning_state import LearningState
from src.gui.controllers.learning_controller import LearningController


class MockStageCard:
    """Mock stage card with configuration."""
    
    def to_config_dict(self):
        """Return a complete config dict like the real stage card."""
        return {
            "txt2img": {
                "model": "test_model.safetensors",
                "vae": "test_vae.safetensors",
                "sampler_name": "Euler a",
                "scheduler": "normal",
                "steps": 25,
                "cfg_scale": 7.5,
                "width": 512,
                "height": 768,
                "seed": 42,
                "clip_skip": 2,
            },
            "pipeline": {
                "batch_size": 1,
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": False,
                "upscale_enabled": False,
            }
        }


class MockStagePanel:
    """Mock stage cards panel."""
    
    def __init__(self):
        self.txt2img_card = MockStageCard()


class MockAppController:
    """Mock app controller with stage card access."""
    
    def _get_stage_cards_panel(self):
        """Return mock stage panel."""
        return MockStagePanel()


def test_baseline_config_with_app_controller():
    """Test that baseline config retrieves stage card configuration when app_controller is provided."""
    print("\n=== Test: Baseline Config with App Controller ===")
    
    # Create learning controller with app_controller
    learning_state = LearningState()
    app_controller = MockAppController()
    controller = LearningController(
        learning_state=learning_state,
        app_controller=app_controller
    )
    
    # Get baseline config
    baseline = controller._get_baseline_config()
    
    # Verify config has proper values from stage card
    print(f"\nBaseline config keys: {list(baseline.keys())}")
    print(f"txt2img keys: {list(baseline.get('txt2img', {}).keys())}")
    
    # Check critical values
    txt2img = baseline.get("txt2img", {})
    assert txt2img.get("model") == "test_model.safetensors", f"Expected model='test_model.safetensors', got '{txt2img.get('model')}'"
    assert txt2img.get("vae") == "test_vae.safetensors", f"Expected vae='test_vae.safetensors', got '{txt2img.get('vae')}'"
    assert txt2img.get("sampler_name") == "Euler a", f"Expected sampler='Euler a', got '{txt2img.get('sampler_name')}'"
    assert txt2img.get("scheduler") == "normal", f"Expected scheduler='normal', got '{txt2img.get('scheduler')}'"
    assert txt2img.get("seed") == 42, f"Expected seed=42, got {txt2img.get('seed')}"
    
    # Check that subseed parameters were added
    assert txt2img.get("subseed") == -1, f"Expected subseed=-1, got {txt2img.get('subseed')}"
    assert txt2img.get("subseed_strength") == 0.0, f"Expected subseed_strength=0.0, got {txt2img.get('subseed_strength')}"
    assert txt2img.get("seed_resize_from_h") == 0, f"Expected seed_resize_from_h=0, got {txt2img.get('seed_resize_from_h')}"
    assert txt2img.get("seed_resize_from_w") == 0, f"Expected seed_resize_from_w=0, got {txt2img.get('seed_resize_from_w')}"
    
    # Check pipeline section exists
    assert "pipeline" in baseline, "Missing pipeline section"
    pipeline = baseline["pipeline"]
    assert pipeline.get("txt2img_enabled") is True, f"Expected txt2img_enabled=True, got {pipeline.get('txt2img_enabled')}"
    
    print("\n✅ All assertions passed!")
    print("\nConfig values retrieved:")
    print(f"  model: {txt2img.get('model')}")
    print(f"  vae: {txt2img.get('vae')}")
    print(f"  sampler: {txt2img.get('sampler_name')}")
    print(f"  scheduler: {txt2img.get('scheduler')}")
    print(f"  seed: {txt2img.get('seed')}")
    print(f"  subseed: {txt2img.get('subseed')}")
    print(f"  subseed_strength: {txt2img.get('subseed_strength')}")
    print(f"  steps: {txt2img.get('steps')}")
    print(f"  cfg_scale: {txt2img.get('cfg_scale')}")
    
    return True


def test_baseline_config_without_app_controller():
    """Test that baseline config falls back gracefully when no app_controller is provided."""
    print("\n=== Test: Baseline Config Fallback (No App Controller) ===")
    
    # Create learning controller without app_controller
    learning_state = LearningState()
    controller = LearningController(learning_state=learning_state)
    
    # Get baseline config
    baseline = controller._get_baseline_config()
    
    # Verify config has at least the structure (values may be empty)
    print(f"\nBaseline config keys: {list(baseline.keys())}")
    
    # Should still have subseed parameters even in fallback
    if "txt2img" in baseline:
        txt2img = baseline["txt2img"]
        print(f"txt2img keys: {list(txt2img.keys())}")
        print(f"  subseed: {txt2img.get('subseed')}")
        print(f"  subseed_strength: {txt2img.get('subseed_strength')}")
        assert txt2img.get("subseed") == -1, f"Expected subseed=-1 in fallback, got {txt2img.get('subseed')}"
        assert txt2img.get("subseed_strength") == 0.0, f"Expected subseed_strength=0.0 in fallback, got {txt2img.get('subseed_strength')}"
        print("\n✅ Fallback has subseed parameters")
    else:
        print("\n⚠️ Fallback returned empty config (no pipeline controller)")
    
    return True


if __name__ == "__main__":
    print("Testing learning controller baseline config retrieval...")
    
    try:
        test_baseline_config_with_app_controller()
        test_baseline_config_without_app_controller()
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
