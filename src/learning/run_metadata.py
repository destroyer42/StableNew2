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
    packs: list[str] | None = None,
    one_click_action: str | None = None,
    stage_outputs: list[dict[str, Any]] | None = None,
    base_dir: str | Path = "runs",
) -> Path:
    """Persist run metadata to runs/<run_id>/run_metadata.json."""

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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
