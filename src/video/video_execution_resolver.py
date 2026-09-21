"""Single canonical resolver for video execution: explicit backend, task and controls.

``VideoExecutionResolver`` is the only place that turns a stage's video intent into a validated
(backend, task, controls) triple.  Two intent sources feed the *same* validation:

* **Neutral (canonical, new work):** a ``video_execution`` block inside the immutable stage
  config: ``{"backend_id", "task", "controls", "workflow_id", "workflow_version"}``.  The backend
  is chosen only by ``backend_id``; nothing is inferred from stage names, task order or models.
* **Legacy bridge (historical records only):** a stage config with no ``video_execution`` block
  whose stage type is one of the accepted stage-owned video stages (``svd_native``,
  ``animatediff``, ``video_workflow``) resolves through the registry's stage claim and the
  fixed baseline mapping below.  It exists so historical NJRs stay replayable and accepted
  jobs keep working.  Removal condition: every producer compiles the neutral block and no
  historical record needs stage-owned routing (replay migration proven), then delete
  ``LEGACY_STAGE_BINDINGS``, ``VideoBackendRegistry.get_for_stage`` and the legacy flags of
  ``VideoBackendCapabilities``.

Validation is deterministic and happens before any backend is called: unknown backend, unsupported
task, unsupported or missing controls, and (for explicit work) an unknown/unapproved workflow all
raise ``VideoContractError``.  There is no fallback and no silent dropping of a control.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.video.video_backend_registry import VideoBackendRegistry
from src.video.video_backend_types import (
    CONTROL_END_ANCHOR,
    CONTROL_MID_ANCHORS,
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
    KNOWN_VIDEO_CONTROLS,
    KNOWN_VIDEO_TASKS,
    VIDEO_TASK_IMAGE_TO_VIDEO,
    VideoBackendInterface,
    VideoExecutionRequest,
)

VIDEO_EXECUTION_KEY = "video_execution"

# stage type -> (task, baseline controls the historical backend honoured).  Prompt text is not a
# baseline control of svd_native: the accepted SVD path has always carried it as context only.
LEGACY_STAGE_BINDINGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "svd_native": (VIDEO_TASK_IMAGE_TO_VIDEO, (CONTROL_SOURCE_IMAGE,)),
    "animatediff": (
        VIDEO_TASK_IMAGE_TO_VIDEO,
        (CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
    ),
    "video_workflow": (
        VIDEO_TASK_IMAGE_TO_VIDEO,
        (CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
    ),
}


class VideoContractError(ValueError):
    """A video request violates the neutral execution contract (raised before dispatch)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class VideoExecutionIntent:
    backend_id: str | None  # None only for the legacy bridge (registry stage claim decides)
    task: str
    controls: tuple[str, ...]
    workflow_id: str | None
    workflow_version: str | None
    legacy: bool


def _clean(value: Any) -> str:
    return str(value or "").strip()


