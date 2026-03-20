from __future__ import annotations

from src.video import ComfyDependencyProbe, build_default_workflow_registry


def test_comfy_dependency_probe_marks_workflow_ready_when_dependencies_present() -> None:
    registry = build_default_workflow_registry()
    spec = registry.get("ltx_multiframe_anchor_v1")
    probe = ComfyDependencyProbe()

    result = probe.probe_workflow(
        spec,
        object_info={
            "ComfyUI-LTXVideo": {"nodes": ["LTXLoader"]},
            "models": {"checkpoints": ["ltx_video.safetensors"]},
            "ltx_video": True,
        },
    )

    assert result.ready is True
    assert result.missing_required == ()
    assert "comfy_ltx_nodes" in result.present
    assert "ltx_model" in result.present


def test_comfy_dependency_probe_reports_missing_required_dependencies() -> None:
    registry = build_default_workflow_registry()
    spec = registry.get("ltx_multiframe_anchor_v1")
    probe = ComfyDependencyProbe()

    result = probe.probe_workflow(
        spec,
        object_info={"models": {"checkpoints": []}},
    )

    assert result.ready is False
    assert "comfy_ltx_nodes" in result.missing_required
    assert "ltx_model" in result.missing_required
