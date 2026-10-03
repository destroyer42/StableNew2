"""PR-IMG-FORGE-100 canonical-path physical acceptance driver (Pair A baseline).

A thin observer around production authority. It freezes ONE case with the production CLI NJR
builder and the production global-prompt policy helper, submits it through

    JobService.submit_njrs -> SQLite JobRepository/JobQueue -> SingleNodeJobRunner ->
    PipelineController -> PipelineRunner.run_njr -> image backend registry -> WebUI-family backend

and reports what happened. A managed runtime is started and stopped ONLY through
``WebUIProcessManager`` (the lifecycle authority) and is *observed*, never gated, through the existing
process inspector. This module does not build a second compiler, queue, backend dispatch, runtime
transition coordinator, prompt/optimizer translation or ownership gate; it does not wrap or patch HTTP,
mutate manager internals, kill processes or change directory.

Application context and evidence location are separate: run it from the StableNew checkout (the process
inspector anchors StableNew ancestry on the process's working directory) and point ``--reports-dir`` anywhere.

    python -m tools.acceptance.img_forge_100_acceptance --backend a1111_webui \
        --runtime-profile <profile.json> --reports-dir <evidence dir> --approved-intent-sha256 <digest>

One job per invocation. Pair A (default) is frozen from the tracked intent with the production CLI builder.
Pairs B/C/D (``--case B|C|D --matrix <authoritative frozen matrix.json>``) use the same production builders
(B/D: the CLI builder with the frozen LoRA token / ADetailer + upscale sections; C: ``ReprocessJobBuilder``
for img2img from the frozen source image); the matrix settings must equal the tracked intent, and the case's
assets are hash verified before any runtime starts. Cancellation and the full matrix belong to later packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INTENT = REPO_ROOT / "tests" / "data" / "contracts" / "img_forge_100_frozen_intent.json"
BACKENDS = ("a1111_webui", "forge_webui")
_TERMINAL = {"completed", "failed", "cancelled"}
_DEVICE_LOSS = ("device lost", "cuda error", "illegal memory access", "unspecified launch failure", "gpu is lost")

EXIT_COMPLETED = EXIT_DRY = 0
EXIT_FAILED, EXIT_STOPPED, EXIT_NOT_SUBMITTED = 1, 2, 3  # stopped: device loss / ambiguous dispatch


class AmbiguousDispatch(RuntimeError):
    """The job never reached a terminal state; its outcome is unknown and it must not be replayed."""


def digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Freeze: the case, through production builders ------------------------------------------------


def load_pair_a(intent_path: Path, backend: str) -> dict[str, Any]:
    document = json.loads(Path(intent_path).read_text(encoding="utf-8"))
    case = next((c for c in document["cases"] if c["case_id"] == f"A-{backend}"), None)
    if case is None or tuple(case["stages"]) != ("txt2img",):
        raise ValueError(f"The frozen intent has no Pair-A txt2img case for {backend}")
    return document["settings"]


CASES = ("A", "B", "C", "D")
_CASE_ASSETS = {
    "A": ("checkpoint",),
    "B": ("checkpoint", "lora"),
    "C": ("checkpoint", "input"),
    "D": ("checkpoint", "face_detector", "hand_detector", "upscaler"),
}


def load_frozen_case(matrix_path: Path, letter: str, backend: str, intent_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """The authoritative frozen matrix and one case; its settings and case must equal the tracked intent."""

    matrix = json.loads(Path(matrix_path).read_text(encoding="utf-8-sig"))
    contract = json.loads(Path(intent_path).read_text(encoding="utf-8"))
    if matrix["settings"] != contract["settings"]:
        raise ValueError("The frozen matrix settings differ from the tracked frozen intent")
    case_id = f"{letter}-{backend}"
    case = next((c for c in matrix["cases"] if c["case_id"] == case_id), None)
    tracked = next((c for c in contract["cases"] if c["case_id"] == case_id), None)
    if case is None or tracked is None or any(case.get(k) != tracked.get(k) for k in ("stages", "overrides", "scenario", "backend")):
        raise ValueError(f"The frozen matrix has no case {case_id} agreeing with the tracked intent")
    return matrix, case


def freeze_case_njr(matrix: dict[str, Any], case: dict[str, Any], *, job_id: str, output_dir: Path) -> Any:
    """Immutable NJR for a frozen case; every transformation is a production builder or helper."""

    letter, backend = case["scenario"], case["backend"]
    settings = {**matrix["settings"], **case.get("overrides", {})}  # C carries its frozen 480x832 geometry
    if letter != "C":
        return freeze_njr(settings, backend, job_id=job_id, output_dir=output_dir, case=letter)
    from src.pipeline.reprocess_builder import ReprocessJobBuilder

    policy = _frozen_policy(settings, img2img_enabled=True)
    section = {key: settings[key] for key in ("steps", "cfg_scale", "sampler_name", "scheduler", "seed", "width", "height", "clip_skip", "negative_prompt")}
    section.update(model=settings["checkpoint"], vae=settings["vae"], denoising_strength=settings["img2img_denoise"])
    config = {
        "img2img": section,
        "pipeline": policy["pipeline"],
        "prompt_optimizer": {"enabled": False},
        "backend_options": {"image": {"backend_id": backend}},
        "model": settings["checkpoint"],
        "vae": settings["vae"],
        **{key: policy[key] for key in ("global_positive_prompt", "global_negative_prompt", "global_prompt_policy_source")},
    }
    return ReprocessJobBuilder(id_fn=lambda: job_id).build_reprocess_job(
        [matrix["assets"]["input"]["path"]], ["img2img"], config=config, output_dir=str(output_dir),
        prompt=settings["prompt"], negative_prompt=settings["negative_prompt"], model=settings["checkpoint"], pack_name=job_id,
    )


def verify_case_assets(matrix: dict[str, Any], letter: str) -> dict[str, Any]:
    """Hash the assets this case needs against the frozen identities (raises on any change)."""

    from tools.qualification.img_forge_100.provenance import verify_assets

    return verify_assets({name: matrix["assets"][name] for name in _CASE_ASSETS[letter]})


def _frozen_policy(settings: dict[str, Any], **pipeline: bool) -> dict[str, Any]:
    """The production global-prompt policy with application disabled: frozen text, source ``frozen_njr``."""

    flags = {"img2img_enabled": False, "adetailer_enabled": False, "upscale_enabled": False, **pipeline}
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy

    return apply_global_prompt_policy(
        {"pipeline": flags},
        positive_enabled=False,
        negative_enabled=False,
        positive_text=settings.get("global_positive_prompt", ""),
        negative_text=settings.get("global_negative_prompt", ""),
    )


def freeze_njr(settings: dict[str, Any], backend: str, *, job_id: str, output_dir: Path, case: str = "A") -> Any:
    """Immutable NJR for the frozen txt2img intent (A); B adds the frozen LoRA token, D the frozen chain."""

    from src.pipeline.cli_njr_builder import build_cli_njr

    chain = case == "D"
    policy = _frozen_policy(settings, adetailer_enabled=chain, upscale_enabled=chain)
    section = {
        "model": settings["checkpoint"],
        "vae": settings["vae"],
        "steps": settings["steps"],
        "cfg_scale": settings["cfg_scale"],
        "sampler_name": settings["sampler_name"],
        "scheduler": settings["scheduler"],
        "seed": settings["seed"],
        "width": settings["width"],
        "height": settings["height"],
        "clip_skip": settings["clip_skip"],
        "negative_prompt": settings["negative_prompt"],
        "batch_size": 1,
        "n_iter": 1,
        "enable_hr": False,
        "prompt_optimizer": {"enabled": False},
        **{key: policy[key] for key in ("global_positive_prompt", "global_negative_prompt", "global_prompt_policy_source")},
    }
    config: dict[str, Any] = {
        "txt2img": section,
        "pipeline": policy["pipeline"],
        "backend_options": {"image": {"backend_id": backend}},
    }
    if chain:
        config["adetailer"], config["upscale"] = dict(settings["adetailer"]), dict(settings["upscale"])
    lora = f" <lora:{settings['lora_name']}:{settings['lora_strength']}>" if case == "B" else ""
    njr = build_cli_njr(prompt=settings["prompt"] + lora, config=config, batch_size=1, run_name=job_id)
    return replace(njr, output_plan=replace(njr.output_plan, base_output_dir=str(output_dir)))


# Where the builder records job identity and the evidence location. Everything else is intent.
_IDENTITY_PATHS = (
    ("job_id",),
    ("output_plan",),
    ("source", "display_name"),
    ("provenance", "metadata", "run_name"),
    ("workload", "metadata", "run_name"),
    ("workload", "intent_config", "requested_job_label"),
)


def intent_digest(njr: Any) -> str:
    """Digest of the execution intent: job identity and evidence location are not intent."""

    data = njr.to_dict()
    for path in _IDENTITY_PATHS:
        node = data
        for key in path[:-1]:
            node = node.get(key) or {}
        node.pop(path[-1], None)
    return digest(data)


# --- The canonical stack (same wiring as tests/helpers/njr_queue_harness.py) ----------------------


def build_stack(state_dir: Path, output_dir: Path, backend: str, endpoint: str, client: Any = None) -> SimpleNamespace:
    from src.controller.job_service import JobService
    from src.controller.pipeline_controller import PipelineController
    from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from src.queue.single_node_runner import SingleNodeJobRunner
    from src.utils import StructuredLogger

    client = client or DefaultImageRuntimePorts(runtime_identity=backend).create_client(base_url=endpoint)
    state_dir.mkdir(parents=True, exist_ok=True)
    repository = JobRepository(state_dir / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    worker = SingleNodeJobRunner(queue, run_callable=None, poll_interval=0.05)
    service = JobService(queue, runner=worker, history_store=repository)
    runner = PipelineRunner(api_client=client, structured_logger=StructuredLogger(), runs_base_dir=str(output_dir))
    worker.run_callable = PipelineController(pipeline_runner=runner, job_service=service)._run_job
    service.auto_run_enabled = True
    return SimpleNamespace(service=service, repository=repository, client=client)


# --- Runtime: lifecycle belongs to WebUIProcessManager; this only starts, observes and stops ------


class ManagedWebUIRuntime:
    """One WebUI-family runtime launched and owned by StableNew's single WebUIProcessManager."""

    def __init__(self, profile: dict[str, Any], backend: str) -> None:
        from tools.qualification.img_forge_100.preflight import explicit_endpoint

        self.backend = backend
        self.profile = profile
        self.endpoint = explicit_endpoint(profile["endpoint"], backend)
        self.manager: Any = None
        self._lock: Any = None

    def start(self) -> dict[str, Any]:
        from src.api.healthcheck import wait_for_webui_ready
        from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager
        from src.utils.single_instance import SingleInstanceLock

        self._lock = SingleInstanceLock()
        if not self._lock.acquire():
            raise RuntimeError("Another StableNew instance holds the application lock; nothing was started")
        timeout = float(self.profile.get("startup_timeout_seconds", 180))
        self.manager = WebUIProcessManager(
            WebUIProcessConfig(
                command=list(self.profile["command"]),
                working_dir=self.profile.get("working_dir"),
                env_overrides=self.profile.get("env_overrides"),
                startup_timeout_seconds=timeout,
                base_url=self.endpoint,
                runtime_identity=self.backend,
            )
        )
        began = time.monotonic()
        self.manager.start()  # refuses an occupied endpoint; never adopts or kills an external process
        if not wait_for_webui_ready(self.endpoint, timeout=timeout, poll_interval=1.0):
            raise RuntimeError("The managed runtime did not become ready")
        return {**self.observe(), "ready_seconds": round(time.monotonic() - began, 1)}

    def observe(self) -> dict[str, Any]:
        """Authoritative manager facts plus the inspector's view; recorded, never used to gate."""

        import psutil

        from src.utils.process_inspector_v2 import collect_process_risk_snapshot

        manager = self.manager
        tree: list[dict[str, Any]] = []
        if manager.pid and psutil.pid_exists(manager.pid):
            root = psutil.Process(manager.pid)
            tree = [p.as_dict(attrs=["pid", "ppid", "name", "cmdline"]) for p in (root, *root.children(recursive=True))]
        port = int(self.endpoint.rsplit(":", 1)[1])
        listeners = [c.pid for c in psutil.net_connections(kind="tcp") if c.status == "LISTEN" and c.laddr.port == port]
        return {
            "manager": manager.get_status(),
            "owns_process": manager.owns_process,
            "root_pid": manager.pid,
            "owned_tree": tree,
            "listening_pids": listeners,
            "endpoint": self.endpoint,
            "process_risk": collect_process_risk_snapshot(),
        }

    def stop(self) -> dict[str, Any]:
        import psutil

        pids = [p["pid"] for p in self.observe()["owned_tree"]] if self.manager and self.manager.owns_process else []
        if self.manager:
            self.manager.stop()
        if self._lock:
            self._lock.release()
        port = int(self.endpoint.rsplit(":", 1)[1])
        return {
            "surviving_pids": [pid for pid in pids if psutil.pid_exists(pid)],
            "listening_pids": [c.pid for c in psutil.net_connections(kind="tcp") if c.status == "LISTEN" and c.laddr.port == port],
        }


