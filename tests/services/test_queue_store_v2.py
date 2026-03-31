from __future__ import annotations

import json
from pathlib import Path

from src.services import queue_store_v2


def test_save_queue_snapshot_uses_unique_temp_path_per_write(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "queue_state_v2.json"
    recorded_paths: list[Path] = []

    def fake_write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
        output_path = Path(path)
        recorded_paths.append(output_path)
        output_path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")

    monkeypatch.setattr(queue_store_v2._QUEUE_CODEC, "write_jsonl", fake_write_jsonl)
    snapshot = queue_store_v2.QueueSnapshotV1(jobs=[], auto_run_enabled=False, paused=False)

    assert queue_store_v2.save_queue_snapshot(snapshot, path=state_path) is True
    assert queue_store_v2.save_queue_snapshot(snapshot, path=state_path) is True

    temp_paths = [path for path in recorded_paths if path != state_path]
    assert len(temp_paths) == 2
    assert temp_paths[0] != temp_paths[1]
    assert all(path.parent == tmp_path for path in temp_paths)
    assert all(path.name.startswith("queue_state_v2.json.") for path in temp_paths)
    assert all(path.name.endswith(".tmp") for path in temp_paths)