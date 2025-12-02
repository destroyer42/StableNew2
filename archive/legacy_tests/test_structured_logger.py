"""Test structured logging functionality"""

import csv
import json

from src.utils.logger import StructuredLogger


class TestStructuredLogger:
    def test_init(self, tmp_path):
        """Test StructuredLogger initialization"""
        logger = StructuredLogger(str(tmp_path))
        assert logger.output_dir == tmp_path
        assert tmp_path.exists()

    def test_create_run_directory(self, tmp_path):
        """Test run directory creation"""
        logger = StructuredLogger(str(tmp_path))

        # Test with custom name
        run_dir = logger.create_run_directory("test_run")
        assert run_dir.name == "test_run"
        assert run_dir.exists()

        # Note: Subdirectories are created on-demand by the pipeline,
        # not pre-created in create_run_directory()
        assert run_dir.is_dir()

        # Test with auto-generated name
        auto_run_dir = logger.create_run_directory()
        assert auto_run_dir.name.startswith("run_")
        assert auto_run_dir.exists()

    def test_save_manifest(self, tmp_path):
        """Test saving image manifests"""
        logger = StructuredLogger(str(tmp_path))
        run_dir = logger.create_run_directory("test_run")

        metadata = {
            "name": "test_image",
            "stage": "txt2img",
            "timestamp": "20240101_120000",
            "prompt": "test prompt",
            "config": {"steps": 20, "cfg_scale": 7.0},
            "path": "/path/to/image.png",
        }

        success = logger.save_manifest(run_dir, "test_image", metadata)
        assert success is True

        # Check manifest file was created
        manifest_file = run_dir / "manifests" / "test_image.json"
        assert manifest_file.exists()

        # Verify content
        with open(manifest_file, encoding="utf-8") as f:
            saved_data = json.load(f)

        assert saved_data["name"] == "test_image"
        assert saved_data["prompt"] == "test prompt"
        assert saved_data["config"]["steps"] == 20

    def test_create_csv_summary(self, tmp_path):
        """Test CSV summary creation"""
        logger = StructuredLogger(str(tmp_path))
        run_dir = logger.create_run_directory("test_run")

        images_data = [
            {
                "name": "image1",
                "stage": "txt2img",
                "timestamp": "20240101_120000",
                "prompt": "landscape photo",
                "config": {
                    "steps": 20,
                    "sampler_name": "Euler a",
                    "cfg_scale": 7.0,
                    "width": 512,
                    "height": 512,
                    "negative_prompt": "blurry",
                },
                "path": "/path/to/image1.png",
            },
            {
                "name": "image2",
                "stage": "img2img",
                "timestamp": "20240101_120001",
                "prompt": "portrait photo",
                "config": {
                    "steps": 15,
                    "sampler_name": "DPM++ 2M",
                    "cfg_scale": 8.0,
                    "denoising_strength": 0.3,
                },
                "path": "/path/to/image2.png",
            },
        ]

        success = logger.create_csv_summary(run_dir, images_data)
        assert success is True

        # Check CSV file was created
        csv_file = run_dir / "summary.csv"
        assert csv_file.exists()

        # Verify CSV content
        with open(csv_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["image_name"] == "image1"
        assert rows[0]["prompt"] == "landscape photo"
        assert rows[0]["steps"] == "20"
        assert rows[1]["image_name"] == "image2"
        assert rows[1]["stage"] == "img2img"

    def test_create_rollup_manifest(self, tmp_path):
        """Test rollup manifest creation"""
        logger = StructuredLogger(str(tmp_path))
        run_dir = logger.create_run_directory("test_run")

        # Create individual manifests
        manifest_data = [
            {"name": "image1", "stage": "txt2img", "prompt": "test prompt 1"},
            {"name": "image2", "stage": "img2img", "prompt": "test prompt 2"},
        ]

        for data in manifest_data:
            logger.save_manifest(run_dir, data["name"], data)

        # Create rollup
        success = logger.create_rollup_manifest(run_dir)
        assert success is True

        # Check rollup file
        rollup_file = run_dir / "rollup_manifest.json"
        assert rollup_file.exists()

        # Verify rollup content
        with open(rollup_file, encoding="utf-8") as f:
            rollup_data = json.load(f)

        assert "run_info" in rollup_data
        assert "images" in rollup_data
        assert rollup_data["run_info"]["total_images"] == 2
        assert len(rollup_data["images"]) == 2

        # Check CSV was also created
        csv_file = run_dir / "summary.csv"
        assert csv_file.exists()

    def test_empty_manifest_handling(self, tmp_path):
        """Test handling of empty manifest directories"""
        logger = StructuredLogger(str(tmp_path))
        run_dir = logger.create_run_directory("empty_test")

        # Try to create rollup with no manifests
        success = logger.create_rollup_manifest(run_dir)
        assert success is True  # Should succeed but create empty rollup

    def test_utf8_handling(self, tmp_path):
        """Test UTF-8 character handling in manifests"""
        logger = StructuredLogger(str(tmp_path))
        run_dir = logger.create_run_directory("utf8_test")

        # Test data with Unicode characters
        metadata = {
            "name": "unicode_test",
            "stage": "txt2img",
            "prompt": "美しい風景, élégant portrait, صورة جميلة",
            "config": {"description": "тест на юникод"},
        }

        success = logger.save_manifest(run_dir, "unicode_test", metadata)
        assert success is True

        # Verify UTF-8 content is preserved
        manifest_file = run_dir / "manifests" / "unicode_test.json"
        with open(manifest_file, encoding="utf-8") as f:
            loaded_data = json.load(f)

        assert loaded_data["prompt"] == "美しい風景, élégant portrait, صورة جميلة"
        assert loaded_data["config"]["description"] == "тест на юникод"
