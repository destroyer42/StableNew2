"""Unit tests for PR-CORE-E: Config Sweep Support.

Tests validate:
- ConfigVariantPlanV2 creation and validation
- JobBuilderV2 config sweep expansion
- Config override application
- Metadata propagation to NormalizedJobRecord
"""

from __future__ import annotations

import pytest

from src.pipeline.config_variant_plan_v2 import ConfigVariant, ConfigVariantPlanV2
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import BatchSettings

# ============================================================================
# ConfigVariantPlanV2 Tests
# ============================================================================


class TestConfigVariantPlanV2:
    """Test ConfigVariantPlanV2 data model and validation."""

    def test_single_variant_creation(self):
        """Test creating a simple single variant."""
        variant = ConfigVariant(
            label="cfg_low",
            overrides={"txt2img.cfg_scale": 4.5},
            index=0,
        )
        assert variant.label == "cfg_low"
        assert variant.overrides == {"txt2img.cfg_scale": 4.5}
        assert variant.index == 0

    def test_variant_requires_label(self):
        """Test that empty label raises ValueError."""
        with pytest.raises(ValueError, match="label must be non-empty"):
            ConfigVariant(label="", overrides={}, index=0)

    def test_variant_requires_dict_overrides(self):
        """Test that non-dict overrides raise TypeError."""
        with pytest.raises(TypeError, match="overrides must be a dict"):
            ConfigVariant(label="test", overrides="not-a-dict", index=0)  # type: ignore

    def test_variant_requires_nonnegative_index(self):
        """Test that negative index raises ValueError."""
        with pytest.raises(ValueError, match="index must be non-negative"):
            ConfigVariant(label="test", overrides={}, index=-1)

    def test_plan_enabled_requires_variants(self):
        """Test that enabled=True with empty variants raises ValueError."""
        with pytest.raises(ValueError, match="enabled=True requires at least one variant"):
            ConfigVariantPlanV2(enabled=True, variants=[])

    def test_plan_detects_duplicate_labels(self):
        """Test that duplicate variant labels are rejected."""
        variants = [
            ConfigVariant("cfg_low", {}, 0),
            ConfigVariant("cfg_high", {}, 1),
            ConfigVariant("cfg_low", {}, 2),  # Duplicate
        ]
        with pytest.raises(ValueError, match="duplicate variant labels"):
            ConfigVariantPlanV2(enabled=True, variants=variants)

    def test_plan_single_variant_factory(self):
        """Test ConfigVariantPlanV2.single_variant() factory."""
        plan = ConfigVariantPlanV2.single_variant("base")
        assert plan.enabled is False
        assert len(plan.variants) == 1
        assert plan.variants[0].label == "base"
        assert plan.variants[0].overrides == {}

    def test_plan_get_variant_count_disabled(self):
        """Test get_variant_count() returns 1 when disabled."""
        plan = ConfigVariantPlanV2(enabled=False, variants=[])
        assert plan.get_variant_count() == 1

    def test_plan_get_variant_count_enabled(self):
        """Test get_variant_count() returns actual count when enabled."""
        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant("cfg_low", {}, 0),
                ConfigVariant("cfg_mid", {}, 1),
                ConfigVariant("cfg_high", {}, 2),
            ],
        )
        assert plan.get_variant_count() == 3

    def test_plan_iter_variants_disabled(self):
        """Test iter_variants() yields single implicit variant when disabled."""
        plan = ConfigVariantPlanV2(enabled=False, variants=[])
        variants = list(plan.iter_variants())
        assert len(variants) == 1
        assert variants[0].label == "base"
        assert variants[0].overrides == {}

    def test_plan_iter_variants_enabled(self):
        """Test iter_variants() yields all variants when enabled."""
        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant("cfg_low", {}, 0),
                ConfigVariant("cfg_high", {}, 1),
            ],
        )
        variants = list(plan.iter_variants())
        assert len(variants) == 2
        assert variants[0].label == "cfg_low"
        assert variants[1].label == "cfg_high"

    def test_plan_serialization(self):
        """Test to_dict() and from_dict() roundtrip."""
        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant("cfg_low", {"txt2img.cfg_scale": 4.5}, 0),
                ConfigVariant("cfg_high", {"txt2img.cfg_scale": 10.0}, 1),
            ],
        )
        data = plan.to_dict()
        reconstructed = ConfigVariantPlanV2.from_dict(data)
        assert reconstructed.enabled == plan.enabled
        assert len(reconstructed.variants) == len(plan.variants)
        assert reconstructed.variants[0].label == plan.variants[0].label
        assert reconstructed.variants[0].overrides == plan.variants[0].overrides


