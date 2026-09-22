"""PR-VID-150: Wan2.2 motion-prompt characterization (qualification only, no production authority).

Reuses the exact PR-VID-130/140 production chain (``VideoWorkflowController -> immutable NJR ->
JobService -> SQLite -> PipelineRunner.run_njr -> VideoExecutionResolver -> ComfyWorkflowVideoBackend
-> StableNew-managed Comfy -> artifact/history``) via the PR-VID-130 acceptance harness's proven
stack-build/teardown, and the PR-VID-110 metrics/telemetry tooling. It adds one capability those
harnesses did not need: an explicit frozen seed, so three fixed-seed cases isolate the effect of
motion-prompt structure rather than sampler noise. It selects no backend and owns no production
runtime lifecycle beyond releasing a Comfy process this run's own managed manager launched.

Each of the three cases (A/B/C) is one process invocation with exactly one job and no retry:

    python -m tools.qualification.vid150.run <source.png> --case A --seed 1733123036

A failed or blocked run (resource-readiness guard, dependency gate, GPU loss) is written to
``reports/vid150/case_<x>/evidence.json`` and the process exits non-zero; it is never retried
automatically. Run the next case only after confirming the system returned to a normal state.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools.acceptance.vid130_wan_acceptance import (
    _build_stack,
    _collect_completed_evidence,
    _Stack,
    _teardown,
    preflight,
)

REPORTS_ROOT = Path("reports/vid150")

# Only the positive motion prompt changes across cases; source, seed, negative prompt, geometry,
# model/files, steps, CFG, sampler, scheduler, frame count, fps and experimental opt-in are held
# constant by ``form_data_for`` and the unchanged Wan production defaults.
CASES: dict[str, str] = {
    "A": "The person raises their right hand and waves.",
    "B": (
        "Camera locked. The person stays in place, raises their right arm from their side to "
        "shoulder height, waves twice, then lowers the arm. The head follows the hand slightly. "
        "Natural shoulder, arm, clothing and hair movement. No zoom, pan, orbit or scene change."
    ),
    "C": (
        "Camera locked. The person takes two deliberate steps forward with natural weight "
        "transfer and opposing arm swing, then stops. Keep the same person, face, clothing and "
        "scene. No zoom, pan, orbit or scene change."
    ),
}


def form_data_for(case: str, seed: int) -> dict[str, Any]:
    """The exact submitted form for one case: only the prompt varies across A/B/C."""

    if case not in CASES:
        raise ValueError(f"unknown case {case!r}; expected one of {sorted(CASES)}")
    return {
        "workflow_id": "wan22_ti2v_5b_i2v_v1",
        "workflow_version": "1.0.0",
        "prompt": CASES[case],
        "negative_prompt": "",
        "seed": str(seed),
        "experimental_opt_in": True,
    }


def case_reports_dir(case: str) -> Path:
    return REPORTS_ROOT / f"case_{case.lower()}"


def _run_case(
    stack: _Stack, args: argparse.Namespace, evidence: dict[str, Any], workspace: Path, reports: Path
) -> int:
    from src.controller.video_workflow_controller import VideoWorkflowController
    from src.pipeline.result_contract_v26 import collect_canonical_artifacts
    from src.queue.job_model import JobStatus
    from tools.qualification.vid110.monitor import ResourceSampler

    _build_stack(stack, workspace)
    app = SimpleNamespace(job_service=stack.service, output_dir=str(workspace / "output"))
    form = form_data_for(args.case, args.seed)
    evidence["case"] = args.case
    evidence["prompt"] = form["prompt"]
    evidence["requested_seed"] = args.seed

    job_id = VideoWorkflowController(app_controller=app).submit_video_workflow_job(
        source_image_path=args.source, form_data=form
    )
    stage = stack.queue.get_job(job_id)._normalized_record.stage_chain[0].to_dict()["extra"]
    evidence["job_id"] = job_id
    evidence["njr_video_execution"] = stage["video_execution"]
    evidence["seed"] = stage.get("seed")
    evidence["source_preparation"] = stage.get("source_preparation")

    started = time.monotonic()
    with ResourceSampler(log_path=reports / "telemetry.csv") as sampler:
        stack.service.runner.run_once(stack.queue.get_job(job_id))
    evidence["wall_seconds"] = round(time.monotonic() - started, 1)
    evidence["peaks"] = sampler.peaks.as_dict()
    done = stack.repository.get_job(job_id)
    evidence["status"] = done.status.value if done else "missing"
    evidence["error"] = str(getattr(done, "error_message", "") or "")[:1500]
    if done is not None and done.status is JobStatus.COMPLETED:
        _collect_completed_evidence(stack, evidence, job_id, stage, done, collect_canonical_artifacts)
        _record_metrics(evidence, reports, args)
    return 0 if evidence["status"] == "completed" else 1


def _record_metrics(evidence: dict[str, Any], reports: Path, args: argparse.Namespace) -> None:
    video_info = evidence.get("video")
    video = video_info.get("path") if isinstance(video_info, dict) else None
    if not video:
        return
    try:
        from tools.qualification.vid110.metrics import clip_metrics, contact_sheet

        preparation = evidence.get("source_preparation") or {}
        source_for_identity = Path(preparation.get("prepared_image_path") or args.source)
        evidence["video"]["metrics"] = clip_metrics(
            Path(video), source_image=source_for_identity
        ).as_dict()
        evidence["video"]["sheet"] = str(
            contact_sheet(Path(video), reports / f"case_{args.case.lower()}_sheet.png")
        )
    except Exception as exc:  # noqa: BLE001 - metrics are evidence, not the gate
        evidence["video"]["metrics_error"] = str(exc)[:200]


def _write_evidence(evidence: dict[str, Any], reports: Path) -> None:
    try:
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never mask the run's own outcome
        print(f"could not write evidence: {exc}", file=sys.stderr)


def run_case(args: argparse.Namespace) -> int:
    """Build, run and always tear down the runtime stack for exactly one case. No retry."""

    reports = case_reports_dir(args.case)
    workspace = reports / "workspace"
    evidence: dict[str, Any] = {"preflight": preflight()}
    stack = _Stack()
    code = 1
    errors: list[str] = []
    try:
        code = _run_case(stack, args, evidence, workspace, reports)
    except BaseException as exc:
        evidence["aborted"] = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        owned, errors = _teardown(stack)
        evidence["managed_comfy_owned"] = owned
        evidence["teardown_errors"] = errors
        _write_evidence(evidence, reports)
    if errors:  # only reachable when the run itself did not raise
        print("teardown errors: " + "; ".join(errors), file=sys.stderr)
        code = code or 1
    print(json.dumps(evidence, indent=2))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--case", required=True, choices=sorted(CASES))
    parser.add_argument("--seed", type=int, default=1733123036)
    parser.add_argument("--dry", action="store_true", help="preflight only; queue nothing")
    args = parser.parse_args(argv)

    state = preflight()
    print(json.dumps(state))
    if state["endpoint_state"] == "healthy":
        print(
            "STOP: an external ComfyUI already serves the configured endpoint. StableNew never "
            "adopts or restarts it; close it yourself (or change the configured endpoint)."
        )
        return 3
    if args.dry:
        return 0
    return run_case(args)


if __name__ == "__main__":
    sys.exit(main())
