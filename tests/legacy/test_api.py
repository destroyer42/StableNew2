"""Tests for API client"""

from unittest.mock import Mock, patch

from src.api import SDWebUIClient


class TestSDWebUIClient:
    """Test cases for SDWebUIClient"""

    def test_init(self):
        """Test client initialization"""
        client = SDWebUIClient()
        assert client.base_url == "http://127.0.0.1:7860"
        assert client.timeout == 300

        client = SDWebUIClient(base_url="http://localhost:8080", timeout=60)
        assert client.base_url == "http://localhost:8080"
        assert client.timeout == 60

    @patch("src.api.client.requests.request")
    def test_check_api_ready_success(self, mock_request):
        """Test successful API readiness check"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_request.return_value = mock_response

        client = SDWebUIClient()
        assert client.check_api_ready(max_retries=1) is True

    @patch("src.api.client.requests.request")
    def test_check_api_ready_failure(self, mock_request):
        """Test failed API readiness check"""
        mock_request.side_effect = Exception("Connection error")

        client = SDWebUIClient()
        assert client.check_api_ready(max_retries=1, retry_delay=0) is False

    @patch("src.api.client.requests.request")
    def test_txt2img_success(self, mock_request):
        """Test successful txt2img request"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"images": ["base64data"]}
        mock_request.return_value = mock_response

        client = SDWebUIClient()
        result = client.txt2img({"prompt": "test"})

        assert result is not None
        assert "images" in result
        assert len(result["images"]) == 1

    @patch("src.api.client.requests.request")
    def test_txt2img_failure(self, mock_request):
        """Test failed txt2img request"""
        mock_request.side_effect = Exception("API error")

        client = SDWebUIClient()
        result = client.txt2img({"prompt": "test"})

        assert result is None

    @patch("src.api.client.requests.request")
    def test_img2img_success(self, mock_request):
        """Test successful img2img request"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"images": ["base64data"]}
        mock_request.return_value = mock_response

        client = SDWebUIClient()
        result = client.img2img({"prompt": "test", "init_images": ["img"]})

        assert result is not None
        assert "images" in result

    @patch("src.api.client.requests.request")
    def test_upscale_success(self, mock_request):
        """Test successful upscale request"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"image": "base64data"}
        mock_request.return_value = mock_response

        client = SDWebUIClient()
        result = client.upscale({"image": "base64image"})

        assert result is not None
        assert "image" in result

    @patch("src.api.client.requests.request")
    def test_get_models(self, mock_request):
        """Test get models request"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [{"name": "model1"}]
        mock_request.return_value = mock_response

        client = SDWebUIClient()
        result = client.get_models()

        assert len(result) == 1
        assert result[0]["name"] == "model1"

    @patch("src.api.client.requests.request")
    def test_get_samplers(self, mock_request):
        """Test get samplers request"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [{"name": "Euler a"}]
        mock_request.return_value = mock_response

        client = SDWebUIClient()
        result = client.get_samplers()

        assert len(result) == 1
        assert result[0]["name"] == "Euler a"
