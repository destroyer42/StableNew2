import pytest

from src.learning.model_profiles import ModelProfile, STYLE_DEFAULTS, get_profile_defaults


@pytest.mark.parametrize(
    "tags, base_type, expected_style",
    [
        (["sdxl_realism"], "sdxl", "sdxl_realism"),
        (["sdxl_portrait"], "sdxl", "sdxl_portrait"),
        (["sd15_realism"], "sd15", "sd15_realism"),
        (["anime"], "sd15", "anime"),
    ],
)
def test_model_profiles_expose_defaults(tags, base_type, expected_style):
    profile = ModelProfile(
        kind="model_profile",
        version=1,
        model_name="test",
        base_type=base_type,
        tags=list(tags),
        recommended_presets=[],
    )
    defaults = get_profile_defaults(profile)
    assert defaults == STYLE_DEFAULTS.get(expected_style, {})
    assert PROFILE_FIELD_CHECK(profile)


def test_profile_defaults_empty_when_unknown():
    profile = ModelProfile(
        kind="model_profile",
        version=1,
        model_name="unknown",
        base_type="unknown",
        tags=[],
        recommended_presets=[],
    )
    defaults = get_profile_defaults(profile)
    assert defaults == {}
    assert PROFILE_FIELD_CHECK(profile)


def PROFILE_FIELD_CHECK(profile: ModelProfile) -> bool:
    assert hasattr(profile, "default_refiner_id")
    assert hasattr(profile, "default_hires_upscaler_id")
    assert hasattr(profile, "default_hires_denoise")
    assert hasattr(profile, "style_profile_id")
    return True
