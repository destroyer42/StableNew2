"""Local operator acceptance for PR-VID-130 (one real Wan2.2 job through the production path).

Runs, in an isolated scratch workspace (own SQLite queue and output directory), the real chain
``VideoWorkflowController -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr ->
VideoExecutionResolver -> ComfyWorkflowVideoBackend -> StableNew-managed Comfy -> artifact/history``,
using the production default video backend registry and the operator's ``presets/settings.json``
Comfy configuration (read-only).

Ownership rules are unchanged: a healthy *external* Comfy or A1111 is never adopted, stopped or
restarted.  If an external Comfy already serves the configured endpoint, or the Wan resource
readiness guard blocks, the run reports that and exits without touching either process.

Cleanup lifetime: from the moment the runtime stack starts being built until the process leaves
``run_acceptance``, one ``finally`` runs ``_teardown``.  It stops **only** a Comfy process this
run's own managed ``ComfyProcessManager`` launched and still owns (``owns_process``), then stops the
job runner and closes the repository; each step is guarded so one failure cannot skip the others,
and a failing teardown is recorded and turns a success into a non-zero exit but never masks the
original exception.  This adds no production process-termination or restart authority: the harness
only releases the process it launched.

    python -m tools.acceptance.vid130_wan_acceptance <source.png> "<motion prompt>" [--dry]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPORTS = Path("reports/vid130")


def preflight() -> dict:
    from src.video.comfy_healthcheck import probe_comfy_endpoint
    from src.video.comfy_process_manager import build_default_comfy_process_config

    config = build_default_comfy_process_config()
    base_url = config.base_url if config else None
    state = probe_comfy_endpoint(base_url, timeout=1.0) if base_url else "unconfigured"
    return {"comfy_base_url": base_url, "endpoint_state": state, "autostart": bool(config)}


@dataclass
class _Stack:
    """Everything the run creates; fields fill in as the stack is built so a partial build is
    still torn down by ``_teardown``."""

    repository: Any = None
    queue: Any = None
    service: Any = None
    registry: Any = None
    controller: Any = None


def _stop_owned_comfy(registry: Any) -> bool:
    """Stop the Comfy process this run's managed manager launched and still owns; never any other.

    An external (or otherwise non-owned) runtime is left completely untouched: the manager is not
    even asked to stop when it does not own its process.
    """

    if registry is None:
        return False
    manager = getattr(registry.get("comfy"), "_managed_process_manager", None)
    if manager is None or not manager.owns_process:
        return False
    manager.stop()
    return True


def _teardown(stack: _Stack) -> tuple[bool, list[str]]:
    """Release everything the run created.  Never raises; returns (owned_comfy_stopped, errors)."""

    errors: list[str] = []

    def step(name: str, action: Any) -> Any:
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - one failed step must not skip the rest
            errors.append(f"{name}: {type(exc).__name__}: {exc}"[:300])
            return None

    owned = bool(step("stop_owned_comfy", lambda: _stop_owned_comfy(stack.registry)))
    if stack.service is not None:
        step("service.runner.stop", lambda: stack.service.runner.stop())
    if stack.repository is not None:
        step("repository.close", lambda: stack.repository.close())
    return owned, errors


def _build_stack(stack: _Stack, workspace: Path) -> None:
    from src.controller.job_service import JobService
    from src.controller.pipeline_controller import PipelineController
    from src.gui.app_state_v2 import AppStateV2
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from src.utils.config import ConfigManager
    from src.utils.logger import StructuredLogger
    from src.video.video_backend_registry import build_default_video_backend_registry

    (workspace / "logs").mkdir(parents=True, exist_ok=True)
    stack.registry = build_default_video_backend_registry()
    stack.repository = JobRepository(workspace / "jobs.sqlite3")
    stack.queue = JobQueue(repository=stack.repository)
    holder: dict = {}
    stack.service = JobService(
        stack.queue,
        run_callable=lambda job: holder["c"]._run_job(job),
        require_normalized_records=True,
    )
    runner = PipelineRunner(
        SimpleNamespace(),
        StructuredLogger(output_dir=workspace / "logs"),
        runs_base_dir=str(workspace / "output"),
        video_backend_registry=stack.registry,
    )
    stack.controller = PipelineController(
        app_state=AppStateV2(),
        config_manager=ConfigManager(presets_dir=workspace / "presets"),
        job_service=stack.service,
        pipeline_runner=runner,
    )
    holder["c"] = stack.controller
    stack.service.auto_run_enabled = False
    stack.service.runner.stop()


def _run(stack: _Stack, args: argparse.Namespace, evidence: dict, workspace: Path) -> int:
    from src.controller.video_workflow_controller import VideoWorkflowController
    from src.pipeline.result_contract_v26 import collect_canonical_artifacts
    from src.queue.job_model import JobStatus
    from tools.qualification.vid110.monitor import ResourceSampler

    _build_stack(stack, workspace)
    app = SimpleNamespace(job_service=stack.service, output_dir=str(workspace / "output"))
    form = {
        "workflow_id": "wan22_ti2v_5b_i2v_v1",
        "workflow_version": "1.0.0",
        "prompt": args.prompt,
        "negative_prompt": "",
        "experimental_opt_in": True,
    }
    job_id = VideoWorkflowController(app_controller=app).submit_video_workflow_job(
        source_image_path=args.source, form_data=form
    )
    stage = stack.queue.get_job(job_id)._normalized_record.stage_chain[0].to_dict()["extra"]
    evidence["job_id"] = job_id
    evidence["njr_video_execution"] = stage["video_execution"]
    evidence["seed"] = stage.get("seed")

    started = time.monotonic()
    with ResourceSampler(log_path=REPORTS / "telemetry.csv") as sampler:
        stack.service.runner.run_once(stack.queue.get_job(job_id))
    evidence["wall_seconds"] = round(time.monotonic() - started, 1)
    evidence["peaks"] = sampler.peaks.as_dict()
    done = stack.repository.get_job(job_id)
    evidence["status"] = done.status.value if done else "missing"
    evidence["error"] = str(getattr(done, "error_message", "") or "")[:1500]
    if done is not None and done.status is JobStatus.COMPLETED:
        _collect_completed_evidence(
            stack, evidence, job_id, stage, done, collect_canonical_artifacts
        )
    return 0 if evidence["status"] == "completed" else 1


def _collect_completed_evidence(
    stack: _Stack, evidence: dict, job_id: str, stage: dict, done: Any, collect: Any
) -> None:
    from src.queue.job_model import JobStatus

    artifacts = collect(done.result)
    evidence["artifacts"] = [
        {k: a.get(k) for k in ("stage", "primary_path", "manifest_path", "artifact_type")}
        for a in artifacts
    ]
    if artifacts and artifacts[0].get("primary_path"):
        video = Path(artifacts[0]["primary_path"])
        evidence["video"] = {"path": str(video), "bytes": video.stat().st_size}
        try:
            from tools.qualification.vid110.metrics import clip_metrics, contact_sheet

            evidence["video"]["metrics"] = clip_metrics(video).as_dict()
            evidence["video"]["sheet"] = str(contact_sheet(video, REPORTS / "sheet.png"))
        except Exception as exc:  # noqa: BLE001 - metrics are evidence, not the gate
            evidence["video"]["metrics_error"] = str(exc)[:200]
    replayed = stack.controller.replay_job_from_history(job_id)
    replay_jobs = stack.queue.list_jobs(JobStatus.QUEUED)
    evidence["replay"] = {
        "created": replayed,
        "parent_job_id": replay_jobs[0]._normalized_record.source.parent_job_id
        if replay_jobs
        else None,
        "same_video_execution": bool(
            replay_jobs
            and replay_jobs[0]
            ._normalized_record.stage_chain[0]
            .to_dict()["extra"]["video_execution"]
            == stage["video_execution"]
        ),
    }


def _write_evidence(evidence: dict) -> None:
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / "acceptance.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never mask the run's own outcome
        print(f"could not write evidence: {exc}", file=sys.stderr)


def run_acceptance(args: argparse.Namespace) -> int:
    """Build, run and always tear down the runtime stack.  Exceptions propagate unchanged."""

    workspace = REPORTS / "workspace"
    evidence: dict = {"preflight": preflight()}
    stack = _Stack()
    code = 1
    try:
        code = _run(stack, args, evidence, workspace)
    except BaseException as exc:
        evidence["aborted"] = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        owned, errors = _teardown(stack)
        evidence["managed_comfy_owned"] = owned
        evidence["teardown_errors"] = errors
        _write_evidence(evidence)
    if errors:  # only reachable when the run itself did not raise
        print("teardown errors: " + "; ".join(errors), file=sys.stderr)
        code = code or 1
    print(json.dumps(evidence, indent=2))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("prompt")
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
    return run_acceptance(args)


if __name__ == "__main__":
    sys.exit(main())
