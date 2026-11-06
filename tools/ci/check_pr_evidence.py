"""Advisory check of a PR body's completion-evidence record against the PR template (PR-DEVEX-EVIDENCE-870).

The rule is ``AGENTS.md`` section 8; ``.github/pull_request_template.md`` is the record; this module owns the record's
schema (``SECTIONS``, ``EVIDENCE_FIELDS``, ``USAGE_FIELDS``) and ``tools/ci/ci_truth.py`` checks that the template matches it.

The PR body is untrusted data. It is read only from the GitHub event JSON (or a local file the operator names), parsed by
a small line-based section extractor and never executed, evaluated, interpolated into a command or used to choose a path.
Output carries only static finding codes and the schema's own field names, never PR text. Missing or contradictory
fields are advisory findings (exit 0); a malformed or oversized event is an input error (exit 2), never a silent pass.
Standard library only; no network, no GitHub writes, no application imports.

    python tools/ci/check_pr_evidence.py --body-file draft.md                  # check a draft body locally
    python tools/ci/check_pr_evidence.py --event "$GITHUB_EVENT_PATH" --summary "$GITHUB_STEP_SUMMARY" --annotations
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

MAX_EVENT_BYTES = 4_000_000
MAX_BODY_CHARS = 65_536  # GitHub's own limit for a PR body
MAX_REPORTED_FINDINGS = 40

EVIDENCE_SECTION = "Acceptance and evidence boundary"
USAGE_SECTION = "Model / usage"

#: Template headings in order, with the template's own body text for free-text sections ("" = empty in the template).
#: ``None`` marks a section made of the labelled fields below.
SECTIONS: tuple[tuple[str, str | None], ...] = (
    ("Outcome", ""),
    ("Execution class", "Narrow / Standard / Architectural"),
    (
        "Model recommendation",
        "Claude Code model + effort; Codex model + effort; why this is the lowest tier likely to finish the package; "
        "expected usage (order of magnitude).",
    ),
    ("Architecture and invariants affected", ""),
    ("Controller-surface effect", ""),
    ("Focused validation", ""),
    ("Required CI", ""),
    (EVIDENCE_SECTION, None),
    ("Known non-blocking debt", ""),
    ("Unrelated user work preserved", ""),
    ("Follow-up", ""),
    (USAGE_SECTION, None),
)

#: (label, template placeholder). The placeholder is how an unfilled field is recognized.
EVIDENCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("Accepted outcome", "<observable result and disposition>"),
    (
        "Evidence mode",
        "<documentation inspection | deterministic test | simulated desktop/integration | physical runtime | "
        "operator-reviewed output | NOT RUN>",
    ),
    ("Evidence identity", "<exact source SHA; named tests, logs or accepted archives>"),
    ("Qualification claim", "<QUALIFIED + accepted verdict reference | N/A | NOT TESTED | HOLD>"),
    ("Not demonstrated", "<scope this evidence does not establish>"),
    ("Owner decision or blocker", "<decision or blocker, or N/A>"),
    ("Existing evidence reused", "<source SHA and why it still applies, or N/A>"),
)
USAGE_FIELDS: tuple[tuple[str, str], ...] = (
    ("Sessions", "<host:id for every participating session; name any shared-session window>"),
    ("Model and effort", "<actual model + effort>"),
    ("Repair passes and result", "<n; PASS | FAIL | BLOCKED>"),
    (
        "Measurement window",
        "<task-start, recorded before discovery> to <closeout-end>, ISO 8601 with timezone",
    ),
    (
        "Measured tokens",
        "<`python tools/usage_report.py --since <task-start> --until <closeout-end> --session <host:id> --line` output, "
        "or UNAVAILABLE and why>",
    ),
)
#: Tokens that only ever appear in an unfilled template value.
PLACEHOLDER_TOKENS = ("<task-start>", "<closeout-end>", "<host:id>")

EVIDENCE_MODES = (
    "documentation inspection",
    "deterministic test",
    "simulated",
    "physical runtime",
    "operator-reviewed",
    "not run",
)
#: Leading keyword of a qualification claim. Verdict keywords need a reference; the others stand alone.
VERDICT_KEYWORDS = ("NOT QUALIFIED", "QUALIFIED", "CONDITIONAL", "INCONCLUSIVE", "FAILED")
NON_VERDICT_KEYWORDS = ("N/A", "NOT TESTED", "HOLD", "NOT RUN")

WARNING = "warning"
REVIEW = "review"  # a claim the checker cannot verify; a person must

#: code -> (severity, static message). Output is built only from these and the schema labels.
MESSAGES: dict[str, tuple[str, str]] = {
    "BODY_EMPTY": (WARNING, "the PR body is empty; fill the PR template"),
    "BODY_TOO_LARGE": (WARNING, "the PR body exceeds the GitHub size limit and was not analyzed"),
    "MISSING_SECTION": (WARNING, "required template section is absent"),
    "DUPLICATE_SECTION": (REVIEW, "section appears more than once; only the first was read"),
    "EMPTY_SECTION": (WARNING, "section is empty"),
    "PLACEHOLDER": (WARNING, "template placeholder left unchanged"),
    "MISSING_FIELD": (WARNING, "required field is absent"),
    "DUPLICATE_FIELD": (REVIEW, "field appears more than once; only the first was read"),
    "EMPTY_FIELD": (
        WARNING,
        "field is empty; write N/A, NOT RUN or UNAVAILABLE where that is the truth",
    ),
    "EXECUTION_CLASS_INVALID": (WARNING, "name exactly one of Narrow, Standard or Architectural"),
    "EVIDENCE_MODE_UNRECOGNIZED": (
        REVIEW,
        "no recognized evidence mode; state what was actually run",
    ),
    "IDENTITY_MISSING": (WARNING, "evidence is claimed but its identity is N/A or NOT RUN"),
    "IDENTITY_WITHOUT_SHA": (WARNING, "evidence identity names no source commit SHA"),
    "IDENTITY_NOT_PR_HEAD": (
        REVIEW,
        "no evidence SHA matches the PR head and no reuse is declared; confirm it applies",
    ),
    "QUALIFICATION_UNRECOGNIZED": (
        WARNING,
        "start with QUALIFIED, CONDITIONAL, INCONCLUSIVE, FAILED, N/A, NOT TESTED or HOLD",
    ),
    "QUALIFICATION_WITHOUT_REFERENCE": (
        WARNING,
        "a qualification verdict needs the accepted verdict reference",
    ),
    "QUALIFICATION_CONTRADICTORY": (
        WARNING,
        "QUALIFIED is combined with an unqualified, untested, held or N/A statement",
    ),
    "QUALIFIED_WITHOUT_EVIDENCE": (
        WARNING,
        "QUALIFIED with evidence mode NOT RUN and no reused evidence",
    ),
    "QUALIFIED_NEEDS_OWNER_ACCEPTANCE": (
        REVIEW,
        "a QUALIFIED claim cannot be verified mechanically; confirm the accepted verdict and its identity",
    ),
    "REUSE_WITHOUT_SHA": (WARNING, "reused evidence names no source commit SHA"),
    "SESSION_ID_MISSING": (WARNING, "name each participating session as host:id, or UNAVAILABLE"),
    "RESULT_MISSING": (WARNING, "state the result as PASS, FAIL or BLOCKED"),
    "WINDOW_INVALID": (
        WARNING,
        "give the start and end as ISO 8601 timestamps with timezone, or UNAVAILABLE",
    ),
    "USAGE_WITHOUT_WINDOW": (WARNING, "measured tokens are reported without a measurement window"),
    "UNAVAILABLE_WITHOUT_REASON": (REVIEW, "say why telemetry is unavailable"),
    "COST_REPORTED": (WARNING, "report tokens only; never convert usage to a price"),
    "SINCE_COMMIT_AS_PACKAGE_USAGE": (
        WARNING,
        "--since-commit measures post-commit usage only; use the --since/--until window or label it post-commit",
    ),
}


class InputError(Exception):
    """The event could not be read as a pull-request event. The message is a static diagnostic code."""


class Finding(NamedTuple):
    code: str
    location: str  # always a schema label, never PR text

    @property
    def severity(self) -> str:
        return MESSAGES[self.code][0]

    @property
    def message(self) -> str:
        return MESSAGES[self.code][1]


class PullRequest(NamedTuple):
    body: str
    draft: bool
    head_sha: str


#: Linear by construction: the optional closing ``#`` sequence is removed in Python (``_heading_name``), never by a
#: regex with adjacent optional runs (that form backtracks cubically on a long heading line).
_HEADING = re.compile(r"^##[ \t]+(\S.*)$")
_FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
_FIELD = re.compile(
    r"^[ ]{0,3}[-*+][ \t]+(?:\*\*)?([A-Za-z][A-Za-z /-]{0,60}?)(?:\*\*)?[ \t]*:(?:\*\*)?[ \t]*(.*)$"
)
_SHA = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?[ ]?(?:Z|[+-]\d{2}:?\d{2})"
)
_SESSION = re.compile(r"(?<![A-Za-z0-9])[a-z][a-z0-9_-]{1,30}:[A-Za-z0-9][A-Za-z0-9._-]{3,}")
_RESULT = re.compile(r"\b(PASS|FAIL|BLOCKED)\b")
_CLASS = re.compile(r"\b(narrow|standard|architectural)\b", re.IGNORECASE)
_COST = re.compile(r"(\$\s?\d|\bUSD\b|\bdollars?\b)", re.IGNORECASE)
_CONTRADICTION = re.compile(
    r"\b(NOT QUALIFIED|UNQUALIFIED|NOT TESTED|HOLD|INCONCLUSIVE)\b|(?<![A-Z0-9])N/A(?![A-Z0-9])"
)


def _heading_name(raw: str) -> str:
    """ATX heading text without its optional closing ``#`` sequence (which must follow a space)."""

    name = raw.rstrip(" \t")
    closed = name.rstrip("#")
    if closed != name and (not closed or closed[-1] in " \t"):
        name = closed.rstrip(" \t")
    return name.strip().lower()


