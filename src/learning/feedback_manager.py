# Subsystem: Learning
# Role: Captures explicit ratings and notes for completed runs.

"""Feedback capture helpers for pipeline runs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def record_feedback(
    run_id: str,
    image_id: str,
    rating: int | float,
    notes: str | None = None,
    *,
    base_dir: str | Path = "runs",
) -> Path:
    """
    Append a feedback entry for a given run.

    Stored at runs/<run_id>/feedback.json as a list of entries.
    """

    run_dir = Path(base_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = run_dir / "feedback.json"

    if feedback_path.exists():
        try:
            existing = json.loads(feedback_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    else:
        existing = []

    entry: dict[str, Any] = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image_id": image_id,
        "rating": rating,
        "notes": notes,
    }
    existing.append(entry)

    feedback_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return feedback_path