# ============================================================================
# JobBuilderV2 Config Sweep Tests
# ============================================================================


class TestJobBuilderV2ConfigSweeps:
    """Test JobBuilderV2 config sweep expansion."""

    def test_no_sweep_produces_single_job(self):
        """Test that no sweep plan produces single job with base config."""
        builder = JobBuilderV2()
        base_config = {"cfg_scale": 7.0, "steps": 20, "seed": 42}

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=None,  # No sweep
        )

        assert len(jobs) == 1
        assert jobs[0].config_variant_label == "base"
        assert jobs[0].config_variant_index == 0
        assert jobs[0].config["cfg_scale"] == 7.0

    def test_disabled_sweep_produces_single_job(self):
        """Test that disabled sweep plan produces single job."""
        builder = JobBuilderV2()
        base_config = {"cfg_scale": 7.0, "steps": 20, "seed": 42}
        plan = ConfigVariantPlanV2(enabled=False, variants=[])

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=plan,
        )

        assert len(jobs) == 1
        assert jobs[0].config_variant_label == "base"

    def test_single_variant_sweep(self):
        """Test simple CFG sweep with 3 variants."""
        builder = JobBuilderV2()
        base_config = {"cfg_scale": 7.0, "steps": 20, "seed": 42}

        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant("cfg_low", {"cfg_scale": 4.5}, 0),
                ConfigVariant("cfg_mid", {"cfg_scale": 7.0}, 1),
                ConfigVariant("cfg_high", {"cfg_scale": 10.0}, 2),
            ],
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=plan,
        )

        assert len(jobs) == 3
        assert jobs[0].config_variant_label == "cfg_low"
        assert jobs[0].config["cfg_scale"] == 4.5
        assert jobs[1].config_variant_label == "cfg_mid"
        assert jobs[1].config["cfg_scale"] == 7.0
        assert jobs[2].config_variant_label == "cfg_high"
        assert jobs[2].config["cfg_scale"] == 10.0

    def test_multi_parameter_sweep(self):
        """Test sweep with multiple overrides per variant."""
        builder = JobBuilderV2()
        base_config = {"cfg_scale": 7.0, "steps": 20, "sampler_name": "Euler a", "seed": 42}

        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant(
                    "fast",
                    {"steps": 15, "sampler_name": "Euler a"},
                    0,
                ),
                ConfigVariant(
                    "quality",
                    {"steps": 30, "sampler_name": "DPM++ 2M Karras"},
                    1,
                ),
            ],
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=plan,
        )

        assert len(jobs) == 2
        assert jobs[0].config_variant_label == "fast"
        assert jobs[0].config["steps"] == 15
        assert jobs[0].config["sampler_name"] == "Euler a"
        assert jobs[1].config_variant_label == "quality"
        assert jobs[1].config["steps"] == 30
        assert jobs[1].config["sampler_name"] == "DPM++ 2M Karras"

    def test_sweep_with_batch_expansion(self):
        """Test config sweep × batch expansion = M×N jobs."""
        builder = JobBuilderV2()
        base_config = {"cfg_scale": 7.0, "steps": 20, "seed": 42}

        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant("cfg_low", {"cfg_scale": 4.5}, 0),
                ConfigVariant("cfg_high", {"cfg_scale": 10.0}, 1),
            ],
        )

        batch = BatchSettings(batch_size=1, batch_runs=3)

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=plan,
            batch_settings=batch,
        )

        # 2 config variants × 3 batch runs = 6 jobs
        assert len(jobs) == 6

        # First config variant (cfg_low) with 3 batches
        assert jobs[0].config_variant_label == "cfg_low"
        assert jobs[0].batch_index == 0
        assert jobs[1].config_variant_label == "cfg_low"
        assert jobs[1].batch_index == 1
        assert jobs[2].config_variant_label == "cfg_low"
        assert jobs[2].batch_index == 2

        # Second config variant (cfg_high) with 3 batches
        assert jobs[3].config_variant_label == "cfg_high"
        assert jobs[3].batch_index == 0
        assert jobs[4].config_variant_label == "cfg_high"
        assert jobs[4].batch_index == 1
        assert jobs[5].config_variant_label == "cfg_high"
        assert jobs[5].batch_index == 2

    def test_config_overrides_recorded_in_metadata(self):
        """Test that config_variant_overrides field is populated."""
        builder = JobBuilderV2()
        base_config = {"cfg_scale": 7.0, "steps": 20, "seed": 42}

        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant(
                    "custom",
                    {"cfg_scale": 8.5, "steps": 25},
                    0,
                ),
            ],
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=plan,
        )

        assert len(jobs) == 1
        assert jobs[0].config_variant_overrides == {"cfg_scale": 8.5, "steps": 25}

    def test_sweep_does_not_mutate_base_config(self):
        """Test that applying sweeps does not mutate original base_config."""
        builder = JobBuilderV2()
        base_config = {"cfg_scale": 7.0, "steps": 20, "seed": 42}
        original_cfg = base_config["cfg_scale"]

        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[ConfigVariant("cfg_high", {"cfg_scale": 10.0}, 0)],
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=plan,
        )

        # Base config should be unchanged
        assert base_config["cfg_scale"] == original_cfg
        # Job should have overridden value
        assert jobs[0].config["cfg_scale"] == 10.0

    def test_nested_config_override_dotnotation(self):
        """Test dot-notation overrides for nested config structures."""
        builder = JobBuilderV2()
        base_config = {
            "txt2img": {"cfg_scale": 7.0, "steps": 20},
            "img2img": {"denoising_strength": 0.5},
            "seed": 42,
        }

        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant(
                    "high_denoise",
                    {"txt2img.cfg_scale": 9.0, "img2img.denoising_strength": 0.8},
                    0,
                ),
            ],
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            config_variant_plan=plan,
        )

        assert len(jobs) == 1
        assert jobs[0].config["txt2img"]["cfg_scale"] == 9.0
        assert jobs[0].config["img2img"]["denoising_strength"] == 0.8