def _strip_comments(text: str) -> str:
    """Drop HTML comments (an unterminated one hides the rest, as GitHub renders it)."""

    out: list[str] = []
    position = 0
    while True:
        start = text.find("<!--", position)
        if start < 0:
            out.append(text[position:])
            return "".join(out)
        out.append(text[position:start])
        end = text.find("-->", start + 4)
        if end < 0:
            return "".join(out)
        position = end + 3


def split_sections(body: str) -> tuple[dict[str, list[str]], set[str]]:
    """Level-2 headings outside code fences -> their body lines. Returns (first occurrence per name, duplicated names)."""

    sections: dict[str, list[str]] = {}
    duplicates: set[str] = set()
    current: list[str] | None = None
    fence = ""
    for line in _strip_comments(body).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        marker = _FENCE.match(line)
        if marker:
            token = marker.group(1)
            if not fence:
                fence = token[0] * 3
            elif token.startswith(fence):
                fence = ""
        elif not fence:
            heading = _HEADING.match(line)
            if heading:
                name = _heading_name(heading.group(1))
                if name in sections:
                    duplicates.add(name)
                    current = None  # the duplicate's text is ignored
                else:
                    current = sections.setdefault(name, [])
                continue
        if current is not None:
            current.append(line)
    return sections, duplicates


