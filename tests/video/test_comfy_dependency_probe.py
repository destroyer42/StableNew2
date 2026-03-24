from __future__ import annotations

from src.video import ComfyDependencyProbe, build_default_workflow_registry


def test_comfy_dependency_probe_marks_workflow_ready_when_dependencies_present() -> None:
    registry = build_default_workflow_registry()
    spec = registry.get("ltx_multiframe_anchor_v1")
    probe = ComfyDependencyProbe()

    result = probe.probe_workflow(
        spec,
        object_info={
            "StableNewLTXAnchorBridge": {"input": {}},
            "models": {"checkpoints": ["ltx_video.safetensors"]},
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


def test_comfy_dependency_probe_allows_unverified_checkpoint_when_model_inventory_absent() -> None:
    registry = build_default_workflow_registry()
    spec = registry.get("ltx_multiframe_anchor_v1")
    probe = ComfyDependencyProbe()

    result = probe.probe_workflow(
        spec,
        object_info={
            "StableNewLTXAnchorBridge": {"input": {}},
        },
    )

    assert result.ready is True
    assert result.missing_required == ()
    assert result.details["ltx_model"]["verifiable"] is False
    assert result.details["ltx_model"]["status"] == "unverified"
