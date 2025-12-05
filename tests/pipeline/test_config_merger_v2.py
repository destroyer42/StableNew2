# Subsystem: Pipeline
# Role: Tests for ConfigMergerV2 config merging logic.

"""Tests for ConfigMergerV2: PromptPack + stage overrides merger.

These tests verify:
1. Override disabled uses base config unchanged
2. Override enabled: field-level precedence (override wins if not None)
3. Nested refiner/hires sub-config merging
4. Nested stage disable behavior (override.enabled=False)
5. Pipeline-level merge across multiple stages
"""

from __future__ import annotations

import pytest

from src.pipeline.config_merger_v2 import (
    ADetailerOverrides,
    ConfigMergerV2,
    HiresOverrides,
    Img2ImgOverrides,
    RefinerOverrides,
    StageOverrideFlags,
    StageOverridesBundle,
    Txt2ImgOverrides,
    UpscaleOverrides,
)


# ---------------------------------------------------------------------------
# Fixtures: Base configs for testing
# ---------------------------------------------------------------------------


@pytest.fixture
def base_txt2img_config() -> dict:
    """A typical base txt2img config from PromptPack."""
    return {
        "model": "base_model.safetensors",
        "vae": "base_vae.safetensors",
        "sampler": "Euler a",
        "scheduler": "normal",
        "steps": 20,
        "cfg_scale": 7.0,
        "width": 512,
        "height": 512,
        "prompt": "base prompt",
        "negative_prompt": "base negative",
        "seed": 12345,
        "refiner": {
            "enabled": True,
            "model_name": "base_refiner.safetensors",
            "switch_at": 0.8,
        },
        "hires_fix": {
            "enabled": False,
            "upscaler_name": "R-ESRGAN 4x+",
            "denoise_strength": 0.5,
            "scale_factor": 2.0,
            "steps": 10,
        },
    }


@pytest.fixture
def base_pipeline_config(base_txt2img_config: dict) -> dict:
    """A full pipeline config with multiple stages."""
    return {
        **base_txt2img_config,
        "refiner_enabled": True,
        "img2img": {
            "enabled": False,
            "model": "base_img2img_model.safetensors",
            "sampler": "DPM++ 2M",
            "steps": 25,
            "denoise_strength": 0.65,
        },
        "upscale": {
            "enabled": True,
            "upscaler_name": "R-ESRGAN 4x+",
            "scale_factor": 2.0,
            "denoise_strength": 0.3,
            "tile_size": 512,
        },
        "adetailer": {
            "enabled": True,
            "model": "face_yolov8n.pt",
            "confidence": 0.3,
            "mask_blur": 4,
            "denoise_strength": 0.4,
        },
    }


# ---------------------------------------------------------------------------
# Test 1: Override disabled uses base config
# ---------------------------------------------------------------------------


class TestOverrideDisabledUsesBase:
    """When override flag is OFF, base config should be used unchanged."""

    def test_merge_stage_with_override_disabled(self) -> None:
        """merge_stage returns deep copy of base when override_enabled=False."""
        base = {"model": "base", "steps": 20, "enabled": True}
        override = {"model": "override", "steps": 50}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=False,
        )

        # Result should equal base values
        assert result["model"] == "base"
        assert result["steps"] == 20
        assert result["enabled"] is True
        # Override values should be ignored
        assert result["model"] != "override"
        assert result["steps"] != 50

    def test_merge_stage_returns_deep_copy(self) -> None:
        """Returned config should be a deep copy, not the same object."""
        base = {"model": "base", "nested": {"key": "value"}}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=None,
            override_enabled=False,
        )

        # Should be equal but not same object
        assert result == base
        assert result is not base
        assert result["nested"] is not base["nested"]

    def test_merge_stage_with_none_override(self) -> None:
        """merge_stage with None override returns base unchanged."""
        base = {"model": "base", "steps": 20}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=None,
            override_enabled=True,  # Even with flag True, None override = no change
        )

        assert result == base
        assert result is not base


# ---------------------------------------------------------------------------
# Test 2: Override enabled - field precedence
# ---------------------------------------------------------------------------


