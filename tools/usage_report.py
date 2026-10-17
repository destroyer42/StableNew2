"""Sum the token usage Claude Code and Codex already log locally, for a time window.

Both hosts record per-request usage in their local session logs, so no API or MCP call is needed:

* Claude Code: ``~/.claude/projects/**/*.jsonl`` (including ``subagents/``), one ``usage`` object per model response.
* Codex: ``~/.codex/sessions/**/*.jsonl``, cumulative ``token_count`` events per session.

The report is tokens only. It never converts tokens to a price (cost is not logged and must not be estimated); compare it
with the model recommendation recorded at the start of a package.

    python tools/usage_report.py --since 2026-10-17T09:00 --until 2026-10-17T11:30
    python tools/usage_report.py --since-commit 30f96bf9 --line     # one line for the PR's "Model / usage" section
    python tools/usage_report.py --since 2026-10-17 --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MATCH = "stablenew"
FIELDS = ("fresh_input", "cache_read", "cache_write", "output")


@dataclass
class Usage:
    """Tokens for one (host, model). ``requests`` is model responses (Claude) or token events in the window (Codex)."""

    requests: int = 0
    fresh_input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0
    reasoning: int = 0  # reported separately by Codex; already counted inside ``output``
    sessions: set[str] = field(default_factory=set)

    def add(self, other: Usage) -> None:
        self.requests += other.requests
        for name in (*FIELDS, "reasoning"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.sessions |= other.sessions


Report = dict[tuple[str, str], Usage]


def parse_time(text: str) -> datetime:
    """ISO 8601 with or without zone; a value without a zone is read as local time."""
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.astimezone()


def _matches(cwd: object, match: str) -> bool:
    return not match or match.lower() in str(cwd or "").replace("\\", "/").lower()


def _json_lines(path: Path) -> Iterator[dict]:
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def _files(base: Path, since: datetime) -> Iterable[Path]:
    if not base.is_dir():
        return []
    cutoff = since.timestamp()
    return sorted(path for path in base.rglob("*.jsonl") if path.stat().st_mtime >= cutoff)


def claude_usage(base: Path, since: datetime, until: datetime, match: str) -> Report:
    """Claude Code repeats a response's usage on each streamed content block, so count each message id once (largest wins)."""
    seen: dict[str, tuple[str, str, dict]] = {}
    for path in _files(base, since):
        for record in _json_lines(path):
            message = record.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            stamp = record.get("timestamp")
            if not isinstance(usage, dict) or not stamp or not _matches(record.get("cwd"), match):
                continue
            model = str(message.get("model") or "unknown")
            if model.startswith("<"):  # synthetic placeholder responses carry no real usage
                continue
            when = parse_time(stamp)
            if not since <= when < until:
                continue
            key = str(message.get("id") or record.get("uuid"))
            previous = seen.get(key)
            if previous is None or usage.get("output_tokens", 0) >= previous[2].get(
                "output_tokens", 0
            ):
                seen[key] = (str(record.get("sessionId") or path.stem), model, usage)
    report: Report = defaultdict(Usage)
    for session, model, usage in seen.values():
        row = report[("Claude Code", model)]
        row.requests += 1
        row.fresh_input += int(usage.get("input_tokens", 0))
        row.cache_read += int(usage.get("cache_read_input_tokens", 0))
        row.cache_write += int(usage.get("cache_creation_input_tokens", 0))
        row.output += int(usage.get("output_tokens", 0))
        row.sessions.add(session)
    return dict(report)


def _codex_totals(usage: dict) -> tuple[int, int, int, int, int]:
    cached = int(usage.get("cached_input_tokens", 0))
    return (
        int(usage.get("input_tokens", 0)) - cached,
        cached,
        int(usage.get("cache_write_input_tokens", 0)),
        int(usage.get("output_tokens", 0)),
        int(usage.get("reasoning_output_tokens", 0)),
    )


