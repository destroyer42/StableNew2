"""PR-VID-SEQ-330-CORE real acceptance: multi-segment sequences on the managed Comfy runtime (TI2V-5B 1.3.0).

Follows ``docs/Subsystems/Video/PR-VID-SEQ-330_Acceptance.md``. It reuses the PR-VID-190 harness unchanged for the
isolated scratch workspace and queue and for observation (production chain ``VideoWorkflowController -> NJR ->
JobService -> SQLite -> PipelineRunner.run_njr -> ComfyWorkflowVideoBackend``, the operator's Comfy settings read-only).
Nothing here stops, kills or restarts any process: the only release is the sequence's own single release of a Comfy
StableNew launched and still owns. A live external Comfy or A1111 refuses the run at preflight.

    python -m tools.acceptance.seq330_sequence_acceptance <source.png> --run A|B|C [--dry] [--reports-dir DIR]

* A: two 17-frame segments, carried anchor, default overlap, assembly on.
* B: three segments; the job is cancelled through the queue once segment 1 is in the ledger, then
  ``resume_sequence`` runs the remaining segment as a new job.
* C: two segments, segment 1 starts from an authored anchor (overlap 0).

Every run is then judged by ``tools/acceptance/seq330_sequence_verification.py`` and any GPU device-loss signal stops
the run at once.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools.acceptance import vid190_queue_recycling_acceptance as harness

WORKFLOW_ID = "wan22_ti2v_5b_i2v_v1"
WORKFLOW_VERSION = "1.3.0"
FRAMES = 17
PROMPT = "the woman smiles, turns her head slowly to the left and back, then raises her right hand and waves"
SEEDS = (20001, 20002, 20003)
REPORTS = Path("reports/seq330")


def _form() -> dict[str, Any]:
    return {
        "workflow_id": WORKFLOW_ID,
        "workflow_version": WORKFLOW_VERSION,
        "prompt": PROMPT,
        "negative_prompt": harness._NEGATIVE,
        "seed": str(SEEDS[0]),
        "frame_count": FRAMES,
    }


def _intent(run: str, anchor: Path | None) -> dict[str, Any]:
    count = 3 if run == "B" else 2
    segments: list[dict[str, Any]] = [
        {"frame_count": FRAMES, "seed": SEEDS[index]} for index in range(count)
    ]
    if run == "C":
        assert anchor is not None
        segments[1]["anchor"] = {"policy": "provided", "path": str(anchor)}
        segments[1]["overlap_frames"] = 0
    return {"segments": segments, "assembly": {"clip_name": f"seq330_{run}", "quality": "balanced"}}


def _controller(stack: Any, workspace: Path) -> Any:
    from src.controller.video_workflow_controller import VideoWorkflowController

    app = SimpleNamespace(job_service=stack.service, output_dir=str(workspace / "output"))
    return VideoWorkflowController(app_controller=app)


def _ledgers(workspace: Path) -> list[Path]:
    return sorted((workspace / "output").rglob("sequence_state.json"))


class _PidWatcher(threading.Thread):
    """Records every distinct managed-Comfy pid seen while a job runs (one pid means one warm process)."""

    def __init__(self, stack: Any) -> None:
        super().__init__(daemon=True)
        self._stack = stack
        self.pids: set[int] = set()
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            pid = harness._manager_state(self._stack).get("pid")
            if pid:
                self.pids.add(int(pid))
            self._stop_event.wait(1.0)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)


def _run_job(
    stack: Any, job_id: str, label: str, comfy_url: str | None, *, cancel_at: int | None = None
) -> dict:
    """Run one queued job to its end (optionally cancelling it through the queue once ``cancel_at`` segments exist)."""

    from src.pipeline.result_contract_v26 import (
        collect_canonical_artifacts,  # noqa: F401 - parity with the harness
    )
    from tools.qualification.vid110.monitor import ResourceSampler

    workspace = harness.REPORTS / "workspace"
    watcher = _PidWatcher(stack)
    record: dict[str, Any] = {
        "label": label,
        "job_id": job_id,
        "before": {
            "host_ram_available_gb": harness._host_ram_gb(),
            "gpu": harness._driver_gpu(),
            "comfy_endpoint_state": harness._endpoint_state(comfy_url),
            **harness._manager_state(stack),
        },
    }
    cancel_marker: dict[str, Any] = {}

    def cancel_when_ready() -> None:
        while not cancel_marker.get("stop"):
            for path in _ledgers(workspace):
                try:
                    done = json.loads(path.read_text(encoding="utf-8")).get("completed_prefix", 0)
                except (OSError, ValueError):
                    continue
                if done >= (cancel_at or 0) and str(job_id) in path.read_text(encoding="utf-8"):
                    stack.service.cancel_current()  # the operator's Cancel: signals the running job's token
                    cancel_marker["fired_at_prefix"] = done
                    return
            time.sleep(0.5)

    canceller = threading.Thread(target=cancel_when_ready, daemon=True) if cancel_at else None
    started = time.monotonic()
    watcher.start()
    if canceller:
        canceller.start()
    with ResourceSampler(log_path=harness.REPORTS / f"telemetry_{label}.csv") as sampler:
        stack.service.runner.run_once(stack.queue.get_job(job_id))
    cancel_marker["stop"] = True
    watcher.stop()
    record["wall_seconds"] = round(time.monotonic() - started, 1)
    record["peaks"] = sampler.peaks.as_dict()
    record["comfy_pids_seen"] = sorted(watcher.pids)
    record["cancel"] = dict(cancel_marker)
    done = stack.repository.get_job(job_id)
    record["status"] = done.status.value if done else "missing"
    record["error"] = str(getattr(done, "error_message", "") or "")[:1500]
    result = getattr(done, "result", None) or {}
    record["sequence_artifact"] = harness._find_key(result, "sequence_artifact")
    time.sleep(5)
    record["after"] = {
        "host_ram_available_gb": harness._host_ram_gb(),
        "gpu": harness._driver_gpu(),
        "comfy_endpoint_state": harness._endpoint_state(comfy_url),
        **harness._manager_state(stack),
    }
    return record


def _verify(ledger: Path, label: str) -> dict[str, Any]:
    from tools.acceptance.seq330_sequence_verification import verify_sequence_evidence

    verdict = verify_sequence_evidence(ledger)
    (harness.REPORTS / f"{label}_verdict.json").write_text(
        json.dumps(verdict, indent=2), encoding="utf-8"
    )
    return verdict


def _find_ledger_for(workspace: Path, job_id: str) -> Path | None:
    for path in _ledgers(workspace):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("job_id") == job_id:
                return path
        except (OSError, ValueError):
            continue
    return None


def _make_anchor(source: Path, workspace: Path) -> Path:
    from PIL import Image, ImageOps

    target = workspace / "authored_anchor_480x832.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        ImageOps.fit(image.convert("RGB"), (480, 832), method=Image.Resampling.LANCZOS).save(target)
    return target


def _run(stack: Any, args: argparse.Namespace, evidence: dict, workspace: Path) -> int:
    harness._build_stack(stack, workspace)
    controller = _controller(stack, workspace)
    comfy_url = evidence["preflight"]["comfy_base_url"]
    source = Path(args.source)
    anchor = _make_anchor(source, workspace) if args.run == "C" else None
    job_id = controller.submit_sequence_job(
        source_image_path=source, form_data=_form(), sequence_intent=_intent(args.run, anchor)
    )
    stage = stack.queue.get_job(job_id)._normalized_record.stage_chain[0].to_dict()["extra"]
    evidence["admission"] = {
        "job_id": job_id,
        "plan_digest": stage["sequence_metadata"]["plan_digest"],
    }
    evidence["jobs"] = []
    cancel_at = 1 if args.run == "B" else None
    record = _run_job(stack, job_id, args.run, comfy_url, cancel_at=cancel_at)
    evidence["jobs"].append(record)
    harness._write_evidence(evidence)
    if harness._device_loss(record):
        evidence["hard_stop"] = "GPU device-loss signal; no further dispatch"
        return 2
    ledger = _find_ledger_for(workspace, job_id)
    evidence["parent_ledger"] = str(ledger) if ledger else None
    if args.run != "B":
        evidence["verdict"] = (
            _verify(ledger, args.run) if ledger else {"passed": False, "checks": []}
        )
        return 0 if record["status"] == "completed" and evidence["verdict"]["passed"] else 1

    # Run B: the cancelled job keeps its prefix; resume runs only the rest as a NEW job.
    if record["status"] != "cancelled" or ledger is None:
        evidence["note"] = "the job was not cancelled between segments; nothing to resume"
        return 1
    parent_bytes = ledger.read_bytes()
    child_id = controller.resume_sequence(job_id, ledger_path=str(ledger))
    child = _run_job(stack, child_id, "B_resume", comfy_url)
    evidence["jobs"].append(child)
    evidence["parent_ledger_unchanged_by_resume"] = ledger.read_bytes() == parent_bytes
    child_ledger = _find_ledger_for(workspace, child_id)
    evidence["verdict"] = (
        _verify(child_ledger, "B_resume") if child_ledger else {"passed": False, "checks": []}
    )
    if harness._device_loss(child):
        evidence["hard_stop"] = "GPU device-loss signal after the resume"
        return 2
    ok = (
        child["status"] == "completed"
        and evidence["verdict"]["passed"]
        and evidence["parent_ledger_unchanged_by_resume"]
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source")
    parser.add_argument("--run", choices=("A", "B", "C"), required=True)
    parser.add_argument("--dry", action="store_true", help="preflight only; queue nothing")
    parser.add_argument("--reports-dir", default=str(REPORTS))
    args = parser.parse_args(argv)
    harness.REPORTS = Path(args.reports_dir)
    harness.REPORTS.mkdir(parents=True, exist_ok=True)

    state = harness.preflight()
    print(json.dumps(state, indent=2))
    if state["comfy_endpoint_state"] != "free" or state["a1111_endpoint_state"] not in {
        "free",
        "unconfigured",
    }:
        print(
            "STOP: a runtime is serving a configured endpoint; StableNew will not adopt or stop it. Close it first."
        )
        return 3
    if args.dry:
        return 0
    workspace = harness.REPORTS / "workspace"
    evidence: dict[str, Any] = {"run": args.run, "source": str(args.source), "preflight": state}
    stack = harness._Stack()
    code = 1
    try:
        code = _run(stack, args, evidence, workspace)
    except BaseException as exc:
        evidence["aborted"] = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        owned, errors = harness._teardown(stack)
        evidence["teardown_stopped_owned_comfy"] = owned
        evidence["teardown_errors"] = errors
        evidence["final_gpu"] = harness._driver_gpu()
        harness._write_evidence(evidence)
    print(json.dumps(evidence, indent=2, default=str))
    return code or (1 if errors else 0)


if __name__ == "__main__":
    sys.exit(main())