class TestOverrideEnabledPrecedence:
    """When override is enabled, override fields win over base (if not None)."""

    def test_override_field_takes_precedence(self) -> None:
        """Override field wins when not None."""
        base = {"model": "base_model", "steps": 20, "cfg_scale": 7.0}
        override = {"model": "override_model", "steps": None, "cfg_scale": 12.0}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["model"] == "override_model"  # Override wins
        assert result["steps"] == 20  # Falls back to base (override is None)
        assert result["cfg_scale"] == 12.0  # Override wins

    def test_override_preserves_unmentioned_fields(self) -> None:
        """Fields not in override are preserved from base."""
        base = {
            "model": "base",
            "steps": 20,
            "width": 512,
            "height": 768,
            "extra_field": "preserved",
        }
        override = {"model": "override", "steps": 30}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["model"] == "override"
        assert result["steps"] == 30
        assert result["width"] == 512  # Preserved
        assert result["height"] == 768  # Preserved
        assert result["extra_field"] == "preserved"  # Preserved

    def test_override_with_empty_string_wins(self) -> None:
        """Empty string is a valid override (not None)."""
        base = {"prompt": "base prompt", "negative_prompt": "base negative"}
        override = {"prompt": "", "negative_prompt": None}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["prompt"] == ""  # Empty string wins
        assert result["negative_prompt"] == "base negative"  # None falls back


# ---------------------------------------------------------------------------
# Test 3: Nested Refiner/Hires sub-config merging
# ---------------------------------------------------------------------------


class TestNestedRefinerHiresMerging:
    """Nested sub-configs merge with the same precedence rules."""

    def test_refiner_config_merge_field_precedence(self) -> None:
        """Refiner fields merge with override winning for non-None values."""
        base_refiner = {
            "enabled": True,
            "model_name": "base_refiner.safetensors",
            "switch_at": 0.8,
        }
        override_refiner = RefinerOverrides(
            enabled=True,
            model_name=None,  # Use base
            switch_at=0.6,  # Override
        )

        result = ConfigMergerV2.merge_refiner_config(
            base_refiner=base_refiner,
            override_refiner=override_refiner,
            override_enabled=True,
        )

        assert result["enabled"] is True
        assert result["model_name"] == "base_refiner.safetensors"  # Falls back
        assert result["switch_at"] == 0.6  # Override wins

    def test_hires_config_merge_field_precedence(self) -> None:
        """Hires fields merge with override winning for non-None values."""
        base_hires = {
            "enabled": False,
            "upscaler_name": "R-ESRGAN 4x+",
            "denoise_strength": 0.5,
            "scale_factor": 2.0,
            "steps": 10,
        }
        override_hires = HiresOverrides(
            enabled=True,  # Enable it
            upscaler_name="4x_foolhardy_Remacri",
            denoise_strength=None,  # Use base
            scale_factor=1.5,
            steps=None,  # Use base
        )

        result = ConfigMergerV2.merge_hires_config(
            base_hires=base_hires,
            override_hires=override_hires,
            override_enabled=True,
        )

        assert result["enabled"] is True  # Overridden to enabled
        assert result["upscaler_name"] == "4x_foolhardy_Remacri"  # Override
        assert result["denoise_strength"] == 0.5  # Falls back
        assert result["scale_factor"] == 1.5  # Override
        assert result["steps"] == 10  # Falls back

    def test_nested_dict_merge_in_merge_stage(self) -> None:
        """Nested dicts in merge_stage are recursively merged."""
        base = {
            "model": "base",
            "hires_fix": {
                "enabled": False,
                "scale_factor": 2.0,
                "denoise_strength": 0.5,
            },
        }
        override = {
            "model": "override",
            "hires_fix": {
                "enabled": True,
                "scale_factor": 1.5,
                # denoise_strength not specified = use base
            },
        }

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["model"] == "override"
        assert result["hires_fix"]["enabled"] is True
        assert result["hires_fix"]["scale_factor"] == 1.5
        assert result["hires_fix"]["denoise_strength"] == 0.5  # Preserved from base


# ---------------------------------------------------------------------------
# Test 4: Nested stage disable behavior
# ---------------------------------------------------------------------------


class TestNestedStageDisable:
    """When override.enabled=False, the stage should be disabled."""

    def test_refiner_disable_via_override(self) -> None:
        """override.enabled=False disables refiner entirely."""
        base_refiner = {
            "enabled": True,
            "model_name": "base_refiner.safetensors",
            "switch_at": 0.8,
        }
        override_refiner = RefinerOverrides(
            enabled=False,  # Explicitly disable
            model_name="ignored_model",
            switch_at=0.5,
        )

        result = ConfigMergerV2.merge_refiner_config(
            base_refiner=base_refiner,
            override_refiner=override_refiner,
            override_enabled=True,
        )

        assert result["enabled"] is False
        # Other fields may still be present but stage is disabled
        # The enabled=False is the key signal to downstream consumers

    def test_hires_disable_via_override(self) -> None:
        """override.enabled=False disables hires entirely."""
        base_hires = {
            "enabled": True,
            "upscaler_name": "R-ESRGAN 4x+",
            "scale_factor": 2.0,
        }
        override_hires = HiresOverrides(enabled=False)

        result = ConfigMergerV2.merge_hires_config(
            base_hires=base_hires,
            override_hires=override_hires,
            override_enabled=True,
        )

        assert result["enabled"] is False

    def test_adetailer_disable_via_override(self) -> None:
        """override.enabled=False disables adetailer."""
        base_ad = {
            "enabled": True,
            "model": "face_yolov8n.pt",
            "confidence": 0.3,
        }
        override_ad = ADetailerOverrides(enabled=False)

        result = ConfigMergerV2.merge_adetailer_config(
            base_adetailer=base_ad,
            override_adetailer=override_ad,
            override_enabled=True,
        )

        assert result["enabled"] is False


