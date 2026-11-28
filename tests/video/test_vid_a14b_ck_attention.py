"""A14B launch-profile tests through the real queue, backend and manager with fake Comfy."""

from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
import requests
from PIL import Image

from src.app.site_phone_video import _phone_specs, make_video_spec
from src.controller.job_service import JobService
from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.video_workflow_controller import VideoWorkflowController
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot
from src.video.comfy_api_client import ComfyApiClient
from src.video.comfy_process_manager import (
    ComfyProcessConfig,
    ComfyProcessManager,
    ComfyStartupError,
    clear_global_comfy_process_manager,
)
from src.video.managed_comfy_runtime import CK_ATTENTION_FLAG, PINNED_MEMORY_FLAG
from src.video.video_execution_resolver import VideoExecutionResolver
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_CK_LAUNCH_ID,
    WAN_A14B_FULL_PICTURE_CK_VERSION,
    WAN_A14B_FULL_PICTURE_ID,
    WAN_A14B_FULL_PICTURE_STANDARD_ID,
    WAN_A14B_ID,
    WAN_A14B_VERSION,
    build_wan_a14b_specs,
)
from src.video.workflow_launch_attention import launch_attention
from src.video.workflow_picker import is_offered, picker_tier, workflow_choices
from src.video.workflow_registry import build_default_workflow_registry
from src.video.workflow_warnings import source_crop_warning
from tests.video.test_comfy_process_manager import (
    _FakeManaged,
    fake_comfy_command,
    fake_comfy_source,
)
from tests.video.test_vid_clip_370_candidate_specs import _a14b_backend, _a14b_request
from tests.video.test_vid_warm_373_a14b_reuse import _client, _slot
from tests.video.test_vid_warm_373_a14b_reuse import _no_encode as _no_encode

BASELINE = (WAN_A14B_ID, WAN_A14B_VERSION)
CK_480 = (WAN_A14B_CK_LAUNCH_ID, WAN_A14B_VERSION)
#: The Make Video default (owner decision 2026-11-28) and the standard-attention entry to switch back to.
DEFAULT_CK = (WAN_A14B_FULL_PICTURE_ID, WAN_A14B_FULL_PICTURE_CK_VERSION)
FALLBACK = (WAN_A14B_FULL_PICTURE_STANDARD_ID, WAN_A14B_VERSION)
FULL_1_0 = (WAN_A14B_FULL_PICTURE_ID, WAN_A14B_VERSION)
CK_PROFILES = (CK_480, DEFAULT_CK)


@pytest.fixture
def stack(tmp_path, monkeypatch):
    slot, _, _ = _slot()
    client = _client(tmp_path)
    backend = _a14b_backend(client, tmp_path, warm_hold=slot)
    command = fake_comfy_command(tmp_path / "runtime", PINNED_MEMORY_FLAG, CK_ATTENTION_FLAG)
    children = []

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
        ComfyProcessConfig(
            command=list(command), autostart_enabled=True, base_url="http://localhost:8188"
        ),
        process_factory=factory,
    )
    backend._process_manager = manager
    monkeypatch.setattr(
        "src.video.comfy_process_manager.probe_comfy_endpoint", lambda *_a, **_k: "free"
    )
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


def _run(backend, tmp_path, identity, job, *, opt_in=True):
    workflow_id, version = identity
    request = _a14b_request(tmp_path, workflow_id=workflow_id, version=version, opt_in=opt_in)
    request.job_id = job
    request.output_dir = tmp_path / job
    return backend.execute(None, request)


