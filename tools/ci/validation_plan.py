"""Repository-owned validation policy: changed files -> a deterministic, risk-proportionate validation plan.

PR-DEVEX-CI-110. The GitHub workflow consumes this plan; routing policy is not buried in YAML conditions.

Model: ``cheap classification -> fast required contract gate -> affected lane tests`` with the full census reserved
for broad or unbounded changes, periodic main-branch evidence, explicit requests and releases.

Lanes are coarse ownership groups, not a module dependency graph. A change may activate several lanes and every
activated lane runs (routing is additive). The classifier escalates when uncertain: an unknown executable path is
never docs-only and never "no tests". Standard library only (it runs before any dependency is installed).

    python tools/ci/validation_plan.py --base <sha> --head <sha> [--event pull_request] [--label full-census] \
        [--commit-message "..."] [--github-output $GITHUB_OUTPUT]
    python tools/ci/validation_plan.py --files a.py b.md        # classify an explicit list (tests/local use)
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LANE_DOCS_ONLY = "docs_only"
LANE_CORE = "core"
LANE_IMAGE = "image"
LANE_VIDEO = "video"
LANE_GUI = "gui"
LANE_RUNTIME = "runtime"
LANE_QUALIFICATION = "qualification_tools"
LANE_CI_AUTHORITY = "ci_test_authority"
LANE_FULL_CENSUS = "full_census_required"
LANES = (
    LANE_DOCS_ONLY,
    LANE_CORE,
    LANE_IMAGE,
    LANE_VIDEO,
    LANE_GUI,
    LANE_RUNTIME,
    LANE_QUALIFICATION,
    LANE_CI_AUTHORITY,
    LANE_FULL_CENSUS,
)

#: Operator/maintainer ways to request the full census without editing workflow YAML.
FULL_CENSUS_LABEL = "full-census"
FULL_CENSUS_COMMIT_MARKER = "[full-census]"
#: Events that are always a full census (periodic main evidence, manual dispatch / release validation).
ALWAYS_FULL_EVENTS = frozenset({"schedule", "workflow_dispatch"})

DOC_SUFFIXES = frozenset({".md", ".rst", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf"})
DOC_EXACT_PATHS = frozenset({"LICENSE", ".github/CODEOWNERS", "CODEOWNERS"})
#: Trees where a ``.md``/``.txt`` file may be data consumed by code, so it is never assumed to be documentation.
NON_DOC_TREES = ("src/", "tests/", "config/", "presets/", "packs/", "data/", "tools/ci/", ".github/workflows/", ".github/actions/")

# Global / unbounded impact: dependency, interpreter, pytest, CI framework, shared test infrastructure, the policy itself.
FULL_CENSUS_RULES: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", "pytest/ruff/mypy/dependency configuration"),
    ("requirements*.txt", "dependency set"),
    ("constraints/*", "dependency constraints"),
    ("*.lock", "dependency lock"),
    ("setup.py", "packaging"),
    ("setup.cfg", "packaging/tool configuration"),
    ("pytest.ini", "pytest configuration"),
    ("tox.ini", "test configuration"),
    ("mypy.ini", "type-check configuration"),
    ("ruff.toml", "lint configuration"),
    (".python-version", "interpreter"),
    (".pre-commit-config.yaml", "tooling configuration"),
    (".github/workflows/*", "CI framework"),
    (".github/actions/*", "CI framework"),
    ("tools/ci/*", "CI/test authority and validation policy"),
    ("conftest.py", "global pytest fixtures"),
    ("*/conftest.py", "pytest fixtures"),
    ("tests/__init__.py", "global test package"),
    ("tests/helpers/*", "shared test helpers with repository-wide blast radius"),
    ("tests/fixtures/*", "shared test fixtures"),
    ("tests/mocks/*", "shared test mocks"),
    ("tests/data/*", "shared test data"),
)

_RUNTIME_SOURCES = (
    "src/api/webui_process_manager.py",
    "src/api/webui_runtime_identity.py",
    "src/api/healthcheck.py",
    "src/services/runtime_transition_service.py",
    "src/utils/single_instance.py",
    "src/utils/process_*",
    "src/utils/*process*",
    "src/utils/webui_*",
    "tools/runtime/*",
    "scripts/*",
    "config/managed_*",
    "config/forge_*",
    "config/*runtime*",
)

#: Ordered (first match wins): pattern -> lanes. Executable-path ownership, source and tests alike.
LANE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    *((pattern, (LANE_RUNTIME,)) for pattern in _RUNTIME_SOURCES),
    ("src/image_backends/*", (LANE_IMAGE,)),
    ("src/api/*", (LANE_IMAGE,)),
    ("src/pipeline/*svd*", (LANE_VIDEO, LANE_CORE)),
    ("src/pipeline/*video*", (LANE_VIDEO, LANE_CORE)),
    ("src/pipeline/*", (LANE_CORE, LANE_IMAGE)),
    ("src/video/*", (LANE_VIDEO,)),
    ("src/gui/*", (LANE_GUI,)),
    ("src/gui_v2/*", (LANE_GUI,)),
    ("src/controller/*", (LANE_CORE, LANE_GUI)),
    ("src/*", (LANE_CORE,)),
    ("tools/qualification/*", (LANE_QUALIFICATION,)),
    ("tools/acceptance/*", (LANE_QUALIFICATION,)),
    ("tools/operator_journey/*", (LANE_QUALIFICATION, LANE_GUI)),
    ("tools/*", (LANE_QUALIFICATION,)),
    # known data/config trees consumed by core code and tests (not unknown ownership)
    ("presets/*", (LANE_CORE,)),
    ("packs/*", (LANE_CORE,)),
    ("lists/*", (LANE_CORE,)),
    ("data/*", (LANE_CORE,)),
    ("config/*", (LANE_CORE,)),
    (".stableNew_version.txt", (LANE_CORE,)),
    (".editorconfig", (LANE_CORE,)),
    (".gitattributes", (LANE_CORE,)),
    (".gitignore", (LANE_CORE,)),
    (".claude/*", (LANE_CORE,)),
    # tests (by area)
    ("tests/image_backends/*", (LANE_IMAGE,)),
    ("tests/api/test_webui_process*", (LANE_RUNTIME,)),
    ("tests/api/test_webui_launch*", (LANE_RUNTIME,)),
    ("tests/api/test_webui_runtime*", (LANE_RUNTIME,)),
    ("tests/api/*", (LANE_IMAGE,)),
    ("tests/services/test_runtime*", (LANE_RUNTIME,)),
    ("tests/integration/test_pr_runtime*", (LANE_RUNTIME,)),
    ("tests/integration/test_pr_img*", (LANE_IMAGE,)),
    ("tests/video/*", (LANE_VIDEO,)),
    ("tests/gui_v2/*", (LANE_GUI,)),
    ("tests/gui/*", (LANE_GUI,)),
    ("tests/tools/test_operator_journey*", (LANE_QUALIFICATION, LANE_GUI)),
    ("tests/tools/*", (LANE_QUALIFICATION,)),
    ("tests/app/*", (LANE_RUNTIME,)),
    ("tests/*", (LANE_CORE,)),
)

#: Lane -> pytest targets (directories, files or globs relative to the repository root). Cross-boundary tests are
#: members of every lane that owns a side of the boundary; a test's directory is not its only ownership.
LANE_TARGETS: dict[str, tuple[str, ...]] = {
    LANE_CORE: (
        "tests/queue", "tests/history", "tests/migrations", "tests/state", "tests/controller", "tests/pipeline",
        "tests/integration", "tests/services", "tests/system", "tests/safety", "tests/unit", "tests/utils",
        "tests/regression", "tests/compat", "tests/app", "tests/cli", "tests/test_*.py",
    ),
    LANE_IMAGE: (
        "tests/image_backends", "tests/api", "tests/integration/test_pr_img*", "tests/safety/test_forge*",
        "tests/pipeline/test_klein*", "tests/pipeline/test_reprocess*",
    ),
    LANE_VIDEO: ("tests/video", "tests/pipeline/test_*svd*", "tests/pipeline/test_*video*"),
    LANE_GUI: (
        "tests/gui_v2", "tests/gui", "tests/review", "tests/curation", "tests/test_*.py",
        "tests/tools/test_operator_journey*", "tests/controller/test_*gui*", "tests/controller/test_app_controller*",
    ),
    LANE_RUNTIME: (
        "tests/api/test_webui_process*", "tests/api/test_webui_launch*", "tests/api/test_webui_runtime*",
        "tests/services/test_runtime*", "tests/integration/test_pr_runtime*", "tests/system/test_managed_*",
        "tests/system/test_runtime_*", "tests/app", "tests/safety",
    ),
    LANE_QUALIFICATION: ("tests/tools",),
}

#: Source areas whose own tests are NOT in the core backbone; they are added when their source/tests change.
DOMAIN_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("src/learning/*", ("tests/learning", "tests/learning_v2")),
    ("src/randomizer/*", ("tests/randomizer",)),
    ("src/promptpacks/*", ("tests/promptpacks",)),
    ("src/prompting/*", ("tests/promptpacks", "tests/unit")),
    ("src/curation/*", ("tests/curation",)),
    ("src/review/*", ("tests/review",)),
    ("src/refinement/*", ("tests/refinement",)),
    ("src/training/*", ("tests/training",)),
    ("src/assets/*", ("tests/assets",)),
    ("src/cluster/*", ("tests/cluster",)),
    ("src/ai_v2/*", ("tests/ai_v2",)),
    ("tests/learning/*", ("tests/learning",)),
    ("tests/learning_v2/*", ("tests/learning_v2",)),
    ("tests/randomizer/*", ("tests/randomizer",)),
    ("tests/promptpacks/*", ("tests/promptpacks",)),
    ("tests/curation/*", ("tests/curation",)),
    ("tests/review/*", ("tests/review",)),
    ("tests/refinement/*", ("tests/refinement",)),
    ("tests/training/*", ("tests/training",)),
    ("tests/assets/*", ("tests/assets",)),
    ("tests/cluster/*", ("tests/cluster",)),
    ("tests/ai_v2/*", ("tests/ai_v2",)),
    ("tests/photo_optimize/*", ("tests/photo_optimize",)),
    ("tests/debughub/*", ("tests/debughub",)),
)

#: Cross-domain ownership for known sources whose relevant tests live outside their filesystem lane. Additive on top of
#: LANE_RULES (every matching rule applies): (source pattern, extra lanes, extra pytest targets). Coarse by design - not a
#: dependency graph; each entry is backed by tests that import the source directly (a policy test re-derives that evidence).
_LEARNING_TESTS = (
    "tests/learning", "tests/learning_v2", "tests/controller/test_learning*", "tests/integration/test_learning*",
    "tests/integration/test_golden_path*",
)
_PROMPT_STATE_TESTS = (
    "tests/state", "tests/promptpacks", "tests/test_*.py", "tests/integration/test_golden_path*",
    "tests/controller/test_content_visibility*", "tests/learning_v2/test_lora_variable_service.py",
)
CROSS_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # learning GUI surfaces: the learning domain tests are their direct owners
    ("src/gui/*learning*", (), _LEARNING_TESTS),
    ("src/gui_v2/*learning*", (), _LEARNING_TESTS),
    # prompt workspace / pack model-state surfaces: state + promptpack coverage
    ("src/gui/models/*", (), _PROMPT_STATE_TESTS),
    ("src/gui/prompt_workspace_state.py", (), _PROMPT_STATE_TESTS),
    ("src/gui/prompt_pack_adapter_v2.py", (), _PROMPT_STATE_TESTS),
    # the central GUI application state is consumed across controller, pipeline, queue and API tests
    ("src/gui/app_state_v2.py", (LANE_CORE,), ()),
    ("src/gui/app_state_projection_sink.py", (LANE_CORE,), ()),
    # GUI panels are exercised by controller preview/sidebar tests and the queue/job-timing integration tests
    ("src/gui/*panel*", (), ("tests/integration", "tests/controller", "tests/test_*.py")),
    ("src/gui/api_status_panel.py", (LANE_RUNTIME,), ()),
    ("src/gui/dropdown_loader_v2.py", (LANE_IMAGE,), ()),
    ("src/gui/*movie*", (LANE_VIDEO,), ()),
    ("src/gui/view_contracts/*video*", (LANE_VIDEO,), ()),
    ("src/gui/stage_cards_v2/*", (), ("tests/test_*.py",)),
    ("src/gui/utils/*", (), ("tests/utils",)),
    ("src/gui/widgets/*", (), ("tests/controller/test_*lora*", "tests/utils")),
)

#: Test areas that deliberately sit outside every lane's backbone but are reachable via DOMAIN_TARGETS
#: (the policy test asserts every ``tests/*`` area is covered by a lane or a domain target).
FULL_CENSUS_ONLY_AREAS: tuple[str, ...] = ("tests/mocks",)


@dataclass(frozen=True)
class ValidationPlan:
    lanes: tuple[str, ...]
    docs_only: bool
    full_census: bool
    full_census_reasons: tuple[str, ...]
    escalations: tuple[str, ...]
    changed_tests: tuple[str, ...]
    affected_targets: tuple[str, ...]
    changed_files: tuple[str, ...]
    reasons: dict[str, list[str]] = field(default_factory=dict)
    #: A docs-only follow-up commit on a head whose evidence is already green: the executable evidence is reused, not
    #: re-earned. The base-to-head classification above is deliberately left untouched (a docs commit never
    #: downgrades it); only what this run executes changes.
    reuse_previous_evidence: bool = False

    @property
    def cheap_path(self) -> bool:
        """Docs-only change, or a docs-only delta over already-green evidence: no Python environment, no tests."""

        return self.docs_only or self.reuse_previous_evidence

    @property
    def run_affected(self) -> bool:
        """Affected-lane tests run only for bounded executable changes (never docs-only, never under a full census)."""

        return not self.cheap_path and not self.full_census and bool(self.affected_targets)

    def as_dict(self) -> dict[str, object]:
        return {
            "lanes": list(self.lanes),
            "docs_only": self.docs_only,
            "cheap_path": self.cheap_path,
            "reuse_previous_evidence": self.reuse_previous_evidence,
            "full_census": self.full_census,
            "full_census_reasons": list(self.full_census_reasons),
            "escalations": list(self.escalations),
            "run_affected": self.run_affected,
            "changed_tests": list(self.changed_tests),
            "affected_targets": list(self.affected_targets),
            "changed_files": list(self.changed_files),
            "reasons": self.reasons,
        }


def _norm(path: str) -> str:
    cleaned = path.replace("\\", "/")
    return cleaned[2:] if cleaned.startswith("./") else cleaned


def _match(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def is_documentation(path: str) -> bool:
    """Prose/media only. Executable or configuration text (workflows, scripts, JSON, .py ...) is never documentation."""

    if path in DOC_EXACT_PATHS:
        return True
    suffix = os.path.splitext(path)[1].lower()
    if suffix not in DOC_SUFFIXES:
        return False
    if path.startswith(NON_DOC_TREES):
        return False
    if suffix == ".txt" and not (path.startswith("docs/") or "/" not in path):
        return False  # only docs/ and root-level .txt notes are prose (e.g. requirements*.txt is caught by FULL rules first)
    return True


def is_test_file(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py") and os.path.basename(path).startswith("test_")


def expand_targets(patterns: tuple[str, ...] | list[str], root: Path = ROOT) -> list[str]:
    """Concrete, existing, sorted, de-duplicated pytest targets for directory/file/glob patterns."""

    found: set[str] = set()
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            for match in sorted(root.glob(pattern)):
                if match.is_dir() or (match.suffix == ".py"):
                    found.add(match.relative_to(root).as_posix())
        elif (root / pattern).exists():
            found.add(pattern)
    return sorted(found)


def classify(
    changed_files: list[str],
    *,
    force_full: str = "",
    root: Path = ROOT,
) -> ValidationPlan:
    files = sorted({_norm(f) for f in changed_files if f})
    reasons: dict[str, list[str]] = {}
    escalations: list[str] = []
    full_reasons: list[str] = [force_full] if force_full else []
    lanes: set[str] = set()
    changed_tests: list[str] = []
    patterns: list[str] = []
    executable = False

    def note(lane: str, path: str) -> None:
        reasons.setdefault(lane, [])
        if len(reasons[lane]) < 8 and path not in reasons[lane]:
            reasons[lane].append(path)

    for path in files:
        full_hit = next((reason for pattern, reason in FULL_CENSUS_RULES if _match(path, pattern)), None)
        if full_hit:
            executable = True
            full_reasons.append(f"{path}: {full_hit}")
            lanes.update({LANE_FULL_CENSUS})
            if path.startswith((".github/", "tools/ci/")) or path in {"pyproject.toml", "pytest.ini", "tox.ini"} or "conftest" in path:
                lanes.add(LANE_CI_AUTHORITY)
                note(LANE_CI_AUTHORITY, path)
            note(LANE_FULL_CENSUS, path)
            if is_test_file(path) and (root / path).exists():
                changed_tests.append(path)
            continue
        if is_documentation(path):
            continue
        executable = True
        rule = next(((p, ln) for p, ln in LANE_RULES if _match(path, p)), None)
        if rule is None:
            # Unknown ownership is never assumed to be core-only: the impact cannot be bounded, so run the full census.
            escalations.append(f"{path}: unknown ownership")
            full_reasons.append(f"{path}: unknown executable/config ownership (impact cannot be bounded)")
            lanes.add(LANE_FULL_CENSUS)
            note(LANE_FULL_CENSUS, path)
        else:
            for lane in rule[1]:
                lanes.add(lane)
                note(lane, path)
        for cross_pattern, cross_lanes, cross_targets in CROSS_DOMAIN_RULES:
            if _match(path, cross_pattern):
                for lane in cross_lanes:
                    lanes.add(lane)
                    note(lane, path)
                patterns.extend(cross_targets)
        for domain_pattern, targets in DOMAIN_TARGETS:
            if _match(path, domain_pattern):
                patterns.extend(targets)
        if is_test_file(path) and (root / path).exists():
            changed_tests.append(path)

    docs_only = not executable
    if docs_only:
        return ValidationPlan((LANE_DOCS_ONLY,), True, False, (), (), (), (), tuple(files), {})

    if force_full:
        lanes.add(LANE_FULL_CENSUS)
    full_census = LANE_FULL_CENSUS in lanes or bool(full_reasons)
    if full_census:
        lanes.add(LANE_FULL_CENSUS)

    ordered = tuple(lane for lane in LANES if lane in lanes)
    affected: list[str] = []
    if not full_census:
        for lane in ordered:
            patterns.extend(LANE_TARGETS.get(lane, ()))
        affected = expand_targets(patterns, root)
        # A directly modified executable test always executes (in addition to its lane).
        affected = sorted(set(affected) | set(changed_tests))
    return ValidationPlan(
        lanes=ordered,
        docs_only=False,
        full_census=full_census,
        full_census_reasons=tuple(dict.fromkeys(full_reasons)),
        escalations=tuple(escalations),
        changed_tests=tuple(sorted(set(changed_tests))),
        affected_targets=tuple(affected),
        changed_files=tuple(files),
        reasons=reasons,
    )


def apply_evidence_reuse(plan: ValidationPlan, delta_files: list[str], *, previous_green: bool, forced_full: str = "") -> ValidationPlan:
    """Reuse green evidence for a docs-only delta over an already-validated head (never over an unvalidated one).

    ``delta_files`` are the paths changed since the previous PR head. Reuse needs: the previous head's required gate (and any
    census it started) green, a delta that is documentation only, and no explicit full-census request. A docs-only delta over
    unvalidated, failed or in-flight executable changes gets the normal full routing.
    """

    if forced_full or plan.docs_only or not previous_green or not delta_files:
        return plan
    if classify(delta_files).docs_only:
        return dataclasses.replace(plan, reuse_previous_evidence=True)
    return plan


def full_census_request(event: str, labels: list[str], commit_message: str) -> str:
    """Why a full census was explicitly requested (empty when it was not)."""

    if event in ALWAYS_FULL_EVENTS:
        return f"{event}: periodic/manual/release census"
    if FULL_CENSUS_LABEL in {label.strip().lower() for label in labels}:
        return f"label '{FULL_CENSUS_LABEL}'"
    if FULL_CENSUS_COMMIT_MARKER in commit_message.lower():
        return f"commit marker {FULL_CENSUS_COMMIT_MARKER}"
    return ""


def changed_files_between(base: str, head: str, root: Path = ROOT) -> list[str]:
    """Base-to-head changed paths (merge-base diff), including deletions and renames' both sides."""

    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...{head}"],
        cwd=root, capture_output=True, text=True, check=True,
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
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    return [line.split("\t", 1)[1].strip() for line in out.splitlines() if "\t" in line]


