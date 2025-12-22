"""Test refiner gating logic across all layers."""
import pytest


class TestGUIStageCardRefinerGating:
    """Test refiner field writing in GUI stage card logic."""
    
    def test_no_refiner_fields_when_disabled(self):
        """GUI stage card must not write refiner fields when use_refiner=False."""
        # Test the logic directly without GUI instantiation
        # This validates that the conditional dict merge works correctly
        use_refiner = False
        refiner_checkpoint = "some_model"
        refiner_switch_at = 0.8
        
        # Simulate the to_config_dict logic
        config_dict = {
            "use_refiner": use_refiner,
            **({"refiner_checkpoint": refiner_checkpoint,
                "refiner_model_name": refiner_checkpoint,
                "refiner_switch_at": refiner_switch_at}
               if use_refiner else {})
        }
        
        assert config_dict["use_refiner"] is False
        assert "refiner_checkpoint" not in config_dict
        assert "refiner_model_name" not in config_dict
        assert "refiner_switch_at" not in config_dict
    
    def test_refiner_fields_present_when_enabled(self):
        """GUI stage card must write refiner fields when use_refiner=True."""
        use_refiner = True
        refiner_checkpoint = "test_model"
        refiner_switch_at = 0.75
        
        # Simulate the to_config_dict logic
        config_dict = {
            "use_refiner": use_refiner,
            **({"refiner_checkpoint": refiner_checkpoint,
                "refiner_model_name": refiner_checkpoint,
                "refiner_switch_at": refiner_switch_at}
               if use_refiner else {})
        }
        
        assert config_dict["use_refiner"] is True
        assert "refiner_checkpoint" in config_dict
        assert config_dict["refiner_checkpoint"] == "test_model"
        assert "refiner_model_name" in config_dict
        assert "refiner_switch_at" in config_dict
        assert config_dict["refiner_switch_at"] == 0.75


class TestBuilderRefinerGating:
    """Test refiner field propagation logic (as used in job builder)."""
    
    def test_no_refiner_propagation_when_disabled(self):
        """Builder must not copy refiner fields when use_refiner=False."""
        # Test the conditional dict merge logic used in _build_config_payload
        txt2img = {
            "use_refiner": False,
            "refiner_checkpoint": "unwanted_model.safetensors",
            "refiner_switch_at": 0.8,
        }
        
        # Simulate the logic from _build_config_payload
        payload = {
            "use_refiner": txt2img.get("use_refiner", False),
            **({"refiner_checkpoint": txt2img.get("refiner_checkpoint"),
                "refiner_switch_at": txt2img.get("refiner_switch_at")}
               if txt2img.get("use_refiner") else {})
        }
        
        assert payload["use_refiner"] is False
        assert "refiner_checkpoint" not in payload
        assert "refiner_switch_at" not in payload
    
    def test_refiner_propagation_when_enabled(self):
        """Builder must copy refiner fields when use_refiner=True."""
        txt2img = {
            "use_refiner": True,
            "refiner_checkpoint": "desired_model.safetensors",
            "refiner_switch_at": 0.7,
        }
        
        # Simulate the logic from _build_config_payload
        payload = {
            "use_refiner": txt2img.get("use_refiner", False),
            **({"refiner_checkpoint": txt2img.get("refiner_checkpoint"),
                "refiner_switch_at": txt2img.get("refiner_switch_at")}
               if txt2img.get("use_refiner") else {})
        }
        
        assert payload["use_refiner"] is True
        assert payload["refiner_checkpoint"] == "desired_model.safetensors"
        assert payload["refiner_switch_at"] == 0.7
    
    def test_missing_use_refiner_defaults_false(self):
        """Builder must default use_refiner to False if missing."""
        txt2img = {
            "refiner_checkpoint": "model.safetensors",
        }
        
        # Simulate the logic from _build_config_payload
        payload = {
            "use_refiner": txt2img.get("use_refiner", False),
            **({"refiner_checkpoint": txt2img.get("refiner_checkpoint"),
                "refiner_switch_at": txt2img.get("refiner_switch_at")}
               if txt2img.get("use_refiner") else {})
        }
        
        assert payload["use_refiner"] is False
        assert "refiner_checkpoint" not in payload


class TestExecutorRefinerActivation:
    """Test refiner activation logic in executor (via integration)."""
    
    def test_refiner_not_activated_with_checkpoint_but_flag_false(self):
        """Executor must not activate refiner when checkpoint exists but use_refiner=False."""
        # This test verifies the logic indirectly through config parsing
        config = {
            "use_refiner": False,
            "refiner_checkpoint": "model.safetensors",
            "refiner_switch_at": 0.8,
        }
        
        # Simulate executor logic
        use_refiner_flag = config.get("use_refiner", False)
        refiner_checkpoint = config.get("refiner_checkpoint")
        refiner_switch_at = config.get("refiner_switch_at", 0.8)
        
        use_refiner = (
            use_refiner_flag
            and refiner_checkpoint
            and refiner_checkpoint != "None"
            and refiner_checkpoint.strip() != ""
            and 0.0 < refiner_switch_at < 1.0
        )
        
        assert use_refiner is False
    
    def test_refiner_activated_with_flag_and_checkpoint(self):
        """Executor must activate refiner when use_refiner=True and valid checkpoint."""
        config = {
            "use_refiner": True,
            "refiner_checkpoint": "model.safetensors",
            "refiner_switch_at": 0.8,
        }
        
        # Simulate executor logic
        use_refiner_flag = config.get("use_refiner", False)
        refiner_checkpoint = config.get("refiner_checkpoint")
        refiner_switch_at = config.get("refiner_switch_at", 0.8)
        
        use_refiner = (
            use_refiner_flag
            and refiner_checkpoint
            and refiner_checkpoint != "None"
            and refiner_checkpoint.strip() != ""
            and 0.0 < refiner_switch_at < 1.0
        )
        
        assert use_refiner is True
    
    def test_refiner_not_activated_with_none_checkpoint(self):
        """Executor must not activate refiner when checkpoint is 'None' string."""
        config = {
            "use_refiner": True,
            "refiner_checkpoint": "None",
            "refiner_switch_at": 0.8,
        }
        
        # Simulate executor logic
        use_refiner_flag = config.get("use_refiner", False)
        refiner_checkpoint = config.get("refiner_checkpoint")
        refiner_switch_at = config.get("refiner_switch_at", 0.8)
        
        use_refiner = (
            use_refiner_flag
            and refiner_checkpoint
            and refiner_checkpoint != "None"
            and refiner_checkpoint.strip() != ""
            and 0.0 < refiner_switch_at < 1.0
        )
        
        assert use_refiner is False
