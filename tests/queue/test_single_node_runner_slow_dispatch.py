"""Slow between-job bookkeeping is attributed in the log (observation only)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from src.queue.single_node_runner import SLOW_DISPATCH_PHASE_SECONDS, SingleNodeJobRunner


def _runner() -> SingleNodeJobRunner:
    return SingleNodeJobRunner.__new__(SingleNodeJobRunner)


def test_fast_dispatch_logs_nothing(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="src.queue.single_node_runner")

    _runner()._log_slow_dispatch(None, hold_check_s=0.01, prepare_s=0.02, claim_s=0.03)

    assert not [r for r in caplog.records if "QUEUE_DISPATCH_SLOW" in r.getMessage()]


def test_slow_phase_is_logged_with_its_breakdown(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="src.queue.single_node_runner")

    _runner()._log_slow_dispatch(
        SimpleNamespace(job_id="job-2"),
        hold_check_s=0.0,
        prepare_s=SLOW_DISPATCH_PHASE_SECONDS + 8.5,
        claim_s=0.1,
    )

    records = [r for r in caplog.records if "QUEUE_DISPATCH_SLOW" in r.getMessage()]
    assert len(records) == 1
    text = records[0].getMessage() + str(records[0].__dict__)
    assert "10500" in text and "prepare_runtime_ms" in text
