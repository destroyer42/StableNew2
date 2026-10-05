"""PR-IMG-FORGE-120 physical acceptance driver: ONE canonical still-image job on the DEFAULT-selected managed Forge.

A thin observer around production authority, in the shape of ``img_forge_100_acceptance``, with one difference that is
the whole point: **it injects nothing about backend selection**. There is no ``--backend``, no runtime-identity or
backend-id override, no launch-profile file and no endpoint argument. The operator's real configuration is read as is
(it must not carry an explicit ``webui_runtime_identity`` or ``forge_runtime_profile_path``), and everything that makes
the job a Forge job is produced by production defaults:

* the NJR is compiled by the production ``build_cli_njr`` and acquires ``backend_options.image.backend_id`` from the
  configured new-work default (``forge_webui``);
* the process configuration comes from the production ``build_default_webui_process_config`` (the shared managed-Forge
  launch-profile authority) and the runtime is started and stopped ONLY through ``WebUIProcessManager``;
* the client comes from ``DefaultImageRuntimePorts()`` with its configured identity and endpoint;
* the job goes ``JobService.submit_njrs -> SQLite -> SingleNodeJobRunner -> PipelineController -> PipelineRunner.run_njr``
  and the runtime identity guard classifies the connected endpoint before dispatch.

Nothing here retries, replays, adopts or kills a process, writes production settings, or builds a second compiler,
queue, runner or process manager. One job per invocation; ``--dry`` freezes and prints the intent digest and the
effective configuration without starting anything, and physical execution needs that digest.

    python -m tools.acceptance.img_forge_120_default_acceptance --reports-dir <new evidence dir> \
        --approved-intent-sha256 <digest>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any

from tools.acceptance.img_forge_100_acceptance import (
    _DEVICE_LOSS,
    DEFAULT_INTENT,
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
    _frozen_policy,
    _write_new,
    intent_digest,
    load_pair_a,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_BACKEND = "forge_webui"


# --- Effective configuration: what the operator has, with nothing injected ------------------------------------------


def effective_configuration() -> dict[str, Any]:
    """The real configuration and what it resolves to; raises if the harness would be selecting Forge for the operator."""

    from src.api.webui_runtime_identity import (
        explicit_webui_base_url,
        load_backend_settings,
        resolve_configured_webui_runtime_identity,
        resolve_effective_webui_base_url,
    )
    from src.utils.config import ConfigManager

    manager = ConfigManager()
    stored = dict(manager._load_settings())
    settings = load_backend_settings(manager)
    evidence = {
        "settings_path": str(manager._settings_path.resolve()),
        "stored_has_webui_runtime_identity": "webui_runtime_identity" in stored,
        "stored_forge_runtime_profile_path": stored.get("forge_runtime_profile_path", ""),
        "stored_webui_base_url": stored.get("webui_base_url"),
        "stored_webui_workdir": stored.get("webui_workdir"),
        "env_STABLENEW_WEBUI_RUNTIME_IDENTITY": os.environ.get("STABLENEW_WEBUI_RUNTIME_IDENTITY"),
        "env_STABLENEW_WEBUI_BASE_URL": os.environ.get("STABLENEW_WEBUI_BASE_URL"),
        "effective_identity": resolve_configured_webui_runtime_identity(settings),
        "explicit_base_url_in_stored_settings": explicit_webui_base_url(stored),  # None: nothing but the legacy flat default
        "effective_base_url": resolve_effective_webui_base_url(settings),
    }
    problems = []
    if evidence["stored_has_webui_runtime_identity"] or evidence["env_STABLENEW_WEBUI_RUNTIME_IDENTITY"]:
        problems.append("an explicit webui_runtime_identity is configured; this acceptance proves the DEFAULT selection")
    if str(evidence["stored_forge_runtime_profile_path"] or "").strip():
        problems.append("forge_runtime_profile_path is set; this acceptance proves the default managed profile")
    if evidence["effective_identity"] != EXPECTED_BACKEND:
        problems.append(f"the effective identity is {evidence['effective_identity']}, not the default {EXPECTED_BACKEND}")
    if problems:
        raise PermissionError("; ".join(problems))
    return evidence


# --- Freeze: the frozen SDXL txt2img intent through the production CLI builder, with NO backend options -----------


def freeze_default_njr(settings: dict[str, Any], *, job_id: str, output_dir: Path) -> Any:
    """The frozen Pair-A txt2img intent. Unlike the qualification drivers this never supplies ``backend_options``."""

    from src.pipeline.cli_njr_builder import build_cli_njr

    policy = _frozen_policy(settings)
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
    config: dict[str, Any] = {"txt2img": section, "pipeline": policy["pipeline"]}  # <- no "backend_options"
    assert "backend_options" not in config
    njr = build_cli_njr(prompt=settings["prompt"], config=config, batch_size=1, run_name=job_id)
    return replace(njr, output_plan=replace(njr.output_plan, base_output_dir=str(output_dir)))


# --- Runtime: the production default process configuration, started only through WebUIProcessManager -----------


class DefaultManagedRuntime(ManagedWebUIRuntime):
    """The managed Forge runtime exactly as ``build_default_webui_process_config`` configures it."""

    def __init__(self) -> None:
        from src.api.webui_process_manager import build_default_webui_process_config

        config = build_default_webui_process_config()
        if config is None or config.runtime_identity != EXPECTED_BACKEND:
            raise RuntimeError(f"The default process configuration is not managed Forge: {config!r}")
        self.config = config
        self.backend = config.runtime_identity
        self.endpoint = str(config.base_url).rstrip("/")
        self.profile = {"command": list(config.command), "working_dir": config.working_dir}
        self.manager: Any = None
        self._lock: Any = None

    def contract_evidence(self) -> dict[str, Any]:
        """Whether the default configuration IS the shared launch-profile authority's output (and nothing tuned)."""

        from src.utils import managed_forge_runtime as authority

        manifest = authority.load_manifest()
        command = list(self.config.command)
        home = Path(command[command.index(manifest["launch_policy"]["model_reference_flag"]) + 1])
        install = authority.managed_install_dir(manifest)
        expected = authority.build_launch_profile(
            manifest, install_dir=install, model_home=home, port=authority.port_from_endpoint(self.endpoint)
        )
        return {
            "install_dir": str(install),
            "model_reference_home": str(home),
            "command": command,
            "command_equals_shared_authority": command == expected["command"],
            "working_dir_equals_shared_authority": self.config.working_dir == expected["working_dir"],
            "env_overrides_equal_shared_authority": dict(self.config.env_overrides or {}) == expected["env_overrides"],
            "contract_problems": authority.check_launch_command(command, manifest),
            "a1111_launch_profile_commands": self.config.launch_profile_commands,
            "contains_a1111_launcher": any("webui-user" in part or "webui.bat" in part for part in command),
        }

    def start(self) -> dict[str, Any]:
        from src.api.healthcheck import wait_for_webui_ready
        from src.api.webui_process_manager import WebUIProcessManager
        from src.utils.single_instance import SingleInstanceLock

        self._lock = SingleInstanceLock()
        if not self._lock.acquire():
            raise RuntimeError("Another StableNew instance holds the application lock; nothing was started")
        timeout = float(self.config.startup_timeout_seconds)
        self.manager = WebUIProcessManager(self.config)
        began = time.monotonic()
        self.manager.start()  # refuses an occupied endpoint; never adopts or kills an external process
        if not wait_for_webui_ready(self.endpoint, timeout=timeout, poll_interval=1.0):
            raise RuntimeError("The managed runtime did not become ready")
        return {**self.observe(), "ready_seconds": round(time.monotonic() - began, 1)}


