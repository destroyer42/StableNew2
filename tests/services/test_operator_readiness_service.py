from __future__ import annotations

from pathlib import Path

import pytest

from src.services.operator_readiness_service import (
    OperatorReadinessService,
    OperatorReadinessState,
    ProductSupportState,
)
from src.video.svd_capabilities import SVDPreflight
from src.video.svd_config import SVDConfig


class _Repository:
    def __init__(self, *, count: int = 0, interrupted_count: int = 0) -> None:
        self._count = count
        self._interrupted_count = interrupted_count
        self.projection_actions: list[str] = []
        self.submission_calls = 0
        self.recovery_calls = 0

    def count(self) -> int:
        return self._count

    def count_jobs_with_last_control_action(self, action: str) -> int:
        self.projection_actions.append(action)
        return self._interrupted_count

    def list_job_models(self):
        raise AssertionError("Readiness must not hydrate persisted jobs")

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
        raise AssertionError(
            "Readiness must use the existing connection state, not probe independently"
        )


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
    python_version: tuple[int, int, int] = (3, 14, 0),
    free_threaded: bool = False,
    jit_enabled: bool = False,
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
        python_version_provider=lambda: python_version,
        free_threaded_provider=lambda: free_threaded,
        jit_enabled_provider=lambda: jit_enabled,
    )


def test_support_policy_is_deterministic_and_only_accepted_journeys_are_supported(
    tmp_path: Path,
) -> None:
    snapshot = _service(tmp_path).collect()

    support = {item.id: item.state for item in snapshot.support_surfaces}
    assert support["a1111_still_image"] is ProductSupportState.SUPPORTED
    assert support["native_svd_xt"] is ProductSupportState.SUPPORTED
    assert support["pipeline"] is ProductSupportState.SUPPORTED
    assert support["movie_clips"] is ProductSupportState.ADVANCED_OR_UNVERIFIED
    assert support["character_training"] is ProductSupportState.ADVANCED_OR_UNVERIFIED
    assert ProductSupportState.DEFERRED.value == "deferred"


def test_ready_webui_and_svd_runtime_are_truthful_when_source_is_not_selected(
    tmp_path: Path,
) -> None:
    webui = _WebUIConnection("ready")
    snapshot = _service(tmp_path, webui=webui).collect()

    assert snapshot.record_for("webui").state is OperatorReadinessState.READY
    assert snapshot.record_for("native_svd_runtime").state is OperatorReadinessState.READY
    assert snapshot.record_for("svd_source_image").state is OperatorReadinessState.OPTIONAL
    assert webui.probe_calls == 0


def test_python_314_is_the_only_ready_runtime(tmp_path: Path) -> None:
    runtime = _service(tmp_path, python_version=(3, 14, 8)).collect().record_for("python_runtime")

    assert runtime is not None
    assert runtime.state is OperatorReadinessState.READY
    assert runtime.blocking_reasons == ()
    assert "3.14" in runtime.summary


def test_jit_enabled_python_314_is_not_a_supported_runtime(tmp_path: Path) -> None:
    runtime = (
        _service(tmp_path, python_version=(3, 14, 8), jit_enabled=True)
        .collect()
        .record_for("python_runtime")
    )

    assert runtime is not None
    assert runtime.state is OperatorReadinessState.ACTION_REQUIRED
    assert "JIT" in runtime.blocking_reasons[0]
    assert "PYTHON_JIT" in runtime.operator_actions[0]


def test_free_threaded_python_314_is_not_a_supported_runtime(tmp_path: Path) -> None:
    runtime = (
        _service(tmp_path, python_version=(3, 14, 8), free_threaded=True)
        .collect()
        .record_for("python_runtime")
    )

    assert runtime is not None
    assert runtime.state is OperatorReadinessState.ACTION_REQUIRED
    assert "free-threaded" in runtime.blocking_reasons[0]
    assert "standard (GIL)" in runtime.operator_actions[0]


