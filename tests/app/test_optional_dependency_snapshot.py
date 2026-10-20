from __future__ import annotations

import socket
import subprocess
from types import SimpleNamespace

from src.app.optional_dependency_probes import (
    OPTIONAL_DEPENDENCY_SCHEMA_V1,
    build_optional_dependency_snapshot,
)


def test_build_optional_dependency_snapshot_collects_comfy_and_svd_capabilities(
    monkeypatch,
) -> None:
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


def test_build_optional_dependency_snapshot_reports_unknown_when_comfy_probe_inputs_missing(
    monkeypatch,
) -> None:
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


def test_the_startup_snapshot_lists_the_approved_ti2v_workflow_without_starting_or_fetching_anything(
    monkeypatch,
) -> None:
    """PR-VID-GOV-316: promoting TI2V-5B 1.2.0 makes ``list_specs_for_backend`` return it.

    With no object info and no client (the bootstrap call), the entry is ``unknown`` and the build
    constructs no dependency probe, spawns no process and opens no connection.
    """

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("the startup snapshot must not probe, spawn or connect")

    monkeypatch.setattr("src.app.optional_dependency_probes.ComfyDependencyProbe", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(
        "src.app.optional_dependency_probes.get_svd_postprocess_capabilities",
        lambda config=None: {},
    )

    capabilities = build_optional_dependency_snapshot().to_dict()["capabilities"]

    assert sorted(capabilities) == ["workflow:wan22_ti2v_5b_i2v_v1@1.2.0"]
    entry = capabilities["workflow:wan22_ti2v_5b_i2v_v1@1.2.0"]
    assert entry["status"] == "unknown" and entry["available"] is False
    assert entry["source"] == "comfy"


def test_a_snapshot_with_comfy_object_info_probes_only_the_approved_workflow_version() -> None:
    from src.video.workflow_catalog import WAN22_STOCK_NODES

    object_info = {node: {"input": {"required": {}}} for node in WAN22_STOCK_NODES}

    capabilities = build_optional_dependency_snapshot(comfy_object_info=object_info).to_dict()[
        "capabilities"
    ]
    workflows = {key for key in capabilities if key.startswith("workflow:")}

    assert workflows == {"workflow:wan22_ti2v_5b_i2v_v1@1.2.0"}
    # The stock nodes are present but this object_info offers no model files: reported as missing
    # (the probe reads the payload it was given; nothing is looked up or downloaded).
    entry = capabilities["workflow:wan22_ti2v_5b_i2v_v1@1.2.0"]
    assert entry["status"] == "missing"
    assert (
        entry["detail"]
        == "Missing required dependencies: wan22_text_encoder, wan22_unet, wan22_vae"
    )
