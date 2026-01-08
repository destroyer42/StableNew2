# Subsystem: Learning
# Role: Captures structured metadata for each learning run.

"""Helpers for run metadata capture."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def write_run_metadata(
    run_id: str,
    config_snapshot: dict[str, Any],
    *,
    packs: list[dict[str, Any]] | None = None,
    one_click_action: str | None = None,
    stage_outputs: list[dict[str, Any]] | None = None,
    base_dir: str | Path = "runs",
    async_write: bool = True,
) -> Path:
    """Persist run metadata to runs/<run_id>/run_metadata.json.
    
    PR-HB-004: Now uses async persistence worker by default to avoid UI blocking.
    
    Args:
        async_write: If True (default), enqueue write to background worker.
                     If False, write synchronously (for tests or critical paths).
    """

    base = Path(base_dir)
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "run_id": run_id,
        "timestamp": _utc_iso(),
        "packs": packs or [],
        "one_click_action": one_click_action,
        "config": config_snapshot or {},
        "stage_outputs": stage_outputs or [],
    }

    path = run_dir / "run_metadata.json"
    
    if async_write:
        # PR-HB-004: Enqueue to background worker
        from src.services.persistence_worker import get_persistence_worker, PersistenceTask
        
        worker = get_persistence_worker()
        task = PersistenceTask(
            task_type="run_metadata",
            data={"file_path": str(path), "payload": payload},
            priority=1,  # Critical - always process
        )
        worker.enqueue(task, critical=True)
    else:
        # Synchronous write (tests, critical paths)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    
    return path
