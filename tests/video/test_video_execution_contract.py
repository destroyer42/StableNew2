"""PR-VID-120: neutral video contract (task, controls, explicit backend) with fake backends.

No GPU, no model, no Comfy: fake backends record whether they were ever called.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.video_backend_registry import (
    VideoBackendRegistry,
    build_default_video_backend_registry,
)
from src.video.video_backend_types import (
    CONTROL_CONTROL_VIDEO,
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_POSE_VIDEO,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
    VIDEO_TASK_IMAGE_TO_VIDEO,
    VideoBackendCapabilities,
    VideoExecutionRequest,
)
from src.video.video_execution_resolver import (
    LEGACY_STAGE_BINDINGS,
    VideoContractError,
    VideoExecutionResolver,
)
from src.video.workflow_contracts import (
    WORKFLOW_CAP_POSE_VIDEO,
    WorkflowDependencySpec,
    WorkflowInputBinding,
    WorkflowOutputBinding,
    WorkflowSpec,
)
from src.video.workflow_registry import WorkflowRegistry


class _FakeBackend:
    def __init__(
        self, backend_id: str, *, controls: tuple[str, ...], required=(CONTROL_SOURCE_IMAGE,)
    ):
        self.backend_id = backend_id
        self.capabilities = VideoBackendCapabilities(
            backend_id=backend_id,
            tasks=(VIDEO_TASK_IMAGE_TO_VIDEO,),
            controls=controls,
            required_controls=tuple(required),
        )
        self.calls = 0

    def execute(self, pipeline, request):
        self.calls += 1
        return None


def _resolver(*backends: _FakeBackend) -> VideoExecutionResolver:
    registry = VideoBackendRegistry()
    for backend in backends:
        registry.register(backend)
    return VideoExecutionResolver(registry)


def _neutral(
    backend_id: str, controls: tuple[str, ...] = (), task: str = VIDEO_TASK_IMAGE_TO_VIDEO
):
    return {"video_execution": {"backend_id": backend_id, "task": task, "controls": list(controls)}}


def test_capabilities_fold_legacy_flags_into_one_source_of_truth() -> None:
    legacy = VideoBackendCapabilities(
        backend_id="x",
        stage_types=("s",),
        requires_input_image=True,
        supports_prompt_text=True,
        supports_multiple_anchors=True,
    )
    assert legacy.tasks == (VIDEO_TASK_IMAGE_TO_VIDEO,)
    assert (
        CONTROL_PROMPT_TEXT in legacy.controls and CONTROL_SOURCE_IMAGE in legacy.required_controls
    )
    assert "mid_anchors" in legacy.controls and legacy.supports_multiple_anchors is True
    assert legacy.supports_negative_prompt is False
    with pytest.raises(ValueError, match="unknown controls"):
        VideoBackendCapabilities(backend_id="x", controls=("wan2.2",))
    with pytest.raises(ValueError, match="unsupported tasks"):
        VideoBackendCapabilities(backend_id="x", tasks=("text_to_video",))
    with pytest.raises(ValueError, match="undeclared"):
        VideoBackendCapabilities(
            backend_id="x", controls=(CONTROL_SOURCE_IMAGE,), required_controls=("prompt_text",)
        )


def test_default_backends_declare_semantic_tasks_and_controls_not_stage_names() -> None:
    registry = build_default_video_backend_registry()
    assert registry.list_backend_ids_for_task(VIDEO_TASK_IMAGE_TO_VIDEO) == [
        "animatediff",
        "comfy",
        "svd_native",
    ]
    svd = registry.get("svd_native").capabilities
    assert svd.controls == (CONTROL_SOURCE_IMAGE,) and svd.required_controls == (
        CONTROL_SOURCE_IMAGE,
    )
    assert CONTROL_PROMPT_TEXT not in svd.controls
    assert "identity_preservation" not in "".join(svd.controls)  # observed result, not a capability


def test_two_backends_may_share_a_task_but_backend_ids_stay_unique() -> None:
    a = _FakeBackend("fake_a", controls=(CONTROL_SOURCE_IMAGE,))
    b = _FakeBackend("fake_b", controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT))
    registry = VideoBackendRegistry()
    registry.register(a)
    registry.register(b)  # same semantic task, no stage claim: no conflict
    assert registry.list_backend_ids_for_task(VIDEO_TASK_IMAGE_TO_VIDEO) == ["fake_a", "fake_b"]
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_FakeBackend("fake_a", controls=(CONTROL_SOURCE_IMAGE,)))


def test_explicit_backend_id_selects_the_backend_not_order_or_task() -> None:
    a, b = (
        _FakeBackend("fake_a", controls=(CONTROL_SOURCE_IMAGE,)),
        _FakeBackend("fake_b", controls=(CONTROL_SOURCE_IMAGE,)),
    )
    resolver = _resolver(a, b)  # a registered first
    intent = resolver.build_intent("video_workflow", _neutral("fake_b"), has_source_image=True)
    assert resolver.resolve("video_workflow", intent) is b


def test_prompt_text_fails_before_dispatch_for_svd_but_a_prompt_backend_accepts_it() -> None:
    registry = build_default_video_backend_registry()
    resolver = VideoExecutionResolver(registry)
    ok = resolver.build_intent(
        "video_workflow", _neutral("svd_native", (CONTROL_SOURCE_IMAGE,)), has_source_image=True
    )
    assert resolver.resolve("video_workflow", ok).backend_id == "svd_native"
    bad = resolver.build_intent(
        "video_workflow",
        _neutral("svd_native", (CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT)),
        has_source_image=True,
    )
    with pytest.raises(VideoContractError) as caught:
        resolver.resolve("video_workflow", bad)
    assert caught.value.code == "unsupported_control" and "prompt_text" in str(caught.value)

    prompt_backend = _FakeBackend(
        "fake_prompt", controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT)
    )
    fake_resolver = _resolver(prompt_backend)
    intent = fake_resolver.build_intent(
        "video_workflow", _neutral("fake_prompt", (CONTROL_PROMPT_TEXT,)), has_source_image=True
    )
    assert fake_resolver.resolve("video_workflow", intent) is prompt_backend


def test_unsupported_or_missing_controls_never_reach_the_backend() -> None:
    backend = _FakeBackend("fake_a", controls=(CONTROL_SOURCE_IMAGE,))
    resolver = _resolver(backend)
    for controls, has_source, code in (
        ((CONTROL_POSE_VIDEO,), True, "unsupported_control"),
        ((CONTROL_CONTROL_VIDEO,), True, "unsupported_control"),
        ((), False, "missing_control"),
        (("wan2.2",), True, "unknown_control"),
    ):
        intent = resolver.build_intent(
            "video_workflow", _neutral("fake_a", controls), has_source_image=has_source
        )
        with pytest.raises(VideoContractError) as caught:
            resolver.resolve("video_workflow", intent)
        assert caught.value.code == code
    assert backend.calls == 0  # resolution alone never executes and nothing was dropped


def test_unknown_backend_unsupported_task_and_missing_backend_id_are_deterministic() -> None:
    resolver = _resolver(_FakeBackend("fake_a", controls=(CONTROL_SOURCE_IMAGE,)))
    cases = (
        (_neutral("ghost"), "unknown_backend"),
        (_neutral("fake_a", task="text_to_video"), "unsupported_task"),
        (
            {"video_execution": {"task": VIDEO_TASK_IMAGE_TO_VIDEO, "controls": []}},
            "backend_required",
        ),
    )
    for config, code in cases:
        intent = resolver.build_intent("video_workflow", config, has_source_image=True)
        with pytest.raises(VideoContractError) as caught:
            resolver.resolve("video_workflow", intent)
        assert caught.value.code == code


def test_no_fallback_between_backends() -> None:
    good = _FakeBackend("fake_good", controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT))
    narrow = _FakeBackend("fake_narrow", controls=(CONTROL_SOURCE_IMAGE,))
    resolver = _resolver(good, narrow)
    intent = resolver.build_intent(
        "video_workflow", _neutral("fake_narrow", (CONTROL_PROMPT_TEXT,)), has_source_image=True
    )
    with pytest.raises(VideoContractError):
        resolver.resolve("video_workflow", intent)  # never silently reroutes to fake_good
    assert good.calls == narrow.calls == 0


def test_legacy_bridge_maps_only_the_three_accepted_stage_types() -> None:
    assert set(LEGACY_STAGE_BINDINGS) == {"svd_native", "animatediff", "video_workflow"}
    resolver = VideoExecutionResolver(build_default_video_backend_registry())
    svd = resolver.build_intent("svd_native", {}, has_source_image=True)
    assert svd.legacy and svd.controls == (CONTROL_SOURCE_IMAGE,)  # prompt stays context-only
    assert resolver.resolve("svd_native", svd).backend_id == "svd_native"
    anchored = resolver.build_intent(
        "video_workflow",
        {"end_anchor_path": "e.png", "mid_anchor_paths": ["m.png"]},
        has_source_image=True,
    )
    assert {"end_anchor", "mid_anchors", CONTROL_NEGATIVE_PROMPT} <= set(anchored.controls)
    assert resolver.resolve("video_workflow", anchored).backend_id == "comfy"
    with pytest.raises(VideoContractError, match="video_execution"):
        resolver.build_intent("future_stage", {}, has_source_image=True)


def _workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    common = {
        "backend_id": "comfy",
        "display_name": "x",
        "input_bindings": (
            WorkflowInputBinding(binding_name="image", source_field="input_image_path"),
        ),
        "output_bindings": (
            WorkflowOutputBinding(binding_name="video", source_field="video_path"),
        ),
        "dependency_specs": (
            WorkflowDependencySpec(dependency_id="d", dependency_kind="custom_node", locator="x"),
        ),
    }
    registry.register(
        WorkflowSpec(workflow_id="plain", workflow_version="1", **common, pinned_revision="r1")
    )
    registry.register(
        WorkflowSpec(
            workflow_id="posed",
            workflow_version="1",
            capability_tags=(WORKFLOW_CAP_POSE_VIDEO,),
            pinned_revision="r1",
            **common,
        )
    )
    registry.register(
        WorkflowSpec(
            workflow_id="off",
            workflow_version="1",
            governance_state="disabled",
            pinned_revision="r1",
            **common,
        )
    )
    return registry


def test_explicit_workflow_is_validated_for_governance_version_and_controls() -> None:
    comfy = ComfyWorkflowVideoBackend(workflow_registry=_workflow_registry())
    registry = VideoBackendRegistry()
    registry.register(comfy)
    resolver = VideoExecutionResolver(registry)

    def request_for(workflow_id: str, version: str, controls: tuple[str, ...]):
        config = _neutral("comfy", controls)
        config["video_execution"].update(workflow_id=workflow_id, workflow_version=version)
        intent = resolver.build_intent("video_workflow", config, has_source_image=True)
        request = VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config=config,
            output_dir=Path("."),
        )
        return intent, request

    intent, request = request_for("posed", "1", (CONTROL_POSE_VIDEO,))
    resolver.apply(request, intent)  # declared by the workflow's capability tag
    assert (
        request.task == VIDEO_TASK_IMAGE_TO_VIDEO
        and CONTROL_POSE_VIDEO in request.requested_controls
    )
    assert request.context_metadata["video_contract"]["legacy_stage_routing"] is False
    for workflow_id, controls, fragment in (
        ("plain", (CONTROL_POSE_VIDEO,), "does not declare"),  # workflow lacks the control
        ("off", (), "not approved"),  # disabled governance can never dispatch
        ("ghost", (), "not registered"),
    ):
        intent, request = request_for(workflow_id, "1", controls)
        with pytest.raises(VideoContractError) as caught:
            resolver.apply(request, intent)
        assert caught.value.code == "invalid_workflow" and fragment in str(caught.value)
    intent, request = request_for("posed", "9", ())  # explicit version, no implicit substitution
    with pytest.raises(VideoContractError, match="not registered"):
        resolver.apply(request, intent)
