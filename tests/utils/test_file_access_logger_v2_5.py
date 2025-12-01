from __future__ import annotations

import json
from pathlib import Path

from src.utils.file_access_log_v2_5_2025_11_26 import FileAccessLogger


def test_file_access_logger_writes_entry(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "file.log"
    target = tmp_path / "example.txt"
    target.write_text("ok", encoding="utf-8")
    logger = FileAccessLogger(log_path)
    logger.record(target, reason="scan")
    logger.record(target, reason="scan")

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["path"] == str(target.resolve())
    assert entry["reason"] == "scan"
