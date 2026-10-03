"""PR-VID-190 real acceptance: three Wan2.2 TI2V-5B jobs queued back to back, no manual kill.

Runs, in an isolated scratch workspace (own SQLite queue and output directory), the production
chain ``VideoWorkflowController -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr
-> VideoExecutionResolver -> ComfyWorkflowVideoBackend -> StableNew-managed Comfy ->
artifact/history`` for ``wan22_ti2v_5b_i2v_v1@1.1.0``, using the operator's
``presets/settings.json`` Comfy configuration (read-only).

All three jobs are queued first and then run in queue order.  Nothing in this harness stops,
kills or restarts any process between jobs: the only release is the backend's own declared
``release_owned_runtime_after_job`` policy, which stops a Comfy process only when StableNew launched
and still owns it.  Between jobs the harness only *observes* (host RAM, driver VRAM, the
configured endpoint, the manager's ownership state).

Bounded retry: if the long (81-frame) job fails for a clean resource reason (readiness or CUDA
out-of-memory), one extra job at 65 frames is queued after the three.  Any sign of GPU device
loss stops the run immediately; no further job is dispatched.

A healthy *external* Comfy or A1111 on the configured endpoints is never adopted, stopped or
restarted; preflight refuses to run instead.  ``finally`` teardown stops only a Comfy this run's
own manager still owns (expected: none, since the policy already released it), then stops the
job runner and closes the scratch repository.

    python -m tools.acceptance.vid190_queue_recycling_acceptance <source.png> [--dry]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPORTS = Path("reports/vid190")
WORKFLOW_ID = "wan22_ti2v_5b_i2v_v1"
WORKFLOW_VERSION = "1.1.0"
RETRY_FRAMES = 65
_NEGATIVE = (
    "static, frozen pose, blurry, low quality, extra limbs, extra fingers, deformed hands, "
    "distorted body, duplicate person, watermark, subtitles"
)
JOBS = (
    (
        "A",
        49,
        19001,
        "the woman smiles, turns her head to the left and back, then raises her right hand and "
        "waves at the camera",
    ),
    (
        "B",
        81,
        19002,
        "the woman slowly raises both arms above her head, lowers them to her sides, then turns "
        "to her left and walks two steps forward",
    ),
    (
        "C",
        49,
        19003,
        "the woman lifts her right knee high and sets it down, then lifts her left knee high, "
        "a slow marching motion in place",
    ),
)
_ANIMATE2_SUBJECT = "A young woman in a navy athletic top, navy leggings and white sneakers"
# Machine-local driving clip for the driving-video job; when unset that job is refused at admission
# ("needs a driving video").
_DRIVING_CLIP = os.environ.get("STABLENEW_VID191_DRIVING_CLIP", "")
# The qualified PR-VID-184 motion-only prompt for the locomotion driving clip (flat-graph node 612).
_MOTION_PROMPT_QUALIFIED = (
    "A person performs a high-knee running drill that transitions into a full sprinting stride, "
    "moving laterally from left to right across a static frame with continuous forward locomotion "
    "and alternating arm-leg swing."
)
# Per suite: (label, workflow_id, version, frames, seed, prompt, driving video or None[, controls]).
# The optional trailing element is the job's ``operator_controls`` form value (PR-VID-192).
SUITES: dict[str, tuple[tuple[Any, ...], ...]] = {
    "ti2v": tuple(
        (label, WORKFLOW_ID, WORKFLOW_VERSION, frames, seed, prompt, None)
        for label, frames, seed, prompt in JOBS
    ),
    "animate2": (
        (
            "A",
            "wan_animate2_prompt_i2v_v1",
            "1.0.0",
            41,
            19101,
            f"{_ANIMATE2_SUBJECT} smiles, raises her right hand and waves at the camera, then "
            "lowers it to her side.",
            None,
        ),
        (
            "B",
            "wan_animate2_prompt_i2v_v1",
            "1.0.0",
            81,
            19102,
            f"{_ANIMATE2_SUBJECT} slowly raises both arms above her head, lowers them, then "
            "turns to her left and walks two steps forward.",
            None,
        ),
        (
            "C",
            "wan_animate2_drive_i2v_v1",
            "1.0.0",
            41,
            19103,
            f"{_ANIMATE2_SUBJECT} exercising in a bright studio.",
            _DRIVING_CLIP,
        ),
    ),
}
# One driving-video job: re-verifies artifact selection after the input-preview fix.
SUITES["animate2_drive"] = (SUITES["animate2"][2],)
# PR-VID-192 controlled experiment: one frozen reference, driving clip, seed, length and appearance
# prompt; ONE variable changes per arm relative to its parent.
#   A0 baseline   PR-VID-191 graph (positive_pose unconnected: the node reuses the appearance prompt)
#   A1 motion     + a distinct, accurate Motion Prompt (default pose/reference strengths)
#   A2 pose       A1 + pose strength 1.5
#   A3 reference  A1 + reference-image strength 1.3 (targets the duplicate-subject/identity issue)
_EXPERIMENT_PROMPT = f"{_ANIMATE2_SUBJECT} exercising in a bright studio."
SUITES["animate2_controls"] = tuple(
    (label, "wan_animate2_drive_i2v_v1", version, 41, 19103, _EXPERIMENT_PROMPT, _DRIVING_CLIP, controls)
    for label, version, controls in (
        ("A0", "1.0.0", None),
        ("A1", "1.1.0", {"pose_prompt": _MOTION_PROMPT_QUALIFIED}),
        ("A2", "1.1.0", {"pose_prompt": _MOTION_PROMPT_QUALIFIED, "pose_strength": "1.5"}),
        (
            "A3",
            "1.1.0",
            {"pose_prompt": _MOTION_PROMPT_QUALIFIED, "reference_image_strength": "1.3"},
        ),
    )
)
_DEVICE_LOSS_MARKERS = (
    "device lost",
    "device_lost",
    "cudaerrordevicesunavailable",
    "unspecified launch failure",
    "illegal memory access",
    "gpu is lost",
    "hostbuf",
)
_CLEAN_RESOURCE_MARKERS = ("not resource-ready", "out of memory", "outofmemory", "cuda oom")


def _endpoint_state(base_url: str | None) -> str:
    from src.video.comfy_healthcheck import probe_comfy_endpoint

    return probe_comfy_endpoint(base_url, timeout=1.0) if base_url else "unconfigured"


def _driver_gpu() -> dict[str, Any]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.free,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=15,
        )
        used, free, total, util = (float(part) for part in out.strip().splitlines()[0].split(","))
        return {"vram_used_mib": used, "vram_free_mib": free, "vram_total_mib": total, "util": util}
    except Exception as exc:  # noqa: BLE001 - an unreadable driver is itself evidence
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _host_ram_gb() -> float:
    import psutil

    return round(psutil.virtual_memory().available / 1e9, 2)


def preflight() -> dict:
    from src.utils.config import ConfigManager
    from src.video.comfy_process_manager import build_default_comfy_process_config

    config = build_default_comfy_process_config()
    settings = ConfigManager().load_settings()
    webui_url = str(settings.get("webui_base_url") or "")
    return {
        "comfy_base_url": config.base_url if config else None,
        "comfy_endpoint_state": _endpoint_state(config.base_url if config else None),
        "comfy_command_has_disable_pinned_memory": bool(
            config and "--disable-pinned-memory" in config.command
        ),
        "a1111_base_url": webui_url or None,
        "a1111_endpoint_state": _endpoint_state(webui_url) if webui_url else "unconfigured",
        "autostart": bool(config),
        "host_ram_available_gb": _host_ram_gb(),
        "gpu": _driver_gpu(),
    }


@dataclass
class _Stack:
    repository: Any = None
    queue: Any = None
    service: Any = None
    registry: Any = None
    controller: Any = None


def _manager(stack: _Stack) -> Any:
    backend = stack.registry.get("comfy") if stack.registry is not None else None
    return getattr(backend, "_managed_process_manager", None)


def _manager_state(stack: _Stack) -> dict[str, Any]:
    manager = _manager(stack)
    if manager is None:
        return {"manager": None}
    return {
        "manager_id": id(manager),
        "running": bool(manager.is_running()),
        "owns_process": bool(manager.owns_process),
        "pid": manager.pid,
    }


def _stop_owned_comfy(stack: _Stack) -> bool:
    manager = _manager(stack)
    if manager is None or not manager.owns_process:
        return False
    manager.stop()
    return True


def _teardown(stack: _Stack) -> tuple[bool, list[str]]:
    errors: list[str] = []

    def step(name: str, action: Any) -> Any:
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - one failed step must not skip the rest
            errors.append(f"{name}: {type(exc).__name__}: {exc}"[:300])
            return None

    owned = bool(step("stop_owned_comfy", lambda: _stop_owned_comfy(stack)))
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


def _find_key(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def _submit(stack: _Stack, source: Path, workspace: Path, job: tuple) -> str:
    from src.controller.video_workflow_controller import VideoWorkflowController

    _label, workflow_id, version, frames, seed, prompt, driving, *rest = job
    controls = rest[0] if rest else None
    app = SimpleNamespace(job_service=stack.service, output_dir=str(workspace / "output"))
    form = {
        "workflow_id": workflow_id,
        "workflow_version": version,
        "prompt": prompt,
        # TI2V keeps the harness negative; Animate-2 uses its qualified stock negative.
        "negative_prompt": _NEGATIVE if workflow_id == WORKFLOW_ID else "",
        "seed": str(seed),
        "frame_count": frames,
        "experimental_opt_in": True,
    }
    if driving:
        form["pose_video_path"] = driving
    if controls:
        form["operator_controls"] = dict(controls)
    return VideoWorkflowController(app_controller=app).submit_video_workflow_job(
        source_image_path=source, form_data=form
    )


def _video_evidence(path: Path, label: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    try:
        from tools.qualification.vid110.metrics import clip_metrics, contact_sheet

        evidence["metrics"] = clip_metrics(path).as_dict()
        evidence["sheet"] = str(contact_sheet(path, REPORTS / f"sheet_{label}.png"))
    except Exception as exc:  # noqa: BLE001 - metrics are evidence, not the gate
        evidence["metrics_error"] = str(exc)[:300]
    return evidence


def _run_one(stack: _Stack, job_id: str, label: str, frames: int, comfy_url: str | None) -> dict:
    from src.pipeline.result_contract_v26 import collect_canonical_artifacts
    from src.queue.job_model import JobStatus
    from tools.qualification.vid110.monitor import ResourceSampler

    record: dict[str, Any] = {
        "label": label,
        "job_id": job_id,
        "frame_count": frames,
        "before": {
            "host_ram_available_gb": _host_ram_gb(),
            "gpu": _driver_gpu(),
            "comfy_endpoint_state": _endpoint_state(comfy_url),
            **_manager_state(stack),
        },
    }
    started = time.monotonic()
    with ResourceSampler(log_path=REPORTS / f"telemetry_{label}.csv") as sampler:
        stack.service.runner.run_once(stack.queue.get_job(job_id))
    record["wall_seconds"] = round(time.monotonic() - started, 1)
    record["peaks"] = sampler.peaks.as_dict()
    done = stack.repository.get_job(job_id)
    record["status"] = done.status.value if done else "missing"
    record["error"] = str(getattr(done, "error_message", "") or "")[:1500]
    result = getattr(done, "result", None) or {}
    record["runtime_release"] = _find_key(result, "runtime_release")
    record["resource_readiness"] = _find_key(result, "resource_readiness")
    # Give the OS a moment to reclaim the released process's memory before observing.
    time.sleep(5)
    record["after"] = {
        "host_ram_available_gb": _host_ram_gb(),
        "gpu": _driver_gpu(),
        "comfy_endpoint_state": _endpoint_state(comfy_url),
        **_manager_state(stack),
    }
    if done is not None and done.status is JobStatus.COMPLETED:
        artifacts = collect_canonical_artifacts(done.result)
        record["artifacts"] = [
            {k: a.get(k) for k in ("stage", "primary_path", "manifest_path", "artifact_type")}
            for a in artifacts
        ]
        if artifacts and artifacts[0].get("primary_path"):
            record["video"] = _video_evidence(Path(artifacts[0]["primary_path"]), label)
        manifest_path = artifacts[0].get("manifest_path") if artifacts else None
        if manifest_path and Path(manifest_path).is_file():
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            record["manifest_provenance"] = {
                key: manifest.get(key)
                for key in ("workflow_id", "workflow_version", "frame_count", "fps",
                            "approximate_seconds", "runtime_policy", "pose_video",
                            "actual_runtime")
            }
    return record


def _device_loss(record: dict) -> bool:
    text = (record.get("error") or "").lower()
    gpu_after = (record.get("after") or {}).get("gpu") or {}
    return any(marker in text for marker in _DEVICE_LOSS_MARKERS) or "error" in gpu_after


def _clean_resource_failure(record: dict) -> bool:
    text = (record.get("error") or "").lower()
    return record.get("status") == "failed" and any(m in text for m in _CLEAN_RESOURCE_MARKERS)


def _replay_evidence(stack: _Stack, job_id: str) -> dict[str, Any]:
    from src.queue.job_model import JobStatus

    parent_stage = (
        stack.queue.get_job(job_id)._normalized_record.stage_chain[0].to_dict()["extra"]
        if stack.queue.get_job(job_id) is not None
        else {}
    )
    created = stack.controller.replay_job_from_history(job_id)
    replay_job = next(
        (
            candidate
            for candidate in stack.queue.list_jobs(JobStatus.QUEUED)
            if candidate._normalized_record is not None
            and candidate._normalized_record.source.parent_job_id == job_id
        ),
        None,
    )
    if replay_job is None:
        return {"created": created, "found": False}
    stage = replay_job._normalized_record.stage_chain[0].to_dict()["extra"]
    evidence = {
        "created": created,
        "replay_job_id": replay_job._normalized_record.job_id,
        "parent_job_id": replay_job._normalized_record.source.parent_job_id,
        "same_frame_count": stage.get("frame_count") == parent_stage.get("frame_count"),
        "same_seed": stage.get("seed") == parent_stage.get("seed"),
        "same_video_execution": stage.get("video_execution") == parent_stage.get("video_execution"),
    }
    # The replay is lineage evidence only: it is cancelled, never dispatched to the GPU here.
    try:
        stack.queue.mark_cancelled(evidence["replay_job_id"], "PR-VID-190 lineage evidence only")
        evidence["cancelled_undispatched"] = True
    except Exception as exc:  # noqa: BLE001 - evidence only
        evidence["cancel_error"] = str(exc)[:200]
    return evidence


def _run(stack: _Stack, args: argparse.Namespace, evidence: dict, workspace: Path) -> int:
    _build_stack(stack, workspace)
    source = Path(args.source)
    comfy_url = evidence["preflight"]["comfy_base_url"]
    queued = []
    # PR-COMFY-RUNTIME-100: a runtime comparison dispatches exactly one named job on an explicit
    # workflow version (the same frozen case on another runtime), never the whole suite.
    suite = tuple(job for job in SUITES[args.suite] if not args.only or job[0] in args.only)
    if args.workflow_version:
        suite = tuple((job[0], job[1], args.workflow_version, *job[3:]) for job in suite)
    if not suite:
        raise SystemExit(f"--only {args.only} matches no job in suite {args.suite!r}")
    evidence["suite"] = args.suite
    for job in suite:
        label, frames = job[0], job[3]
        job_id = _submit(stack, source, workspace, job)
        stage = stack.queue.get_job(job_id)._normalized_record.stage_chain[0].to_dict()["extra"]
        queued.append((label, frames, job_id))
        evidence.setdefault("admission", []).append(
            {
                "label": label,
                "job_id": job_id,
                "workflow_id": stage.get("workflow_id"),
                "workflow_version": stage.get("workflow_version"),
                "frame_count": stage.get("frame_count"),
                "fps": stage.get("fps"),
                "seed": stage.get("seed"),
                "pose_video": {
                    "path": stage.get("pose_video_path"),
                    "sha256": stage.get("pose_video_sha256"),
                }
                if stage.get("pose_video_path")
                else None,
                "operator_controls": stage.get("operator_controls"),
                "experimental_opt_in": stage["video_execution"]["experimental_opt_in"],
            }
        )
    evidence["queued_before_first_dispatch"] = len(queued)

    records: list[dict] = []
    retry_needed = False
    for label, frames, job_id in queued:
        record = _run_one(stack, job_id, label, frames, comfy_url)
        records.append(record)
        evidence["jobs"] = records
        _write_evidence(evidence)
        if _device_loss(record):
            evidence["hard_stop"] = f"GPU device-loss signal after job {label}; no further dispatch"
            return 2
        if label == "B" and _clean_resource_failure(record):
            retry_needed = True
    if retry_needed:
        # The bounded retry is derived from the selected B job by label: a filtered suite
        # (``--only B``) holds one tuple, so a positional index would be wrong or out of range.
        base = next(job for job in suite if job[0] == "B")
        retry_job = (f"{base[0]}_retry", base[1], base[2], RETRY_FRAMES, *base[4:])
        retry_id = _submit(stack, source, workspace, retry_job)
        record = _run_one(stack, retry_id, "B_retry", RETRY_FRAMES, comfy_url)
        records.append(record)
        evidence["jobs"] = records
        if _device_loss(record):
            evidence["hard_stop"] = "GPU device-loss signal after the bounded retry"
            return 2

    first_completed = next((r for r in records if r["status"] == "completed"), None)
    if first_completed is not None:
        evidence["replay"] = _replay_evidence(stack, first_completed["job_id"])
    evidence["final_gpu"] = _driver_gpu()
    evidence["final_endpoint_state"] = _endpoint_state(comfy_url)
    # The verdict covers exactly the primary jobs this invocation queued (the whole suite, or the
    # ``--only`` selection such as A0-A3) -- never a hard-coded label set, which would be empty for a
    # filtered controls run and pass vacuously.  The bounded ``B_retry`` is not a primary job and
    # never substitutes for a failed B.
    primary_labels = [label for label, _frames, _job_id in queued]
    evidence["primary_jobs"] = primary_labels
    primary = [r for r in records if r["label"] in primary_labels]
    complete = len(primary) == len(primary_labels) and all(
        r["status"] == "completed" for r in primary
    )
    return 0 if complete else 1


def _write_evidence(evidence: dict) -> None:
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / "acceptance.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never mask the run's own outcome
        print(f"could not write evidence: {exc}", file=sys.stderr)


def run_acceptance(args: argparse.Namespace, state: dict) -> int:
    workspace = REPORTS / "workspace"
    evidence: dict = {
        "source": str(args.source),
        "preflight": state,
    }
    stack = _Stack()
    code = 1
    try:
        code = _run(stack, args, evidence, workspace)
    except BaseException as exc:
        evidence["aborted"] = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        owned, errors = _teardown(stack)
        evidence["teardown_stopped_owned_comfy"] = owned
        evidence["teardown_errors"] = errors
        _write_evidence(evidence)
    if errors:
        print("teardown errors: " + "; ".join(errors), file=sys.stderr)
        code = code or 1
    print(json.dumps(evidence, indent=2))
    return code


def main(argv: list[str] | None = None) -> int:
    global REPORTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--dry", action="store_true", help="preflight only; queue nothing")
    parser.add_argument("--suite", choices=sorted(SUITES), default="ti2v")
    parser.add_argument(
        "--reports-dir", default=str(REPORTS), help="evidence directory (default reports/vid190)"
    )
    parser.add_argument(
        "--only",
        type=lambda text: [part.strip() for part in text.split(",") if part.strip()],
        default=[],
        help="comma-separated job labels to run (default: the whole suite)",
    )
    parser.add_argument(
        "--workflow-version",
        default="",
        help="run every selected job on this workflow version (default: the suite's own)",
    )
    args = parser.parse_args(argv)
    REPORTS = Path(args.reports_dir)

    state = preflight()
    print(json.dumps(state, indent=2))
    if state["comfy_endpoint_state"] != "free":
        print(
            "STOP: the configured ComfyUI endpoint is not free (an external or leftover ComfyUI "
            "is serving it). StableNew never adopts or stops it; close it yourself first."
        )
        return 3
    if state["a1111_endpoint_state"] not in {"free", "unconfigured"}:
        print(
            "STOP: A1111 is serving its configured endpoint. StableNew will not stop a runtime it "
            "did not launch; close it yourself first."
        )
        return 3
    if args.dry:
        return 0
    return run_acceptance(args, state)


if __name__ == "__main__":
    sys.exit(main())
