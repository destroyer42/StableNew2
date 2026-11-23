"""PR-IMG-COMFY-381: the Base Generation projection shows the effective ComfyUI backend and blocks what cannot run there."""

from __future__ import annotations

from src.gui_v2.model_policy_projection import project_model_controls
from src.image_backends.model_policy import (
    EVIDENCE_NONE,
    EVIDENCE_REGISTRY,
    FAMILY_UNKNOWN,
    _sdxl_policy,
    _unverified_policy,
)


def test_an_sdxl_policy_projects_the_comfy_badge_without_blocking() -> None:
    projection = project_model_controls(
        _sdxl_policy(EVIDENCE_REGISTRY), "comfyui", model_name="juggernaut.safetensors"
    )
    assert projection.note.startswith("Image backend: ComfyUI")
    assert projection.blocking == ""


def test_a_model_comfy_cannot_run_is_blocked_with_switch_guidance() -> None:
    projection = project_model_controls(
        _unverified_policy(FAMILY_UNKNOWN, EVIDENCE_NONE), "comfyui"
    )
    assert "Switch the Image backend to Forge" in projection.blocking


def test_the_forge_projection_is_unchanged() -> None:
    projection = project_model_controls(_sdxl_policy(EVIDENCE_REGISTRY), "forge_webui")
    assert projection.note == "" and projection.blocking == ""
