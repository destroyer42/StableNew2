"""Run the reviewed visual adapter through the existing contained process launcher."""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import psutil

from src.ai_assist.activation import runtime_import_problem
from src.ai_assist.argv import build_environment
from src.ai_assist.attestation import attestation_covers
from src.ai_assist.host import MemoryProbe, checked_memory, read_host_memory
from src.ai_assist.manifests import RuntimeBuild, load_runtime_manifest
from src.ai_assist.observe import ChildObserver
from src.ai_assist.paths import attestation_path, runtime_dir
from src.ai_assist.runtime import strip_end_of_text
from src.utils.managed_process import ProcessOutcome, run_bounded
from tools.qualification.vl220 import contract, plan, scoring, staging
from tools.qualification.vl220.candidates import (
    GEMMA_CANDIDATE_ID,
    RUNTIME_MANIFEST_PATH,
    VisualCandidate,
    check_admission,
    find_candidate,
    has_link,
    runtime_reasons,
)
from tools.qualification.vl220.invocation import (
    InvocationRefused,
    build_visual_argv,
    copy_image,
    strict_json,
    write_inputs,
)

_GIB = 1024**3
_MEMORY_MARGIN_GIB = 4
_GEMMA_WORKING_SET_BYTES = 12 * _GIB
_MAX_DOCUMENT_BYTES = 4 * 1024**2
# The named mutex serializes visual evaluations across processes and installation roots.
_MUTEX_NAME = r"Global\StableNew.VisionEvaluation"

BusyProbe = Callable[[], list[str]]
CancelCheck = Callable[[], bool]


