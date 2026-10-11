"""One operator-authorized Z-Image canary through the existing production queue.

No physical activity is authorized by this module or by a dry-run digest.
Transport recording delegates to the production client; it cannot replay a POST.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P
from src.image_backends.forge_zimage_profile import validate_zimage_njr
from tools.acceptance.img_116_klein_acceptance import _OwnedTree, forge_selected_in_memory
from tools.acceptance.img_forge_100_acceptance import (
    AmbiguousDispatch,
    ManagedWebUIRuntime,
    _artifacts,
    _await_terminal,
    build_stack,
    digest,
)
from tools.qualification.img154.manifest import FrozenIntent

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "http://127.0.0.1:7886"
ACTION = "one_normal_queued_zimage_generation"


def _write_new(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())


def freeze(attempt: str, reports: Path) -> Any:
    from src.pipeline.cli_njr_builder import build_cli_njr

    case = FrozenIntent()
    njr = build_cli_njr(
        prompt=case.prompt, batch_size=1, run_name=attempt,
        config={"txt2img": {"model": P.transformer.filename, "seed": case.seed},
                "backend_options": {"image": {"backend_id": P.backend_id, "model_profile": P.reference()}}},
    )
    njr = replace(njr, job_id=attempt, output_plan=replace(njr.output_plan, base_output_dir=str(reports / "output")))
    validate_zimage_njr(njr)
    return njr


def source_revision() -> dict[str, str]:
    def git(*args: str) -> str:
        return subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), *args],
                              check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    return {"sha": git("rev-parse", "HEAD"), "dirty": git("status", "--porcelain", "--untracked-files=all")}


def authorize(args: argparse.Namespace, packet: dict[str, Any]) -> dict[str, Any]:
    """A current owner-issued record is separate from digest matching. Never synthesize consent."""
    if args.approved_digest != packet["approval_digest"]:
        raise PermissionError("approved digest does not match the exact dry-run packet")
    if not args.owner_authorization:
        raise PermissionError("separate current owner authorization is required")
    record = json.loads(Path(args.owner_authorization).read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise PermissionError("owner authorization must be a JSON object")
    expected = {"owner": "Rob", "action": ACTION, "attempt_id": packet["attempt_id"],
                "approval_digest": packet["approval_digest"], "source_sha": packet["source"]["sha"],
                "reports_dir": packet["reports_dir"]}
    if any(record.get(k) != v for k, v in expected.items()):
        raise PermissionError("owner authorization does not identify this exact acceptance attempt")
    now = datetime.now(UTC)
    issued = datetime.fromisoformat(record["issued_at"])
    expires = datetime.fromisoformat(record["expires_at"])
    if issued.tzinfo is None or expires.tzinfo is None or not issued <= now < expires:
        raise PermissionError("owner authorization is not current")
    return dict(record)


def launch_profile(model_home: Path, reports: Path) -> dict[str, Any]:
    from src.utils.managed_forge_runtime import resolve_default_launch_profile, verify_pinned_launch

    profile = resolve_default_launch_profile(model_home=model_home, base_url=ENDPOINT)
    command = list(profile["command"])
    command[command.index("--data-dir") + 1] = str(reports / "runtime" / "data")
    env = dict(profile["env_overrides"])
    for key, directory in {"HF_HUB_CACHE": "hf", "MPLCONFIGDIR": "matplotlib",
                           "YOLO_CONFIG_DIR": "yolo", "UV_CACHE_DIR": "uv"}.items():
        env[key] = str(reports / "runtime" / directory)
    env["COMMANDLINE_ARGS"] = ""
    profile.update(command=command, env_overrides=env)
    verify_pinned_launch(command, profile["working_dir"], P.forge_revision)
    return profile


def preflight(runtime: Any, model_home: Path, reports: Path) -> dict[str, Any]:
    import psutil

    from src.image_backends.forge_klein_assets import _verify_one
    from src.utils.single_instance import SingleInstanceLock

    expected = launch_profile(model_home, reports)
    if type(runtime) is not ManagedWebUIRuntime or runtime.profile != expected or runtime.backend != P.backend_id:
        raise PermissionError("untrusted runtime: only the established managed acceptance adapter is admitted")
    if SingleInstanceLock.is_gui_running():
        raise PermissionError("another StableNew instance holds the application lock")
    conflicts = [c.pid for c in psutil.net_connections(kind="tcp")
                 if c.status == "LISTEN" and c.laddr.port == 7886]
    if conflicts:
        raise PermissionError(f"qualification port conflicts: {conflicts}")
    from src.utils.process_inspector_v2 import collect_process_risk_snapshot

    process_risk = collect_process_risk_snapshot()
    if process_risk.get("webui_runtime_tree_count"):
        raise PermissionError("a WebUI process tree already exists; no process is adopted or interrupted")
    memory = psutil.virtual_memory()
    if memory.total < P.min_total_ram_bytes:
        raise PermissionError("PR-155 requires at least 32,000,000,000 bytes total physical RAM")
    # Before launch: declared reference files. After launch the production served-file
    # verifier binds catalog paths to the actual owned session, before model selection.
    assets = {asset.role: _verify_one(model_home, asset) for asset in P.assets}
    disk = shutil.disk_usage(reports)
    if disk.free <= 0:
        raise PermissionError("evidence storage has no free space")
    return {"source": source_revision(), "launch": expected, "installed_assets": assets,
            "ram_total_bytes": memory.total, "ram_available_bytes": memory.available,
            "storage_free_bytes": disk.free, "process_risk": process_risk, "lock_observed_free": True}


class RequestEvidence:
    """Record the actual production Session.request boundary, with a durable one-POST fence.

    No HTTP implementation or payload construction lives here. The original method
    handles all transport and production retry policy. A second generation is refused.
    """

    def __init__(self, client: Any, reports: Path) -> None:
        self.client, self.reports = client, reports
        self.original = client._session.request
        self.original_factory = client._build_http_session
        self.dispatched = False
        self.response: dict[str, Any] | None = None
        self.error = ""
        self.blocked = 0
        self.lock = threading.Lock()
        client._session.request = self.request
        client._build_http_session = self.build_session

    def build_session(self) -> Any:
        """Production GET/connect recovery may replace a Session; retain the same fence."""
        session = self.original_factory()
        original = session.request

        def observed(method: str, url: str, **kwargs: Any) -> Any:
            return self.request(method, url, _delegate=original, **kwargs)

        session.request = observed
        return session

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        delegate = kwargs.pop("_delegate", self.original)
        path = urlparse(url).path.rstrip("/")
        generation = method.upper() == "POST" and path in {
            "/sdapi/v1/txt2img", "/sdapi/v1/img2img", "/sdapi/v1/extra-single-image"}
        if not generation:
            return delegate(method, url, **kwargs)
        with self.lock:
            if self.dispatched or path != "/sdapi/v1/txt2img":
                self.blocked += 1
                raise PermissionError("second or unintended generation refused; never replay")
            _write_new(self.reports / "dispatch.json", {"utc": datetime.now(UTC).isoformat(),
                       "method": method, "url": url, "payload": kwargs.get("json")})
            self.dispatched = True
        try:
            response = delegate(method, url, **kwargs)
            self.response = {"utc": datetime.now(UTC).isoformat(), "status": response.status_code,
                             "body": response.json()}
            _write_new(self.reports / "response.json", self.response)
            return response
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            _write_new(self.reports / "dispatch_error.json", {"error": self.error})
            raise


class Observations:
    """Reuse native PR-154B providers as observers, with no monitor or process-control authority."""

    def __init__(self, runtime: Any, reports: Path) -> None:
        from tools.qualification.img154b.sampler import build_native_providers

        self.providers, _ = build_native_providers(_OwnedTree(runtime).process_tree_pids)
        self.path = reports / "telemetry.jsonl"
        self.rows: list[dict[str, Any]] = []
        self.pending: dict[str, Any] = {}
        self.lock, self.done = threading.Lock(), threading.Event()
        self.thread: threading.Thread | None = None
        self.phase = "runtime_startup"

    def sample(self, phase: str) -> dict[str, Any]:
        from concurrent.futures import wait

        from tools.qualification.img154b.sampler import _submit_daemon

        with self.lock:
            row: dict[str, Any] = {"utc": datetime.now(UTC).isoformat(), "mono": time.monotonic(),
                                   "phase": phase, "values": {}, "status": {}, "sources": {}}
            for provider in self.providers:
                if provider.name not in self.pending:
                    self.pending[provider.name] = _submit_daemon(provider.read, "img156-observation")
            wait(list(self.pending.values()), timeout=0.5)
            for provider in self.providers:
                task = self.pending[provider.name]
                if not task.done():
                    row["status"].update(dict.fromkeys(provider.fields, "slow"))
                    continue
                self.pending.pop(provider.name)
                try:
                    reading = task.result()
                    row["values"].update(reading.values)
                    row["status"].update(reading.status)
                    row["sources"][provider.name] = {"source": reading.source, "detail": reading.detail}
                except Exception as exc:  # measurement failure is a gap, never a healthy zero
                    row["status"].update(dict.fromkeys(provider.fields, "error"))
                    row["sources"][provider.name] = {"error": str(exc)}
            row["latency_s"] = time.monotonic() - row["mono"]
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, default=str) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.rows.append(row)
            return row

    def start(self) -> None:
        def loop() -> None:
            while not self.done.wait(1):
                self.sample(self.phase)
        self.thread = threading.Thread(target=loop, daemon=True, name="img156-observer")
        self.thread.start()

    def close(self) -> None:
        self.done.set()
        if self.thread:
            self.thread.join(timeout=2)


def resource_result(rows: list[dict[str, Any]], faults: dict[str, Any]) -> dict[str, Any]:
    metrics = {"forge_tree_private_bytes": max, "forge_tree_working_set_bytes": max,
               "ram_available_bytes": min, "commit_headroom_bytes": min,
               "vram_used_bytes": max, "shared_vram_bytes": max, "gpu_temperature_c": max}
    summary: dict[str, Any] = {}
    gaps: list[str] = []
    for field, reducer in metrics.items():
        valid = [r["values"].get(field) for r in rows if r["status"].get(field) == "ok"
                 and isinstance(r["values"].get(field), (int, float))]
        summary[field] = reducer(valid) if valid else None
        relevant = [r for r in rows if not (field.startswith("forge_tree") and
                    (r["phase"] in {"preflight", "after_cleanup"} or
                     (r["phase"] in {"runtime_startup", "cleanup"} and r["status"].get(field) == "not_applicable")))]
        if not relevant or any(r["status"].get(field) != "ok" for r in relevant):
            gaps.append(field)
    times = [r["mono"] for r in rows]
    if not rows or any(r["status"].get("gpu_device_present") != "ok" for r in rows):
        gaps.append("gpu_device_present")
    for row in rows:
        for source in row.get("sources", {}).values():
            detail = str(source.get("detail", ""))
            if "processes readable" in detail:
                readable, total = detail.split()[0].split("/")
                if readable != total:
                    gaps.append("partial_process_tree")
    intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
    if not intervals or max(intervals) > 2.5:
        gaps.append("sample_intervals")  # observation cadence, not a hardware admission floor
    if not faults.get("complete"):
        gaps.append("windows_fault_events")
    device_loss = any(r["values"].get("gpu_device_present") is False for r in rows)
    if faults.get("events") or faults.get("boot_changed") or device_loss:
        verdict = "FAULT_OBSERVED"
    else:
        verdict = "COVERAGE_INCOMPLETE" if gaps else "OBSERVED_NO_FAULT"
    return {"verdict": verdict, "extrema": summary, "gaps": gaps, "samples": len(rows),
            "intervals_s": intervals, "faults": faults, "device_loss_observed": device_loss}


def fault_snapshot() -> Any:
    from tools.qualification.img154.probes import Clocks, collect_fault_snapshot, run_allow_listed

    return collect_fault_snapshot(Clocks(), run_allow_listed)


def validate_result(entry: Any, repository: Any, njr: Any, reports: Path, wire: RequestEvidence) -> dict[str, Any]:
    """Independent decoding and attribution; success cannot be inferred from terminal status alone."""
    from PIL import Image, ImageStat

    failures: list[str] = []
    artifacts = _artifacts(entry.result)
    try:
        if len(artifacts) != 1 or len(list((reports / "output").rglob("*.png"))) != 1:
            raise ValueError("exactly one canonical output PNG is required")
        artifact = artifacts[0]
        path, manifest_path = Path(artifact["path"]).resolve(), Path(artifact["manifest"]).resolve()
        if not path.is_relative_to(reports / "output") or not manifest_path.is_relative_to(reports / "output"):
            raise ValueError("artifact escaped the isolated output root")
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG" or image.size != (1024, 1024) or not any(ImageStat.Stat(image.convert("RGB")).var):
                raise ValueError("image is invalid, constant or wrong dimensions")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dispatch = json.loads((reports / "dispatch.json").read_text(encoding="utf-8"))["payload"]
        expected = {"prompt": FrozenIntent().prompt, "negative_prompt": "", "seed": 424254,
                    "steps": 9, "sampler_name": "Euler", "scheduler": "Beta", "cfg_scale": 1.0,
                    "distilled_cfg_scale": 9.0, "width": 1024, "height": 1024, "batch_size": 1,
                    "n_iter": 1, "send_images": True, "save_images": False}
        if dispatch != expected or manifest.get("zimage_effective_request") != dispatch:
            raise ValueError("actual request or manifest differs from the frozen 14-field request")
        if manifest.get("requested_seed") != 424254 or manifest.get("actual_seed") != 424254:
            raise ValueError("requested/effective seed is missing or wrong")
        if manifest.get("job_id") != njr.job_id:
            raise ValueError("image job lineage differs")
        profile = manifest["zimage_profile"]
        if profile["model_profile"] != P.reference() or profile["asset_identity"]["forge"]["revision"] != P.forge_revision:
            raise ValueError("result profile or Forge pin differs")
        for asset in P.assets:
            if profile["asset_identity"][asset.role]["sha256"] != asset.sha256:
                raise ValueError("served asset identity differs")
        if not manifest["zimage_selection"]["verified_before_dispatch"] or not wire.response or wire.response["status"] != 200:
            raise ValueError("selection or response evidence incomplete")
        info = wire.response["body"].get("info")
        info = json.loads(info) if isinstance(info, str) else info
        if not isinstance(info, dict) or info.get("seed") != 424254 or info.get("all_seeds") != [424254]:
            raise ValueError("response seed evidence incomplete or wrong")
        from tools.qualification.img154b.request import verify_infotext

        infotexts = info.get("infotexts") or []
        if len(infotexts) != 1 or verify_infotext(infotexts[0])[0]:
            raise ValueError("effective sampling/model/module infotext is missing or wrong")
        _write_new(reports / "validated_manifest.json", manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failures.append(str(exc))
    snapshot = (entry.snapshot or {}).get("normalized_job")
    refs = repository.get_artifact_references(njr.job_id)
    canonical = (entry.status.value == "completed" and snapshot == njr.to_dict()
                 and repository.identities() == {njr.job_id} and bool(refs)
                 and entry.started_at is not None and entry.completed_at is not None and not wire.blocked)
    if artifacts:
        canonical = canonical and all(a["path"] in refs and a["manifest"] in refs for a in artifacts)
    return {"generation": "GENERATION_FAIL" if failures else "GENERATION_PASS",
            "integration": "CANONICAL_PATH_PASS" if canonical and not failures else "CANONICAL_PATH_FAIL",
            "validation_errors": failures, "artifacts": artifacts, "repository_artifact_references": refs,
            "snapshot_digest": digest(snapshot), "status": entry.status.value, "error": entry.error_message}


def cleanup_result(immediate: dict[str, Any]) -> str:
    if "error" in immediate or immediate.get("surviving_pids") or immediate.get("listening_pids"):
        return "CLEANUP_FAILED"
    if {"surviving_pids", "listening_pids"} <= immediate.keys():
        return "CLEANUP_VERIFIED"
    return "CLEANUP_NOT_VERIFIED"


def run(args: argparse.Namespace, *, runtime: Any = None, client: Any = None,
        observer: Any = None, preflight_fn: Any = preflight, faults_fn: Any = fault_snapshot,
        settle_fn: Any = time.sleep) -> int:
    reports = Path(args.reports_dir).resolve()
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 1800:
        raise ValueError("completion wait must be finite, positive and at most 1800 seconds")
    if args.dry:
        reports.mkdir(parents=True, exist_ok=False)  # atomic claim; even empty/partial roots refuse
        attempt = f"img156-{uuid.uuid4().hex}"
        njr = freeze(attempt, reports)
        packet = {"schema": "stablenew.img156.v1", "attempt_id": attempt, "reports_dir": str(reports),
                  "source": source_revision(), "njr": njr.to_dict()}
        packet["approval_digest"] = digest(packet)
        _write_new(reports / "intent.json", packet)
        print(json.dumps({"approval_digest": packet["approval_digest"], "attempt_id": attempt}))
        return 0
    if not reports.is_dir() or {p.name for p in reports.iterdir()} != {"intent.json"}:
        raise PermissionError("incomplete or previously used evidence root")
    packet = json.loads((reports / "intent.json").read_text(encoding="utf-8"))
    from src.pipeline.job_models_v2 import NormalizedJobRecord

    njr = NormalizedJobRecord.from_dict(packet["njr"])
    validate_zimage_njr(njr)
    if njr.to_dict() != freeze(packet["attempt_id"], reports).to_dict():
        raise PermissionError("packet is not the frozen acceptance case")
    content = {k: v for k, v in packet.items() if k != "approval_digest"}
    if digest(content) != packet["approval_digest"] or packet["reports_dir"] != str(reports):
        raise PermissionError("dry-run packet binding mismatch")
    authorization = authorize(args, packet)
    revision = source_revision()
    if revision["dirty"] or revision != packet["source"]:
        raise PermissionError("physical execution requires unchanged clean source")
    _write_new(reports / "attempt.json", {"authorization": authorization, "claimed_at": datetime.now(UTC).isoformat()})
    report: dict[str, Any] = {"attempt_id": njr.job_id, "approval_digest": packet["approval_digest"],
                            "generation": "GENERATION_FAIL", "integration": "CANONICAL_PATH_INCOMPLETE"}
    stack = wire = None
    started = False
    faults_before = faults_after = None
    try:
        runtime = runtime or ManagedWebUIRuntime(launch_profile(Path(args.model_home), reports), P.backend_id)
        report["preflight"] = preflight_fn(runtime, Path(args.model_home), reports)
        observer = observer or Observations(runtime, reports)
        critical = ("ram_available_bytes", "commit_headroom_bytes", "vram_used_bytes", "shared_vram_bytes", "gpu_device_present")
        for _ in range(3):  # bounded read-only provider warmup; no model or runtime activity
            report["pre_execution_observation"] = observer.sample("preflight")
            if all(report["pre_execution_observation"]["status"].get(k) == "ok" for k in critical):
                break
        if any(report["pre_execution_observation"]["status"].get(k) != "ok" for k in critical):
            raise PermissionError("essential observations unavailable; owner decision required")
        if report["pre_execution_observation"]["values"].get("gpu_device_present") is False:
            raise PermissionError("GPU device-loss indicator present; owner decision required")
        faults_before = faults_fn()
        observer.start()  # includes startup/loading, rather than starting after startup
        if type(runtime) is ManagedWebUIRuntime:
            for key in ("HF_HUB_CACHE", "MPLCONFIGDIR", "YOLO_CONFIG_DIR", "UV_CACHE_DIR"):
                Path(runtime.profile["env_overrides"][key]).mkdir(parents=True, exist_ok=False)
            (reports / "runtime" / "data").mkdir(parents=True, exist_ok=False)
        started = True
        report["runtime_start"] = runtime.start()
        if not report["runtime_start"].get("owns_process"):
            raise PermissionError("external runtime ownership is never claimed")
        observer.phase = "loading_or_generation"
        with forge_selected_in_memory():
            stack = build_stack(reports / "state", reports / "output", P.backend_id, runtime.endpoint, client=client)
            wire = RequestEvidence(stack.client, reports)
            from src.controller.submission_policy_v26 import SubmissionPolicy

            report["accepted_ids"] = stack.service.submit_njrs([njr], SubmissionPolicy(start_when_idle=True))
            entry = _await_terminal(stack.repository, njr.job_id, args.timeout_seconds)
            report["completion_observation"] = observer.sample("job_completion")
            report.update(validate_result(entry, stack.repository, njr, reports, wire))
            if report["accepted_ids"] != [njr.job_id]:
                report["integration"] = "CANONICAL_PATH_FAIL"
            if wire.dispatched and not wire.response:
                report["generation"] = "GENERATION_AMBIGUOUS"
    except Exception as exc:  # evidence first, no retry, replay or second job
        report["error"] = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AmbiguousDispatch) or (wire and wire.dispatched and not wire.response):
            report["generation"] = "GENERATION_AMBIGUOUS"
    finally:
        if observer:
            observer.phase = "cleanup"
        owned = bool(report.get("runtime_start", {}).get("owns_process"))
        if started and (owned or type(runtime) is ManagedWebUIRuntime):
            try:
                report["shutdown_immediate"] = {"utc": datetime.now(UTC).isoformat(), **runtime.stop()}
            except Exception as exc:
                report["shutdown_immediate"] = {"error": str(exc)}
            report["cleanup"] = cleanup_result(report["shutdown_immediate"]) if owned else "CLEANUP_NOT_VERIFIED"
            if observer:
                observer.phase = "after_cleanup"
            # Observation only. Never a second shutdown or a retroactive cleanup promotion.
            try:
                settle_fn(1)
                report["shutdown_settled"] = {"utc": datetime.now(UTC).isoformat(), **runtime.observe()}
            except Exception as exc:
                report["shutdown_settled"] = {"error": str(exc)}
        else:
            report["cleanup"] = "CLEANUP_NOT_VERIFIED"
        if stack:
            try:
                report["worker_quiesced"] = stack.service.stop(timeout=5)
                if report["worker_quiesced"]:
                    stack.repository.close()
                else:
                    report["integration"] = "CANONICAL_PATH_INCOMPLETE"
            except Exception as exc:
                report["worker_stop_error"] = str(exc)
                report["integration"] = "CANONICAL_PATH_INCOMPLETE"
        if faults_before is not None:
            settle_fn(120)  # existing fault-event settle window, not a resource threshold
        if observer:
            try:
                observer.sample("after_cleanup")
            except Exception as exc:
                report["observation_error"] = str(exc)
            observer.close()
        try:
            faults_after = faults_fn() if faults_before is not None else None
            from tools.qualification.img154.evidence import classify_faults

            comparison = classify_faults(faults_before, faults_after, seconds_after_run=120)
            fault_evidence = {"complete": comparison.status == "NO_NEW_EVENTS_COMPLETE_COVERAGE",
                              "events": dict(comparison.new_records), "gaps": list(comparison.gaps),
                              "boot_changed": comparison.boot_changed}
        except Exception as exc:
            fault_evidence = {"complete": False, "events": [], "error": str(exc)}
        report["resources"] = resource_result(observer.rows if observer else [], fault_evidence)
        report["dispatch"] = {"sent": bool(wire and wire.dispatched), "blocked_additional": wire.blocked if wire else 0}
        _write_new(reports / "acceptance.json", report)
    return 0 if (report["generation"] == "GENERATION_PASS" and report["integration"] == "CANONICAL_PATH_PASS"
                 and report["resources"]["verdict"] == "OBSERVED_NO_FAULT" and report["cleanup"] == "CLEANUP_VERIFIED") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--approved-digest", default="")
    parser.add_argument("--owner-authorization", type=Path)
    parser.add_argument("--model-home", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    args = parser.parse_args(argv)
    if not args.dry and args.model_home is None:
        parser.error("--model-home is required for physical acceptance")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