def _github_output(plan: ValidationPlan, handle) -> None:
    def kv(key: str, value: str) -> None:
        handle.write(f"{key}={value}\n")

    kv("docs_only", str(plan.docs_only).lower())
    kv("cheap_path", str(plan.cheap_path).lower())
    kv("reuse_previous_evidence", str(plan.reuse_previous_evidence).lower())
    kv("full_census", str(plan.full_census and not plan.cheap_path).lower())
    kv("run_affected", str(plan.run_affected).lower())
    kv("lanes", ",".join(plan.lanes))
    delimiter = "TARGETS_" + uuid.uuid4().hex  # unguessable: a path can never end the block and inject output keys
    handle.write(f"targets<<{delimiter}\n" + "\n".join(plan.affected_targets) + f"\n{delimiter}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--files", nargs="*", default=None, help="classify an explicit file list instead of a git diff")
    parser.add_argument("--event", default="pull_request")
    parser.add_argument("--label", action="append", default=[], help="PR label (repeatable)")
    parser.add_argument("--commit-message", default="")
    parser.add_argument("--before", default="", help="previous PR head SHA (synchronize events) for evidence reuse")
    parser.add_argument("--previous-green", action="store_true", help="the --before head's required gate (and census, if any) succeeded")
    parser.add_argument("--github-output", default="")
    args = parser.parse_args(argv)

    if args.files is not None:
        files = list(args.files)
    elif args.base:
        files = changed_files_between(args.base, args.head)
    else:
        parser.error("give --base/--head or --files")
    forced = full_census_request(args.event, args.label, args.commit_message)
    plan = classify(files, force_full=forced)
    if args.before and args.base and args.previous_green:
        plan = apply_evidence_reuse(plan, changed_files_direct(args.before, args.head), previous_green=True, forced_full=forced)
    payload = json.dumps(plan.as_dict(), indent=2)
    print(payload)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            _github_output(plan, handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
