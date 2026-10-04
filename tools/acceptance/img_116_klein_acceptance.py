"""PR-IMG-116 physical acceptance driver: FLUX.2 Klein 4B FP8 production smokes (two jobs, no retry).

A thin observer around production authority, in the same shape as ``img_forge_100_acceptance``:

* Smoke A (``--smoke A``): the operator intent (checkpoint, size, seed, prompt) is compiled by the
  production ``build_cli_njr`` (which applies the Klein compile policy and stamps the model profile) and
  submitted through ``JobService.submit_njrs -> SQLite -> SingleNodeJobRunner -> PipelineRunner.run_njr ->
  forge_webui``.
* Smoke B (``--smoke B --source-artifact <smoke A png>``): the production ``AppController.
  on_reprocess_images_with_prompt_delta`` (the Review tab's handler) builds the edit NJR through the
  production ``ReprocessJobBuilder`` with the explicit Klein edit marker the Review checkbox sets, and
  submits it to the same JobService.

The managed Forge runtime is started and stopped ONLY through ``WebUIProcessManager``. Nothing here retries,
replays, adopts or kills a process, changes production settings, or builds a second compiler/queue/runner.
The configured backend identity is overridden *in memory for this process only* (the production settings file is
never written), exactly as an operator who selected ``forge_webui`` would see it.

One job per invocation. ``--dry`` freezes and prints the intent digest; physical execution needs that digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
    intent_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = "forge_webui"
SEED_A = 424242
EDIT_INSTRUCTION = (
    "keep the same person, face, pose, framing, hands, motorcycle, lighting and background; "
    "change only the jacket to deep red leather"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_installed_assets(data_dir: Path) -> dict[str, Any]:
    """Size + SHA-256 of the three installed files against the immutable profile (raises on any mismatch)."""

    from src.image_backends.forge_klein_profile import latest_klein_profile

    verified: dict[str, Any] = {}
    for asset in latest_klein_profile().assets:
        path = Path(data_dir) / "models" / asset.models_subdir / asset.filename
        if not path.is_file() or path.stat().st_size != asset.size:
            raise ValueError(f"{asset.role}: {path} is missing or has the wrong size")
        actual = _sha256(path)
        if actual != asset.sha256:
            raise ValueError(f"{asset.role}: {path} hashes to {actual}, expected {asset.sha256}")
        verified[asset.role] = {"path": str(path), "bytes": asset.size, "sha256": actual}
    return verified


@contextmanager
def forge_selected_in_memory(runtime_profile: Path | str = ""):
    """The operator selecting ``forge_webui`` (and its managed runtime profile): an in-process view of settings."""

    from unittest.mock import patch

    from src.utils.config import ConfigManager

    original = ConfigManager.load_settings

    def load_settings(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            **original(self, *args, **kwargs),
            "webui_runtime_identity": BACKEND,
            "forge_runtime_profile_path": str(runtime_profile or ""),
        }

    with patch.object(ConfigManager, "load_settings", load_settings):
        yield


# --- Freeze -------------------------------------------------------------------------------------------


def freeze_smoke_a(*, job_id: str, output_dir: Path) -> Any:
    from dataclasses import replace

    from src.pipeline.cli_njr_builder import build_cli_njr
    from tools.qualification.img115.spec import CASES

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
    njr = build_cli_njr(prompt=CASES["A"]["prompt"], config=config, batch_size=1, run_name=job_id)
    return replace(njr, output_plan=replace(njr.output_plan, base_output_dir=str(output_dir)))


class _CapturingService:
    """Records the NJRs the production Review handler submits; optionally forwards to the real service."""

    def __init__(self, real: Any = None, approved_digest: str = "") -> None:
        self.real, self.approved, self.captured = real, approved_digest, []

    def submit_njrs(self, njrs: list[Any], policy: Any) -> list[str]:
        self.captured.extend(njrs)
        if self.real is None:
            return [n.job_id for n in njrs]
        if len(njrs) != 1:
            raise PermissionError(f"The Klein edit smoke submits exactly one NJR; got {len(njrs)}")
        if intent_digest(njrs[0]) != self.approved:
            raise PermissionError("The NJR built by the Review handler does not match the approved intent digest")
        return self.real.submit_njrs(njrs, policy)


def run_review_handler(source: Path, service: Any, output_dir: Path) -> list[Any]:
    """The production Review-tab handler, on a shell controller (no GUI), with the explicit Klein marker."""

    from unittest.mock import Mock, patch

    from src.controller.app_controller import AppController
    from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter

    with patch("src.controller.app_controller.AppController.__init__", return_value=None):
        controller = AppController.__new__(AppController)
    controller.job_service = service
    controller._append_log = Mock()
    controller._api_client = Mock()
    controller.cancel_token = None
    controller._build_reprocess_config = lambda stages: {}  # ignored by the frozen Klein edit config
    marked = ReviewWorkflowAdapter.with_klein_edit_request(None, [source])
    controller.on_reprocess_images_with_prompt_delta(
        image_paths=[str(source)],
        stages=["img2img"],
        prompt_delta=EDIT_INSTRUCTION,
        negative_prompt_delta="",
        prompt_mode="replace",
        negative_prompt_mode="replace",
        batch_size=1,
        source_metadata_by_image=marked,
    )
    return list(service.captured)


# --- Run ------------------------------------------------------------------------------------------------


def _fault_events(start: datetime) -> list[dict[str, Any]]:
    from tools.qualification.img110r.orchestrate import fault_events_since

    return fault_events_since(start)


def run(args: argparse.Namespace, runtime: Any, *, sampler: Any = None, client: Any = None) -> int:
    import psutil

    reports = Path(args.reports_dir).resolve()
    if reports.exists() and any(reports.iterdir()):
        raise FileExistsError(f"{reports} already holds evidence; choose a new --reports-dir")
    reports.mkdir(parents=True, exist_ok=True)
    smoke = args.smoke
    job_id = args.job_id or f"img116-klein-{smoke.lower()}-{int(time.time())}"
    output_dir = reports / "output"
    source: Path | None = None
    source_sha_before = ""
    with forge_selected_in_memory(getattr(args, "runtime_profile", "") or ""):
        if smoke == "A":
            njr = freeze_smoke_a(job_id=job_id, output_dir=output_dir)
        else:
            source = Path(args.source_artifact).resolve()
            source_sha_before = _sha256(source)
            capture = _CapturingService()
            (njr,) = run_review_handler(source, capture, output_dir)
        intent_sha = intent_digest(njr)
        report: dict[str, Any] = {
            "smoke": smoke, "job_id": njr.job_id, "intent_sha256": intent_sha, "reports_dir": str(reports),
            "njr": njr.to_dict(), "configured_backend_override": "in-memory for this process only",
        }
        _write_new(reports / "intent.json", report)
        if args.dry:
            print(json.dumps({"dry": True, "job_id": njr.job_id, "intent_sha256": intent_sha, "reports_dir": str(reports)}))
            return EXIT_DRY
        if args.approved_intent_sha256 != intent_sha:
            raise PermissionError(f"Physical execution requires the approved intent digest {intent_sha}")

        code, stack, submitted = EXIT_NOT_SUBMITTED, None, False
        began_wall = datetime.now()
        try:
            report["assets_verified"] = verify_installed_assets(Path(args.forge_data_dir))
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
            from src.controller.submission_policy_v26 import SubmissionPolicy

            report["pre_dispatch_memory"] = {
                "total_gb": round(psutil.virtual_memory().total / 1e9, 2),
                "available_gb": round(psutil.virtual_memory().available / 1e9, 2),
            }
            from tools.qualification.img115.run import _TreeSampler

            started = time.monotonic()
            with (sampler or _NullSampler()) as peaks, _TreeSampler(_OwnedTree(runtime), reports / "tree.csv") as tree:
                submitted = True
                if smoke == "A":
                    stack.service.submit_njrs([njr], SubmissionPolicy(start_when_idle=True))
                else:
                    assert source is not None
                    guarded = _CapturingService(real=stack.service, approved_digest=intent_sha)
                    run_review_handler(source, guarded, output_dir)
                    njr = guarded.captured[0]
                    report["submitted_job_id"] = njr.job_id
                entry = _await_terminal(stack.repository, njr.job_id, args.timeout_seconds)
            status, error = entry.status.value, str(entry.error_message or "")
            variants = ((entry.result or {}).get("variants") or [{}])
            report["job"] = {
                "status": status,
                "error": error,
                "wall_seconds": round(time.monotonic() - started, 1),
                "artifacts": _artifacts(entry.result),
                "klein_evidence": (variants[0].get("image_backend_metadata") or {}).get("klein_profile"),
                "image_backend_id": variants[0].get("image_backend_id"),
                "peaks": peaks.peaks.as_dict() if hasattr(peaks, "peaks") else None,
                "forge_tree_memory": tree.peaks(),
                "snapshot_backend_options": ((entry.snapshot or {}).get("normalized_job", {}).get("workload", {}) or {}).get("backend_options"),
            }
            if source is not None:
                report["source_sha256_before"], report["source_sha256_after"] = source_sha_before, _sha256(source)
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
            report["fault_events"] = _fault_events(began_wall)
            report["exit_code"] = code
            _write_new(reports / "acceptance.json", report)
    print(json.dumps({"exit_code": code, "job_id": njr.job_id, "intent_sha256": intent_sha, "reports_dir": str(reports)}))
    return code


class _OwnedTree:
    """Adapter so the IMG-115 tree sampler can observe the manager-owned Forge process tree (read-only)."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def process_tree_pids(self) -> list[int]:
        import psutil

        pid = getattr(getattr(self._runtime, "manager", None), "pid", None)
        if not pid or not psutil.pid_exists(pid):
            return []
        root = psutil.Process(pid)
        return [root.pid, *(child.pid for child in root.children(recursive=True))]


