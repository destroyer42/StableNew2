from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.services.operator_readiness_service import (
    OperatorReadinessService,
    OperatorReadinessState,
    ProductSupportState,
)
from src.video.svd_capabilities import SVDPreflight
from src.video.svd_config import SVDConfig


@dataclass
class _Metadata:
    last_control_action: str | None = None


@dataclass
class _Job:
    execution_metadata: _Metadata


class _Repository:
    def __init__(self, *, count: int = 0, jobs: list[_Job] | None = None) -> None:
        self._count = count
        self._jobs = list(jobs or [])
        self.submission_calls = 0
        self.recovery_calls = 0

    def count(self) -> int:
        return self._count

    def list_job_models(self) -> list[_Job]:
        return list(self._jobs)

    def submit(self, *_args, **_kwargs) -> None:
        self.submission_calls += 1
        raise AssertionError("Readiness must not submit queue work")

    def recover_interrupted_jobs(self) -> None:
        self.recovery_calls += 1
        raise AssertionError("Readiness must not mutate recovery state")


class _WebUIConnection:
    def __init__(self, state: str, error: str | None = None) -> None:
        self._state = state
        self.last_readiness_error = error
        self.probe_calls = 0

    def get_state(self) -> str:
        return self._state

    def is_webui_ready_strict(self) -> bool:
        self.probe_calls += 1
        raise AssertionError("Readiness must use the existing connection state, not probe independently")


def _preflight(
    *,
    blockers: tuple[str, ...] = ("Select a source image.",),
    cached: bool = True,
    source_path: str | None = None,
    source_valid: bool | None = None,
) -> SVDPreflight:
    return SVDPreflight(
        available=not blockers,
        blocking_reasons=blockers,
        warnings=(),
        model_id="stabilityai/stable-video-diffusion-img2vid-xt",
        model_supported=True,
        model_cached=cached,
        local_files_only=True,
        cache_dir="C:/cache/svd",
        torch_available=True,
        diffusers_available=True,
        pipeline_available=True,
        cuda_available=True,
        gpu_name="Test GPU",
        gpu_memory_gb=12.0,
        core_summary="Accepted SVD baseline.",
        source_image_path=source_path,
        source_image_valid=source_valid,
    )


def _service(
    tmp_path: Path,
    *,
    repository: _Repository | None = None,
    webui: _WebUIConnection | None = None,
    preflight: SVDPreflight | None = None,
    ffmpeg: Path | None | object = ...,
    path_probe=None,
) -> OperatorReadinessService:
    packs = tmp_path / "packs"
    output = tmp_path / "output"
    packs.mkdir()
    output.mkdir()
    resolved_ffmpeg = tmp_path / "ffmpeg.exe" if ffmpeg is ... else ffmpeg
    return OperatorReadinessService(
        repository=repository or _Repository(),
        webui_connection=webui or _WebUIConnection("ready"),
        prompt_pack_dir_provider=lambda: packs,
        output_dir_provider=lambda: output,
        svd_config_provider=SVDConfig,
        svd_preflight_provider=lambda _config, *, source_image_path=None: preflight
        or _preflight(source_path=source_image_path),
        ffmpeg_resolver=lambda: resolved_ffmpeg,
        path_probe=path_probe,
    )


def test_support_policy_is_deterministic_and_only_accepted_journeys_are_supported(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).collect()

    support = {item.id: item.state for item in snapshot.support_surfaces}
    assert support["a1111_still_image"] is ProductSupportState.SUPPORTED
    assert support["native_svd_xt"] is ProductSupportState.SUPPORTED
    assert support["pipeline"] is ProductSupportState.SUPPORTED
    assert support["movie_clips"] is ProductSupportState.ADVANCED_OR_UNVERIFIED
    assert support["character_training"] is ProductSupportState.ADVANCED_OR_UNVERIFIED
    assert ProductSupportState.DEFERRED.value == "deferred"


def test_ready_webui_and_svd_runtime_are_truthful_when_source_is_not_selected(tmp_path: Path) -> None:
    webui = _WebUIConnection("ready")
    snapshot = _service(tmp_path, webui=webui).collect()

    assert snapshot.record_for("webui").state is OperatorReadinessState.READY
    assert snapshot.record_for("native_svd_runtime").state is OperatorReadinessState.READY
    assert snapshot.record_for("svd_source_image").state is OperatorReadinessState.OPTIONAL
    assert webui.probe_calls == 0


def test_unavailable_webui_projects_existing_connection_authority(tmp_path: Path) -> None:
    snapshot = _service(
        tmp_path,
        webui=_WebUIConnection("error", "port 127.0.0.1:7860 not listening"),
    ).collect()

    record = snapshot.record_for("webui")
    assert record.state is OperatorReadinessState.ACTION_REQUIRED
    assert record.blocking_reasons == ("port 127.0.0.1:7860 not listening",)
    assert record.source == "WebUIConnectionController"


def test_missing_local_svd_cache_is_action_required_without_blurring_source_state(tmp_path: Path) -> None:
    preflight = _preflight(
        blockers=(
            "Select a source image.",
            "Local-only mode requires a complete cached SVD model at 'C:/cache/svd'.",
        ),
        cached=False,
    )
    snapshot = _service(tmp_path, preflight=preflight).collect()

    runtime = snapshot.record_for("native_svd_runtime")
    assert runtime.state is OperatorReadinessState.ACTION_REQUIRED
    assert runtime.blocking_reasons == (preflight.blocking_reasons[1],)
    assert "local cache" in runtime.operator_actions[0].lower()
    assert snapshot.record_for("svd_source_image").state is OperatorReadinessState.OPTIONAL


def test_missing_ffmpeg_is_action_required_for_video_export(tmp_path: Path) -> None:
    snapshot = _service(tmp_path, ffmpeg=None).collect()

    record = snapshot.record_for("ffmpeg")
    assert record.state is OperatorReadinessState.ACTION_REQUIRED
    assert "FFmpeg" in record.blocking_reasons[0]
    assert "STABLENEW_FFMPEG_PATH" in record.operator_actions[0]


def test_promptpack_and_output_failures_are_projected_without_writes(tmp_path: Path) -> None:
    def failing_probe(path: Path) -> tuple[bool, str | None]:
        return False, f"not writable: {path.name}"

    snapshot = _service(tmp_path, path_probe=failing_probe).collect()

    assert snapshot.record_for("promptpack_storage").state is OperatorReadinessState.ACTION_REQUIRED
    assert snapshot.record_for("output_storage").state is OperatorReadinessState.ACTION_REQUIRED


def test_collection_reads_recovery_metadata_without_queue_or_repository_mutation(tmp_path: Path) -> None:
    repository = _Repository(
        count=2,
        jobs=[_Job(_Metadata("restart_requeue")), _Job(_Metadata())],
    )
    snapshot = _service(tmp_path, repository=repository).collect()

    storage = snapshot.record_for("job_storage")
    recovery = snapshot.record_for("queue_recovery")
    assert storage.state is OperatorReadinessState.READY
    assert recovery.state is OperatorReadinessState.READY
    assert "1 persisted job was recovered" in recovery.summary
    assert repository.submission_calls == 0
    assert repository.recovery_calls == 0
