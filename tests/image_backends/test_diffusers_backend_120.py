"""PR-IMG-120: the Diffusers backend's lease, floors, contained-child, teardown and artifact contract.

The child is run in-process by a fake ``run_bounded`` that calls the real ``run_job`` with hermetic fakes, so the whole
parent/child file protocol is exercised without starting a process, importing torch or touching a GPU.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError
from src.image_backends import ImageBackendRegistry, ImageExecutionRequest
from src.image_backends.diffusers_backend import (
    DiffusersImageBackend,
    Ideogram4ExecutionError,
    Ideogram4ResourceError,
    Ideogram4Unavailable,
    child_environment,
)
from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1 as P
from src.image_backends.diffusers_ideogram4_profile import Ideogram4ProfileError
from src.image_backends.diffusers_ideogram4_worker import run_job
from src.image_backends.diffusers_readiness import GpuMemory, InstallationStatus
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.pipeline_runner import PipelineRunner
from src.services.runtime_transition_service import (
    RuntimeOwnershipState,
    RuntimeTransitionError,
    RuntimeTransitionResult,
    RuntimeTransitionStatus,
)
from src.utils.managed_process import ProcessOutcome
from src.utils.process_observation import OwnedTreeEvidence
from tests.helpers.ideogram4_fakes import FakeWorld, fake_loader

GIB = 1024**3
PROFILE_OPTIONS = {"image": {"backend_id": "diffusers", "model_profile": P.reference()}}


class FakeTransition:
    def __init__(self, status: RuntimeTransitionStatus = RuntimeTransitionStatus.READY) -> None:
        self.status = status
        self.targets: list[str] = []

    def prepare_for(self, target: str) -> RuntimeTransitionResult:
        self.targets.append(target)
        blockers = (
            ("external Forge WebUI on port 7860",)
            if self.status is not RuntimeTransitionStatus.READY
            else ()
        )
        return RuntimeTransitionResult(
            target=target,
            conflicts_observed=("forge_webui",),
            ownership_state={"forge_webui": RuntimeOwnershipState.OWNED},
            releases_attempted=("forge_webui",),
            releases_completed=("forge_webui",) if not blockers else (),
            status=self.status,
            blockers=blockers,
        )


def ownership(active_after_teardown: int = 0) -> OwnedTreeEvidence:
    return OwnedTreeEvidence(
        root_pid=4242,
        events=(),
        total_processes=1,
        survivors_at_end=active_after_teardown,
        runner_terminated_survivors=False,
        active_after_teardown=active_after_teardown,
        io_read_bytes=0,
        io_write_bytes=0,
        io_other_bytes=0,
        complete=active_after_teardown == 0,
    )


class FakeRunner:
    """Stands in for ``run_bounded``: records the launch, then runs the real child entry point in-process."""

    def __init__(self, world: FakeWorld | None = None, **outcome: Any) -> None:
        self.world = world or FakeWorld()
        self.outcome = outcome
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.run_child = True

    def __call__(self, args: list[str], **kwargs: Any) -> ProcessOutcome:
        self.calls.append((list(args), kwargs))
        if kwargs["cancel"]():
            return ProcessOutcome(
                returncode=None, cancelled=True, contained=True, ownership=ownership()
            )
        returncode = 0
        if (
            self.run_child
            and not self.outcome.get("launch_error")
            and not self.outcome.get("timed_out")
        ):
            returncode = run_job(
                Path(args[3]), loader=fake_loader(self.world), missing_runtime=lambda: []
            )
            kwargs["cancel"]()  # one more poll after the child wrote its last progress event
        fields = {
            "returncode": returncode,
            "contained": True,
            "memory_limit_enforced": True,
            "ownership": ownership(),
            **self.outcome,
        }
        return ProcessOutcome(**fields)


class Token:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self.cancelled


class Pipeline:
    def __init__(self) -> None:
        self.statuses: list[dict[str, Any]] = []

    def _emit_status_update(self, status: dict[str, Any]) -> None:
        self.statuses.append(status)


def backend(
    tmp_path: Path,
    runner: FakeRunner | None = None,
    *,
    transition: FakeTransition | None = None,
    ready: bool = True,
    free_mib: int = 11_500,
    host_ram: int = 40 * GIB,
    gpu_error: bool = False,
) -> DiffusersImageBackend:
    def gpu() -> GpuMemory:
        if gpu_error:
            raise RuntimeError("nvidia-smi missing")
        return GpuMemory(free_mib, 12_282 - free_mib, 12_282)

    status = (
        InstallationStatus(True, (), tmp_path / "snapshot")
        if ready
        else InstallationStatus(False, ("Python package 'bitsandbytes' is not installed",), None)
    )
    temp_root = tmp_path / "jobs"
    temp_root.mkdir(exist_ok=True)
    return DiffusersImageBackend(
        transition=transition or FakeTransition(),
        installation=lambda: status,
        gpu_memory=gpu,
        host_ram_bytes=lambda: host_ram,
        process_runner=runner or FakeRunner(),
        interpreter="python-test",
        temp_root=str(temp_root),
        clock=iter(range(0, 100_000, 2)).__next__,
        rng=random.Random(3),
    )


def request(tmp_path: Path, **changes: Any) -> ImageExecutionRequest:
    values: dict[str, Any] = {
        "backend_id": "diffusers",
        "stage_name": "txt2img",
        "stage_config": {"model": P.model_name, "steps": 12},
        "output_dir": tmp_path / "run" / "txt2img",
        "image_name": "txt2img_p01",
        "prompt": "A teapot on a table.",
        "selected_model": P.model_name,
        "steps": 12,
        "width": 512,
        "height": 512,
        "seed": 100,
        "image_count": 2,
        "job_id": "job-i4",
        "backend_options": PROFILE_OPTIONS,
        "cancel_token": Token(),
    }
    values.update(changes)
    return ImageExecutionRequest(**values)


def test_successful_job_leases_launches_contained_and_publishes_artifacts(tmp_path: Path) -> None:
    runner, transition, pipeline = FakeRunner(), FakeTransition(), Pipeline()
    result = backend(tmp_path, runner, transition=transition).execute(pipeline, request(tmp_path))

    assert transition.targets == ["diffusers"]
    ((args, kwargs),) = runner.calls
    assert args[:3] == [
        "python-test",
        "-I",
        str(Path("src/image_backends/diffusers_ideogram4_worker.py").resolve()),
    ]
    assert kwargs["memory_limit_mb"] == 36_864 and kwargs["record_ownership"] is True
    assert kwargs["timeout_seconds"] == 300 + 2 * 12 * 20
    assert kwargs["env"]["HF_HUB_OFFLINE"] == "1" and kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"

    assert result.backend_id == "diffusers" and len(result.output_paths) == 2
    raw = result.raw_result
    assert raw["all_seeds"] == [100, 101] and raw["image_backend_id"] == "diffusers"
    assert raw["model_profile"] == P.reference()
    for path, seed in zip(result.output_paths, (100, 101), strict=True):
        with Image.open(path) as image:
            assert image.size == (512, 512) and image.getpixel((0, 0))[0] == seed
            assert any("stablenew" in key.lower() for key in image.info)
        manifest = json.loads(
            (Path(path).parent / "manifests" / f"{Path(path).stem}.json").read_text(
                encoding="utf-8"
            )
        )
        block = manifest["ideogram4"]
        assert (
            manifest["seed"] == seed
            and block["preset"] == "V4_TURBO_12"
            and block["caption_mode"] == "automatic"
        )
        assert block["caption_mapping_version"] == 1 and block["max_resident_transformers"] == 1
        assert block["lease"]["status"] == "ready" and block["floors"]["free_vram_mib"] == 11_500
        assert (
            block["teardown"]["active_after_teardown"] == 0
            and block["teardown"]["ownership_complete"] is True
        )
        assert block["teardown"]["post_exit_vram"]["free_mib"] == 11_500
    assert [Path(p).name for p in result.output_paths] == [
        "txt2img_p01_batch0.png",
        "txt2img_p01_batch1.png",
    ]
    # The temporary job directory is always removed; progress reached the runner's status channel.
    assert list((tmp_path / "jobs").iterdir()) == []
    details = [s.get("stage_detail") for s in pipeline.statuses]
    assert "Ideogram 4: image 2/2, step 12/12" in details
    assert pipeline.statuses[-1]["progress"] == 1.0


def test_an_external_gpu_occupant_refuses_before_anything_is_launched(tmp_path: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(RuntimeTransitionError, match="external Forge WebUI"):
        backend(
            tmp_path, runner, transition=FakeTransition(RuntimeTransitionStatus.ACTION_REQUIRED)
        ).execute(Pipeline(), request(tmp_path))
    assert runner.calls == []


@pytest.mark.parametrize(
    ("kwargs", "error", "fragment"),
    [
        ({"ready": False}, Ideogram4Unavailable, "bitsandbytes"),
        ({"free_mib": 9_000}, Ideogram4ResourceError, "needs 10700 MiB"),
        ({"gpu_error": True}, Ideogram4ResourceError, "could not read free GPU memory"),
        ({"host_ram": 8 * GIB}, Ideogram4ResourceError, "available host RAM"),
    ],
)
def test_installation_and_resource_floors_refuse_before_launch(
    tmp_path: Path, kwargs, error, fragment
) -> None:
    runner = FakeRunner()
    with pytest.raises(error, match=fragment):
        backend(tmp_path, runner, **kwargs).execute(Pipeline(), request(tmp_path))
    assert runner.calls == []


def test_cancellation_before_launch_and_during_the_child(tmp_path: Path) -> None:
    runner = FakeRunner()
    with pytest.raises(CancellationError):
        backend(tmp_path, runner).execute(Pipeline(), request(tmp_path, cancel_token=Token(True)))
    assert runner.calls == []

    class LateToken:
        calls = 0

        def is_cancelled(self) -> bool:
            LateToken.calls += 1
            return (
                LateToken.calls > 2
            )  # passes both pre-launch checks, cancels at the first child poll

    with pytest.raises(CancellationError, match="model process was stopped"):
        backend(tmp_path, runner).execute(Pipeline(), request(tmp_path, cancel_token=LateToken()))
    assert list((tmp_path / "jobs").iterdir()) == []


@pytest.mark.parametrize(
    ("runner_kwargs", "world", "code"),
    [
        ({"launch_error": "CreateProcess failed"}, None, "launch_error"),
        ({"timed_out": True, "returncode": None}, None, "timeout"),
        ({}, FakeWorld(oom_on_step=2), "out_of_memory"),
        ({}, FakeWorld(fail_on_step=1), "failed"),
        ({}, FakeWorld(token_count=5000), "caption_too_long"),
        ({"ownership": ownership(active_after_teardown=1)}, None, "teardown_unproven"),
    ],
)
def test_child_failures_are_typed_and_never_reported_clean(
    tmp_path: Path, runner_kwargs, world, code
) -> None:
    runner = FakeRunner(world, **runner_kwargs)
    with pytest.raises(Ideogram4ExecutionError) as raised:
        backend(tmp_path, runner).execute(Pipeline(), request(tmp_path))
    assert raised.value.code == code
    assert list((tmp_path / "jobs").iterdir()) == []
    assert not (tmp_path / "run" / "txt2img").exists() or not list(
        (tmp_path / "run" / "txt2img").glob("*.png")
    )


def test_a_child_that_exits_without_a_result_is_a_failure(tmp_path: Path) -> None:
    runner = FakeRunner(returncode=1, stderr=b"Traceback: boom")
    runner.run_child = False
    with pytest.raises(Ideogram4ExecutionError, match="no readable result") as raised:
        backend(tmp_path, runner).execute(Pipeline(), request(tmp_path))
    assert raised.value.code == "failed" and "boom" in str(raised.value)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"stage_name": "img2img"}, "only txt2img"),
        ({"backend_options": {"image": {"backend_id": "diffusers"}}}, "runs only Ideogram 4"),
        ({"selected_model": "sdxl.safetensors"}, "exact model selection"),
        ({"negative_prompt": "blurry"}, "negative prompt is unsupported"),
        ({"input_image_path": Path("in.png")}, "takes no input image"),
        ({"prompt": "{broken"}, "not a valid JSON object"),
        ({"steps": 30}, "steps must be one of"),
        ({"width": 2048, "height": 2048}, "outside the tested sizes"),
        ({"image_count": 6}, "1-4 images"),
    ],
)
def test_request_validation_refuses_before_the_lease(tmp_path: Path, changes, fragment) -> None:
    transition, runner = FakeTransition(), FakeRunner()
    with pytest.raises(Ideogram4ProfileError) as raised:
        backend(tmp_path, runner, transition=transition).execute(
            Pipeline(), request(tmp_path, **changes)
        )
    assert fragment in str(raised.value)
    assert transition.targets == [] and runner.calls == []


def test_child_environment_is_an_allowlist_with_forced_offline_settings() -> None:
    env = child_environment(
        {
            "PATH": "p",
            "HF_HOME": "h",
            "HF_TOKEN": "secret",
            "OPENAI_API_KEY": "x",
            "HF_HUB_OFFLINE": "0",
        }
    )
    assert env["PATH"] == "p" and env["HF_HOME"] == "h"
    assert "HF_TOKEN" not in env and "OPENAI_API_KEY" not in env
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"


class _NoWebUIPipeline:
    def __init__(self) -> None:
        self.client = None

    def _begin_run_metrics(self) -> None:
        return None

    def get_run_efficiency_metrics(self, _variant_count: int) -> dict[str, object]:
        return {}


def test_canonical_run_njr_dispatches_to_diffusers_without_any_webui_call(tmp_path: Path) -> None:
    config = {
        "model": P.model_name,
        "prompt": "A ceramic teapot.",
        "seed": 5,
        "steps": 12,
        "width": 512,
        "height": 512,
        "negative_prompt": "",
        "prompt_optimizer": {"enabled": False},
    }
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "i4-e2e").build_jobs(base_config=config)[
        0
    ]
    assert record.backend_options["image"]["backend_id"] == "diffusers"

    runner_fake = FakeRunner()
    registry = ImageBackendRegistry()
    registry.register(backend(tmp_path, runner_fake))
    webui = Mock()
    pipeline_runner = PipelineRunner(
        webui, Mock(), runs_base_dir=str(tmp_path / "runs"), image_backend_registry=registry
    )
    pipeline_runner._pipeline = _NoWebUIPipeline()

    result = pipeline_runner.run_njr(record)

    assert result.success is True, result.error
    assert result.metadata["image_backend_id"] == "diffusers"
    assert len(runner_fake.calls) == 1 and Path(result.output_paths[0]).is_file()
    # No WebUI client was used: neither the job-start VRAM cleanup nor any generation call.
    assert webui.method_calls == []
    assert pipeline_runner._pipeline.client is None
