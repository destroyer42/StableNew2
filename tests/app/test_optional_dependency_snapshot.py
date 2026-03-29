from __future__ import annotations

from types import SimpleNamespace

from src.app.optional_dependency_probes import (
    OPTIONAL_DEPENDENCY_SCHEMA_V1,
    build_optional_dependency_snapshot,
)


def test_build_optional_dependency_snapshot_collects_comfy_and_svd_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.optional_dependency_probes.build_default_workflow_registry",
        lambda: SimpleNamespace(
            list_specs_for_backend=lambda backend_id: [
                SimpleNamespace(
                    workflow_id="wf-1",
                    workflow_version="1.0.0",
                    governance_state="approved",
                    pinned_revision="git:abc123",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "src.app.optional_dependency_probes.ComfyDependencyProbe",
        lambda client=None: SimpleNamespace(
            probe_workflow=lambda spec, object_info=None: SimpleNamespace(
                ready=True,
                missing_required=[],
                to_dict=lambda: {"workflow_id": spec.workflow_id, "ready": True},
            )
        ),
    )
    monkeypatch.setattr(
        "src.app.optional_dependency_probes.get_svd_postprocess_capabilities",
        lambda config=None: {
            "rife": SimpleNamespace(
                available=True,
                status="ready",
                detail="rife present",
                to_dict=lambda: {"available": True, "status": "ready"},
            )
        },
    )

    snapshot = build_optional_dependency_snapshot(
        comfy_object_info={"nodes": []},
        comfy_client=object(),
    ).to_dict()

    assert snapshot["schema"] == OPTIONAL_DEPENDENCY_SCHEMA_V1
    assert snapshot["capabilities"]["workflow:wf-1@1.0.0"]["status"] == "ready"
    assert snapshot["capabilities"]["workflow:wf-1@1.0.0"]["metadata"]["workflow_id"] == "wf-1"
    assert snapshot["capabilities"]["svd:rife"]["status"] == "ready"


def test_build_optional_dependency_snapshot_reports_unknown_when_comfy_probe_inputs_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.optional_dependency_probes.build_default_workflow_registry",
        lambda: SimpleNamespace(
            list_specs_for_backend=lambda backend_id: [
                SimpleNamespace(
                    workflow_id="wf-2",
                    workflow_version="2.0.0",
                    governance_state="approved",
                    pinned_revision="git:def456",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "src.app.optional_dependency_probes.get_svd_postprocess_capabilities",
        lambda config=None: {},
    )

    snapshot = build_optional_dependency_snapshot().to_dict()

    assert snapshot["capabilities"]["workflow:wf-2@2.0.0"]["status"] == "unknown"