@pytest.mark.parametrize(
    "first, second",
    [
        (BASELINE, CK_480),
        (CK_480, BASELINE),
        (FALLBACK, DEFAULT_CK),
        (DEFAULT_CK, FALLBACK),
        (FULL_1_0, DEFAULT_CK),
        (DEFAULT_CK, FULL_1_0),
    ],
)
@pytest.mark.usefixtures("_no_encode")
def test_warm_reuse_and_switch_in_both_directions(stack, tmp_path, first, second):
    backend, client, manager, children = stack
    # A saved CK flag cannot override a frozen baseline choice.
    manager.config.command.append(CK_ATTENTION_FLAG)

    for index, identity in enumerate((first, first, second, second)):
        result = _run(backend, tmp_path, identity, f"job-{index}")
        ck = identity in CK_PROFILES
        evidence = result.backend_metadata["comfy_attention"]
        assert evidence["profile"] == ("ck" if ck else "baseline")
        assert evidence["dynamic_vram"] is True
        assert evidence["flags"] == (
            [PINNED_MEMORY_FLAG, CK_ATTENTION_FLAG] if ck else [PINNED_MEMORY_FLAG]
        )
        assert (CK_ATTENTION_FLAG in children[-1].command) is ck
        assert "--disable-dynamic-vram" not in children[-1].command
        if index == 2:
            assert result.backend_metadata["runtime_reuse"]["status"] == "released"
            assert children[0].stopped
        if index in {1, 3}:
            assert result.backend_metadata["runtime_reuse"]["status"] == "warm"
        assert len(children) == 1 + index // 2
    assert len(client.queued) == 4
    assert CK_ATTENTION_FLAG in manager.config.command


def _a14b_spec(identity):
    return next(
        spec
        for spec in build_wan_a14b_specs()
        if (spec.workflow_id, spec.workflow_version) == identity
    )


@pytest.mark.parametrize("ck_identity", CK_PROFILES)
@pytest.mark.parametrize("registered", [True, False])
def test_launch_proof_finds_ck_flag_on_comfys_attention_group(
    stack, tmp_path, registered, ck_identity
):
    """ComfyUI registers --use-ck-attention on ``attn_group``, not on ``parser`` itself."""

    backend, _client, _manager, children = stack
    ck_registration = f"attn_group.add_argument({CK_ATTENTION_FLAG!r}, action='store_true')\n"
    fake_comfy_source(
        tmp_path / "runtime",
        "parser.add_argument('--disable-pinned-memory', action='store_true')\n"
        "attn_group = parser.add_mutually_exclusive_group()\n"
        "attn_group.add_argument('--use-sage-attention', action='store_true')\n"
        + (ck_registration if registered else ""),
    )

    backend._verify_required_launch_flags(_a14b_spec(BASELINE))
    backend._verify_required_launch_flags(_a14b_spec(FALLBACK))
    if registered:
        backend._verify_required_launch_flags(_a14b_spec(ck_identity))
    else:
        with pytest.raises(ComfyStartupError, match="does not support --use-ck-attention"):
            backend._verify_required_launch_flags(_a14b_spec(ck_identity))

    assert children == []


@pytest.mark.parametrize(
    "fault, message",
    [
        ("reported_arguments", "owned launch arguments"),
        ("ck_startup_fallback", "startup did not verify"),
        ("dynamic_vram_unavailable", "startup did not verify"),
        ("dynamic_vram_disabled", "requires dynamic VRAM"),
        ("external", "external ComfyUI"),
        ("foreign_listener", "not served by the owned launch"),
        ("listener_changed", "not served by the owned launch"),
    ],
)
@pytest.mark.parametrize("identity", CK_PROFILES)
def test_unverified_profile_cannot_dispatch(stack, tmp_path, monkeypatch, fault, message, identity):
    backend, client, manager, children = stack
    get_stats = client.get_system_stats

    def foreign_listener(**_kwargs):
        return [
            SimpleNamespace(
                status=psutil.CONN_LISTEN,
                pid=99999,
                laddr=SimpleNamespace(ip="127.0.0.1", port=8188),
            )
        ]

    def report():
        stats = get_stats()
        if fault == "reported_arguments":
            stats["system"]["argv"].remove(CK_ATTENTION_FLAG)
        elif fault == "ck_startup_fallback":
            children[-1]._stderr.pop()
        elif fault == "dynamic_vram_unavailable":
            children[-1]._stderr.pop(0)
        elif fault == "listener_changed":
            monkeypatch.setattr(psutil, "net_connections", foreign_listener)
        return stats

    monkeypatch.setattr(client, "get_system_stats", report)
    if fault == "dynamic_vram_disabled":
        manager.config.command.append("--disable-dynamic-vram")
    if fault == "foreign_listener":
        monkeypatch.setattr(psutil, "net_connections", foreign_listener)
    if fault == "external":
        monkeypatch.setattr(
            "src.video.comfy_process_manager.probe_comfy_endpoint", lambda *_a, **_k: "healthy"
        )

    with pytest.raises(ComfyStartupError, match=message):
        _run(backend, tmp_path, identity, "refused")

    assert client.queued == []
    if fault in {"external", "dynamic_vram_disabled"}:
        assert children == []


