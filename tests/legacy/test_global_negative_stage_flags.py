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


def test_global_negative_stage_flags(tmp_path):
    client = StubClient()
    logger = StructuredLogger(output_dir=str(tmp_path / "logs"))
    pipeline = Pipeline(client, logger)

    # Set a known global negative prompt
    pipeline.config_manager.save_global_negative_prompt("GLOBAL_BAD")

    config = {
        "txt2img": {
            "steps": 5,
            "negative_prompt": "local one",
        },
        "img2img": {
            "steps": 5,
            "denoising_strength": 0.25,
            "negative_prompt": "cleanup neg",
        },
        "upscale": {
            "upscaler": "R-ESRGAN 4x+",
            "upscaling_resize": 2.0,
            "upscale_mode": "single",
        },
        "pipeline": {
            "img2img_enabled": True,
            "upscale_enabled": True,
            # Enable global negative for txt2img, disable for img2img
            "apply_global_negative_txt2img": True,
            "apply_global_negative_img2img": False,
            "apply_global_negative_upscale": True,
        },
    }

    run_dir = pipeline.logger.create_run_directory("test_stage_flags")
    results = pipeline.run_pack_pipeline(
        pack_name="PackA",
        prompt="a hero",
        config=config,
        run_dir=run_dir,
        prompt_index=0,
        batch_size=1,
    )

    assert results["txt2img"], "txt2img metadata missing"
    t_meta = results["txt2img"][0]
    assert t_meta["global_negative_applied"] is True
    assert (
        "GLOBAL_BAD" in t_meta["final_negative_prompt"]
    ), "Global negative should appear in txt2img final negative prompt"
    assert t_meta["original_negative_prompt"].startswith("local one")

    # img2img may or may not run depending on compare/refiner flags; if present, validate flags
    if results["img2img"]:
        i_meta = results["img2img"][0]
        assert i_meta["global_negative_applied"] is False
        assert (
            "GLOBAL_BAD" not in i_meta["final_negative_prompt"]
        ), "Global negative should be skipped for img2img stage"

    # Ensure prompt metadata structure
    assert "original_prompt" in t_meta and "final_prompt" in t_meta
    assert t_meta["final_prompt"], "Final prompt should not be empty"