def _fields(lines: list[str], labels: tuple[str, ...]) -> tuple[dict[str, str], set[str]]:
    """Known ``- Label: value`` bullets; following non-field lines continue the value (sub-bullets, wrapped text)."""

    known = {label.lower(): label for label in labels}
    values: dict[str, list[str]] = {}
    duplicates: set[str] = set()
    current: list[str] | None = None
    for line in lines:
        match = _FIELD.match(line)
        label = known.get(match.group(1).strip().lower()) if match else None
        if match and label:
            if label in values:
                duplicates.add(label)
                current = None
            else:
                current = values.setdefault(label, [match.group(2).strip()])
        elif current is not None and line.strip():
            current.append(line.strip())
    return {
        label: " ".join(part for part in parts if part).strip() for label, parts in values.items()
    }, duplicates


def _plain(value: str) -> str:
    return value.replace("**", "").replace("`", "").strip()


def _is_na(value: str) -> bool:
    head = _plain(value).upper().rstrip(".")
    return head in {"N/A", "NA", "NONE", "NOT APPLICABLE"} or head.startswith(
        ("N/A ", "N/A:", "N/A;", "N/A,", "N/A -", "N/A (")
    )


def _is_placeholder(value: str, placeholder: str) -> bool:
    return placeholder in value or any(token in value for token in PLACEHOLDER_TOKENS)


