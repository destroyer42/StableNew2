"""AnimateDiff execution retirement: refusal of ENABLED stages, inertness of the disabled placeholder.

Every PromptPack job carries a disabled ``animatediff`` placeholder stage plus an ``animatediff`` settings dict.
Those must stay valid, loadable and silently inert. Only an *enabled* AnimateDiff stage is refused, and always
before any dispatch (no WebUI request, no extension probe).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_service import JobService
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.animatediff_retirement import (
    ANIMATEDIFF_RETIRED_MESSAGE,
    AnimateDiffRetiredError,
    njr_enables_animatediff,
    stage_enables_animatediff,
)
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.pipeline.result_contract_v26 import extract_primary_artifact
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.queue.failure_triage import TriageCategory, triage_failure
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _placeholder_stage() -> StageConfig:
    """The disabled placeholder every PromptPack job carries."""

    return StageConfig(
        stage_type="animatediff",
        enabled=False,
        extra={"fps": 8, "video_length": 16, "batch_size": 16},
    )


def _as_json(record: NormalizedJobRecord) -> Any:
    return json.loads(json.dumps(record.to_queue_snapshot(), default=str))


def _enabled_animatediff_njr(job_id: str = "ad-enabled", **overrides: Any) -> NormalizedJobRecord:
    """A video NJR shaped like the one historical source='video' AnimateDiff job."""

    return make_pipeline_njr(
        job_id=job_id,
        positive_prompt="portrait, subtle head turn",
        stage_chain=(
            StageConfig(
                stage_type="animatediff",
                enabled=True,
                extra={"enabled": True, "motion_module": "mm_sdxl_hs.safetensors", "fps": 8},
            ),
        ),
        input_image_paths=("seed.png",),
        start_stage="animatediff",
        **overrides,
    )


def _placeholder_pack_njr(job_id: str = "pack-placeholder") -> NormalizedJobRecord:
    """An ordinary image NJR: enabled txt2img plus the disabled animatediff placeholder."""

    return make_pipeline_njr(
        job_id=job_id,
        source_kind="prompt_pack",
        prompt_pack_id="pack-001",
        prompt_pack_name="Pack",
        stage_chain=(make_stage_config("txt2img"), _placeholder_stage()),
        config={"model": "sdxl", "prompt": "p", "animatediff": {"enabled": False, "fps": 8}},
    )


# ---------------------------------------------------------------------------
# predicate
# ---------------------------------------------------------------------------


def test_predicate_keys_on_enabled_stage_only() -> None:
    assert stage_enables_animatediff(StageConfig(stage_type="animatediff", enabled=True))
    assert not stage_enables_animatediff(_placeholder_stage())
    assert not stage_enables_animatediff(StageConfig(stage_type="txt2img", enabled=True))
    # Persisted dict form: a missing ``enabled`` key means enabled (StageConfig.from_value), explicit false is inert.
    assert stage_enables_animatediff({"stage_type": "animatediff", "enabled": True})
    assert stage_enables_animatediff({"stage_type": "animatediff"})
    assert not stage_enables_animatediff({"stage_type": "animatediff", "enabled": False})

    assert njr_enables_animatediff(_enabled_animatediff_njr())
    assert not njr_enables_animatediff(_placeholder_pack_njr())
    # The ``animatediff`` settings dict alone (even with enabled=True inside it) is not an executing stage.
    settings_only = make_pipeline_njr(
        job_id="settings-only",
        config={"model": "sdxl", "prompt": "p", "animatediff": {"enabled": True}},
    )
    assert not njr_enables_animatediff(settings_only)


def test_error_message_is_stable_and_actionable() -> None:
    message = str(AnimateDiffRetiredError())
    assert message == ANIMATEDIFF_RETIRED_MESSAGE
    assert "AnimateDiff execution is retired" in message
    assert "Disable the AnimateDiff stage" in message
    assert "native SVD" in message and "Comfy Video Workflow" in message
    assert "No request was sent" in message and "no stage was substituted" in message
    assert isinstance(AnimateDiffRetiredError(), ValueError)


# ---------------------------------------------------------------------------
# fresh PromptPack compilation
# ---------------------------------------------------------------------------


def _write_pack(path: Path, preset_data: dict[str, Any] | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": path.stem,
                    "slots": [
                        {
                            "index": 0,
                            "text": "An angelic knight",
                            "negative": "",
                            "positive_embeddings": [],
                            "negative_embeddings": [],
                            "loras": [],
                        }
                    ],
                    "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                },
                "preset_data": preset_data or {},
            }
        ),
        encoding="utf-8",
    )


def _builder(
    tmp_path: Path, preset_data: dict[str, Any] | None = None
) -> PromptPackNormalizedJobBuilder:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(exist_ok=True)
    _write_pack(packs_dir / "knight.json", preset_data)
    counter = iter(f"job-{index}" for index in range(1, 100))
    return PromptPackNormalizedJobBuilder(
        config_manager=ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs_dir),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=lambda: next(counter)),
    )


def _entry(stage_flags: dict[str, bool] | None = None) -> PackJobEntry:
    return PackJobEntry(
        pack_id="knight",
        pack_name="knight",
        config_snapshot={"randomization": {"enabled": False}},
        stage_flags=stage_flags or {"txt2img": True},
        randomizer_metadata={"enabled": False, "max_variants": 1},
    )


def test_fresh_compile_with_animatediff_enabled_stage_flag_is_refused(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    with pytest.raises(AnimateDiffRetiredError, match="AnimateDiff execution is retired"):
        builder.build_jobs([_entry({"txt2img": True, "animatediff": True})])


def test_fresh_compile_with_saved_animatediff_enabled_is_refused(tmp_path: Path) -> None:
    builder = _builder(tmp_path, {"pipeline": {"animatediff_enabled": True}})
    with pytest.raises(AnimateDiffRetiredError):
        builder.build_jobs([_entry()])


def test_fresh_compile_with_disabled_placeholder_is_unaffected(tmp_path: Path) -> None:
    """Regression: the placeholder stage (and its settings dict) compiles, serializes and round-trips."""

    builder = _builder(tmp_path, {"animatediff": {"enabled": False, "fps": 8}})
    records = builder.build_jobs([_entry()])
    assert len(records) == 1
    record = records[0]

    placeholder = [stage for stage in record.stages if stage.stage_type == "animatediff"]
    assert len(placeholder) == 1 and placeholder[0].enabled is False
    assert [stage.stage_type for stage in record.stages if stage.enabled] == ["txt2img"]
    assert not njr_enables_animatediff(record)
    assert record.config.get("animatediff") is not None  # the settings key stays readable

    reloaded = normalized_job_from_snapshot({"normalized_job": _as_json(record)})
    assert reloaded is not None

    def stage_dicts(item: NormalizedJobRecord) -> list[Any]:
        return [s for s in _as_json(item)["stages"] if s["stage_type"] == "animatediff"]

    assert stage_dicts(reloaded) == stage_dicts(
        record
    )  # the placeholder entry survives byte-for-byte
    assert [stage.enabled for stage in reloaded.stages if stage.stage_type == "animatediff"] == [
        False
    ]
    again = normalized_job_from_snapshot({"normalized_job": _as_json(reloaded)})
    assert again is not None and _as_json(again) == _as_json(
        reloaded
    )  # stable after the first load


# ---------------------------------------------------------------------------
# JobService submission
# ---------------------------------------------------------------------------


class _Runner:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def is_running(self) -> bool:
        return self.started

    def run_once(self, job: Any) -> dict[str, Any]:
        return {"success": True}

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        return None


def _service() -> tuple[JobService, _Runner]:
    queue = JobQueue()
    runner = _Runner()
    runner.job_queue = queue  # type: ignore[attr-defined]
    return JobService(queue, runner=runner), runner


def test_job_service_submission_of_enabled_stage_is_refused_and_nothing_is_queued() -> None:
    service, runner = _service()
    good = _placeholder_pack_njr("good")

    with pytest.raises(AnimateDiffRetiredError, match="AnimateDiff execution is retired"):
        service.submit_njrs([good, _enabled_animatediff_njr()])

    assert (
        service.job_queue.list_jobs() == []
    )  # all-or-none: the valid sibling was not admitted either
    assert runner.started is False


def test_job_service_submission_of_disabled_placeholder_is_unaffected() -> None:
    service, _runner = _service()
    record = _placeholder_pack_njr()
    assert service.submit_njrs([record]) == [record.job_id]
    assert service.job_queue.get_job(record.job_id) is not None


# ---------------------------------------------------------------------------
# run_njr entry and queued jobs at claim time
# ---------------------------------------------------------------------------


def test_run_njr_entry_refusal_precedes_any_client_call(tmp_path: Path) -> None:
    client = Mock()
    runner = PipelineRunner(client, Mock(), runs_base_dir=str(tmp_path / "runs"))
    client.reset_mock()

    with pytest.raises(AnimateDiffRetiredError):
        runner.run_njr(_enabled_animatediff_njr())

    assert client.mock_calls == []
    assert not (tmp_path / "runs").exists()


def test_queued_enabled_job_fails_through_the_normal_path_without_any_request(
    tmp_path: Path,
) -> None:
    """A job queued before the retirement fails at claim time with the stable message; nothing is dispatched."""

    client = Mock()
    pipeline_runner = PipelineRunner(client, Mock(), runs_base_dir=str(tmp_path / "runs"))
    client.reset_mock()
    repository = JobRepository(tmp_path / "state" / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    controller = JobExecutionController(
        queue=queue, replay_runner=pipeline_runner, restore_state=False
    )
    service = JobService(queue, runner=controller._runner, history_store=repository)
    record = _enabled_animatediff_njr("legacy-queued")
    try:
        # Simulate admission by an older version: the job reaches the repository without today's JobService gate.
        job = service._job_from_njr(record, policy=SubmissionPolicy())
        queue.submit_many([job])
        claimed = queue.claim_next_job()
        assert claimed is not None and claimed.job_id == record.job_id
        with pytest.raises(RuntimeError, match="AnimateDiff execution is retired"):
            controller._runner.run_once(claimed)  # the worker records the failure, then re-raises

        durable = queue.get_job(record.job_id)
        assert durable is not None and durable.status is JobStatus.FAILED
        assert "AnimateDiff execution is retired" in (durable.error_message or "")
        assert client.mock_calls == []

        triage = triage_failure(
            error_message=durable.error_message,
            envelope=durable.error_envelope,
            result=durable.result,
        )
        assert triage.category is TriageCategory.INVALID_CONFIGURATION
        assert triage.error_type == "AnimateDiffRetiredError"
    finally:
        service.stop()
        repository.close()


# ---------------------------------------------------------------------------
# replay / reprocess
# ---------------------------------------------------------------------------


def test_replay_of_enabled_stage_is_refused_and_placeholder_replays_unchanged() -> None:
    with pytest.raises(AnimateDiffRetiredError):
        compile_replay_intent(ReplayIntent(_enabled_animatediff_njr()))

    parent = _placeholder_pack_njr()
    replay = compile_replay_intent(ReplayIntent(parent), id_fn=lambda: "replay-1")
    assert replay.job_id == "replay-1"
    assert [stage.stage_type for stage in replay.stages] == ["txt2img", "animatediff"]
    assert [stage.enabled for stage in replay.stages] == [True, False]


def test_reprocess_requesting_animatediff_is_refused_with_the_retired_error(tmp_path: Path) -> None:
    image = tmp_path / "in.png"
    image.write_bytes(b"png")
    builder = ReprocessJobBuilder(id_fn=lambda: "reprocess-1")

    with pytest.raises(AnimateDiffRetiredError, match="AnimateDiff execution is retired"):
        builder.build_reprocess_job([image], ["animatediff"])

    # The other video stage keeps working through the same builder.
    assert (
        builder.build_reprocess_job([image], ["svd_native"]).stage_chain[0].stage_type
        == "svd_native"
    )


# ---------------------------------------------------------------------------
# disabled -> enabled flip only
# ---------------------------------------------------------------------------


def test_refusal_happens_for_the_disabled_to_enabled_flip_only() -> None:
    """Same NJR, same stage entry: only flipping ``enabled`` False -> True turns admission into a refusal."""

    video_stage = StageConfig(stage_type="video_workflow", enabled=True, extra={"workflow_id": "w"})
    placeholder = make_pipeline_njr(
        job_id="flip",
        stage_chain=(_placeholder_stage(), video_stage),
        input_image_paths=("seed.png",),
    )
    flipped = replace(
        placeholder,
        stages=tuple(
            replace(stage, enabled=True) if stage.stage_type == "animatediff" else stage
            for stage in placeholder.stages
        ),
    )
    assert not njr_enables_animatediff(placeholder)
    assert njr_enables_animatediff(flipped)

    service, _runner = _service()
    assert service.submit_njrs([placeholder]) == ["flip"]
    other, _runner = _service()
    with pytest.raises(AnimateDiffRetiredError):
        other.submit_njrs([flipped])
    with pytest.raises(AnimateDiffRetiredError):
        compile_replay_intent(ReplayIntent(flipped))
    with pytest.raises(AnimateDiffRetiredError):
        PipelineRunner(Mock(), Mock()).run_njr(flipped)


# ---------------------------------------------------------------------------
# readability of old records
# ---------------------------------------------------------------------------


def test_old_snapshot_with_enabled_stage_still_loads_and_its_artifact_renders(
    tmp_path: Path,
) -> None:
    """The one historical enabled job: it deserializes, persists, reads back, and its artifact is extractable."""

    record = _enabled_animatediff_njr("historical-video")
    reloaded = normalized_job_from_snapshot({"normalized_job": _as_json(record)})
    assert reloaded is not None
    assert [(stage.stage_type, stage.enabled) for stage in reloaded.stages] == [
        ("animatediff", True)
    ]
    assert njr_enables_animatediff(reloaded)

    clip = tmp_path / "clip.mp4"
    result = {
        "success": True,
        "metadata": {
            "animatediff_artifact": {
                "stage": "animatediff",
                "backend_id": "animatediff",
                "artifact_type": "video",
                "primary_path": str(clip),
                "output_paths": [str(clip)],
                "count": 1,
                "artifacts": [
                    {
                        "schema": "stablenew.artifact.v2.6",
                        "artifact_type": "video",
                        "stage": "animatediff",
                        "primary_path": str(clip),
                        "output_paths": [str(clip)],
                    }
                ],
            }
        },
    }
    assert extract_primary_artifact(result)["primary_path"] == str(clip)

    repository = JobRepository(tmp_path / "state" / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue, runner=_Runner(), history_store=repository)
    try:
        job = service._job_from_njr(record, policy=SubmissionPolicy())
        queue.submit_many([job])  # persisted as an older version would have
        assert queue.mark_running(record.job_id) is not None
        published = queue.publish_result(
            record.job_id,
            status=JobStatus.COMPLETED,
            result=result,
            stage_checkpoints=[],
            error_message=None,
        )
        assert published is not None
        stored = repository.get_job_model(record.job_id)
        stored_record = getattr(stored, "_normalized_record", None)
        assert stored_record is not None and njr_enables_animatediff(stored_record)
        entry = repository.get_job(record.job_id)
        assert entry is not None and entry.status is JobStatus.COMPLETED
        assert extract_primary_artifact(entry.result)["primary_path"] == str(clip)
    finally:
        service.stop()
        repository.close()
