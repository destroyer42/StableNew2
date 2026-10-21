"""Repository-owned validation policy: changed files -> a deterministic validation plan.

PR-DEVEX-CI-160. The full census is the merge gate, so there is no per-lane routing: a change set is either
documentation only (cheap path, no Python environment, no tests) or executable (the required gate, then the sharded
full census, both blocking). A docs-only follow-up commit over an already-green head reuses that evidence.

The classifier is conservative: only prose/media is documentation; executable or configuration text (workflows,
scripts, JSON, ``.py``, ``requirements*.txt`` ...) never is. Standard library only (it runs before any dependency is
installed).

    python tools/ci/validation_plan.py --base <sha> --head <sha> [--event pull_request] [--github-output $GITHUB_OUTPUT]
    python tools/ci/validation_plan.py --files a.py b.md        # classify an explicit list (tests/local use)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Why every executable change runs the census (recorded in the plan artifact for the PR reader).
CENSUS_REASON = "the full census is the merge gate for every executable change"

DOC_SUFFIXES = frozenset({".md", ".rst", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf"})
DOC_EXACT_PATHS = frozenset({"LICENSE", ".github/CODEOWNERS", "CODEOWNERS"})
#: Trees where a ``.md``/``.txt`` file may be data consumed by code, so it is never assumed to be documentation.
NON_DOC_TREES = (
    "src/",
    "tests/",
    "config/",
    "presets/",
    "packs/",
    "data/",
    "tools/ci/",
    ".github/workflows/",
    ".github/actions/",
)


@dataclass(frozen=True)
class ValidationPlan:
    docs_only: bool
    full_census: bool
    full_census_reasons: tuple[str, ...]
    changed_files: tuple[str, ...]
    #: A docs-only follow-up commit on a head whose evidence is already green: the executable evidence is reused, not
    #: re-earned. The base-to-head classification above is deliberately left untouched (a docs commit never
    #: downgrades it); only what this run executes changes.
    reuse_previous_evidence: bool = False

    @property
    def cheap_path(self) -> bool:
        """Docs-only change, or a docs-only delta over already-green evidence: no Python environment, no tests."""

        return self.docs_only or self.reuse_previous_evidence

    def as_dict(self) -> dict[str, object]:
        return {
            "docs_only": self.docs_only,
            "cheap_path": self.cheap_path,
            "reuse_previous_evidence": self.reuse_previous_evidence,
            "full_census": self.full_census,
            "full_census_reasons": list(self.full_census_reasons),
            "changed_files": list(self.changed_files),
        }


def _norm(path: str) -> str:
    cleaned = path.replace("\\", "/")
    return cleaned[2:] if cleaned.startswith("./") else cleaned


def is_documentation(path: str) -> bool:
    """Prose/media only. Executable or configuration text (workflows, scripts, JSON, .py ...) is never documentation."""

    if path in DOC_EXACT_PATHS:
        return True
    suffix = os.path.splitext(path)[1].lower()
    if suffix not in DOC_SUFFIXES:
        return False
    if path.startswith(NON_DOC_TREES):
        return False
    if suffix == ".txt" and not path.startswith("docs/"):
        return False  # only docs/ text notes are prose; requirements*.txt, constraints and version files are configuration
    return True


def classify(changed_files: list[str]) -> ValidationPlan:
    files = tuple(sorted({_norm(f) for f in changed_files if f}))
    executable = [path for path in files if not is_documentation(path)]
    if not executable:
        return ValidationPlan(
            docs_only=True, full_census=False, full_census_reasons=(), changed_files=files
        )
    return ValidationPlan(
        docs_only=False, full_census=True, full_census_reasons=(CENSUS_REASON,), changed_files=files
    )


def apply_evidence_reuse(
    plan: ValidationPlan, delta_files: list[str], *, previous_green: bool
) -> ValidationPlan:
    """Reuse green evidence for a docs-only delta over an already-validated head (never over an unvalidated one).

    ``delta_files`` are the paths changed since the previous PR head. Reuse needs: the previous head's required gate and
    census green, and a delta that is documentation only. A docs-only delta over unvalidated, failed or in-flight
    executable changes gets the normal full validation.
    """

    if plan.docs_only or not previous_green or not delta_files:
        return plan
    if classify(delta_files).docs_only:
        return dataclasses.replace(plan, reuse_previous_evidence=True)
    return plan


def changed_files_between(base: str, head: str, root: Path = ROOT) -> list[str]:
    """Base-to-head changed paths (merge-base diff), including deletions."""

    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...{head}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    paths: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            paths.append(parts[1].strip())
    return paths


def changed_files_direct(before: str, after: str, root: Path = ROOT) -> list[str]:
    """Paths changed between two PR heads (two-dot: what this push added), including deletions."""

    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", before, after],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.split("\t", 1)[1].strip() for line in out.splitlines() if "\t" in line]


def _github_output(plan: ValidationPlan, handle) -> None:
    def kv(key: str, value: str) -> None:
        handle.write(f"{key}={value}\n")

    kv("docs_only", str(plan.docs_only).lower())
    kv("cheap_path", str(plan.cheap_path).lower())
    kv("reuse_previous_evidence", str(plan.reuse_previous_evidence).lower())
    kv("full_census", str(plan.full_census and not plan.cheap_path).lower())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="classify an explicit file list instead of a git diff",
    )
    parser.add_argument("--event", default="pull_request")
    parser.add_argument(
        "--before", default="", help="previous PR head SHA (synchronize events) for evidence reuse"
    )
    parser.add_argument(
        "--previous-green",
        action="store_true",
        help="the --before head's required gate and census succeeded",
    )
    parser.add_argument("--github-output", default="")
    args = parser.parse_args(argv)

    if args.files is not None:
        files = list(args.files)
    elif args.event == "push":
        try:
            files = (
                changed_files_direct(args.before, args.head)
                if args.before
                else ["tools/ci/validation_plan.py"]
            )
        except subprocess.CalledProcessError:
            # An initial push or unavailable history must never look docs-only.
            files = ["tools/ci/validation_plan.py"]
    elif args.base:
        files = changed_files_between(args.base, args.head)
    else:
        parser.error("give --base/--head or --files")
    plan = classify(files)
    if args.event in {"schedule", "workflow_dispatch"} and plan.docs_only:
        # Explicit periodic/manual verification covers the entire executable tree.
        plan = dataclasses.replace(
            plan,
            docs_only=False,
            full_census=True,
            full_census_reasons=(f"{args.event}: always a full census",),
        )
    if args.event == "pull_request" and args.before and args.base and args.previous_green:
        plan = apply_evidence_reuse(
            plan, changed_files_direct(args.before, args.head), previous_green=True
        )
    print(json.dumps(plan.as_dict(), indent=2))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            _github_output(plan, handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
