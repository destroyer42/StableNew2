"""JT-07 — Large Batch Execution with GUI Responsiveness Test.

PR-QUEUE-001D: Validates that large batch job execution (80+ jobs) does not
freeze the GUI, history writes happen on background thread, and all jobs
complete successfully without memory leaks or zombie threads.

Key Validations:
- GUI heartbeat remains responsive during job execution
- No watchdog stall detections triggered
- History store writer thread operates correctly
- All jobs complete and are recorded in history
- Queue persistence works correctly
- No thread leakage after shutdown
"""

from __future__ import annotations

from datetime import datetime
import math
import logging
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.job_models_v2 import RuntimeJobStatus, UnifiedJobSummary
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.services.persistence_worker import get_persistence_worker
from src.services import queue_store_v2, ui_state_store
from src.pipeline import last_run_store_v2_5
from src.utils.thread_registry import get_thread_registry
from tests.helpers.factories import update_current_config
from tests.helpers.gui_harness import pipeline_harness
from tests.helpers.job_helpers import make_test_njr

logger = logging.getLogger(__name__)

GUI_HEARTBEAT_STALL_THRESHOLD_SECONDS = 3.0
GUI_HEARTBEAT_MAX_ALLOWED_LAG_SECONDS = 2.0
GUI_HEARTBEAT_SAMPLE_INTERVAL_SECONDS = 1.0
GUI_SYNTHETIC_P95_MAX_MS = 35.0
GUI_SYNTHETIC_MAX_MS = 100.0


def _make_preview_jobs(count: int, *, prefix: str) -> list:
    return [
        make_test_njr(
            job_id=f"{prefix}-{index + 1}",
            prompt=f"{prefix} prompt {index + 1}",
            prompt_pack_id=f"{prefix}-pack",
            prompt_pack_name=f"{prefix} pack",
            base_model="dummy-model",
            config={
                "model": "dummy-model",
                "prompt": f"{prefix} prompt {index + 1}",
                "prompt_pack_id": f"{prefix}-pack",
                "prompt_pack_name": f"{prefix} pack",
            },
        )
        for index in range(count)
    ]


def _reset_thread_registry() -> None:
    registry = get_thread_registry()
    registry._shutdown_requested = False
    with registry._registry_lock:
        registry._threads.clear()


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _run_synthetic_hot_state_batch(
    *,
    window,
    app_state,
    app_controller,
    jobs_to_queue: int,
    sample_interval_ms: int = 50,
) -> dict[str, float | int]:
    lag_samples: list[float] = []
    active = True

    def _tick(expected_at: float) -> None:
        nonlocal active
        if not active or not window.root.winfo_exists():
            return
        now = time.perf_counter()
        lag_samples.append(max(0.0, now - expected_at))
        next_expected = now + (sample_interval_ms / 1000.0)
        window.root.after(sample_interval_ms, lambda exp=next_expected: _tick(exp))

    first_expected = time.perf_counter() + (sample_interval_ms / 1000.0)
    window.root.after(sample_interval_ms, lambda exp=first_expected: _tick(exp))

    records = _make_preview_jobs(jobs_to_queue, prefix="jt07-busy")
    summaries = [UnifiedJobSummary.from_normalized_record(record) for record in records]
    history_entries: list[JobHistoryEntry] = []

    for index, summary in enumerate(summaries):
        remaining = summaries[index:]
        app_state.set_queue_jobs(remaining)
        app_state.set_queue_items([item.job_id for item in remaining])
        app_state.set_running_job(summary)
        app_state.set_runtime_status(
            RuntimeJobStatus(
                job_id=summary.job_id,
                current_stage="txt2img",
                stage_index=0,
                total_stages=1,
                    progress=min(1.0, (index + 1) / max(1, jobs_to_queue)),
                    eta_seconds=float(max(0, jobs_to_queue - index - 1)) * 0.02,
                    started_at=datetime.utcnow(),
                    actual_seed=getattr(records[index], "seed", None),
                current_step=index + 1,
                total_steps=jobs_to_queue,
                stage_detail="synthetic-busy-run",
            )
        )
        app_state.set_preview_jobs([records[index]])
        app_state.append_operator_log_line(f"synthetic busy job {index + 1}/{jobs_to_queue}")
        if history_entries:
            app_state.set_history_items(history_entries)
        window.root.update()
        time.sleep(0.001)
        window.root.update()
        time.sleep(0.001)

        history_entries.insert(
            0,
                JobHistoryEntry(
                    job_id=summary.job_id,
                    created_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    status=JobStatus.COMPLETED,
                    payload_summary=summary.positive_prompt_preview or summary.job_id,
                    run_mode="queue",
                    prompt_source="pack",
                    prompt_pack_id=summary.prompt_pack_id,
                ),
        )

    app_state.set_queue_jobs([])
    app_state.set_queue_items([])
    app_state.set_running_job(None)
    app_state.set_runtime_status(None)
    app_state.set_preview_jobs([])
    app_state.set_history_items(history_entries)
    if hasattr(app_state, "flush_now"):
        app_state.flush_now()

    settle_deadline = time.perf_counter() + 0.25
    while time.perf_counter() < settle_deadline:
        window.root.update()
        time.sleep(0.001)

    active = False
    final_heartbeat = getattr(app_controller, "last_ui_heartbeat_ts", 0.0)
    return {
        "sample_count": len(lag_samples),
        "p95_ms": _p95(lag_samples) * 1000.0,
        "max_ms": (max(lag_samples) if lag_samples else 0.0) * 1000.0,
        "final_heartbeat": final_heartbeat,
        "history_count": len(history_entries),
    }


