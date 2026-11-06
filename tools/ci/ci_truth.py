"""Canonical CI/testing documentation truth, checkable without the application environment (PR-DEVEX-CI-110).

It also holds the PR completion-evidence record to its schema (``tools/ci/check_pr_evidence.py``) and the advisory
evidence workflow to its trust boundary (PR-DEVEX-EVIDENCE-870).

Standard library only: the docs-only cheap path of the required job runs this under the runner's system Python, and the
pytest truth tests (``tests/system/test_ci_truth_sync_v2.py``) call the same function, so the rules live in exactly one place.

    python tools/ci/ci_truth.py        # exit 1 and print each problem when a canonical document violates current CI truth
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CODING = "docs/StableNew_Coding_and_Testing_v2.6.md"
#: Stale generic statements that described the pre-CI-110 workflow as an always-present full-suite job.
STALE_PHRASES = {
    "STATUS.md": ("one required gate, one informational full-suite job",),
    "docs/CODEX_MAP.md": ("(required gate + informational full-suite)",),
}


#: STATUS.md is current state only (audit P2-1). Its size, stale-marker and dead-reference rules are enforced here.
STATUS = "STATUS.md"
STATUS_MAX_LINES = 150
#: Phrases that mean a per-PR narrative or an out-of-date lifecycle label crept back in (matched case-insensitively).
STATUS_BANNED_MARKERS = (
    "not merged",
    "local implementation",
    "locally validated",
    "local deterministic validation",
    "awaiting integration",
    "draft pr",
    "python 3.11",
    "python 3.12",
    "3.11/3.12",
)
REPO_PATH_PREFIXES = ("docs/", "src/", "tools/", "tests/", "scripts/", "config/", "constraints/")
_BACKTICKED = re.compile(r"`([^`\s]+)`")

#: The task map is hand-written navigation; the exhaustive module index is generated into docs/CODE_MAP.md.
TASK_MAP = "docs/CODEX_MAP.md"
TASK_MAP_MAX_LINES = 60


def _dead_references(root: Path, rel: str, text: str) -> list[str]:
    problems: list[str] = []
    for reference in sorted(set(_BACKTICKED.findall(text))):
        candidate = reference.rstrip(".,;:)")
        if not candidate.startswith(REPO_PATH_PREFIXES):
            continue
        exists = any(root.glob(candidate)) if "*" in candidate else (root / candidate).exists()
        if not exists:
            problems.append(f"{rel} references a path that does not exist: {candidate}")
    return problems


def status_problems(root: Path = ROOT) -> list[str]:
    text = _read(root, STATUS)
    if text is None:
        return [f"{STATUS} is missing"]
    problems: list[str] = []
    lines = text.splitlines()
    if len(lines) > STATUS_MAX_LINES:
        problems.append(f"{STATUS} has {len(lines)} lines; the cap is {STATUS_MAX_LINES} (current state only, no PR narrative)")
    lowered = text.lower()
    for marker in STATUS_BANNED_MARKERS:
        if marker in lowered:
            problems.append(f"{STATUS} contains the stale/narrative marker {marker!r}")
    problems.extend(_dead_references(root, STATUS, text))
    return problems


def task_map_problems(root: Path = ROOT) -> list[str]:
    """The task map stays a short hand-written table whose every path exists (the full module index is generated)."""
    text = _read(root, TASK_MAP)
    if text is None:
        return [f"{TASK_MAP} is missing"]
    problems: list[str] = []
    line_count = len(text.splitlines())
    if line_count > TASK_MAP_MAX_LINES:
        problems.append(
            f"{TASK_MAP} has {line_count} lines; the cap is {TASK_MAP_MAX_LINES} (link to docs/CODE_MAP.md instead of listing modules)"
        )
    problems.extend(_dead_references(root, TASK_MAP, text))
    return problems


#: AGENTS.md is the only place operating rules live (audit P2-4). Everything else adds procedure or points to it.
RULES = "AGENTS.md"
RULE_CAPS = {
    "CLAUDE.md": 40,
    ".github/copilot-instructions.md": 12,
    "docs/AGENT_OPERATING_MODEL.md": 160,
    "docs/AI_MODEL_SELECTION.md": 90,
}
#: Bridges that must name AGENTS.md as the authority.
RULE_BRIDGES = ("CLAUDE.md", ".github/copilot-instructions.md", "docs/AGENT_OPERATING_MODEL.md", "docs/AI_MODEL_SELECTION.md")
#: Rule text that exists once, in AGENTS.md. Restating it elsewhere is how the copies drifted before.
RESTATED_RULE_MARKERS = (
    "immediately before an authorized",
    "execution profile + model",
    "cost/task",
    "never grants qualification",
)
RESTATEMENT_SCOPES = ("docs/AGENT_OPERATING_MODEL.md", "docs/AI_MODEL_SELECTION.md", "docs/CODEX_WORK_PACKAGE_TEMPLATE.md", "CLAUDE.md")


def rules_problems(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    if _read(root, RULES) is None:
        return [f"{RULES} is missing"]
    for rel, cap in RULE_CAPS.items():
        text = _read(root, rel)
        if text is None:
            problems.append(f"{rel} is missing")
            continue
        if len(text.splitlines()) > cap:
            problems.append(f"{rel} has {len(text.splitlines())} lines; the cap is {cap} (rules live in {RULES}; link instead of copying)")
        if rel in RULE_BRIDGES and "AGENTS.md" not in text:
            problems.append(f"{rel} must name {RULES} as the authority")
    scoped = list(RESTATEMENT_SCOPES)
    for directory, pattern in ((".github/agents", "*.md"), (".claude/skills", "*/SKILL.md")):
        base = root / directory
        if base.is_dir():
            scoped.extend(path.relative_to(root).as_posix() for path in sorted(base.glob(pattern)))
    for rel in scoped:
        lowered = (_read(root, rel) or "").lower()
        for marker in RESTATED_RULE_MARKERS:
            if marker in lowered:
                problems.append(f"{rel} restates a rule that belongs only in {RULES}: {marker!r}")
    return problems


#: The completion-evidence record (PR-DEVEX-EVIDENCE-870). The rule is AGENTS.md section 8; the schema is the checker's.
PR_TEMPLATE = ".github/pull_request_template.md"
WORK_PACKAGE_TEMPLATE = "docs/CODEX_WORK_PACKAGE_TEMPLATE.md"
EVIDENCE_RULE_ANCHOR = "**Completion evidence**"
#: Full-package measurement (docs/AI_MODEL_SELECTION.md); `--since-commit` is post-commit only and never a template example.
CANONICAL_USAGE_COMMAND = "python tools/usage_report.py --since <task-start> --until <closeout-end> --session <host:id> --line"


def _evidence_checker():
    """The checker module, loaded from beside this file: the record's schema has one owner."""

    spec = importlib.util.spec_from_file_location(
        "check_pr_evidence_schema", Path(__file__).with_name("check_pr_evidence.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completion_evidence_problems(root: Path = ROOT) -> list[str]:
    """The PR template carries exactly the checker's sections and fields, unfilled, plus the canonical usage command."""

    template = _read(root, PR_TEMPLATE)
    if template is None:
        return [f"{PR_TEMPLATE} is missing"]
    checker = _evidence_checker()
    problems: list[str] = []
    headings = re.findall(r"^## (.+?)\s*$", template, flags=re.MULTILINE)
    expected = [name for name, _ in checker.SECTIONS]
    if headings != expected:
        problems.append(f"{PR_TEMPLATE} headings {headings} differ from the check_pr_evidence.py schema {expected}")
    findings = checker.analyze_body(template)
    for finding in findings:
        if finding.code.startswith(("MISSING", "DUPLICATE")):
            problems.append(f"{PR_TEMPLATE} {finding.code} for {finding.location} (template and checker schema disagree)")
    placeholders = {finding.location for finding in findings if finding.code == "PLACEHOLDER"}
    for section, fields in ((checker.EVIDENCE_SECTION, checker.EVIDENCE_FIELDS), (checker.USAGE_SECTION, checker.USAGE_FIELDS)):
        for label, _ in fields:
            if f"{section} / {label}" not in placeholders:
                problems.append(f"{PR_TEMPLATE} field {section} / {label} does not carry the checker's placeholder")
    if CANONICAL_USAGE_COMMAND not in template:
        problems.append(f"{PR_TEMPLATE} must give the full-package usage command `{CANONICAL_USAGE_COMMAND}`")
    if "AGENTS.md" not in template:
        problems.append(f"{PR_TEMPLATE} must point to AGENTS.md for the completion-evidence rule")
    problems.extend(_dead_references(root, PR_TEMPLATE, template))
    work_package = _read(root, WORK_PACKAGE_TEMPLATE)
    if work_package is None:
        problems.append(f"{WORK_PACKAGE_TEMPLATE} is missing")
    elif checker.EVIDENCE_SECTION not in work_package:
        problems.append(f"{WORK_PACKAGE_TEMPLATE} must name the {checker.EVIDENCE_SECTION!r} record")
    for rel, text in ((PR_TEMPLATE, template), (WORK_PACKAGE_TEMPLATE, work_package or "")):
        if "--since-commit" in text:
            problems.append(f"{rel} presents --since-commit (post-commit only) as package usage; use the --since/--until window")
    if EVIDENCE_RULE_ANCHOR not in (_read(root, RULES) or ""):
        problems.append(f"{RULES} must state the {EVIDENCE_RULE_ANCHOR} rule (section 8)")
    return problems


#: The advisory evidence workflow's trust boundary (PR-DEVEX-EVIDENCE-870), checked as text (no YAML parser here).
ADVISORY_WORKFLOW = ".github/workflows/pr_evidence_advisory.yml"
CI_WORKFLOW = ".github/workflows/ci.yml"
ADVISORY_REQUIRED = (
    "on:\n  pull_request:\n    types: [ opened, edited, synchronize, reopened, ready_for_review ]\n",
    "permissions:\n  contents: read\n",
    "persist-credentials: false",
    'python3 tools/ci/check_pr_evidence.py --event "$GITHUB_EVENT_PATH"',
)
#: A privileged trigger, another ref, a widened token, a secret, a cache or a masked failure.
ADVISORY_FORBIDDEN = (
    "pull_request_target",
    "issue_comment",
    "workflow_run",
    "head.sha",
    "head.ref",
    "head_ref",
    "refs/pull/",
    "merge_commit_sha",
    "secrets.",
    "github.token",
    "github_token",
    ": write",
    "write-all",
    "id-token",
    "continue-on-error",
    "actions/cache",
    "pip install",
    "github-script",
)
ADVISORY_EXPRESSIONS = frozenset({"${{ github.event.pull_request.number }}"})
ADVISORY_MAX_TIMEOUT_MINUTES = 10
#: The reviewed workflow, every non-blank line that is not a full-line comment, exactly. This allowlist is the
#: contract: YAML has too many spellings (flow style, quoting, extra triggers or job-level permissions, a job named
#: like a required check) for a denylist to hold. Changing the workflow means changing this text in the same reviewed
#: diff; the checks above and below only explain which part of a mismatch matters.
ADVISORY_CANONICAL = """\
name: PR evidence advisory
on:
  pull_request:
    types: [ opened, edited, synchronize, reopened, ready_for_review ]
    branches: [ "**" ]
permissions:
  contents: read
concurrency:
  group: pr-evidence-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  pr-evidence:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
    - name: Check out the checker (no credentials kept)
      uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4
      with:
        persist-credentials: false
        sparse-checkout: tools/ci
    - name: Report completion-evidence findings (advisory)
      run: python3 tools/ci/check_pr_evidence.py --event "$GITHUB_EVENT_PATH" --summary "$GITHUB_STEP_SUMMARY" --annotations
"""


def _workflow_code(text: str) -> str:
    """ASCII-only line split: str.splitlines()/strip() treat Unicode spaces and breaks as whitespace; YAML does not."""

    lines = (line.rstrip(" ") for line in text.replace("\r\n", "\n").split("\n"))
    return "".join(f"{line}\n" for line in lines if line and not line.lstrip(" ").startswith("#"))


def advisory_workflow_problems(text: str) -> list[str]:
    rel = ADVISORY_WORKFLOW
    code = _workflow_code(text)
    problems: list[str] = []
    if re.search(r"[^\x20-\x7e\n]", text.replace("\r\n", "\n")):
        problems.append(f"{rel} must be printable ASCII (an invisible character can hide a command from review)")
    if code != ADVISORY_CANONICAL:
        problems.append(f"{rel} differs from the reviewed canonical form ADVISORY_CANONICAL in tools/ci/ci_truth.py")
    problems.extend(f"{rel} must contain {needle!r}" for needle in ADVISORY_REQUIRED if needle not in code)
    lowered = text.lower()  # forbidden text is refused even in a comment
    problems.extend(f"{rel} must not contain {needle!r}" for needle in ADVISORY_FORBIDDEN if needle in lowered)
    for expression in sorted(set(re.findall(r"\$\{\{.*?\}\}", text, flags=re.DOTALL))):
        if expression not in ADVISORY_EXPRESSIONS:
            problems.append(f"{rel} interpolates {expression!r}; only {sorted(ADVISORY_EXPRESSIONS)} are allowed")
    if re.search(r"^\s+(ref|repository):", text, flags=re.MULTILINE):
        problems.append(f"{rel} must check out the PR's own merge commit (no `ref:` or `repository:` override)")
    for action in re.findall(r"uses:\s*(\S+)", text):
        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action):
            problems.append(f"{rel} action {action!r} is not pinned to a full commit SHA")
    timeouts = [int(value) for value in re.findall(r"timeout-minutes:\s*(\d+)", text)]
    if not timeouts or max(timeouts) > ADVISORY_MAX_TIMEOUT_MINUTES:
        problems.append(f"{rel} needs a timeout-minutes of at most {ADVISORY_MAX_TIMEOUT_MINUTES}")
    jobs = re.findall(r"^  [a-z][a-z0-9-]*:\s*$", text.split("\njobs:", 1)[-1], flags=re.MULTILINE)
    if len(jobs) != 1:
        problems.append(f"{rel} must define exactly one job")
    return problems


def ci_trigger_problems(text: str) -> list[str]:
    """A PR-body edit must never rerun the census: ci.yml listens only to the default pull_request activity types."""

    triggers = text.split("\non:", 1)[-1].split("\npermissions:", 1)[0]
    return [
        f"{CI_WORKFLOW} must not trigger on {needle!r} (a PR-body edit would rerun the census)"
        for needle in ("edited", "ready_for_review", "pull_request_target", "types:")
        if needle in triggers
    ]


def workflow_contract_problems(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    for rel, check in ((ADVISORY_WORKFLOW, advisory_workflow_problems), (CI_WORKFLOW, ci_trigger_problems)):
        text = _read(root, rel)
        problems.extend([f"{rel} is missing"] if text is None else check(text))
    return problems


def _read(root: Path, rel: str) -> str | None:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.is_file() else None


def docs_truth_problems(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    coding = _read(root, CODING)
    agents = _read(root, "AGENTS.md")
    if coding is None:
        problems.append(f"{CODING} is missing")
    else:
        for heading in ("Level 1", "Level 2", "Level 3"):
            if heading not in coding:
                problems.append(f"{CODING} no longer defines {heading}")
        if "Python 3.14" not in coding:
            problems.append(f"{CODING} must name Python 3.14 as the supported interpreter")
        for stale in ("Python 3.11", "Python 3.12"):
            if stale in coding:
                problems.append(f"{CODING} still names {stale}")
        if "python tools/ci/run_pr_gate.py" not in coding:
            problems.append(f"{CODING} must point to `python tools/ci/run_pr_gate.py`")
        if "GitHub required CI" not in coding:
            problems.append(f"{CODING} must describe GitHub required CI")
        if "tools/ci/validation_plan.py" not in coding:
            problems.append(f"{CODING} must describe the repository-owned validation plan (tools/ci/validation_plan.py)")
    if agents is None:
        problems.append("AGENTS.md is missing")
    elif "python tools/ci/run_pr_gate.py" not in agents:
        problems.append("AGENTS.md must point to `python tools/ci/run_pr_gate.py`")
    problems.extend(status_problems(root))
    problems.extend(task_map_problems(root))
    problems.extend(rules_problems(root))
    problems.extend(completion_evidence_problems(root))
    for rel, phrases in STALE_PHRASES.items():
        text = _read(root, rel)
        if text is None:
            problems.append(f"{rel} is missing")
            continue
        for phrase in phrases:
            if phrase in text:
                problems.append(f"{rel} still states the pre-CI-110 workflow: {phrase!r}")
    return problems


def main() -> int:
    problems = docs_truth_problems() + workflow_contract_problems()
    for problem in problems:
        print(f"CI truth: {problem}", file=sys.stderr)
    if not problems:
        print("CI/testing documentation truth OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
