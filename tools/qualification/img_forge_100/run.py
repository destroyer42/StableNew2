"""Frozen eight-case operator run through the existing JobService/SQLite/NJR path.

Default CLI operation is preview only. Physical execution requires a separately approved matrix
digest and source/runtime provenance. No raw generation API, retry, runtime launcher or cancellation
case is provided here. Every failure stops further submission and retains the repository/artifacts.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from .preflight import explicit_endpoint, loopback_endpoint
from .provenance import digest, load_descriptor, verify_assets, write_exclusive

BACKENDS = ("a1111_webui", "forge_webui")
CHAINS = {"A": ("txt2img",), "B": ("txt2img",), "C": ("img2img",),
          "D": ("txt2img", "adetailer", "upscale")}
CASE_IDS = tuple(f"{scenario}-{backend}" for scenario in CHAINS for backend in BACKENDS)


def validate_matrix(matrix: dict[str, Any]) -> None:
    if matrix.get("package") != "PR-IMG-FORGE-100":
        raise ValueError("Wrong package")
    cases = matrix["cases"]
    if tuple(c["case_id"] for c in cases) != CASE_IDS:
        raise ValueError("Exactly the frozen eight cases, in order, are required")
    if matrix["settings"]["seed"] < 0 or matrix["settings"]["steps"] <= 0:
        raise ValueError("Freeze a seed and positive steps")
    for key in ("checkpoint", "input", "lora", "face_detector", "hand_detector"):
        spec = matrix["assets"][key]
        if len(spec["sha256"]) != 64 or not spec["path"]:
            raise ValueError(f"Freeze asset identity: {key}")
    for backend in BACKENDS:
        explicit_endpoint(matrix["endpoints"][backend], backend)
    loopback_endpoint(matrix["observed_comfy_endpoint"])
    if matrix["endpoints"][BACKENDS[0]] == matrix["endpoints"][BACKENDS[1]]:
        raise ValueError("A1111 and Forge endpoints must be separate")
    for case in cases:
        expected = f"{case['scenario']}-{case['backend']}"
        if case["case_id"] != expected or tuple(case["stages"]) != CHAINS[case["scenario"]]:
            raise ValueError("Case identity or stage chain changed")
        overrides = case.get("overrides", {})
        if overrides and (case["scenario"] != "C" or set(overrides) != {"width", "height"}):
            raise ValueError("Only frozen img2img geometry may override common settings")
    for index in range(0, 8, 2):
        if cases[index].get("overrides", {}) != cases[index + 1].get("overrides", {}):
            raise ValueError("Matched arms must request the same geometry")
    for name in ("adetailer", "upscale", "img2img"):
        extra = matrix["settings"].get(name, {})
        if any(key in extra for key in ("batch_size", "n_iter", "loop_count", "enable_hr")):
            raise ValueError("Stage options cannot expand the frozen job count")


def compile_case(matrix: dict[str, Any], case: dict[str, Any], root: Path) -> Any:
    """Create ordinary immutable NJRs; product stage translation remains in src/."""
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy
    from src.pipeline.njr_core_v26 import (
        CURRENT_NJR_SCHEMA_VERSION,
        ImageWorkloadSpec,
        NJRProvenance,
        NormalizedJobRecord,
        OutputPlan,
        SourceDescriptor,
        SourceKind,
        StageConfig,
        WorkloadKind,
    )

    s = {**matrix["settings"], **case.get("overrides", {})}
    prompt = s["prompt"]
    if case["scenario"] == "B":
        prompt += f" <lora:{s['lora_name']}:{s['lora_strength']}>"
    config = {**s, "model": s["checkpoint"], "prompt": prompt,
              "batch_size": 1, "n_iter": 1, "enable_hr": False,
              "prompt_optimizer": {"enabled": False},
              "pipeline": {"adetailer_enabled": case["scenario"] == "D",
                           "upscale_enabled": case["scenario"] == "D"}}
    config = apply_global_prompt_policy(
        config, positive_enabled=False, negative_enabled=False,
        positive_text=s.get("global_positive_prompt", ""),
        negative_text=s.get("global_negative_prompt", ""),
    )
    stages = []
    for name in case["stages"]:
        extra = dict(s.get(name, {}))
        if name == "img2img":
            extra.update(width=s["width"], height=s["height"], seed=s["seed"],
                         negative_prompt=s["negative_prompt"], clip_skip=s.get("clip_skip", 2))
        stages.append(StageConfig(stage_type=name, enabled=True, model=s["checkpoint"], vae=s["vae"],
                                  steps=s["steps"], cfg_scale=s["cfg_scale"],
                                  sampler_name=s["sampler_name"], scheduler=s["scheduler"],
                                  denoising_strength=s["img2img_denoise"] if name == "img2img" else None,
                                  extra=extra))
    input_paths = (matrix["assets"]["input"]["path"],) if case["scenario"] == "C" else ()
    return NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION, job_id=f"forge100-{digest(matrix)[:16]}-{case['case_id']}",
        workload_kind=WorkloadKind.IMAGE, source=SourceDescriptor(kind=SourceKind.CLI),
        workload=ImageWorkloadSpec(positive_prompt=prompt, negative_prompt=s["negative_prompt"],
                                  config=config, images_per_prompt=1, input_image_paths=input_paths,
                                  start_stage=case["stages"][0],
                                  backend_options={"image": {"backend_id": case["backend"]}},
                                  metadata={"qualification_case": case["case_id"], "matrix_sha256": digest(matrix)}),
        stages=tuple(stages), output_plan=OutputPlan(base_output_dir=str(root / "output")),
        provenance=NJRProvenance(seed=s["seed"], metadata={"qualification": "PR-IMG-FORGE-100"}),
    )


def build_services(matrix: dict[str, Any], root: Path) -> tuple[Any, Any]:
    """Use the production queue, repository, controller bridge and runner, without a process owner."""
    from src.api.webui_runtime_identity import classify_client_runtime
    from src.controller.job_service import JobService
    from src.controller.pipeline_controller import PipelineController
    from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts
    from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
    from src.image_backends.image_backend_registry import ImageBackendRegistry
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from src.queue.single_node_runner import SingleNodeJobRunner
    from src.services.runtime_transition_service import RuntimeTransitionCoordinator
    from src.utils import StructuredLogger
    from src.video.comfy_healthcheck import probe_comfy_endpoint

    repository = JobRepository(root / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    worker = SingleNodeJobRunner(queue, run_callable=None)
    service = JobService(queue, runner=worker, history_store=repository)
    controllers = {}
    for backend in BACKENDS:
        client = DefaultImageRuntimePorts(runtime_identity=backend).create_client(
            base_url=explicit_endpoint(matrix["endpoints"][backend], backend))
        # Explicit endpoint observers avoid generic discovery and cannot adopt/stop a PID.
        transition = RuntimeTransitionCoordinator(
            webui_manager_getter=lambda: None, comfy_manager_getter=lambda: None,
            webui_endpoint_present=lambda: True,  # Passing live preflight is mandatory before dispatch.
            webui_endpoint_identity=lambda c=client: classify_client_runtime(c).identity,
            comfy_endpoint_present=lambda: probe_comfy_endpoint(
                loopback_endpoint(matrix["observed_comfy_endpoint"]), timeout=0.5) != "free",
        )
        registry = ImageBackendRegistry()
        registry.register(A1111WebUIImageBackend(transition=transition))
        registry.register(ForgeWebUIImageBackend(transition=transition))
        runner = PipelineRunner(client, StructuredLogger(), runs_base_dir=str(root / "output"),
                                image_backend_registry=registry)
        controllers[backend] = PipelineController(pipeline_runner=runner, job_service=service)

    def dispatch(job: Any) -> dict[str, Any]:
        record = job._normalized_record
        return controllers[record.backend_options["image"]["backend_id"]]._run_job(job)

    worker.run_callable = dispatch
    service.auto_run_enabled = False
    return service, repository


def execute_matrix(
    matrix: dict[str, Any], root: Path, *, approved_digest: str | None,
    provenance: dict[str, Any], preflights: dict[str, dict[str, Any]],
    service_factory: Any = build_services, timeout_seconds: float = 600,
) -> list[dict[str, Any]]:
    validate_matrix(matrix)
    matrix_sha = digest(matrix)
    if approved_digest != matrix_sha:
        raise PermissionError("Physical execution requires the owner's exact approved matrix digest")
    if matrix.get("execution_blockers"):
        raise ValueError("The proposed matrix still has unresolved execution blockers")
    unsigned = {k: v for k, v in provenance.items() if k != "provenance_sha256"}
    if (provenance.get("matrix_sha256") != matrix_sha
            or provenance.get("provenance_sha256") != digest(unsigned)):
        raise ValueError("Unfrozen or mismatched provenance")
    descriptor = load_descriptor(Path(__file__).resolve().parents[3] / "config" / "forge_qualification_runtime.json")
    if (provenance.get("stable_sha") != matrix["stable_sha"]
            or provenance.get("forge", {}).get("commit") != descriptor["source"]["commit"]
            or provenance.get("adetailer", {}).get("commit") != descriptor["adetailer"]["commit"]):
        raise ValueError("Source provenance does not match the frozen qualification pins")
    verify_assets(matrix["assets"])
    if any(not preflights.get(b, {}).get("ready")
           or preflights[b].get("endpoint") != matrix["endpoints"][b] for b in BACKENDS):
        raise ValueError("Both explicit endpoints require passing preflight")
    root.mkdir(parents=True, exist_ok=False)  # An existing run is never replayed or overwritten.
    write_exclusive(root / "provenance.json", provenance)
    write_exclusive(root / "matrix.json", matrix)
    records = [compile_case(matrix, case, root) for case in matrix["cases"]]
    for record in records:
        write_exclusive(root / f"{record.job_id}.njr.json", record.to_dict())
    service, repository = service_factory(matrix, root)
    from src.controller.submission_policy_v26 import SubmissionPolicy

    results = []
    for case, record in zip(matrix["cases"], records, strict=True):
        started = time.monotonic()
        service.submit_njrs([record], policy=SubmissionPolicy(start_when_idle=True))
        while True:
            entry = repository.get_job(record.job_id)
            status = getattr(getattr(entry, "status", None), "value", "")
            if status in {"completed", "failed", "cancelled"}:
                result = {"case_id": case["case_id"], "job_id": record.job_id,
                          "status": status, "elapsed_seconds": time.monotonic() - started,
                          "snapshot": entry.snapshot, "result": entry.result,
                          "error": entry.error_message}
                write_exclusive(root / f"{case['case_id']}.result.json", result)
                results.append(result)
                if status != "completed":
                    return results  # Device loss and ambiguous failures never trigger another submission.
                break
            if time.monotonic() - started >= timeout_seconds:
                write_exclusive(root / f"{case['case_id']}.timeout.json",
                                {"job_id": record.job_id, "status": "unknown", "replay_forbidden": True})
                raise TimeoutError("Job state is ambiguous; preserve the run and do not replay")
            time.sleep(0.1)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    args = parser.parse_args()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    validate_matrix(matrix)
    print(json.dumps({"matrix_sha256": digest(matrix), "cases": CASE_IDS,
                      "physical_execution": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
