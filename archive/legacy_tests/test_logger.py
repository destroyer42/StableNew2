"""Tests for logger utilities"""

from src.utils import StructuredLogger


class TestStructuredLogger:
    """Test cases for StructuredLogger"""

    def test_init(self, tmp_path):
        """Test initialization"""
        logger = StructuredLogger(output_dir=str(tmp_path / "output"))
        assert logger.output_dir.exists()

    def test_create_run_directory(self, tmp_path):
        """Test creating run directory"""
        logger = StructuredLogger(output_dir=str(tmp_path / "output"))

        # Create with auto-generated name
        run_dir = logger.create_run_directory()
        assert run_dir.exists()
        # Note: Subdirectories are created on-demand, not pre-created
        # The run directory itself should exist
        assert run_dir.is_dir()

    def test_create_run_directory_custom_name(self, tmp_path):
        """Test creating run directory with custom name"""
        logger = StructuredLogger(output_dir=str(tmp_path / "output"))

        run_dir = logger.create_run_directory("custom_run")
        assert run_dir.name == "custom_run"
        assert run_dir.exists()

    def test_save_manifest(self, tmp_path):
        """Test saving JSON manifest"""
        logger = StructuredLogger(output_dir=str(tmp_path / "output"))
        run_dir = logger.create_run_directory("test_run")

        metadata = {"name": "test_image", "prompt": "test prompt", "steps": 20}

        assert logger.save_manifest(run_dir, "test_image", metadata) is True

        manifest_path = run_dir / "manifests" / "test_image.json"
        assert manifest_path.exists()

        # Verify content
        import json

        with open(manifest_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["name"] == "test_image"
        assert loaded["prompt"] == "test prompt"

    def test_create_csv_summary(self, tmp_path):
        """Test creating CSV summary"""
        logger = StructuredLogger(output_dir=str(tmp_path / "output"))
        run_dir = logger.create_run_directory("test_run")

        images_data = [
            {"name": "img1", "prompt": "test1", "steps": 20},
            {"name": "img2", "prompt": "test2", "steps": 30},
        ]

        assert logger.create_csv_summary(run_dir, images_data) is True

        csv_path = run_dir / "summary.csv"
        assert csv_path.exists()

        # Verify content
        with open(csv_path, encoding="utf-8") as f:
            content = f.read()

        assert "name" in content
        assert "prompt" in content
        assert "img1" in content
        assert "test2" in content

    def test_csv_summary_empty_data(self, tmp_path):
        """Test creating CSV summary with empty data"""
        logger = StructuredLogger(output_dir=str(tmp_path / "output"))
        run_dir = logger.create_run_directory("test_run")

        assert logger.create_csv_summary(run_dir, []) is False

    def test_utf8_in_manifest(self, tmp_path):
        """Test UTF-8 support in manifests"""
        logger = StructuredLogger(output_dir=str(tmp_path / "output"))
        run_dir = logger.create_run_directory("test_run")

        metadata = {
            "prompt": "美しい風景, schöne Landschaft, 漂亮的风景",
            "negative_prompt": "悪い品質",
        }

        assert logger.save_manifest(run_dir, "utf8_test", metadata) is True

        # Verify UTF-8 is preserved
        import json

        manifest_path = run_dir / "manifests" / "utf8_test.json"
        with open(manifest_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["prompt"] == metadata["prompt"]
        assert loaded["negative_prompt"] == metadata["negative_prompt"]
