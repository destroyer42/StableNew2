"""Test API client functionality"""

from unittest.mock import MagicMock

import requests
import requests_mock

from src.api.client import SDWebUIClient

API_BASE_URL = "http://127.0.0.1:7860"


class TestSDWebUIClient:
    """Test suite for the SD WebUI API client"""

    def setup_method(self):
        """Setup for each test"""
        self.client = SDWebUIClient()
        self.client.set_options_write_enabled(True)

    def test_init(self):
        """Test client initialization"""
        assert self.client.base_url == API_BASE_URL

    def test_check_api_ready_success(self):
        """Test successful API readiness check"""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/sd-models", json=[{"title": "model1.safetensors"}])
            assert self.client.check_api_ready() is True

    def test_check_api_ready_failure(self):
        """Test failed API readiness check"""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/sd-models", exc=requests.exceptions.ConnectTimeout)
            assert self.client.check_api_ready() is False

    def test_txt2img_success(self):
        """Test successful txt2img call"""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/txt2img", json={"images": ["test_image_base64"]})
            response = self.client.txt2img({})
            assert response is not None
            assert "images" in response

    def test_txt2img_failure(self):
        """Test failed txt2img call"""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/txt2img", status_code=500)
            response = self.client.txt2img({})
            assert response is None

    def test_img2img_success(self):
        """Test successful img2img call"""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/img2img", json={"images": ["test_image_base64"]})
            response = self.client.img2img({})
            assert response is not None
            assert "images" in response

    def test_upscale_success(self):
        """Test successful upscale call"""
        with requests_mock.Mocker() as m:
            m.post(
                f"{API_BASE_URL}/sdapi/v1/extra-single-image",
                json={"image": "upscaled_image_base64"},
            )
            response = self.client.upscale_image("dummy_base64", "R-ESRGAN 4x+", 2.0)
            assert response is not None
            assert "image" in response

    def test_get_models_success(self):
        """Test successful get_models call"""
        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/sd-models",
                json=[{"title": "model1"}, {"title": "model2"}],
            )
            models = self.client.get_models()
            assert [m["title"] for m in models] == ["model1", "model2"]

    def test_get_current_model_success(self):
        """Test successful get_current_model call"""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", json={"sd_model_checkpoint": "current_model"})
            model = self.client.get_current_model()
            assert model == "current_model"

    def test_get_options_success(self):
        """Ensure get_options returns parsed dict."""
        with requests_mock.Mocker() as m:
            m.get(f"{API_BASE_URL}/sdapi/v1/options", json={"jpeg_quality": 80})
            opts = self.client.get_options()
            assert opts["jpeg_quality"] == 80

    def test_update_options_posts_payload(self):
        """Ensure update_options POSTs with the provided payload."""
        with requests_mock.Mocker() as m:
            m.post(f"{API_BASE_URL}/sdapi/v1/options", json={"ok": True})
            payload = {"jpeg_quality": 90}
            updated = self.client.update_options(payload)
            assert updated["ok"] is True
            assert m.last_request.json() == payload

    def test_apply_upscale_performance_defaults_posts_options(self):
        """Ensure upscale defaults call POST /options exactly once."""
        client = SDWebUIClient()
        client.set_options_write_enabled(True)
        client._perform_request = MagicMock(return_value=object())

        client.apply_upscale_performance_defaults()

        client._perform_request.assert_called_once()
        args, kwargs = client._perform_request.call_args
        assert args[0] == "post"
        assert args[1] == "/sdapi/v1/options"
        payload = kwargs["json"]
        assert payload["img_max_size_mp"] == 16
        assert "ESRGAN_tile" in payload
        assert "DAT_tile" in payload

    def test_ensure_safe_upscale_defaults_clamps_values(self):
        """ensure_safe_upscale_defaults should clamp oversized values and POST payload."""
        client = SDWebUIClient()
        client.set_options_write_enabled(True)

        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/options",
                json={
                    "img_max_size_mp": 32,
                    "ESRGAN_tile": 2048,
                    "ESRGAN_tile_overlap": 160,
                    "DAT_tile": 1024,
                    "DAT_tile_overlap": 64,
                },
            )
            m.post(f"{API_BASE_URL}/sdapi/v1/options", json={"ok": True})

            client.ensure_safe_upscale_defaults(max_img_mp=8.0, max_tile=768, max_overlap=128)

            payload = m.last_request.json()
            assert payload["img_max_size_mp"] == 8.0
            assert payload["ESRGAN_tile"] == 768
            assert payload["ESRGAN_tile_overlap"] == 128
            assert payload["DAT_tile"] == 768
            assert "DAT_tile_overlap" not in payload, "values within limits should stay untouched"

    def test_ensure_safe_upscale_defaults_no_changes_skips_post(self):
        """When values already safe, ensure_safe_upscale_defaults should not POST."""
        client = SDWebUIClient()
        client.set_options_write_enabled(True)

        with requests_mock.Mocker() as m:
            m.get(
                f"{API_BASE_URL}/sdapi/v1/options",
                json={
                    "img_max_size_mp": 4.0,
                    "ESRGAN_tile": 512,
                    "ESRGAN_tile_overlap": 64,
                    "DAT_tile": 640,
                    "DAT_tile_overlap": 32,
                },
            )
            post_mock = m.post(f"{API_BASE_URL}/sdapi/v1/options", json={"ok": True})

            client.ensure_safe_upscale_defaults(max_img_mp=8.0, max_tile=768, max_overlap=128)

            assert post_mock.called is False


def test_generate_images_surfaces_crash_diagnostics_context():
    client = SDWebUIClient()
    client.set_options_write_enabled(True)
    session_id = client._session_id

    with requests_mock.Mocker() as m:
        m.post(
            f"{API_BASE_URL}/sdapi/v1/txt2img",
            [
                {"status_code": 500, "text": "server fatal error"},
                {"exc": requests.exceptions.ConnectionError("Connection refused")},
            ],
        )

        outcome = client.generate_images(stage="txt2img", payload={})

    assert outcome.error is not None
    diagnostics = outcome.error.details.get("diagnostics") if outcome.error.details else None
    assert diagnostics is not None
    assert diagnostics.get("webui_unavailable") is True
    assert diagnostics.get("crash_suspected") is True
    request_summary = diagnostics.get("request_summary")
    assert request_summary is not None
    assert request_summary.get("endpoint") == "/sdapi/v1/txt2img"
    assert request_summary.get("session_id") == session_id
    assert diagnostics.get("previous_http_error") is not None
