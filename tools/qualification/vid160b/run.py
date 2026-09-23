"""PR-VID-160B: Wan2.2-Animate-14B GGUF resource-feasibility probe (qualification only).

Answers exactly one question: can the frozen minimal Move-mode graph
(``tools.qualification.vid160b.graph``) complete one generation on this machine without unsafe
host-memory exhaustion, VRAM failure, or GPU loss? This is **not** production integration: Animate
is not a registered StableNew workflow, and this tool dispatches directly to a manager-owned Comfy
instance the same way ``tools/qualification/vid110`` does, never through
``VideoWorkflowController``/NJR/``VideoExecutionResolver``. It creates no second queue or history
store, never imports from ``src.controller``/``src.queue``, and only ever owns the one Comfy
process ``ComfyProcessManager`` itself launches.

    python -m tools.qualification.vid160b.run <reference_image.png> [--dry]

Exactly one prompt is submitted per invocation. There is no retry loop anywhere in this module.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.qualification.vid110.comfy_client import ComfyClient, ComfyRunError
from tools.qualification.vid160b.graph import ProbeSpec, build_probe_graph, validate_graph
from tools.qualification.vid160b.telemetry import ProbeResourceSampler

REPORTS = Path("reports/vid160b")
REQUIRED_NODE_CLASSES = (
    "UnetLoaderGGUF",
    "WanAnimateToVideo",
    "CLIPVisionLoader",
    "CLIPVisionEncode",
    "ModelSamplingSD3",
)
RUN_TIMEOUT_SECONDS = 900.0


def preflight() -> dict[str, Any]:
    from src.video.comfy_healthcheck import probe_comfy_endpoint
    from src.video.comfy_process_manager import build_default_comfy_process_config

    config = build_default_comfy_process_config()
    base_url = config.base_url if config else None
    state = probe_comfy_endpoint(base_url, timeout=1.0) if base_url else "unconfigured"
    return {"comfy_base_url": base_url, "endpoint_state": state, "autostart": bool(config)}


def verify_dependencies(base_url: str) -> list[str]:
    """Bounded, read-only check that the frozen graph's node classes are advertised.

    Model-file presence is intentionally NOT re-checked over HTTP here: ComfyUI only reports a
    missing model file as part of a failed prompt validation, which the single real submission
    itself will surface. This check exists to fail fast on a missing *node* (wrong custom-node
    install) before spending the one authorized attempt.
    """

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


@dataclass
class _Stack:
    """Everything the probe creates; a partial build is still torn down by ``_teardown``."""

    manager: Any = None


def _stop_owned_comfy(stack: _Stack) -> bool:
    if stack.manager is None or not stack.manager.owns_process:
        return False
    stack.manager.stop()
    return True


def _teardown(stack: _Stack) -> tuple[bool, list[str]]:
    """Release only the Comfy process this run's own manager owns. Never raises."""

    errors: list[str] = []
    owned = False
    try:
        owned = _stop_owned_comfy(stack)
    except Exception as exc:  # noqa: BLE001 - one failed step must not mask the outcome
        errors.append(f"stop_owned_comfy: {type(exc).__name__}: {exc}"[:300])
    return owned, errors


def _run_probe(stack: _Stack, args: argparse.Namespace, evidence: dict[str, Any]) -> int:
    from src.video.comfy_process_manager import (
        ComfyProcessManager,
        build_default_comfy_process_config,
    )

    config = build_default_comfy_process_config()
    if config is None:
        raise RuntimeError("no configured Comfy process (unconfigured base_url/command)")
    stack.manager = ComfyProcessManager(config)
    stack.manager.ensure_running()
    base_url = config.base_url or "http://127.0.0.1:8188"

    dependency_problems = verify_dependencies(base_url)
    evidence["dependency_check"] = dependency_problems
    if dependency_problems:
        evidence["status"] = "dependency_blocked"
        return 1

    client = ComfyClient(base_url)
    uploaded_name = client.upload_image(Path(args.reference_image))
    evidence["uploaded_reference_image"] = uploaded_name

    spec = ProbeSpec(reference_image=uploaded_name)
    graph = build_probe_graph(spec)
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
    }
    if graph_problems:
        evidence["status"] = "graph_invalid"
        return 1

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "frozen_graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")

    started = time.monotonic()
    with ProbeResourceSampler(log_path=REPORTS / "telemetry.csv") as sampler:
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
                "safety_stop" if sampler.peaks.stop_reason else "comfy_run_error"
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


def run_probe(args: argparse.Namespace) -> int:
    """Build, run and always tear down. Exactly one Comfy prompt submission. No retry."""

    evidence: dict[str, Any] = {"preflight": preflight()}
    stack = _Stack()
    code = 1
    try:
        code = _run_probe(stack, args, evidence)
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
    return run_probe(args)


if __name__ == "__main__":
    sys.exit(main())
