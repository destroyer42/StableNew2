"""PR-VID-POST-305 / decision D8: secondary motion is retired.

An *enabled* secondary-motion request (intent in observe/apply mode, or an enabled runtime block) is refused with
one readable message before any dispatch. A disabled or absent one is inert, and everything already stored
(configs, NJRs, manifests, container metadata, Learning records) keeps loading and rendering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.job_service import JobService
from src.pipeline.job_models_v2 import StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.pipeline.secondary_motion_retirement import (
    SECONDARY_MOTION_RETIRED_MESSAGE,
    SecondaryMotionRetiredError,
    block_enables_secondary_motion,
    intent_enables_secondary_motion,
    njr_enables_secondary_motion,
    require_secondary_motion_block_disabled,
)
from src.queue.failure_triage import TriageCategory, triage_failure
from src.queue.job_queue import JobQueue
from src.utils.error_envelope_v2 import get_attached_envelope
from src.video.container_metadata import build_public_media_payload
from src.video.motion.secondary_motion_provenance import extract_secondary_motion_summary
from src.video.svd_config import SVDConfig
from src.video.svd_postprocess import validate_svd_postprocess_config
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


def _intent(**overrides: Any) -> dict[str, Any]:
    return {"enabled": True, "mode": "apply", "intent": "micro_sway", **overrides}


def _svd_njr(*, intent: dict[str, Any] | None = None, stage_extra: dict[str, Any] | None = None):
    return make_pipeline_njr(
        job_id="svd-job",
        stage_chain=(StageConfig(stage_type="svd_native", enabled=True, extra=stage_extra or {}),),
        input_image_paths=("seed.png",),
        start_stage="svd_native",
        intent_config={"secondary_motion": intent} if intent is not None else {},
    )


# ---------------------------------------------------------------------------
# predicate: only an enabled request is refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["apply", "observe", "APPLY"])
def test_enabled_intent_in_an_active_mode_is_refused(mode: str) -> None:
    assert intent_enables_secondary_motion(_intent(mode=mode))
    assert njr_enables_secondary_motion(_svd_njr(intent=_intent(mode=mode)))


@pytest.mark.parametrize(
    "intent",
    [
        None,
        {},
        {"enabled": False, "mode": "apply"},
        {"enabled": True, "mode": "disabled"},
        {"enabled": True},
        "apply",
    ],
)
def test_absent_disabled_or_off_mode_intent_is_inert(intent: Any) -> None:
    assert not intent_enables_secondary_motion(intent)
    njr_intent = intent if isinstance(intent, dict) else None
    assert not njr_enables_secondary_motion(_svd_njr(intent=njr_intent))


def test_enabled_runtime_blocks_on_a_stage_are_refused() -> None:
    block = {"enabled": True, "policy": {"enabled": True}}
    assert njr_enables_secondary_motion(
        _svd_njr(stage_extra={"postprocess": {"secondary_motion": block}})
    )
    assert njr_enables_secondary_motion(_svd_njr(stage_extra={"secondary_motion": block}))
    # The block's enabled state falls back to its policy, then its intent (SVDSecondaryMotionConfig.from_dict).
    assert block_enables_secondary_motion({"policy": {"enabled": True}})
    assert block_enables_secondary_motion({"intent": {"enabled": True}})
    assert not block_enables_secondary_motion({"enabled": False, "policy": {"enabled": True}})
    assert not block_enables_secondary_motion({})
    assert not block_enables_secondary_motion(None)
    disabled = {"enabled": False}
    assert not njr_enables_secondary_motion(
        _svd_njr(stage_extra={"postprocess": {"secondary_motion": disabled}})
    )


def test_message_is_stable_and_actionable() -> None:
    message = str(SecondaryMotionRetiredError())
    assert message == SECONDARY_MOTION_RETIRED_MESSAGE
    assert "retired" in message and "enabled=false" in message and "RIFE" in message
    assert isinstance(SecondaryMotionRetiredError(), ValueError)
    with pytest.raises(SecondaryMotionRetiredError):
        require_secondary_motion_block_disabled({"enabled": True})
    require_secondary_motion_block_disabled({"enabled": False})


# ---------------------------------------------------------------------------
# refusal points
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


def test_job_service_refuses_an_enabled_request_and_admits_nothing() -> None:
    service, runner = _service()
    good = make_pipeline_njr(job_id="good", stage_chain=(make_stage_config("txt2img"),))

    with pytest.raises(SecondaryMotionRetiredError, match="Secondary motion is retired"):
        service.submit_njrs([good, _svd_njr(intent=_intent())])

    assert service.job_queue.list_jobs() == []
    assert runner.started is False


def test_job_service_still_admits_a_disabled_intent() -> None:
    service, _runner = _service()
    record = _svd_njr(intent=_intent(enabled=False))
    assert service.submit_njrs([record]) == [record.job_id]


def test_run_njr_refuses_before_any_client_call_with_a_typed_envelope(tmp_path: Path) -> None:
    client = Mock()
    runner = PipelineRunner(client, Mock(), runs_base_dir=str(tmp_path / "runs"))
    client.reset_mock()

    with pytest.raises(SecondaryMotionRetiredError) as caught:
        runner.run_njr(_svd_njr(intent=_intent()))

    assert client.mock_calls == []
    assert not (tmp_path / "runs").exists()
    envelope = get_attached_envelope(caught.value)
    assert envelope is not None and envelope.error_type == "SecondaryMotionRetiredError"
    triage = triage_failure(error_message=str(caught.value), envelope=envelope, result=None)
    assert triage.category is TriageCategory.INVALID_CONFIGURATION
    assert triage.error_type == "SecondaryMotionRetiredError"


def test_replaying_a_parent_that_enabled_it_is_refused() -> None:
    with pytest.raises(SecondaryMotionRetiredError):
        compile_replay_intent(ReplayIntent(_svd_njr(intent=_intent())))


def test_svd_admission_refuses_an_enabled_config_and_keeps_a_stored_one_loadable() -> None:
    stored = {
        "postprocess": {
            "secondary_motion": {
                "enabled": True,
                "policy_id": "svd_secondary_motion_v1",
                "intent": {"enabled": True, "mode": "apply"},
                "intensity": 0.4,
                "regions": ["hair"],
            }
        }
    }
    config = SVDConfig.from_dict(stored)  # still loads and displays
    assert config.postprocess.secondary_motion.enabled is True
    assert config.postprocess.secondary_motion.regions == ("hair",)
    assert SVDConfig.from_dict(config.to_dict()).postprocess.secondary_motion == (
        config.postprocess.secondary_motion
    )

    valid, reason = validate_svd_postprocess_config(config)
    assert valid is False and reason == SECONDARY_MOTION_RETIRED_MESSAGE

    disabled = SVDConfig.from_dict({"postprocess": {"secondary_motion": {"enabled": False}}})
    assert validate_svd_postprocess_config(disabled) == (True, None)


# ---------------------------------------------------------------------------
# history stays readable
# ---------------------------------------------------------------------------


def test_stored_summaries_and_container_metadata_still_render() -> None:
    stored = {
        "stage": "video_workflow",
        "backend_id": "comfy",
        "secondary_motion": {
            "intent": {"enabled": True, "mode": "observe", "intent": "micro_sway"},
            "primary_policy": {
                "policy_id": "observe_policy_v1",
                "enabled": True,
                "backend_mode": "observe_shared_postprocess_candidate",
                "intensity": 0.25,
                "cap_pixels": 12,
            },
        },
    }
    summary = extract_secondary_motion_summary(stored)
    assert summary["status"] == "observe"
    assert summary["policy_id"] == "observe_policy_v1"
    payload = build_public_media_payload(stored, media_type="video")
    assert payload["secondary_motion"]["status"] == "observe"
