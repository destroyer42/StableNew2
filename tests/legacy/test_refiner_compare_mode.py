import base64
from io import BytesIO

from PIL import Image

from src.pipeline.executor import Pipeline
from src.utils.logger import StructuredLogger


class StubClient:
    def __init__(self):
        self.calls = []

    @staticmethod
    def _png_b64(color=(255, 0, 0), size=(8, 8)) -> str:
        img = Image.new("RGB", size, color)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def txt2img(self, payload):
        # Return deterministic single image
        self.calls.append(("txt2img", payload))
        return {"images": [self._png_b64((0, 255, 0))]}

    def img2img(self, payload):
        self.calls.append(("img2img", payload))
        return {"images": [self._png_b64((0, 0, 255))]}

    def upscale_image(
        self,
        image_b64,
        upscaler,
        upscaling_resize,
        gfpgan_visibility,
        codeformer_visibility,
        codeformer_weight,
    ):
        self.calls.append(("upscale", {"upscaler": upscaler}))
        return {"image": self._png_b64((255, 255, 0))}

    def set_model(self, *_a, **_k):
        return True

    def set_vae(self, *_a, **_k):
        return True

    def set_hypernetwork(self, *_a, **_k):
        return True


def test_refiner_compare_mode_produces_two_upscaled_images(tmp_path):
    client = StubClient()
    logger = StructuredLogger(output_dir=str(tmp_path / "logs"))
    pipeline = Pipeline(client, logger)

    config = {
        "txt2img": {
            "steps": 10,
            "enable_hr": True,
            "hr_scale": 2.0,
            "hr_upscaler": "Latent",
            "hr_second_pass_steps": 5,
            "refiner_checkpoint": "sdxl_refiner.safetensors",
            "refiner_switch_at": 0.8,
        },
        "img2img": {
            "steps": 12,
            "denoising_strength": 0.25,
        },
        "upscale": {
            "upscaler": "R-ESRGAN 4x+",
            "upscaling_resize": 2.0,
            "upscale_mode": "single",
        },
        "pipeline": {
            "img2img_enabled": True,
            "upscale_enabled": True,
            "adetailer_enabled": False,
            "refiner_compare_mode": True,
        },
    }

    run_dir = pipeline.logger.create_run_directory("test_compare")
    results = pipeline.run_pack_pipeline(
        pack_name="PackA",
        prompt="a hero",
        config=config,
        run_dir=run_dir,
        prompt_index=0,
        batch_size=1,
    )

    # We expect two upscaled images: base + refined
    upscaled_paths = [m["path"] for m in results.get("upscaled", [])]
    assert len(upscaled_paths) == 2, f"Expected 2 upscaled images, got {len(upscaled_paths)}"
    # naming may differ, just ensure two outputs and paths are distinct
    assert len(set(upscaled_paths)) == 2

    # Ensure img2img was invoked once for the refined branch
    img2img_calls = [c for c in client.calls if c[0] == "img2img"]
    assert img2img_calls, "img2img should run in compare mode"

    # Ensure txt2img ran first
    txt2img_calls = [c for c in client.calls if c[0] == "txt2img"]
    assert txt2img_calls, "txt2img should have been called"

    # Ensure both branches were upscaled
    upscale_calls = [c for c in client.calls if c[0] == "upscale"]
    assert len(upscale_calls) == 2, f"Expected 2 upscale calls, got {len(upscale_calls)}"
