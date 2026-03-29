from __future__ import annotations

from dataclasses import asdict

import pytest

from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION
from src.pipeline.config_contract_v26 import build_config_layers
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.replay_engine import ReplayEngine, ReplayValidationError
from src.utils.snapshot_builder_v2 import build_job_snapshot


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls = []

    def run_njr(self, njr, cancel_token=None, run_plan=None, log_fn=None):
        self.calls.append({"njr": njr, "run_plan": run_plan})
        return {"status": "ok"}


def _njr() -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id="replay-validation-001",
        config={"prompt": "castle", "model": "sdxl"},
        path_output_dir="out",
        filename_template="{seed}",
        seed=123,
        intent_config={"run_mode": "queue", "source": "run", "prompt_source": "manual"},
    )


def test_replay_history_record_accepts_snapshot_with_valid_intent_contract() -> None:
    njr = _njr()
    snapshot = build_job_snapshot(type("Job", (), {"job_id": njr.job_id, "source": "gui", "prompt_source": "manual"})(), njr)
    record = HistoryRecord(
        id=njr.job_id,
        timestamp="2025-01-01T00:00:00Z",
        status="completed",
        history_schema=HISTORY_SCHEMA_VERSION,
        njr_snapshot=snapshot,
        metadata={},
        runtime={},
        ui_summary={},
    )
    engine = ReplayEngine(_RecordingRunner())

    result = engine.replay_history_record(record)

    assert result["status"] == "ok"


def test_replay_history_record_rejects_snapshot_with_drifted_intent_hash() -> None:
    njr = _njr()
    snapshot = build_job_snapshot(type("Job", (), {"job_id": njr.job_id, "source": "gui", "prompt_source": "manual"})(), njr)
    snapshot["config_layers"]["intent_hash"] = "bad-hash"
    record = HistoryRecord(
        id=njr.job_id,
        timestamp="2025-01-01T00:00:00Z",
        status="completed",
        history_schema=HISTORY_SCHEMA_VERSION,
        njr_snapshot=snapshot,
        metadata={},
        runtime={},
        ui_summary={},
    )
    engine = ReplayEngine(_RecordingRunner())

    with pytest.raises(ReplayValidationError):
        engine.replay_history_record(record)


def test_replay_history_record_allows_legacy_snapshot_without_contract() -> None:
    njr = _njr()
    record = HistoryRecord(
        id=njr.job_id,
        timestamp="2025-01-01T00:00:00Z",
        status="completed",
        history_schema=HISTORY_SCHEMA_VERSION,
        njr_snapshot={"normalized_job": asdict(njr), "schema_version": HISTORY_SCHEMA_VERSION},
        metadata={},
        runtime={},
        ui_summary={},
    )
    engine = ReplayEngine(_RecordingRunner())

    result = engine.replay_history_record(record)

    assert result["status"] == "ok"