# ============================================================================
# Integration Tests
# ============================================================================


class TestConfigSweepIntegration:
    """Integration tests combining sweeps with randomization and batches."""

    def test_sweep_with_randomization_plan(self):
        """Test config sweep combined with matrix randomization (future)."""
        # This test is a placeholder for when RandomizationPlanV2 is integrated
        # Expected behavior: config_variants × matrix_variants × batches
        pytest.skip("Requires RandomizationPlanV2 integration")

    def test_sweep_determinism(self):
        """Test that identical sweep plans produce identical job orders."""
        builder = JobBuilderV2(
            time_fn=lambda: 1234567890.0,
            id_fn=lambda: "test-job-id",
        )

        base_config = {"cfg_scale": 7.0, "steps": 20, "seed": 42}

        plan = ConfigVariantPlanV2(
            enabled=True,
            variants=[
                ConfigVariant("cfg_low", {"cfg_scale": 4.5}, 0),
                ConfigVariant("cfg_high", {"cfg_scale": 10.0}, 1),
            ],
        )

        jobs1 = builder.build_jobs(base_config=base_config, config_variant_plan=plan)
        jobs2 = builder.build_jobs(base_config=base_config, config_variant_plan=plan)

        assert len(jobs1) == len(jobs2)
        for j1, j2 in zip(jobs1, jobs2, strict=True):
            assert j1.config_variant_label == j2.config_variant_label
            assert j1.config_variant_index == j2.config_variant_index
            assert j1.config["cfg_scale"] == j2.config["cfg_scale"]


# ============================================================================
# Prompt Resolution Integration (PR-CORE-E Spec)
# ============================================================================


class TestGlobalNegativeIntegration:
    """Test global negative application through UnifiedPromptResolver."""

    def test_global_negative_applied_in_resolver(self):
        """Test that UnifiedPromptResolver applies global negative correctly."""
        from src.pipeline.resolution_layer import UnifiedPromptResolver

        resolver = UnifiedPromptResolver()

        resolved = resolver.resolve(
            gui_prompt="a beautiful landscape",
            global_negative="blurry, bad quality",
            apply_global_negative=True,
            pack_negative="watermark",
        )

        # Order: global_negative, pack_negative
        assert "blurry, bad quality" in resolved.negative
        assert "watermark" in resolved.negative
        assert resolved.global_negative_applied is True

    def test_global_negative_disabled(self):
        """Test that global negative is skipped when apply_global_negative=False."""
        from src.pipeline.resolution_layer import UnifiedPromptResolver

        resolver = UnifiedPromptResolver()

        resolved = resolver.resolve(
            gui_prompt="a beautiful landscape",
            global_negative="blurry, bad quality",
            apply_global_negative=False,
            pack_negative="watermark",
        )

        assert "blurry, bad quality" not in resolved.negative
        assert "watermark" in resolved.negative
        assert resolved.global_negative_applied is False

    def test_global_negative_ordering(self):
        """Test that global negative appears before pack negative."""
        from src.pipeline.resolution_layer import UnifiedPromptResolver

        resolver = UnifiedPromptResolver()

        resolved = resolver.resolve(
            gui_prompt="test",
            global_negative="global_term",
            apply_global_negative=True,
            pack_negative="pack_term",
        )

        # Global should come first
        assert resolved.negative.index("global_term") < resolved.negative.index("pack_term")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
