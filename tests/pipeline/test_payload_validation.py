from __future__ import annotations

import math

import pytest

from src.pipeline.executor import WebUIPayloadValidationError, _validate_webui_payload


class _CustomObject:
    pass


def test_validate_webui_payload_sanitizes_strings_without_mutation():
    original = {
        "prompt": "clean\rhidden",
        "negative_prompt": "danger\x07signal",
    }

    sanitized = _validate_webui_payload("txt2img", original)

    assert sanitized["prompt"] == "cleanhidden"
    assert sanitized["negative_prompt"] == "dangersignal"
    assert sanitized is not original
    assert original["prompt"].endswith("hidden")


def test_validate_webui_payload_rejects_out_of_range_dimensions():
    with pytest.raises(WebUIPayloadValidationError) as excinfo:
        _validate_webui_payload("txt2img", {"width": 5000, "height": 64})

    assert "width must be between 1" in str(excinfo.value)


def test_validate_webui_payload_requires_finite_cfg_scale():
    with pytest.raises(WebUIPayloadValidationError) as excinfo:
        _validate_webui_payload("txt2img", {"cfg_scale": math.inf})

    assert "cfg_scale must be finite" in str(excinfo.value)


def test_validate_webui_payload_rejects_non_serializable_values():
    with pytest.raises(WebUIPayloadValidationError):
        _validate_webui_payload("txt2img", {"prompt": "ok", "meta": _CustomObject()})
