"""PR-AI-111 physical qualification session (Stage A/B). NOT run in Stage 1; every test of it uses fakes.

One session = one evidence directory, claimed exclusively (a second session of the same stage is refused). It imports an
operator-supplied runtime archive and the operator-supplied model files into an *evidence-local* AI root (never the
operator's real ``%LOCALAPPDATA%`` directory), runs each requested arm over a frozen case list through the production
``AiAssistService`` (candidate mode), records every outcome incrementally (flushed and fsynced), samples the machine and
any network connection owned by the runtime, verifies the child tree is gone after every request, and scores the arms.

It never downloads anything, never touches the firewall and never runs without a plan digest that matches the committed plan
and a non-empty owner authorization statement that is written into the evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.ai_assist.argv import RunLimits, Sampling
from src.ai_assist.attestation import read_attestation
from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.host import GenerationActivity, read_host_memory
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
)
from src.ai_assist.runtime import AiRuntime
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
from tools.qualification.ai111.scoring import evaluate_gates, summarize_arm

_ACTIVE_SUFFIXES = frozenset(
    {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py", ".sh", ".so", ".dylib"}
)
_EXECUTABLE_PREFERENCE = ("llama-completion.exe", "llama-cli.exe")
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


def derive_runtime_build(archive: Path, intent: dict[str, Any]) -> RuntimeBuild:
    """Verify the archive against the frozen digest, then hash every loadable member so it can be pinned and imported."""

    sha, size = hash_file(archive)
    if size != intent["bytes"] or sha != intent["sha256"]:
        raise ImportRefused("runtime_archive_mismatch")
    files: dict[str, str] = {}
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir() or PurePosixPath(info.filename).suffix.lower() not in _ACTIVE_SUFFIXES:
                continue
            digest = hashlib.sha256()
            with bundle.open(info) as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            files[info.filename] = digest.hexdigest()
    executable = next((name for name in _EXECUTABLE_PREFERENCE if name in files), None)
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
    """Background evidence: system memory (1 Hz) and any network connection owned by the runtime (4 Hz)."""

    evidence: Path
    ai_root: Path
    safety: dict[str, Any]
    stop: threading.Event = field(default_factory=threading.Event)
    abort_reason: str = ""
    egress_seen: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._memory_loop, name="AI111-memory"),
            threading.Thread(target=self._egress_loop, name="AI111-egress"),
        ]
        for thread in self._threads:
            thread.start()

    def close(self) -> None:
        self.stop.set()
        for thread in self._threads:
            thread.join(10)

    def egress_total(self) -> int:
        with self._lock:
            return self.egress_seen

    def _memory_loop(self) -> None:
        breaches = 0
        # A baseline sample before anything runs, one per interval, and a final one when the session stops.
        while True:
            memory = read_host_memory()
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

    def _egress_loop(self) -> None:
        import psutil

        marker = str(self.ai_root).lower()
        while not self.stop.wait(0.25):
            try:
                owners = {
                    p.info["pid"]
                    for p in psutil.process_iter(["pid", "cmdline"])
                    if marker in " ".join(p.info["cmdline"] or []).lower()
                }
                if not owners:
                    continue
                hits = [c for c in psutil.net_connections(kind="inet") if c.pid in owners]
            except Exception:  # noqa: BLE001 - recorded, never silent: the sampler itself failing is evidence
                append_jsonl(
                    self.evidence / "egress.jsonl",
                    {"utc": datetime.now(UTC).isoformat(), "sampler_error": True},
                )
                continue
            if hits:
                with self._lock:
                    self.egress_seen += len(hits)
                append_jsonl(
                    self.evidence / "egress.jsonl",
                    {
                        "utc": datetime.now(UTC).isoformat(),
                        "connections": [[c.status, str(c.laddr), str(c.raddr)] for c in hits],
                    },
                )


def _tree_gone(marker: str, wait_seconds: float) -> bool:
    import psutil

    deadline = time.monotonic() + wait_seconds
    while True:
        alive = [
            p.pid
            for p in psutil.process_iter(["pid", "cmdline"])
            if marker in " ".join(p.info["cmdline"] or []).lower()
        ]
        if not alive:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.25)


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


def run_session(
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
) -> dict[str, Any]:
    # Marker-based session egress and teardown diagnostics below are not proof
    # of process ownership. Real runtime execution stays refused until that
    # evidence path is bound to the owned container and D12b is authorized.
    # An injected command factory is solely the hermetic Python-child test seam.
    if command_factory is None:
        return {
            "verdict": "NOT TESTED",
            "refused": [
                "Physical qualification blocked: ownership-bound session egress and teardown evidence required before D12b"
            ],
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
            "stage": stage,
            "arms": arms,
            "cases": len(cases),
            "corpus_sha256": corpus_digest(cases),
            "owner_authorization": authorization_text,
            "strict_offline": strict_offline,
            "started_utc": datetime.now(UTC).isoformat(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "executed_sha": _git_head(),
        },
    )
    busy = (busy_provider or quiet_host_refusals)() if plan["safety"]["quiet_host_required"] else []
    if attest:
        from src.ai_assist.attestation import record_attestation

        ai_root.mkdir(parents=True, exist_ok=True)
        record_attestation(ai_root, attest)
    problems = preflight(
        plan,
        paths,
        registry,
        arms,
        strict_offline=strict_offline,
        ai_root=ai_root,
        authorization_text=authorization_text,
        busy=busy,
    )
    if problems:
        write_new_json(evidence / "preflight-refusal.json", problems)
        return {"verdict": "INCONCLUSIVE", "refused": problems}

    build = derive_runtime_build(paths.runtime_archive, plan["runtime_intent"])
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
    for model_id in model_arms:
        entry = next(e for e in registry.entries if e.model_id == model_id)
        import_model(paths.model_files[model_id], entry, ai_root)

    limits = RunLimits(**plan["limits"])
    sampling = Sampling(**plan["sampling"])
    sampler = _Sampler(evidence, ai_root, plan["safety"])
    sampler.start()
    records_path = evidence / "records.jsonl"
    records: dict[str, list[dict[str, Any]]] = {}
    teardown_verified = True
    abort = ""
    marker = str(ai_root).lower()
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
            entry = next(e for e in registry.entries if e.model_id == model_id)
            record_active(ai_root, build, entry)
            service = AiAssistService(
                root=ai_root,
                runtime_manifest=RuntimeManifest((build,)),
                registry=ModelRegistry((entry,)),
                activity_provider=lambda: GenerationActivity(),
                runtime=AiRuntime(ai_root, command_factory=command_factory)
                if command_factory
                else None,
                policy=ServicePolicy(allow_candidate=True, strict_offline=strict_offline),
                limits=limits,
                sampling=sampling,
            )
            consecutive_infra = 0
            for number, case in enumerate(cases, start=1):
                if sampler.abort_reason:
                    abort = sampler.abort_reason
                    break
                egress_before = sampler.egress_total()
                outcome = service.run(
                    case.request(f"{model_id[:24].replace('.', '_')}-{number:04d}")
                )
                suggestion = outcome.suggestion
                details = dict(outcome.details)
                details["egress_connections"] = sampler.egress_total() - egress_before
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
                }
                records.setdefault(model_id, []).append(row)
                append_jsonl(records_path, row)
                if not _tree_gone(marker, plan["safety"]["teardown_wait_seconds"]):
                    teardown_verified = False
                    abort = "child tree still present after a request"
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
            if abort:
                break
    finally:
        sampler.close()

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
        and sampler.egress_total() == 0
        and all(v["verdict"] == "PASS" for v in verdicts.values())
    ):
        overall = "PASS"
    elif any(v["verdict"] == "NO-GO" for v in verdicts.values()) and not abort:
        overall = "NO-GO (per arm; see verdicts)"
    result = {
        "verdict": overall,
        "abort_reason": abort,
        "teardown_verified": teardown_verified,
        "egress_connections_observed": sampler.egress_total(),
        "arm_verdicts": {
            arm: {k: v[k] for k in ("verdict", "failed", "unmet")} for arm, v in verdicts.items()
        },
        "note": "Preference gates stay unmet until the operator rates the blinded pairs; PASS needs them.",
    }
    write_new_json(evidence / "result.json", result)
    return result


def _baseline_fields(arm: str, case: Case) -> dict[str, Any]:
    produced = BASELINE_FUNCTIONS[arm](case)
    return {
        "positive": produced.get("positive"),
        "negative": produced.get("negative"),
        "choice": produced.get("choice"),
    }


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=10).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
    args = parser.parse_args(argv)
    plan = plan_module.frozen_plan()
    if args.authorize_plan != plan_module.digest(plan):
        raise SystemExit("Authorization does not match the frozen plan digest")
    registry = load_model_registry(plan_module.REGISTRY_PATH)
    cases = build_corpus(plan["corpus"]["seed"], plan["corpus"]["counts"])
    if args.operator_corpus:
        cases += from_jsonl(args.operator_corpus.read_text(encoding="utf-8"))
    if args.stage == "A":
        cases = stage_a_subset(cases, plan["stages"]["A"]["cases_per_arm"], plan["corpus"]["seed"])
    files = {e.model_id: args.model_dir / e.filename for e in registry.entries}
    paths = SessionPaths(args.evidence_root, args.runtime_archive, files, args.operator_corpus)
    result = run_session(
        plan=plan,
        paths=paths,
        stage=args.stage,
        arms=args.arms,
        cases=cases,
        authorization_text=args.authorization_text,
        registry=registry,
        strict_offline=args.strict_offline,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
