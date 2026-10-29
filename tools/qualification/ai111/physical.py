"""PR-AI-111 physical qualification session (Stage A/B). NOT run in Stage 1 or 113; every test of it uses fakes.

One session = one evidence directory, claimed exclusively (a second session of the same stage is refused). It imports an
operator-supplied runtime archive and the operator-supplied model files into an *evidence-local* AI root (never the
operator's real ``%LOCALAPPDATA%`` directory), runs each requested arm over a frozen case list through the production
``AiAssistService`` (candidate mode), records every outcome incrementally (flushed and fsynced), samples the machine, takes the owned container's own record of
every process, connection attempt and file access of each request (``ownership.py``), verifies teardown from that record
after every request, and scores the arms.

It never downloads anything, never touches the firewall and never runs without a plan digest that matches the committed plan
and a non-empty owner authorization statement that is written into the evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.ai_assist.argv import RunLimits, Sampling
from src.ai_assist.attestation import read_attestation
from src.ai_assist.contracts import AiCancelToken, OutcomeCode
from src.ai_assist.host import GenerationActivity, MemoryProbe, read_host_memory
from src.ai_assist.manifests import (
    ImportRefused,
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    hash_file,
    import_model,
    import_runtime,
    load_model_registry,
    record_active,
    verify_installation,
)
from src.ai_assist.paths import runtime_dir
from src.ai_assist.runtime import AiRuntime, default_command
from src.ai_assist.service import AiAssistService, ServicePolicy
from tools.qualification.ai111 import plan as plan_module
from tools.qualification.ai111.baselines import ARMS as BASELINE_FUNCTIONS
from tools.qualification.ai111.blinding import blinded_view, make_pairs
from tools.qualification.ai111.corpus import (
    Case,
    build_corpus,
    corpus_digest,
    from_jsonl,
    stage_a_subset,
)
from tools.qualification.ai111.ownership import (
    OwnedSessionMonitor,
    OwnershipPolicy,
    default_host_monitor,
)
from tools.qualification.ai111.scoring import evaluate_gates, summarize_arm

logger = logging.getLogger(__name__)

_ACTIVE_SUFFIXES = frozenset(
    {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py", ".sh", ".so", ".dylib"}
)
_EXECUTABLE_PREFERENCE = ("llama-completion.exe", "llama-cli.exe")
#: The only archive members a physical session may launch, pinned by SHA-256 (from the passive member-hash manifest).
#: D12a covers both (``d12a.AUTHORIZED_MEMBERS``: the owner's AI-114 runtime-executable decision added the one-shot
#: ``llama-completion.exe`` to the original ``llama-cli.exe``). A session may name either, but a recommendation counts only
#: the D12a verdict of the member that actually ran.
LAUNCHABLE_MEMBERS = {
    "llama-cli.exe": "c84a4604db9a01cb64ece64c7da5ace4c83c44dfb63f55a9c8d2270b685c0ee7",
    "llama-completion.exe": "b36b1ef84a047542f72dca924616052efde7e380c2a12562d459f5febf5cab72",
}
_BUSY_PATTERNS = ("stable-diffusion-webui", "comfyui", "run_pr_gate", "pytest", "forge")


def write_new_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def derive_runtime_build(
    archive: Path, intent: dict[str, Any], executable: str | None = None, *, spec: Any = None
) -> RuntimeBuild:
    """Verify the archive against the frozen digest, then hash every loadable member so it can be pinned and imported.

    ``executable`` names the member to run; without it the first of ``_EXECUTABLE_PREFERENCE`` present is used."""

    sha, size = hash_file(archive)
    if size != intent["bytes"] or sha != intent["sha256"]:
        raise ImportRefused("runtime_archive_mismatch")
    files: dict[str, str] = {}
    if spec is not None:
        if intent != spec.runtime or executable not in spec.members:
            raise ImportRefused("contract_runtime_or_executable_mismatch")
        from tools.qualification.ai111.d12a import verify_archive_members

        # Sizes are checked against the ZIP headers by the shared verifier. The
        # archive's exact hash binds those headers; file digests come from the contract.
        with zipfile.ZipFile(archive) as bundle:
            pinned = {
                name: (sha, bundle.getinfo(name).file_size) for name, sha in intent["files"].items()
            }
        verify_archive_members(archive, pinned)
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir() or PurePosixPath(info.filename).suffix.lower() not in _ACTIVE_SUFFIXES:
                continue
            digest = hashlib.sha256()
            with bundle.open(info) as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            files[info.filename] = digest.hexdigest()
    if executable is not None:
        if executable not in files:
            raise ImportRefused("requested_executable_not_in_archive")
        allowed_members = spec.members if spec is not None else LAUNCHABLE_MEMBERS
        if executable not in allowed_members:
            raise ImportRefused("requested_executable_not_launchable")
        if files[executable] != allowed_members[executable]:
            raise ImportRefused("requested_executable_hash_mismatch")
    else:
        executable = next((name for name in _EXECUTABLE_PREFERENCE if name in files), None)
        if intent == plan_module.RUNTIME_INTENT and (
            executable is None or files[executable] != LAUNCHABLE_MEMBERS[executable]
        ):
            raise ImportRefused("default_executable_hash_mismatch")
    if executable is None:
        raise ImportRefused("no_inference_executable_in_archive")
    return RuntimeBuild(
        build_id=f"{intent['tag']}-{intent['compute']}",
        upstream_repository=intent["repository"],
        upstream_tag=intent["tag"],
        asset_name=intent["asset"],
        asset_sha256=intent["sha256"],
        asset_bytes=intent["bytes"],
        license_spdx=intent["license"],
        executable=executable,
        files=files,
        qualified=False,
    )


def quiet_host_refusals(
    process_lister: Callable[[], list[tuple[int, str]]] | None = None,
) -> list[str]:
    """Refuse while other generation or gate work is running; sharing the machine would make the numbers meaningless."""

    if process_lister is None:
        import psutil

        def process_lister() -> list[tuple[int, str]]:
            rows = []
            for process in psutil.process_iter(["pid", "cmdline"]):
                try:
                    rows.append((process.info["pid"], " ".join(process.info["cmdline"] or [])))
                except Exception:  # noqa: BLE001 - an unreadable process cannot be judged
                    continue
            return rows

    me = os.getpid()
    return sorted(
        {
            f"busy host: {pattern}"
            for pid, line in process_lister()
            if pid != me
            for pattern in _BUSY_PATTERNS
            if pattern in line.lower() and "tools.qualification.ai111" not in line
        }
    )


@dataclass
class SessionPaths:
    evidence_root: Path
    runtime_archive: Path
    model_files: dict[str, Path]  # model_id -> operator-supplied local file
    operator_corpus: Path | None = None


@dataclass
class _Sampler:
    """Background evidence: system memory (1 Hz). Process, connection and file evidence is the monitor's, not this one's."""

    evidence: Path
    safety: dict[str, Any]
    memory_probe: MemoryProbe = read_host_memory
    stop: threading.Event = field(default_factory=threading.Event)
    abort_reason: str = ""

    def start(self) -> None:
        self._thread = threading.Thread(target=self._memory_loop, name="AI111-memory")
        self._thread.start()

    def close(self) -> None:
        self.stop.set()
        self._thread.join(10)

    def _memory_loop(self) -> None:
        breaches = 0
        # A baseline sample before anything runs, one per interval, and a final one when the session stops.
        while True:
            memory = self.memory_probe()
            row: dict[str, Any] = {"utc": datetime.now(UTC).isoformat()}
            if memory is None:
                breaches += 1
                row["unreadable"] = True
            else:
                row.update(
                    available_gib=round(memory.available_gib, 3),
                    commit_headroom_gib=round(memory.commit_headroom_gib, 3),
                )
                bad = (
                    memory.available_gib < self.safety["physical_available_gib_abort"]
                    or memory.commit_headroom_gib < self.safety["commit_headroom_gib_abort"]
                )
                breaches = breaches + 1 if bad else 0
            append_jsonl(self.evidence / "telemetry.jsonl", row)
            if breaches >= 2:
                self.abort_reason = "host memory guard"
                return
            if self.stop.wait(self.safety["sample_seconds"]):
                break


#: The service's own admission rule (model file + this margin, in GiB, for BOTH available RAM and commit headroom), applied
#: once up front for the largest requested model so a session does not import 19 GB before discovering it cannot run.
PREFERRED_AVAILABLE_GIB = 12.0


def resource_check(
    memory_probe: MemoryProbe, registry: ModelRegistry, arms: list[str]
) -> tuple[dict[str, Any], list[str]]:
    """Readings, per-arm requirements and refusals. The preferred 12 GiB is advisory and only recorded as a warning."""

    from src.ai_assist.service import MEMORY_MARGIN_GIB

    needs = {
        e.model_id: e.bytes / 1024**3 + MEMORY_MARGIN_GIB
        for e in registry.entries
        if e.model_id in arms
    }
    memory = memory_probe()
    report: dict[str, Any] = {
        "per_arm_requirement_gib": {k: round(v, 3) for k, v in needs.items()},
        "preferred_available_gib": PREFERRED_AVAILABLE_GIB,
        "warnings": [],
    }
    if memory is None:
        return report, ["memory could not be read"]
    report["available_gib"] = round(memory.available_gib, 3)
    report["commit_headroom_gib"] = round(memory.commit_headroom_gib, 3)
    problems: list[str] = []
    for model_id, need in sorted(needs.items()):
        if memory.available_gib < need:
            problems.append(
                f"available RAM {memory.available_gib:.2f} GiB is below {model_id}'s requirement {need:.2f} GiB"
            )
        if memory.commit_headroom_gib < need:
            problems.append(
                f"commit headroom {memory.commit_headroom_gib:.2f} GiB is below {model_id}'s requirement {need:.2f} GiB"
            )
    if needs and memory.available_gib < PREFERRED_AVAILABLE_GIB:
        report["warnings"].append(
            f"available RAM {memory.available_gib:.2f} GiB is under the preferred {PREFERRED_AVAILABLE_GIB:.0f} GiB "
            "for the full screening session"
        )
    return report, problems


def preflight(
    plan: dict[str, Any],
    paths: SessionPaths,
    registry: ModelRegistry,
    arms: list[str],
    *,
    strict_offline: bool,
    ai_root: Path,
    authorization_text: str,
    busy: list[str],
) -> list[str]:
    problems: list[str] = []
    if not authorization_text.strip():
        problems.append("no owner authorization statement was supplied")
    intent = plan["runtime_intent"]
    if not paths.runtime_archive.is_file():
        problems.append(f"missing runtime archive: {paths.runtime_archive.name}")
    else:
        sha, size = hash_file(paths.runtime_archive)
        if size != intent["bytes"] or sha != intent["sha256"]:
            problems.append("runtime archive does not match the frozen size/SHA-256")
    needed = 0
    for model_id in arms:
        if model_id in plan_module.BASELINE_ARMS:
            continue
        entry = next((e for e in registry.entries if e.model_id == model_id), None)
        file = paths.model_files.get(model_id)
        if entry is None:
            problems.append(f"unknown model arm: {model_id}")
        elif file is None or not file.is_file():
            problems.append(f"missing model file for {model_id}")
        else:
            sha, size = hash_file(file)
            if size != entry.bytes or sha != entry.sha256:
                problems.append(f"model file for {model_id} does not match the frozen size/SHA-256")
            needed += entry.bytes
    ai_root.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(ai_root.parent).free < needed + 5 * 1024**3:
        problems.append("not enough free disk for the evidence-local model copies plus 5 GiB")
    if strict_offline and read_attestation(ai_root) is None:
        problems.append(
            "strict offline requires the operator firewall attestation in the evidence-local AI root"
        )
    problems.extend(busy)
    return problems


def run_session(**kwargs: Any) -> dict[str, Any]:
    """Run one physical session; the monitor's closing bracket (canary and beacon) runs on every path that began."""

    monitor = kwargs.get("monitor")
    result: dict[str, Any] | None = None
    try:
        result = _run_session(**kwargs)
        return result
    finally:
        if monitor is not None:
            where = monitor.evidence_dir.parent if monitor.evidence_dir is not None else None
            leaked = monitor.close_and_report(where)
            if result is not None:
                result["trace_sessions_left_running"] = leaked
                if leaked and result.get("verdict") == "PASS":
                    result["verdict"] = "INCONCLUSIVE"
            if leaked:
                logger.error("Trace sessions left running after the session: %s", leaked)