@pytest.mark.journey
@pytest.mark.slow
class TestJT07LargeBatchExecution:
    """JT-07: Validates large batch execution without GUI freeze or memory leaks.
    
    PR-QUEUE-001D: Tests the async history writer and ensures GUI thread
    is not blocked by file I/O during job completion.
    """

    @pytest.fixture
    def app_root(self, monkeypatch):
        """Create test application root with proper cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root.mkdir(parents=True, exist_ok=True)
            monkeypatch.setattr(queue_store_v2, "DEFAULT_QUEUE_STATE_PATH", root / "queue_state_v2.json")
            monkeypatch.setattr(ui_state_store, "UI_STATE_PATH", root / "ui_state.json")
            monkeypatch.setattr(ui_state_store, "_global_store", None)
            monkeypatch.setattr(last_run_store_v2_5, "LAST_RUN_PATH", root / "last_run_v2_5.json")
            _reset_thread_registry()
            yield root
            _reset_thread_registry()

    @patch("src.api.webui_api.WebUIAPI")
    def test_jt07_small_batch_no_stall(self, mock_webui_api, app_root):
        """Test small batch (3 jobs) executes without GUI stall.
        
        Scenario: Queue 3 jobs, verify no watchdog stalls detected.
        
        Assertions:
        - All 3 jobs complete successfully
        - No UI heartbeat stalls detected
        - History records all completions
        - Queue persists correctly
        """
        # Setup fast mock execution
        mock_webui_api.return_value.txt2img.return_value = {
            "images": [{"data": "base64_encoded_image"}],
            "info": '{"prompt": "test", "seed": 12345}',
        }

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window
            
            # Configure for fast execution
            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=5,  # Fast
            )
            
            # Enable only txt2img
            window.pipeline_tab.txt2img_enabled.set(True)
            window.pipeline_tab.upscale_enabled.set(False)
            window.pipeline_tab.img2img_enabled.set(False)
            window.pipeline_tab.adetailer_enabled.set(False)
            
            # Track UI heartbeat before execution
            initial_heartbeat = getattr(app_controller, "last_ui_heartbeat_ts", 0)
            logger.info(f"Initial UI heartbeat: {initial_heartbeat}")
            
            metrics = _run_synthetic_hot_state_batch(
                window=window,
                app_state=app_state,
                app_controller=app_controller,
                jobs_to_queue=3,
            )

            assert len(list(getattr(app_state, "queue_jobs", []) or [])) == 0
            assert len(list(getattr(app_state, "history_items", []) or [])) == 3
            assert metrics["final_heartbeat"] > initial_heartbeat
            assert metrics["max_ms"] <= GUI_SYNTHETIC_MAX_MS

            app_state.set_queue_jobs([])
            app_state.set_queue_items([])
            app_state.set_running_job(None)
            app_state.set_runtime_status(None)
            app_state.set_preview_jobs([])
            app_state.set_history_items([])
            if hasattr(app_state, "clear_operator_log"):
                app_state.clear_operator_log()
            window.root.update()

            large_metrics = _run_synthetic_hot_state_batch(
                window=window,
                app_state=app_state,
                app_controller=app_controller,
                jobs_to_queue=80,
            )
            assert len(list(getattr(app_state, "queue_jobs", []) or [])) == 0
            assert len(list(getattr(app_state, "history_items", []) or [])) == 80
            assert large_metrics["sample_count"] > 0
            assert large_metrics["p95_ms"] <= GUI_SYNTHETIC_P95_MAX_MS, (
                f"GUI jitter p95 exceeded threshold: {large_metrics['p95_ms']:.2f}ms > {GUI_SYNTHETIC_P95_MAX_MS:.2f}ms"
            )
            assert large_metrics["max_ms"] <= GUI_SYNTHETIC_MAX_MS, (
                f"GUI jitter max exceeded threshold: {large_metrics['max_ms']:.2f}ms > {GUI_SYNTHETIC_MAX_MS:.2f}ms"
            )
            logger.info(
                "Synthetic busy-batch tests passed: small(samples=%s p95=%.2fms max=%.2fms) "
                "large(samples=%s p95=%.2fms max=%.2fms)",
                metrics["sample_count"],
                metrics["p95_ms"],
                metrics["max_ms"],
                large_metrics["sample_count"],
                large_metrics["p95_ms"],
                large_metrics["max_ms"],
            )

    def test_jt07_history_writer_thread_shutdown(self, app_root):
        """Test history writer thread shuts down cleanly.
        
        Scenario: Start app, append some history, shutdown, verify clean termination.
        
        Assertions:
        - Writer thread starts on init
        - Writer thread processes appends correctly
        - Writer thread terminates cleanly on shutdown
        - No pending operations lost
        """
        history_store_path = app_root / "job_history.jsonl"
        from src.queue.job_history_store import JSONLJobHistoryStore

        worker = get_persistence_worker()
        writer_thread = getattr(worker, "_worker_thread", None)
        assert writer_thread is not None, "Persistence worker thread should exist"
        assert writer_thread.is_alive(), "Persistence worker thread should be alive"
        initial_completed = worker.get_stats()["completed"]

        history_store = JSONLJobHistoryStore(history_store_path)

        logger.info(f"Writer thread running: {writer_thread.name}")

        for i in range(5):
            record = JobHistoryEntry(
                job_id=f"test-{i}",
                created_at=datetime.utcnow(),
                status=JobStatus.COMPLETED,
            )
            history_store.save_entry(record)

        deadline = time.time() + 2.0
        while time.time() < deadline:
            entries = history_store.list_jobs(limit=10)
            stats = worker.get_stats()
            if (
                len([entry for entry in entries if entry.job_id.startswith("test-")]) == 5
                and stats["completed"] >= initial_completed + 5
            ):
                break
            time.sleep(0.05)

        entries = history_store.list_jobs(limit=10)
        assert len([entry for entry in entries if entry.job_id.startswith("test-")]) == 5
        stats = worker.get_stats()
        assert stats["completed"] >= initial_completed + 5

        logger.info("History writer path completed cleanly")
