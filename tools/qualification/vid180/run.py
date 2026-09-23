"""PR-VID-180: Wan2.2-Animate 480x832 motion-transfer characterization (qualification only).

Answers the product question PR-VID-175's interpretability PASS made askable: at the
resource-viable, visually interpretable 480x832 envelope, does Wan2.2-Animate transfer useful
human gesture (Case A) and genuine stepping/root translation (Case B) while preserving the
reference person's identity, anatomy and temporal coherence? Reuses ``tools.qualification.vid170.
graph`` unchanged (only ``width``/``height`` differ, exactly as PR-VID-175 did), plus PR-VID-160B/
160C's ownership/preflight/teardown, commit-aware telemetry, and Comfy dispatch, all unchanged.
Case C (real weight-shift/hip-hinge) is PR-VID-175's already-accepted evidence, reused read-only,
not a runnable case in this module. Still qualification-only: Animate is not a registered
StableNew workflow, and this never goes through ``VideoWorkflowController``/NJR/
``VideoExecutionResolver``.

    python -m tools.qualification.vid180.run <reference_image.png> --case A|B [--dry]

Exactly one prompt is submitted per invocation, and evidence is written under a case-specific
directory so output association can never mix cases. There is no retry loop anywhere in this
module, and no code path here can submit case "C".
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
from tools.qualification.vid160c.run import stage_pose_video
from tools.qualification.vid160c.telemetry import CommitAwareResourceSampler
from tools.qualification.vid170.graph import (
    CharacterizationSpec,
    build_characterization_graph,
    validate_graph,
)

REPORTS_ROOT = Path("reports/vid180")
RUN_TIMEOUT_SECONDS = 900.0

WIDTH = 480
HEIGHT = 832

# Only A and B are runnable. Case C is PR-VID-175's already-accepted evidence, reused read-only;
# it is deliberately absent from this mapping so no code path here can submit it.
CASES: dict[str, Path] = {
    "A": Path("reports/vid180/case_a_arm_raise_480x832.mp4"),
    "B": Path("reports/vid180/case_b_walk_forward_480x832.mp4"),
}

REQUIRED_NODE_CLASSES = (
    "UnetLoaderGGUF",
    "WanAnimateToVideo",
    "CLIPVisionLoader",
    "CLIPVisionEncode",
    "ModelSamplingSD3",
    "LoadVideo",
    "GetVideoComponents",
)

__all__ = ["REPORTS_ROOT", "CASES", "WIDTH", "HEIGHT", "preflight", "run_case", "main", "case_reports_dir"]


def case_reports_dir(case: str) -> Path:
    return REPORTS_ROOT / f"run_{case.lower()}"


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


def _run_case(
    stack: _Stack, args: argparse.Namespace, evidence: dict[str, Any], reports: Path
) -> int:
    from src.video.comfy_process_manager import (
        ComfyProcessManager,
        build_default_comfy_process_config,
    )

    if args.case not in CASES:
        raise ValueError(f"unknown case {args.case!r}; expected one of {sorted(CASES)}")
    pose_source = CASES[args.case]
    if not pose_source.exists():
        raise RuntimeError(f"frozen pose asset missing: {pose_source}")

    config = build_default_comfy_process_config()
    if config is None:
        raise RuntimeError("no configured Comfy process (unconfigured base_url/command)")
    evidence["comfy_command_memory_flags"] = [
        flag
        for flag in config.command
        if flag.startswith("--") and any(k in flag for k in ("vram", "memory", "gpu-only"))
    ]
    stack.manager = ComfyProcessManager(config)
    stack.manager.ensure_running()
    base_url = config.base_url or "http://127.0.0.1:8188"
    comfy_pid = stack.manager.pid

    dependency_problems = verify_dependencies(base_url)
    evidence["dependency_check"] = dependency_problems
    if dependency_problems:
        evidence["status"] = "dependency_blocked"
        return 1

    client = ComfyClient(base_url)
    uploaded_reference = client.upload_image(Path(args.reference_image))
    evidence["uploaded_reference_image"] = uploaded_reference
    pose_filename = stage_pose_video(config.command, pose_source)
    evidence["pose_asset_source"] = str(pose_source)
    evidence["staged_pose_video"] = pose_filename

    spec = CharacterizationSpec(
        reference_image=uploaded_reference,
        pose_video_file=pose_filename,
        width=WIDTH,
        height=HEIGHT,
    )
    graph = build_characterization_graph(spec)
    graph_problems = validate_graph(graph)
    evidence["graph_validation"] = graph_problems
    evidence["frozen_spec"] = {
        "case": args.case,
        "width": spec.width,
        "height": spec.height,
        "length": spec.length,
        "steps": spec.steps,
        "cfg": spec.cfg,
        "shift": spec.shift,
        "seed": spec.seed,
        "sampler": spec.sampler,
        "scheduler": spec.scheduler,
        "positive_prompt": spec.positive_prompt,
        "negative_prompt": spec.negative_prompt,
        "fps": spec.fps,
        "pose_video_file": pose_filename,
    }
    if graph_problems:
        evidence["status"] = "graph_invalid"
        return 1

    reports.mkdir(parents=True, exist_ok=True)
    (reports / "frozen_graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")

    started = time.monotonic()
    with CommitAwareResourceSampler(
        comfy_pid=comfy_pid, log_path=reports / "telemetry.csv"
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
    saved = client.download(outputs[0], reports / f"case_{args.case.lower()}_output.mp4")
    evidence["output_path"] = str(saved)
    evidence["output_bytes"] = saved.stat().st_size
    evidence["status"] = "completed" if saved.stat().st_size > 0 else "empty_output"
    return 0 if evidence["status"] == "completed" else 1


def _write_evidence(evidence: dict[str, Any], reports: Path) -> None:
    try:
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never mask the run's own outcome
        print(f"could not write evidence: {exc}", file=sys.stderr)


def run_case(args: argparse.Namespace) -> int:
    """Build, run and always tear down. Exactly one Comfy prompt submission for this one case. No
    retry."""

    reports = case_reports_dir(args.case)
    evidence: dict[str, Any] = {"preflight": preflight(), "case": args.case}
    stack = _Stack()
    code = 1
    try:
        code = _run_case(stack, args, evidence, reports)
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
    parser.add_argument("reference_image")
    parser.add_argument("--case", required=True, choices=sorted(CASES))
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
    return run_case(args)


if __name__ == "__main__":
    sys.exit(main())
