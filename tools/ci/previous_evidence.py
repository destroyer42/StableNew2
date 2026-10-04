"""Decide whether a docs-only follow-up may reuse the previous PR head's CI evidence (PR-DEVEX-CI-110).

Standard library only (it runs before any dependency is installed) and deliberately testable: the policy is a pure function over
GitHub check-run records, not jq inside workflow YAML.

Reuse is allowed only when ALL of the following hold, otherwise the normal validation runs:

* the current PR base is already an ancestor of the previous head (reused integration evidence was earned on a tree that
  already contains the current base; it is not reused once the base has advanced past the previously validated head);
* the latest GitHub-Actions ``required`` check run for the previous head concluded ``success``;
* the latest ``affected`` and ``full-suite`` check runs for the previous head concluded ``success`` or ``skipped`` (skipped
  means the plan did not select that job). A check merely having ``status == completed`` is never enough: failure, cancelled,
  timed_out, action_required, neutral, stale, an in-progress run or a missing run all block reuse;
* only check runs created by the GitHub Actions app count, and the latest one per name wins (not an arbitrary first match).

    python tools/ci/previous_evidence.py --repo OWNER/REPO --before <prev head> --base <current base> [--github-output FILE]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITHUB_ACTIONS_APP = "github-actions"
REQUIRED_CHECK = "required"
SELECTED_CHECKS = ("affected", "full-suite")
SELECTED_OK = frozenset({"success", "skipped"})


@dataclass(frozen=True)
class Decision:
    green: bool
    reason: str


def latest_actions_check_runs(check_runs: Iterable[dict]) -> dict[str, dict]:
    """The latest (highest id) GitHub-Actions check run per name."""

    latest: dict[str, dict] = {}
    for run in check_runs:
        app = (run.get("app") or {}).get("slug")
        name = run.get("name")
        if app != GITHUB_ACTIONS_APP or not name:
            continue
        if name not in latest or int(run.get("id") or 0) > int(latest[name].get("id") or 0):
            latest[name] = run
    return latest


def evaluate(check_runs: Iterable[dict], *, base_is_ancestor: bool) -> Decision:
    """Pure policy: may the previous head's evidence be reused?"""

    if not base_is_ancestor:
        return Decision(False, "the current base is not an ancestor of the previous head (main advanced): normal validation")
    latest = latest_actions_check_runs(check_runs)
    required = latest.get(REQUIRED_CHECK)
    if required is None:
        return Decision(False, "no required check run for the previous head")
    if required.get("conclusion") != "success":
        return Decision(False, f"previous required check is {required.get('status')}/{required.get('conclusion')}, not success")
    for name in SELECTED_CHECKS:
        run = latest.get(name)
        if run is None:
            return Decision(False, f"no {name} check run for the previous head")
        if run.get("conclusion") not in SELECTED_OK:
            return Decision(False, f"previous {name} is {run.get('status')}/{run.get('conclusion')}, not success or skipped")
    return Decision(True, "previous head's required gate and selected jobs concluded green")


def fetch_check_runs(repo: str, sha: str) -> list[dict]:
    out = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repo}/commits/{sha}/check-runs?per_page=100", "--jq", ".check_runs[]"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def base_is_ancestor(base: str, before: str, root: Path = ROOT) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", base, before], cwd=root, capture_output=True).returncode == 0


def decide(
    repo: str,
    before: str,
    base: str,
    *,
    fetch: Callable[[str, str], list[dict]] = fetch_check_runs,
    ancestor: Callable[[str, str], bool] = base_is_ancestor,
) -> Decision:
    """Fail closed: any error obtaining the evidence means no reuse."""

    if not (repo and before and base):
        return Decision(False, "missing repository, previous head or base")
    try:
        is_ancestor = ancestor(base, before)
        runs = fetch(repo, before) if is_ancestor else []
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return Decision(False, f"could not read the previous head's evidence ({type(exc).__name__})")
    return evaluate(runs, base_is_ancestor=is_ancestor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="")
    parser.add_argument("--before", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--github-output", default="")
    args = parser.parse_args(argv)
    decision = decide(args.repo, args.before, args.base)
    print(json.dumps({"green": decision.green, "reason": decision.reason}))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"green={str(decision.green).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