def _shas(value: str, head_sha: str = "") -> list[str]:
    """Commit-SHA-like tokens. An all-digit token counts only as a full SHA or a prefix of the PR head (else a number)."""

    return [
        sha
        for sha in _SHA.findall(value)
        if len(sha) == 40
        or any(ch in "abcdef" for ch in sha)
        or (head_sha and head_sha.startswith(sha))
    ]


def _qualification_keyword(value: str) -> tuple[str, str]:
    """(leading keyword, remainder) or ("", value) when the claim does not start with a recognized keyword."""

    plain = _plain(value)
    upper = plain.upper()
    for keyword in (*VERDICT_KEYWORDS, *NON_VERDICT_KEYWORDS):
        if upper.startswith(keyword) and (
            len(upper) == len(keyword) or not upper[len(keyword)].isalnum()
        ):
            return keyword, plain[len(keyword) :].strip(" \t:;,.-–—()")
    return "", plain


def _filled(
    section: str, lines: list[str], schema: tuple[tuple[str, str], ...], findings: list[Finding]
) -> dict[str, str]:
    """Field values that are present, non-empty and not placeholders; records findings for the rest."""

    values, duplicates = _fields(lines, tuple(label for label, _ in schema))
    filled: dict[str, str] = {}
    for label, placeholder in schema:
        location = f"{section} / {label}"
        if label in duplicates:
            findings.append(Finding("DUPLICATE_FIELD", location))
        value = values.get(label)
        if value is None:
            findings.append(Finding("MISSING_FIELD", location))
        elif not _plain(value):
            findings.append(Finding("EMPTY_FIELD", location))
        elif _is_placeholder(value, placeholder):
            findings.append(Finding("PLACEHOLDER", location))
        else:
            filled[label] = value
    return filled


def _check_evidence(lines: list[str], head_sha: str, findings: list[Finding]) -> None:
    section = EVIDENCE_SECTION
    values = _filled(section, lines, EVIDENCE_FIELDS, findings)
    mode = _plain(values.get("Evidence mode", "")).lower()
    modes = {name for name in EVIDENCE_MODES if name in mode}
    if "Evidence mode" in values and not modes:
        findings.append(Finding("EVIDENCE_MODE_UNRECOGNIZED", f"{section} / Evidence mode"))
    reuse = values.get("Existing evidence reused")
    reused = reuse is not None and not _is_na(reuse)
    if reused and not _shas(reuse or ""):
        findings.append(Finding("REUSE_WITHOUT_SHA", f"{section} / Existing evidence reused"))

    identity = values.get("Evidence identity")
    if identity is not None and modes - {"not run"}:
        upper = _plain(identity).upper()
        location = f"{section} / Evidence identity"
        if _is_na(identity) or upper.startswith("NOT RUN"):
            findings.append(Finding("IDENTITY_MISSING", location))
        elif not _shas(identity, head_sha):
            findings.append(Finding("IDENTITY_WITHOUT_SHA", location))
        elif (
            head_sha
            and not reused
            and not any(head_sha.startswith(sha) for sha in _shas(identity, head_sha))
        ):
            findings.append(Finding("IDENTITY_NOT_PR_HEAD", location))

    claim = values.get("Qualification claim")
    if claim is None:
        return
    location = f"{section} / Qualification claim"
    keyword, remainder = _qualification_keyword(claim)
    if not keyword:
        findings.append(Finding("QUALIFICATION_UNRECOGNIZED", location))
        return
    if keyword in VERDICT_KEYWORDS and (not remainder or _is_na(remainder)):
        findings.append(Finding("QUALIFICATION_WITHOUT_REFERENCE", location))
    if keyword == "QUALIFIED":
        if _CONTRADICTION.search(remainder.upper()):
            findings.append(Finding("QUALIFICATION_CONTRADICTORY", location))
        if modes == {"not run"} and not reused:
            findings.append(Finding("QUALIFIED_WITHOUT_EVIDENCE", location))
        findings.append(Finding("QUALIFIED_NEEDS_OWNER_ACCEPTANCE", location))


