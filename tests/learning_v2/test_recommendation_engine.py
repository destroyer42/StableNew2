"""Tests for the Automated Parameter Recommendation Engine (APRE)."""

import json
import tempfile
import unittest
from pathlib import Path

from src.learning.recommendation_engine import (
    RecommendationEngine,
)


class TestRecommendationEngine(unittest.TestCase):
    """Test cases for the RecommendationEngine."""

    def setUp(self):
        """Set up test fixtures."""
        # Create temporary file for test records
        self.temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        self.temp_path = Path(self.temp_file.name)
        self.temp_file.close()

        # Create engine
        self.engine = RecommendationEngine(self.temp_path)

    def tearDown(self):
        """Clean up test fixtures."""
        if self.temp_path.exists():
            self.temp_path.unlink()

    def _create_test_record(
        self,
        rating: int,
        sampler: str = "Euler a",
        scheduler: str = "Karras",
        steps: int = 20,
        cfg_scale: float = 7.0,
        experiment_name: str = "Test Exp",
        variable_under_test: str = "CFG Scale",
        variant_value: float = 7.0,
    ) -> dict:
        """Create a test learning record."""
        return {
            "run_id": f"test_run_{rating}",
            "timestamp": "2025-11-25T12:00:00",
            "base_config": {"prompt": "test prompt"},
            "variant_configs": [{"cfg_scale": cfg_scale}],
            "randomizer_mode": "learning_experiment",
            "randomizer_plan_size": 1,
            "primary_model": "test_model",
            "primary_sampler": sampler,
            "primary_scheduler": scheduler,
            "primary_steps": steps,
            "primary_cfg_scale": cfg_scale,
            "metadata": {
                "experiment_name": experiment_name,
                "variable_under_test": variable_under_test,
                "variant_value": variant_value,
                "image_path": f"test_image_{rating}.png",
                "user_rating": rating,
                "user_notes": f"Test rating {rating}",
            },
        }

    def test_empty_records(self):
        """Test behavior with no records."""
        recommendations = self.engine.recommend("test prompt", "txt2img")
        self.assertEqual(len(recommendations.recommendations), 0)

    def test_single_record(self):
        """Test recommendations from a single record."""
        # Write a single record
        record = self._create_test_record(rating=4, sampler="Euler a", steps=20, cfg_scale=7.0)
        with open(self.temp_path, "w") as f:
            f.write(json.dumps(record) + "\n")

        recommendations = self.engine.recommend("test prompt", "txt2img")

        # Should have recommendations for each parameter type
        param_names = {rec.parameter_name for rec in recommendations.recommendations}
        expected_params = {"sampler", "scheduler", "steps", "cfg_scale"}
        self.assertTrue(expected_params.issubset(param_names))

        # Check specific recommendations
        sampler_rec = recommendations.get_best_for_parameter("sampler")
        self.assertIsNotNone(sampler_rec)
        self.assertEqual(sampler_rec.recommended_value, "Euler a")
        self.assertEqual(sampler_rec.sample_count, 1)
        self.assertEqual(sampler_rec.mean_rating, 4.0)

    def test_multiple_records_same_values(self):
        """Test recommendations from multiple records with same values."""
        # Write multiple records with same parameter values but different ratings
        records = [
            self._create_test_record(rating=3, sampler="Euler a", steps=20, cfg_scale=7.0),
            self._create_test_record(rating=4, sampler="Euler a", steps=20, cfg_scale=7.0),
            self._create_test_record(rating=5, sampler="Euler a", steps=20, cfg_scale=7.0),
        ]

        with open(self.temp_path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        recommendations = self.engine.recommend("test prompt", "txt2img")

        # Check that ratings are averaged
        sampler_rec = recommendations.get_best_for_parameter("sampler")
        self.assertIsNotNone(sampler_rec)
        self.assertEqual(sampler_rec.recommended_value, "Euler a")
        self.assertEqual(sampler_rec.sample_count, 3)
        self.assertAlmostEqual(sampler_rec.mean_rating, 4.0, places=1)

    def test_multiple_records_different_values(self):
        """Test recommendations from records with different parameter values."""
        # Write records with different samplers
        records = [
            self._create_test_record(rating=3, sampler="Euler a"),
            self._create_test_record(rating=5, sampler="DPM++ 2M Karras"),
            self._create_test_record(rating=4, sampler="Euler a"),
        ]

        with open(self.temp_path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        recommendations = self.engine.recommend("test prompt", "txt2img")

        # Should recommend the most confident sampler (Euler a has 2 samples, higher confidence)
        sampler_rec = recommendations.get_best_for_parameter("sampler")
        self.assertIsNotNone(sampler_rec)
        self.assertEqual(sampler_rec.recommended_value, "Euler a")
        self.assertEqual(sampler_rec.sample_count, 2)
        self.assertEqual(sampler_rec.mean_rating, 3.5)

    def test_confidence_calculation(self):
        """Test confidence score calculation."""
        # Create records with varying sample counts
        records = [
            # High confidence: many samples, consistent rating
            self._create_test_record(rating=4, sampler="Euler a"),
            self._create_test_record(rating=4, sampler="Euler a"),
            self._create_test_record(rating=5, sampler="Euler a"),
            self._create_test_record(rating=4, sampler="Euler a"),
            # Low confidence: few samples
            self._create_test_record(rating=5, sampler="DPM++ 2M Karras"),
        ]

        with open(self.temp_path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        recommendations = self.engine.recommend("test prompt", "txt2img")

        euler_rec = recommendations.get_best_for_parameter("sampler")
        self.assertIsNotNone(euler_rec)
        self.assertEqual(euler_rec.recommended_value, "Euler a")

        # Should have higher confidence due to more samples
        self.assertGreater(euler_rec.confidence_score, 0.5)

    def test_numeric_parameter_ranges(self):
        """Test recommendations for numeric parameters with different values."""
        records = [
            self._create_test_record(rating=3, steps=10),
            self._create_test_record(rating=4, steps=20),
            self._create_test_record(rating=5, steps=30),
            self._create_test_record(rating=4, steps=20),
        ]

        with open(self.temp_path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        recommendations = self.engine.recommend("test prompt", "txt2img")

        steps_rec = recommendations.get_best_for_parameter("steps")
        self.assertIsNotNone(steps_rec)
        self.assertEqual(
            steps_rec.recommended_value, 20
        )  # Most reliable value (2 samples, mean 4.0)
        self.assertEqual(steps_rec.sample_count, 2)
        self.assertEqual(steps_rec.mean_rating, 4.0)

    def test_experiment_variable_tracking(self):
        """Test that experiment variables are properly tracked."""
        records = [
            self._create_test_record(
                rating=4, cfg_scale=6.0, variable_under_test="CFG Scale", variant_value=6.0
            ),
            self._create_test_record(
                rating=5, cfg_scale=8.0, variable_under_test="CFG Scale", variant_value=8.0
            ),
            self._create_test_record(
                rating=3, cfg_scale=10.0, variable_under_test="CFG Scale", variant_value=10.0
            ),
        ]

        with open(self.temp_path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        recommendations = self.engine.recommend("test prompt", "txt2img")

        cfg_rec = recommendations.get_best_for_parameter("cfg_scale")
        self.assertIsNotNone(cfg_rec)
        self.assertEqual(cfg_rec.recommended_value, 8.0)  # Highest rated CFG value
        self.assertEqual(cfg_rec.mean_rating, 5.0)

    def test_ui_format_conversion(self):
        """Test conversion to UI format."""
        record = self._create_test_record(rating=4, sampler="Euler a")
        with open(self.temp_path, "w") as f:
            f.write(json.dumps(record) + "\n")

        recommendations = self.engine.recommend("test prompt", "txt2img")
        ui_format = recommendations.to_ui_format()

        self.assertIsInstance(ui_format, list)
        self.assertGreater(len(ui_format), 0)

        # Check structure of first recommendation
        rec_dict = ui_format[0]
        self.assertIn("parameter", rec_dict)
        self.assertIn("value", rec_dict)
        self.assertIn("confidence", rec_dict)
        self.assertIn("samples", rec_dict)

    def test_statistics(self):
        """Test statistics reporting."""
        records = [
            self._create_test_record(rating=4),
            self._create_test_record(rating=5),
        ]

        with open(self.temp_path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        stats = self.engine.get_statistics()
        self.assertIn("total_records", stats)
        self.assertIn("rated_records", stats)
        self.assertEqual(stats["rated_records"], 2)

    def test_malformed_json_handling(self):
        """Test handling of malformed JSON records."""
        # Write some valid and invalid JSON
        with open(self.temp_path, "w") as f:
            f.write('{"valid": "json"}\n')
            f.write('{"incomplete": json\n')  # Malformed
            f.write('{"another": "valid"}\n')

        # Should not crash and should process valid records
        recommendations = self.engine.recommend("test prompt", "txt2img")
        # Should handle gracefully (may have no recommendations if records don't have ratings)
        self.assertIsNotNone(recommendations)


if __name__ == "__main__":
    unittest.main()