class InjectedRuntime:
    """No process at all: for deterministic proofs whose HTTP is a fake."""

    def start(self) -> dict[str, Any]:
        return {"runtime": "injected", "owns_process": False}

    def stop(self) -> dict[str, Any]:
        return {"surviving_pids": [], "listening_pids": []}


# --- Run: freeze, submit, observe, report -----------------------------------------------------------


def _await_terminal(repository: Any, job_id: str, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = repository.get_job(job_id)
        if getattr(getattr(entry, "status", None), "value", "") in _TERMINAL:
            return entry
        time.sleep(0.2)
    raise AmbiguousDispatch(f"Job {job_id} did not reach a terminal state in {timeout}s; do not replay")


def _artifacts(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    from src.pipeline.result_contract_v26 import collect_canonical_artifacts

    found = []
    for artifact in collect_canonical_artifacts(result or {}):
        path = Path(str(artifact.get("primary_path") or ""))
        if path.is_file():
            found.append({"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "manifest": artifact.get("manifest_path")})
    return found


def _write_new(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:  # never overwrite historical evidence
        json.dump(payload, handle, indent=2, default=str)


def run(args: argparse.Namespace, runtime: Any, *, client: Any = None, sampler: Any = None) -> int:
    reports = Path(args.reports_dir).resolve()  # evidence only: the working directory is never changed
    if reports.exists() and any(reports.iterdir()):
        raise FileExistsError(f"{reports} already holds evidence; choose a new --reports-dir")
    reports.mkdir(parents=True, exist_ok=True)
    letter = getattr(args, "case", "A")
    matrix: dict[str, Any] | None = None
    if letter == "A":
        settings = load_pair_a(Path(args.intent), args.backend)
        job_id = args.job_id or f"forge100-baseline-{args.backend}-{int(time.time())}"
        njr = freeze_njr(settings, args.backend, job_id=job_id, output_dir=reports / "output")
    else:
        if not getattr(args, "matrix", None):
            raise ValueError(f"--matrix (the authoritative frozen matrix) is required for case {letter}")
        matrix, case = load_frozen_case(Path(args.matrix), letter, args.backend, Path(args.intent))
        job_id = args.job_id or f"forge100-{letter}-{args.backend}-{int(time.time())}"
        njr = freeze_case_njr(matrix, case, job_id=job_id, output_dir=reports / "output")
    intent_sha = intent_digest(njr)
    report: dict[str, Any] = {"job_id": job_id, "case": letter, "backend": args.backend, "intent_sha256": intent_sha, "cwd": str(Path.cwd()), "reports_dir": str(reports), "njr": njr.to_dict()}
    _write_new(reports / "intent.json", report)
    if args.dry:
        print(json.dumps({"dry": True, "job_id": job_id, "intent_sha256": intent_sha, "reports_dir": str(reports)}))
        return EXIT_DRY
    if args.approved_intent_sha256 != intent_sha:
        raise PermissionError(f"Physical execution requires the owner's approved intent digest {intent_sha}")

    code, stack, submitted = EXIT_NOT_SUBMITTED, None, False
    try:
        if matrix is not None:
            # Before any runtime starts: the frozen assets are exactly the approved ones (and the source stays so).
            report["assets_verified"] = verify_case_assets(matrix, letter)
        report["runtime_start"] = runtime.start()
        start = report["runtime_start"]
        if start.get("owns_process") and not start["process_risk"]["webui_runtime_tree_count"]:
            # The manager owns a tree the production inspector cannot see: a production observation
            # defect to report, not a reason to add a second ownership heuristic here.
            report["classification"] = "PRODUCTION_PROCESS_OBSERVATION_DEFECT"
            return code
        stack = build_stack(reports / "state", reports / "output", args.backend, getattr(args, "endpoint", ""), client=client)
        from src.controller.submission_policy_v26 import SubmissionPolicy

        started = time.monotonic()
        with (sampler or nullcontext()) as peaks:
            submitted = True
            stack.service.submit_njrs([njr], SubmissionPolicy(start_when_idle=True))
            entry = _await_terminal(stack.repository, job_id, args.timeout_seconds)
        status, error = entry.status.value, str(entry.error_message or "")
        report["job"] = {
            "status": status,
            "error": error,
            "wall_seconds": round(time.monotonic() - started, 1),
            "result_metadata": (entry.result or {}).get("metadata"),
            "artifacts": _artifacts(entry.result),
            "peaks": peaks.peaks.as_dict() if hasattr(peaks, "peaks") else None,
        }
        if matrix is not None and letter == "C":
            from tools.qualification.img_forge_100.provenance import hash_file

            report["input_sha256_after"] = hash_file(matrix["assets"]["input"]["path"])
        stopped = any(marker in error.lower() for marker in _DEVICE_LOSS)
        code = EXIT_STOPPED if stopped else EXIT_COMPLETED if status == "completed" else EXIT_FAILED
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
        report["exit_code"] = code
        _write_new(reports / "acceptance.json", report)
    print(json.dumps({"exit_code": code, "job_id": job_id, "intent_sha256": intent_sha, "reports_dir": str(reports)}))
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", required=True, choices=BACKENDS)
    parser.add_argument("--runtime-profile", type=Path, help="JSON launch profile: command, working_dir, env_overrides, endpoint")
    parser.add_argument("--reports-dir", type=Path, default=None, help="where evidence is written (default: a fresh reports/img_forge_100_acceptance/<backend>-<time>); never changes the working directory")
    parser.add_argument("--intent", type=Path, default=DEFAULT_INTENT)
    parser.add_argument("--case", choices=CASES, default="A", help="frozen pair; B/C/D also require --matrix")
    parser.add_argument("--matrix", type=Path, default=None, help="authoritative frozen matrix.json (assets and cases) for B/C/D")
    parser.add_argument("--approved-intent-sha256", default="")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--dry", action="store_true", help="freeze and print the intent; start and submit nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.reports_dir = args.reports_dir or REPO_ROOT / "reports" / "img_forge_100_acceptance" / f"{args.backend}-{int(time.time())}"
    if args.dry:
        return run(args, InjectedRuntime())
    if args.runtime_profile is None:
        raise SystemExit("--runtime-profile is required for physical execution")
    profile = json.loads(args.runtime_profile.read_text(encoding="utf-8"))
    runtime = ManagedWebUIRuntime(profile, args.backend)
    args.endpoint = runtime.endpoint
    from tools.qualification.vid110.monitor import ResourceSampler

    return run(args, runtime, sampler=ResourceSampler(log_path=Path(args.reports_dir).resolve() / "telemetry.csv"))


if __name__ == "__main__":
    sys.exit(main())
