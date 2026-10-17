"""tools/usage_report.py sums host-logged tokens for a window without estimating cost."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "usage_report_under_test", ROOT / "tools" / "usage_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves the defining module by name
    spec.loader.exec_module(module)
    return module


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _claude(
    stamp: str,
    message_id: str,
    *,
    out: int,
    cwd: str = r"C:\work\StableNew",
    model: str = "claude-sonnet-5-5",
) -> dict:
    return {
        "timestamp": stamp,
        "uuid": f"u-{stamp}-{out}",
        "cwd": cwd,
        "sessionId": "s1",
        "message": {
            "id": message_id,
            "model": model,
            "role": "assistant",
            "usage": {
                "input_tokens": 2,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 300,
                "output_tokens": out,
            },
        },
    }


def test_claude_counts_each_response_once_and_only_inside_the_window(tmp_path: Path) -> None:
    usage = _module()
    _write(
        tmp_path / "proj" / "s1.jsonl",
        [
            _claude("2026-10-17T10:00:00Z", "m1", out=10),  # streamed block 1 of m1
            _claude(
                "2026-10-17T10:00:01Z", "m1", out=40
            ),  # streamed block 2 of m1: the larger output wins, counted once
            _claude("2026-10-17T11:00:00Z", "m2", out=5),
            _claude("2026-10-17T09:00:00Z", "early", out=999),  # before the window
            _claude("2026-10-17T13:00:00Z", "late", out=999),  # after the window
            _claude(
                "2026-10-17T10:30:00Z", "syn", out=7, model="<synthetic>"
            ),  # placeholder response
            _claude(
                "2026-10-17T10:40:00Z", "other", out=7, cwd=r"C:\elsewhere\project"
            ),  # different project
        ],
    )
    _write(
        tmp_path / "proj" / "s1" / "subagents" / "agent-1.jsonl",
        [_claude("2026-10-17T10:10:00Z", "sub1", out=100)],
    )
    for path in tmp_path.rglob("*.jsonl"):  # file pruning is by mtime; make every file recent
        path.touch()
    report = usage.claude_usage(
        tmp_path, _utc("2026-10-17T09:30:00"), _utc("2026-10-17T12:00:00"), "stablenew"
    )
    row = report[("Claude Code", "claude-sonnet-5-5")]
    assert row.requests == 3  # m1 once, m2, and the subagent response
    assert row.output == 40 + 5 + 100
    assert row.cache_read == 3000
    assert row.cache_write == 900
    assert row.fresh_input == 6


def _codex_meta(cwd: str, model: str) -> list[dict]:
    return [
        {"timestamp": "2026-10-17T08:00:00Z", "type": "session_meta", "payload": {"cwd": cwd}},
        {
            "timestamp": "2026-10-17T08:00:01Z",
            "type": "turn_context",
            "payload": {"cwd": cwd, "model": model},
        },
    ]


def _codex_total(stamp: str, *, inp: int, cached: int, out: int, reasoning: int = 0) -> dict:
    total = {
        "input_tokens": inp,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": 0,
        "output_tokens": out,
        "reasoning_output_tokens": reasoning,
    }
    return {
        "timestamp": stamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": total}},
    }


def test_codex_window_is_the_difference_of_cumulative_totals(tmp_path: Path) -> None:
    usage = _module()
    _write(
        tmp_path / "2026" / "10" / "17" / "rollout-a.jsonl",
        [
            *_codex_meta(r"C:\Users\rob\projects\StableNew-main", "gpt-6.1-sol"),
            _codex_total("2026-10-17T08:30:00Z", inp=1000, cached=600, out=50),  # before the window
            _codex_total("2026-10-17T10:00:00Z", inp=3000, cached=2000, out=150, reasoning=20),
            _codex_total("2026-10-17T11:00:00Z", inp=5000, cached=3500, out=250, reasoning=60),
            _codex_total(
                "2026-10-17T13:00:00Z", inp=9000, cached=7000, out=900
            ),  # after the window
        ],
    )
    _write(
        tmp_path / "2026" / "10" / "17" / "rollout-b.jsonl",
        [
            *_codex_meta(r"C:\Users\rob\Documents\OtherProject", "gpt-6.1-sol"),
            _codex_total("2026-10-17T10:00:00Z", inp=999, cached=0, out=999),
        ],
    )
    for path in tmp_path.rglob("*.jsonl"):
        path.touch()
    report = usage.codex_usage(
        tmp_path, _utc("2026-10-17T09:00:00"), _utc("2026-10-17T12:00:00"), "stablenew"
    )
    assert list(report) == [("Codex", "gpt-6.1-sol")]
    row = report[("Codex", "gpt-6.1-sol")]
    assert row.requests == 2
    assert row.cache_read == 3500 - 600
    assert row.fresh_input == (5000 - 3500) - (1000 - 600)
    assert row.output == 250 - 50
    assert row.reasoning == 60


def test_rendering_reports_tokens_only_and_never_a_cost(tmp_path: Path) -> None:
    usage = _module()
    row = usage.Usage(
        requests=2, fresh_input=1500, cache_read=2_500_000, cache_write=10, output=3200
    )
    report = {("Claude Code", "claude-sonnet-5-5"): row}
    line = usage.render_line(report)
    assert "cache read 2.5M" in line and "output 3.2k" in line and "cost not reported" in line
    assert "$" not in line and "$" not in usage.render_table(report)
    assert usage.render_line({}).startswith("usage unavailable")
    payload = json.loads(
        usage.render_json(report, _utc("2026-10-17T09:00:00"), _utc("2026-10-17T10:00:00"))
    )
    assert payload["rows"][0]["output"] == 3200


def test_an_empty_or_missing_log_directory_reports_nothing(tmp_path: Path) -> None:
    usage = _module()
    since, until = _utc("2026-10-17T09:00:00"), _utc("2026-10-17T10:00:00")
    assert usage.claude_usage(tmp_path / "missing", since, until, "stablenew") == {}
    assert usage.codex_usage(tmp_path / "missing", since, until, "stablenew") == {}
