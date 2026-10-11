"""IMG159: compiled effective Z-Image configuration through JobService/SQLite/queue/runner/executor with a fake Forge.

The PromptPack is compiled by the production builder from a legacy-style configuration (stored global positive text,
enabled prompt optimizer, CLIP skip 2, inherited SDXL sampling). The single dispatched POST must carry the composed
prompt exactly once, the profile's own sampling, and nothing the compile step normalized.
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P
from src.pipeline.global_prompt_policy import apply_global_prompt_policy
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import JobStatus
from tests.helpers.njr_queue_harness import run_njr_via_queue
from tests.integration.test_pr_img_116_klein_canonical_path import _client
from tests.integration.test_pr_img_155_zimage_canonical_path import (  # noqa: F401
    _no_physical_assets,
    transport,
)
from tests.pipeline.test_zimage_compile_policy import _pack
from tests.tools.test_img_forge_100_acceptance_driver import canonical_context  # noqa: F401

GLOBAL_POSITIVE = "soft studio lighting"
BASE = "A ceramic teapot on a wooden table."


def legacy_style_record(tmp_path, monkeypatch):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    manager = builder._config_manager
    config = {
        "txt2img": {**manager._config["txt2img"], "clip_skip": 2, "sampler_name": "DPM++ 2M", "scheduler": "Karras",
                    "steps": 30, "cfg_scale": 7.0, "seed": 424254},
        "pipeline": dict(manager._config["pipeline"]),
        "prompt_optimizer": {"enabled": True},
    }
    entry.config_snapshot = apply_global_prompt_policy(
        config, positive_enabled=True, positive_text=GLOBAL_POSITIVE, negative_enabled=True, negative_text="ugly"
    )
    source = deepcopy(entry.config_snapshot)
    (record,) = builder.build_jobs([entry])
    assert entry.config_snapshot == source and path.read_bytes() == original
    return record


def test_dispatched_request_carries_the_composed_prompt_once_and_the_profile_sampling(tmp_path, monkeypatch):
    record = legacy_style_record(tmp_path, monkeypatch)
    t = transport()
    entry = run_njr_via_queue(record, _client(t), artifact_root=tmp_path / "artifacts")
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert len(t.generation_calls) == 1
    payload = t.generation_calls[0][2]
    assert payload["prompt"] == f"{GLOBAL_POSITIVE}, {BASE}"
    assert payload["prompt"].count(GLOBAL_POSITIVE) == 1  # the executor did not apply it a second time
    assert payload["negative_prompt"] == ""
    assert (payload["sampler_name"], payload["scheduler"], payload["steps"], payload["cfg_scale"]) == ("Euler", "Beta", 9, 1)
    assert payload["distilled_cfg_scale"] == P.distilled_cfg_scale
    stored = entry.snapshot["normalized_job"]
    assert stored["workload"]["positive_prompt"] == payload["prompt"]
    assert stored["workload"]["config"]["pipeline"]["apply_global_positive_txt2img"] is False
    assert stored["workload"]["config"]["global_positive_prompt"] == ""


def test_replaying_the_frozen_njr_neither_reinterprets_nor_repeats_the_global_contribution(tmp_path, monkeypatch):
    record = legacy_style_record(tmp_path, monkeypatch)
    frozen = json.dumps(record.to_dict(), sort_keys=True, default=str)
    restored = NormalizedJobRecord.from_dict(json.loads(frozen))
    t = transport()
    entry = run_njr_via_queue(restored, _client(t), artifact_root=tmp_path / "artifacts")
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert t.generation_calls[0][2]["prompt"] == f"{GLOBAL_POSITIVE}, {BASE}"
    assert restored.positive_prompt == record.positive_prompt  # the frozen text is what ran, not a fresh composition


@pytest.mark.parametrize("change", [{"enable_hr": True}, {"width": 576, "height": 1024}])
def test_unsupported_work_is_still_refused_before_any_generation(tmp_path, monkeypatch, change):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    entry.config_snapshot = {
        "txt2img": {**builder._config_manager._config["txt2img"], **change},
        "pipeline": dict(builder._config_manager._config["pipeline"]),
    }
    with pytest.raises(ValueError):
        builder.build_jobs([entry])
    assert path.read_bytes() == original


@pytest.mark.usefixtures("canonical_context")
def test_send_job_and_run_now_freeze_and_dispatch_the_same_effective_job(tmp_path, monkeypatch):
    """Both go through JobService.submit_njrs; only the immediate-start policy differs (queue-first either way)."""
    from dataclasses import replace

    from src.controller.submission_policy_v26 import SubmissionPolicy
    from tools.acceptance.img_forge_100_acceptance import _await_terminal, build_stack

    record = legacy_style_record(tmp_path, monkeypatch)
    record = replace(record, output_plan=replace(record.output_plan, base_output_dir=str(tmp_path / "output")))
    twin = replace(record, job_id="twin-job")
    t = transport()
    stack = build_stack(tmp_path / "state", tmp_path / "output", P.backend_id, "http://127.0.0.1:7860", client=_client(t))
    try:
        # Send Job: admitted and durably queued; admission itself dispatches nothing.
        queued = stack.service.submit_njrs([record], SubmissionPolicy(start_when_idle=False))
        assert queued == [record.job_id] and t.generation_calls == []
        # Run Now: the same compiled effective job with the immediate-start policy, still admitted through the
        # queue; the single FIFO worker then drains both, each as exactly one generation POST.
        started = stack.service.submit_njrs([twin], SubmissionPolicy(start_when_idle=True))
        assert started == [twin.job_id]
        results = [_await_terminal(stack.repository, job_id, 10) for job_id in (record.job_id, twin.job_id)]
        assert all(result.status is JobStatus.COMPLETED for result in results), [r.error_message for r in results]
        assert results[0].snapshot["normalized_job"]["workload"] == results[1].snapshot["normalized_job"]["workload"]
        assert len(t.generation_calls) == 2
        prompts = {call[2]["prompt"] for call in t.generation_calls}
        assert prompts == {f"{GLOBAL_POSITIVE}, {BASE}"}
    finally:
        quiesced = stack.service.stop(timeout=5)
        if quiesced:
            stack.repository.close()
        assert quiesced
