"""Tests for WebUI mock infrastructure."""

import pytest
from tests.mocks.webui_mock_server import MockWebUIServer, get_mock_server
from tests.mocks.webui_mock_client import MockWebUIClient
from tests.mocks.mock_responses import generate_stub_image


def test_mock_server_txt2img():
    """Test mock server returns valid txt2img response."""
    server = MockWebUIServer()
    
    payload = {"prompt": "test prompt", "seed": 123, "width": 512, "height": 512}
    response = server.txt2img(payload)
    
    assert "images" in response
    assert len(response["images"]) == 1
    assert "info" in response
    assert server.call_count["txt2img"] == 1


def test_mock_server_img2img():
    """Test mock server returns valid img2img response."""
    server = MockWebUIServer()
    
    init_image = generate_stub_image()
    payload = {
        "prompt": "test prompt",
        "init_images": [init_image],
        "denoising_strength": 0.75,
    }
    response = server.img2img(payload)
    
    assert "images" in response
    assert "info" in response
    assert server.call_count["img2img"] == 1


def test_mock_server_upscale():
    """Test mock server returns valid upscale response."""
    server = MockWebUIServer()
    
    image = generate_stub_image()
    payload = {
        "image": image,
        "upscaler_1": "R-ESRGAN 4x+",
        "upscaling_resize": 2,
    }
    response = server.upscale(payload)
    
    assert "image" in response
    assert "info" in response
    assert server.call_count["upscale"] == 1


def test_mock_server_controlnet():
    """Test mock server returns valid controlnet response."""
    server = MockWebUIServer()
    
    control_image = generate_stub_image()
    payload = {
        "prompt": "test prompt",
        "controlnet_input_image": [control_image],
        "controlnet_module": "depth",
        "controlnet_model": "control_v11f1p_sd15_depth",
    }
    response = server.controlnet(payload)
    
    assert "images" in response
    assert "info" in response
    assert server.call_count["controlnet"] == 1


def test_mock_client_integration():
    """Test MockWebUIClient uses mock server."""
    client = MockWebUIClient()
    client.server.reset()
    
    response = client.txt2img(prompt="test", seed=42)
    
    assert "images" in response
    assert client.server.call_count["txt2img"] == 1


def test_mock_server_singleton():
    """Test get_mock_server returns singleton."""
    server1 = get_mock_server()
    server2 = get_mock_server()
    
    assert server1 is server2


def test_mock_server_reset():
    """Test server reset clears history."""
    server = MockWebUIServer()
    
    server.txt2img({"prompt": "test"})
    assert server.call_count["txt2img"] == 1
    
    server.reset()
    assert server.call_count["txt2img"] == 0
    assert len(server.requests_made) == 0


def test_generate_stub_image():
    """Test stub image generation."""
    image_b64 = generate_stub_image(512, 512, "red")
    
    assert isinstance(image_b64, str)
    assert len(image_b64) > 0


def test_mock_client_all_methods():
    """Test all MockWebUIClient methods."""
    client = MockWebUIClient()
    client.server.reset()
    
    # txt2img
    resp = client.txt2img(prompt="test")
    assert "images" in resp
    
    # img2img
    init = generate_stub_image()
    resp = client.img2img(prompt="test", init_images=[init])
    assert "images" in resp
    
    # upscale
    resp = client.upscale(image=init)
    assert "image" in resp
    
    # controlnet
    resp = client.controlnet(prompt="test", controlnet_input_image=[init])
    assert "images" in resp
    
    # progress
    resp = client.get_progress()
    assert resp["progress"] == 1.0
    
    # interrupt
    resp = client.interrupt()
    assert resp["success"] is True
    
    # config
    resp = client.get_config()
    assert "sd_model_checkpoint" in resp
