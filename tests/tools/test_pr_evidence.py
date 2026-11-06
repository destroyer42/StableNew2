"""PR-DEVEX-EVIDENCE-870: the advisory PR completion-evidence checker treats the body as untrusted data."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ci" / "check_pr_evidence.py"
sys.path.insert(0, str(SCRIPT.parent))

import check_pr_evidence as ev  # noqa: E402

HEAD = "0123456789abcdef0123456789abcdef01234567"

BASE_EVIDENCE = {
    "Accepted outcome": "The template and checker agree; accepted as delivered.",
    "Evidence mode": "deterministic test",
    "Evidence identity": "source 0123456789ab; tests/tools/test_pr_evidence.py",
    "Qualification claim": "N/A (no runtime behavior changes)",
    "Not demonstrated": "Live advisory run; it needs the workflow on main.",
    "Owner decision or blocker": "N/A",
    "Existing evidence reused": "N/A",
}
BASE_USAGE = {
    "Sessions": "claude:033a89ad-5ba7-4ff7-a692-ade0d3f1672f",
    "Model and effort": "Sonnet 5.5 Medium",
    "Repair passes and result": "0; PASS",
    "Measurement window": "2026-11-05T23:31:34-05:00 to 2026-11-06T01:10:00-05:00",
    "Measured tokens": "claude sonnet: 1 response, fresh input 10k, cache read 4.1M, cache write 90k, output 40k",
}


def body(
    evidence: dict | None = None,
    usage: dict | None = None,
    *,
    drop: tuple[str, ...] = (),
    extra: str = "",
) -> str:
    """A complete PR body built from the schema, with field overrides (value None removes the field)."""

    fields = {**BASE_EVIDENCE, **(evidence or {})}
    usage_fields = {**BASE_USAGE, **(usage or {})}
    out: list[str] = []
    for name, _ in ev.SECTIONS:
        if name in drop:
            continue
        out.append(f"## {name}\n")
        if name == ev.EVIDENCE_SECTION:
            out.extend(
                f"- {label}: {value}" for label, value in fields.items() if value is not None
            )
        elif name == ev.USAGE_SECTION:
            out.extend(
                f"- {label}: {value}" for label, value in usage_fields.items() if value is not None
            )
        elif name == "Execution class":
            out.append("Standard")
        else:
            out.append("Stated.")
        out.append("")
    return "\n".join(out) + extra


def codes(text: str, head_sha: str = HEAD) -> set[str]:
    return {finding.code for finding in ev.analyze_body(text, head_sha=head_sha)}


# --- legitimate records: scoped N/A, NOT RUN, HOLD and UNAVAILABLE are valid ------------------------------------


@pytest.mark.parametrize(
    "evidence, usage",
    [
        pytest.param(  # docs-only package, qualification not applicable
            {
                "Evidence mode": "documentation inspection",
                "Evidence identity": f"source {HEAD[:12]}; ci_truth.py OK",
            },
            None,
            id="docs-only",
        ),
        pytest.param(  # known-root-cause repair with focused deterministic tests
            {"Evidence identity": f"{HEAD}; tests/queue/test_x.py::test_root_cause"},
            None,
            id="root-cause-repair",
        ),
        pytest.param(  # simulated GUI journey with physical limits stated
            {
                "Evidence mode": "simulated desktop/integration (Xvfb journey)",
                "Evidence identity": f"{HEAD[:10]}; golden-path journey GP-03 log",
                "Not demonstrated": "Physical GPU generation; real Forge timing.",
                "Qualification claim": "NOT TESTED (physical run not authorized)",
            },
            None,
            id="simulated-gui",
        ),
        pytest.param(  # held physical qualification, nothing physical executed
            {
                "Evidence mode": "NOT RUN",
                "Evidence identity": "NOT RUN",
                "Qualification claim": "HOLD pending owner authorization of the physical run",
                "Owner decision or blocker": "Owner authorization for the physical run",
            },
            None,
            id="held-qualification",
        ),
        pytest.param(  # completed package with honestly unavailable telemetry
            None,
            {
                "Sessions": "UNAVAILABLE (host logs not on this machine)",
                "Measurement window": "UNAVAILABLE",
                "Measured tokens": "UNAVAILABLE: the session log was rotated before closeout",
            },
            id="telemetry-unavailable",
        ),
        pytest.param(  # reuse of earlier exact-source evidence after a docs-only follow-up
            {
                "Evidence identity": "abcdef1234567; full-suite and windows green",
                "Existing evidence reused": "abcdef1234567: only docs changed since, so source evidence still applies",
            },
            None,
            id="evidence-reuse",
        ),
    ],
)
def test_legitimate_completion_records_have_no_findings(evidence, usage) -> None:
    assert codes(body(evidence, usage)) == set()


def test_a_qualified_claim_with_reference_is_flagged_for_human_review_only() -> None:
    found = codes(
        body(
            {
                "Evidence mode": "physical runtime",
                "Qualification claim": "QUALIFIED: SYSTEM-840 verdict V-12 (owner-accepted)",
            }
        )
    )
    assert found == {"QUALIFIED_NEEDS_OWNER_ACCEPTANCE"}
    assert ev.MESSAGES["QUALIFIED_NEEDS_OWNER_ACCEPTANCE"][0] == ev.REVIEW


def test_bold_labels_continuation_lines_and_html_comments_are_read() -> None:
    text = body().replace("- Evidence identity:", "- **Evidence identity:**")
    text = text.replace(
        "- Not demonstrated: Live advisory run; it needs the workflow on main.",
        "- Not demonstrated:\n  - live advisory run\n  - physical GPU <!-- hidden: QUALIFIED -->",
    )
    assert codes(text) == set()


# --- missing, placeholder and contradictory records -------------------------------------------------------------


def test_the_unfilled_template_reports_placeholders_and_nothing_missing() -> None:
    template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    findings = ev.analyze_body(template)
    assert {f.code for f in findings} <= {"PLACEHOLDER", "EMPTY_SECTION"}
    placeholders = {f.location for f in findings if f.code == "PLACEHOLDER"}
    for section, fields in (
        (ev.EVIDENCE_SECTION, ev.EVIDENCE_FIELDS),
        (ev.USAGE_SECTION, ev.USAGE_FIELDS),
    ):
        assert {f"{section} / {label}" for label, _ in fields} <= placeholders


@pytest.mark.parametrize(
    "text, expected",
    [
        (body(drop=(ev.EVIDENCE_SECTION,)), "MISSING_SECTION"),
        (body({"Owner decision or blocker": None}), "MISSING_FIELD"),
        (body({"Not demonstrated": ""}), "EMPTY_FIELD"),
        (body({"Evidence mode": dict(ev.EVIDENCE_FIELDS)["Evidence mode"]}), "PLACEHOLDER"),
        (
            body(
                None,
                {"Measured tokens": "`python tools/usage_report.py --since <task-start> --line`"},
            ),
            "PLACEHOLDER",
        ),
        (body({"Evidence mode": "it works on my machine"}), "EVIDENCE_MODE_UNRECOGNIZED"),
        (body({"Evidence identity": "N/A"}), "IDENTITY_MISSING"),
        (body({"Evidence identity": "the tests passed"}), "IDENTITY_WITHOUT_SHA"),
        (
            body({"Evidence identity": "1234567 and 20261105"}),
            "IDENTITY_WITHOUT_SHA",
        ),  # numbers are not SHAs
        (body({"Evidence identity": "fedcba9876543; test_x"}), "IDENTITY_NOT_PR_HEAD"),
        (body({"Existing evidence reused": "the earlier run"}), "REUSE_WITHOUT_SHA"),
        (body({"Qualification claim": "probably fine"}), "QUALIFICATION_UNRECOGNIZED"),
        (body({"Qualification claim": "QUALIFIED"}), "QUALIFICATION_WITHOUT_REFERENCE"),
        (body({"Qualification claim": "INCONCLUSIVE"}), "QUALIFICATION_WITHOUT_REFERENCE"),
        (body({"Qualification claim": "QUALIFIED: N/A"}), "QUALIFICATION_WITHOUT_REFERENCE"),
        (
            body({"Qualification claim": "QUALIFIED via V-12, physical run NOT TESTED"}),
            "QUALIFICATION_CONTRADICTORY",
        ),
        (
            body({"Qualification claim": "QUALIFIED (V-12) but on HOLD"}),
            "QUALIFICATION_CONTRADICTORY",
        ),
        (
            body(
                {
                    "Evidence mode": "NOT RUN",
                    "Evidence identity": "NOT RUN",
                    "Qualification claim": "QUALIFIED V-12",
                }
            ),
            "QUALIFIED_WITHOUT_EVIDENCE",
        ),
        (
            body(drop=("Execution class",)).replace(
                "## Model recommendation",
                "## Execution class\n\nNarrow / Standard\n\n## Model recommendation",
            ),
            "EXECUTION_CLASS_INVALID",
        ),
        (body(None, {"Sessions": "the main session"}), "SESSION_ID_MISSING"),
        (body(None, {"Repair passes and result": "0"}), "RESULT_MISSING"),
        (body(None, {"Measurement window": "2026-11-05 evening"}), "WINDOW_INVALID"),
        (
            body(None, {"Measurement window": "2026-11-05T23:31 to 2026-11-06T01:10"}),
            "WINDOW_INVALID",
        ),  # no timezone
        (body(None, {"Measurement window": "UNAVAILABLE"}), "USAGE_WITHOUT_WINDOW"),
        (body(None, {"Measured tokens": "UNAVAILABLE"}), "UNAVAILABLE_WITHOUT_REASON"),
        (body(None, {"Measured tokens": "output 40k (about $1.20)"}), "COST_REPORTED"),
        (
            body(
                None,
                {
                    "Measured tokens": "`python tools/usage_report.py --since-commit a1b2c3d --line`: output 40k"
                },
            ),
            "SINCE_COMMIT_AS_PACKAGE_USAGE",
        ),
        (body(extra="\n## Model / usage\n\n- Sessions: other:abcd1234\n"), "DUPLICATE_SECTION"),
        (
            body({"Owner decision or blocker": "N/A\n- Owner decision or blocker: approve D9"}),
            "DUPLICATE_FIELD",
        ),
        ("", "BODY_EMPTY"),
        ("x" * (ev.MAX_BODY_CHARS + 1), "BODY_TOO_LARGE"),
    ],
    ids=lambda value: value if value in ev.MESSAGES else "",
)
def test_incomplete_or_contradictory_records_are_detected(text: str, expected: str) -> None:
    assert expected in codes(text)


def test_since_commit_is_accepted_when_labelled_post_commit() -> None:
    text = body(
        None,
        {"Measured tokens": "output 40k; also --since-commit a1b2c3d post-commit only: output 9k"},
    )
    assert "SINCE_COMMIT_AS_PACKAGE_USAGE" not in codes(text)


def test_closing_hash_sequences_are_dropped_but_hashes_inside_a_heading_are_kept() -> None:
    assert ev._heading_name("Outcome ##") == "outcome"
    assert ev._heading_name("Outcome") == "outcome"
    assert ev._heading_name("C#") == "c#"
    assert "MISSING_SECTION" not in codes(body().replace("## Outcome\n", "## Outcome ##\n"))


@pytest.mark.parametrize(
    "line",
    [
        "## a"
        + " " * 65_000
        + "x",  # cubic backtracking in the earlier heading regex (security review)
        "## " + "#" * 65_000 + " x",
        "- Evidence mode" + " " * 65_000 + "x",
        "- " + "a" * 65_000 + ":",
        "0" * 65_000,
        "2026-11-05T23:31 " * 3_800,
    ],
    ids=[
        "heading-spaces",
        "heading-hashes",
        "field-spaces",
        "field-label",
        "hex-run",
        "timestamps",
    ],
)
def test_a_maximum_size_adversarial_line_is_analyzed_in_linear_time(line: str) -> None:
    import time

    text = body().replace("## Outcome\n", f"## Outcome\n{line}\n")[: ev.MAX_BODY_CHARS]
    started = time.perf_counter()
    ev.analyze_body(text, head_sha=HEAD)
    ev.analyze_body(line[: ev.MAX_BODY_CHARS])
    assert time.perf_counter() - started < 2.0


def test_headings_inside_code_fences_and_level_three_headings_are_not_sections() -> None:
    text = (
        body(drop=(ev.USAGE_SECTION,))
        + "\n```\n## Model / usage\n- Sessions: claude:abcd\n```\n### Model / usage\n"
    )
    assert "MISSING_SECTION" in codes(text)


# --- untrusted input: never echoed, executed or trusted as structure ----------------------------------------------

INJECTIONS = (
    "$(touch /tmp/pwned)",
    "`rm -rf ~`",
    "${{ secrets.GITHUB_TOKEN }}",
    "::set-output name=x::y",
    "::add-mask::abc",
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "| injected | table |",
    "'; DROP TABLE jobs; --",
    "\x1b[31mred\x1b[0m",
)


def _adversarial_body() -> str:
    hostile = " ".join(INJECTIONS)
    return body(
        {
            "Accepted outcome": hostile,
            "Evidence mode": hostile,
            "Qualification claim": "QUALIFIED " + hostile,
        },
        {"Sessions": hostile},
        extra=f"\n## {hostile}\n\n{hostile}\n## Outcome\n\n{hostile}\n",
    )


def test_hostile_body_text_never_reaches_any_output(tmp_path: Path) -> None:
    findings = ev.analyze_body(_adversarial_body(), head_sha=HEAD)
    assert findings  # still analyzed, not crashed
    rendered = "\n".join(
        [
            *ev.render_lines(findings, draft=False),
            *ev.render_annotations(findings, draft=False),
            ev.render_summary(findings, draft=False),
        ]
    )
    for needle in (*INJECTIONS, "pwned", "alert(1)", "DROP TABLE", "\x1b"):
        assert needle not in rendered
    for finding in findings:  # every location is a schema label, never PR text
        assert finding.location in _schema_locations()


def test_annotations_are_single_line_and_drafts_downgrade_to_notices() -> None:
    findings = [
        ev.Finding("MISSING_SECTION", "Outcome"),
        ev.Finding("QUALIFIED_NEEDS_OWNER_ACCEPTANCE", "x"),
    ]
    ready = ev.render_annotations(findings, draft=False)
    assert ready[0].startswith("::warning ") and ready[1].startswith("::notice ")
    assert all(line.startswith("::notice ") for line in ev.render_annotations(findings, draft=True))
    assert all("\n" not in line and "\r" not in line for line in ready)
    assert len(ev.render_annotations([findings[0]] * 500, draft=False)) == ev.MAX_REPORTED_FINDINGS


def test_every_finding_code_has_a_static_message_and_severity() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    used = set(__import__("re").findall(r'Finding\("([A-Z_]+)"', source))
    assert used <= set(ev.MESSAGES)
    assert {severity for severity, _ in ev.MESSAGES.values()} == {ev.WARNING, ev.REVIEW}


def _schema_locations() -> set[str]:
    locations = {"body", ev.USAGE_SECTION, *(name for name, _ in ev.SECTIONS)}
    for section, fields in (
        (ev.EVIDENCE_SECTION, ev.EVIDENCE_FIELDS),
        (ev.USAGE_SECTION, ev.USAGE_FIELDS),
    ):
        locations.update(f"{section} / {label}" for label, _ in fields)
    return locations


# --- event loading and CLI ---------------------------------------------------------------------------------------


def _event(tmp_path: Path, payload: object, name: str = "event.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _pull(**overrides: object) -> dict:
    return {
        "action": "edited",
        "pull_request": {
            "number": 7,
            "body": body(),
            "draft": False,
            "head": {"sha": HEAD},
            **overrides,
        },
    }


def test_the_event_loader_extracts_only_body_draft_and_head(tmp_path: Path) -> None:
    pull = ev.load_event(_event(tmp_path, _pull(draft=True, head={"sha": "not-a-sha; rm -rf /"})))
    assert pull.body == body() and pull.draft is True and pull.head_sha == ""
    assert ev.load_event(_event(tmp_path, _pull(body=None))).body == ""


@pytest.mark.parametrize(
    "raw, code",
    [
        (b"{not json", "EVENT_NOT_JSON"),
        (b"\xff\xfe\x00garbage", "EVENT_NOT_UTF8"),
        (b"[1, 2, 3]", "EVENT_NOT_PULL_REQUEST"),
        (json.dumps({"issue": {"body": "x"}}).encode(), "EVENT_NOT_PULL_REQUEST"),
        (json.dumps({"pull_request": {"body": ["x"]}}).encode(), "EVENT_BODY_NOT_TEXT"),
        (
            json.dumps({"pull_request": {"body": "x", "draft": "yes"}}).encode(),
            "EVENT_DRAFT_NOT_BOOLEAN",
        ),
        (
            b"[" * 100_000 + b"]" * 100_000,
            # Deep nesting is an input error, not a crash. The interpreter decides which: a RecursionError (3.14.9)
            # is EVENT_NOT_JSON; a build that parses the depth (3.14.10) yields a list, not a pull-request event.
            "EVENT_NOT_JSON|EVENT_NOT_PULL_REQUEST",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_malformed_events_are_input_errors(tmp_path: Path, raw: bytes, code: str) -> None:
    path = tmp_path / "event.json"
    path.write_bytes(raw)
    with pytest.raises(ev.InputError, match=code):
        ev.load_event(path)


def test_an_oversized_event_is_refused_before_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ev, "MAX_EVENT_BYTES", 64)
    with pytest.raises(ev.InputError, match="EVENT_TOO_LARGE"):
        ev.load_event(_event(tmp_path, _pull()))


def test_findings_are_advisory_and_input_errors_are_visible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    incomplete = _event(tmp_path, _pull(body=body(drop=(ev.EVIDENCE_SECTION,))))
    assert ev.main(["--event", str(incomplete), "--summary", str(summary), "--annotations"]) == 0
    out = capsys.readouterr().out
    assert "MISSING_SECTION" in out and "::warning title=PR evidence (advisory)::" in out
    assert "MISSING_SECTION" in summary.read_text(
        encoding="utf-8"
    ) and "Advisory only" in summary.read_text(encoding="utf-8")

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert ev.main(["--event", str(broken)]) == 2
    captured = capsys.readouterr()
    assert "input error EVENT_NOT_JSON" in captured.err and "no findings" not in captured.out


def test_the_checker_runs_with_the_standard_library_only_and_needs_no_application(
    tmp_path: Path,
) -> None:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert imports <= {"__future__", "argparse", "json", "re", "sys", "pathlib", "typing"}

    draft = tmp_path / "draft.md"
    draft.write_text(_adversarial_body(), encoding="utf-8")
    # -I -S: isolated mode without site-packages, run from an unrelated directory (no repository code importable).
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--body-file", str(draft)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "advisory finding" in result.stdout and "pwned" not in result.stdout
    assert not (tmp_path / "pwned").exists()