@contextmanager
def evaluation_slot() -> Iterator[None]:
    if sys.platform != "win32":
        raise InvocationRefused("windows_containment_required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = create(None, True, _MUTEX_NAME)
    existing = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if not handle:
        raise InvocationRefused("evaluation_slot_unavailable")
    try:
        if existing:
            raise InvocationRefused("evaluation_in_progress")
        yield
    finally:
        close(handle)


def read_document(path: Path) -> Any:
    if has_link(path) or not path.is_file():
        raise InvocationRefused("invalid_document_path")
    with path.open("rb") as handle:
        raw = handle.read(_MAX_DOCUMENT_BYTES + 1)
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise InvocationRefused("document_too_large")
    return strict_json(raw.decode("utf-8"))


def _runtime_problem(root: Path, build: RuntimeBuild) -> str:
    path = runtime_dir(root, build.build_id)
    if has_link(path) or not path.is_dir():
        return "runtime_not_imported"
    # The verified Windows archive is flat. Reject any unsigned DLL/search-path entry.
    allowed = {*build.files, "LICENSE-LLVM-OpenMP"}
    if any(
        child.name not in allowed or has_link(child) or not child.is_file()
        for child in path.iterdir()
    ):
        return "unexpected_runtime_file"
    if runtime_import_problem(root, build):
        return "runtime_integrity_failed"
    return ""


def readiness(
    root: Path,
    candidate: VisualCandidate,
    acknowledgement: Mapping[str, Any] | None,
    *,
    cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    """Reverify installed identities and egress attestation without launching a process."""
    root = staging.evaluation_root(root)
    target = staging.installed_pair(root, candidate)
    build_id = candidate.runtime.required_build_id
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    admission = check_admission(
        candidate,
        target,
        build_id=build_id,
        runtime_manifest=manifest,
        acknowledgement=acknowledgement,
        cancel=cancel,
    )
    reasons = list(admission.reasons)
    try:
        if read_document(target / "import_record.json") != staging.import_record(candidate):
            reasons.append("import_record_mismatch")
    except (OSError, ValueError):
        reasons.append("import_record_missing_or_invalid")
    build = manifest.find(build_id)
    if build is not None and not runtime_reasons(candidate, build_id, manifest):
        if problem := _runtime_problem(root, build):
            reasons.append(problem)
        if has_link(attestation_path(root)) or not attestation_covers(
            root, build_id, build.executable
        ):
            reasons.append("operator_attestation_missing")
    return {
        "candidate_id": candidate.candidate_id,
        "build_id": build_id,
        "launch_prerequisites_met": not reasons,
        "reasons": reasons,
        "qualified": False,
    }


def _limits(candidate: VisualCandidate) -> contract.ResourceLimits:
    limits = contract.ResourceLimits()
    if candidate.candidate_id == GEMMA_CANDIDATE_ID:
        return replace(limits, max_peak_working_set_bytes=_GEMMA_WORKING_SET_BYTES)
    return limits


def execution_identity(candidate: VisualCandidate) -> dict[str, Any]:
    build_id = candidate.runtime.required_build_id
    build = load_runtime_manifest(RUNTIME_MANIFEST_PATH).find(build_id)
    if build is None:
        raise InvocationRefused("runtime_build_not_pinned")
    identity = {
        "plan_sha256": plan.build_plan(candidate)["plan_sha256"],
        "profile": "vl230.mtmd.b11960/1",
        "build_id": build_id,
        "executable": build.executable,
        "executable_sha256": build.files[build.executable],
        "archive_sha256": build.asset_sha256,
        "loadable_files_sha256": contract.digest(dict(build.files)),
        "limits": asdict(_limits(candidate)),
        "jinja": True,
    }
    return {**identity, "execution_sha256": contract.digest(identity)}


def _quiet_probe() -> list[str]:
    """Conservatively refuse while the desktop, a known backend, or another llama runtime is open."""
    hints = (
        "stable-diffusion-webui",
        "comfyui",
        "forge",
        "src.main",
        "launch_stablenew",
        "llama-completion",
        "llama-mtmd-cli",
        "llama-server",
        "tools.qualification.ai111",
    )
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = (process.info["name"] or "").lower()
            if process.pid == os.getpid() or not any(
                marker in name for marker in ("python", "llama", "stablenew", "comfy", "forge")
            ):
                continue
            args = process.cmdline()
            command = " ".join(args).lower()
            if any(Path(arg).name.lower() in {"main.py", "launch.py", "webui.py"} for arg in args):
                command += " " + process.cwd().lower()
        except psutil.NoSuchProcess:
            continue
        if any(hint in command or hint in name for hint in hints):
            return ["host_runtime_active"]
    return []


def _host_refusal(
    candidate: VisualCandidate, memory_probe: MemoryProbe, busy_probe: BusyProbe
) -> str:
    try:
        if busy_probe():
            return "generation_or_gate_active"
        memory = checked_memory(memory_probe())
    except Exception:  # noqa: BLE001 - inability to observe the host must block launch
        return "host_probe_failed"
    if memory is None:
        return "memory_unreadable"
    needed = candidate.download_bytes / _GIB + _MEMORY_MARGIN_GIB
    if min(memory.available_gib, memory.commit_headroom_gib) < needed:
        return "memory_headroom_insufficient"
    return ""


def _outcome_reason(outcome: ProcessOutcome, stop_reason: str, observed: bool) -> str:
    if outcome.launch_error:
        return (
            "containment_unavailable"
            if outcome.launch_error.startswith("containment")
            else "launch_failed"
        )
    if not outcome.contained or outcome.memory_limit_enforced is not True:
        return "containment_unverified"
    if stop_reason or outcome.cancelled:
        return stop_reason or "cancelled"
    if outcome.timed_out:
        return "wall_clock_limit"
    if outcome.output_truncated:
        return "output_too_large"
    if outcome.returncode != 0:
        return "child_exit_nonzero"
    if not observed:
        return "child_not_observed"
    return ""


def _run_case(
    candidate: VisualCandidate,
    case: contract.Case,
    assets: Mapping[str, contract.Asset],
    root: Path,
    asset_root: Path,
    *,
    runner: Callable[..., ProcessOutcome],
    cancel: CancelCheck,
    memory_probe: MemoryProbe,
    busy_probe: BusyProbe,
) -> tuple[str, contract.Measurement | None, dict[str, Any]]:
    """Return an in-memory response and content-free per-case evidence."""
    target = staging.installed_pair(root, candidate)
    runtime = runtime_dir(root, candidate.runtime.required_build_id)
    limits = _limits(candidate)
    with tempfile.TemporaryDirectory(prefix=".case-", dir=root) as work:
        scratch = Path(work)
        images = tuple(
            copy_image(assets[asset_id], asset_root, scratch, index)
            for index, asset_id in enumerate(case.asset_ids, 1)
        )
        prompt, schema = write_inputs(case, scratch)
        argv = build_visual_argv(
            root,
            scratch,
            target / candidate.model.filename,
            target / candidate.projector.filename,
            images,
            prompt,
            schema,
            jinja=True,
            context_tokens=limits.max_context_tokens,
        )
        if cancel():
            raise InvocationRefused("cancelled")
        if reason := _host_refusal(candidate, memory_probe, busy_probe):
            raise InvocationRefused(reason)

        stop_reason = ""
        observer = ChildObserver(cap_gib=limits.max_peak_working_set_bytes / _GIB)
        started = time.monotonic()

        def should_stop() -> bool:
            nonlocal stop_reason
            try:
                memory = checked_memory(memory_probe())
                if cancel():
                    stop_reason = "cancelled"
                elif (
                    memory is None
                    or memory.available_gib < 0.25
                    or memory.commit_headroom_gib < 1.0
                ):
                    stop_reason = "host_memory_guard"
                elif problem := observer.poll():
                    stop_reason = problem
                elif (
                    observer.evidence.peak_tree_working_set_gib * _GIB
                    > limits.max_peak_working_set_bytes
                ):
                    stop_reason = "working_set_limit"
            except Exception:  # noqa: BLE001 - the contained runner must stop on failed observation
                stop_reason = "host_probe_failed"
            return bool(stop_reason)

        outcome = runner(
            [str(runtime / candidate.runtime.tool), *argv],
            cwd=scratch,
            env=build_environment(runtime, os.environ, scratch),
            cancel=should_stop,
            observe=observer.bind,
            require_containment=True,
            timeout_seconds=limits.max_wall_seconds,
            memory_limit_mb=limits.max_peak_working_set_bytes / 1024**2,
            max_stdout_bytes=contract.MAX_RESPONSE_BYTES + 64,
        )
        observation = observer.evidence
        wall_seconds = time.monotonic() - started
        measurement = None
        if observation.child_observed and outcome.contained:
            measurement = contract.Measurement(
                wall_seconds,
                round(observation.peak_tree_working_set_gib * _GIB),
                limits.max_context_tokens,
                True,
            )
        reason = _outcome_reason(outcome, stop_reason, observation.child_observed)
        response = ""
        status = "invalid"
        if not reason:
            try:
                text = strip_end_of_text(outcome.stdout).decode("utf-8")
                strict_json(text)
            except (ValueError, RecursionError):
                reason = "not_strict_json"
            else:
                check = contract.validate_response(case, text)
                status, reason = check.status, check.reason
                if status in ("valid", "refused"):
                    response = text
        return (
            response,
            measurement,
            {
                "case_id": case.case_id,
                "argv_sha256": contract.digest(argv),
                "wall_seconds": wall_seconds,
                "peak_working_set_bytes": measurement.peak_working_set_bytes
                if measurement
                else None,
                "exit_code": outcome.returncode,
                "response_status": status,
                "reason": reason,
            },
        )


def evaluate(
    candidate_id: str,
    root: Path,
    case_path: Path,
    label_path: Path,
    acknowledgement: Mapping[str, Any] | None,
    *,
    execution_sha256: str,
    case_sha256: str,
    label_sha256: str,
    cancel: CancelCheck = lambda: False,
    memory_probe: MemoryProbe = read_host_memory,
    busy_probe: BusyProbe = _quiet_probe,
    runner: Callable[..., ProcessOutcome] = run_bounded,
) -> dict[str, Any]:
    """Run an explicitly frozen evaluation and return a report with no model text or input paths."""
    candidate = find_candidate(candidate_id)
    root = staging.evaluation_root(root)
    identity = execution_identity(candidate)
    case_doc = read_document(case_path)
    label_doc = read_document(label_path)
    if (
        identity["execution_sha256"] != execution_sha256
        or contract.digest(case_doc) != case_sha256
        or contract.digest(label_doc) != label_sha256
    ):
        raise InvocationRefused("evaluation_identity_mismatch")
    cases = contract.validate_case_set(case_doc)
    labels = contract.validate_label_set(label_doc, cases)
    assets = {asset.asset_id: asset for asset in cases.assets}
    responses: dict[str, str] = {}
    measurements: dict[str, contract.Measurement] = {}
    evidence: list[dict[str, Any]] = []
    stopped = ""
    with evaluation_slot():
        for case in cases.cases:
            ready = readiness(root, candidate, acknowledgement, cancel=cancel)
            if not ready["launch_prerequisites_met"]:
                stopped = ready["reasons"][0]
                break
            try:
                response, measurement, row = _run_case(
                    candidate,
                    case,
                    assets,
                    root,
                    case_path.absolute().parent,
                    runner=runner,
                    cancel=cancel,
                    memory_probe=memory_probe,
                    busy_probe=busy_probe,
                )
            except InvocationRefused as exc:
                stopped = str(exc)
                break
            except OSError:
                stopped = "case_io_error"
                break
            responses[case.case_id] = response
            if measurement is not None:
                measurements[case.case_id] = measurement
            evidence.append(row)
            if row["reason"] in {
                "cancelled",
                "containment_unavailable",
                "containment_unverified",
                "launch_failed",
                "child_not_observed",
                "child_not_observable",
                "process_observation_invalid",
                "process_memory_unreadable",
                "process_priority_unverified",
                "process_memory_cap",
                "working_set_limit",
                "host_memory_guard",
                "host_probe_failed",
                "child_exit_nonzero",
                "wall_clock_limit",
            }:
                stopped = row["reason"]
                break
    return {
        **identity,
        "case_set_sha256": case_sha256,
        "label_set_sha256": label_sha256,
        "set_id": cases.set_id,
        "candidate_id": candidate_id,
        "complete": not stopped,
        "stop_reason": stopped or None,
        "qualified": False,
        "cases": evidence,
        "scores": scoring.score_run(cases, labels, responses, measurements, _limits(candidate)),
        "baselines": {
            mode: scoring.score_run(cases, labels, scoring.baseline_responses(cases, mode))
            for mode in ("all_yes", "all_no", "seeded_random")
        },
    }