def _check_usage(lines: list[str], findings: list[Finding]) -> None:
    section = USAGE_SECTION
    text = "\n".join(lines)
    if "--since-commit" in text and "post-commit" not in text.lower():
        findings.append(Finding("SINCE_COMMIT_AS_PACKAGE_USAGE", section))
    values = _filled(section, lines, USAGE_FIELDS, findings)

    def unavailable(value: str) -> bool:
        return _plain(value).upper().startswith("UNAVAILABLE")

    sessions = values.get("Sessions")
    if sessions is not None and not unavailable(sessions) and not _SESSION.search(sessions):
        findings.append(Finding("SESSION_ID_MISSING", f"{section} / Sessions"))
    result = values.get("Repair passes and result")
    if result is not None and not _RESULT.search(result):
        findings.append(Finding("RESULT_MISSING", f"{section} / Repair passes and result"))
    window = values.get("Measurement window")
    window_ok = window is not None and len(_TIMESTAMP.findall(window)) >= 2
    if window is not None and not window_ok and not unavailable(window):
        findings.append(Finding("WINDOW_INVALID", f"{section} / Measurement window"))
    tokens = values.get("Measured tokens")
    if tokens is None:
        return
    location = f"{section} / Measured tokens"
    if _COST.search(tokens):
        findings.append(Finding("COST_REPORTED", location))
    if unavailable(tokens):
        if not _plain(tokens)[len("UNAVAILABLE") :].strip(" \t:;,.-–—()"):
            findings.append(Finding("UNAVAILABLE_WITHOUT_REASON", location))
    elif any(ch.isdigit() for ch in tokens) and window is not None and not window_ok:
        findings.append(Finding("USAGE_WITHOUT_WINDOW", location))


def analyze_body(body: str, *, head_sha: str = "") -> list[Finding]:
    """All findings for one PR body, in template order. Pure: no I/O."""

    if len(body) > MAX_BODY_CHARS:
        return [Finding("BODY_TOO_LARGE", "body")]
    if not body.strip():
        return [Finding("BODY_EMPTY", "body")]
    sections, duplicates = split_sections(body)
    findings: list[Finding] = []
    for name, template_text in SECTIONS:
        key = name.lower()
        if key in duplicates:
            findings.append(Finding("DUPLICATE_SECTION", name))
        lines = sections.get(key)
        if lines is None:
            findings.append(Finding("MISSING_SECTION", name))
        elif name == EVIDENCE_SECTION:
            _check_evidence(lines, head_sha, findings)
        elif name == USAGE_SECTION:
            _check_usage(lines, findings)
        else:
            text = "\n".join(lines).strip()
            if not _plain(text):
                findings.append(Finding("EMPTY_SECTION", name))
            elif template_text and text == template_text:
                findings.append(Finding("PLACEHOLDER", name))
            elif name == "Execution class" and len({m.lower() for m in _CLASS.findall(text)}) != 1:
                findings.append(Finding("EXECUTION_CLASS_INVALID", name))
    return findings


