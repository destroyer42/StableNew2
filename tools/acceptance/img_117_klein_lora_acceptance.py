"""PR-IMG-117 physical acceptance driver: FLUX.2 Klein 4B FP8 single-LoRA production acceptance.

A thin observer in the shape of ``img_116_klein_acceptance``. One managed Forge session (started and stopped ONLY
through ``WebUIProcessManager``) runs three jobs through the production path

    ``build_cli_njr`` -> ``JobService.submit_njrs`` -> SQLite -> ``SingleNodeJobRunner`` ->
    ``PipelineRunner.run_njr`` -> ``forge_webui``

with the same prompt, seed, geometry and fixed Klein sampling:

* ``baseline``  - no LoRA;
* ``lora_a``    - exactly one LoRA at the first weight;
* ``lora_b``    - the same LoRA at a second weight (shows that the weight is honored).

Profile version 2 is selected for this process only (in memory) until the qualification is accepted, exactly as an
operator who selected ``forge_webui`` is simulated in memory by the PR-IMG-116 driver. Nothing here retries, replays,
adopts or kills a process, writes production settings, or builds a second compiler, queue or runner. Each job is
submitted exactly once; ``--dry`` freezes and prints the intent digest that physical execution requires.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from src.image_backends.forge_klein_lora import observe_lora_consumption
from tools.acceptance.img_116_klein_acceptance import (
    BACKEND,
    SEED_A,
    _fault_events,
    _NullSampler,
    _OwnedTree,
    forge_selected_in_memory,
    verify_installed_assets,
)
from tools.acceptance.img_forge_100_acceptance import (
    _DEVICE_LOSS,
    EXIT_COMPLETED,
    EXIT_DRY,
    EXIT_FAILED,
    EXIT_NOT_SUBMITTED,
    EXIT_STOPPED,
    AmbiguousDispatch,
    InjectedRuntime,
    ManagedWebUIRuntime,
    _artifacts,
    _await_terminal,
    _write_new,
    build_stack,
    digest,
    intent_digest,
)

LORA_NAME = "flux2-klein-4b-lora-old-gods"
WEIGHT_A = 0.8
WEIGHT_B = 0.4
PROMPT = (
    "An old-gods wise elder in a candlelit workshop, detailed portrait, shallow depth of field, "
    "warm natural light"
)
# Forge prints no HTTP access log; each generation dispatch shows up as exactly one sampling progress bar.
_SAMPLING_RUN = re.compile(r"Total progress:\s+0%")


@contextmanager
def klein_v2_selected_in_memory():
    """Profile v2 as the version new work is stamped with, for this process only (never persisted)."""

    from unittest.mock import patch

    from src.image_backends import forge_klein_profile as profile_module

    with patch.object(profile_module, "_LATEST_PROFILE", profile_module.KLEIN_PROFILE_V2):
        yield


def job_specs() -> list[dict[str, Any]]:
    return [
        {"label": "baseline", "prompt": PROMPT, "lora": None},
        {"label": "lora_a", "prompt": f"{PROMPT} <lora:{LORA_NAME}:{WEIGHT_A:g}>", "lora": (LORA_NAME, WEIGHT_A)},
        {"label": "lora_b", "prompt": f"{PROMPT} <lora:{LORA_NAME}:{WEIGHT_B:g}>", "lora": (LORA_NAME, WEIGHT_B)},
    ]


def freeze_job(spec: dict[str, Any], *, job_id: str, output_dir: Path) -> Any:
    from src.pipeline.cli_njr_builder import build_cli_njr

    config = {
        "txt2img": {
            "model": "flux-2-klein-4b-fp8.safetensors",
            "seed": SEED_A,
            "width": 768,
            "height": 1024,
            "batch_size": 1,
            "n_iter": 1,
        },
        "backend_options": {"image": {"backend_id": BACKEND}},
    }
    njr = build_cli_njr(prompt=spec["prompt"], config=config, batch_size=1, run_name=job_id)
    return replace(njr, output_plan=replace(njr.output_plan, base_output_dir=str(output_dir)))


def _stdout_text(runtime: Any) -> str:
    path = Path(str(runtime.manager.get_recent_output_tail(max_lines=1).get("stdout_log_path") or ""))
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _count_sampling_runs(runtime: Any) -> int:
    """Sampling runs Forge's stdout has recorded so far (one per generation dispatch; read-only)."""

    text = _stdout_text(runtime)
    return len(_SAMPLING_RUN.findall(text)) if text else -1


