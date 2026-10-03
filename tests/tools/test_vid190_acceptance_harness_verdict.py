"""PR-COMFY-RUNTIME-100 repair: truth of the acceptance harness's exit code and bounded retry.

Deterministic and GPU-free: the dispatch of a job (``_submit``/``_run_one``) is replaced by a fake that
returns the record a real run would, so only the harness's own selection, retry and verdict logic runs.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import Any

import pytest

from tools.acceptance import vid190_queue_recycling_acceptance as acceptance

CLEAN_RESOURCE_ERROR = "Workflow 'x' is not resource-ready: only 15.5 GB of system RAM is available"
DEVICE_LOSS_ERROR = "CUDA error: device lost during sampling"


class _FakeQueue:
    def get_job(self, job_id: str) -> Any:
        extra = {
            "workflow_id": "wf",
            "workflow_version": "v",
            "frame_count": 41,
            "fps": 24,
            "seed": 1,
            "video_execution": {"experimental_opt_in": True},
        }
        stage = SimpleNamespace(to_dict=lambda: {"extra": extra})
        return SimpleNamespace(_normalized_record=SimpleNamespace(stage_chain=[stage]))


class _Harness:
    """Runs ``acceptance._run`` against scripted per-label outcomes; records what was dispatched."""

    def __init__(self, monkeypatch, outcomes: dict[str, tuple[str, str]]) -> None:
        self.outcomes = outcomes  # label -> (status, error); unlisted labels complete
        self.submitted: list[tuple] = []
        self.dispatched: list[str] = []
        monkeypatch.setattr(acceptance, "_build_stack", lambda stack, workspace: None)
        monkeypatch.setattr(acceptance, "_submit", self._submit)
        monkeypatch.setattr(acceptance, "_run_one", self._run_one)
        monkeypatch.setattr(acceptance, "_replay_evidence", lambda stack, job_id: {})
        monkeypatch.setattr(acceptance, "_driver_gpu", lambda: {})
        monkeypatch.setattr(acceptance, "_endpoint_state", lambda url: "free")
        monkeypatch.setattr(acceptance, "_write_evidence", lambda evidence: None)

    def _submit(self, stack, source, workspace, job) -> str:
        self.submitted.append(job)
        return f"job-{len(self.submitted)}"

    def _run_one(self, stack, job_id, label, frames, comfy_url) -> dict:
        self.dispatched.append(label)
        status, error = self.outcomes.get(label, ("completed", ""))
        return {
            "label": label,
            "job_id": job_id,
            "frame_count": frames,
            "status": status,
            "error": error,
            "after": {"gpu": {}},
        }

    def run(self, suite: str, only: list[str] | None = None, version: str = "") -> tuple[int, dict]:
        args = argparse.Namespace(
            source="source.png", suite=suite, only=only or [], workflow_version=version
        )
        evidence: dict = {"preflight": {"comfy_base_url": "http://127.0.0.1:1"}}
        code = acceptance._run(SimpleNamespace(queue=_FakeQueue()), args, evidence, workspace=None)
        return code, evidence


def _failed(error: str = "boom") -> tuple[str, str]:
    return ("failed", error)


# --- Fix 1: the verdict covers the primary jobs actually selected -----------------------------------


@pytest.mark.parametrize("label", ["A0", "A1", "A2", "A3"])
def test_a_failed_selected_controls_job_fails_the_run(monkeypatch, label: str) -> None:
    harness = _Harness(monkeypatch, {label: _failed()})

    code, evidence = harness.run("animate2_controls", only=[label])

    assert code == 1  # previously: filtering to A/B/C left [] and all([]) returned 0
    assert evidence["primary_jobs"] == [label]
    assert harness.dispatched == [label]


@pytest.mark.parametrize("selection", [["A0"], ["A1", "A3"], ["A0", "A1", "A2", "A3"]])
def test_selected_controls_jobs_that_all_complete_pass(monkeypatch, selection: list[str]) -> None:
    code, evidence = _Harness(monkeypatch, {}).run("animate2_controls", only=selection)

    assert code == 0
    assert evidence["primary_jobs"] == selection


def test_one_failed_job_among_several_selected_controls_jobs_fails_the_run(monkeypatch) -> None:
    code, _evidence = _Harness(monkeypatch, {"A2": _failed()}).run(
        "animate2_controls", only=["A1", "A2", "A3"]
    )

    assert code == 1


@pytest.mark.parametrize("suite", ["ti2v", "animate2"])
def test_the_whole_suite_keeps_its_a_b_c_verdict(monkeypatch, suite: str) -> None:
    ok_code, ok_evidence = _Harness(monkeypatch, {}).run(suite)
    assert ok_code == 0 and ok_evidence["primary_jobs"] == ["A", "B", "C"]
    for label in ("A", "B", "C"):
        assert _Harness(monkeypatch, {label: _failed()}).run(suite)[0] == 1


def test_a_single_filtered_job_is_judged_on_its_own_outcome(monkeypatch) -> None:
    assert _Harness(monkeypatch, {}).run("animate2_drive", only=["C"])[0] == 0
    assert _Harness(monkeypatch, {"C": _failed()}).run("animate2_drive", only=["C"])[0] == 1


def test_an_unknown_label_selection_is_refused_before_anything_is_queued(monkeypatch) -> None:
    harness = _Harness(monkeypatch, {})

    with pytest.raises(SystemExit):
        harness.run("animate2_controls", only=["A9"])

    assert harness.submitted == [] and harness.dispatched == []


def test_workflow_version_override_applies_to_every_selected_job_only(monkeypatch) -> None:
    harness = _Harness(monkeypatch, {})

    harness.run("ti2v", only=["A"], version="1.2.0")

    assert [(job[0], job[2]) for job in harness.submitted] == [("A", "1.2.0")]


# --- Fix 2: the bounded B retry in a filtered suite ---------------------------------------------------


def test_filtered_b_with_a_clean_resource_failure_queues_exactly_one_65_frame_retry(monkeypatch) -> None:
    harness = _Harness(monkeypatch, {"B": _failed(CLEAN_RESOURCE_ERROR)})

    code, evidence = harness.run("ti2v", only=["B"], version="1.2.0")  # previously: IndexError on suite[1]

    assert [job[0] for job in harness.submitted] == ["B", "B_retry"]
    assert harness.dispatched == ["B", "B_retry"]  # exactly one retry, no further dispatch
    original, retry = harness.submitted
    assert retry[3] == acceptance.RETRY_FRAMES == 65
    assert (retry[1], retry[2], retry[4:]) == (original[1], original[2], original[4:])  # same case, version, seed, prompt
    assert retry[2] == "1.2.0"
    assert code == 1  # the established policy: the retry never substitutes for a failed primary B
    assert evidence["primary_jobs"] == ["B"]


def test_a_failing_retry_is_not_retried_again(monkeypatch) -> None:
    harness = _Harness(
        monkeypatch,
        {"B": _failed(CLEAN_RESOURCE_ERROR), "B_retry": _failed(CLEAN_RESOURCE_ERROR)},
    )

    code, _evidence = harness.run("ti2v", only=["B"])

    assert harness.dispatched == ["B", "B_retry"] and code == 1


def test_filtered_b_without_a_resource_failure_never_retries(monkeypatch) -> None:
    for outcome in ({}, {"B": _failed("some other failure")}):
        harness = _Harness(monkeypatch, outcome)
        harness.run("ti2v", only=["B"])
        assert harness.dispatched == ["B"]


def test_a_filtered_non_b_resource_failure_never_triggers_the_b_retry(monkeypatch) -> None:
    harness = _Harness(monkeypatch, {"A": _failed(CLEAN_RESOURCE_ERROR)})

    code, _evidence = harness.run("ti2v", only=["A"])

    assert harness.dispatched == ["A"] and code == 1


def test_the_unfiltered_suite_retry_is_unchanged(monkeypatch) -> None:
    harness = _Harness(monkeypatch, {"B": _failed(CLEAN_RESOURCE_ERROR)})

    code, _evidence = harness.run("ti2v")

    assert harness.dispatched == ["A", "B", "C", "B_retry"]
    suite_b = next(job for job in acceptance.SUITES["ti2v"] if job[0] == "B")
    retry = harness.submitted[-1]
    assert retry == ("B_retry", suite_b[1], suite_b[2], acceptance.RETRY_FRAMES, *suite_b[4:])
    assert code == 1  # B failed, so the primary verdict fails (unchanged)


# --- GPU device loss still hard-stops ----------------------------------------------------------------


@pytest.mark.parametrize("only", [["B"], None])
def test_device_loss_on_b_returns_2_and_prevents_the_retry(monkeypatch, only) -> None:
    harness = _Harness(monkeypatch, {"B": _failed(DEVICE_LOSS_ERROR + "; " + CLEAN_RESOURCE_ERROR)})

    code, evidence = harness.run("ti2v", only=only)

    assert code == 2
    assert "device-loss" in evidence["hard_stop"]
    assert "B_retry" not in harness.dispatched
    if only is None:
        assert harness.dispatched == ["A", "B"]  # no further dispatch after the loss


def test_device_loss_on_a_selected_controls_job_stops_before_the_next_one(monkeypatch) -> None:
    harness = _Harness(monkeypatch, {"A1": _failed(DEVICE_LOSS_ERROR)})

    code, _evidence = harness.run("animate2_controls", only=["A0", "A1", "A2"])

    assert code == 2 and harness.dispatched == ["A0", "A1"]


def test_device_loss_on_the_bounded_retry_returns_2(monkeypatch) -> None:
    harness = _Harness(
        monkeypatch,
        {"B": _failed(CLEAN_RESOURCE_ERROR), "B_retry": _failed(DEVICE_LOSS_ERROR)},
    )

    code, evidence = harness.run("ti2v", only=["B"])

    assert code == 2 and harness.dispatched == ["B", "B_retry"]
    assert "bounded retry" in evidence["hard_stop"]
