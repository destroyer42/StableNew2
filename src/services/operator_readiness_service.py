"""Read-only operator readiness projection built from existing authorities."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from src.pipeline.video import resolve_ffmpeg_executable
from src.promptpacks.paths import resolve_prompt_pack_dir
from src.video.svd_capabilities import SVDPreflight, get_svd_preflight
from src.video.svd_config import SVDConfig
from src.video.svd_models import get_default_svd_cache_dir


class ProductSupportState(str, Enum):
    """Product-policy classification; this is not an execution authorization."""

    SUPPORTED = "supported"
    ADVANCED_OR_UNVERIFIED = "advanced_or_unverified"
    DEFERRED = "deferred"


class OperatorReadinessState(str, Enum):
    READY = "ready"
    ACTION_REQUIRED = "action_required"
    OPTIONAL = "optional"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProductSupportSurface:
    id: str
    display_name: str
    state: ProductSupportState
    summary: str
    source: str


@dataclass(frozen=True)
class OperatorReadinessRecord:
    id: str
    display_name: str
    state: OperatorReadinessState
    summary: str
    blocking_reasons: tuple[str, ...]
    operator_actions: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class OperatorReadinessSnapshot:
    support_surfaces: tuple[ProductSupportSurface, ...]
    records: tuple[OperatorReadinessRecord, ...]

    def support_for(self, surface_id: str) -> ProductSupportSurface | None:
        return next((surface for surface in self.support_surfaces if surface.id == surface_id), None)

    def record_for(self, record_id: str) -> OperatorReadinessRecord | None:
        return next((record for record in self.records if record.id == record_id), None)


class _WebUIConnectionAuthority(Protocol):
    def get_state(self) -> Any: ...


PathProbe = Callable[[Path], tuple[bool, str | None]]
SVDPreflightProvider = Callable[..., SVDPreflight]


def product_support_surfaces() -> tuple[ProductSupportSurface, ...]:
    """Return deterministic product policy for currently visible operator surfaces."""

    return (
        ProductSupportSurface(
            id="a1111_still_image",
            display_name="A1111 still-image create-to-replay",
            state=ProductSupportState.SUPPORTED,
            summary="Accepted queue-first still-image journey through canonical artifacts and replay.",
            source="PR-MVP-060 accepted product state",
        ),
        ProductSupportSurface(
            id="native_svd_xt",
            display_name="Native Diffusers SVD XT selected-image-to-video",
            state=ProductSupportState.SUPPORTED,
            summary="Accepted queue-first native SVD XT journey through canonical artifacts and replay.",
            source="PR-MVP-070 accepted product state",
        ),
        ProductSupportSurface(
            id="prompt",
            display_name="Prompt",
            state=ProductSupportState.SUPPORTED,
            summary="PromptPack authoring is part of the accepted still-image journey.",
            source="PR-MVP-060 accepted product state",
        ),
        ProductSupportSurface(
            id="pipeline",
            display_name="Pipeline",
            state=ProductSupportState.SUPPORTED,
            summary="The accepted queue-first image journey is projected through Pipeline.",
            source="PR-MVP-060 accepted product state",
        ),
        ProductSupportSurface(
            id="svd",
            display_name="SVD Img2Vid",
            state=ProductSupportState.SUPPORTED,
            summary="The accepted native SVD XT selected-image-to-video journey.",
            source="PR-MVP-070 accepted product state",
        ),
        ProductSupportSurface(
            id="learning",
            display_name="Learning",
            state=ProductSupportState.ADVANCED_OR_UNVERIFIED,
            summary="Visible surface without a separately accepted MVP operator journey.",
            source="Current roadmap and visible-tab inventory",
        ),
        ProductSupportSurface(
            id="review",
            display_name="Review",
            state=ProductSupportState.ADVANCED_OR_UNVERIFIED,
            summary="Visible surface without a separately accepted MVP operator journey.",
            source="Current roadmap and visible-tab inventory",
        ),
        ProductSupportSurface(
            id="photo_optimize",
            display_name="Photo Optimize",
            state=ProductSupportState.ADVANCED_OR_UNVERIFIED,
            summary="Visible surface without a separately accepted MVP operator journey.",
            source="Current roadmap and visible-tab inventory",
        ),
        ProductSupportSurface(
            id="movie_clips",
            display_name="Movie Clips",
            state=ProductSupportState.ADVANCED_OR_UNVERIFIED,
            summary="Visible surface without a separately accepted MVP operator journey.",
            source="Current roadmap and visible-tab inventory",
        ),
        ProductSupportSurface(
            id="character_training",
            display_name="Character Training",
            state=ProductSupportState.ADVANCED_OR_UNVERIFIED,
            summary="Visible surface without a separately accepted MVP operator journey.",
            source="Current roadmap and visible-tab inventory",
        ),
        ProductSupportSurface(
            id="video_workflow",
            display_name="Video Workflow",
            state=ProductSupportState.ADVANCED_OR_UNVERIFIED,
            summary="Visible surface without a separately accepted MVP operator journey.",
            source="Current roadmap and visible-tab inventory",
        ),
    )


class OperatorReadinessService:
    """Read existing runtime authorities without starting, repairing, or submitting work."""

    def __init__(
        self,
        *,
        repository: Any | None = None,
        webui_connection: _WebUIConnectionAuthority | None = None,
        prompt_pack_dir_provider: Callable[[], Path] = resolve_prompt_pack_dir,
        output_dir_provider: Callable[[], Path] | None = None,
        svd_config_provider: Callable[[], SVDConfig] | None = None,
        svd_preflight_provider: SVDPreflightProvider = get_svd_preflight,
        ffmpeg_resolver: Callable[[], Path | None] = resolve_ffmpeg_executable,
        path_probe: PathProbe | None = None,
    ) -> None:
        self._repository = repository
        self._webui_connection = webui_connection
        self._prompt_pack_dir_provider = prompt_pack_dir_provider
        self._output_dir_provider = output_dir_provider or (lambda: Path("output"))
        self._svd_config_provider = svd_config_provider or _accepted_svd_baseline_config
        self._svd_preflight_provider = svd_preflight_provider
        self._ffmpeg_resolver = ffmpeg_resolver
        self._path_probe = path_probe or _probe_directory

    def collect(self, *, source_image_path: str | Path | None = None) -> OperatorReadinessSnapshot:
        """Collect a side-effect-free projection of existing authority state."""

        preflight = self._svd_preflight_provider(
            self._svd_config_provider(), source_image_path=source_image_path
        )
        return OperatorReadinessSnapshot(
            support_surfaces=product_support_surfaces(),
            records=(
                self._repository_record(),
                self._path_record(
                    record_id="promptpack_storage",
                    display_name="PromptPack storage",
                    path=self._prompt_pack_dir_provider(),
                    source="PromptPack path resolver",
                ),
                self._path_record(
                    record_id="output_storage",
                    display_name="Output storage",
                    path=self._output_dir_provider(),
                    source="Configured output-path provider",
                ),
                self._webui_record(),
                self._svd_runtime_record(preflight),
                self._svd_source_record(preflight),
                self._ffmpeg_record(),
                self._recovery_record(),
            ),
        )

    def _repository_record(self) -> OperatorReadinessRecord:
        if self._repository is None:
            return _unknown_record(
                "job_storage",
                "Job storage",
                "JobRepository was not supplied to the readiness projection.",
                "JobRepository / SQLite authority",
            )
        try:
            count = int(self._repository.count())
        except Exception as exc:
            return _action_record(
                "job_storage",
                "Job storage",
                "SQLite job storage could not be read.",
                (str(exc),),
                ("Review the JobRepository/SQLite diagnostics before submitting work.",),
                "JobRepository / SQLite authority",
            )
        return OperatorReadinessRecord(
            id="job_storage",
            display_name="Job storage",
            state=OperatorReadinessState.READY,
            summary=f"SQLite job storage is reachable ({count} persisted job{'s' if count != 1 else ''}).",
            blocking_reasons=(),
            operator_actions=(),
            source="JobRepository / SQLite authority",
        )

    def _path_record(
        self,
        *,
        record_id: str,
        display_name: str,
        path: str | Path,
        source: str,
    ) -> OperatorReadinessRecord:
        resolved = Path(path).expanduser().resolve(strict=False)
        ready, reason = self._path_probe(resolved)
        if ready:
            return OperatorReadinessRecord(
                id=record_id,
                display_name=display_name,
                state=OperatorReadinessState.READY,
                summary=f"{display_name} is readable and writable at '{resolved}'.",
                blocking_reasons=(),
                operator_actions=(),
                source=source,
            )
        detail = reason or f"'{resolved}' is unavailable."
        return _action_record(
            record_id,
            display_name,
            f"{display_name} is not ready at '{resolved}'.",
            (detail,),
            (f"Create or select a readable, writable {display_name.lower()} location.",),
            source,
        )

    def _webui_record(self) -> OperatorReadinessRecord:
        if self._webui_connection is None:
            return _unknown_record(
                "webui",
                "A1111 / WebUI",
                "WebUI connection authority was not supplied to the readiness projection.",
                "WebUIConnectionController",
            )
        state = _state_value(self._webui_connection.get_state())
        if state == "ready":
            return OperatorReadinessRecord(
                id="webui",
                display_name="A1111 / WebUI",
                state=OperatorReadinessState.READY,
                summary="WebUI connection authority reports READY.",
                blocking_reasons=(),
                operator_actions=(),
                source="WebUIConnectionController",
            )
        detail = getattr(self._webui_connection, "last_readiness_error", None)
        reason = str(detail or f"WebUI connection authority reports '{state or 'unknown'}'.")
        return _action_record(
            "webui",
            "A1111 / WebUI",
            "WebUI is not ready for the supported still-image path.",
            (reason,),
            ("Use the existing WebUI connection controls, then refresh readiness.",),
            "WebUIConnectionController",
        )

    def _svd_runtime_record(self, preflight: SVDPreflight) -> OperatorReadinessRecord:
        blockers = _svd_runtime_blockers(preflight)
        if not blockers:
            return OperatorReadinessRecord(
                id="native_svd_runtime",
                display_name="Native SVD XT runtime",
                state=OperatorReadinessState.READY,
                summary=preflight.core_summary,
                blocking_reasons=(),
                operator_actions=(),
                source="get_svd_preflight / SVDPreflight",
            )
        actions = ["Review Native SVD preflight details and correct the listed runtime prerequisite."]
        if preflight.local_files_only and not preflight.model_cached:
            actions.insert(0, "Place the supported SVD XT model in the configured local cache, then refresh.")
        return _action_record(
            "native_svd_runtime",
            "Native SVD XT runtime",
            "Native SVD XT runtime is not ready.",
            blockers,
            tuple(actions),
            "get_svd_preflight / SVDPreflight",
        )

    def _svd_source_record(self, preflight: SVDPreflight) -> OperatorReadinessRecord:
        if preflight.source_image_path is None:
            return OperatorReadinessRecord(
                id="svd_source_image",
                display_name="SVD source image",
                state=OperatorReadinessState.OPTIONAL,
                summary="Select a source image when creating a native SVD XT job.",
                blocking_reasons=(),
                operator_actions=("Select a source image to submit a video job.",),
                source="get_svd_preflight / SVDPreflight",
            )
        if preflight.source_image_valid:
            return OperatorReadinessRecord(
                id="svd_source_image",
                display_name="SVD source image",
                state=OperatorReadinessState.READY,
                summary="Selected source image passed SVD admission.",
                blocking_reasons=(),
                operator_actions=(),
                source="get_svd_preflight / SVDPreflight",
            )
        blockers = tuple(
            reason for reason in preflight.blocking_reasons if reason.startswith("Invalid SVD source image:")
        )
        return _action_record(
            "svd_source_image",
            "SVD source image",
            "Selected source image is not admissible for SVD.",
            blockers or ("Selected source image did not pass SVD admission.",),
            ("Select a valid source image to submit a video job.",),
            "get_svd_preflight / SVDPreflight",
        )

    def _ffmpeg_record(self) -> OperatorReadinessRecord:
        executable = self._ffmpeg_resolver()
        if executable is not None:
            return OperatorReadinessRecord(
                id="ffmpeg",
                display_name="FFmpeg video export",
                state=OperatorReadinessState.READY,
                summary=f"FFmpeg executable resolves to '{executable}'.",
                blocking_reasons=(),
                operator_actions=(),
                source="resolve_ffmpeg_executable",
            )
        return _action_record(
            "ffmpeg",
            "FFmpeg video export",
            "FFmpeg executable could not be resolved for MP4 export.",
            ("No FFmpeg executable was found by the existing resolver.",),
            ("Configure STABLENEW_FFMPEG_PATH or install FFmpeg on PATH, then refresh.",),
            "resolve_ffmpeg_executable",
        )

    def _recovery_record(self) -> OperatorReadinessRecord:
        if self._repository is None:
            return _unknown_record(
                "queue_recovery",
                "Persisted queue recovery",
                "JobRepository was not supplied to inspect persisted recovery metadata.",
                "JobRepository execution_metadata",
            )
        try:
            jobs = self._repository.list_job_models()
            recovered = sum(
                1
                for job in jobs
                if getattr(getattr(job, "execution_metadata", None), "last_control_action", None)
                == "restart_requeue"
            )
        except Exception as exc:
            return _unknown_record(
                "queue_recovery",
                "Persisted queue recovery",
                f"Persisted recovery metadata could not be read: {exc}",
                "JobRepository execution_metadata",
            )
        if recovered:
            summary = f"{recovered} persisted job{' was' if recovered == 1 else 's were'} recovered after interruption."
            state = OperatorReadinessState.READY
        else:
            summary = "No persisted restart-requeue recovery metadata is currently present."
            state = OperatorReadinessState.OPTIONAL
        return OperatorReadinessRecord(
            id="queue_recovery",
            display_name="Persisted queue recovery",
            state=state,
            summary=summary,
            blocking_reasons=(),
            operator_actions=("Interrupted RUNNING jobs are requeued by the existing repository recovery path.",),
            source="JobRepository execution_metadata",
        )


def _accepted_svd_baseline_config() -> SVDConfig:
    """Return the accepted baseline only for read-only SVD preflight projection."""

    return SVDConfig.from_dict(
        {
            "preprocess": {"resize_mode": "center_crop"},
            "inference": {
                "num_frames": 14,
                "fps": 7,
                "motion_bucket_id": 48,
                "noise_aug_strength": 0.01,
                "decode_chunk_size": 2,
                "num_inference_steps": 25,
                "local_files_only": True,
                "cache_dir": str(get_default_svd_cache_dir()),
            },
            "output": {"output_format": "mp4", "save_frames": False, "save_preview_image": True},
        }
    )


def _probe_directory(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, f"Directory does not exist: '{path}'."
    if not path.is_dir():
        return False, f"Path is not a directory: '{path}'."
    if not os.access(path, os.R_OK):
        return False, f"Directory is not readable: '{path}'."
    if not os.access(path, os.W_OK):
        return False, f"Directory is not writable: '{path}'."
    return True, None


def _svd_runtime_blockers(preflight: SVDPreflight) -> tuple[str, ...]:
    if preflight.source_image_path is None:
        return tuple(reason for reason in preflight.blocking_reasons if reason != "Select a source image.")
    if preflight.source_image_valid is False:
        return tuple(
            reason
            for reason in preflight.blocking_reasons
            if not reason.startswith("Invalid SVD source image:")
        )
    return preflight.blocking_reasons


def _state_value(state: Any) -> str:
    value = getattr(state, "value", state)
    return str(value or "").strip().lower()


def _action_record(
    record_id: str,
    display_name: str,
    summary: str,
    blockers: tuple[str, ...],
    actions: tuple[str, ...],
    source: str,
) -> OperatorReadinessRecord:
    return OperatorReadinessRecord(
        id=record_id,
        display_name=display_name,
        state=OperatorReadinessState.ACTION_REQUIRED,
        summary=summary,
        blocking_reasons=blockers,
        operator_actions=actions,
        source=source,
    )


def _unknown_record(
    record_id: str, display_name: str, summary: str, source: str
) -> OperatorReadinessRecord:
    return OperatorReadinessRecord(
        id=record_id,
        display_name=display_name,
        state=OperatorReadinessState.UNKNOWN,
        summary=summary,
        blocking_reasons=(),
        operator_actions=(),
        source=source,
    )


__all__ = [
    "OperatorReadinessRecord",
    "OperatorReadinessService",
    "OperatorReadinessSnapshot",
    "OperatorReadinessState",
    "ProductSupportState",
    "ProductSupportSurface",
    "product_support_surfaces",
]
