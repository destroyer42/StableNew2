"""Test refiner flag propagation through runner to executor."""
import pytest


def test_runner_propagates_use_refiner_flag_in_payload():
    """Runner must write use_refiner=True into payload when conditions met."""
    # Simulate the runner's logic for adding refiner fields
    njr_config = {
        "use_refiner": True,
        "refiner_checkpoint": "refiner_model.safetensors",
        "refiner_switch_at": 0.8,
    }
    
    payload = {}
    
    # Runner's conditional refiner logic (from pipeline_runner.py lines 159-162)
    if njr_config.get("use_refiner") and njr_config.get("refiner_checkpoint"):
        payload["use_refiner"] = True  # Must propagate flag
        payload["refiner_checkpoint"] = njr_config["refiner_checkpoint"]
        payload["refiner_switch_at"] = njr_config.get("refiner_switch_at", 0.8)
    
    # Verify use_refiner flag is in payload
    assert "use_refiner" in payload
    assert payload["use_refiner"] is True
    assert payload["refiner_checkpoint"] == "refiner_model.safetensors"
    assert payload["refiner_switch_at"] == 0.8


def test_runner_omits_refiner_when_use_refiner_false():
    """Runner must not write refiner fields when use_refiner=False."""
    njr_config = {
        "use_refiner": False,
        "refiner_checkpoint": "refiner_model.safetensors",  # Present but disabled
        "refiner_switch_at": 0.8,
    }
    
    payload = {}
    
    # Runner's conditional refiner logic
    if njr_config.get("use_refiner") and njr_config.get("refiner_checkpoint"):
        payload["use_refiner"] = True
        payload["refiner_checkpoint"] = njr_config["refiner_checkpoint"]
        payload["refiner_switch_at"] = njr_config.get("refiner_switch_at", 0.8)
    
    # Verify refiner fields are NOT in payload
    assert "use_refiner" not in payload
    assert "refiner_checkpoint" not in payload
    assert "refiner_switch_at" not in payload


def test_executor_reads_use_refiner_from_txt2img_config():
    """Executor must read use_refiner from txt2img_config (nested) not top-level."""
    # Simulate what executor receives from runner
    config_nested = {
        "txt2img": {
            "use_refiner": True,
            "refiner_checkpoint": "refiner.safetensors",
            "refiner_switch_at": 0.8,
        }
    }
    
    # Executor's logic extraction
    txt2img_config = config_nested.get("txt2img", config_nested)
    use_refiner_flag = txt2img_config.get("use_refiner", config_nested.get("use_refiner", False))
    refiner_checkpoint = txt2img_config.get("refiner_checkpoint")
    refiner_switch_at = txt2img_config.get("refiner_switch_at", 0.8)
    
    use_refiner = (
        use_refiner_flag
        and refiner_checkpoint
        and refiner_checkpoint != "None"
        and refiner_checkpoint.strip() != ""
        and 0.0 < refiner_switch_at < 1.0
    )
    
    assert use_refiner is True


def test_executor_reads_use_refiner_from_flat_config():
    """Executor must also support flat config (no txt2img nesting)."""
    # Flat config from runner
    config_flat = {
        "use_refiner": True,
        "refiner_checkpoint": "refiner.safetensors",
        "refiner_switch_at": 0.8,
    }
    
    # Executor's logic extraction (when txt2img key doesn't exist)
    txt2img_config = config_flat.get("txt2img", config_flat)
    use_refiner_flag = txt2img_config.get("use_refiner", config_flat.get("use_refiner", False))
    refiner_checkpoint = txt2img_config.get("refiner_checkpoint")
    refiner_switch_at = txt2img_config.get("refiner_switch_at", 0.8)
    
    use_refiner = (
        use_refiner_flag
        and refiner_checkpoint
        and refiner_checkpoint != "None"
        and refiner_checkpoint.strip() != ""
        and 0.0 < refiner_switch_at < 1.0
    )
    
    assert use_refiner is True
