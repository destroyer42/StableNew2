"""Per-file mypy ratchet over all of ``src`` (audit P1-4).

The ten-file smoke gate (``run_mypy_smoke.py``) proves a few typed seams. This gate covers the whole application with the
project's strict configuration, but as a *ratchet* rather than a target: a file may never have more mypy errors than its
checked-in baseline, a file absent from the baseline must have none, and any improvement must be locked in by lowering the
baseline. The existing debt is therefore tolerated and cannot grow, and every clean file stays clean.

Counts must be identical on every machine, so mypy runs with ``--no-site-packages`` (installed third-party packages cannot
change what is inferred), ``--platform linux`` and ``--python-version 3.14``, and unresolved-import errors are ignored.
Third-party values are therefore ``Any``; this ratchet measures StableNew's own typing, not its dependencies'.

    python tools/ci/run_mypy_ratchet.py            # check against tools/ci/mypy_baseline.json
    python tools/ci/run_mypy_ratchet.py --update   # rewrite the baseline after a deliberate improvement
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "tools" / "ci" / "mypy_baseline.json"
SCHEMA_VERSION = 1

#: Environment-dependent by nature (what is installed), so never counted.
IGNORED_CODES = frozenset({"import-not-found", "import-untyped", "import"})

MYPY_ARGS = (
    "--config-file",
    "pyproject.toml",
    "--no-site-packages",
    "--platform",
    "linux",
    "--python-version",
    "3.14",
    "--show-error-codes",
    "--hide-error-context",
    "--no-error-summary",
    "--no-color-output",
    "--no-pretty",
)

_ERROR_LINE = re.compile(r"^(?P<path>[^:\n]+\.pyi?):\d+(?::\d+)?: error: .*\[(?P<code>[\w-]+)\]\s*$")


def parse_counts(output: str) -> dict[str, int]:
    """Errors per ``src`` file (POSIX paths), excluding environment-dependent import errors."""

    counts: Counter[str] = Counter()
    for line in output.splitlines():
        match = _ERROR_LINE.match(line.strip())
        if not match or match.group("code") in IGNORED_CODES:
            continue
        path = match.group("path").replace("\\", "/")
        if path.startswith("src/"):
            counts[path] += 1
    return dict(sorted(counts.items()))


def compare(current: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """Human-readable problems; empty when no file regressed and no improvement is left unrecorded."""

    problems: list[str] = []
    for path in sorted(set(current) | set(baseline)):
        have, allowed = current.get(path, 0), baseline.get(path, 0)
        if have > allowed:
            where = "a file with no mypy errors" if allowed == 0 else f"baseline {allowed}"
            problems.append(f"REGRESSION: {path}: {have} mypy error(s) ({where}); fix them, do not raise the baseline")
        elif have < allowed:
            problems.append(
                f"IMPROVED: {path}: {have} mypy error(s), baseline {allowed}; run "
                "`python tools/ci/run_mypy_ratchet.py --update` to lock the improvement in"
            )
    return problems


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path.name}: unsupported schema_version {data.get('schema_version')!r}")
    return {str(k): int(v) for k, v in data["counts"].items()}


def write_baseline(counts: dict[str, int], path: Path = BASELINE_PATH) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "metric": "mypy errors per src file, strict, --no-site-packages --platform linux --python-version 3.14",
        "total": sum(counts.values()),
        "counts": counts,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def run_mypy() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "src", *MYPY_ARGS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if "error:" not in result.stdout and result.returncode not in (0, 1):
        raise RuntimeError(f"mypy failed to run (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="rewrite the baseline from the current counts")
    parser.add_argument("--report", default="", help="also write the current counts to this JSON file")
    args = parser.parse_args(argv)

    counts = parse_counts(run_mypy())
    if args.report:
        Path(args.report).write_text(json.dumps({"total": sum(counts.values()), "counts": counts}, indent=2), encoding="utf-8")
    if args.update:
        write_baseline(counts)
        print(f"mypy ratchet baseline written: {sum(counts.values())} error(s) in {len(counts)} file(s)")
        return 0
    if not BASELINE_PATH.is_file():
        print(f"mypy ratchet FAILED: {BASELINE_PATH.name} is missing; create it with --update", file=sys.stderr)
        return 1
    problems = compare(counts, load_baseline())
    if problems:
        print(f"mypy ratchet FAILED ({len(problems)} issue(s))", file=sys.stderr)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(f"mypy ratchet OK: {sum(counts.values())} error(s) in {len(counts)} file(s), none beyond the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
