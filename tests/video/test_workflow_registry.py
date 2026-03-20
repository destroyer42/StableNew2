from __future__ import annotations

from src.video import (
    WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowRegistry,
    WorkflowSpec,
    build_default_workflow_registry,
)


def test_default_workflow_registry_registers_builtin_ltx_workflow() -> None:
    registry = build_default_workflow_registry()

    assert registry.list_workflow_ids() == ["ltx_multiframe_anchor_v1"]
    spec = registry.get("ltx_multiframe_anchor_v1")
    assert spec.backend_id == "comfy"
    assert spec.workflow_version == "1.0.0"
    assert "multi_frame_anchor_video" in spec.capability_tags
    assert any(binding.binding_name == "end_anchor" for binding in spec.input_bindings)


def test_workflow_registry_rejects_duplicate_workflow_versions() -> None:
    registry = WorkflowRegistry()
    spec = WorkflowSpec(
        workflow_id="workflow-a",
        workflow_version="1.0.0",
        backend_id="comfy",
        display_name="Workflow A",
        capability_tags=(WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO,),
        input_bindings=(WorkflowInputBinding("source", "input_image_path"),),
        output_bindings=(WorkflowOutputBinding("output_dir", "output_dir", required=True),),
        dependency_specs=(
            WorkflowDependencySpec(
                dependency_id="dep-1",
                dependency_kind="custom_node",
                locator="NodePackage",
            ),
        ),
    )
    registry.register(spec)

    try:
        registry.register(spec)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("Expected duplicate workflow registration to fail")


def test_workflow_spec_rejects_duplicate_dependency_ids() -> None:
    try:
        WorkflowSpec(
            workflow_id="workflow-b",
            workflow_version="1.0.0",
            backend_id="comfy",
            display_name="Workflow B",
            capability_tags=(WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO,),
            input_bindings=(WorkflowInputBinding("source", "input_image_path"),),
            output_bindings=(WorkflowOutputBinding("output_dir", "output_dir", required=True),),
            dependency_specs=(
                WorkflowDependencySpec("dep-1", "custom_node", "NodeA"),
                WorkflowDependencySpec("dep-1", "checkpoint", "CheckpointA"),
            ),
        )
    except ValueError as exc:
        assert "duplicate dependency ids" in str(exc)
    else:
        raise AssertionError("Expected duplicate dependency ids to fail validation")


def test_workflow_registry_requires_version_when_multiple_versions_exist() -> None:
    registry = WorkflowRegistry()
    for version in ("1.0.0", "1.1.0"):
        registry.register(
            WorkflowSpec(
                workflow_id="workflow-c",
                workflow_version=version,
                backend_id="comfy",
                display_name=f"Workflow C {version}",
                capability_tags=(WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO,),
                input_bindings=(WorkflowInputBinding("source", "input_image_path"),),
                output_bindings=(WorkflowOutputBinding("output_dir", "output_dir", required=True),),
                dependency_specs=(
                    WorkflowDependencySpec("dep-1", "custom_node", f"Node-{version}"),
                ),
            )
        )

    try:
        registry.get("workflow-c")
    except KeyError as exc:
        assert "multiple versions" in str(exc)
    else:
        raise AssertionError("Expected ambiguous workflow lookup to require an explicit version")
