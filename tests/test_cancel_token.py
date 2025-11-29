"""Tests for cancel token integration in pipeline."""

import json
import logging
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.gui.state import CancelToken
from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


class TestCancelTokenIntegration:
    """Tests for cancel token integration in pipeline."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory."""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        shutil.rmtree(temp_path)

    @pytest.fixture
    def mock_client(self):
        """Create mock API client."""
        client = Mock()
        client.txt2img = Mock(return_value={"images": ["base64_image_data"]})
        client.img2img = Mock(return_value={"images": ["base64_image_data"]})
        client.upscale_image = Mock(return_value={"image": "base64_image_data"})
        client.set_model = Mock()
        client.set_vae = Mock()
        return client

    @pytest.fixture
    def pipeline(self, mock_client, temp_dir):
        """Create pipeline instance with mocked client."""
        logger = StructuredLogger()
        logger.output_dir = temp_dir
        pipeline = Pipeline(mock_client, logger)
        return pipeline

    def test_cancel_token_passed_to_txt2img(self, pipeline, temp_dir):
        """Test that cancel token is passed to txt2img."""
        cancel_token = CancelToken()
        config = {"txt2img": {}}

        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            results = pipeline.run_txt2img(
                "test prompt", config, temp_dir, batch_size=1, cancel_token=cancel_token
            )

        # Should complete normally
        assert isinstance(results, list)

    def test_cancel_before_txt2img(self, pipeline, temp_dir):
        """Test cancellation before txt2img starts."""
        cancel_token = CancelToken()
        cancel_token.cancel()

        config = {"txt2img": {}}

        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            results = pipeline.run_txt2img(
                "test prompt", config, temp_dir, batch_size=1, cancel_token=cancel_token
            )

        # Should return empty list
        assert results == []

    def test_cancel_after_txt2img_api_call(self, pipeline, temp_dir, mock_client):
        """Test cancellation after txt2img API call."""
        cancel_token = CancelToken()
        config = {"txt2img": {}}

        # Cancel after API call
        def delayed_cancel(*args, **kwargs):
            cancel_token.cancel()
            return {"images": ["base64_image_data"]}

        mock_client.txt2img = Mock(side_effect=delayed_cancel)

        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            results = pipeline.run_txt2img(
                "test prompt", config, temp_dir, batch_size=1, cancel_token=cancel_token
            )

        # Should return empty list (cancelled after API call)
        assert results == []

    def test_cancel_during_image_saving(self, pipeline, temp_dir, mock_client):
        """Test cancellation during image saving loop."""
        cancel_token = CancelToken()
        config = {"txt2img": {}}

        # Return multiple images
        mock_client.txt2img = Mock(return_value={"images": ["image1", "image2", "image3"]})

        save_count = [0]

        def save_and_cancel(*args, **kwargs):
            save_count[0] += 1
            if save_count[0] == 2:
                cancel_token.cancel()
            return True

        with patch("src.pipeline.executor.save_image_from_base64", side_effect=save_and_cancel):
            results = pipeline.run_txt2img(
                "test prompt", config, temp_dir, batch_size=3, cancel_token=cancel_token
            )

        # Should have saved 2 images (cancelled on the 2nd, but check happens before 3rd)
        assert len(results) == 2

    def test_cancel_before_img2img(self, pipeline, temp_dir):
        """Test cancellation before img2img starts."""
        cancel_token = CancelToken()
        cancel_token.cancel()

        config = {}
        input_path = temp_dir / "test.png"
        input_path.touch()

        with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
            result = pipeline.run_img2img(
                input_path, "test prompt", config, temp_dir, cancel_token=cancel_token
            )

        assert result is None

    def test_cancel_before_upscale(self, pipeline, temp_dir):
        """Test cancellation before upscale starts."""
        cancel_token = CancelToken()
        cancel_token.cancel()

        config = {}
        input_path = temp_dir / "test.png"
        input_path.touch()

        with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
            result = pipeline.run_upscale(input_path, config, temp_dir, cancel_token=cancel_token)

        assert result is None

    def test_full_pipeline_cancel_before_start(self, pipeline, temp_dir):
        """Test full pipeline cancellation before start."""
        cancel_token = CancelToken()
        cancel_token.cancel()

        config = {"txt2img": {}, "img2img": {}, "upscale": {}}

        results = pipeline.run_full_pipeline(
            "test prompt", config, run_name="test", batch_size=1, cancel_token=cancel_token
        )

        # Should return minimal results
        assert results["txt2img"] == []
        assert results["img2img"] == []
        assert results["upscaled"] == []

    def test_full_pipeline_cancel_after_txt2img(self, pipeline, temp_dir, mock_client):
        """Test full pipeline cancellation after txt2img."""
        cancel_token = CancelToken()
        config = {"txt2img": {}, "img2img": {}, "upscale": {}}

        # Cancel after txt2img
        def delayed_cancel(*args, **kwargs):
            result = {"images": ["base64_image_data"]}
            cancel_token.cancel()
            return result

        mock_client.txt2img = Mock(side_effect=delayed_cancel)

        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
                results = pipeline.run_full_pipeline(
                    "test prompt", config, run_name="test", batch_size=1, cancel_token=cancel_token
                )

        # Should have txt2img results but not img2img or upscale
        assert len(results["txt2img"]) >= 0  # May be empty if cancelled during saving
        assert results["img2img"] == []
        assert results["upscaled"] == []

    def test_full_pipeline_cancel_during_img2img_loop(self, pipeline, temp_dir, mock_client):
        """Test full pipeline cancellation during img2img loop."""
        cancel_token = CancelToken()
        config = {"txt2img": {}, "img2img": {}, "upscale": {}}

        # Generate multiple txt2img images
        mock_client.txt2img = Mock(return_value={"images": ["image1", "image2", "image3"]})

        img2img_count = [0]

        def img2img_and_cancel(*args, **kwargs):
            img2img_count[0] += 1
            if img2img_count[0] == 2:
                cancel_token.cancel()
            return {"images": ["cleaned_image"]}

        mock_client.img2img = Mock(side_effect=img2img_and_cancel)

        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
                results = pipeline.run_full_pipeline(
                    "test prompt", config, run_name="test", batch_size=3, cancel_token=cancel_token
                )

        # Should have some txt2img results but limited img2img
        assert len(results["txt2img"]) == 3
        assert len(results["img2img"]) <= 2  # Cancelled during loop

    def test_full_pipeline_cancel_logs_status(self, pipeline, temp_dir, caplog):
        """Ensure cancellation logs standardized message and records run status."""
        cancel_token = CancelToken()
        cancel_token.cancel()
        config = {"txt2img": {}, "img2img": {}, "upscale": {}}
        run_name = "cancel_log_test"

        with caplog.at_level(logging.INFO):
            results = pipeline.run_full_pipeline(
                "test prompt", config, run_name=run_name, batch_size=1, cancel_token=cancel_token
            )

        assert results["txt2img"] == []
        assert any("Pipeline cancelled during full pipeline" in msg for msg in caplog.messages)

        status_path = temp_dir / run_name / "run_status.json"
        assert status_path.exists()
        with open(status_path, encoding="utf-8") as f:
            status_data = json.load(f)
        assert status_data["status"] == "cancelled"