class _NullSampler:
    def __enter__(self) -> SimpleNamespace:
        return SimpleNamespace()

    def __exit__(self, *_exc: object) -> None:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", required=True, choices=("A", "B"))
    parser.add_argument("--runtime-profile", type=Path, help="managed Forge launch profile JSON (verify_managed_forge.py --print-profile)")
    parser.add_argument("--forge-data-dir", type=Path, required=True, help="managed Forge --data-dir (holds models/)")
    parser.add_argument("--source-artifact", type=Path, default=None, help="Smoke B: the Smoke A output image")
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--approved-intent-sha256", default="")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--dry", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke == "B" and args.source_artifact is None:
        raise SystemExit("--source-artifact is required for Smoke B")
    if args.dry:
        return run(args, InjectedRuntime())
    if args.runtime_profile is None:
        raise SystemExit("--runtime-profile is required for physical execution")
    profile = json.loads(args.runtime_profile.read_text(encoding="utf-8"))
    runtime = ManagedWebUIRuntime(profile, BACKEND)
    args.endpoint = runtime.endpoint
    from tools.qualification.vid110.monitor import ResourceSampler

    return run(args, runtime, sampler=ResourceSampler(log_path=Path(args.reports_dir).resolve() / "telemetry.csv"))


if __name__ == "__main__":
    sys.exit(main())
