"""Local operator acceptance for PR-VID-130 (one real Wan2.2 job through the production path).

Runs, in an isolated scratch workspace (own SQLite queue and output directory), the real chain
``VideoWorkflowController -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr ->
VideoExecutionResolver -> ComfyWorkflowVideoBackend -> StableNew-managed Comfy -> artifact/history``,
using the production default video backend registry and the operator's ``presets/settings.json``
Comfy configuration (read-only).

Ownership rules are unchanged: a healthy *external* Comfy or A1111 is never adopted, stopped or
restarted.  If an external Comfy already serves the configured endpoint, or the Wan resource
readiness guard blocks, the run reports that and exits without touching either process.  Only the
Comfy process this run itself launched is stopped afterwards.

    python -m tools.acceptance.vid130_wan_acceptance <source.png> "<motion prompt>" [--dry]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPORTS = Path("reports/vid130")


def preflight() -> dict:
    from src.video.comfy_healthcheck import probe_comfy_endpoint
    from src.video.comfy_process_manager import build_default_comfy_process_config

    config = build_default_comfy_process_config()
    base_url = config.base_url if config else None
    state = probe_comfy_endpoint(base_url, timeout=1.0) if base_url else "unconfigured"
    return {"comfy_base_url": base_url, "endpoint_state": state, "autostart": bool(config)}


def _stop_owned_comfy(registry) -> bool:
    """Stop only a Comfy process this run itself launched (the manager enforces ownership)."""

    manager = getattr(registry.get("comfy"), "_managed_process_manager", None)
    owned = bool(manager and manager.owns_process)
    if manager is not None:
        manager.stop()
    return owned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("prompt")
    parser.add_argument("--dry", action="store_true", help="preflight only; queue nothing")
    args = parser.parse_args(argv)

    from src.controller.job_service import JobService
    from src.controller.pipeline_controller import PipelineController
    from src.controller.video_workflow_controller import VideoWorkflowController
    from src.gui.app_state_v2 import AppStateV2
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.pipeline.result_contract_v26 import collect_canonical_artifacts
    from src.queue.job_model import JobStatus
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from src.utils.config import ConfigManager
    from src.utils.logger import StructuredLogger
    from src.video.video_backend_registry import build_default_video_backend_registry
    from tools.qualification.vid110.monitor import ResourceSampler

    evidence: dict = {"preflight": preflight()}
    print(json.dumps(evidence["preflight"]))
    if evidence["preflight"]["endpoint_state"] == "healthy":
        print(
            "STOP: an external ComfyUI already serves the configured endpoint. StableNew never "
            "adopts or restarts it; close it yourself (or change the configured endpoint)."
        )
        return 3
    if args.dry:
        return 0

    workspace = REPORTS / "workspace"
    (workspace / "logs").mkdir(parents=True, exist_ok=True)
    repository = JobRepository(workspace / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    holder: dict = {}
    service = JobService(
        queue, run_callable=lambda job: holder["c"]._run_job(job), require_normalized_records=True
    )
    registry = build_default_video_backend_registry()
    runner = PipelineRunner(
        SimpleNamespace(),
        StructuredLogger(output_dir=workspace / "logs"),
        runs_base_dir=str(workspace / "output"),
        video_backend_registry=registry,
    )
    controller = PipelineController(
        app_state=AppStateV2(),
        config_manager=ConfigManager(presets_dir=workspace / "presets"),
        job_service=service,
        pipeline_runner=runner,
    )
    holder["c"] = controller
    service.auto_run_enabled = False
    service.runner.stop()

    app = SimpleNamespace(job_service=service, output_dir=str(workspace / "output"))
    video_controller = VideoWorkflowController(app_controller=app)
    form = {
        "workflow_id": "wan22_ti2v_5b_i2v_v1",
        "workflow_version": "1.0.0",
        "prompt": args.prompt,
        "negative_prompt": "",
        "experimental_opt_in": True,
    }
    job_id = video_controller.submit_video_workflow_job(
        source_image_path=args.source, form_data=form
    )
    record = queue.get_job(job_id)._normalized_record
    stage = record.stage_chain[0].to_dict()["extra"]
    evidence["job_id"] = job_id
    evidence["njr_video_execution"] = stage["video_execution"]
    evidence["seed"] = stage.get("seed")

    started = time.monotonic()
    try:
        with ResourceSampler(log_path=REPORTS / "telemetry.csv") as sampler:
            service.runner.run_once(queue.get_job(job_id))
    except BaseException:
        _stop_owned_comfy(registry)
        raise
    evidence["wall_seconds"] = round(time.monotonic() - started, 1)
    evidence["peaks"] = sampler.peaks.as_dict()
    done = repository.get_job(job_id)
    evidence["status"] = done.status.value if done else "missing"
    evidence["error"] = str(getattr(done, "error_message", "") or "")[:1500]
    if done is not None and done.status is JobStatus.COMPLETED:
        artifacts = collect_canonical_artifacts(done.result)
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
        replayed = controller.replay_job_from_history(job_id)
        replay_jobs = queue.list_jobs(JobStatus.QUEUED)
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
    evidence["managed_comfy_owned"] = _stop_owned_comfy(registry)
    service.runner.stop()
    repository.close()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "acceptance.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