@pytest.mark.usefixtures("_no_encode")
def test_failed_release_cannot_dispatch_in_other_mode(stack, tmp_path, monkeypatch):
    backend, client, manager, children = stack
    _run(backend, tmp_path, DEFAULT_CK, "ck")
    with pytest.raises(ComfyStartupError, match="job-specific CK"):
        manager.ensure_running()
    monkeypatch.setattr(children[0], "stop", lambda **_k: None)

    with pytest.raises(ComfyStartupError, match="attention profile 'baseline'"):
        _run(backend, tmp_path, FALLBACK, "baseline")

    assert len(children) == 1
    assert len(client.queued) == 1


@pytest.mark.parametrize(
    "identity, opted_in",
    [
        (BASELINE, False),
        (CK_480, True),
        (DEFAULT_CK, False),
        (FALLBACK, False),
    ],
)
def test_picker_submission_snapshot_and_history_replay(tmp_path: Path, identity, opted_in):
    workflow_id, version = identity
    db = tmp_path / "queue.db"
    repository = JobRepository(db)
    queue = JobQueue(repository=repository)
    service = JobService(queue)
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output")),
    )
    source = tmp_path / "reference.png"
    Image.new("RGB", (160, 90), "navy").save(source)
    form = controller.build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == DEFAULT_CK
    choices = {
        choice.workflow_id: choice for choice in workflow_choices(controller.list_workflow_specs())
    }
    assert choices[WAN_A14B_FULL_PICTURE_ID].recommended
    assert choices[WAN_A14B_CK_LAUNCH_ID].experimental
    assert "CK attention (Experimental)" in choices[WAN_A14B_CK_LAUNCH_ID].label
    form.update(
        workflow_id=workflow_id,
        workflow_version=version,
        prompt="turn toward the camera",
        seed=9,
        frame_count=17,
    )
    if opted_in:
        with pytest.raises(ValueError, match="experimental"):
            controller.submit_video_workflow_job(source_image_path=source, form_data=form)
        assert queue.list_jobs() == []
        form["experimental_opt_in"] = True
    parent_id = controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    form.update(
        workflow_id=WAN_A14B_ID,
        workflow_version=WAN_A14B_VERSION,
        experimental_opt_in=False,
        seed=21,
    )

    replay_ids = []

    def submit(records, **_kwargs):
        replay_ids.extend(service.submit_njrs(records))
        return len(records)

    assert (
        HistoryHandoffService().replay_job_from_history(
            job_id=parent_id,
            history_service=service._history_service,
            submit_normalized_jobs=submit,
        )
        == 1
    )
    [replay_id] = replay_ids
    assert replay_id != parent_id
    assert repository.get_lineage(replay_id) == (parent_id, None)
    assert [job.job_id for job in queue.list_jobs()] == [parent_id, replay_id]
    resolver = VideoExecutionResolver(None)
    for job_id in (parent_id, replay_id):
        record = normalized_job_from_snapshot(repository.get_job_model(job_id).snapshot)
        workflow = record.config["video_workflow"]
        intent = resolver.build_intent("video_workflow", workflow, has_source_image=True)
        assert (intent.workflow_id, intent.workflow_version) == identity
        assert intent.experimental_opt_in is opted_in
        assert workflow["seed"] == 9


