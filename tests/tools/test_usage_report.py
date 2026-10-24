"""tools/usage_report.py sums host-logged tokens for a window without estimating cost."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
    assert payload["rows"][0]["responses"] == 2
    assert payload["rows"][0]["token_events"] is None
    assert payload["rows"][0]["request_unit"] == "responses"


def test_an_empty_or_missing_log_directory_reports_nothing(tmp_path: Path) -> None:
    usage = _module()
    since, until = _utc("2026-10-17T09:00:00"), _utc("2026-10-17T10:00:00")
    assert usage.claude_usage(tmp_path / "missing", since, until, "stablenew") == {}
    assert usage.codex_usage(tmp_path / "missing", since, until, "stablenew") == {}


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_old_mtime_does_not_exclude_in_window_events(tmp_path: Path, host: str) -> None:
    usage = _module()
    path = tmp_path / "stale.jsonl"
    records = (
        [_claude("2026-10-17T10:00:00Z", "m1", out=20)]
        if host == "claude"
        else [
            *_codex_meta("StableNew", "model-a"),
            _codex_total("2026-10-17T10:00:00Z", inp=100, cached=40, out=20),
        ]
    )
    _write(path, records)
    os.utime(path, (1, 1))
    report = getattr(usage, f"{host}_usage")(
        tmp_path, _utc("2026-10-17T09:00:00"), _utc("2026-10-17T11:00:00"), "stablenew"
    )
    assert sum(row.output for row in report.values()) == 20


def test_claude_response_ids_are_scoped_to_session_and_stream(tmp_path: Path) -> None:
    usage = _module()
    first = _claude("2026-10-17T10:00:00Z", "same-id", out=20)
    second = _claude("2026-10-17T10:01:00Z", "same-id", out=30)
    second["sessionId"] = "s2"
    _write(tmp_path / "s1.jsonl", [first, first])
    _write(tmp_path / "s2.jsonl", [second, second])
    # A subagent can share the parent session and a response ID in its own stream.
    _write(tmp_path / "s1" / "subagents" / "agent-a.jsonl", [first, first])
    report = usage.claude_usage(
        tmp_path, _utc("2026-10-17T09:00:00"), _utc("2026-10-17T11:00:00"), "stablenew"
    )
    row = report[("Claude Code", "claude-sonnet-5-5")]
    assert (row.requests, row.output, row.fresh_input) == (3, 70, 6)
    assert row.sessions == {"s1", "s2"}
    selected = usage.claude_usage(
        tmp_path,
        _utc("2026-10-17T09:00:00"),
        _utc("2026-10-17T11:00:00"),
        "stablenew",
        {"claude:s1"},
    )
    assert selected[("Claude Code", "claude-sonnet-5-5")].output == 40


def test_codex_model_switching_uses_event_deltas_and_keeps_unknown(tmp_path: Path) -> None:
    usage = _module()
    _write(
        tmp_path / "switch.jsonl",
        [
            {"type": "session_meta", "payload": {"id": "session-a", "cwd": "StableNew"}},
            _codex_total("2026-10-17T09:59:00Z", inp=100, cached=40, out=10),
            _codex_total("2026-10-17T10:00:00Z", inp=150, cached=60, out=20, reasoning=3),
            {"type": "turn_context", "payload": {"model": "model-a"}},
            _codex_total("2026-10-17T10:01:00Z", inp=250, cached=100, out=40, reasoning=8),
            # Duplicate snapshots remain token events, not additional token usage/responses.
            _codex_total("2026-10-17T10:01:01Z", inp=250, cached=100, out=40, reasoning=8),
            {"type": "turn_context", "payload": {"model": "model-b"}},
            _codex_total("2026-10-17T10:02:00Z", inp=450, cached=220, out=70, reasoning=15),
            _codex_total("2026-10-17T11:00:00Z", inp=900, cached=400, out=200, reasoning=40),
            {"type": "turn_context", "payload": {"model": "future-model"}},
        ],
    )
    since, until = _utc("2026-10-17T10:00:00"), _utc("2026-10-17T11:00:00")
    report = usage.codex_usage(tmp_path, since, until, "stablenew")
    assert set(report) == {("Codex", model) for model in ("unknown", "model-a", "model-b")}
    assert (report[("Codex", "model-a")].fresh_input, report[("Codex", "model-a")].output) == (
        60,
        20,
    )
    assert report[("Codex", "model-b")].cache_read == 120
    assert sum(row.output for row in report.values()) == 60
    assert sum(row.reasoning for row in report.values()) == 15  # already in the 60 output tokens
    payload = json.loads(usage.render_json(report, since, until))
    assert all(row["sessions"] == ["session-a"] for row in payload["rows"])
    assert all(row["responses"] is None for row in payload["rows"])
    assert sum(row["token_events"] for row in payload["rows"]) == 4
    assert all(
        row["requests"] == row["token_events"] and row["request_unit"] == "token_events"
        for row in payload["rows"]
    )
    assert "token events" in usage.render_line(report)
    assert "reasoning" in usage.render_table(report)


def test_cli_timestamp_window_includes_pre_commit_work(tmp_path: Path, monkeypatch, capsys) -> None:
    usage = _module()
    _write(
        tmp_path / "claude" / "s1.jsonl",
        [
            _claude("2026-10-17T09:00:00Z", "implementation", out=40),
            _claude("2026-10-17T10:00:00Z", "closeout", out=10),
            _claude("2026-10-17T11:00:00Z", "excluded-end", out=999),
        ],
    )
    refs = {"first": _utc("2026-10-17T10:00:00"), "end": _utc("2026-10-17T11:00:00")}
    monkeypatch.setattr(usage, "commit_time", refs.__getitem__)
    common = [
        "--claude-dir",
        str(tmp_path / "claude"),
        "--codex-dir",
        str(tmp_path / "absent"),
        "--json",
    ]
    assert (
        usage.main(["--since", "2026-10-17T09:00:00Z", "--until", "2026-10-17T11:00:00Z", *common])
        == 0
    )
    full = json.loads(capsys.readouterr().out)
    assert full["rows"][0]["output"] == 50
    assert usage.main(["--since-commit", "first", "--until-commit", "end", *common]) == 0
    post_commit = json.loads(capsys.readouterr().out)
    assert post_commit["rows"][0]["output"] == 10


def test_cli_session_filters_are_host_qualified_and_json_is_stable(tmp_path: Path, capsys) -> None:
    usage = _module()
    for session, out in (("selected", 20), ("unrelated", 999)):
        record = _claude("2026-10-17T10:00:00Z", "m", out=out)
        record["sessionId"] = session
        _write(tmp_path / "claude" / f"{session}.jsonl", [record])
        meta = _codex_meta("StableNew", "model-a")
        meta[0]["payload"]["id"] = session
        _write(
            tmp_path / "codex" / f"file-{session}.jsonl",
            [*meta, _codex_total("2026-10-17T10:00:00Z", inp=100, cached=40, out=out)],
        )
    args = [
        "--since",
        "2026-10-17T09:00:00Z",
        "--until",
        "2026-10-17T11:00:00Z",
        "--claude-dir",
        str(tmp_path / "claude"),
        "--codex-dir",
        str(tmp_path / "codex"),
        "--session",
        "claude:selected",
        "--session",
        "codex:selected",
        "--json",
    ]
    usage.main(args)
    first = capsys.readouterr().out
    usage.main(args)
    assert capsys.readouterr().out == first
    payload = json.loads(first)
    assert len(payload["rows"]) == 2
    assert all(row["sessions"] == ["selected"] and row["output"] == 20 for row in payload["rows"])
    assert "shared" in payload["attribution_note"]
    usage.main([*args, "--session", "codex:missing"])
    assert json.loads(capsys.readouterr().out)["rows"] == payload["rows"]  # selection is a union
    usage.main([*args[:-5], "--session", "codex:selected", "--json"])
    assert [row["host"] for row in json.loads(capsys.readouterr().out)["rows"]] == ["Codex"]


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_malformed_records_are_skipped_without_losing_valid_usage(
    tmp_path: Path, host: str
) -> None:
    usage = _module()
    valid = (
        _claude("2026-10-17T10:00:00Z", "valid", out=20)
        if host == "claude"
        else _codex_total("2026-10-17T10:00:00Z", inp=100, cached=40, out=20)
    )
    bad_time = json.loads(json.dumps(valid))
    bad_time["timestamp"] = "not-a-time"
    bad_tokens = json.loads(json.dumps(valid))
    tokens = (
        bad_tokens["message"]["usage"]
        if host == "claude"
        else bad_tokens["payload"]["info"]["total_token_usage"]
    )
    tokens["output_tokens"] = {"bad": "type"}
    empty_usage = json.loads(json.dumps(valid))
    if host == "claude":
        empty_usage["message"]["usage"] = {}
    else:
        empty_usage["payload"]["info"]["total_token_usage"] = {}
    path = tmp_path / "malformed.jsonl"
    _write(
        path, [*_codex_meta("StableNew", "model-a"), {}, bad_time, bad_tokens, valid, empty_usage]
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write('broken json\n[]\nnull\n"text"\n\n')
    report = getattr(usage, f"{host}_usage")(
        tmp_path, _utc("2026-10-17T09:00:00"), _utc("2026-10-17T11:00:00"), "stablenew"
    )
    assert sum(row.output for row in report.values()) == 20
    assert sum(row.requests for row in report.values()) == 1


def test_codex_cwd_and_missing_model_context_apply_at_each_event(tmp_path: Path) -> None:
    usage = _module()
    before = _codex_total("2026-10-17T09:30:00Z", inp=100, cached=40, out=10)
    inside = _codex_total("2026-10-17T10:00:00Z", inp=200, cached=80, out=20)
    inside["payload"]["info"]["total_token_usage"]["cache_write_input_tokens"] = 7
    _write(
        tmp_path / "changing-cwd.jsonl",
        [
            *_codex_meta("Unrelated", "earlier-model"),
            before,
            # A context without a model must not inherit an unsupported model attribution.
            {"type": "turn_context", "payload": {"cwd": "StableNew"}},
            inside,
            {"type": "turn_context", "payload": {"cwd": "Unrelated", "model": "later-model"}},
            _codex_total("2026-10-17T10:30:00Z", inp=900, cached=400, out=90),
        ],
    )
    report = usage.codex_usage(
        tmp_path, _utc("2026-10-17T09:00:00"), _utc("2026-10-17T11:00:00"), "stablenew"
    )
    assert set(report) == {("Codex", "unknown")}
    row = report[("Codex", "unknown")]
    assert (row.fresh_input, row.cache_read, row.cache_write, row.output) == (60, 40, 7, 10)
    assert row.sessions == {"changing-cwd"}  # no metadata ID: filename fallback
    assert (
        usage.codex_usage(
            tmp_path,
            _utc("2026-10-17T09:00:00"),
            _utc("2026-10-17T11:00:00"),
            "missing-project",
            {"codex:changing-cwd"},
        )
        == {}
    )  # session selection never bypasses the cwd filter


@pytest.mark.parametrize("selector", ["bare-id", "other:session", "codex:", "claude:"])
def test_cli_rejects_ambiguous_session_selectors(selector: str, capsys) -> None:
    usage = _module()
    with pytest.raises(SystemExit) as error:
        usage.main(["--since", "2026-10-17", "--session", selector])
    assert error.value.code == 2
    assert "expected claude:SESSION_ID or codex:SESSION_ID" in capsys.readouterr().err


def test_cli_rejects_empty_or_reversed_window() -> None:
    usage = _module()
    with pytest.raises(SystemExit, match="end after it starts"):
        usage.main(["--since", "2026-10-17T10:00Z", "--until", "2026-10-17T10:00Z"])


def test_codex_partial_snapshot_cannot_reset_the_pre_window_baseline(tmp_path: Path) -> None:
    usage = _module()
    partial = _codex_total("2026-10-17T09:59:00Z", inp=150, cached=60, out=17)
    partial["payload"]["info"]["total_token_usage"] = {"output_tokens": 17}
    _write(
        tmp_path / "partial.jsonl",
        [
            *_codex_meta("StableNew", "model-a"),
            _codex_total("2026-10-17T09:30:00Z", inp=100, cached=40, out=10),
            partial,
            _codex_total("2026-10-17T10:00:00Z", inp=200, cached=80, out=20),
        ],
    )
    report = usage.codex_usage(
        tmp_path, _utc("2026-10-17T10:00:00"), _utc("2026-10-17T11:00:00"), "stablenew"
    )
    row = report[("Codex", "model-a")]
    assert (row.fresh_input, row.cache_read, row.output, row.requests) == (60, 40, 10, 1)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_malformed_model_is_unknown_instead_of_invented(tmp_path: Path, host: str) -> None:
    usage = _module()
    records = (
        [_claude("2026-10-17T10:00:00Z", "m1", out=20, model=None)]
        if host == "claude"
        else [
            *_codex_meta("StableNew", {"unexpected": "object"}),
            _codex_total("2026-10-17T10:00:00Z", inp=100, cached=40, out=20),
        ]
    )
    _write(tmp_path / "unknown-model.jsonl", records)
    report = getattr(usage, f"{host}_usage")(
        tmp_path, _utc("2026-10-17T09:00:00"), _utc("2026-10-17T11:00:00"), "stablenew"
    )
    assert set(report) == {("Claude Code" if host == "claude" else "Codex", "unknown")}
