"""Secondary-motion retirement policy: one predicate, one error, one stable message (owner decision D8).

Secondary motion was a post-process that shifted whole frames by integer pixels, filling the edge with black. It
produced judder, not motion, so it no longer executes. The intent key, the policy and apply records already stored
on jobs, the result keys and the learning readers stay readable so historical records still load, display and
render in history. What is refused is *execution*: any request that would run an **enabled** secondary-motion
intent or stage block.

An intent that is absent, disabled or in ``mode == "disabled"`` is inert and stays valid, so the refusal keys on
the enabled state (the same predicate the runner used to decide whether to run the stage), never on the key's
presence.

The refusal is raised before any dispatch at JobService submission, ``PipelineRunner.run_njr``, replay compilation
and the SVD and Comfy backends. The stage is never dropped or substituted: running the clip without it would
change the requested result.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.utils.error_envelope_v2 import wrap_exception

SECONDARY_MOTION_STAGE = "secondary_motion"
SECONDARY_MOTION_RETIRED_CODE = "secondary_motion_retired"
SECONDARY_MOTION_RETIRED_MESSAGE = (
    "Secondary motion is retired and can no longer run: it shifted whole frames and produced judder. "
    "Turn it off (secondary_motion.enabled=false or mode=disabled), or smooth the clip with RIFE "
    "interpolation instead. No generation was started and nothing was substituted."
)

# The intent modes the runner treated as "on" (``observe`` recorded a policy, ``apply`` also shifted frames).
_ACTIVE_INTENT_MODES = frozenset({"observe", "apply"})


class SecondaryMotionRetiredError(ValueError):
    """An enabled secondary-motion request was made; it is refused before any dispatch."""

    code = SECONDARY_MOTION_RETIRED_CODE

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or SECONDARY_MOTION_RETIRED_MESSAGE)


def intent_enables_secondary_motion(intent: Any) -> bool:
    """Whether a ``secondary_motion`` *intent* mapping asks for the stage (enabled and observe/apply mode)."""

    if not isinstance(intent, Mapping):
        return False
    mode = str(intent.get("mode") or "disabled").strip().lower()
    return bool(intent.get("enabled")) and mode in _ACTIVE_INTENT_MODES


def block_enables_secondary_motion(block: Any) -> bool:
    """Whether a ``secondary_motion`` *runtime* block (the SVD postprocess or Comfy stage form) is enabled.

    Mirrors ``SVDSecondaryMotionConfig.from_dict``: ``enabled`` falls back to the nested policy and then intent.
    """

    if not isinstance(block, Mapping):
        return False
    policy = block.get("policy")
    intent = block.get("intent")
    intent_enabled = intent.get("enabled", False) if isinstance(intent, Mapping) else False
    fallback = (
        policy.get("enabled", intent_enabled) if isinstance(policy, Mapping) else intent_enabled
    )
    return bool(block.get("enabled", fallback))


def stage_enables_secondary_motion(stage: Any) -> bool:
    """Whether one stage entry (a ``StageConfig``-like object or its dict form) carries an enabled block."""

    to_dict = getattr(stage, "to_dict", None)
    payload = to_dict() if callable(to_dict) else stage
    if not isinstance(payload, Mapping):
        return False
    flat = dict(payload)
    extra = flat.pop("extra", None)
    if isinstance(extra, Mapping):
        flat.update(extra)
    if block_enables_secondary_motion(flat.get(SECONDARY_MOTION_STAGE)):
        return True
    postprocess = flat.get("postprocess")
    return isinstance(postprocess, Mapping) and block_enables_secondary_motion(
        postprocess.get(SECONDARY_MOTION_STAGE)
    )


def stages_enable_secondary_motion(stages: Iterable[Any] | None) -> bool:
    return any(stage_enables_secondary_motion(stage) for stage in (stages or ()))


def njr_enables_secondary_motion(njr: Any) -> bool:
    """Whether an NJR (or NJR-like object) would execute an enabled secondary-motion request."""

    intent_config = getattr(njr, "intent_config", None)
    if isinstance(intent_config, Mapping):
        from src.pipeline.config_contract_v26 import extract_secondary_motion_intent

        if intent_enables_secondary_motion(extract_secondary_motion_intent(intent_config)):
            return True
    chain = getattr(njr, "stage_chain", None)
    if chain is None:
        chain = getattr(njr, "stages", None)
    return stages_enable_secondary_motion(chain)


def require_secondary_motion_not_enabled(njr: Any) -> None:
    """Raise ``SecondaryMotionRetiredError`` when the NJR would execute enabled secondary motion.

    The error carries a typed envelope, so a queued job that fails here is classified as an invalid configuration
    (not an unclassified error) by the queue failure path.
    """

    if njr_enables_secondary_motion(njr):
        error = SecondaryMotionRetiredError()
        wrap_exception(
            error,
            subsystem="pipeline",
            job_id=getattr(njr, "job_id", None),
            stage=SECONDARY_MOTION_STAGE,
            context={"code": SECONDARY_MOTION_RETIRED_CODE},
        )
        raise error


def require_secondary_motion_block_disabled(block: Any) -> None:
    """Backend-side refusal for one runtime block, raised before the backend dispatches anything."""

    if block_enables_secondary_motion(block):
        raise SecondaryMotionRetiredError()


__all__ = [
    "SECONDARY_MOTION_RETIRED_CODE",
    "SECONDARY_MOTION_RETIRED_MESSAGE",
    "SECONDARY_MOTION_STAGE",
    "SecondaryMotionRetiredError",
    "block_enables_secondary_motion",
    "intent_enables_secondary_motion",
    "njr_enables_secondary_motion",
    "require_secondary_motion_block_disabled",
    "require_secondary_motion_not_enabled",
    "stage_enables_secondary_motion",
    "stages_enable_secondary_motion",
]