@pytest.mark.parametrize(
    "version",
    [(3, 10, 6), (3, 11, 9), (3, 12, 14), (3, 13, 1), (3, 15, 0)],
    ids=["3.10", "3.11", "3.12", "3.13", "3.15"],
)
def test_unsupported_python_minors_are_action_required_with_a_3_14_action(
    tmp_path: Path, version: tuple[int, int, int]
) -> None:
    runtime = _service(tmp_path, python_version=version).collect().record_for("python_runtime")
    detected = ".".join(str(part) for part in version)

    assert runtime is not None
    assert runtime.state is OperatorReadinessState.ACTION_REQUIRED
    assert runtime.blocking_reasons == (f"Detected Python {detected}; required Python 3.14.x.",)
    assert "Python 3.14" in runtime.operator_actions[0]


def test_unavailable_webui_projects_existing_connection_authority(tmp_path: Path) -> None:
    snapshot = _service(
        tmp_path,
        webui=_WebUIConnection("error", "port 127.0.0.1:7860 not listening"),
    ).collect()

    record = snapshot.record_for("webui")
    assert record.state is OperatorReadinessState.ACTION_REQUIRED
    assert record.blocking_reasons == ("port 127.0.0.1:7860 not listening",)
    assert record.source == "WebUIConnectionController"


def test_missing_local_svd_cache_is_action_required_without_blurring_source_state(
    tmp_path: Path,
) -> None:
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


def test_collection_reads_recovery_metadata_without_queue_or_repository_mutation(
    tmp_path: Path,
) -> None:
    repository = _Repository(count=2, interrupted_count=1)
    snapshot = _service(tmp_path, repository=repository).collect()

    storage = snapshot.record_for("job_storage")
    recovery = snapshot.record_for("queue_recovery")
    assert storage.state is OperatorReadinessState.READY
    assert recovery.state is OperatorReadinessState.ACTION_REQUIRED
    assert "1 interrupted job requires operator review" in recovery.summary
    assert recovery.blocking_reasons == ("INTERRUPTED_RESTART_ACTION_REQUIRED",)
    assert "Replay Job intentionally" in recovery.operator_actions[0]
    assert repository.submission_calls == 0
    assert repository.recovery_calls == 0
    assert repository.projection_actions == ["restart_interrupted_action_required"]


@pytest.mark.parametrize("count", [0, 1, 3])
def test_recovery_projection_preserves_count_state_and_text(tmp_path: Path, count: int) -> None:
    repository = _Repository(count=10_926, interrupted_count=count)
    record = _service(tmp_path, repository=repository).collect().record_for("queue_recovery")

    assert repository.projection_actions == ["restart_interrupted_action_required"]
    if count:
        assert record.state is OperatorReadinessState.ACTION_REQUIRED
        assert record.summary == (
            f"{count} interrupted job{' requires' if count == 1 else 's require'} operator review."
        )
        assert record.blocking_reasons == ("INTERRUPTED_RESTART_ACTION_REQUIRED",)
        assert "Replay Job intentionally" in record.operator_actions[0]
    else:
        assert record.state is OperatorReadinessState.OPTIONAL
        assert record.summary == "No interrupted-restart action-required records are currently present."
        assert record.blocking_reasons == ()


def test_recovery_projection_failure_is_unknown_without_hydration_fallback(tmp_path: Path) -> None:
    class FailingRepository(_Repository):
        def count_jobs_with_last_control_action(self, action: str) -> int:
            self.projection_actions.append(action)
            raise RuntimeError("metadata query failed")

    repository = FailingRepository()
    record = _service(tmp_path, repository=repository).collect().record_for("queue_recovery")

    assert record.state is OperatorReadinessState.UNKNOWN
    assert "metadata query failed" in record.summary
    assert repository.projection_actions == ["restart_interrupted_action_required"]
    assert repository.submission_calls == repository.recovery_calls == 0