# ---------------------------------------------------------------------------
# Test 5: Pipeline-level merge across stages
# ---------------------------------------------------------------------------


class TestPipelineLevelMerge:
    """Test ConfigMergerV2.merge_pipeline for multi-stage merging."""

    def test_merge_pipeline_with_no_overrides(
        self, base_pipeline_config: dict
    ) -> None:
        """With no overrides, merge_pipeline returns deep copy of base."""
        flags = StageOverrideFlags()  # All flags False
        bundle = StageOverridesBundle()

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        # Should be deep equal but not same object
        assert result == base_pipeline_config
        assert result is not base_pipeline_config
        assert result["refiner"] is not base_pipeline_config["refiner"]

    def test_merge_pipeline_with_none_bundle(
        self, base_pipeline_config: dict
    ) -> None:
        """None bundle is handled gracefully."""
        flags = StageOverrideFlags(txt2img_override_enabled=True)

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=None,
            override_flags=flags,
        )

        assert result == base_pipeline_config
        assert result is not base_pipeline_config

    def test_merge_pipeline_txt2img_override(
        self, base_pipeline_config: dict
    ) -> None:
        """txt2img overrides are applied when flag is True."""
        flags = StageOverrideFlags(txt2img_override_enabled=True)
        bundle = StageOverridesBundle(
            txt2img=Txt2ImgOverrides(
                model="override_model.safetensors",
                steps=50,
                cfg_scale=12.0,
                prompt=None,  # Keep base prompt
            )
        )

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        assert result["model"] == "override_model.safetensors"
        assert result["steps"] == 50
        assert result["cfg_scale"] == 12.0
        assert result["prompt"] == "base prompt"  # Preserved

    def test_merge_pipeline_only_enabled_flags_apply(
        self, base_pipeline_config: dict
    ) -> None:
        """Only stages with override flags True are modified."""
        flags = StageOverrideFlags(
            txt2img_override_enabled=False,  # Should NOT apply txt2img
            upscale_override_enabled=True,  # Should apply upscale
        )
        bundle = StageOverridesBundle(
            txt2img=Txt2ImgOverrides(model="ignored.safetensors", steps=999),
            upscale=UpscaleOverrides(scale_factor=4.0, denoise_strength=0.1),
        )

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        # txt2img should be unchanged (flag was False)
        assert result["model"] == "base_model.safetensors"
        assert result["steps"] == 20

        # upscale should be overridden
        assert result["upscale"]["scale_factor"] == 4.0
        assert result["upscale"]["denoise_strength"] == 0.1

    def test_merge_pipeline_with_refiner_override(
        self, base_pipeline_config: dict
    ) -> None:
        """Refiner overrides are applied via its own flag."""
        flags = StageOverrideFlags(refiner_override_enabled=True)
        bundle = StageOverridesBundle(
            refiner=RefinerOverrides(
                enabled=True,
                model_name="new_refiner.safetensors",
                switch_at=0.7,
            )
        )

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        assert result["refiner"]["model_name"] == "new_refiner.safetensors"
        assert result["refiner"]["switch_at"] == 0.7
        assert result["refiner_enabled"] is True

    def test_merge_pipeline_with_hires_override(
        self, base_pipeline_config: dict
    ) -> None:
        """Hires overrides are applied via its own flag."""
        flags = StageOverrideFlags(hires_override_enabled=True)
        bundle = StageOverridesBundle(
            hires=HiresOverrides(
                enabled=True,
                upscaler_name="Latent",
                scale_factor=1.5,
            )
        )

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        assert result["hires_fix"]["enabled"] is True
        assert result["hires_fix"]["upscaler_name"] == "Latent"
        assert result["hires_fix"]["scale_factor"] == 1.5

    def test_merge_pipeline_with_adetailer_override(
        self, base_pipeline_config: dict
    ) -> None:
        """ADetailer overrides are applied via its own flag."""
        flags = StageOverrideFlags(adetailer_override_enabled=True)
        bundle = StageOverridesBundle(
            adetailer=ADetailerOverrides(
                enabled=True,
                model="person_yolov8s.pt",
                confidence=0.5,
            )
        )

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        assert result["adetailer"]["model"] == "person_yolov8s.pt"
        assert result["adetailer"]["confidence"] == 0.5
        assert result["adetailer"]["enabled"] is True

    def test_merge_pipeline_with_img2img_override(
        self, base_pipeline_config: dict
    ) -> None:
        """Img2img overrides are applied via its own flag."""
        flags = StageOverrideFlags(img2img_override_enabled=True)
        bundle = StageOverridesBundle(
            img2img=Img2ImgOverrides(
                enabled=True,
                denoise_strength=0.8,
                steps=40,
            )
        )

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        assert result["img2img"]["enabled"] is True
        assert result["img2img"]["denoise_strength"] == 0.8
        assert result["img2img"]["steps"] == 40

    def test_merge_pipeline_multiple_overrides(
        self, base_pipeline_config: dict
    ) -> None:
        """Multiple stages can be overridden simultaneously."""
        flags = StageOverrideFlags(
            txt2img_override_enabled=True,
            refiner_override_enabled=True,
            upscale_override_enabled=True,
        )
        bundle = StageOverridesBundle(
            txt2img=Txt2ImgOverrides(model="new_model.safetensors", steps=30),
            refiner=RefinerOverrides(switch_at=0.65),
            upscale=UpscaleOverrides(scale_factor=3.0),
        )

        result = ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        # All overrides applied
        assert result["model"] == "new_model.safetensors"
        assert result["steps"] == 30
        assert result["refiner"]["switch_at"] == 0.65
        assert result["upscale"]["scale_factor"] == 3.0