def load_event(path: Path) -> PullRequest:
    """Extract only the body, draft flag and head SHA from a pull-request event file; raise InputError otherwise."""

    try:
        if path.stat().st_size > MAX_EVENT_BYTES:
            raise InputError("EVENT_TOO_LARGE")
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError("EVENT_UNREADABLE") from exc
    try:
        event = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise InputError("EVENT_NOT_UTF8") from exc
    except (ValueError, RecursionError) as exc:
        raise InputError("EVENT_NOT_JSON") from exc
    pull = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pull, dict):
        raise InputError("EVENT_NOT_PULL_REQUEST")
    body = pull.get("body")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise InputError("EVENT_BODY_NOT_TEXT")
    draft = pull.get("draft", False)
    if not isinstance(draft, bool):
        raise InputError("EVENT_DRAFT_NOT_BOOLEAN")
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    head_sha = sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) else ""
    return PullRequest(body=body, draft=draft, head_sha=head_sha)


def _escape_command(text: str) -> str:
    """GitHub workflow-command data escaping (the inputs are static already; this keeps them single-line)."""

    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_lines(findings: list[Finding], *, draft: bool) -> list[str]:
    if not findings:
        return [
            "PR evidence: no findings (fields are filled; the claims themselves still need review)"
        ]
    lines = [f"PR evidence: {len(findings)} advisory finding(s){' (draft PR)' if draft else ''}"]
    for finding in findings[:MAX_REPORTED_FINDINGS]:
        lines.append(f"  {finding.code} [{finding.severity}] {finding.location}: {finding.message}")
    if len(findings) > MAX_REPORTED_FINDINGS:
        lines.append(f"  ... {len(findings) - MAX_REPORTED_FINDINGS} more")
    return lines


def render_annotations(findings: list[Finding], *, draft: bool) -> list[str]:
    out = []
    for finding in findings[:MAX_REPORTED_FINDINGS]:
        level = "notice" if draft or finding.severity == REVIEW else "warning"
        text = _escape_command(f"{finding.code} at {finding.location}: {finding.message}")
        out.append(f"::{level} title=PR evidence (advisory)::{text}")
    return out


def render_summary(findings: list[Finding], *, draft: bool) -> str:
    lines = ["## PR evidence (advisory)", ""]
    lines.append(
        "Advisory only: not a required check. It verifies that the completion-evidence fields are filled and internally "
        "consistent, not that the evidence exists or is true. Rule: `AGENTS.md` section 8."
    )
    lines.append("")
    if draft:
        lines.extend(["Draft PR: incomplete fields are expected until it is ready for review.", ""])
    if not findings:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"
    lines.extend(["| Code | Severity | Where | What |", "|---|---|---|---|"])
    for finding in findings[:MAX_REPORTED_FINDINGS]:
        lines.append(
            f"| `{finding.code}` | {finding.severity} | {finding.location} | {finding.message} |"
        )
    if len(findings) > MAX_REPORTED_FINDINGS:
        lines.append(f"\n{len(findings) - MAX_REPORTED_FINDINGS} more finding(s) not shown.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--event", type=Path, help="GitHub pull-request event JSON (GITHUB_EVENT_PATH)"
    )
    source.add_argument("--body-file", type=Path, help="a local Markdown PR body")
    parser.add_argument(
        "--summary", type=Path, help="append a Markdown summary here (GITHUB_STEP_SUMMARY)"
    )
    parser.add_argument(
        "--annotations", action="store_true", help="emit GitHub warning/notice annotations"
    )
    args = parser.parse_args(argv)

    try:
        if args.event is not None:
            pull = load_event(args.event)
        else:
            try:
                if args.body_file.stat().st_size > MAX_EVENT_BYTES:
                    raise InputError("BODY_FILE_TOO_LARGE")
                pull = PullRequest(args.body_file.read_text(encoding="utf-8"), False, "")
            except (OSError, UnicodeDecodeError) as exc:
                raise InputError("BODY_FILE_UNREADABLE") from exc
    except InputError as exc:
        print(f"PR evidence: input error {exc}", file=sys.stderr)
        return 2

    findings = analyze_body(pull.body, head_sha=pull.head_sha)
    for line in render_lines(findings, draft=pull.draft):
        print(line)
    if args.annotations:
        for line in render_annotations(findings, draft=pull.draft):
            print(line)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(render_summary(findings, draft=pull.draft))
    return 0


if __name__ == "__main__":
    sys.exit(main())