# --- The canonical stack, with the DEFAULT ports (no identity, no endpoint argument) ---------------------------------


def build_default_stack(state_dir: Path, output_dir: Path) -> Any:
    from types import SimpleNamespace

    from src.controller.job_service import JobService
    from src.controller.pipeline_controller import PipelineController
    from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from src.queue.single_node_runner import SingleNodeJobRunner
    from src.utils import StructuredLogger

    ports = DefaultImageRuntimePorts()  # configured identity; nothing passed in
    client = ports.create_client(base_url=ports.base_url())
    state_dir.mkdir(parents=True, exist_ok=True)
    repository = JobRepository(state_dir / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    worker = SingleNodeJobRunner(queue, run_callable=None, poll_interval=0.05)
    service = JobService(queue, runner=worker, history_store=repository)
    runner = PipelineRunner(api_client=client, structured_logger=StructuredLogger(), runs_base_dir=str(output_dir))
    worker.run_callable = PipelineController(pipeline_runner=runner, job_service=service)._run_job
    service.auto_run_enabled = True
    return SimpleNamespace(service=service, repository=repository, client=client, ports=ports)


def _find_backend_ids(node: Any, found: list[str] | None = None) -> list[str]:
    """Every ``backend_options.image.backend_id`` anywhere in a persisted snapshot (shape-agnostic)."""

    found = [] if found is None else found
    if isinstance(node, dict):
        options = node.get("backend_options")
        if isinstance(options, dict) and isinstance(options.get("image"), dict) and options["image"].get("backend_id"):
            found.append(str(options["image"]["backend_id"]))
        for value in node.values():
            _find_backend_ids(value, found)
    elif isinstance(node, list):
        for value in node:
            _find_backend_ids(value, found)
    return found


def run(args: argparse.Namespace, runtime: Any, *, sampler: Any = None, dry_runtime: bool = False) -> int:
    reports = Path(args.reports_dir).resolve()  # evidence only: the working directory is never changed
    if reports.exists() and any(reports.iterdir()):
        raise FileExistsError(f"{reports} already holds evidence; choose a new --reports-dir")
    reports.mkdir(parents=True, exist_ok=True)
    configuration = effective_configuration()
    settings = load_pair_a(Path(args.intent), EXPECTED_BACKEND)
    job_id = args.job_id or f"forge120-default-{int(time.time())}"
    njr = freeze_default_njr(settings, job_id=job_id, output_dir=reports / "output")
    stamped = njr.backend_options["image"]["backend_id"]
    intent_sha = intent_digest(njr)
    report: dict[str, Any] = {
        "job_id": job_id,
        "intent_sha256": intent_sha,
        "cwd": str(Path.cwd()),
        "reports_dir": str(reports),
        "effective_configuration": configuration,
        "harness_supplied_backend_options": False,  # freeze_default_njr asserts it never passes any
        "njr_backend_id_stamped_by_default": stamped,
        "njr": njr.to_dict(),
    }
    _write_new(reports / "intent.json", report)
    if stamped != EXPECTED_BACKEND:
        raise AssertionError(f"New work compiled to {stamped}, not the default {EXPECTED_BACKEND}")
    if args.dry:
        print(json.dumps({"dry": True, "job_id": job_id, "intent_sha256": intent_sha, "backend_stamped": stamped,
                          "effective_identity": configuration["effective_identity"],
                          "effective_base_url": configuration["effective_base_url"], "reports_dir": str(reports)}))
        return EXIT_DRY
    if args.approved_intent_sha256 != intent_sha:
        raise PermissionError(f"Physical execution requires the approved intent digest {intent_sha}")

    code, stack, submitted = EXIT_NOT_SUBMITTED, None, False
    try:
        report["managed_contract"] = runtime.contract_evidence()
        report["runtime_start"] = runtime.start()
        start = report["runtime_start"]
        if start.get("owns_process") and not start["process_risk"]["webui_runtime_tree_count"]:
            report["classification"] = "PRODUCTION_PROCESS_OBSERVATION_DEFECT"
            return code
        stack = build_default_stack(reports / "state", reports / "output")
        from src.api.webui_runtime_identity import classify_client_runtime

        observed = classify_client_runtime(stack.client)
        report["default_client"] = {
            "type": type(stack.client).__name__,
            "base_url": stack.client.base_url,
            "runtime_identity_observed": observed.identity,
            "evidence": dict(observed.evidence),
            "client_endpoint_equals_process_endpoint": str(stack.client.base_url).rstrip("/") == runtime.endpoint,
        }
        if not observed.is_forge:
            report["classification"] = "RUNTIME_IDENTITY_NOT_FORGE"
            return EXIT_STOPPED
        from src.controller.submission_policy_v26 import SubmissionPolicy

        started = time.monotonic()
        with (sampler or nullcontext()) as peaks:
            submitted = True
            stack.service.submit_njrs([njr], SubmissionPolicy(start_when_idle=True))
            entry = _await_terminal(stack.repository, job_id, args.timeout_seconds)
        status, error = entry.status.value, str(entry.error_message or "")
        result_metadata = (entry.result or {}).get("metadata") or {}
        report["job"] = {
            "status": status,
            "error": error,
            "wall_seconds": round(time.monotonic() - started, 1),
            "result_metadata": result_metadata,
            "artifacts": _artifacts(entry.result),
            "peaks": peaks.peaks.as_dict() if hasattr(peaks, "peaks") else None,
        }
        report["identity_evidence"] = {
            "sqlite_njr_snapshot_backend_ids": _find_backend_ids(entry.snapshot),
            "history_result_image_backend_id": result_metadata.get("image_backend_id"),
            "history_result_backend_ids": _find_backend_ids(entry.result),
        }
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
    parser.add_argument("--reports-dir", type=Path, required=True, help="a NEW evidence directory; the working directory never changes")
    parser.add_argument("--intent", type=Path, default=DEFAULT_INTENT)
    parser.add_argument("--approved-intent-sha256", default="")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--dry", action="store_true", help="freeze and print the intent and effective configuration; start nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry:
        return run(args, InjectedRuntime())
    runtime = DefaultManagedRuntime()
    from tools.qualification.vid110.monitor import ResourceSampler

    return run(args, runtime, sampler=ResourceSampler(log_path=Path(args.reports_dir).resolve() / "telemetry.csv"))


if __name__ == "__main__":
    sys.exit(main())
