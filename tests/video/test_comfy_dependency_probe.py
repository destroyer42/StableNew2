from __future__ import annotations

from src.video import ComfyDependencyProbe
from tests.helpers.video_contract_registry import build_synthetic_contract_registry


def test_comfy_dependency_probe_marks_workflow_ready_when_dependencies_present() -> None:
    registry = build_synthetic_contract_registry()
    spec = registry.get("synthetic_anchor_video_v1")
    probe = ComfyDependencyProbe()

    result = probe.probe_workflow(
        spec,
        object_info={
            "SyntheticAnchorBridge": {"input": {}},
            "models": {"checkpoints": ["synthetic_video.safetensors"]},
        },
    )

    assert result.ready is True
    assert result.missing_required == ()
    assert "synthetic_nodes" in result.present
    assert "synthetic_model" in result.present


def test_comfy_dependency_probe_reports_missing_required_dependencies() -> None:
    registry = build_synthetic_contract_registry()
    spec = registry.get("synthetic_anchor_video_v1")
    probe = ComfyDependencyProbe()

    result = probe.probe_workflow(
        spec,
        object_info={"models": {"checkpoints": []}},
    )

    assert result.ready is False
    assert "synthetic_nodes" in result.missing_required
    assert "synthetic_model" in result.missing_required


def test_comfy_dependency_probe_allows_unverified_checkpoint_when_model_inventory_absent() -> None:
    registry = build_synthetic_contract_registry()
    spec = registry.get("synthetic_anchor_video_v1")
    probe = ComfyDependencyProbe()

    result = probe.probe_workflow(
        spec,
        object_info={
            "SyntheticAnchorBridge": {"input": {}},
        },
    )

    assert result.ready is True
    assert result.missing_required == ()
    assert result.details["synthetic_model"]["verifiable"] is False
    assert result.details["synthetic_model"]["status"] == "unverified"
