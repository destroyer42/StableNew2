"""Sum the token usage Claude Code and Codex already log locally, for a time window.

Both hosts record per-request usage in their local session logs, so no API or MCP call is needed:

* Claude Code: ``~/.claude/projects/**/*.jsonl`` (including ``subagents/``), one ``usage`` object per model response.
* Codex: ``~/.codex/sessions/**/*.jsonl``, cumulative ``token_count`` events per session.

The report is tokens only. It never converts tokens to a price (cost is not logged and must not be estimated); compare it
with the model recommendation recorded at the start of a package.

    python tools/usage_report.py --since 2026-10-17T09:00 --until 2026-10-17T11:30
    python tools/usage_report.py --since 2026-10-17T09:00Z --until 2026-10-17T11:30Z --session codex:SESSION_ID --line
    python tools/usage_report.py --since-commit 30f96bf9 --line     # post-commit usage only
    python tools/usage_report.py --since 2026-10-17 --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MATCH = "stablenew"
FIELDS = ("fresh_input", "cache_read", "cache_write", "output")
ATTRIBUTION_NOTE = (
    "Session/time-window usage only; a shared session is not an exact package total without "
    "an independently supported boundary. Missing host telemetry is unavailable, not zero."
)


@dataclass
class Usage:
    """Tokens for one (host, model). Legacy ``requests`` counts responses (Claude) or token events (Codex)."""

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


def _files(base: Path) -> list[Path]:
    """Event timestamps are authoritative; mtime cannot safely exclude a log."""
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.jsonl"))


def _timestamp(record: dict) -> datetime | None:
    stamp = record.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        return parse_time(stamp)
    except (ValueError, OverflowError):
        return None


def _tokens(usage: dict, names: tuple[str, ...]) -> tuple[int, ...] | None:
    if not any(name in usage for name in names):
        return None
    values = tuple(usage.get(name, 0) for name in names)
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return values


def _selected(host: str, session: str, sessions: set[str] | None) -> bool:
    return not sessions or f"{host}:{session}" in sessions


def _model_name(value: object) -> str:
    return value if isinstance(value, str) and value.strip() else "unknown"


def claude_usage(
    base: Path, since: datetime, until: datetime, match: str, sessions: set[str] | None = None
) -> Report:
    """Deduplicate streamed chunks within each session/log stream (largest output wins)."""
    report: Report = defaultdict(Usage)
    for path in _files(base):
        seen: dict[tuple[str, str], tuple[str, tuple[int, ...]]] = {}
        for record in _json_lines(path):
            message = record.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            when = _timestamp(record)
            if (
                not isinstance(usage, dict)
                or when is None
                or not _matches(record.get("cwd"), match)
            ):
                continue
            model = _model_name(message.get("model"))
            if model.startswith("<"):  # synthetic placeholder responses carry no real usage
                continue
            if not since <= when < until:
                continue
            session = str(record.get("sessionId") or path.stem)
            if not _selected("claude", session, sessions):
                continue
            counts = _tokens(
                usage,
                (
                    "input_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                    "output_tokens",
                ),
            )
            response_id = message.get("id") or record.get("uuid")
            if counts is None or not response_id:
                continue  # no supported identity for stream deduplication
            key = (session, str(response_id))
            previous = seen.get(key)
            if previous is None or counts[3] >= previous[1][3]:
                seen[key] = (model, counts)
        for (session, _), (model, counts) in seen.items():
            row = report[("Claude Code", model)]
            row.requests += 1
            for name, count in zip(FIELDS, counts, strict=True):
                setattr(row, name, getattr(row, name) + count)
            row.sessions.add(session)
    return dict(report)


def _codex_totals(usage: dict) -> tuple[int, ...] | None:
    if "input_tokens" not in usage or "output_tokens" not in usage:
        return None  # a partial snapshot cannot establish a cumulative baseline
    counts = _tokens(
        usage,
        (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ),
    )
    if counts is None:
        return None
    inp, cached, written, out, reasoning = counts
    if cached > inp or reasoning > out:
        return None
    return inp - cached, cached, written, out, reasoning


def codex_usage(
    base: Path, since: datetime, until: datetime, match: str, sessions: set[str] | None = None
) -> Report:
    """Attribute each cumulative-counter delta to its active context, including a pre-window baseline."""
    report: Report = defaultdict(Usage)
    for path in _files(base):
        cwd: object = None
        model = "unknown"
        session = path.stem
        previous = (0, 0, 0, 0, 0)
        for record in _json_lines(path):
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            kind = record.get("type")
            if kind in ("session_meta", "turn_context"):
                cwd = payload.get("cwd") or cwd
                model = _model_name(payload.get("model"))
                if kind == "session_meta":
                    session = str(payload.get("id") or path.stem)
                continue
            info = payload.get("info") if payload.get("type") == "token_count" else None
            total = info.get("total_token_usage") if isinstance(info, dict) else None
            when = _timestamp(record)
            if not isinstance(total, dict) or when is None:
                continue
            totals = _codex_totals(total)
            if totals is None:
                continue
            if (
                since <= when < until
                and _matches(cwd, match)
                and _selected("codex", session, sessions)
            ):
                row = report[("Codex", model)]
                row.requests += 1  # token events, not model responses
                row.sessions.add(session)
                for name, end, start in zip((*FIELDS, "reasoning"), totals, previous, strict=True):
                    setattr(row, name, getattr(row, name) + max(end - start, 0))
            previous = totals
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


def _count_label(host: str, usage: Usage) -> str:
    return f"{usage.requests} " + ("token events" if host == "Codex" else "responses")


def render_table(report: Report) -> str:
    if not report:
        return "No usage found in the window (check --since/--until and --match)."
    rows = [
        (
            "host",
            "model",
            "responses/events",
            "fresh input",
            "cache read",
            "cache write",
            "output",
            "reasoning (in output)",
        )
    ]
    for (host, model), usage in sorted(report.items()):
        rows.append(
            (
                host,
                model,
                _count_label(host, usage),
                *(human(getattr(usage, name)) for name in (*FIELDS, "reasoning")),
            )
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
            f"{host} {model}: {_count_label(host, usage)}, fresh input {human(usage.fresh_input)}, cache read {human(usage.cache_read)}, "
            f"cache write {human(usage.cache_write)}, output {human(usage.output)}, reasoning {human(usage.reasoning)} (in output)"
        )
    return "; ".join(parts) + " (tokens from host session logs; cost not reported)"


def render_json(
    report: Report,
    since: datetime,
    until: datetime,
    *,
    match: str = DEFAULT_MATCH,
    sessions: set[str] | None = None,
) -> str:
    return json.dumps(
        {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "match": match,
            "selected_sessions": sorted(sessions or ()),
            "attribution_note": ATTRIBUTION_NOTE,
            "rows": [
                {
                    "host": host,
                    "model": model,
                    "requests": usage.requests,
                    "request_unit": "token_events" if host == "Codex" else "responses",
                    "responses": None if host == "Codex" else usage.requests,
                    "token_events": usage.requests if host == "Codex" else None,
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


def session_selector(text: str) -> str:
    host, separator, identity = text.partition(":")
    if host not in ("claude", "codex") or not separator or not identity:
        raise argparse.ArgumentTypeError("expected claude:SESSION_ID or codex:SESSION_ID")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    start = parser.add_mutually_exclusive_group(required=True)
    start.add_argument(
        "--since", help="window start, ISO 8601 (a value without a zone is local time)"
    )
    start.add_argument(
        "--since-commit",
        metavar="REF",
        help="post-commit window start at committer time; excludes earlier package work",
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
    parser.add_argument(
        "--session",
        action="append",
        type=session_selector,
        default=[],
        metavar="HOST:ID",
        help="restrict to claude:ID or codex:ID (repeat for a union); cwd filter still applies",
    )
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
    sessions = set(args.session)
    report = combine(
        claude_usage(args.claude_dir, since, until, args.match, sessions),
        codex_usage(args.codex_dir, since, until, args.match, sessions),
    )
    if args.json:
        print(render_json(report, since, until, match=args.match, sessions=sessions))
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
