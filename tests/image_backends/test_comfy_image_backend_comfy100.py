"""PR-IMG-COMFY-100: the Comfy still-image backend's lease, ownership, probe, dispatch, observation, cancellation,
artifact and release contract, and the canonical ``run_njr`` route. Everything runs against in-memory fakes."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image

from src.api.http_transport import DispatchOutcomeUnknown
from src.controller.runtime_state import CancellationError
from src.image_backends import ImageBackendRegistry, ImageExecutionRequest
from src.image_backends.comfy_image_backend import (
    REQUIRED_LAUNCH_FLAGS,
    ComfyImageBackend,
    ComfyImageExecutionError,
    ComfyImageUnavailable,
)
from src.image_backends.comfy_image_graphs import QWEN_IMAGE_21_T2I, QWEN_IMAGE_21_TURBO_T2I
from src.image_backends.comfy_image_readiness import (
    ComfyImageResourceError,
    ComfyInstallationStatus,
)
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_21_PROFILE_V1 as BASE
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_21_TURBO_PROFILE_V1 as TURBO
from src.image_backends.comfy_qwen_image_profile import QwenImageProfileError
from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.pipeline_runner import PipelineRunner
from src.services.runtime_transition_service import RuntimeTransitionError, RuntimeTransitionStatus
from src.video.comfy_process_manager import ComfyStartupError
from tests.helpers.comfy_image_fakes import (
    GIB,
    FakeComfyClient,
    FakeManager,
    FakeTransition,
    Pipeline,
    Token,
    object_info,
    system_stats,
)


def options(profile=BASE) -> dict[str, Any]:
    return {"image": {"backend_id": "comfyui", "model_profile": profile.reference()}}


def make_backend(
    tmp_path: Path,
    client: FakeComfyClient | None = None,
    *,
    manager: FakeManager | None = None,
    transition: FakeTransition | None = None,
    installed: bool = True,
    timeout_after: int = 10_000,
) -> tuple[ComfyImageBackend, FakeComfyClient, FakeManager, FakeTransition]:
    client = client or FakeComfyClient()
    manager = manager or FakeManager()
    transition = transition or FakeTransition()
    status = (
        ComfyInstallationStatus(True, (), {"x": "y"}, sha256_verified=True)
        if installed
        else ComfyInstallationStatus(False, (f"Model missing: {BASE.model_name}",))
    )
    ticks = iter(range(0, timeout_after * 10, 1))
    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    backend = ComfyImageBackend(
        transition=transition,
        process_manager=manager,
        client_factory=lambda base_url: client,
        installation=lambda profile: status,
        clock=lambda: float(next(ticks)),
        sleep=lambda seconds: None,
        rng=random.Random(5),
        temp_root=str(jobs),
        poll_seconds=0,
    )
    return backend, client, manager, transition


def request(tmp_path: Path, profile=BASE, **changes: Any) -> ImageExecutionRequest:
    values: dict[str, Any] = {
        "backend_id": "comfyui",
        "stage_name": "txt2img",
        "stage_config": {"model": profile.model_name, "steps": profile.steps},
        "output_dir": tmp_path / "run" / "txt2img",
        "image_name": "txt2img_p01",
        "prompt": "A paper lantern floating on a lake.",
        "selected_model": profile.model_name,
        "steps": profile.steps,
        "cfg_scale": 1.0,
        "width": 1200,
        "height": 896,
        "seed": 1234,
        "image_count": 1,
        "job_id": "job-q1",
        "backend_options": options(profile),
        "cancel_token": Token(),
    }
    values.update(changes)
    return ImageExecutionRequest(**values)


@pytest.mark.parametrize("profile", [BASE, TURBO])
def test_successful_job_dispatches_once_and_publishes_one_provenanced_png(
    tmp_path: Path, profile
) -> None:
    backend, client, manager, transition = make_backend(tmp_path)
    pipeline = Pipeline()

    result = backend.execute(pipeline, request(tmp_path, profile))

    assert result is not None and transition.targets == ["comfy"]
    assert (
        manager.required == [REQUIRED_LAUNCH_FLAGS] and manager.stops == 1 and not manager.running
    )
    assert len(client.payloads) == 1
    payload = client.payloads[0]
    graph = QWEN_IMAGE_21_T2I if profile is BASE else QWEN_IMAGE_21_TURBO_T2I
    assert payload["extra_data"] == {"backend_id": "comfyui", **graph.reference()}
    assert payload["prompt"]["1"]["inputs"]["unet_name"] == profile.model_name
    assert payload["prompt"]["9"]["inputs"]["filename_prefix"] == "stablenew/job-q1/txt2img_p01"
    target = Path(result.primary_path or "")
    assert target.parent == tmp_path / "run" / "txt2img" and target.name == "txt2img_p01.png"
    with Image.open(target) as image:
        assert image.size == (1200, 896)
        assert image.info  # StableNew's embedded metadata contract
    manifest = json.loads(Path(result.manifest_path or "").read_text(encoding="utf-8"))
    assert (
        manifest["image_backend_id"] == "comfyui"
        and manifest["model_profile"] == profile.reference()
    )
    assert manifest["seed"] == 1234 and manifest["config"]["steps"] == profile.steps
    assert manifest["model_identity"]["files"][profile.model_name] == profile.diffusion_model.sha256
    qwen = manifest["qwen_image"]
    assert qwen["graph"] == graph.reference() and qwen["prompt_id"] == client.prompt_id
    assert qwen["actual_runtime"]["comfyui_version"] == "0.38.0"
    assert (
        qwen["floors"]["vram_free_bytes"] == 11 * GIB
        and qwen["installation"]["sha256_verified"] is True
    )
    assert len(qwen["submitted_graph_sha256"]) == 64 and "non-commercial" in qwen["licence"]
    assert result.backend_metadata["runtime_release"] == {
        "policy": "release_owned_runtime_after_job", "ownership": "owned", "pid": 4321, "released": True,
    }  # fmt: skip
    assert result.artifact["primary_path"] == str(target)
    assert not list((tmp_path / "jobs").iterdir())  # the job's download folder is removed


def test_a_random_seed_is_resolved_before_dispatch_and_recorded(tmp_path: Path) -> None:
    backend, client, *_ = make_backend(tmp_path)
    result = backend.execute(Pipeline(), request(tmp_path, seed=-1))
    sent = client.payloads[0]["prompt"]["7"]["inputs"]["seed"]
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert 0 <= sent < 2**32 and manifest["seed"] == sent and manifest["requested_seed"] == -1


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"stage_name": "img2img"}, "only txt2img"),
        ({"negative_prompt": "blurry"}, "negative prompt"),
        ({"input_image_path": Path("x.png")}, "no input image"),
        ({"width": 1024, "height": 768}, "supported sizes"),
        ({"steps": 30}, "steps 30"),
        ({"cfg_scale": 7.0}, "cfg_scale"),
        ({"image_count": 2}, "one image per job"),
        ({"prompt": "  "}, "needs a prompt"),
        ({"selected_model": "sdxl.safetensors"}, "exact model selection"),
        ({"backend_options": {"image": {"backend_id": "comfyui"}}}, "ordinary checkpoint"),
        ({"backend_options": {"image": {"backend_id": "comfyui", "model_profile": IDEOGRAM4_PROFILE_V1.reference()}}},
         "requires the 'diffusers' backend"),
    ],
)  # fmt: skip
def test_out_of_envelope_requests_are_refused_before_any_lease_or_runtime(
    tmp_path: Path, changes: dict[str, Any], fragment: str
) -> None:
    backend, client, manager, transition = make_backend(tmp_path)
    with pytest.raises(QwenImageProfileError, match=fragment):
        backend.execute(Pipeline(), request(tmp_path, **changes))
    assert transition.targets == [] and manager.required == [] and client.payloads == []


def test_missing_weights_refuse_before_the_lease(tmp_path: Path) -> None:
    backend, client, manager, transition = make_backend(tmp_path, installed=False)
    with pytest.raises(ComfyImageUnavailable, match="not installed: Model missing"):
        backend.execute(Pipeline(), request(tmp_path))
    assert transition.targets == [] and manager.required == []


def test_an_external_webui_occupant_refuses_before_comfy_starts(tmp_path: Path) -> None:
    backend, client, manager, _ = make_backend(
        tmp_path, transition=FakeTransition(RuntimeTransitionStatus.ACTION_REQUIRED)
    )
    with pytest.raises(RuntimeTransitionError):
        backend.execute(Pipeline(), request(tmp_path))
    assert manager.required == [] and client.payloads == [] and manager.stops == 0


def test_an_external_comfy_is_never_adopted_or_stopped(tmp_path: Path) -> None:
    backend, client, manager, _ = make_backend(tmp_path, manager=FakeManager(external=True))
    with pytest.raises(ComfyStartupError, match="refusing to adopt"):
        backend.execute(Pipeline(), request(tmp_path))
    assert client.payloads == [] and manager.stops == 0


def test_autostart_off_refuses_and_an_unhealthy_start_is_released(tmp_path: Path) -> None:
    backend, client, manager, _ = make_backend(tmp_path, manager=FakeManager(autostart=False))
    with pytest.raises(ComfyStartupError, match="automatic ComfyUI start is off"):
        backend.execute(Pipeline(), request(tmp_path))
    backend, client, manager, _ = make_backend(tmp_path, manager=FakeManager(healthy=False))
    with pytest.raises(ComfyStartupError, match="did not become healthy"):
        backend.execute(Pipeline(), request(tmp_path))
    assert client.payloads == []


@pytest.mark.parametrize(
    ("client", "error", "fragment"),
    [
        (
            FakeComfyClient(info=object_info(missing_class="QwenImage21Cache")),
            ComfyImageUnavailable,
            "QwenImage21Cache",
        ),
        (
            FakeComfyClient(info=object_info(drop_file=BASE.model_name)),
            ComfyImageUnavailable,
            "UNETLoader.unet_name",
        ),
        (
            FakeComfyClient(stats=system_stats(vram_free=3 * GIB)),
            ComfyImageResourceError,
            "free GPU memory",
        ),
        (
            FakeComfyClient(stats=system_stats(ram_free=2 * GIB)),
            ComfyImageResourceError,
            "free host RAM",
        ),
    ],
)
def test_probe_and_floor_failures_queue_nothing_and_release_the_owned_runtime(
    tmp_path: Path, client: FakeComfyClient, error: type[Exception], fragment: str
) -> None:
    backend, client, manager, _ = make_backend(tmp_path, client)
    with pytest.raises(error, match=fragment):
        backend.execute(Pipeline(), request(tmp_path))
    assert client.payloads == [] and manager.stops == 1 and not manager.running


def test_an_ambiguous_dispatch_is_never_replayed(tmp_path: Path) -> None:
    ambiguous = DispatchOutcomeUnknown(
        "POST /prompt: connection reset", method="POST", path="/prompt"
    )
    backend, client, manager, _ = make_backend(tmp_path, FakeComfyClient(queue_error=ambiguous))
    with pytest.raises(DispatchOutcomeUnknown):
        backend.execute(Pipeline(), request(tmp_path))
    assert len(client.payloads) == 1 and client.history_calls == 0 and manager.stops == 1


def test_a_missing_prompt_id_fails_without_polling(tmp_path: Path) -> None:
    backend, client, *_ = make_backend(tmp_path, FakeComfyClient(echo_prompt_id=False))
    with pytest.raises(ComfyImageExecutionError, match="no prompt id"):
        backend.execute(Pipeline(), request(tmp_path))
    assert client.history_calls == 0


def test_comfy_execution_errors_keep_their_detail(tmp_path: Path) -> None:
    failed = {
        "status": {
            "status_str": "error",
            "completed": False,
            "messages": [
                [
                    "execution_error",
                    {
                        "exception_type": "torch.OutOfMemoryError",
                        "exception_message": "CUDA out of memory",
                    },
                ]
            ],
        }
    }
    client = FakeComfyClient(history=[lambda pid: {pid: failed}])  # fmt: skip
    backend, client, manager, _ = make_backend(tmp_path, client)
    with pytest.raises(ComfyImageExecutionError, match="CUDA out of memory") as caught:
        backend.execute(Pipeline(), request(tmp_path))
    assert (
        caught.value.code == "execution_error" and manager.stops == 1 and len(client.payloads) == 1
    )


def test_liveness_is_reported_while_the_prompt_runs_without_inventing_progress(
    tmp_path: Path,
) -> None:
    running = {"status": {"status_str": "running", "completed": False}}
    done = FakeComfyClient().get_history  # default completion behaviour
    client = FakeComfyClient(
        history=[lambda pid: {}, lambda pid: {pid: running}, lambda pid: done(pid)]
    )
    backend, client, *_ = make_backend(tmp_path, client)
    pipeline = Pipeline()
    backend.execute(pipeline, request(tmp_path))
    assert pipeline.statuses and all("executing" in s["stage_detail"] for s in pipeline.statuses)
    assert all("progress" not in s and s["job_id"] == "job-q1" for s in pipeline.statuses)


def test_timeout_stops_this_prompt_and_fails(tmp_path: Path) -> None:
    client = FakeComfyClient(history=[lambda pid: {}], queue_state="running")
    backend, client, manager, _ = make_backend(tmp_path, client, timeout_after=100)
    with pytest.raises(ComfyImageExecutionError, match="took longer") as caught:
        backend.execute(Pipeline(), request(tmp_path))
    assert (
        caught.value.code == "timeout"
        and client.interrupted == [client.prompt_id]
        and manager.stops == 1
    )


@pytest.mark.parametrize(
    ("state", "interrupted", "deleted"), [("running", 1, 0), ("pending", 0, 1), (None, 0, 0)]
)
def test_cancellation_stops_only_this_prompt(
    tmp_path: Path, state, interrupted: int, deleted: int
) -> None:
    client = FakeComfyClient(history=[lambda pid: {}], queue_state=state)
    backend, client, manager, _ = make_backend(tmp_path, client)
    token = Token(
        after_polls=2
    )  # passes the pre-start and pre-dispatch checks, then cancels inside the wait
    with pytest.raises(CancellationError):
        backend.execute(Pipeline(), request(tmp_path, cancel_token=token))
    assert len(client.interrupted) == interrupted and len(client.deleted) == deleted
    if interrupted:
        assert client.interrupted == [client.prompt_id]
    assert manager.stops == 1 and len(client.payloads) == 1


def test_cancellation_before_start_touches_nothing(tmp_path: Path) -> None:
    backend, client, manager, transition = make_backend(tmp_path)
    with pytest.raises(CancellationError):
        backend.execute(Pipeline(), request(tmp_path, cancel_token=Token(cancelled=True)))
    assert transition.targets == [] and manager.required == [] and client.payloads == []


@pytest.mark.parametrize(
    ("client", "code"),
    [
        (FakeComfyClient(output_count=0), "wrong_output_count"),
        (FakeComfyClient(output_count=2), "wrong_output_count"),
        (FakeComfyClient(image_size=(1024, 1024)), "wrong_output_size"),
    ],
)
def test_wrong_outputs_fail_and_publish_nothing(
    tmp_path: Path, client: FakeComfyClient, code: str
) -> None:
    backend, client, manager, _ = make_backend(tmp_path, client)
    with pytest.raises(ComfyImageExecutionError) as caught:
        backend.execute(Pipeline(), request(tmp_path))
    assert caught.value.code == code and manager.stops == 1
    assert not (tmp_path / "run" / "txt2img").exists() or not list(
        (tmp_path / "run" / "txt2img").glob("*.png")
    )


def test_registry_rejects_extra_stages_and_the_backend_rejects_foreign_njr_intent(
    tmp_path: Path,
) -> None:
    backend, *_ = make_backend(tmp_path)
    registry = ImageBackendRegistry()
    registry.register(backend)
    with pytest.raises(ValueError, match="does not support stage chain: adetailer"):
        registry.validate_stage_chain("comfyui", ["txt2img", "adetailer"])
    njr = Mock(base_model="sdxl.safetensors", backend_options={"image": {"backend_id": "comfyui"}})
    with pytest.raises(QwenImageProfileError, match="ordinary checkpoint"):
        backend.validate_njr_intent(njr, ["txt2img"])


class _NoWebUIPipeline:
    def __init__(self) -> None:
        self.client = None

    def _begin_run_metrics(self) -> None:
        return None

    def get_run_efficiency_metrics(self, _variant_count: int) -> dict[str, object]:
        return {}


@pytest.mark.parametrize("profile", [BASE, TURBO])
def test_canonical_run_njr_dispatches_to_comfy_without_any_webui_call(
    tmp_path: Path, profile
) -> None:
    config = {
        "model": profile.model_name,
        "prompt": "A ceramic teapot on a wooden table.",
        "seed": 5,
        "width": 1024,
        "height": 1024,
        "negative_prompt": "",
        "prompt_optimizer": {"enabled": False},
    }
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "qwen-e2e").build_jobs(
        base_config=config
    )[0]
    assert record.backend_options["image"] == {
        "backend_id": "comfyui",
        "model_profile": profile.reference(),
    }

    backend, client, manager, _ = make_backend(tmp_path)
    registry = ImageBackendRegistry()
    registry.register(backend)
    webui = Mock()
    runner = PipelineRunner(
        webui, Mock(), runs_base_dir=str(tmp_path / "runs"), image_backend_registry=registry
    )
    runner._pipeline = _NoWebUIPipeline()

    result = runner.run_njr(record)

    assert result.success is True, result.error
    assert result.metadata["image_backend_id"] == "comfyui"
    assert len(client.payloads) == 1 and Path(result.output_paths[0]).is_file()
    assert client.payloads[0]["prompt"]["7"]["inputs"].get("seed", client.payloads[0]["prompt"]["7"]["inputs"].get(
        "noise_seed")) == 5  # fmt: skip
    assert webui.method_calls == [] and runner._pipeline.client is None
    assert manager.stops == 1


def test_the_registered_comfy_owner_wins_and_construction_stays_in_the_video_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.video.comfy_process_manager as manager_module
    import src.video.comfy_workflow_backend as video_backend

    remembered, live, constructed = FakeManager(), FakeManager(), FakeManager()
    built: list[str] = []
    monkeypatch.setattr(manager_module, "get_global_comfy_process_manager", lambda: None)
    monkeypatch.setattr(
        video_backend, "shared_comfy_process_manager", lambda: built.append("x") or constructed
    )
    backend = ComfyImageBackend(transition=FakeTransition())
    assert backend._resolve_process_manager() is constructed and built == ["x"]
    backend._process_manager = remembered
    assert backend._resolve_process_manager() is remembered and built == ["x"]
    # Another feature (video) holds the live owner: use it rather than launching a second manager on its port.
    monkeypatch.setattr(manager_module, "get_global_comfy_process_manager", lambda: live)
    assert backend._resolve_process_manager() is live
    monkeypatch.setattr(video_backend, "shared_comfy_process_manager", lambda: None)
    monkeypatch.setattr(manager_module, "get_global_comfy_process_manager", lambda: None)
    with pytest.raises(ComfyImageUnavailable, match="launch configuration"):
        ComfyImageBackend(transition=FakeTransition())._resolve_process_manager()


def test_shared_comfy_process_manager_reuses_the_global_owner_or_builds_from_the_default_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.video.comfy_workflow_backend as video_backend

    owner = object()
    monkeypatch.setattr(video_backend, "get_global_comfy_process_manager", lambda: owner)
    assert video_backend.shared_comfy_process_manager() is owner
    monkeypatch.setattr(video_backend, "get_global_comfy_process_manager", lambda: None)
    monkeypatch.setattr(video_backend, "build_default_comfy_process_config", lambda: None)
    assert video_backend.shared_comfy_process_manager() is None
    monkeypatch.setattr(video_backend, "build_default_comfy_process_config", lambda: "config")
    monkeypatch.setattr(video_backend, "ComfyProcessManager", lambda config: ("manager", config))
    assert video_backend.shared_comfy_process_manager() == ("manager", "config")
