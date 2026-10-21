from __future__ import annotations

import pytest

from src.video import (
    WORKFLOW_CAP_SINGLE_IMAGE_TO_VIDEO,
    WORKFLOW_GOVERNANCE_DISABLED,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowRegistry,
    WorkflowSpec,
    build_default_workflow_registry,
)
from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_registry import RETIRED_WORKFLOW_IDS, WorkflowLookupError
from tests.helpers.video_contract_registry import (
    SYNTHETIC_ANCHOR_ID,
    SYNTHETIC_DISABLED_ID,
    build_synthetic_disabled_registry,
)


def test_default_workflow_registry_holds_only_real_evidence_backed_workflows() -> None:
    registry = build_default_workflow_registry()

    assert registry.list_workflow_ids() == [
        "wan22_ti2v_5b_i2v_v1",
        "wan_animate2_drive_i2v_v1",
        "wan_animate2_prompt_i2v_v1",
    ]
    # No catalog entry is a disabled placeholder: every registered spec is offerable.
    assert all(spec.is_offerable for spec in build_builtin_workflow_specs())
    assert not any(
        spec.governance_state == WORKFLOW_GOVERNANCE_DISABLED for spec in build_builtin_workflow_specs()
    )
    # The qualified fixed-length revision stays registered for exact replay beside the
    # PR-VID-190 variable-length revision.
    assert [
        (spec.workflow_id, spec.workflow_version)
        for spec in registry.list_offerable_specs("comfy")
    ] == [
        ("wan22_ti2v_5b_i2v_v1", "1.0.0"),
        ("wan22_ti2v_5b_i2v_v1", "1.1.0"),
        ("wan22_ti2v_5b_i2v_v1", "1.2.0"),
        ("wan22_ti2v_5b_i2v_v1", "1.3.0"),
        ("wan_animate2_drive_i2v_v1", "1.0.0"),
        ("wan_animate2_drive_i2v_v1", "1.1.0"),
        ("wan_animate2_drive_i2v_v1", "1.2.0"),
        ("wan_animate2_prompt_i2v_v1", "1.0.0"),
        ("wan_animate2_prompt_i2v_v1", "1.1.0"),
        ("wan_animate2_prompt_i2v_v1", "1.2.0"),
    ]


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


def test_workflow_registry_rejects_disabled_workflow_at_lookup_time() -> None:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowSpec(
            workflow_id="workflow-disabled",
            workflow_version="1.0.0",
            backend_id="comfy",
            display_name="Workflow Disabled",
            governance_state=WORKFLOW_GOVERNANCE_DISABLED,
            input_bindings=(WorkflowInputBinding("source", "input_image_path"),),
            output_bindings=(WorkflowOutputBinding("output_dir", "output_dir", required=True),),
            dependency_specs=(WorkflowDependencySpec("dep-1", "custom_node", "NodeA"),),
        )
    )

    try:
        registry.get("workflow-disabled", "1.0.0")
    except KeyError as exc:
        assert "not approved" in str(exc)
    else:
        raise AssertionError("Expected disabled workflow lookup to fail")


def test_disabled_workflow_is_never_offerable_or_runnable_even_with_experimental_opt_in() -> None:
    registry = build_synthetic_disabled_registry()

    assert SYNTHETIC_DISABLED_ID in registry.list_workflow_ids()
    assert SYNTHETIC_DISABLED_ID not in [
        spec.workflow_id for spec in registry.list_offerable_specs("comfy")
    ]
    assert SYNTHETIC_DISABLED_ID not in [
        spec.workflow_id for spec in registry.list_specs_for_backend("comfy")
    ]
    # The approved synthetic spec beside it is offered, so the exclusion is by governance state.
    assert SYNTHETIC_ANCHOR_ID in [spec.workflow_id for spec in registry.list_offerable_specs("comfy")]
    for lookup in (
        lambda: registry.get(SYNTHETIC_DISABLED_ID, "1.0.0"),
        lambda: registry.get(SYNTHETIC_DISABLED_ID, "1.0.0", allow_experimental=True),
        lambda: registry.get_offerable(SYNTHETIC_DISABLED_ID, "1.0.0"),
        lambda: registry.get(SYNTHETIC_DISABLED_ID),
    ):
        with pytest.raises(WorkflowLookupError, match="not approved for execution"):
            lookup()


def test_unknown_and_retired_workflow_ids_fail_with_a_stable_readable_message() -> None:
    registry = build_default_workflow_registry()

    with pytest.raises(KeyError) as unknown:
        registry.get("no_such_workflow_v9", "1.0.0")
    assert isinstance(unknown.value, WorkflowLookupError)
    # str() is the plain message: KeyError would otherwise wrap it in repr quotes.
    assert str(unknown.value) == "Workflow 'no_such_workflow_v9' version '1.0.0' is not registered"
    with pytest.raises(WorkflowLookupError) as unversioned:
        registry.get("no_such_workflow_v9")
    assert str(unversioned.value) == "Workflow 'no_such_workflow_v9' is not registered"

    assert set(RETIRED_WORKFLOW_IDS) == {
        "ltx_multiframe_anchor_v1",
        "ltx_multiframe_anchor_v1_conditioned",
    }
    for retired_id in RETIRED_WORKFLOW_IDS:
        for lookup in (
            lambda retired_id=retired_id: registry.get(retired_id, "1.0.0"),
            lambda retired_id=retired_id: registry.get(retired_id),
            lambda retired_id=retired_id: registry.get_offerable(retired_id, "1.0.0"),
        ):
            with pytest.raises(WorkflowLookupError) as retired:
                lookup()
            message = str(retired.value)
            assert message.startswith(f"Workflow '{retired_id}'")
            assert "is not registered" in message and "was removed" in message
            assert not message.startswith(("'", '"'))
