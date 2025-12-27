"""Realistic WebUI API response payloads for testing."""

import base64
import json
from io import BytesIO
from PIL import Image


def generate_stub_image(width: int = 512, height: int = 512, color: str = "blue") -> str:
    """Generate a stub PNG image as base64 string."""
    img = Image.new("RGB", (width, height), color=color)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def txt2img_response(prompt: str, seed: int = 42, width: int = 512, height: int = 512) -> dict:
    """Generate realistic txt2img API response."""
    info = {
        "prompt": prompt,
        "negative_prompt": "",
        "seed": seed,
        "subseed": seed,
        "subseed_strength": 0,
        "width": width,
        "height": height,
        "sampler_name": "Euler a",
        "cfg_scale": 7.0,
        "steps": 20,
        "batch_size": 1,
        "restore_faces": False,
        "sd_model_name": "mock_model_v1.safetensors",
        "sd_model_hash": "abc123",
        "sd_vae_name": "auto",
        "job_timestamp": "20251225143000",
        "clip_skip": 2,
        "is_using_inpainting_conditioning": False,
    }
    
    return {
        "images": [generate_stub_image(width, height, "blue")],
        "parameters": info,
        "info": json.dumps(info),
    }


def img2img_response(
    prompt: str,
    init_image: str,
    seed: int = 42,
    width: int = 512,
    height: int = 512,
    denoising_strength: float = 0.75
) -> dict:
    """Generate realistic img2img API response."""
    info = {
        "prompt": prompt,
        "negative_prompt": "",
        "seed": seed,
        "subseed": seed,
        "subseed_strength": 0,
        "width": width,
        "height": height,
        "sampler_name": "Euler a",
        "cfg_scale": 7.0,
        "steps": 20,
        "batch_size": 1,
        "restore_faces": False,
        "denoising_strength": denoising_strength,
        "init_images": [init_image],
        "resize_mode": 0,
        "image_cfg_scale": 1.5,
        "mask": None,
        "mask_blur": 4,
        "inpainting_fill": 1,
        "inpaint_full_res": True,
        "sd_model_name": "mock_model_v1.safetensors",
        "sd_model_hash": "abc123",
    }
    
    return {
        "images": [generate_stub_image(width, height, "green")],
        "parameters": info,
        "info": json.dumps(info),
    }


def upscale_response(image: str, upscaler: str = "R-ESRGAN 4x+", scale: int = 2) -> dict:
    """Generate realistic upscale API response."""
    # Stub: just return 2x dimensions
    return {
        "image": generate_stub_image(1024, 1024, "purple"),
        "info": json.dumps({
            "upscaler": upscaler,
            "resize": scale,
        }),
    }


def controlnet_response(prompt: str, control_image: str, module: str, model: str) -> dict:
    """Generate realistic ControlNet/ADetailer response."""
    info = {
        "prompt": prompt,
        "seed": 42,
        "width": 512,
        "height": 512,
        "controlnet_module": module,
        "controlnet_model": model,
        "controlnet_weight": 1.0,
        "controlnet_guidance_start": 0.0,
        "controlnet_guidance_end": 1.0,
    }
    
    return {
        "images": [generate_stub_image(512, 512, "orange")],
        "parameters": info,
        "info": json.dumps(info),
    }
