"""PR-VID-160C commit-aware adjudication run.

Answers the question the first PR-VID-160C run left open: did the frozen <1.0 GB
available-physical-RAM guard stop a generation that would otherwise have completed within real
Windows virtual-memory (commit) capacity, or was physical exhaustion predictive of genuine commit
exhaustion? This module runs the *exact* first-run graph/assets/settings again
(``tools.qualification.vid160c.graph.build_pose_probe_graph``, entirely unchanged) through the
same manager-owned Comfy dispatch, replacing only the sampler:
``tools.qualification.vid160c.telemetry.CommitAwareResourceSampler`` in place of
``tools.qualification.vid160b.telemetry.ProbeResourceSampler``. The original run's own module,
``tools.qualification.vid160c.run``, is untouched, and its evidence
(``reports/vid160c/evidence.json``, ``reports/vid160c/telemetry.csv``) is preserved as-is; this
module writes to a separate ``reports/vid160c/adjudication/`` evidence root.

    python -m tools.qualification.vid160c.adjudicate <reference_image.png> <pose_video.mp4> [--dry]

Exactly one additional prompt is submitted per invocation. There is no retry loop anywhere in this
module.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from tools.qualification.vid110.comfy_client import ComfyClient, ComfyRunError
from tools.qualification.vid160b.run import _Stack, _teardown, preflight
from tools.qualification.vid160c.graph import PoseProbeSpec, build_pose_probe_graph, validate_graph
from tools.qualification.vid160c.run import REQUIRED_NODE_CLASSES, stage_pose_video
from tools.qualification.vid160c.telemetry import CommitAwareResourceSampler

REPORTS = Path("reports/vid160c/adjudication")
RUN_TIMEOUT_SECONDS = 900.0

__all__ = ["REPORTS", "preflight", "run_adjudication", "main"]


def verify_dependencies(base_url: str) -> list[str]:
    import requests

    problems: list[str] = []
    try:
        response = requests.get(f"{base_url}/object_info", timeout=20.0)
        response.raise_for_status()
        info = response.json()
    except Exception as exc:  # noqa: BLE001 - reported as a dependency problem, not raised
        return [f"could not read /object_info: {type(exc).__name__}: {exc}"]
    for node_class in REQUIRED_NODE_CLASSES:
        if node_class not in info:
            problems.append(f"required node class not advertised by Comfy: {node_class}")
    return problems


def _run_adjudication(
    stack: _Stack, args: argparse.Namespace, evidence: dict[str, Any]
) -> int:
    from src.video.comfy_process_manager import (
        ComfyProcessManager,
        build_default_comfy_process_config,
    )
    from tools.qualification.vid160c.win_memory import read_system_commit

    config = build_default_comfy_process_config()
    if config is None:
        raise RuntimeError("no configured Comfy process (unconfigured base_url/command)")
    evidence["comfy_command_memory_flags"] = [
        flag
        for flag in config.command
        if flag.startswith("--")
        and any(k in flag for k in ("vram", "memory", "gpu-only"))
    ]
    stack.manager = ComfyProcessManager(config)
    stack.manager.ensure_running()
    base_url = config.base_url or "http://127.0.0.1:8188"
    comfy_pid = stack.manager.pid
    evidence["comfy_pid"] = comfy_pid

    baseline_commit = read_system_commit()
    evidence["baseline_commit"] = {
        "commit_total_gb": round(baseline_commit.commit_total_gb, 2),
        "commit_limit_gb": round(baseline_commit.commit_limit_gb, 2),
        "commit_headroom_gb": round(baseline_commit.commit_headroom_gb, 2),
        "commit_percent": round(baseline_commit.commit_percent, 2),
        "physical_available_gb": round(baseline_commit.physical_available_gb, 2),
    }

    dependency_problems = verify_dependencies(base_url)
    evidence["dependency_check"] = dependency_problems
    if dependency_problems:
        evidence["status"] = "dependency_blocked"
        return 1

    client = ComfyClient(base_url)
    uploaded_reference = client.upload_image(Path(args.reference_image))
    evidence["uploaded_reference_image"] = uploaded_reference
    pose_filename = stage_pose_video(config.command, Path(args.pose_video))
    evidence["staged_pose_video"] = pose_filename

    # Identical spec to the first VID-160C run -- no parameter differs.
    spec = PoseProbeSpec(reference_image=uploaded_reference, pose_video_file=pose_filename)
    graph = build_pose_probe_graph(spec)
    graph_problems = validate_graph(graph)
    evidence["graph_validation"] = graph_problems
    evidence["frozen_spec"] = {
        "width": spec.width,
        "height": spec.height,
        "length": spec.length,
        "steps": spec.steps,
        "cfg": spec.cfg,
        "shift": spec.shift,
        "seed": spec.seed,
        "sampler": spec.sampler,
        "scheduler": spec.scheduler,
        "pose_video_file": pose_filename,
    }
    if graph_problems:
        evidence["status"] = "graph_invalid"
        return 1

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "frozen_graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")

    started = time.monotonic()
    with CommitAwareResourceSampler(
        comfy_pid=comfy_pid, log_path=REPORTS / "telemetry.csv"
    ) as sampler:
        try:
            prompt_id = client.queue(graph)
            evidence["prompt_id"] = prompt_id
            entry = client.wait(
                prompt_id,
                timeout=RUN_TIMEOUT_SECONDS,
                poll=1.0,
                abort_reason=sampler.abort_reason,
            )
        except ComfyRunError as exc:
            evidence["wall_seconds"] = round(time.monotonic() - started, 1)
            evidence["peaks"] = sampler.peaks.as_dict()
            evidence["error"] = str(exc)[:1500]
            evidence["status"] = (
                "commit_aware_safety_stop" if sampler.peaks.stop_reason else "comfy_run_error"
            )
            return 1
    evidence["wall_seconds"] = round(time.monotonic() - started, 1)
    evidence["peaks"] = sampler.peaks.as_dict()

    outputs = client.output_files(entry)
    evidence["outputs"] = outputs
    if not outputs:
        evidence["status"] = "no_output"
        return 1
    saved = client.download(outputs[0], REPORTS / "probe_output.mp4")
    evidence["output_path"] = str(saved)
    evidence["output_bytes"] = saved.stat().st_size
    evidence["status"] = "completed" if saved.stat().st_size > 0 else "empty_output"
    return 0 if evidence["status"] == "completed" else 1


def _write_evidence(evidence: dict[str, Any]) -> None:
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never mask the run's own outcome
        print(f"could not write evidence: {exc}", file=sys.stderr)


def run_adjudication(args: argparse.Namespace) -> int:
    """Build, run and always tear down. Exactly one additional Comfy prompt submission. No
    retry."""

    evidence: dict[str, Any] = {"preflight": preflight()}
    stack = _Stack()
    code = 1
    try:
        code = _run_adjudication(stack, args, evidence)
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
    parser.add_argument("reference_image")
    parser.add_argument("pose_video")
    parser.add_argument("--dry", action="store_true", help="preflight only; submit nothing")
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
    return run_adjudication(args)


if __name__ == "__main__":
    sys.exit(main())
