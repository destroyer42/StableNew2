"""Frozen-plan agreement: the plan binds every operator-controlled input, and the NJR must match it before dispatch.

``journey_inputs`` are the fixed inputs a journey types (prompts, LoRA name).  ``build_plan`` freezes them into each
target; the journeys read them back from the plan, so the plan, not a constant in the code, is what the operator
interface is given.  ``PlanGate`` wraps ``JobService.submit_njrs`` as an observer that may only *decline*: every record
about to be queued is compared with the frozen target and a mismatch (or more jobs than the plan allows) raises
``PlanMismatch`` before anything reaches the queue.  The gate adds no submission path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.operator_journey.observe import SubmissionObserver


class PlanMismatch(RuntimeError):
    """The NJR about to be dispatched does not match the frozen plan; nothing was queued."""


def journey_inputs(key: str) -> dict[str, Any]:
    """The fixed operator inputs of a journey (frozen into the plan; physical runs read them from it)."""

    if key == "image":
        from tools.operator_journey.golden import img01

        return {
            "prompt": img01.PROMPT,
            "negative_prompt": img01.NEGATIVE,
            "pack_name": img01.PACK_NAME,
        }
    if key == "video":
        from tools.operator_journey.golden import vid01

        return {"motion_prompt": vid01.MOTION_PROMPT}
    from tools.operator_journey.journeys.learning_lora_strength import (
        _RATINGS,
        _STRENGTHS,
        DEFAULT_LORA,
    )

    return {
        "lora_name": DEFAULT_LORA,
        "lora_strengths": list(_STRENGTHS),
        "ratings": list(_RATINGS),
    }


def input_problems(key: str, target: dict[str, Any]) -> list[str]:
    inputs = target.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        return [f"{key}: the plan does not bind the operator inputs (prompts / LoRA)"]
    missing = [name for name in journey_inputs(key) if inputs.get(name) in (None, "")]
    return [f"{key}: plan inputs missing: {', '.join(missing)}"] if missing else []


def _dig(blob: Any, *path: str) -> Any:
    for part in path:
        if not isinstance(blob, dict):
            return None
        blob = blob.get(part)
    return blob


def _norm(njr: dict[str, Any]) -> dict[str, Any]:
    return njr.get("normalized_job") if isinstance(njr.get("normalized_job"), dict) else njr


def _same(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def njr_mismatches(key: str, target: dict[str, Any], njr: dict[str, Any]) -> list[str]:
    """Every way the (frozen) NJR disagrees with the plan target; empty when they agree."""

    job = _norm(njr)
    problems: list[str] = []
    settings = target.get("settings") or {}
    inputs = target.get("inputs") or {}

    def expect(name: str, wanted: Any, seen: Any) -> None:
        if wanted is not None and not _same(wanted, seen):
            problems.append(f"{name}: plan {wanted!r} != NJR {seen!r}")

    if key == "learning":
        # A Learning job carries its executed baseline in the frozen experiment provenance.
        config = (
            _dig(job, "provenance", "metadata", "frozen_experiment", "executed_config", "txt2img")
            or {}
        )
        if not config:
            problems.append("the Learning NJR carries no frozen txt2img configuration")
        expect("seed", settings.get("seed"), config.get("seed"))
    if key in ("image", "learning"):
        config = config if key == "learning" else (_dig(job, "workload", "config") or {})
        wanted_model = str((target.get("model") or {}).get("name") or "")
        seen_model = str(config.get("model") or "")
        if wanted_model and Path(wanted_model).stem.lower() not in seen_model.lower():
            problems.append(f"model: plan {wanted_model!r} != NJR {seen_model!r}")
        for name in ("width", "height", "steps"):
            expect(name, settings.get(name), config.get(name))
        if key == "image":
            expect("seed", settings.get("seed"), config.get("seed"))
            prompt = str(_dig(job, "workload", "positive_prompt") or config.get("prompt") or "")
            if inputs.get("prompt") and not prompt.startswith(str(inputs["prompt"])):
                problems.append(f"prompt: plan {inputs['prompt']!r} != NJR {prompt!r}")
            negative = str(
                _dig(job, "workload", "negative_prompt") or config.get("negative_prompt") or ""
            )
            if inputs.get("negative_prompt") and str(inputs["negative_prompt"]) not in negative:
                problems.append("negative_prompt: the plan's negative prompt is not in the NJR")
    else:
        video = _dig(job, "workload", "config", "video_workflow") or {}
        wanted = target.get("workflow") or {}
        expect("workflow id", wanted.get("id"), video.get("workflow_id"))
        expect("workflow version", wanted.get("version"), video.get("workflow_version"))
        expect("frames", settings.get("frames"), video.get("frame_count"))
        expect("seed", settings.get("seed"), video.get("seed"))
        expect("motion prompt", inputs.get("motion_prompt"), video.get("prompt"))
        dims = _dig(video, "source_preparation", "target_dimensions") or {}
        expect("width", settings.get("width"), dims.get("width"))
        expect("height", settings.get("height"), dims.get("height"))
        assets = target.get("source_assets") or []
        source = _dig(video, "source_preparation", "original_source_path")
        if (
            assets
            and source
            and Path(str(assets[0]["path"])).resolve() != Path(str(source)).resolve()
        ):
            problems.append(f"source image: plan {assets[0]['path']} != NJR {source}")
    return problems


class PlanGate(SubmissionObserver):
    """A ``SubmissionObserver`` that declines any submission that disagrees with the frozen target."""

    def __init__(self, key: str, target: dict[str, Any]) -> None:
        super().__init__()
        self.key, self.target = key, target
        self.mismatches: list[str] = []
        self.verified = 0

    def install(self, job_service: Any) -> None:
        super().install(job_service)
        counted = job_service.submit_njrs

        def gated(records: Any, *args: Any, **kwargs: Any) -> Any:
            batch = list(records)
            problems: list[str] = []
            allowed = int(self.target.get("job_count", 0) or 0)
            if allowed and self.verified + len(batch) > allowed:
                problems.append(
                    f"job count: {self.verified + len(batch)} submitted would exceed the frozen {allowed}"
                )
            for record in batch:
                problems += njr_mismatches(self.key, self.target, record.to_dict())
            if problems:
                self.mismatches.extend(problems)
                raise PlanMismatch("; ".join(problems))
            self.verified += len(batch)
            return counted(batch, *args, **kwargs)

        job_service.submit_njrs = gated


__all__ = ["PlanGate", "PlanMismatch", "input_problems", "journey_inputs", "njr_mismatches"]
