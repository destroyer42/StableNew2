"""A14B launch-profile tests through the real queue, backend and manager with fake Comfy."""

from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
import requests
from PIL import Image

from src.controller.job_service import JobService
from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
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
    WAN_A14B_ID,
    WAN_A14B_VERSION,
    build_wan_a14b_specs,
)
from src.video.workflow_picker import workflow_choices
from tests.video.test_comfy_process_manager import (
    _FakeManaged,
    fake_comfy_command,
    fake_comfy_source,
)
from tests.video.test_vid_clip_370_candidate_specs import _a14b_backend, _a14b_request
from tests.video.test_vid_warm_373_a14b_reuse import _client, _slot
from tests.video.test_vid_warm_373_a14b_reuse import _no_encode as _no_encode


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
    request = _a14b_request(tmp_path, workflow_id=identity, opt_in=opt_in)
    request.job_id = job
    request.output_dir = tmp_path / job
    return backend.execute(None, request)


@pytest.mark.parametrize(
    "first, second",
    [
        (WAN_A14B_ID, WAN_A14B_CK_LAUNCH_ID),
        (WAN_A14B_CK_LAUNCH_ID, WAN_A14B_ID),
    ],
)
@pytest.mark.usefixtures("_no_encode")
def test_warm_reuse_and_switch_in_both_directions(stack, tmp_path, first, second):
    backend, client, manager, children = stack
    # A saved CK flag cannot override a frozen baseline choice.
    manager.config.command.append(CK_ATTENTION_FLAG)

    for index, workflow_id in enumerate((first, first, second, second)):
        result = _run(backend, tmp_path, workflow_id, f"job-{index}")
        ck = workflow_id == WAN_A14B_CK_LAUNCH_ID
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


def _a14b_spec(workflow_id):
    return next(
        spec
        for spec in build_wan_a14b_specs()
        if (spec.workflow_id, spec.workflow_version) == (workflow_id, WAN_A14B_VERSION)
    )


@pytest.mark.parametrize("registered", [True, False])
def test_launch_proof_finds_ck_flag_on_comfys_attention_group(stack, tmp_path, registered):
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

    backend._verify_required_launch_flags(_a14b_spec(WAN_A14B_ID))
    if registered:
        backend._verify_required_launch_flags(_a14b_spec(WAN_A14B_CK_LAUNCH_ID))
    else:
        with pytest.raises(ComfyStartupError, match="does not support --use-ck-attention"):
            backend._verify_required_launch_flags(_a14b_spec(WAN_A14B_CK_LAUNCH_ID))

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
def test_unverified_profile_cannot_dispatch(stack, tmp_path, monkeypatch, fault, message):
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
        _run(backend, tmp_path, WAN_A14B_CK_LAUNCH_ID, "refused")

    assert client.queued == []
    if fault in {"external", "dynamic_vram_disabled"}:
        assert children == []


@pytest.mark.usefixtures("_no_encode")
def test_failed_release_cannot_dispatch_in_other_mode(stack, tmp_path, monkeypatch):
    backend, client, manager, children = stack
    _run(backend, tmp_path, WAN_A14B_CK_LAUNCH_ID, "ck")
    with pytest.raises(ComfyStartupError, match="job-specific CK"):
        manager.ensure_running()
    monkeypatch.setattr(children[0], "stop", lambda **_k: None)

    with pytest.raises(ComfyStartupError, match="attention profile 'baseline'"):
        _run(backend, tmp_path, WAN_A14B_ID, "baseline")

    assert len(children) == 1
    assert len(client.queued) == 1


@pytest.mark.parametrize(
    "workflow_id, opted_in",
    [
        (WAN_A14B_ID, False),
        (WAN_A14B_CK_LAUNCH_ID, True),
    ],
)
def test_picker_submission_snapshot_and_history_replay(tmp_path: Path, workflow_id, opted_in):
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
    assert (form["workflow_id"], form["workflow_version"]) == (WAN_A14B_ID, WAN_A14B_VERSION)
    choices = {
        choice.workflow_id: choice for choice in workflow_choices(controller.list_workflow_specs())
    }
    assert choices[WAN_A14B_ID].recommended
    assert choices[WAN_A14B_CK_LAUNCH_ID].experimental
    assert "CK attention (Experimental)" in choices[WAN_A14B_CK_LAUNCH_ID].label
    form.update(workflow_id=workflow_id, prompt="turn toward the camera", seed=9, frame_count=17)
    if opted_in:
        with pytest.raises(ValueError, match="experimental"):
            controller.submit_video_workflow_job(source_image_path=source, form_data=form)
        assert queue.list_jobs() == []
        form["experimental_opt_in"] = True
    parent_id = controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    form.update(workflow_id=WAN_A14B_ID, experimental_opt_in=False, seed=21)

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
        assert (intent.workflow_id, intent.workflow_version) == (workflow_id, WAN_A14B_VERSION)
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
