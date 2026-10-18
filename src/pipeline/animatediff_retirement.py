"""AnimateDiff execution retirement policy: one predicate, one error, one stable message.

AnimateDiff (image-to-video through the WebUI extension) no longer executes. The stage type, the ``animatediff``
config key, the persisted stage entries and the ``animatediff_artifact`` result key stay readable so historical
records still load, display and render in history. What is refused is *execution*: any request that would run an
**enabled** AnimateDiff stage.

Every PromptPack job carries a *disabled* ``animatediff`` placeholder stage (``enabled=False``). That placeholder is
inert and must stay valid, so the refusal keys only on an enabled stage, never on the stage's presence or on the
``animatediff`` settings dictionary.

The refusal is raised before any dispatch (no WebUI request, no extension probe) at fresh compilation, JobService
submission, replay/reprocess compilation and ``PipelineRunner.run_njr``/``build_run_plan_from_njr``. The stage is never
dropped or substituted: replacing it with SVD or Wan would change the requested result.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.utils.error_envelope_v2 import wrap_exception

ANIMATEDIFF_STAGE = "animatediff"
ANIMATEDIFF_RETIRED_CODE = "animatediff_retired"
ANIMATEDIFF_RETIRED_MESSAGE = (
    "AnimateDiff execution is retired and can no longer run. Disable the AnimateDiff stage "
    "(animatediff_enabled=false), or use native SVD or the Comfy Video Workflow instead. "
    "No request was sent and no stage was substituted."
)


class AnimateDiffRetiredError(ValueError):
    """An enabled AnimateDiff stage was requested; the request is refused before any dispatch."""

    code = ANIMATEDIFF_RETIRED_CODE

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or ANIMATEDIFF_RETIRED_MESSAGE)


def _stage_name(stage: Any) -> str:
    raw = stage.get("stage_type") if isinstance(stage, dict) else getattr(stage, "stage_type", None)
    raw = getattr(raw, "value", raw)
    return str(raw or "").strip().lower()


def _stage_enabled(stage: Any) -> bool:
    # Mirrors StageConfig.from_value: a persisted stage dict without an ``enabled`` key is enabled.
    raw = (
        stage.get("enabled", True) if isinstance(stage, dict) else getattr(stage, "enabled", False)
    )
    return bool(raw)


def stage_enables_animatediff(stage: Any) -> bool:
    """Whether one stage entry (a ``StageConfig``-like object or its dict form) is an *enabled* AnimateDiff stage."""

    return _stage_name(stage) == ANIMATEDIFF_STAGE and _stage_enabled(stage)


def stages_enable_animatediff(stages: Iterable[Any] | None) -> bool:
    return any(stage_enables_animatediff(stage) for stage in (stages or ()))


def njr_enables_animatediff(njr: Any) -> bool:
    """Whether an NJR (or NJR-like object) would execute an enabled AnimateDiff stage."""

    chain = getattr(njr, "stage_chain", None)
    if chain is None:
        chain = getattr(njr, "stages", None)
    return stages_enable_animatediff(chain)


def refuse_enabled_animatediff(stages: Iterable[Any] | None) -> None:
    """Raise ``AnimateDiffRetiredError`` when any stage entry is an enabled AnimateDiff stage."""

    if stages_enable_animatediff(stages):
        raise AnimateDiffRetiredError()


def require_animatediff_not_enabled(njr: Any) -> None:
    """Raise ``AnimateDiffRetiredError`` when the NJR would execute an enabled AnimateDiff stage.

    The error carries a typed envelope, so a queued job that fails here is classified as an invalid configuration
    (not an unclassified error) by the queue failure path.
    """

    if njr_enables_animatediff(njr):
        error = AnimateDiffRetiredError()
        wrap_exception(
            error,
            subsystem="pipeline",
            job_id=getattr(njr, "job_id", None),
            stage=ANIMATEDIFF_STAGE,
            context={"code": ANIMATEDIFF_RETIRED_CODE},
        )
        raise error


__all__ = [
    "ANIMATEDIFF_RETIRED_CODE",
    "ANIMATEDIFF_RETIRED_MESSAGE",
    "ANIMATEDIFF_STAGE",
    "AnimateDiffRetiredError",
    "njr_enables_animatediff",
    "refuse_enabled_animatediff",
    "require_animatediff_not_enabled",
    "stage_enables_animatediff",
    "stages_enable_animatediff",
]
