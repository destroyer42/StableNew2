"""Inspect the offline index, route a task, or emit a bounded context capsule."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from tools import context_index, context_router
from tools.generate_code_map import ROOT

CAPSULE_VERSION = 1
DEFAULT_BUDGET = 1200
MIN_BUDGET = 650
MAX_BUDGET = 4000
PURPOSE = (
    "Navigation only. Read current authority and verify referenced source and tests before editing."
)
VALIDATION = "Start with focused tests. Consult the operating contract for the applicable gate."
LIMITS = "Static syntax only. Dynamic imports, reflection and registrations can hide edges. Test and document references do not prove coverage."
GROUPS = ("docs", "sources", "dependencies", "tests")
GROUP_LABELS = {
    "docs": "Relevant documentation",
    "sources": "Implementation surfaces",
    "dependencies": "Potential impact",
    "tests": "Suggested tests",
}


def markdown_escape(value: str) -> str:
    return re.sub(r"([\\\x60*_\[\]<>|&])", r"\\\1", " ".join(value.split()))


def markdown(data: dict) -> str:
    identity = data["identity"]
    status = "dirty" if identity["dirty"] else "clean"
    lines = [
        "# Task context",
        "",
        "1. Read " + " → ".join(f"\x60{path}\x60" for path in data["authority"]) + ".",
        "2. Read the relevant documentation, then verify selected source paths and tests.",
        "",
        "Task — " + markdown_escape(data["task"]),
        "",
        f"{identity['repository']} · {markdown_escape(identity['checkout'])} · {status}",
        f"HEAD {identity['head']} · corpus SHA-256 {identity['fingerprint']}",
        f"Capsule v{data['schema']} · index v{data['index_schema']} · {data['confidence']}",
        "",
        data["purpose"],
        data["validation"],
        data["limitations"],
    ]
    for group in GROUPS:
        if not data[group]:
            continue
        lines.extend(("", f"## {GROUP_LABELS[group]}", ""))
        for row in data[group]:
            uncertainty = row.get("import_uncertainty", {})
            context = [row["evidence"], row["why"]]
            if row.get("owner"):
                context.append(row["owner"])
            if row.get("issue"):
                context.append(row["issue"])
            context.extend(f"{count} {state}" for state, count in sorted(uncertainty.items()))
            lines.append(
                f"- {markdown_escape(row['path'])} · {markdown_escape(' · '.join(context))}"
            )
    if data["omitted"]:
        lines.extend(("", "More candidates are available with the route command or --broader."))
    return "\n".join(lines) + "\n"


def json_line(data: dict) -> str:
    return context_index.json_text(data) + "\n"


def size_units(value: str) -> int:
    """Conservative approximate tokens at three UTF-8 bytes per unit."""
    return (len(value.encode("utf-8")) + 2) // 3


def capsule(
    index: dict,
    routing: dict,
    budget: int,
    render: Callable[[dict], str],
) -> str:
    if not MIN_BUDGET <= budget <= MAX_BUDGET:
        raise ValueError(f"Choose a capsule budget in {MIN_BUDGET}–{MAX_BUDGET} estimated tokens.")
    result = {
        "schema": CAPSULE_VERSION,
        "index_schema": index["schema"],
        "identity": index["identity"],
        "task": routing["task"],
        "confidence": routing["confidence"],
        "purpose": PURPOSE,
        "authority": [*context_index.AUTHORITY, context_index.TASK_MAP],
        "reading_order": list(GROUPS),
        "validation": VALIDATION,
        "limitations": LIMITS,
        "budget": budget,
        "omitted": True,
        **{group: [] for group in GROUPS},
    }
    if size_units(render(result)) > budget:
        raise ValueError("Task and checkout metadata exceed the selected budget.")
    # Give each evidence type a slot before filling with further ranked candidates.
    seen = set(result["authority"])
    omitted = False
    for rank in range(max(len(routing[group]) for group in GROUPS)):
        for group in ("sources", "docs", "tests", "dependencies"):
            if rank >= len(routing[group]):
                continue
            row = {
                key: value
                for key, value in routing[group][rank].items()
                if key not in ("score", "summary")
            }
            path = row["path"]
            if path in seen:
                continue
            result[group].append(row)
            if size_units(render(result)) > budget:
                result[group].pop()
                omitted = True
            else:
                seen.add(path)
    result["omitted"] = omitted
    rendered = render(result)
    if size_units(rendered) > budget:
        result["omitted"] = True
        rendered = render(result)
    return rendered


def verify(captured: dict, identity: dict) -> None:
    if (
        captured.get("schema") != CAPSULE_VERSION
        or captured.get("index_schema") != context_index.INDEX_VERSION
        or captured.get("identity") != identity
    ):
        raise ValueError("Stale or mismatched capsule. Regenerate it from this checkout.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index", help="Print the generated index as JSON.")
    commands.add_parser("verify", help="Check the freshness of a JSON capsule on stdin.")
    for name in ("route", "capsule"):
        command = commands.add_parser(name)
        command.add_argument("task")
        command.add_argument("--limit", type=int, default=context_router.DEFAULT_RESULTS)
        command.add_argument("--broader", action="store_true")
        if name == "capsule":
            command.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
            command.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            submitted = sys.stdin.buffer.read(16385)
            if len(submitted) > 16384:
                raise ValueError("Expected a JSON capsule no larger than 16,384 bytes.")
            captured = json.loads(submitted)
            if not isinstance(captured, dict):
                raise ValueError("Expected a JSON capsule object.")
            identity, _, _ = context_index.snapshot(args.root)
            verify(captured, identity)
            sys.stdout.write(json_line({"status": "current", "identity": identity}))
            return 0
        if args.command != "index" and not 1 <= len(args.task.strip().encode("utf-8")) <= 480:
            raise ValueError("Supply a task between 1 and 480 UTF-8 bytes.")
        index = context_index.build(args.root)
        if args.command == "index":
            sys.stdout.write(json_line(index))
            return 0
        routing = context_router.route(index, args.task, limit=args.limit, broader=args.broader)
        if args.command == "route":
            sys.stdout.write(
                json_line(
                    {
                        **routing,
                        "index_schema": index["schema"],
                        "identity": index["identity"],
                        "limitations": index["limitations"],
                    }
                )
            )
        else:
            render = json_line if args.format == "json" else markdown
            sys.stdout.write(capsule(index, routing, args.budget, render))
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Repository context unavailable. {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    raise SystemExit(main())