def run(args: argparse.Namespace, runtime: Any, *, sampler_factory: Any = None, client: Any = None) -> int:
    import psutil

    reports = Path(args.reports_dir).resolve()
    if reports.exists() and any(reports.iterdir()):
        raise FileExistsError(f"{reports} already holds evidence; choose a new --reports-dir")
    reports.mkdir(parents=True, exist_ok=True)
    output_dir = reports / "output"
    stamp = int(time.time())
    with forge_selected_in_memory(), klein_v2_selected_in_memory():
        njrs = {
            spec["label"]: freeze_job(spec, job_id=f"img117-{spec['label']}-{stamp}", output_dir=output_dir)
            for spec in job_specs()
        }
        digests = {label: intent_digest(njr) for label, njr in njrs.items()}
        combined = digest(digests)
        report: dict[str, Any] = {
            "job_ids": {label: njr.job_id for label, njr in njrs.items()},
            "intent_sha256": combined,
            "per_job_intent_sha256": digests,
            "reports_dir": str(reports),
            "njrs": {label: njr.to_dict() for label, njr in njrs.items()},
            "configured_backend_override": "forge_webui and profile v2 selected in memory for this process only",
            "jobs": {},
        }
        _write_new(reports / "intent.json", report)
        if args.dry:
            print(json.dumps({"dry": True, "intent_sha256": combined, "reports_dir": str(reports), "jobs": digests}))
            return EXIT_DRY
        if args.approved_intent_sha256 != combined:
            raise PermissionError(f"Physical execution requires the approved intent digest {combined}")

        code, stack, submitted = EXIT_NOT_SUBMITTED, None, False
        began_wall = datetime.now()
        try:
            report["assets_verified"] = verify_installed_assets(Path(args.forge_data_dir))
            report["lora_file"] = _lora_identity(args.lora_file)
            report["pre_run_memory"] = {
                "available_gb": round(psutil.virtual_memory().available / 1e9, 2),
                "total_gb": round(psutil.virtual_memory().total / 1e9, 2),
            }
            report["runtime_start"] = runtime.start()
            start = report["runtime_start"]
            if start.get("owns_process") and not start["process_risk"]["webui_runtime_tree_count"]:
                report["classification"] = "PRODUCTION_PROCESS_OBSERVATION_DEFECT"
                return code
            stack = build_stack(reports / "state", output_dir, BACKEND, getattr(args, "endpoint", ""), client=client)
            report["forge_lora_listing"] = _listing(stack.client, LORA_NAME)
            from src.controller.submission_policy_v26 import SubmissionPolicy
            from tools.qualification.img115.run import _TreeSampler

            code = EXIT_COMPLETED
            for spec in job_specs():
                label = spec["label"]
                njr = njrs[label]
                before_posts = _count_sampling_runs(runtime) if runtime is not None else -1
                memory_before = {
                    "total_gb": round(psutil.virtual_memory().total / 1e9, 2),
                    "available_gb": round(psutil.virtual_memory().available / 1e9, 2),
                }
                started = time.monotonic()
                sampler = sampler_factory(reports / f"telemetry-{label}.csv") if sampler_factory else _NullSampler()
                with sampler as peaks, _TreeSampler(_OwnedTree(runtime), reports / f"tree-{label}.csv") as tree:
                    submitted = True
                    stack.service.submit_njrs([njr], SubmissionPolicy(start_when_idle=True))
                    entry = _await_terminal(stack.repository, njr.job_id, args.timeout_seconds)
                status, error = entry.status.value, str(entry.error_message or "")
                variants = (entry.result or {}).get("variants") or [{}]
                job = {
                    "label": label,
                    "status": status,
                    "error": error,
                    "wall_seconds": round(time.monotonic() - started, 1),
                    "memory_before_dispatch": memory_before,
                    "artifacts": _artifacts(entry.result),
                    "klein_evidence": (variants[0].get("image_backend_metadata") or {}).get("klein_profile"),
                    "variant": {k: v for k, v in variants[0].items() if k != "image_backend_metadata"},
                    "sampling_runs": (_count_sampling_runs(runtime) - before_posts) if before_posts >= 0 else None,
                    "peaks": peaks.peaks.as_dict() if hasattr(peaks, "peaks") else None,
                    "forge_tree_memory": tree.peaks(),
                    "snapshot_profile": (
                        ((entry.snapshot or {}).get("normalized_job", {}).get("workload", {}) or {})
                        .get("backend_options")
                    ),
                    "snapshot_prompt": (
                        ((entry.snapshot or {}).get("normalized_job", {}).get("workload", {}) or {}).get("positive_prompt")
                    ),
                }
                report["jobs"][label] = job
                if any(marker in error.lower() for marker in _DEVICE_LOSS):
                    code = EXIT_STOPPED
                    break
                if status != "completed":
                    code = EXIT_FAILED
                    break  # one failure class ends the run; nothing is retried or replayed
            report["forge_lora_observation"] = observe_lora_consumption(
                _stdout_text(runtime).splitlines(), LORA_NAME
            )
        except AmbiguousDispatch as exc:
            report["classification"], report["error"], code = "AMBIGUOUS_DISPATCH", str(exc), EXIT_STOPPED
        except Exception as exc:  # noqa: BLE001 - evidence first: record, stop, never retry
            report["error"] = f"{type(exc).__name__}: {exc}"
            code = EXIT_STOPPED if submitted else EXIT_NOT_SUBMITTED
        finally:
            if stack is not None:
                stack.service.stop()
                stack.repository.close()
            report["runtime_stop"] = runtime.stop()
            report["fault_events"] = _fault_events(began_wall)
            report["exit_code"] = code
            _write_new(reports / "acceptance.json", report)
    print(json.dumps({"exit_code": code, "intent_sha256": combined, "reports_dir": str(reports)}))
    return code


