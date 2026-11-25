"""Animate 1.3.0 (CK attention launch profile, kept warm): catalog identity, profile resolution, launch plan and a real
manager and backend with fake Comfy.  Fakes only: no GPU, model, network or real process."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest
from src.video.comfy_process_manager import (
    ComfyProcessConfig,
    ComfyProcessManager,
    ComfyStartupError,
    clear_global_comfy_process_manager,
)
from src.video.managed_comfy_runtime import CK_ATTENTION_FLAG, PINNED_MEMORY_FLAG, plan_comfy_launch
from src.video.video_backend_types import (
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_POSE_VIDEO,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
)
from src.video.workflow_catalog_wan_a14b import WAN_A14B_CK_LAUNCH_ID, WAN_A14B_ID
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_KEEP_WARM_SECONDS,
    WAN_ANIMATE2_PROMPT_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
    WAN_ANIMATE2_SPEED_VERSION,
    animate2_launch_attention,
)
from src.video.workflow_launch_attention import launch_attention
from src.video.workflow_readiness import WorkflowResourceReadiness, required_launch_flags
from src.video.workflow_registry import WorkflowLookupError, build_default_workflow_registry
from tests.video.test_comfy_process_manager import (
    _FakeManaged,
    fake_comfy_command,
    fake_comfy_source,
)
from tests.video.test_pr_vid_190_comfy_lifecycle_frame_count import _no_transition
from tests.video.test_pr_vid_190_wan_animate2 import _AnimateComfy, _driving_clip
from tests.video.test_vid_warm_373_a14b_reuse import _slot
from tests.video.test_wan22_experimental_workflow import _driver_probe

REGISTRY = build_default_workflow_registry()


def _drive(version: str):
    return REGISTRY.get(WAN_ANIMATE2_DRIVE_ID, version, allow_experimental=True)


# ------------------------------------------------------------------------------------------- catalog


def test_1_3_0_is_the_1_2_0_graph_with_only_launch_and_disclosure_differences() -> None:
    old, new = _drive(WAN_ANIMATE2_RUNTIME_VERSION), _drive(WAN_ANIMATE2_SPEED_VERSION)

    assert (old.workflow_version, new.workflow_version) == ("1.2.0", "1.3.0")
    assert new.input_bindings == old.input_bindings
    assert new.output_bindings == old.output_bindings
    assert new.dependency_specs == old.dependency_specs
    assert new.capability_tags == old.capability_tags
    differing = {
        key
        for key in set(old.backend_defaults) | set(new.backend_defaults)
        if old.backend_defaults.get(key) != new.backend_defaults.get(key)
    }
    assert differing == {"operator_projection", "provenance", "runtime_policy"}
    # the graph, geometry, controls and sampling are byte-identical
    assert new.backend_defaults["prompt_template"] == old.backend_defaults["prompt_template"]
    assert new.backend_defaults["frame_count_policy"] == old.backend_defaults["frame_count_policy"]
    fixed_old = dict(old.backend_defaults["operator_projection"]["fixed_settings"])
    fixed_new = dict(new.backend_defaults["operator_projection"]["fixed_settings"])
    assert {k: v for k, v in fixed_new.items() if k not in {"attention", "runtime"}} == fixed_old
    assert "Comfy Kitchen" in fixed_new["attention"] and "1.2.0" in fixed_new["attention"]
    assert new.backend_defaults["provenance"]["comfyui_version"] == "0.38.0"
    assert "speed_evidence" in new.backend_defaults["provenance"]


def test_only_the_driving_video_workflow_gained_a_speed_revision() -> None:
    assert REGISTRY.list_versions(WAN_ANIMATE2_DRIVE_ID)[-1] == WAN_ANIMATE2_SPEED_VERSION
    assert REGISTRY.list_versions(WAN_ANIMATE2_PROMPT_ID)[-1] == WAN_ANIMATE2_RUNTIME_VERSION


def test_the_speed_revision_declares_a_bounded_idle_grace_and_keeps_the_release_policy() -> None:
    policy = _drive(WAN_ANIMATE2_SPEED_VERSION).backend_defaults["runtime_policy"]

    assert policy == {
        "release_owned_runtime_after_job": True,
        "keep_warm_between_jobs_seconds": WAN_ANIMATE2_KEEP_WARM_SECONDS,
        "required_launch_flags": [PINNED_MEMORY_FLAG],
    }
    assert 0 < WAN_ANIMATE2_KEEP_WARM_SECONDS <= 300


def test_earlier_revisions_declare_no_idle_grace_and_no_profile() -> None:
    for version in ("1.0.0", "1.1.0", "1.2.0"):
        policy = _drive(version).backend_defaults["runtime_policy"]
        assert "keep_warm_between_jobs_seconds" not in policy
        assert policy["required_launch_flags"] == [PINNED_MEMORY_FLAG]
        assert launch_attention(_drive(version)) is None


def test_the_speed_revision_stays_experimental_and_needs_the_per_job_opt_in() -> None:
    assert _drive(WAN_ANIMATE2_SPEED_VERSION).governance_state == "experimental"
    with pytest.raises(WorkflowLookupError, match="explicit experimental opt-in"):
        REGISTRY.get(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_SPEED_VERSION)


def test_the_profile_resolves_from_immutable_identity_and_only_for_the_speed_revision() -> None:
    resolved = {
        (spec.workflow_id, spec.workflow_version): launch_attention(spec)
        for workflow_id in REGISTRY.list_workflow_ids()
        for spec in (
            REGISTRY.get(workflow_id, version, allow_experimental=True)
            for version in REGISTRY.list_versions(workflow_id)
        )
    }
    assert resolved[(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_SPEED_VERSION)] == "ck"
    assert resolved[(WAN_A14B_ID, "1.0.0")] == "baseline"
    assert resolved[(WAN_A14B_CK_LAUNCH_ID, "1.0.0")] == "ck"
    assert sorted(key for key, value in resolved.items() if value == "ck") == sorted(
        [(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_SPEED_VERSION), (WAN_A14B_CK_LAUNCH_ID, "1.0.0")]
    )
    assert animate2_launch_attention(SimpleNamespace(workflow_id=WAN_ANIMATE2_DRIVE_ID, workflow_version="1.3.1")) is None


# ------------------------------------------------------------------------------------- launch plan


def test_launch_plan_adds_the_ck_flag_for_the_speed_revision_and_leaves_1_2_0_alone(tmp_path) -> None:
    command = fake_comfy_source(
        tmp_path / "runtime",
        "parser.add_argument('--disable-pinned-memory', action='store_true')\n"
        "attn_group = parser.add_mutually_exclusive_group()\n"
        "attn_group.add_argument('--use-ck-attention', action='store_true')\n",
    )
    workdir = str(tmp_path / "runtime")
    old, new = _drive(WAN_ANIMATE2_RUNTIME_VERSION), _drive(WAN_ANIMATE2_SPEED_VERSION)

    launched_old = plan_comfy_launch(command, workdir, required_launch_flags(old), attention_profile=launch_attention(old))
    launched_new = plan_comfy_launch(command, workdir, required_launch_flags(new), attention_profile=launch_attention(new))

    assert CK_ATTENTION_FLAG not in launched_old and PINNED_MEMORY_FLAG in launched_old
    assert CK_ATTENTION_FLAG in launched_new and PINNED_MEMORY_FLAG in launched_new


def test_a_runtime_that_does_not_offer_ck_attention_is_refused_before_anything_starts(tmp_path) -> None:
    command = fake_comfy_command(tmp_path / "runtime", PINNED_MEMORY_FLAG)
    new = _drive(WAN_ANIMATE2_SPEED_VERSION)

    with pytest.raises(ValueError, match="does not support --use-ck-attention"):
        plan_comfy_launch(command, str(tmp_path / "runtime"), required_launch_flags(new), attention_profile="ck")


# ------------------------------------------------------------- real manager and backend, fake Comfy


@pytest.fixture
def stack(tmp_path, monkeypatch):
    slot, _, _ = _slot()
    client = _AnimateComfy(tmp_path)
    backend = ComfyWorkflowVideoBackend(
        client=client,
        readiness=WorkflowResourceReadiness(ram_probe=lambda: 24.0, gpu_probe=_driver_probe(client.stats)),
        transition=_no_transition(),
        history_timeout=5.0,
        history_poll_interval=0.1,
        warm_hold=slot,
    )
    command = fake_comfy_source(
        tmp_path / "runtime",
        "parser.add_argument('--disable-pinned-memory', action='store_true')\n"
        "attn_group = parser.add_mutually_exclusive_group()\n"
        "attn_group.add_argument('--use-ck-attention', action='store_true')\n",
    )
    children: list[_FakeManaged] = []

    def factory(argv, **kwargs):
        child = _FakeManaged(argv, **kwargs)
        child._stderr = ["\x1b[32m[INFO]\x1b[0m DynamicVRAM support detected and enabled"]
        if CK_ATTENTION_FLAG in argv:
            child._stderr.append("[INFO] Using Comfy Kitchen attention")
        children.append(child)
        return child

    listener_pid = 54322
    root = SimpleNamespace(
        pid=54321,
        is_running=lambda: True,
        children=lambda recursive: [SimpleNamespace(pid=listener_pid, is_running=lambda: True)],
    )
    monkeypatch.setattr(psutil, "Process", lambda pid: root)
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_kw: [
            SimpleNamespace(
                status=psutil.CONN_LISTEN,
                pid=listener_pid,
                laddr=SimpleNamespace(ip="127.0.0.1", port=8188),
            )
        ],
    )
    manager = ComfyProcessManager(
        ComfyProcessConfig(command=list(command), autostart_enabled=True, base_url="http://localhost:8188"),
        process_factory=factory,
    )
    backend._process_manager = manager
    monkeypatch.setattr("src.video.comfy_process_manager.probe_comfy_endpoint", lambda *_a, **_k: "free")
    monkeypatch.setattr(manager, "check_health", lambda **_kw: True)
    monkeypatch.setattr(
        client,
        "get_system_stats",
        lambda: {
            **client.stats,
            "system": {**client.stats.get("system", {}), "argv": list(manager.running_command[1:])},
        },
    )
    yield backend, client, manager, children
    manager.stop()
    clear_global_comfy_process_manager()


def _request(tmp_path: Path, version: str, job: str) -> VideoExecutionRequest:
    source = tmp_path / "reference.png"
    source.write_bytes(b"png")
    clip = _driving_clip(tmp_path)
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={
            "workflow_id": WAN_ANIMATE2_DRIVE_ID,
            "workflow_version": version,
            "seed": 11,
            "frame_count": 41,
            "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
            "pose_video_path": str(clip),
            "pose_video_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
            "operator_controls": {
                "video_frame_offset": 0,
                "pose_prompt": "the woman waves",
                "pose_strength": 1.0,
                "pose_start_percent": 0.0,
                "pose_end_percent": 1.0,
                "reference_image_strength": 1.0,
            },
        },
        output_dir=tmp_path / job,
        input_image_path=source,
        prompt="the woman waves and turns",
        negative_prompt="blurry",
        job_id=job,
        workflow_id=WAN_ANIMATE2_DRIVE_ID,
        workflow_version=version,
        requested_controls=tuple(
            sorted([CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT, CONTROL_POSE_VIDEO])
        ),
        experimental_opt_in=True,
    )


def test_the_speed_revision_launches_with_ck_attention_and_stays_warm_between_jobs(stack, tmp_path) -> None:
    backend, client, manager, children = stack

    for index in range(3):
        result = backend.execute(None, _request(tmp_path, WAN_ANIMATE2_SPEED_VERSION, f"job-{index}"))
        evidence = result.backend_metadata["comfy_attention"]
        assert evidence["profile"] == "ck" and evidence["dynamic_vram"] is True
        assert evidence["flags"] == [PINNED_MEMORY_FLAG, CK_ATTENTION_FLAG]
        assert CK_ATTENTION_FLAG in children[-1].command and PINNED_MEMORY_FLAG in children[-1].command
        release = result.backend_metadata["runtime_release"]
        assert release["policy"] == "keep_warm_between_jobs" and release["held"] is True
        assert release["idle_release_seconds"] == WAN_ANIMATE2_KEEP_WARM_SECONDS
        if index:
            assert result.backend_metadata["runtime_reuse"]["status"] == "warm"
    assert len(children) == 1 and not children[0].stopped
    assert len(client.queued) == 3
    # the saved launch command is never rewritten by the profile
    assert CK_ATTENTION_FLAG not in manager.config.command


def test_a_job_frozen_at_1_2_0_still_launches_cold_without_ck_and_is_not_kept_warm(stack, tmp_path) -> None:
    backend, _client, manager, children = stack

    for index in range(2):
        result = backend.execute(None, _request(tmp_path, WAN_ANIMATE2_RUNTIME_VERSION, f"old-{index}"))
        assert "comfy_attention" not in result.backend_metadata
        assert CK_ATTENTION_FLAG not in children[-1].command
        assert result.backend_metadata["runtime_release"]["released"] is True
        assert children[-1].stopped
    assert len(children) == 2
    assert CK_ATTENTION_FLAG not in manager.config.command


@pytest.mark.parametrize("first, second", [("1.3.0", "1.2.0"), ("1.2.0", "1.3.0")])
def test_switching_between_the_speed_revision_and_1_2_0_releases_and_relaunches(stack, tmp_path, first, second) -> None:
    backend, _client, _manager, children = stack

    for index, version in enumerate((first, first, second, second)):
        result = backend.execute(None, _request(tmp_path, version, f"job-{index}"))
        assert (CK_ATTENTION_FLAG in children[-1].command) is (version == "1.3.0")
        if index == 2 and first == "1.3.0":
            assert result.backend_metadata["runtime_reuse"]["status"] == "released"
            assert children[0].stopped
        if index == 1 and first == "1.3.0":
            assert result.backend_metadata["runtime_reuse"]["status"] == "warm"
    assert (CK_ATTENTION_FLAG in children[0].command) is (first == "1.3.0")
    assert (CK_ATTENTION_FLAG in children[-1].command) is (second == "1.3.0")


def test_an_unverified_ck_startup_cannot_dispatch_the_speed_revision(stack, tmp_path, monkeypatch) -> None:
    backend, client, manager, children = stack

    def no_ck_line(argv, **kwargs):
        child = _FakeManaged(argv, **kwargs)
        child._stderr = ["[INFO] DynamicVRAM support detected and enabled"]  # CK flag set, CK never selected
        children.append(child)
        return child

    manager._process_factory = no_ck_line
    with pytest.raises(ComfyStartupError, match="startup did not verify"):
        backend.execute(None, _request(tmp_path, WAN_ANIMATE2_SPEED_VERSION, "job-bad"))
    assert client.queued == []
