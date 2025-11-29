# Subsystem: Learning
# Role: Aggregates pipeline run outputs into datasets for training/evaluation.

"""Dataset aggregation utilities for learning groundwork."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def _iter_run_dirs(base_dir: str | Path) -> Iterable[Path]:
    base = Path(base_dir)
    if not base.exists():
        return []
    return [p for p in base.iterdir() if p.is_dir()]


def collect_runs(base_dir: str | Path = "runs") -> list[dict[str, Any]]:
    """Return run metadata payloads from runs/<run_id>/run_metadata.json."""

    runs: list[dict[str, Any]] = []
    for run_dir in _iter_run_dirs(base_dir):
        meta_path = run_dir / "run_metadata.json"
        if not meta_path.exists():
            continue
        try:
            runs.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return runs


def collect_feedback(base_dir: str | Path = "runs") -> list[dict[str, Any]]:
    """Return feedback entries across all runs."""

    feedback_items: list[dict[str, Any]] = []
    for run_dir in _iter_run_dirs(base_dir):
        feedback_path = run_dir / "feedback.json"
        if not feedback_path.exists():
            continue
        try:
            entries = json.loads(feedback_path.read_text(encoding="utf-8"))
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        entry = dict(entry)
                        entry.setdefault("run_id", run_dir.name)
                        feedback_items.append(entry)
        except Exception:
            continue
    return feedback_items


def build_learning_dataset(base_dir: str | Path = "runs") -> dict[str, Any]:
    """Aggregate runs + feedback into a single dataset structure."""

    runs = collect_runs(base_dir)
    feedback = collect_feedback(base_dir)
    return {
        "runs": runs,
        "feedback": feedback,
    }
