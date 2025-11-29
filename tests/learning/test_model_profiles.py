import tempfile
import json
from pathlib import Path
import pytest
from src.learning.model_profiles import (
    ModelProfile, LoraProfile, ModelPreset, LoraOverlay,
    LoraRecommendedWeight, LoraRecommendedPairing,
    load_model_profile, load_lora_profile, suggest_preset_for
)

def make_model_profile(path: Path, presets=None):
    data = {
        "kind": "model_profile",
        "version": 1,
        "model_name": "TestModel",
        "base_type": "sdxl",
        "tags": ["test"],
        "recommended_presets": presets or [],
        "learning_summary": {"runs_observed": 1, "mean_rating": 4.5},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path

def make_lora_profile(path: Path, weights=None):
    data = {
        "kind": "lora_profile",
        "version": 1,
        "lora_name": "TestLora",
        "target_base_type": "sdxl",
        "intended_use": ["portrait"],
        "trigger_phrases": ["test"],
        "recommended_weights": weights or [],
        "recommended_pairings": [],
        "learning_summary": {"runs_observed": 1, "mean_rating": 4.0},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path

def test_load_model_profile_from_json_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.modelprofile.json"
        make_model_profile(path)
        profile = load_model_profile(path)
        assert profile is not None
        assert profile.model_name == "TestModel"
        assert profile.kind == "model_profile"
        assert profile.version == 1

def test_load_lora_profile_from_json_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.loraprofile.json"
        make_lora_profile(path)
        profile = load_lora_profile(path)
        assert profile is not None
        assert profile.lora_name == "TestLora"
        assert profile.kind == "lora_profile"
        assert profile.version == 1

def test_suggest_preset_picks_highest_rated_preset():
    presets = [
        ModelPreset(id="1", label="bad", rating="bad", source="internet_prior", sampler="Euler", scheduler=None, steps=10, cfg=5.0, resolution=(512,512)),
        ModelPreset(id="2", label="good", rating="good", source="internet_prior", sampler="DPM++", scheduler="Karras", steps=30, cfg=6.5, resolution=(1024,1024)),
        ModelPreset(id="3", label="best", rating="best", source="internet_prior", sampler="DPM++ 2M Karras", scheduler="Karras", steps=40, cfg=7.0, resolution=(1280,1280)),
    ]
    profile = ModelProfile(
        kind="model_profile", version=1, model_name="TestModel", base_type="sdxl", tags=[], recommended_presets=presets, learning_summary={}
    )
    result = suggest_preset_for(profile, [])
    assert result is not None
    assert result.sampler == "DPM++ 2M Karras"
    assert result.steps == 40
    assert result.cfg == 7.0
    assert result.resolution == (1280,1280)

def test_suggest_preset_merges_lora_weights():
    preset = ModelPreset(
        id="1", label="best", rating="best", source="internet_prior", sampler="Euler", scheduler=None, steps=20, cfg=5.5, resolution=(512,512), lora_overlays=[LoraOverlay(name="TestLora", weight=0.7)]
    )
    model_profile = ModelProfile(
        kind="model_profile", version=1, model_name="TestModel", base_type="sdxl", tags=[], recommended_presets=[preset], learning_summary={}
    )
    lora_profile = LoraProfile(
        kind="lora_profile", version=1, lora_name="TestLora", target_base_type="sdxl", intended_use=[], trigger_phrases=[], recommended_weights=[LoraRecommendedWeight(label="default", weight=0.8, rating="best")], recommended_pairings=[], learning_summary={}
    )
    result = suggest_preset_for(model_profile, [lora_profile])
    assert result is not None
    assert "TestLora" in result.lora_weights
    # Should prefer lora_profile's recommended weight
    assert result.lora_weights["TestLora"] == 0.8

def test_suggest_preset_returns_none_if_no_presets():
    profile = ModelProfile(
        kind="model_profile", version=1, model_name="TestModel", base_type="sdxl", tags=[], recommended_presets=[], learning_summary={}
    )
    result = suggest_preset_for(profile, [])
    assert result is None
