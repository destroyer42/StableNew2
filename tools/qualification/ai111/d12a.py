"""PR-AI-QUAL-114 D12a: the bounded binary-compatibility run of the frozen llama.cpp CPU build.

D12a is the owner's narrow authorization to extract the verified runtime archive into a *new evidence-only directory* and
run exactly two commands of each of two named members: ``--version`` and ``--help`` of ``llama-completion.exe`` (the
harness's one-shot launcher, added by the owner's AI-114 runtime-executable decision) and of ``llama-cli.exe`` (the
original D12a member). This module does that and nothing more: no model file is ever present, no inference command is
built, and no other member is launched.

* The archive is verified against the frozen size/SHA-256 and every member against the passive member-hash manifest
  (recorded before any extraction), the archive is unpacked with confined member paths, and every extracted file is hashed
  again from disk immediately before launch (and again after the last command).
* Both commands go through the ownership monitor and therefore through ``run_bounded``: the bounded runner remains the only
  process lifecycle owner. The harness and every child run under a standard-user token; the ETW capture is started and
  stopped by the operator from an Administrator terminal (PR-AI-QUAL-114E), so the file and connection findings are
  retrospective: they come from the post-capture analysis and the run is not verified until that analysis passes. In real
  time the monitor still stops an unexpected descendant, an elevated child or an unverified teardown.
* The help text of each member is compared with the closed flag vocabulary of ``src/ai_assist/argv.py`` (the flags
  ``build_argv`` actually emits for the inference path). A missing flag is a compatibility finding for that member, never a
  reason to substitute another spelling, another executable or to weaken the restrictions.
* Two kinds of stop: a *security or integrity* stop (monitor finding, unproven teardown, a changed tree, a loadable file in
  the working directory) ends the whole run; a *compatibility* stop (non-zero exit, timeout, output over the cap) ends only
  that member, and the verdicts are kept per member so nothing is silently read as another member's result.

``--help`` output beyond the authorized 64 KiB is cut by the runner; a truncated help is reported as INCONCLUSIVE rather than
read as proof that a flag is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.ai_assist.argv import ALLOWED_FLAGS, FORBIDDEN_FLAGS, build_environment
from src.utils.managed_process import OwnedChildObservation, ProcessOutcome
from tools.qualification.ai111 import plan as plan_module
from tools.qualification.ai111.ownership import OwnedSessionMonitor, OwnershipPolicy

#: The members the owner authorized, with their frozen SHA-256 (from the passive member-hash manifest), in run order: the
#: preferred Stage A launcher first. ``llama-cli.exe`` is the original D12a member; ``llama-completion.exe`` was added by
#: the owner's AI-114 runtime-executable decision (same archive, same pins as ``physical.LAUNCHABLE_MEMBERS``).
AUTHORIZED_MEMBERS: dict[str, str] = {
    "llama-completion.exe": "b36b1ef84a047542f72dca924616052efde7e380c2a12562d459f5febf5cab72",
    "llama-cli.exe": "c84a4604db9a01cb64ece64c7da5ace4c83c44dfb63f55a9c8d2270b685c0ee7",
}
#: SHA-256 of the passive member-hash manifest recorded before any extraction. The manifest names its own archive, which
#: alone would let a forged manifest vouch for a swapped archive; pinning the manifest itself closes that.
PASSIVE_MANIFEST_SHA256 = "f15151047cc3dcb3e093cffce3273a2b6f8c5acf4830a4e981174871475e8a9e"
COMMANDS: tuple[tuple[str, ...], ...] = (("--version",), ("--help",))
TIMEOUT_SECONDS = 10.0
STDOUT_CAP_BYTES = 64 * 1024
#: Hard bound on what an extraction may write (the frozen archive unpacks to about 60 MB).
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
_ACTIVE_SUFFIXES = frozenset(
    {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py", ".sh", ".so", ".dylib"}
)
_MODEL_SUFFIXES = frozenset({".gguf", ".ggml", ".safetensors"})

#: Flags ``build_argv`` always emits. Their absence from the help text breaks the closed command vocabulary.
REQUIRED_FLAGS: frozenset[str] = ALLOWED_FLAGS


class D12aRefused(RuntimeError):
    """A precondition failed before anything was extracted or launched."""


def write_new_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


# -- passive manifest and extraction -----------------------------------------------------------------------------------


def load_passive_manifest(path: Path, archive_sha256: str) -> dict[str, tuple[str, int]]:
    return load_passive_manifest_bytes(path.read_bytes(), archive_sha256)


def load_passive_manifest_bytes(raw: bytes, archive_sha256: str) -> dict[str, tuple[str, int]]:
    """Member name -> (SHA-256, bytes) from the passive evidence that was recorded without extracting anything."""

    document = json.loads(raw.decode("utf-8"))
    if document.get("archive_sha256") != archive_sha256:
        raise D12aRefused("passive member manifest is for a different archive")
    members = document.get("members")
    if not isinstance(members, dict) or not members:
        raise D12aRefused("passive member manifest is empty")
    return {name: (str(entry["sha256"]), int(entry["bytes"])) for name, entry in members.items()}


def _member_problem(name: str) -> str | None:
    posix = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or posix.is_absolute()
        or ":" in name
        or any(part in ("", ".", "..") for part in posix.parts)
    ):
        return f"unsafe member path: {name!r}"
    return None


def verify_archive_members(
    archive: Path | io.BytesIO, manifest: dict[str, tuple[str, int]]
) -> dict[str, tuple[str, int]]:
    """Hash every archive file member from the zip itself and require it to equal the passive manifest.

    Every active-suffix file must be in the manifest and every manifest entry must be in the archive. Returns the member
    table of the archive (name -> (sha256, bytes)); raises ``D12aRefused`` on any difference."""

    seen: dict[str, tuple[str, int]] = {}
    lowered: set[str] = set()
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            problem = _member_problem(info.filename.rstrip("/"))
            if problem:
                raise D12aRefused(problem)
            if info.is_dir():
                continue
            if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise D12aRefused(f"symbolic link member: {info.filename}")
            if info.filename.lower() in lowered:
                raise D12aRefused(f"duplicate member (case-insensitive): {info.filename}")
            lowered.add(info.filename.lower())
            total += info.file_size
            if total > MAX_EXTRACTED_BYTES:
                raise D12aRefused("archive expands beyond the extraction bound")
            if PurePosixPath(info.filename).suffix.lower() in _MODEL_SUFFIXES:
                raise D12aRefused(f"model-like member in a runtime archive: {info.filename}")
            digest = hashlib.sha256()
            size = 0
            with bundle.open(info) as source:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    digest.update(chunk)
            if size != info.file_size:
                raise D12aRefused(f"member size differs from its header: {info.filename}")
            seen[info.filename] = (digest.hexdigest(), size)
    missing = sorted(set(manifest) - set(seen))
    if missing:
        raise D12aRefused(f"manifest members absent from the archive: {missing[:5]}")
    for name, value in seen.items():
        expected = manifest.get(name)
        if expected is None:
            if PurePosixPath(name).suffix.lower() in _ACTIVE_SUFFIXES:
                raise D12aRefused(f"active member not in the passive manifest: {name}")
        elif expected != value:
            raise D12aRefused(f"member differs from the passive manifest: {name}")
    return seen


def extract_archive(archive: Path | io.BytesIO, target: Path) -> None:
    """Unpack into a new empty directory; member paths were already confined by :func:`verify_archive_members`."""

    target.mkdir(parents=True)
    root = target.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            destination = (root / info.filename).resolve()
            if root not in destination.parents:
                raise D12aRefused(f"member would leave the extraction directory: {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, destination.open("xb") as handle:
                while chunk := source.read(1024 * 1024):
                    handle.write(chunk)


def verify_extracted(
    directory: Path, members: dict[str, tuple[str, int]], manifest: dict[str, tuple[str, int]]
) -> list[str]:
    """Problems with the extracted tree: a missing, changed, extra or redirected file, or any model-like file."""

    problems: list[str] = []
    root = directory.resolve()
    present: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or path.is_junction():
            problems.append(f"redirected entry: {relative}")
        elif path.is_file():
            present.add(relative)
            if path.suffix.lower() in _MODEL_SUFFIXES:
                problems.append(f"model-like file present: {relative}")
    for name in sorted(set(members) - present):
        problems.append(f"missing: {name}")
    for name in sorted(present - set(members)):
        problems.append(f"unexpected file: {name}")
    for name in sorted(present & set(members)):
        path = root / name
        want_sha, want_bytes = members[name]
        if path.stat().st_size != want_bytes or sha256_file(path) != want_sha:
            problems.append(f"changed after extraction: {name}")
        elif name in manifest and manifest[name] != (want_sha, want_bytes):
            problems.append(f"differs from the passive manifest: {name}")
    return problems


# -- help analysis ------------------------------------------------------------------------------------------------------


def flag_in_text(flag: str, text: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", text) is not None


def analyze_help(help_text: str, *, truncated: bool) -> dict[str, Any]:
    """Compare help text with the closed vocabulary. Presence in the help is syntax evidence only, not behaviour."""

    present = sorted(f for f in REQUIRED_FLAGS if flag_in_text(f, help_text))
    missing = sorted(REQUIRED_FLAGS - set(present))
    forbidden_documented = sorted(f for f in FORBIDDEN_FLAGS if flag_in_text(f, help_text))
    if not help_text.strip():
        verdict = "INCONCLUSIVE"
    elif missing and truncated:
        verdict = "INCONCLUSIVE"  # the cut text may simply not have reached the missing flags
    elif missing:
        verdict = "FAIL"
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "help_truncated_at_cap": truncated,
        "required_flags_present": present,
        "required_flags_missing": missing,
        "forbidden_flags_documented_but_never_emitted": forbidden_documented,
        "scope": "flag spellings in the help text only; accepted values and runtime behaviour are not shown by this run",
    }


# -- the run ------------------------------------------------------------------------------------------------------------


@dataclass
class _CommandTrace:
    samples: int = 0
    peak_private_bytes: int = 0
    peak_working_set_bytes: int = 0
    priority_classes: set[int] = field(default_factory=set)
    priority_verified: bool | None = None
    processes_seen: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "peak_tree_private_bytes": self.peak_private_bytes,
            "peak_tree_working_set_bytes": self.peak_working_set_bytes,
            "priority_classes_observed": sorted(self.priority_classes),
            "priority_verified": self.priority_verified,
            "max_processes": self.processes_seen,
        }


def _command_result(
    member: str,
    outcome: ProcessOutcome,
    trace: _CommandTrace,
    elapsed_s: float,
    args: Sequence[str],
) -> dict[str, Any]:
    return {
        "command": [member, *args],
        "returncode": outcome.returncode,
        "timed_out": outcome.timed_out,
        "cancelled": outcome.cancelled,
        "launch_error": outcome.launch_error,
        "stdout_bytes": len(outcome.stdout),
        "stderr_bytes": len(outcome.stderr),
        "output_truncated_at_cap": outcome.output_truncated,
        "contained": outcome.contained,
        "elapsed_seconds": round(elapsed_s, 3),
        "observation": trace.summary(),
    }


def run_d12a(
    *,
    archive: Path,
    passive_manifest: Path,
    evidence_root: Path,
    monitor: OwnedSessionMonitor,
    authorization_text: str,
    attestation: str,
    runner_clock: Callable[[], float] | None = None,
    intent: dict[str, Any] | None = None,
    authorized_members: Mapping[str, str] = AUTHORIZED_MEMBERS,
    passive_manifest_sha256: str | None = PASSIVE_MANIFEST_SHA256,
) -> dict[str, Any]:
    """Run D12a once into a new ``<evidence_root>/d12a`` directory. Returns the result record (also written)."""

    import time

    clock = runner_clock or time.monotonic
    intent = intent or plan_module.RUNTIME_INTENT
    if not authorization_text.strip():
        raise D12aRefused("no owner authorization statement was supplied")
    if not attestation.strip():
        raise D12aRefused("no operator outbound-restriction attestation was supplied")
    not_ready = monitor.provider_problems()
    if not_ready:
        raise D12aRefused("monitoring not ready: " + "; ".join(not_ready))
    # The archive is read once; the very bytes that were hashed are the ones verified and extracted.
    data = archive.read_bytes()
    sha, size = hashlib.sha256(data).hexdigest(), len(data)
    if size != intent["bytes"] or sha != intent["sha256"]:
        raise D12aRefused("runtime archive does not match the frozen size/SHA-256")
    manifest_bytes = passive_manifest.read_bytes()
    if (
        passive_manifest_sha256 is not None
        and hashlib.sha256(manifest_bytes).hexdigest() != passive_manifest_sha256
    ):
        raise D12aRefused("passive member manifest is not the recorded one")
    manifest = load_passive_manifest_bytes(manifest_bytes, intent["sha256"])
    members = verify_archive_members(io.BytesIO(data), manifest)
    for name, pinned in authorized_members.items():
        if name not in members or members[name][0] != pinned:
            raise D12aRefused(f"{name} is not the authorized member")

    evidence = evidence_root / "d12a"
    evidence.mkdir(parents=True)
    write_new_json(
        evidence / "authorization.json",
        {
            "authorization_text": authorization_text,
            "operator_attestation": {
                "statement": attestation,
                "verified_by_stablenew": False,
            },
            "scope": "extract the verified archive and run --version and --help of "
            + " and ".join(authorized_members)
            + " only",
            "archive": {"path": str(archive), "bytes": size, "sha256": sha},
            "members": [
                {"name": name, "bytes": members[name][1], "sha256": members[name][0]}
                for name in authorized_members
            ],
            "commands": [list(c) for c in COMMANDS],
            "timeout_seconds_per_command": TIMEOUT_SECONDS,
            "stdout_cap_bytes": STDOUT_CAP_BYTES,
            "started_utc": datetime.now(UTC).isoformat(),
        },
    )
    runtime_dir = evidence / "runtime"
    scratch = evidence / "scratch"
    extract_archive(io.BytesIO(data), runtime_dir)
    scratch.mkdir()
    pre_problems = verify_extracted(runtime_dir, members, manifest)
    write_new_json(
        evidence / "pre-launch-verification.json",
        {"members_verified": len(members), "problems": pre_problems},
    )
    if pre_problems:
        return _finish(
            evidence, "FAIL", {"stopped": "pre-launch verification", "problems": pre_problems}
        )

    monitor.bind_evidence(evidence / "ownership")
    monitor.bind_roots(read_roots=(runtime_dir, _system_root()), write_roots=(scratch,))
    monitor.run_canary()
    readiness = monitor.readiness()
    write_new_json(
        evidence / "monitor-readiness.json",
        {"canary": monitor.canary_report, "problems": readiness},
    )
    if readiness:
        return _finish(
            evidence, "NOT TESTED", {"stopped": "monitor not ready", "problems": readiness}
        )

    run = monitor.runner()
    per_member: dict[str, dict[str, Any]] = {}
    stopped = ""  # a security or integrity stop: it ends the whole run
    halted_by = ""
    for member in authorized_members:
        entry: dict[str, Any] = {
            "sha256": members[member][0],
            "bytes": members[member][1],
            "stopped": "",
            "commands": [],
            "compatibility": None,
            "version_first_line": "",
            "verdict": "NOT TESTED",
            "_captured": {},
            "_truncated": False,
        }
        per_member[member] = entry
        if stopped:
            entry["stopped"] = "not run: an earlier member stopped the run"
            continue
        stopped = _run_member(
            member,
            entry,
            run=run,
            monitor=monitor,
            runtime_dir=runtime_dir,
            scratch=scratch,
            evidence=evidence,
            members=members,
            manifest=manifest,
            clock=clock,
        )
        if stopped:
            halted_by = member

    post_problems = verify_extracted(runtime_dir, members, manifest)
    write_new_json(
        evidence / "post-run-verification.json",
        {"members_verified": len(members), "problems": post_problems},
    )
    for member, entry in per_member.items():
        captured = entry.pop("_captured")
        truncated_stop = entry.pop("_truncated")
        if not entry["commands"]:
            if member == halted_by:
                entry["verdict"] = (
                    "FAIL"  # stopped by the security or integrity check before its first launch
                )
            continue  # otherwise never launched: stays NOT TESTED with its reason
        help_truncated = any(
            r["output_truncated_at_cap"]
            for r in entry["commands"]
            if r["command"][1:] == ["--help"]
        )
        compat = (
            analyze_help(captured.get("help", ""), truncated=help_truncated)
            if "help" in captured
            else None
        )
        if compat is not None:
            write_new_json(evidence / f"{Path(member).stem}.compatibility.json", compat)
        version_text = captured.get("version", "").strip()
        entry["compatibility"] = compat
        entry["version_first_line"] = version_text.splitlines()[0] if version_text else ""
        if post_problems:
            entry["verdict"] = "FAIL"
        elif entry["stopped"]:
            entry["verdict"] = "INCONCLUSIVE" if truncated_stop else "FAIL"
        elif compat is None:
            entry["verdict"] = "INCONCLUSIVE"
        else:
            entry["verdict"] = compat["verdict"]
    verdict = _overall_verdict([e["verdict"] for e in per_member.values()])
    stop_notes = {m: e["stopped"] for m, e in per_member.items() if e["stopped"]}
    body = {
        "members": per_member,
        "archive_sha256": sha,
        "priority_note": "below-normal is a creation flag set by run_bounded; a command shorter than the 50 ms poll may "
        "exit before any read-back, so per-command priority_verified can be null",
        "stopped": stopped,
        "stopped_by_member": stop_notes,
        "post_run_problems": post_problems,
        "monitoring": monitor.summary(),
        "finalized": not monitor.summary().get("capture_analysis_required", False),
        "file_access_events_by_request": [
            {"number": r.number, "files": sorted(set(r.files))} for r in monitor.session_records()
        ],
    }
    return _finish(evidence, verdict, body)


def _overall_verdict(verdicts: Sequence[str]) -> str:
    """The run is only as good as its weakest member: FAIL beats INCONCLUSIVE beats NOT TESTED beats PASS."""

    for level in ("FAIL", "INCONCLUSIVE", "NOT TESTED"):
        if level in verdicts:
            return level
    return "PASS"


def _run_member(
    member: str,
    entry: dict[str, Any],
    *,
    run: Callable[..., ProcessOutcome],
    monitor: OwnedSessionMonitor,
    runtime_dir: Path,
    scratch: Path,
    evidence: Path,
    members: dict[str, tuple[str, int]],
    manifest: dict[str, tuple[str, int]],
    clock: Callable[[], float],
) -> str:
    """Run both commands of one member. Returns a run-wide (security or integrity) stop reason, or ``""``.

    A compatibility stop (non-zero exit, timeout, output over the cap) is recorded on ``entry`` only."""

    executable = runtime_dir / member
    stem = Path(member).stem
    for args in COMMANDS:
        # Re-hash the whole extracted tree immediately before each launch: nothing may have changed since the last check.
        again = verify_extracted(runtime_dir, members, manifest)
        if again:
            reason = f"{member}: tree changed before launch: " + "; ".join(again[:3])
            entry["stopped"] = reason
            return reason
        loose = _loadable_files(scratch)
        if loose:
            reason = (
                f"{member}: loadable file in the child's working directory before launch: "
                + ", ".join(loose[:3])
            )
            entry["stopped"] = reason
            return reason
        trace = _CommandTrace()
        holder: list[OwnedChildObservation] = []

        def cancel(
            trace: _CommandTrace = trace, holder: list[OwnedChildObservation] = holder
        ) -> bool:
            if holder:
                _sample(holder[0], trace)
            return False

        started = clock()
        outcome = run(
            [str(executable), *args],
            timeout_seconds=TIMEOUT_SECONDS,
            max_stdout_bytes=STDOUT_CAP_BYTES,
            cwd=scratch,
            env=build_environment(runtime_dir, os.environ, scratch),
            observe=holder.append,
            cancel=cancel,
        )
        result = _command_result(member, outcome, trace, clock() - started, args)
        record = monitor.records[-1]
        result["ownership"] = {
            "violations": record.violations,
            "connection_attempts": record.connections,
            "file_events": len(record.files),
            "process_complete": record.process.get("complete"),
            "active_after_teardown": record.process.get("active_after_teardown"),
            "total_processes": record.process.get("total_processes"),
        }
        entry["commands"].append(result)
        planted = _loadable_files(scratch) + [
            entry_ for entry_ in record.files if _loadable_access_in(entry_, scratch)
        ]
        if planted:
            result["ownership"]["loadable_in_working_directory"] = planted
            record.violations.append("loadable_file_in_working_directory")
        label = "version" if args == ("--version",) else "help"
        entry["_captured"][label] = outcome.stdout.decode("utf-8", "replace")
        (evidence / f"{stem}.{label}.stdout.txt").write_bytes(outcome.stdout)
        (evidence / f"{stem}.{label}.stderr.txt").write_bytes(outcome.stderr)
        if outcome.stderr and label == "help" and not outcome.stdout:
            entry["_captured"][label] = outcome.stderr.decode("utf-8", "replace")
        what = f"{member} {' '.join(args)}"
        # Security and integrity first: these end the whole run.
        if record.violations or record.connections:
            reason = f"{what}: monitor findings {record.violations}"
            entry["stopped"] = reason
            return reason
        if (
            record.process.get("complete") is not True
            or record.process.get("active_after_teardown") != 0
        ):
            reason = f"{what}: teardown not proven"
            entry["stopped"] = reason
            return reason
        # Compatibility: these end this member only.
        if (
            outcome.launch_error or outcome.timed_out or outcome.returncode != 0
        ) and not outcome.output_truncated:
            entry["stopped"] = f"{what}: launch failure, timeout or nonzero exit"
            return ""
        if outcome.output_truncated:
            # The runner kills a child that exceeds the authorized cap, so the text is a prefix: judge it, never widen the cap.
            entry["stopped"] = f"{what}: output exceeded the authorized {STDOUT_CAP_BYTES}-byte cap"
            entry["_truncated"] = True
            return ""
    return ""


_LOADABLE = frozenset({".dll", ".exe", ".sys", ".drv", ".ocx", ".pyd", ".bat", ".cmd", ".ps1"})


def _loadable_files(directory: Path) -> list[str]:
    """Any loadable or scriptable file below ``directory`` (the child's working directory must never hold one)."""

    return sorted(
        p.relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in _LOADABLE
    )


def _loadable_access_in(entry: str, directory: Path) -> bool:
    """A file event (``mode:path``) that touched a loadable file under ``directory``."""

    path = Path(entry.partition(":")[2])
    try:
        inside = directory.resolve() in path.resolve().parents
    except OSError:
        return False
    return inside and path.suffix.lower() in _LOADABLE


def _sample(child: OwnedChildObservation, trace: _CommandTrace) -> None:
    try:
        sample = child.sample()
    except Exception:  # noqa: BLE001 - an unreadable sample is simply not recorded; the run is judged on the monitor
        return
    trace.samples += 1
    trace.peak_private_bytes = max(trace.peak_private_bytes, sample.private_bytes)
    trace.peak_working_set_bytes = max(trace.peak_working_set_bytes, sample.working_set_bytes)
    trace.processes_seen = max(trace.processes_seen, sample.process_count)
    if sample.priority_class is not None:
        trace.priority_classes.add(sample.priority_class)
    trace.priority_verified = (
        sample.priority_verified
        if trace.priority_verified is None
        else (trace.priority_verified and sample.priority_verified is True)
    )


def _system_root() -> Path:
    return Path(os.environ.get("SystemRoot", "C:\\Windows"))


def _finish(evidence: Path, verdict: str, body: dict[str, Any]) -> dict[str, Any]:
    result = {"verdict": verdict, "finished_utc": datetime.now(UTC).isoformat(), **body}
    write_new_json(evidence / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--passive-manifest", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True, help="a NEW run directory")
    parser.add_argument("--authorization-text", required=True)
    parser.add_argument(
        "--attest",
        required=True,
        help="the operator's own statement that an outbound restriction covers the extracted executable (recorded, "
        "never verified by StableNew)",
    )
    parser.add_argument("--run-id", required=True, help="the run id the operator gave the capture")
    parser.add_argument(
        "--capture-dir",
        type=Path,
        required=True,
        help="the operator's ACTIVE capture; it must be <evidence-root>/capture",
    )
    parser.add_argument(
        "--canary-proof",
        type=Path,
        required=True,
        help="analysis.json of a prior canary capture that passed",
    )
    args = parser.parse_args(argv)
    from tools.qualification.ai111 import tokens
    from tools.qualification.ai111.capture_session import CaptureAdmission, RetrospectiveMonitor

    if tokens.current_process_elevated() is not False:
        print(
            "This process is elevated or unreadable: use an ordinary terminal. Nothing was started."
        )
        return 2
    if args.capture_dir.resolve() != (args.evidence_root / "capture").resolve():
        print("The capture must be this run's own <evidence-root>/capture. Nothing was started.")
        return 2
    admission = CaptureAdmission(
        capture_dir=args.capture_dir, run_id=args.run_id, proof_path=args.canary_proof
    )
    monitor = RetrospectiveMonitor(OwnershipPolicy(), admission)
    try:
        result = run_d12a(
            archive=args.archive,
            passive_manifest=args.passive_manifest,
            evidence_root=args.evidence_root,
            monitor=monitor,
            authorization_text=args.authorization_text,
            attestation=args.attest,
        )
    except D12aRefused as exc:
        print(json.dumps({"verdict": "NOT TESTED", "refused": str(exc)}, indent=2))
        return 1
    finally:
        monitor.close_and_report(args.evidence_root / "d12a")
    print(json.dumps({k: result[k] for k in ("verdict", "stopped") if k in result}, indent=2))
    print(
        "Not final: stop the capture (Administrator terminal), then run capture_analysis analyze; "
        "the result counts only with a PASS analysis."
    )
    if result["verdict"] != "PASS":
        return 1
    return (
        0 if result.get("finalized") else 3
    )  # 3: passed in real time, final only after the capture analysis


if __name__ == "__main__":
    sys.exit(main())
