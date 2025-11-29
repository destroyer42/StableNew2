from __future__ import annotations

import json
from pathlib import Path

from src.learning.dataset_builder import build_learning_dataset, collect_feedback, collect_runs


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def test_dataset_builder_aggregates_runs_and_feedback(tmp_path: Path) -> None:
    base_dir = tmp_path / "runs"
    # Create two runs with metadata and feedback
    run1 = base_dir / "r1"
    run2 = base_dir / "r2"
    _write(run1 / "run_metadata.json", {"run_id": "r1", "packs": ["p1"], "config": {}})
    _write(run2 / "run_metadata.json", {"run_id": "r2", "packs": ["p2"], "config": {}})
    _write(run1 / "feedback.json", [{"image_id": "img-1", "rating": 4}])
    _write(run2 / "feedback.json", [{"image_id": "img-2", "rating": 5}])

    runs = collect_runs(base_dir)
    feedback = collect_feedback(base_dir)
    dataset = build_learning_dataset(base_dir)

    assert len(runs) == 2
    assert {r["run_id"] for r in runs} == {"r1", "r2"}
    assert len(feedback) == 2
    assert dataset["runs"] == runs
    assert dataset["feedback"] == feedback
