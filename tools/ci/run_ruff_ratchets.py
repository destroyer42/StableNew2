"""Ruff-based ratchets: formatting and blind/silent exception handling (audit P1-5).

A big-bang reformat of ~400 files would conflict with every in-flight branch, and 2,000+ broad or silent ``except`` blocks
cannot be fixed at once, so both are ratchets over a checked-in baseline (``tools/ci/ruff_ratchet_baseline.json``):

* **format** - a file that ``ruff format`` would change may not be added to the set; a file outside the baseline must be
  formatted. A baselined file that becomes formatted must be removed (``--update``), so formatting only spreads inward.
* **rules** - per ``src`` file and rule, the number of ``BLE001`` (blind ``except Exception``), ``S110`` (``except: pass``) and
  ``S112`` (``except: continue``) findings may not exceed the baseline. New code cannot add a swallowed failure; fixing one
  must be locked in.

Both use the pinned ruff (requirements-dev.txt) and the project's configuration, so results are the same on every machine.

    python tools/ci/run_ruff_ratchets.py            # check
    python tools/ci/run_ruff_ratchets.py --update   # rewrite the baseline after a deliberate improvement
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "tools" / "ci" / "ruff_ratchet_baseline.json"
SCHEMA_VERSION = 1
RULES = ("BLE001", "S110", "S112")
RULE_SCOPE = "src"

_WOULD_REFORMAT = re.compile(r"^Would reformat: (?P<path>.+?)\s*$")


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def parse_unformatted(output: str) -> list[str]:
    files = {
        m.group("path").replace("\\", "/")
        for line in output.splitlines()
        if (m := _WOULD_REFORMAT.match(line.strip()))
    }
    return sorted(files)


def parse_rule_counts(raw_json: str) -> dict[str, dict[str, int]]:
    """``{file: {rule: count}}`` from ``ruff check --output-format json`` (paths made repo-relative POSIX)."""

    counts: dict[str, dict[str, int]] = {}
    for item in json.loads(raw_json or "[]"):
        code = item.get("code")
        if code not in RULES:
            continue
        path = Path(item["filename"])
        try:
            relative = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.as_posix().replace("\\", "/")
        per_file = counts.setdefault(relative, {})
        per_file[code] = per_file.get(code, 0) + 1
    return {path: dict(sorted(per.items())) for path, per in sorted(counts.items())}


def compare_format(current: list[str], baseline: list[str]) -> list[str]:
    problems = []
    for path in sorted(set(current) - set(baseline)):
        problems.append(
            f"FORMAT REGRESSION: {path} is not ruff-formatted; run `ruff format {path}`"
        )
    for path in sorted(set(baseline) - set(current)):
        problems.append(
            f"FORMAT IMPROVED: {path} is now formatted; run `python tools/ci/run_ruff_ratchets.py --update`"
        )
    return problems


def compare_rules(
    current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]
) -> list[str]:
    problems = []
    for path in sorted(set(current) | set(baseline)):
        for rule in RULES:
            have, allowed = current.get(path, {}).get(rule, 0), baseline.get(path, {}).get(rule, 0)
            if have > allowed:
                problems.append(
                    f"{rule} REGRESSION: {path}: {have} finding(s), baseline {allowed}; handle the specific exception or log it"
                )
            elif have < allowed:
                problems.append(
                    f"{rule} IMPROVED: {path}: {have} finding(s), baseline {allowed}; run `python tools/ci/run_ruff_ratchets.py --update`"
                )
    return problems


def collect() -> tuple[list[str], dict[str, dict[str, int]]]:
    formatted = _ruff("format", "--check", ".")
    if formatted.returncode not in (0, 1):
        raise RuntimeError(
            f"ruff format failed (exit {formatted.returncode}):\n{formatted.stdout}\n{formatted.stderr}"
        )
    checked = _ruff(
        "check",
        RULE_SCOPE,
        "--select",
        ",".join(RULES),
        "--output-format",
        "json",
        "--no-cache",
        "--exit-zero",
    )
    if checked.returncode != 0:
        raise RuntimeError(f"ruff check failed (exit {checked.returncode}):\n{checked.stderr}")
    return parse_unformatted(formatted.stdout + formatted.stderr), parse_rule_counts(checked.stdout)


def load_baseline(path: Path = BASELINE_PATH) -> tuple[list[str], dict[str, dict[str, int]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path.name}: unsupported schema_version {data.get('schema_version')!r}")
    return list(data["format"]["files"]), {
        p: {r: int(n) for r, n in per.items()} for p, per in data["rules"]["counts"].items()
    }


def write_baseline(
    files: list[str], counts: dict[str, dict[str, int]], path: Path = BASELINE_PATH
) -> None:
    totals = {rule: sum(per.get(rule, 0) for per in counts.values()) for rule in RULES}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "format": {
            "metric": "files `ruff format --check` would reformat",
            "total": len(files),
            "files": files,
        },
        "rules": {"metric": f"findings per {RULE_SCOPE} file", "totals": totals, "counts": counts},
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--update", action="store_true", help="rewrite the baseline from the current state"
    )
    args = parser.parse_args(argv)

    files, counts = collect()
    if args.update:
        write_baseline(files, counts)
        print(
            f"ruff ratchet baseline written: {len(files)} unformatted file(s); "
            + ", ".join(f"{r}={sum(p.get(r, 0) for p in counts.values())}" for r in RULES)
        )
        return 0
    if not BASELINE_PATH.is_file():
        print(
            f"ruff ratchets FAILED: {BASELINE_PATH.name} is missing; create it with --update",
            file=sys.stderr,
        )
        return 1
    base_files, base_counts = load_baseline()
    problems = compare_format(files, base_files) + compare_rules(counts, base_counts)
    if problems:
        print(f"ruff ratchets FAILED ({len(problems)} issue(s))", file=sys.stderr)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(
        f"ruff ratchets OK: {len(files)} unformatted file(s) and "
        + ", ".join(f"{r}={sum(p.get(r, 0) for p in counts.values())}" for r in RULES)
        + " - none beyond the baseline"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