def test_direct_profile_client_disables_environment_proxies_and_redirects(monkeypatch):
    observed = []

    def send(session, request, **kwargs):
        observed.append((session.trust_env, request.method, request.url, kwargs["allow_redirects"]))
        return SimpleNamespace(status_code=200, json=lambda: {"prompt_id": "fake"})

    monkeypatch.setattr(requests.Session, "send", send)
    client = ComfyApiClient(base_url="http://127.0.0.1:8188", direct=True)
    assert client.queue_prompt({"prompt": {}}) == {"prompt_id": "fake"}
    assert observed == [(False, "POST", "http://127.0.0.1:8188/prompt", False)]


# ---------------------------------------------------------------- CK is the Make Video default (2026-11-28)


def _registered(identity):
    return build_default_workflow_registry().get(*identity, allow_experimental=True)


def _assert_same_clip_settings(spec, other):
    """Only how attention is computed may differ: same graph, files, sizes, lengths and runtime policy."""

    assert spec.dependency_specs == other.dependency_specs
    assert spec.input_bindings == other.input_bindings
    for key in (
        "prompt_template",
        "source_preparation",
        "frame_count_policy",
        "runtime_policy",
        "resource_readiness",
    ):
        assert spec.backend_defaults[key] == other.backend_defaults[key], key


def test_the_make_video_default_is_full_picture_with_ck_attention():
    spec = _registered(DEFAULT_CK)

    assert spec.governance_state == "approved" and not spec.is_experimental
    assert spec.backend_defaults["make_video_default"] is True
    assert launch_attention(spec) == "ck"
    assert "full picture" in spec.display_name and "CK attention" in spec.display_name
    attention = spec.backend_defaults["operator_projection"]["fixed_settings"]["attention"]
    assert "Comfy Kitchen" in attention
    _assert_same_clip_settings(spec, _registered(FULL_1_0))
    phone = make_video_spec(_phone_specs(DefaultWorkflowRegistryPort()))
    assert phone is not None and phone.registry_key == DEFAULT_CK


def test_the_standard_attention_fallback_stays_selectable_without_any_switch():
    spec = _registered(FALLBACK)
    controller = VideoWorkflowController(
        app_controller=None, workflow_registry=DefaultWorkflowRegistryPort()
    )
    records = {item["workflow_id"]: item for item in controller.list_workflow_specs()}
    choices = {item.workflow_id: item for item in workflow_choices(records.values())}
    choice = choices[WAN_A14B_FULL_PICTURE_STANDARD_ID]

    assert spec.governance_state == "approved" and not spec.is_experimental
    assert spec.backend_defaults["make_video_default"] is False
    assert launch_attention(spec) == "baseline"
    _assert_same_clip_settings(spec, _registered(FULL_1_0))
    assert is_offered(records[WAN_A14B_FULL_PICTURE_STANDARD_ID], show_experimental=False)
    assert "standard attention" in choice.label and not choice.recommended
    assert source_crop_warning(spec, 500, 1500) is not None
    assert source_crop_warning(spec, 768, 1024) is None


def test_a_job_frozen_at_full_picture_1_0_0_keeps_standard_attention():
    assert launch_attention(_registered(FULL_1_0)) == "baseline"


def test_the_480x832_ck_profile_is_no_longer_called_unrated():
    record = {"workflow_id": WAN_A14B_CK_LAUNCH_ID, "governance_state": "experimental"}
    reason = picker_tier(record).reason

    assert "Unrated" not in reason and "full-picture" in reason


def test_every_attention_profile_workflow_is_verified_before_dispatch():
    """The backend verifies the serving attention inside the readiness step, so every profile needs one."""

    for spec in build_default_workflow_registry().list_offerable_specs("comfy"):
        if launch_attention(spec) is not None:
            assert spec.backend_defaults.get("resource_readiness"), spec.registry_key


def test_a_running_comfy_launched_without_ck_refuses_the_ck_default(stack, tmp_path):
    backend, client, manager, children = stack
    # Something else launched the owned ComfyUI without the CK argument and still holds it.
    manager.ensure_running(required_flags=(PINNED_MEMORY_FLAG,))

    with pytest.raises(ComfyStartupError, match="do not match attention profile 'ck'"):
        _run(backend, tmp_path, DEFAULT_CK, "refused")

    assert client.queued == []
    assert len(children) == 1 and CK_ATTENTION_FLAG not in children[0].command