def _run_session(
    *,
    plan: dict[str, Any],
    paths: SessionPaths,
    stage: str,
    arms: list[str],
    cases: list[Case],
    authorization_text: str,
    registry: ModelRegistry | None = None,
    strict_offline: bool = False,
    command_factory: Callable[..., Any] | None = None,
    busy_provider: Callable[[], list[str]] | None = None,
    attest: str | None = None,
    memory_probe: MemoryProbe = read_host_memory,
    monitor: OwnedSessionMonitor | None = None,
    executable: str | None = None,
    gpu_probe: Callable[[], list[str]] | None = None,
    lifecycle_probes: bool = False,
    extra_read_roots: tuple[Path, ...] = (),
    run_id: str = "",
    probe_case: Case | None = None,
    contract_spec: Any = None,
    readiness_evidence: dict[str, Any] | None = None,
    capture_segment: dict[str, Any] | None = None,
    capture_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Process, connection and file evidence comes only from the ownership monitor, which reads the bounded runner's own
    # container record. A session with no monitor, or one whose channels are not lifetime-complete and canary-proven,
    # refuses before anything is imported or launched. ``command_factory`` is the hermetic Python-child test seam.
    if monitor is None:
        monitor = default_host_monitor(OwnershipPolicy())
    arm_specs = {}
    if contract_spec is not None:
        from tools.qualification.ai111.readiness import bind_capture_evidence, readiness_problems

        readiness_evidence = bind_capture_evidence(readiness_evidence, monitor)
        problems = readiness_problems(
            contract_spec,
            "S3_stage_a" if stage == "A" else "S4_stage_b",
            readiness_evidence,
            executable=executable or "",
        )
        model_arms = [a for a in arms if a not in plan_module.BASELINE_ARMS]
        if len(model_arms) != 1 or len(set(arms)) != len(arms):
            problems.append("one executable arm per capture required")
        if any(a in plan_module.BASELINE_ARMS and a != "B1_engine" for a in arms):
            problems.append("only B1_engine is the LFM3 reference")
        for arm in model_arms:
            arm_specs[arm] = contract_spec.arm(arm)
        expected = list(contract_spec.cases(stage))
        if stage == "B":
            if capture_plan is None:
                problems.append("approved Stage B capture segment absent")
            else:
                from tools.qualification.ai111.stage_b_captures import (
                    execution_segment,
                    selected_arm,
                )

                capture_segment = execution_segment(
                    capture_plan,
                    contract_spec,
                    (capture_segment or {}).get("index", -1),
                    run_id,
                    paths.evidence_root,
                    readiness_evidence or {},
                )
                if model_arms != [capture_segment["arm"]] or arms != model_arms:
                    problems.append("Stage B capture must contain only its planned arm")
                for arm in model_arms:
                    arm_specs[arm] = selected_arm(
                        contract_spec, arm, capture_plan["stage_a_disposition"]
                    )
                expected = [c for c in expected if c.case_id in capture_segment["case_ids"]]
        if corpus_digest(cases) != corpus_digest(expected):
            problems.append("case list differs from selected contract/segment")
        if (
            not strict_offline
            or monitor.kind != "host"
            or command_factory is not None
            or gpu_probe is None
        ):
            problems.append(
                "physical contract requires authentic monitor, default command, strict offline and GPU probe"
            )
        if problems:
            return {"verdict": "NOT TESTED", "refused": problems}
        plan = contract_spec.execution_plan()
        registry = contract_spec.registry(model_arms)
    static_problems = monitor.provider_problems()
    if static_problems:
        return {
            "verdict": "NOT TESTED",
            "refused": [f"monitoring not ready: {problem}" for problem in static_problems],
        }
    registry = registry or load_model_registry(plan_module.REGISTRY_PATH)
    evidence = paths.evidence_root / f"physical-{stage}"
    # Exclusive claim: a second session of this stage is refused (FileExistsError), never merged into.
    evidence.mkdir(parents=True)
    ai_root = evidence / "ai-root"
    write_new_json(
        evidence / "execution-manifest.json",
        {
            "plan_sha256": plan_module.digest(plan),
            "contract_sha256": contract_spec.sha256 if contract_spec else plan_module.digest(plan),
            "contract_selector": contract_spec.selector if contract_spec else "qwen-frozen",
            "capture_id": getattr(getattr(monitor, "admission", None), "manifest", {}).get(
                "capture_id"
            )
            if getattr(getattr(monitor, "admission", None), "manifest", None)
            else None,
            "capture_segment": capture_segment,
            "arm_identities": {a: s.identity(executable) for a, s in arm_specs.items()},
            "stage": stage,
            "arms": arms,
            "cases": len(cases),
            "corpus_sha256": corpus_digest(cases),
            "owner_authorization": authorization_text,
            "readiness_evidence": readiness_evidence,
            "strict_offline": strict_offline,
            "started_utc": datetime.now(UTC).isoformat(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "ownership_sha256": hashlib.sha256(
                Path(__file__).with_name("ownership.py").read_bytes()
            ).hexdigest(),
            "monitor_kind": monitor.kind,
            "executed_sha": _git_head(),
            "source_dirty": _git_dirty(),
            "run_id": run_id,
            "host": platform.node(),
            "executable": executable or "(first of the preference list)",
            "lifecycle_probes": lifecycle_probes,
            "extra_read_roots": [str(r) for r in extra_read_roots],
            "etw_sha256": _sha_of_sibling("etw.py"),
            "capture_sha256": {
                name: _sha_of_sibling(f"{name}.py")
                for name in ("capture_control", "capture_session", "capture_analysis")
            },
        },
    )
    busy = (busy_provider or quiet_host_refusals)() if plan["safety"]["quiet_host_required"] else []
    if attest:
        from src.ai_assist.attestation import record_attestation

        ai_root.mkdir(parents=True, exist_ok=True)
        record_attestation(ai_root, attest)
    model_ids = [arm_specs[a].model.model_id if a in arm_specs else a for a in arms]
    problems = preflight(
        plan,
        paths,
        registry,
        model_ids,
        strict_offline=strict_offline,
        ai_root=ai_root,
        authorization_text=authorization_text,
        busy=busy,
    )
    resources, resource_problems = resource_check(memory_probe, registry, model_ids)
    write_new_json(evidence / "resource-preflight.json", resources)
    problems += resource_problems
    if problems:
        write_new_json(evidence / "preflight-refusal.json", problems)
        return {"verdict": "INCONCLUSIVE", "refused": problems}

    # Before anything is imported or launched, show the monitor detecting a known file read, connection attempt and
    # short-lived descendant of its own trusted canary child. Any shortfall refuses the whole session.
    monitor.bind_evidence(evidence / "ownership")
    monitor.bind_roots(
        read_roots=(
            ai_root,
            Path(os.environ.get("SystemRoot", "C:\\Windows")),
            *extra_read_roots,
        ),
        write_roots=(ai_root / "work",),
    )
    monitor.run_canary()
    monitor_problems = monitor.readiness()
    write_new_json(
        evidence / "monitor-readiness.json",
        {"canary": monitor.canary_report, "problems": monitor_problems},
    )
    if monitor_problems:
        return {
            "verdict": "NOT TESTED",
            "refused": [f"monitoring not ready: {problem}" for problem in monitor_problems],
        }

    build = derive_runtime_build(
        paths.runtime_archive, plan["runtime_intent"], executable, spec=contract_spec
    )
    write_new_json(
        evidence / "derived-runtime-build.json",
        {
            "build_id": build.build_id,
            "executable": build.executable,
            "asset_sha256": build.asset_sha256,
            "files": dict(build.files),
        },
    )
    import_runtime(paths.runtime_archive, build, ai_root)
    model_arms = [a for a in arms if a not in plan_module.BASELINE_ARMS]
    for arm_id in model_arms:
        model_id = arm_specs[arm_id].model.model_id if arm_id in arm_specs else arm_id
        entry = next(e for e in registry.entries if e.model_id == model_id)
        import_model(paths.model_files[model_id], entry, ai_root)

    limits = RunLimits(**plan["limits"])
    sampling = Sampling(**plan["sampling"])
    sampler = _Sampler(evidence, plan["safety"], memory_probe=memory_probe)
    sampler.start()
    records_path = evidence / "records.jsonl"
    records: dict[str, list[dict[str, Any]]] = {}
    abort = ""
    try:
        # Baseline arms are deterministic and free: record them first so the blind pairs have both sides.
        for arm in [a for a in arms if a in plan_module.BASELINE_ARMS]:
            for case in cases:
                row = {
                    "case_id": case.case_id,
                    "arm": arm,
                    "outcome": "suggestion",
                    "reason": "",
                    "elapsed_ms": 0,
                    "details": {},
                    **_baseline_fields(arm, case),
                }
                records.setdefault(arm, []).append(row)
                append_jsonl(records_path, row)
        for model_id in model_arms:
            selected_arm = arm_specs.get(model_id)
            entry_id = selected_arm.model.model_id if selected_arm else model_id
            entry = next(e for e in registry.entries if e.model_id == entry_id)
            record_active(ai_root, build, entry)
            arm_problems = _arm_preconditions(
                plan, ai_root, build, entry, busy_provider, gpu_probe, strict_offline
            )
            append_jsonl(
                evidence / "arm-integrity.jsonl",
                {"arm": model_id, "phase": "before", "problems": arm_problems, "utc": _now()},
            )
            if arm_problems:
                abort = f"arm precondition failed for {model_id}: " + "; ".join(arm_problems)
                break
            service = AiAssistService(
                root=ai_root,
                runtime_manifest=RuntimeManifest((build,)),
                registry=ModelRegistry((entry,)),
                activity_provider=lambda: GenerationActivity(),
                memory_probe=memory_probe,
                runtime=AiRuntime(
                    ai_root,
                    command_factory=command_factory or default_command,
                    runner=monitor.runner(),
                    **_argv_options(selected_arm),
                ),
                policy=ServicePolicy(allow_candidate=True, strict_offline=strict_offline),
                limits=limits,
                sampling=sampling,
            )
            consecutive_infra = 0
            for number, case in enumerate(cases, start=1):
                if sampler.abort_reason:
                    abort = sampler.abort_reason
                    break
                if contract_spec is not None:
                    before = _deep_problems(ai_root, build, entry)
                    if before:
                        abort = "identity changed before request: " + "; ".join(before)
                        break
                monitored_before = len(monitor.records)
                started_utc = _now()
                outcome = service.run(
                    case.request(f"{model_id[:24].replace('.', '_')}-{number:04d}")
                )
                suggestion = outcome.suggestion
                details = dict(outcome.details)
                new_records = monitor.records[monitored_before:]
                details["egress_connections"] = sum(len(r.connections) for r in new_records)
                details["ownership_violations"] = sorted(
                    {v for r in new_records for v in r.violations}
                )
                row = {
                    "case_id": case.case_id,
                    "arm": model_id,
                    "outcome": outcome.code.value,
                    "reason": outcome.reason,
                    "elapsed_ms": outcome.elapsed_ms,
                    "positive": getattr(suggestion, "positive_text", None),
                    "negative": getattr(suggestion, "negative_text", None),
                    "choice": getattr(suggestion, "target", None)
                    or getattr(suggestion, "workflow", None),
                    "details": details,
                    "started_utc": started_utc,
                    "ended_utc": _now(),
                    "arm_request_index": number + (capture_segment or {}).get("offset", 0),
                    "capture_request_index": number,
                    "capture_phase": "cold" if number == 1 else "warm",
                    "phase": "cold"
                    if number + (capture_segment or {}).get("offset", 0) == 1
                    else "warm",
                    "input_chars": case.request("probe").input_chars(),
                    **(selected_arm.identity(build.executable) if selected_arm else {}),
                    "monitor_kind": monitor.kind,
                    "stage": stage,
                    "run_id": run_id,
                    "capture_id": getattr(getattr(monitor, "admission", None), "manifest", {}).get(
                        "capture_id"
                    )
                    if getattr(getattr(monitor, "admission", None), "manifest", None)
                    else None,
                    "monitor_request_numbers": [r.number for r in new_records],
                    "process_complete": bool(new_records)
                    and all(r.process.get("complete") is True for r in new_records),
                    "active_after_teardown": 0
                    if new_records
                    and all(r.process.get("active_after_teardown") == 0 for r in new_records)
                    else None,
                }
                records.setdefault(model_id, []).append(row)
                append_jsonl(records_path, row)
                if (contract_spec is not None and not new_records) or (
                    new_records
                    and not all(
                        r.process.get("complete") is True
                        and r.process.get("active_after_teardown") == 0
                        for r in new_records
                    )
                ):
                    abort = "owned child tree not verified gone after a request"
                    break
                if contract_spec is not None:
                    after_request = _deep_problems(ai_root, build, entry)
                    if (
                        after_request
                        or outcome.code == OutcomeCode.TIMEOUT
                        or outcome.reason in ("output_too_large", "process_memory_cap")
                    ):
                        abort = (
                            "request interval invalid or stopped at resource/output/time limit: "
                            + "; ".join(after_request)
                        )
                        break
                if details["ownership_violations"]:
                    abort = "ownership violation: " + ", ".join(details["ownership_violations"])
                    break
                if outcome.reason in _UNTRUSTWORTHY_OBSERVATION:
                    abort = f"observation no longer trustworthy: {outcome.reason}"
                    break
                infra = outcome.code in (
                    OutcomeCode.TIMEOUT,
                    OutcomeCode.UNAVAILABLE,
                    OutcomeCode.RESOURCE_INSUFFICIENT,
                    OutcomeCode.YIELDED_TO_GENERATION,
                )
                consecutive_infra = consecutive_infra + 1 if infra else 0
                if consecutive_infra >= plan["safety"]["consecutive_infrastructure_failures_abort"]:
                    abort = f"{consecutive_infra} consecutive infrastructure failures"
                    break
            if not abort:
                after = _deep_problems(ai_root, build, entry)
                append_jsonl(
                    evidence / "arm-integrity.jsonl",
                    {"arm": model_id, "phase": "after", "problems": after, "utc": _now()},
                )
                if after:
                    abort = f"identity changed during {model_id}: " + "; ".join(after)
            if not abort and lifecycle_probes:
                lifecycle_rows = _lifecycle_probes(
                    probe_case or cases[0],
                    model_id,
                    ai_root,
                    build,
                    entry,
                    monitor,
                    memory_probe,
                    sampling,
                    limits,
                    command_factory,
                    strict_offline,
                    selected_arm,
                )
                for row in lifecycle_rows:
                    append_jsonl(evidence / "lifecycle-probes.jsonl", row)
                if any(
                    not r["teardown_verified"] or r["ownership_violations"] for r in lifecycle_rows
                ):
                    abort = f"lifecycle probe for {model_id} left unverified teardown or violations"
            if abort:
                break
    finally:
        sampler.close()

    teardown_verified = monitor.teardown_verified()
    cases_by_id = {c.case_id: c for c in cases}
    summaries = {arm: summarize_arm(cases_by_id, rows) for arm, rows in records.items()}
    verdicts = {
        arm: evaluate_gates(summaries[arm], plan["thresholds"], teardown_verified=teardown_verified)
        for arm in model_arms
        if arm in summaries
    }
    write_new_json(evidence / "summary.json", summaries)
    pairs = {}
    for model_id in model_arms:
        pairs[model_id] = make_pairs(
            [c.case_id for c in cases if c.kind == "prompt_rewrite"],
            model_id,
            "B1_engine",
            seed=plan["corpus"]["seed"],
        )
    write_new_json(evidence / "blind-pairs-manifest.json", pairs)
    texts = {
        (r["case_id"], r["arm"]): (r.get("positive") or "") + "\n---\n" + (r.get("negative") or "")
        for rows in records.values()
        for r in rows
        if r["outcome"] == "suggestion"
    }
    for model_id, manifest in pairs.items():
        usable = [
            p
            for p in manifest
            if (p["case_id"], p["left"]) in texts and (p["case_id"], p["right"]) in texts
        ]
        write_new_json(evidence / f"blinded-view-{model_id[:40]}.json", blinded_view(usable, texts))
    overall = "INCONCLUSIVE"
    if (
        verdicts
        and not abort
        and monitor.kind == "host"
        and monitor.summary()["requests_monitored"] > 0
        and monitor.teardown_verified()
        and monitor.connection_attempts() == 0
        and not monitor.violations()
        and all(v["verdict"] == "PASS" for v in verdicts.values())
    ):
        overall = "PASS"
    elif any(v["verdict"] == "NO-GO" for v in verdicts.values()) and not abort:
        overall = "NO-GO (per arm; see verdicts)"
    result = {
        "verdict": overall,
        "abort_reason": abort,
        "teardown_verified": teardown_verified,
        "egress_connections_observed": monitor.connection_attempts(),
        "monitoring": monitor.summary(),
        "arm_verdicts": {
            arm: {k: v[k] for k in ("verdict", "failed", "unmet")} for arm, v in verdicts.items()
        },
        "note": "Preference gates stay unmet until the operator rates the blinded pairs; PASS needs them.",
    }
    write_new_json(evidence / "result.json", result)
    return result


_UNTRUSTWORTHY_OBSERVATION = frozenset(
    {
        "process_priority_unverified",
        "process_observation_invalid",
        "process_memory_unreadable",
        "child_not_observable",
    }
)


def _argv_options(arm: Any) -> dict[str, Any]:
    if arm is None:
        return {}
    from tools.qualification.ai111.lfm3_contract import LFM3_ALLOWED_FLAGS

    return {"argv_builder": arm.argv, "allowed_flags": LFM3_ALLOWED_FLAGS}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _deep_problems(ai_root: Path, build: RuntimeBuild, entry: Any) -> list[str]:
    """Re-hash every pinned runtime file and the model file; any difference from the frozen identity is a stop.

    The runtime directory must also hold no loadable file beyond the pinned set (the runtime loads backend DLLs by
    scanning its own directory), and no scratch directory may hold one."""

    result = verify_installation(
        ai_root, RuntimeManifest((build,)), ModelRegistry((entry,)), deep=True, allow_candidate=True
    )
    problems = [] if result.ok else [result.reason]
    runtime_root = runtime_dir(ai_root, build.build_id)
    pinned = {name.lower() for name in build.files}
    for base, label in ((runtime_root, "runtime"), (ai_root / "work", "scratch")):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _ACTIVE_SUFFIXES:
                continue
            relative = path.relative_to(base).as_posix().lower()
            if label == "scratch" or relative not in pinned:
                problems.append(f"unpinned loadable file in {label}: {relative}")
    return problems


def _arm_preconditions(
    plan: dict[str, Any],
    ai_root: Path,
    build: RuntimeBuild,
    entry: Any,
    busy_provider: Callable[[], list[str]] | None,
    gpu_probe: Callable[[], list[str]] | None,
    strict_offline: bool,
) -> list[str]:
    """Before each model arm: the identity is still the frozen one, the host is still quiet and the GPU is as found."""

    problems = _deep_problems(ai_root, build, entry)
    if strict_offline and read_attestation(ai_root) is None:
        problems.append("operator attestation missing")
    if plan["safety"]["quiet_host_required"]:
        problems += (busy_provider or quiet_host_refusals)()
    if gpu_probe is not None:
        problems += gpu_probe()
    return problems


def _lifecycle_probes(
    case: Case,
    model_id: str,
    ai_root: Path,
    build: RuntimeBuild,
    entry: Any,
    monitor: OwnedSessionMonitor,
    memory_probe: MemoryProbe,
    sampling: Sampling,
    limits: RunLimits,
    command_factory: Callable[..., Any] | None,
    strict_offline: bool,
    selected_arm: Any = None,
) -> list[dict[str, Any]]:
    """Real-model timeout and cancellation: a deliberately short deadline, and a cancel fired while the model loads.

    These are lifecycle measurements, kept apart from the scored cases. Each records whether the probe really stopped the
    child (a model that finishes inside the deadline did not exercise the path) and whether teardown was proven."""

    rows: list[dict[str, Any]] = []
    for kind in ("timeout", "cancel"):
        if selected_arm is not None and _deep_problems(ai_root, build, entry):
            break
        probe_limits = RunLimits(
            **{**asdict(limits), "timeout_seconds": 2.0 if kind == "timeout" else 60.0}
        )
        service = AiAssistService(
            root=ai_root,
            runtime_manifest=RuntimeManifest((build,)),
            registry=ModelRegistry((entry,)),
            activity_provider=lambda: GenerationActivity(),
            memory_probe=memory_probe,
            runtime=AiRuntime(
                ai_root,
                command_factory=command_factory or default_command,
                runner=monitor.runner(),
                **_argv_options(selected_arm),
            ),
            policy=ServicePolicy(allow_candidate=True, strict_offline=strict_offline),
            limits=probe_limits,
            sampling=sampling,
        )
        token = AiCancelToken()
        timer = threading.Timer(1.0, token.cancel) if kind == "cancel" else None
        before = len(monitor.records)
        started = _now()
        if timer is not None:
            timer.start()
        try:
            outcome = service.run(case.request(f"{model_id[:20].replace('.', '_')}-{kind}"), token)
        finally:
            if timer is not None:
                timer.cancel()
        new = monitor.records[before:]
        expected = OutcomeCode.TIMEOUT if kind == "timeout" else OutcomeCode.CANCELLED
        rows.append(
            {
                "arm": model_id,
                "probe": kind,
                "outcome": outcome.code.value,
                "reason": outcome.reason,
                "elapsed_ms": outcome.elapsed_ms,
                "stopped_as_intended": outcome.code == expected,
                "teardown_verified": bool(new)
                and all(
                    r.process.get("complete") is True
                    and r.process.get("active_after_teardown") == 0
                    for r in new
                ),
                "ownership_violations": sorted({v for r in new for v in r.violations}),
                "started_utc": started,
                "ended_utc": _now(),
                **(selected_arm.identity(build.executable) if selected_arm else {}),
                "monitor_kind": monitor.kind,
                "run_id": getattr(getattr(monitor, "admission", None), "run_id", None),
                "capture_id": getattr(getattr(monitor, "admission", None), "manifest", {}).get(
                    "capture_id"
                )
                if getattr(getattr(monitor, "admission", None), "manifest", None)
                else None,
                "monitor_request_numbers": [r.number for r in new],
                "process_complete": bool(new)
                and all(r.process.get("complete") is True for r in new),
                "active_after_teardown": 0
                if new and all(r.process.get("active_after_teardown") == 0 for r in new)
                else None,
            }
        )
        if selected_arm is not None and _deep_problems(ai_root, build, entry):
            rows[-1]["teardown_verified"] = False
            break
    return rows


def _baseline_fields(arm: str, case: Case) -> dict[str, Any]:
    produced = BASELINE_FUNCTIONS[arm](case)
    return {
        "positive": produced.get("positive"),
        "negative": produced.get("negative"),
        "choice": produced.get("choice"),
    }


def _sha_of_sibling(name: str) -> str | None:
    path = Path(__file__).with_name(name)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _git_command() -> list[str] | None:
    """An absolute git, found on PATH without consulting the current directory (this process may be elevated), with
    repository-configured helpers disabled."""

    cwd = Path.cwd().resolve()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry)
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved == cwd or cwd in resolved.parents:
            continue
        candidate = directory / "git.exe"
        if candidate.is_file():
            return [str(candidate), "-c", "core.fsmonitor=false", "-c", "core.hooksPath=NUL"]
    return None


def _git_dirty() -> bool | None:
    """Whether tracked source differs from HEAD (evidence from a modified tree is labelled, not hidden)."""

    git = _git_command()
    if git is None:
        return None
    try:
        status = subprocess.check_output(
            [*git, "status", "--porcelain", "--untracked-files=no"], text=True, timeout=30
        )
    except Exception:  # noqa: BLE001
        return None
    return bool(status.strip())


def _git_head() -> str:
    git = _git_command()
    if git is None:
        return "unknown"
    try:
        return subprocess.check_output([*git, "rev-parse", "HEAD"], text=True, timeout=10).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def extra_root_refusal(root: Path) -> str:
    """Why an additional read root is not acceptable. Access is never widened to a user profile or a whole drive."""

    resolved = root.resolve()
    if not resolved.is_dir():
        return "not an existing directory"
    if resolved == Path(resolved.anchor):
        return "a drive root"
    for prefix, why in _refused_prefixes():
        if resolved == prefix or prefix in resolved.parents or resolved in prefix.parents:
            return why
    return ""


def _refused_prefixes() -> list[tuple[Path, str]]:
    """Directories an additional read root may never be, contain or sit under."""

    drive = Path(os.environ.get("SystemDrive", "C:") + "\\")
    system = Path(os.environ.get("SystemRoot", str(drive / "Windows")))
    return [
        (drive / "Users", "user profile data (anything under the Users directory)"),
        (Path.home(), "the user's profile"),
        (plan_module.REPO_ROOT, "the source repository"),
        (system / "Temp", "a user-writable system directory"),
    ]


def nvidia_smi_probe(
    max_utilization_percent: float = 40.0, max_memory_growth_mib: float = 2048.0
) -> Callable[[], list[str]]:
    """Read-only GPU guard: the GPU must stay queryable and unused by anyone else while the CPU-only runtime works."""

    from tools.qualification.ai111.tool_runner import bounded_tool

    root = os.environ.get("SystemRoot", "C:\\Windows")
    tool = str(Path(root) / "System32" / "nvidia-smi.exe")
    baseline: list[float] = []

    def probe() -> list[str]:
        try:
            code, text = bounded_tool(
                [tool, "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"]
            )
            utilization, memory = (float(part) for part in text.strip().splitlines()[0].split(","))
        except Exception:  # noqa: BLE001 - a GPU that cannot be read is a stop, not a pass
            return ["gpu: nvidia-smi could not be read"]
        if code != 0:
            return ["gpu: nvidia-smi failed"]
        baseline.append(memory)
        problems = []
        if utilization > max_utilization_percent:
            problems.append(f"gpu: utilization {utilization:.0f}% (another workload is running)")
        if memory - baseline[0] > max_memory_growth_mib:
            problems.append("gpu: memory use grew since the session started")
        return problems

    return probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", choices=("qwen-frozen", "lfm3-v1"), default="qwen-frozen")
    parser.add_argument("--readiness-evidence", type=Path)
    parser.add_argument("--capture-plan", type=Path)
    parser.add_argument("--segment", type=int)
    parser.add_argument(
        "--authorize-plan", required=True, help="the exact plan digest the owner accepted"
    )
    parser.add_argument(
        "--authorization-text",
        required=True,
        help="the owner's named authorization, recorded verbatim",
    )
    parser.add_argument("--stage", choices=("A", "B"), required=True)
    parser.add_argument("--arms", nargs="+", required=True)
    parser.add_argument("--runtime-archive", type=Path, required=True)
    parser.add_argument(
        "--model-dir",
        type=Path,
        required=True,
        help="directory holding the operator-downloaded GGUF files",
    )
    parser.add_argument("--evidence-root", type=Path, default=Path("reports/ai111"))
    parser.add_argument("--operator-corpus", type=Path)
    parser.add_argument("--strict-offline", action="store_true")
    parser.add_argument(
        "--attest",
        help="the operator's own statement that an outbound restriction exists (recorded, never verified by StableNew)",
    )
    parser.add_argument(
        "--executable",
        required=True,
        choices=sorted(LAUNCHABLE_MEMBERS),
        help="the runtime archive member to launch (pinned by SHA-256); it must be the member the D12a record covers",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="unique run identity; it must equal the run id the operator gave the capture",
    )
    parser.add_argument(
        "--lifecycle-probes",
        action="store_true",
        help="after each model's cases, run one real timeout probe and one real cancellation probe",
    )
    parser.add_argument(
        "--extra-read-root",
        type=Path,
        action="append",
        default=[],
        help="a directory the runtime was shown to need (from the D12a record); never a profile or drive root",
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        required=True,
        help="the operator's ACTIVE ETW capture; it must be <evidence-root>/capture (PR-AI-QUAL-114E)",
    )
    parser.add_argument(
        "--canary-proof",
        type=Path,
        required=True,
        help="analysis.json of a prior canary capture that passed",
    )
    args = parser.parse_args(argv)
    from tools.qualification.ai111.execution_contract import select_contract

    spec = select_contract(args.contract, args.authorize_plan)
    plan = spec.execution_plan()
    if args.authorize_plan != spec.sha256:
        raise SystemExit("Authorization does not match the frozen plan digest")
    for root in args.extra_read_root:
        refusal = extra_root_refusal(root)
        if refusal:
            raise SystemExit(f"--extra-read-root {root}: {refusal}")
    registry = load_model_registry(plan_module.REGISTRY_PATH)
    cases = build_corpus(plan["corpus"]["seed"], plan["corpus"]["counts"])
    if args.operator_corpus:
        cases += from_jsonl(args.operator_corpus.read_text(encoding="utf-8"))
    if args.stage == "A":
        cases = stage_a_subset(cases, plan["stages"]["A"]["cases_per_arm"], plan["corpus"]["seed"])
    segment = None
    capture_plan = None
    readiness = (
        json.loads(args.readiness_evidence.read_text(encoding="utf-8"))
        if args.readiness_evidence
        else None
    )
    if args.contract == "lfm3-v1":
        if args.operator_corpus:
            parser.error("LFM3 uses only the frozen case corpus")
        cases = list(spec.cases(args.stage))
        registry = spec.registry([a for a in args.arms if a not in plan_module.BASELINE_ARMS])
        if args.stage == "B":
            from tools.qualification.ai111.stage_b_captures import execution_segment

            if args.capture_plan is None or args.segment is None:
                parser.error("Stage B requires --capture-plan and --segment")
            capture_plan = json.loads(args.capture_plan.read_text(encoding="utf-8"))
            segment = execution_segment(
                capture_plan, spec, args.segment, args.run_id, args.evidence_root, readiness or {}
            )
            cases = [c for c in cases if c.case_id in segment["case_ids"]]
    files = {e.model_id: args.model_dir / e.filename for e in registry.entries}
    paths = SessionPaths(args.evidence_root, args.runtime_archive, files, args.operator_corpus)
    from tools.qualification.ai111.capture_session import CaptureAdmission, RetrospectiveMonitor

    if args.capture_dir.resolve() != (args.evidence_root / "capture").resolve():
        raise SystemExit("The capture must be this run's own <evidence-root>/capture")
    monitor = RetrospectiveMonitor(
        OwnershipPolicy(),
        CaptureAdmission(
            capture_dir=args.capture_dir, run_id=args.run_id, proof_path=args.canary_proof
        ),
    )
    result = run_session(
        plan=plan,
        paths=paths,
        stage=args.stage,
        arms=args.arms,
        cases=cases,
        authorization_text=args.authorization_text,
        registry=registry,
        strict_offline=args.strict_offline,
        monitor=monitor,
        attest=args.attest,
        executable=args.executable,
        gpu_probe=nvidia_smi_probe(),
        lifecycle_probes=args.lifecycle_probes,
        extra_read_roots=tuple(args.extra_read_root),
        run_id=args.run_id,
        contract_spec=spec if args.contract == "lfm3-v1" else None,
        readiness_evidence=readiness,
        capture_segment=segment,
        capture_plan=capture_plan,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["verdict"] != "PASS":
        return 1
    return (
        0 if not (result.get("monitoring") or {}).get("capture_analysis_required") else 3
    )  # 3: final only after the capture analysis


if __name__ == "__main__":
    sys.exit(main())
