from src.learning.model_defaults_resolver import (
    GuiDefaultsResolver,
    ModelDefaultsContext,
    ModelDefaultsResolver,
)
from src.utils.config import ConfigManager


def test_model_defaults_resolver_applies_style_defaults() -> None:
    resolver = ModelDefaultsResolver(config_manager=ConfigManager())
    ctx = ModelDefaultsContext(model_name="sdxl_portrait_model")
    resolved = resolver.resolve_config(ctx)
    txt2img = resolved.get("txt2img", {})
    hires = resolved.get("hires_fix", {})
    assert txt2img.get("refiner_model_name") == "sdxl_portrait_refiner"
    assert hires.get("upscaler_name") == "ESRGAN_4x"
    assert hires.get("denoise") == 0.2


def test_model_defaults_resolver_runtime_overrides_win() -> None:
    resolver = ModelDefaultsResolver(config_manager=ConfigManager())
    ctx = ModelDefaultsContext(model_name="sdxl_portrait_model")
    overrides = {"txt2img": {"refiner_model_name": "user-refiner"}}
    resolved = resolver.resolve_config(ctx, runtime_overrides=overrides)
    assert resolved["txt2img"]["refiner_model_name"] == "user-refiner"


def test_gui_defaults_resolver_returns_fields() -> None:
    resolver = GuiDefaultsResolver(config_manager=ConfigManager())
    defaults = resolver.resolve_for_gui(model_name="sdxl_portrait_model")
    assert defaults["txt2img"]["refiner_model_name"] == "sdxl_portrait_refiner"
    assert defaults["hires_fix"]["upscaler_name"] == "ESRGAN_4x"
