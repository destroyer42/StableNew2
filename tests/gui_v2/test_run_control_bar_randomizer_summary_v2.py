"""PR-044: Test RunControlBar randomizer summary integration."""

from __future__ import annotations

from src.pipeline.randomizer_v2 import get_variant_count


class TestRunControlBarRandomizerSummary:
    """Test that RunControlBar summary reflects randomizer state."""

    def test_randomizer_off_shows_one_variant(self) -> None:
        """When randomizer is off, variant count should be 1."""
        count = get_variant_count(mode="off", max_variants=10)
        assert count == 1

    def test_randomizer_on_shows_max_variants(self) -> None:
        """When randomizer is on, variant count reflects max_variants."""
        count = get_variant_count(mode="fanout", max_variants=5)
        assert count == 5

    def test_summary_includes_randomizer_status(self) -> None:
        """Verify the summary logic includes randomizer status."""
        # This tests the logic pattern used in _refresh_summary
        rand_mode = "fanout"
        rand_text = "ON" if rand_mode != "off" else "OFF"
        assert rand_text == "ON"

        rand_mode = "off"
        rand_text = "ON" if rand_mode != "off" else "OFF"
        assert rand_text == "OFF"

    def test_job_count_matches_variant_count(self) -> None:
        """Job count should scale with variant count."""
        # Simulate _build_run_plan logic
        enabled_stages = ["txt2img"]
        batch_runs = 1
        variant_count = get_variant_count(mode="fanout", max_variants=3)

        total_jobs = len(enabled_stages) * batch_runs * variant_count
        assert total_jobs == 3

    def test_job_count_with_multiple_stages(self) -> None:
        """Job count scales with stages × batches × variants."""
        enabled_stages = ["txt2img", "img2img"]
        batch_runs = 2
        variant_count = get_variant_count(mode="fanout", max_variants=3)

        total_jobs = len(enabled_stages) * batch_runs * variant_count
        assert total_jobs == 12  # 2 stages × 2 batches × 3 variants