# ---------------------------------------------------------------------------
# Test 6: Immutability guarantees
# ---------------------------------------------------------------------------


class TestImmutabilityGuarantees:
    """Merger must not mutate inputs."""

    def test_merge_pipeline_does_not_mutate_base(
        self, base_pipeline_config: dict
    ) -> None:
        """merge_pipeline should not modify the base config."""
        import copy

        original = copy.deepcopy(base_pipeline_config)

        flags = StageOverrideFlags(txt2img_override_enabled=True)
        bundle = StageOverridesBundle(
            txt2img=Txt2ImgOverrides(model="mutated.safetensors", steps=100)
        )

        ConfigMergerV2.merge_pipeline(
            base_config=base_pipeline_config,
            stage_overrides=bundle,
            override_flags=flags,
        )

        # Original base should be unchanged
        assert base_pipeline_config == original

    def test_merge_stage_does_not_mutate_base(self) -> None:
        """merge_stage should not modify the base stage config."""
        import copy

        base = {"model": "base", "steps": 20, "nested": {"key": "value"}}
        original = copy.deepcopy(base)

        ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config={"model": "override", "nested": {"key": "new"}},
            override_enabled=True,
        )

        assert base == original

    def test_merge_refiner_does_not_mutate_base(self) -> None:
        """merge_refiner_config should not modify the base."""
        import copy

        base = {"enabled": True, "model_name": "base", "switch_at": 0.8}
        original = copy.deepcopy(base)

        ConfigMergerV2.merge_refiner_config(
            base_refiner=base,
            override_refiner=RefinerOverrides(switch_at=0.5),
            override_enabled=True,
        )

        assert base == original


# ---------------------------------------------------------------------------
# Test 7: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_base_config(self) -> None:
        """Merging into empty base config works."""
        base: dict = {}
        override = {"model": "new_model", "steps": 20}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["model"] == "new_model"
        assert result["steps"] == 20

    def test_empty_override_config(self) -> None:
        """Empty override config preserves all base values."""
        base = {"model": "base", "steps": 20}
        override: dict = {}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result == base
        assert result is not base

    def test_override_with_zero_value(self) -> None:
        """Zero is a valid override value (not None)."""
        base = {"steps": 20, "cfg_scale": 7.0, "seed": 12345}
        override = {"steps": 0, "cfg_scale": 0.0, "seed": 0}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["steps"] == 0
        assert result["cfg_scale"] == 0.0
        assert result["seed"] == 0

    def test_override_with_false_value(self) -> None:
        """False is a valid override value (not None)."""
        base = {"enabled": True, "feature": True}
        override = {"enabled": False, "feature": False}

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["enabled"] is False
        assert result["feature"] is False

    def test_deep_nested_dicts(self) -> None:
        """Deeply nested dicts are merged correctly."""
        base = {
            "level1": {
                "level2": {
                    "level3": {"value": "base", "other": "preserved"},
                }
            }
        }
        override = {
            "level1": {
                "level2": {
                    "level3": {"value": "override"},
                }
            }
        }

        result = ConfigMergerV2.merge_stage(
            base_stage_config=base,
            override_stage_config=override,
            override_enabled=True,
        )

        assert result["level1"]["level2"]["level3"]["value"] == "override"
        assert result["level1"]["level2"]["level3"]["other"] == "preserved"
