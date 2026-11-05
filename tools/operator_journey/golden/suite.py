"""Suite runner: executes the golden-path journeys in a mode and writes the per-run evidence folder.

Evidence folder (outside Git, default ``reports/operator_journeys/``): ``plan.json``, ``evidence.json``, ``summary.md``,
``actions.jsonl``, ``screenshots/``, ``artifacts.json``, ``logs/`` (bounded, redacted) and, for physical runs,
``resource_telemetry.jsonl``.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from tools.operator_journey.evidence import FAIL, HOLD, NO_GO, PASS, JourneyEvidence
from tools.operator_journey.golden import SUITE_ID, SUITE_VERSION
from tools.operator_journey.golden.definitions import ADVANCED_ORDER, JourneyDef, select
from tools.operator_journey.golden.friction import friction_report, outcomes
from tools.operator_journey.golden.modes import (
    PHYSICAL,
    READINESS,
    SIMULATED,
    ModeRefusal,
    validate_combination,
)
from tools.operator_journey.golden.provenance import provenance
from tools.operator_journey.golden.session import RunConfig
from tools.operator_journey.workspace import REPO_ROOT, repo_sha

EVIDENCE_SCHEMA = "2"
EXIT_CODES = {PASS: 0, FAIL: 1, HOLD: 2, NO_GO: 3}
EXIT_REFUSED = 4
_LOG_LIMIT = 20_000
_HOME = str(Path.home())
_REDACTIONS = (
    # the home path in the three spellings a report can carry: native, forward slashes and JSON-escaped
    *(
        (re.compile(re.escape(form), re.IGNORECASE), "~")
        for form in sorted(
            {_HOME, _HOME.replace("\\", "/"), _HOME.replace("\\", "\\\\")}, key=len, reverse=True
        )
    ),
    (re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+"), r"\1=<redacted>"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer <redacted>"),
)
_WORST = {PASS: 0, HOLD: 1, FAIL: 2, NO_GO: 3}


def journey_assessment(
    r: JourneyEvidence, driver: str, *, physical: bool = False
) -> dict[str, Any]:
    """Friction, the four-way outcome and timings of one journey (derived from its own trace; nothing is assumed)."""

    from datetime import datetime

    friction = friction_report(r.action_trace)
    try:
        duration = round(
            (
                datetime.fromisoformat(r.completed_at) - datetime.fromisoformat(r.started_at)
            ).total_seconds(),
            2,
        )
    except ValueError:
        duration = None
    clicks = sum(1 for e in r.action_trace if e.get("action") == "click")
    return {
        "friction": friction,
        "outcomes": outcomes(driver, r.verdict, r.failed_assertion, friction, physical=physical),
        "timings": {
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "duration_s": duration,
            "trace_span_s": r.action_trace[-1]["t"] if r.action_trace else None,
            "actions": len(r.action_trace),
            "clicks": clicks,
        },
    }


def redact(text: str, limit: int = _LOG_LIMIT) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return (
        text if len(text) <= limit else text[:limit] + f"\n...[truncated {len(text) - limit} chars]"
    )


def new_run_dir(root: Path, mode: str) -> Path:
    path = Path(root) / f"{time.strftime('%Y%m%d_%H%M%S')}_{SUITE_ID}_{mode}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runner(journey: JourneyDef, config: RunConfig) -> JourneyEvidence:
    """The simulated runner for one journey (imports deferred: app modules need the workspace redirect)."""

    from tools.operator_journey.golden.fixtures import make_fake_a1111, seed_declared_sdxl
    from tools.operator_journey.golden.session import run_journey_body

    if journey.key in ADVANCED_ORDER:
        from tools.operator_journey.golden.advanced import run_advanced

        return run_advanced(journey, config)
    if journey.key == "image":
        from tools.operator_journey.golden.img01 import run_img01

        return run_journey_body(
            journey.id,
            run_img01,
            config,
            mode_label="simulated",
            fake_a1111_factory=make_fake_a1111,
            workspace_hook=seed_declared_sdxl,
        )
    if journey.key == "video":
        from tools.operator_journey.fake_comfy import FakeComfy
        from tools.operator_journey.golden.fixtures import make_fake_a1111 as _fake_a
        from tools.operator_journey.golden.vid01 import WORKFLOW_ID, WORKFLOW_VERSION, run_vid01

        def make_comfy() -> FakeComfy:
            from src.video.workflow_registry import build_default_workflow_registry

            return FakeComfy(build_default_workflow_registry().get(WORKFLOW_ID, WORKFLOW_VERSION))

        return run_journey_body(
            journey.id,
            run_vid01,
            config,
            mode_label="simulated",
            fake_a1111_factory=_fake_a,
            fake_comfy_factory=make_comfy,
            workspace_hook=seed_declared_sdxl,
        )
    from tools.operator_journey.golden.lrn01 import run_lrn01
    from tools.operator_journey.journeys.learning_lora_strength import DEFAULT_LORA

    return run_journey_body(
        journey.id,
        run_lrn01,
        config,
        mode_label="simulated",
        fake_a1111_factory=lambda: make_fake_a1111(loras=(DEFAULT_LORA,)),
        workspace_hook=seed_declared_sdxl,
    )


def simulated_plan(journeys: list[JourneyDef], driver: str) -> dict[str, Any]:
    return {
        "suite": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "mode": SIMULATED,
        "repo_sha": repo_sha(),
        "desktop_driver": driver,
        "physical_gpu": False,
        "starts_model_runtime": False,
        "journeys": [
            {
                "id": j.id,
                "title": j.title,
                "steps": list(j.steps),
                "acceptance": list(j.simulated_acceptance),
            }
            for j in journeys
        ],
        "fixtures": "loopback HTTP fakes at the WebUI/Comfy API boundary only; queue, repository, compiler, runner real",
    }


def write_run_evidence(
    run_dir: Path,
    *,
    plan: dict[str, Any],
    results: list[JourneyEvidence],
    mode: str,
    driver: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """Aggregate per-journey evidence into the documented run folder; returns the overall verdict."""

    verdicts = {r.journey_id: r.verdict for r in results}
    overall = max(verdicts.values(), key=lambda v: _WORST[v], default=PASS)
    (run_dir / "plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True, default=str), "utf-8"
    )
    display: dict[str, Any] = {}
    try:
        from tools.operator_journey.desktop import display_facts

        display = display_facts() if driver == "windows" else {}
    except Exception:  # noqa: BLE001
        display = {}
    layout = next((r.summary.get("layout") for r in results if r.summary.get("layout")), None)
    evidence = {
        "suite": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "evidence_schema": EVIDENCE_SCHEMA,
        "mode": mode,
        "desktop_driver": driver,
        "layout": layout,
        "repository_sha": repo_sha(),
        "display": display,
        "provenance": provenance(display=display, layout=layout),
        "overall_verdict": overall,
        "journeys": {},
        **(extra or {}),
    }
    artifacts: list[dict[str, Any]] = []
    with (run_dir / "actions.jsonl").open("w", encoding="utf-8") as actions:
        for r in results:
            evidence["journeys"][r.journey_id] = r.as_dict() | {
                "observations": r.observations,
                **journey_assessment(r, driver, physical=mode == PHYSICAL),
            }
            for entry in r.action_trace:
                actions.write(json.dumps({"journey": r.journey_id, **entry}, default=str) + "\n")
            for obs in r.observations:
                if obs["name"] in {"image_media", "video_media"}:
                    artifacts.append(
                        {"journey": r.journey_id, "source": obs["source"], **obs["value"]}
                    )
            src_dir = Path(str(r.summary.get("evidence_dir", ""))) / "screenshots"
            if src_dir.is_dir():
                (run_dir / "screenshots").mkdir(exist_ok=True)
                for shot in src_dir.glob("*.png"):
                    shutil.copy2(shot, run_dir / "screenshots" / f"{r.journey_id}_{shot.name}")
    (run_dir / "artifacts.json").write_text(json.dumps(artifacts, indent=2, default=str), "utf-8")
    logs = run_dir / "logs"
    logs.mkdir(exist_ok=True)
    for r in results:
        body = json.dumps(
            {
                "gui": r.gui_errors,
                "threads": r.thread_errors,
                "logs": r.log_errors,
                "shutdown_noise": r.shutdown_noise,
                "isolation": r.isolation_violations,
            },
            default=str,
        )
        (logs / f"{r.journey_id}.diagnostics.txt").write_text(redact(body), "utf-8")
    (run_dir / "evidence.json").write_text(
        redact(json.dumps(evidence, indent=2, sort_keys=True, default=str), 2_000_000), "utf-8"
    )
    (run_dir / "summary.md").write_text(
        redact(summary_markdown(overall, mode, driver, results, extra), 200_000), "utf-8"
    )
    return overall


def summary_markdown(
    overall: str,
    mode: str,
    driver: str,
    results: list[JourneyEvidence],
    extra: dict[str, Any] | None,
) -> str:
    lines = [
        f"# Golden-path operator journeys ({mode})",
        "",
        f"- Overall: **{overall}**  - Desktop driver: `{driver}`  - Repository SHA: `{repo_sha()}`",
        "",
    ]
    for r in results:
        passed = sum(1 for c in r.checks if c.passed)
        lines += [f"## {r.journey_id}: {r.verdict}", f"- Checks: {passed}/{len(r.checks)} passed"]
        if r.failed_assertion:
            lines.append(f"- Finding: {r.failed_assertion}")
        fixtures = [o["name"] for o in r.observations if o["source"] == "simulated_fixture"]
        if fixtures:
            lines.append(
                f"- Simulated fixture values (not observations): {', '.join(sorted(set(fixtures)))}"
            )
        lines.append("")
    if extra:
        lines += ["## Mode details", "```json", json.dumps(extra, indent=2, default=str), "```"]
    return "\n".join(lines) + "\n"


def run_simulated(
    journeys: list[JourneyDef],
    *,
    driver: str,
    evidence_root: Path,
    hide_window: bool = False,
    discard_workspace: bool = False,
    layout: str = "maximized",
) -> tuple[str, Path]:
    run_dir = new_run_dir(evidence_root, SIMULATED)
    config = RunConfig(
        layout=layout,
        driver=driver,
        evidence_dir=run_dir / "journeys",
        hide_window=hide_window and driver == "tk",
        discard_workspace=discard_workspace,
    )
    results = [_runner(j, config) for j in journeys]
    overall = write_run_evidence(
        run_dir,
        plan=simulated_plan(journeys, driver),
        results=results,
        mode=SIMULATED,
        driver=driver,
    )
    return overall, run_dir


def run_readiness(plan_path: Path, *, evidence_root: Path, ctx: Any = None) -> tuple[str, Path]:
    """Mode B: read-only; never starts a runtime.  Verdict PASS, HOLD or NO-GO."""

    from tools.operator_journey.golden.plan import load_plan
    from tools.operator_journey.golden.readiness import evaluate_readiness

    run_dir = new_run_dir(evidence_root, READINESS)
    try:
        plan = load_plan(plan_path)
    except (OSError, ValueError) as exc:
        report = {
            "verdict": HOLD,
            "gates": [{"id": "frozen_plan", "state": HOLD, "detail": f"unreadable plan: {exc}"}],
            "started_runtime": False,
            "physical_run_authorized": False,
        }
        plan = {}
    else:
        report = evaluate_readiness(plan, ctx)
    (run_dir / "plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True, default=str), "utf-8"
    )
    (run_dir / "evidence.json").write_text(
        redact(
            json.dumps(
                {
                    "suite": SUITE_ID,
                    "mode": READINESS,
                    "repository_sha": repo_sha(),
                    "readiness": report,
                },
                indent=2,
                default=str,
            ),
            2_000_000,
        ),
        "utf-8",
    )
    md = [f"# Physical readiness: {report['verdict']}", ""] + [
        f"- {g['state']:5} {g['id']}: {g['detail']}" for g in report["gates"]
    ]
    md.append(
        f"\nPhysical run authorized by the plan: {report.get('physical_run_authorized')}. No runtime was started."
    )
    (run_dir / "summary.md").write_text(redact("\n".join(md)), "utf-8")
    return report["verdict"], run_dir


def build_plan_from_spec(spec_path: Path, out_path: Path, evidence_root: Path) -> Path:
    """Freeze ``{targets, limits}`` into a plan with live (read-only) observations; authorization stays absent."""

    from tools.operator_journey.golden.plan import build_plan

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    plan = build_plan(
        targets=spec["targets"], limits=spec["limits"], evidence_dir=str(evidence_root)
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2, sort_keys=True, default=str), "utf-8")
    return out_path


def run_suite(
    *,
    journeys_choice: str,
    mode: str,
    driver: str,
    plan_path: Path | None,
    evidence_root: Path,
    hide_window: bool = False,
    env: dict[str, str] | None = None,
    confirm: Any = None,
    ctx: Any = None,
    layout: str = "maximized",
) -> tuple[str, Path | None]:
    """Validate the combination, then run.  Raises ``ModeRefusal`` before anything starts when it is not allowed."""

    validate_combination(mode=mode, driver=driver, plan=plan_path, env=env, layout=layout)
    chosen = select(journeys_choice)
    if mode in {PHYSICAL, READINESS}:
        # An advanced journey has no physical lane: it is refused here, before any plan, readiness gate or runtime.
        unsupported = [j.id for j in chosen if not j.physical]
        if unsupported:
            raise ModeRefusal(
                f"{', '.join(unsupported)} {'has' if len(unsupported) == 1 else 'have'} no physical lane (simulated and "
                f"desktop-driver runs only); choose a journey with a physical lane for --mode {mode}"
            )
    if mode == SIMULATED:
        return run_simulated(
            chosen,
            driver=driver,
            evidence_root=evidence_root,
            hide_window=hide_window,
            layout=layout,
        )
    assert plan_path is not None
    if mode == READINESS:
        return run_readiness(plan_path, evidence_root=evidence_root, ctx=ctx)
    from tools.operator_journey.golden.physical import run_physical

    return run_physical(
        plan_path, journeys=chosen, evidence_root=evidence_root, confirm=confirm, ctx=ctx
    )


__all__ = [
    "EXIT_CODES",
    "EXIT_REFUSED",
    "ModeRefusal",
    "REPO_ROOT",
    "PHYSICAL",
    "run_suite",
    "redact",
]
