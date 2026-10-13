"""Pure operator diagnostics and declaration preservation, plus a real widget round trip."""

from __future__ import annotations

import copy
import io

import pytest
from PIL import Image

from src.conditioning.openpose import new_declaration
from src.conditioning.openpose_diagnostics import (
    geometry_feedback,
    input_image_facts,
    pose_model_hint,
)
from src.gui_v2.openpose_conditioning_view import describe_openpose
from src.image_backends.openpose_capability import STATUS_SUPPORTED, OpenPoseTarget

TARGET = OpenPoseTarget(STATUS_SUPPORTED, "supported", "SDXL on Forge", family="sdxl")


@pytest.mark.parametrize(
    "model,blocked",
    [
        ("diffusers_xl_depth_full [12345678]", True),
        ("ttplanetSDXLControlnet_v20Fp16", True),
        ("thibaud_xl_openpose", False),
        ("custom_model", False),
        ("depth_in_an_arbitrary_name", False),
    ],
)
def test_family_evidence_is_never_reported_as_pose_qualification(model, blocked) -> None:
    raw = new_declaration("pose.png", model=model)
    before = copy.deepcopy(raw)
    view = describe_openpose(raw, target=TARGET, model_status="sdxl")
    assert view.executable is not blocked
    assert raw == before and view.selection.model == model
    assert pose_model_hint(model).status == ("incompatible" if blocked else "unverified")
    text = " ".join(line.text for line in view.lines)
    assert "pose" in text.lower() and ("unverified" in text if not blocked else "known" in text)


@pytest.mark.parametrize(
    "mode,fragment",
    [
        ("Balanced", "balances"),
        ("My prompt is more important", "reduces"),
        ("ControlNet is more important", "overpower"),
    ],
)
def test_warnings_explain_strength_without_changing_saved_intent(mode, fragment) -> None:
    raw = {
        **new_declaration("pose.png", model="thibaud_xl_openpose"),
        "weight": 1.75,
        "guidance_start": 0.15,
        "guidance_end": 0.85,
        "control_mode": mode,
    }
    before = copy.deepcopy(raw)
    view = describe_openpose(
        raw,
        target=TARGET,
        image_facts={
            "width": 1024,
            "height": 1024,
            "has_transparency": True,
        },
    )
    text = " ".join(line.text for line in view.lines)
    assert raw == before and view.selection.weight == 1.75
    assert fragment in text and "white, not black" in text and "1024x1024" in text
    assert "None passes the supplied pixels" in text


@pytest.mark.parametrize(
    "mode,fragment",
    [
        ("Just Resize", "stretches"),
        ("Crop and Resize", "crops"),
        ("Resize and Fill", "pads"),
    ],
)
def test_geometry_feedback_is_specific_and_flags_aspect_ratio_mismatch(mode, fragment) -> None:
    text = geometry_feedback(1024, 1024, mode, target=(512, 1024))
    assert fragment in text and "Aspect ratios differ" in text and "512x1024" in text


def test_palette_transparency_and_opaque_rgba_are_distinguished_without_rewriting_bytes() -> None:
    for mode, alpha, expected in [("RGBA", 255, False), ("RGBA", 0, True)]:
        image = Image.new(mode, (64, 96), (0, 0, 0, alpha))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        facts = input_image_facts(data)
        assert facts["has_transparency"] is expected and facts["width"] == 64
    palette = Image.new("P", (64, 96), 0)
    palette_buffer = io.BytesIO()
    palette.save(palette_buffer, format="PNG", transparency=0)
    assert input_image_facts(palette_buffer.getvalue())["has_transparency"] is True


@pytest.mark.gui
def test_widget_warning_refresh_keeps_every_persisted_setting(tk_root, tmp_path) -> None:
    from tests.gui_v2.test_openpose_picker_panel_210 import _panel, library

    # The fixture implementation is reused explicitly to keep this test's filesystem isolated.
    root = library.__wrapped__(tmp_path)
    panel, changes = _panel(tk_root, root, tmp_path)
    raw = {
        **new_declaration("Standing/relaxed.png", model="diffusers_xl_depth_full"),
        "weight": 0.0,
        "guidance_start": 0.2,
        "guidance_end": 0.7,
        "control_mode": "ControlNet is more important",
        "resize_mode": "Crop and Resize",
    }
    try:
        panel.set_target(TARGET)
        panel.set_declaration(raw)
        panel.refresh_library()
        assert panel.get_declaration() == raw and changes == []
        assert not panel.current_view().executable
        assert "known depth" in panel.notes_var.get() and "crops" in panel.notes_var.get()
        assert panel.weight_var.get() == "0"
    finally:
        panel.destroy()