def _lora_identity(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    target = Path(path)
    digest_ = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest_.update(block)
    return {"name": target.stem, "bytes": target.stat().st_size, "sha256": digest_.hexdigest()}


def _listing(client: Any, name: str) -> dict[str, Any]:
    lister = getattr(client, "get_loras", None)
    listed = lister() if callable(lister) else None
    if listed is None:
        return {"readable": False}
    match = [item for item in listed if name.lower() in {item["name"].lower(), item["alias"].lower()}]
    return {"readable": True, "count": len(listed), "entry": match[0] if match else None}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime-profile", type=Path)
    parser.add_argument("--forge-data-dir", type=Path, required=True)
    parser.add_argument("--lora-file", type=Path, required=True, help="the LoRA file (hashed for the report only)")
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--approved-intent-sha256", default="")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--dry", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry:
        return run(args, InjectedRuntime())
    if args.runtime_profile is None:
        raise SystemExit("--runtime-profile is required for physical execution")
    profile = json.loads(args.runtime_profile.read_text(encoding="utf-8"))
    runtime = ManagedWebUIRuntime(profile, BACKEND)
    args.endpoint = runtime.endpoint
    from tools.qualification.vid110.monitor import ResourceSampler

    return run(args, runtime, sampler_factory=lambda log: ResourceSampler(log_path=log))


if __name__ == "__main__":
    sys.exit(main())