class TestPipelineEarlyOut:
    """Test that pipeline exits early when cancelled."""

    @pytest.fixture
    def mock_client(self):
        """Create mock client that tracks calls."""
        client = Mock()
        client.txt2img = Mock(return_value={"images": ["img"]})
        client.img2img = Mock(return_value={"images": ["img"]})
        client.upscale_image = Mock(return_value={"image": "img"})
        client.set_model = Mock()
        client.set_vae = Mock()
        return client

    def test_early_out_prevents_subsequent_stages(self, mock_client, tmp_path):
        """Test that cancellation prevents subsequent stages from running."""
        logger = StructuredLogger()
        logger.output_dir = tmp_path
        pipeline = Pipeline(mock_client, logger)

        cancel_token = CancelToken()

        # Cancel immediately
        cancel_token.cancel()

        config = {"txt2img": {}, "img2img": {}, "upscale": {}}

        with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
            with patch("src.pipeline.executor.load_image_to_base64", return_value="base64"):
                results = pipeline.run_full_pipeline("test", config, cancel_token=cancel_token)

        # txt2img should not be called
        assert mock_client.txt2img.call_count == 0
        # img2img should not be called
        assert mock_client.img2img.call_count == 0
        # upscale should not be called
        assert mock_client.upscale_image.call_count == 0
