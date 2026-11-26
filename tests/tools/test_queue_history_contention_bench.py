"""The queue/History contention benchmark runs hermetically on a tiny temporary database (PR-QUEUE-LOCK-IO-N9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.diagnostics import queue_history_contention_bench as bench


def test_bench_drains_a_tiny_copy_shaped_database(tmp_path: Path, capsys):
    db = tmp_path / "bench.sqlite3"

    exit_code = bench.main(
        ["--db", str(db), "--rows", "40", "--queued", "4", "--cycles", "4", "--json"]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["drain"]["errors"] == []
    assert report["drain"]["cycles_completed"] == 4
    assert report["history_query"]["n"] == 5
    assert report["drain"]["claim"]["n"] >= 4


def test_bench_rebuilds_queued_rows_and_reuses_the_filler(tmp_path: Path, capsys):
    db = tmp_path / "bench.sqlite3"
    for _ in range(2):
        assert (
            bench.main(
                ["--db", str(db), "--rows", "30", "--queued", "3", "--cycles", "3", "--json"]
            )
            == 0
        )
    second = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (
        second["drain"]["cycles_completed"] == 3
    )  # the previous run's completed jobs were replaced


def test_bench_refuses_a_state_directory(tmp_path: Path):
    with pytest.raises(SystemExit):
        bench.main(["--db", str(tmp_path / "state" / "jobs.sqlite3"), "--rows", "1"])