def codex_usage(base: Path, since: datetime, until: datetime, match: str) -> Report:
    """Codex logs cumulative per-session totals, so a window is the last total inside it minus the last total before it."""
    report: Report = defaultdict(Usage)
    for path in _files(base, since):
        cwd: object = None
        model = "unknown"
        before = (0, 0, 0, 0, 0)
        latest: tuple[int, int, int, int, int] | None = None
        events = 0
        for record in _json_lines(path):
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            kind = record.get("type")
            if kind in ("session_meta", "turn_context"):
                cwd = payload.get("cwd") or cwd
                model = str(payload.get("model") or model)
                continue
            info = payload.get("info") if payload.get("type") == "token_count" else None
            total = info.get("total_token_usage") if isinstance(info, dict) else None
            stamp = record.get("timestamp")
            if not isinstance(total, dict) or not stamp:
                continue
            when = parse_time(stamp)
            totals = _codex_totals(total)
            if when < since:
                before = totals
            elif when < until:
                latest = totals
                events += 1
        if latest is None or not _matches(cwd, match):
            continue
        row = report[("Codex", model)]
        row.requests += events
        row.sessions.add(path.stem)
        for name, end, start in zip((*FIELDS, "reasoning"), latest, before, strict=True):
            setattr(row, name, getattr(row, name) + max(end - start, 0))
    return dict(report)


def combine(*reports: Report) -> Report:
    merged: Report = defaultdict(Usage)
    for report in reports:
        for key, usage in report.items():
            merged[key].add(usage)
    return dict(merged)


def human(value: int) -> str:
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if value >= limit:
            return f"{value / limit:.1f}{suffix}"
    return str(value)


def render_table(report: Report) -> str:
    if not report:
        return "No usage found in the window (check --since/--until and --match)."
    rows = [("host", "model", "requests", "fresh input", "cache read", "cache write", "output")]
    for (host, model), usage in sorted(report.items()):
        rows.append(
            (host, model, str(usage.requests), *(human(getattr(usage, name)) for name in FIELDS))
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def render_line(report: Report) -> str:
    """One line for a PR body: tokens only, explicit that cost is not reported."""
    if not report:
        return "usage unavailable (no host log entries in the window)"
    parts = []
    for (host, model), usage in sorted(report.items()):
        parts.append(
            f"{host} {model}: {usage.requests} requests, fresh input {human(usage.fresh_input)}, cache read {human(usage.cache_read)}, "
            f"cache write {human(usage.cache_write)}, output {human(usage.output)}"
        )
    return "; ".join(parts) + " (tokens from host session logs; cost not reported)"


def render_json(report: Report, since: datetime, until: datetime) -> str:
    return json.dumps(
        {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "rows": [
                {
                    "host": host,
                    "model": model,
                    "requests": usage.requests,
                    "sessions": sorted(usage.sessions),
                    **{name: getattr(usage, name) for name in (*FIELDS, "reasoning")},
                }
                for (host, model), usage in sorted(report.items())
            ],
        },
        indent=2,
    )


def commit_time(ref: str) -> datetime:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI", ref], capture_output=True, text=True, check=False
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"cannot read the commit time of {ref!r}: {result.stderr.strip()}")
    return parse_time(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    start = parser.add_mutually_exclusive_group(required=True)
    start.add_argument(
        "--since", help="window start, ISO 8601 (a value without a zone is local time)"
    )
    start.add_argument(
        "--since-commit", metavar="REF", help="window start at the committer time of this commit"
    )
    end = parser.add_mutually_exclusive_group()
    end.add_argument("--until", help="window end, ISO 8601 (default: now)")
    end.add_argument(
        "--until-commit", metavar="REF", help="window end at the committer time of this commit"
    )
    parser.add_argument(
        "--match",
        default=DEFAULT_MATCH,
        help=f"only sessions whose cwd contains this text (default {DEFAULT_MATCH!r}; '' for all)",
    )
    parser.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--codex-dir", type=Path, default=Path.home() / ".codex" / "sessions")
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--line", action="store_true", help="print one line for the PR 'Model / usage' section"
    )
    output.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    since = parse_time(args.since) if args.since else commit_time(args.since_commit)
    until = (
        parse_time(args.until)
        if args.until
        else commit_time(args.until_commit)
        if args.until_commit
        else datetime.now(UTC)
    )
    if until <= since:
        raise SystemExit("the window must end after it starts")
    report = combine(
        claude_usage(args.claude_dir, since, until, args.match),
        codex_usage(args.codex_dir, since, until, args.match),
    )
    if args.json:
        print(render_json(report, since, until))
    elif args.line:
        print(render_line(report))
    else:
        print(
            f"Usage from {since.isoformat(timespec='minutes')} to {until.isoformat(timespec='minutes')}"
        )
        print(render_table(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