class VideoExecutionResolver:
    def __init__(self, registry: VideoBackendRegistry) -> None:
        self._registry = registry

    def is_video_stage(self, stage_type: str) -> bool:
        """True for stage types that carry video work: the persisted video stage types (which
        also carry explicit neutral work) or any stage type a registered backend still claims."""

        return stage_type in LEGACY_STAGE_BINDINGS or self._registry.is_registered_stage(stage_type)

    def build_intent(
        self,
        stage_type: str,
        stage_config: Mapping[str, Any],
        *,
        has_source_image: bool,
    ) -> VideoExecutionIntent:
        block = stage_config.get(VIDEO_EXECUTION_KEY)
        if isinstance(block, Mapping) and block:
            controls = {_clean(item) for item in block.get("controls") or () if _clean(item)}
            if has_source_image:
                controls.add(CONTROL_SOURCE_IMAGE)
            return VideoExecutionIntent(
                backend_id=_clean(block.get("backend_id")) or None,
                task=_clean(block.get("task")) or VIDEO_TASK_IMAGE_TO_VIDEO,
                controls=tuple(sorted(controls)),
                workflow_id=_clean(block.get("workflow_id") or stage_config.get("workflow_id"))
                or None,
                workflow_version=_clean(
                    block.get("workflow_version") or stage_config.get("workflow_version")
                )
                or None,
                legacy=False,
            )
        binding = LEGACY_STAGE_BINDINGS.get(stage_type)
        if binding is None:
            raise VideoContractError(
                "unknown_stage", f"Stage '{stage_type}' has no explicit video_execution block"
            )
        task, baseline = binding
        controls = set(baseline)
        if not has_source_image:
            controls.discard(CONTROL_SOURCE_IMAGE)
        if stage_config.get("end_anchor_path"):
            controls.add(CONTROL_END_ANCHOR)
        if stage_config.get("mid_anchor_paths"):
            controls.add(CONTROL_MID_ANCHORS)
        return VideoExecutionIntent(
            backend_id=None,
            task=task,
            controls=tuple(sorted(controls)),
            workflow_id=_clean(stage_config.get("workflow_id")) or None,
            workflow_version=_clean(stage_config.get("workflow_version")) or None,
            legacy=True,
        )

    def resolve(self, stage_type: str, intent: VideoExecutionIntent) -> VideoBackendInterface:
        """Return the backend for ``intent`` after validating task and controls."""

        if intent.legacy:
            try:
                backend = self._registry.get_for_stage(stage_type)
            except KeyError as exc:
                raise VideoContractError("unknown_backend", str(exc)) from exc
        else:
            if not intent.backend_id:
                raise VideoContractError(
                    "backend_required", "Neutral video work must name an explicit backend_id"
                )
            try:
                backend = self._registry.get(intent.backend_id)
            except KeyError as exc:
                raise VideoContractError("unknown_backend", str(exc)) from exc
        self.validate(backend, intent)
        return backend

    @staticmethod
    def validate(backend: VideoBackendInterface, intent: VideoExecutionIntent) -> None:
        capabilities = backend.capabilities
        backend_id = backend.backend_id
        if intent.task not in KNOWN_VIDEO_TASKS or intent.task not in capabilities.tasks:
            raise VideoContractError(
                "unsupported_task",
                f"Video backend '{backend_id}' does not support task '{intent.task}'",
            )
        requested = set(intent.controls)
        unknown = sorted(requested - KNOWN_VIDEO_CONTROLS)
        if unknown:
            raise VideoContractError("unknown_control", f"Unknown video controls {unknown}")
        unsupported = sorted(requested - set(capabilities.controls))
        if unsupported:
            raise VideoContractError(
                "unsupported_control",
                f"Video backend '{backend_id}' does not support requested controls {unsupported}",
            )
        missing = sorted(set(capabilities.required_controls) - requested)
        if missing:
            raise VideoContractError(
                "missing_control",
                f"Video backend '{backend_id}' requires controls {missing}",
            )

    def apply(self, request: VideoExecutionRequest, intent: VideoExecutionIntent) -> None:
        """Stamp the validated task/controls/workflow identity onto the neutral request and run
        the backend's optional explicit-workflow check (never for the legacy bridge)."""

        request.task = intent.task
        request.requested_controls = tuple(intent.controls)
        if intent.workflow_id:
            request.workflow_id = intent.workflow_id
            request.workflow_version = intent.workflow_version
        request.context_metadata["video_contract"] = {
            "task": intent.task,
            "controls": list(intent.controls),
            "backend_id": request.backend_id,
            "workflow_id": intent.workflow_id,
            "workflow_version": intent.workflow_version,
            "legacy_stage_routing": intent.legacy,
        }
        if intent.legacy:
            return
        backend = self._registry.get(request.backend_id)
        check = getattr(backend, "validate_workflow", None)
        if callable(check):
            try:
                check(request)
            except (KeyError, ValueError) as exc:
                raise VideoContractError("invalid_workflow", str(exc)) from exc


__all__ = [
    "LEGACY_STAGE_BINDINGS",
    "VIDEO_EXECUTION_KEY",
    "VideoContractError",
    "VideoExecutionIntent",
    "VideoExecutionResolver",
]
