"""PR-VID-SEQ-330-CORE: the prompts frozen in the plan are exactly the prompts the backend is handed.

A blank, inherited or explicitly empty value must never be silently replaced by another one between admission and
dispatch, and the plan must record the value that will really be used (including a workflow's default negative prompt).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.video.sequence_plan import SequencePlan, SequencePlanError
from tests.pipeline.test_pr_vid_seq_330_runner import (
    FakeComfy,
    _built,
    _runner,
    needs_ffmpeg,
)


def _plan_of(njr: Any) -> SequencePlan:
    return SequencePlan.from_dict(dict(njr.stage_chain[0].extra)["sequence_metadata"])


def _intent(*segments: dict[str, Any]) -> dict[str, Any]:
    return {"segments": list(segments), "assembly": {"enabled": False}}


def _dispatched(backend: FakeComfy) -> list[tuple[str, str]]:
    return [(r["prompt"], r["negative_prompt"]) for r in backend.requests]


@needs_ffmpeg
def test_every_dispatched_prompt_equals_the_frozen_plan_value(tmp_path: Path) -> None:
    _c, _s, built = _built(
        tmp_path,
        _intent(
            {"frame_count": 17, "seed": 1},
            {"frame_count": 17, "seed": 2, "prompt": "turns", "negative_prompt": "blur"},
            {"frame_count": 17, "seed": 3},
        ),
    )
    backend = FakeComfy()

    result = _runner(tmp_path, backend).run_njr(built.njr, cancel_token=None)

    assert result.success is True, result.error
    plan = _plan_of(built.njr)
    assert _dispatched(backend) == [(s.prompt, s.negative_prompt) for s in plan.segments]
    # ...and the stage config the backend saw carries the same values as the request.
    assert [
        (r["config_prompt"], r["config_negative_prompt"]) for r in backend.requests
    ] == _dispatched(backend)


def test_a_blank_negative_is_frozen_as_the_workflows_default_that_the_job_really_uses(
    tmp_path: Path,
) -> None:
    _c, _s, built = _built(
        tmp_path, _intent({"frame_count": 17}, {"frame_count": 17}), negative_prompt=""
    )
    plan = _plan_of(built.njr)
    job_negative = built.njr.negative_prompt

    assert job_negative  # the single-clip builder fills the workflow's default negative prompt
    assert [s.negative_prompt for s in plan.segments] == [job_negative, job_negative]


@needs_ffmpeg
def test_an_explicitly_empty_negative_is_dispatched_empty_not_replaced_by_the_jobs(
    tmp_path: Path,
) -> None:
    _c, _s, built = _built(
        tmp_path,
        _intent({"frame_count": 17}, {"frame_count": 17, "negative_prompt": ""}),
        negative_prompt="no blur",
    )
    plan = _plan_of(built.njr)
    assert [s.negative_prompt for s in plan.segments] == [
        "no blur",
        "",
    ]  # explicit empty is frozen as empty
    backend = FakeComfy()

    result = _runner(tmp_path, backend).run_njr(built.njr, cancel_token=None)

    assert result.success is True, result.error
    assert [r["negative_prompt"] for r in backend.requests] == ["no blur", ""]
    assert [r["config_negative_prompt"] for r in backend.requests] == ["no blur", ""]


def test_an_explicitly_empty_positive_prompt_is_refused_for_a_workflow_that_requires_one(
    tmp_path: Path,
) -> None:
    with pytest.raises(SequencePlanError, match="needs a prompt"):
        _built(tmp_path, _intent({"frame_count": 17}, {"frame_count": 17, "prompt": ""}))


def test_a_segment_prompt_is_never_trimmed_into_something_else_or_inherited_by_accident(
    tmp_path: Path,
) -> None:
    _c, _s, built = _built(
        tmp_path,
        _intent({"frame_count": 17, "prompt": "  waves  "}, {"frame_count": 17, "prompt": None}),
    )

    plan = _plan_of(built.njr)

    assert [s.prompt for s in plan.segments] == [
        "waves",
        "the person waves",
    ]  # None inherits; text is stripped once
