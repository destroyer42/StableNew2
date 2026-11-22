"""PR-IMG-COMFY-381: the ``image_backend_default`` setting and its place in backend-selection precedence.

Precedence is unchanged: explicit job identity -> model-required backend (Qwen, Ideogram) -> configured default.
The setting is a global default, not per-job runtime switching, and it fails closed.
"""

from __future__ import annotations

import pytest

from src.api import webui_runtime_identity as identity
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_21_PROFILE_V1
from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1
from src.image_backends.image_backend_types import (
    configured_image_backend_id,
    configured_webui_image_backend_id,
    normalize_image_backend_default,
    normalize_image_backend_options,
)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    values: dict = {}
    monkeypatch.setattr(identity, "load_backend_settings", lambda config_manager=None: values)
    return values


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "webui"), ("", "webui"), ("WebUI", "webui"), (" comfyui ", "comfyui")],
)
def test_normalization_accepts_blank_and_known_values(raw, expected) -> None:
    assert normalize_image_backend_default(raw) == expected


def test_an_unknown_value_fails_closed() -> None:
    with pytest.raises(identity.WebUIRuntimeConfigurationError, match="image_backend_default"):
        normalize_image_backend_default("forge")


def test_the_default_follows_the_webui_identity_exactly_as_before(settings: dict) -> None:
    assert configured_image_backend_id() == "forge_webui"
    settings["webui_runtime_identity"] = "a1111_webui"
    assert configured_image_backend_id() == "a1111_webui"
    settings["image_backend_default"] = "webui"
    assert configured_image_backend_id() == "a1111_webui"


def test_comfyui_selects_the_comfy_backend_but_not_the_webui_slot(settings: dict) -> None:
    settings["image_backend_default"] = "comfyui"
    settings["webui_runtime_identity"] = "a1111_webui"
    assert configured_image_backend_id() == "comfyui"
    assert configured_webui_image_backend_id() == "a1111_webui"


def test_an_unknown_persisted_value_raises_instead_of_selecting_a_backend(settings: dict) -> None:
    settings["image_backend_default"] = "somewhere"
    with pytest.raises(identity.WebUIRuntimeConfigurationError):
        configured_image_backend_id()
    with pytest.raises(identity.WebUIRuntimeConfigurationError):
        normalize_image_backend_options({}, model_name="juggernaut.safetensors")


@pytest.mark.parametrize(
    ("default", "expected"), [("webui", "forge_webui"), ("comfyui", "comfyui")]
)
def test_an_ordinary_checkpoint_takes_the_configured_default(
    settings: dict, default: str, expected: str
) -> None:
    settings["image_backend_default"] = default
    options = normalize_image_backend_options({}, model_name="juggernaut.safetensors")
    assert options["image"]["backend_id"] == expected


@pytest.mark.parametrize("default", ["webui", "comfyui"])
def test_model_required_backends_still_win_over_the_default(settings: dict, default: str) -> None:
    settings["image_backend_default"] = default
    qwen = normalize_image_backend_options({}, model_name=QWEN_IMAGE_21_PROFILE_V1.model_name)
    ideogram = normalize_image_backend_options({}, model_name=IDEOGRAM4_PROFILE_V1.model_name)
    assert qwen["image"]["backend_id"] == "comfyui"
    assert ideogram["image"]["backend_id"] == IDEOGRAM4_PROFILE_V1.backend_id


def test_an_explicit_identity_is_never_rewritten_by_the_default(settings: dict) -> None:
    settings["image_backend_default"] = "comfyui"
    kept = normalize_image_backend_options(
        {"image": {"backend_id": "forge_webui"}}, model_name="juggernaut.safetensors"
    )
    explicit = normalize_image_backend_options(
        {}, backend_id="a1111_webui", model_name="juggernaut.safetensors"
    )
    assert (
        kept["image"]["backend_id"] == "forge_webui"
        and explicit["image"]["backend_id"] == "a1111_webui"
    )
