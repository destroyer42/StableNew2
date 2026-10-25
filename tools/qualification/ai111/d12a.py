"""PR-AI-QUAL-114 D12a: the bounded binary-compatibility run of the frozen llama.cpp CPU build.

D12a is the owner's narrow authorization to extract the verified runtime archive into a *new evidence-only directory* and
run exactly two commands of one named member, ``llama-cli.exe --version`` and ``llama-cli.exe --help``. This module does
that and nothing more: no model file is ever present, no inference command is built, and no other member is launched.

* The archive is verified against the frozen size/SHA-256 and every member against the passive member-hash manifest
  (recorded before any extraction), the archive is unpacked with confined member paths, and every extracted file is hashed
  again from disk immediately before launch (and again after the last command).
* Both commands go through the ownership monitor and therefore through ``run_bounded``: the bounded runner remains the only
  process lifecycle owner. The monitor (ETW, elevated) must be canary-proven before anything is launched, and any
  connection attempt, file access outside the stated roots, unexpected descendant or unverified teardown stops the run.
* The help text is compared with the closed flag vocabulary of ``src/ai_assist/argv.py``. A missing flag is a compatibility
  finding, never a reason to substitute another spelling or to weaken the restrictions.

``--help`` output beyond the authorized 64 KiB is cut by the runner; a truncated help is reported as INCONCLUSIVE rather than
read as proof that a flag is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.ai_assist.argv import ALLOWED_FLAGS, FORBIDDEN_FLAGS, build_environment
from src.ai_assist.manifests import hash_file
from src.utils.managed_process import OwnedChildObservation, ProcessOutcome
from tools.qualification.ai111 import plan as plan_module
from tools.qualification.ai111.ownership import OwnedSessionMonitor, OwnershipPolicy

MEMBER = "llama-cli.exe"
#: The one member the owner authorized (D12a request in ``PR-AI-111_Offline_Qualification.md``): its frozen SHA-256.
AUTHORIZED_MEMBER_SHA256 = "c84a4604db9a01cb64ece64c7da5ace4c83c44dfb63f55a9c8d2270b685c0ee7"
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
    """Member name -> (SHA-256, bytes) from the passive evidence that was recorded without extracting anything."""

    document = json.loads(path.read_text(encoding="utf-8"))
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
    archive: Path, manifest: dict[str, tuple[str, int]]
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


def extract_archive(archive: Path, target: Path) -> None:
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
    outcome: ProcessOutcome, trace: _CommandTrace, elapsed_s: float, args: Sequence[str]
) -> dict[str, Any]:
    return {
        "command": [MEMBER, *args],
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
    runner_clock: Callable[[], float] | None = None,
    intent: dict[str, Any] | None = None,
    authorized_member_sha256: str = AUTHORIZED_MEMBER_SHA256,
) -> dict[str, Any]:
    """Run D12a once into a new ``<evidence_root>/d12a`` directory. Returns the result record (also written)."""

    import time

    clock = runner_clock or time.monotonic
    intent = intent or plan_module.RUNTIME_INTENT
    if not authorization_text.strip():
        raise D12aRefused("no owner authorization statement was supplied")
    not_ready = monitor.provider_problems()
    if not_ready:
        raise D12aRefused("monitoring not ready: " + "; ".join(not_ready))
    sha, size = hash_file(archive)
    if size != intent["bytes"] or sha != intent["sha256"]:
        raise D12aRefused("runtime archive does not match the frozen size/SHA-256")
    manifest = load_passive_manifest(passive_manifest, intent["sha256"])
    members = verify_archive_members(archive, manifest)
    if MEMBER not in members or members[MEMBER][0] != authorized_member_sha256:
        raise D12aRefused(f"{MEMBER} is not the authorized member")

    evidence = evidence_root / "d12a"
    evidence.mkdir(parents=True)
    write_new_json(
        evidence / "authorization.json",
        {
            "authorization_text": authorization_text,
            "scope": "extract the verified archive and run llama-cli.exe --version and --help only",
            "archive": {"path": str(archive), "bytes": size, "sha256": sha},
            "member": {"name": MEMBER, "bytes": members[MEMBER][1], "sha256": members[MEMBER][0]},
            "commands": [list(c) for c in COMMANDS],
            "timeout_seconds_per_command": TIMEOUT_SECONDS,
            "stdout_cap_bytes": STDOUT_CAP_BYTES,
            "started_utc": datetime.now(UTC).isoformat(),
        },
    )
    runtime_dir = evidence / "runtime"
    scratch = evidence / "scratch"
    extract_archive(archive, runtime_dir)
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

    executable = runtime_dir / MEMBER
    results: list[dict[str, Any]] = []
    captured: dict[str, str] = {}
    stopped = ""
    run = monitor.runner()
    for args in COMMANDS:
        # Re-hash the whole extracted tree immediately before each launch: nothing may have changed since the last check.
        again = verify_extracted(runtime_dir, members, manifest)
        if again:
            stopped = "tree changed before launch: " + "; ".join(again[:3])
            break
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
        result = _command_result(outcome, trace, clock() - started, args)
        record = monitor.records[-1]
        result["ownership"] = {
            "violations": record.violations,
            "connection_attempts": record.connections,
            "file_events": len(record.files),
            "process_complete": record.process.get("complete"),
            "active_after_teardown": record.process.get("active_after_teardown"),
            "total_processes": record.process.get("total_processes"),
        }
        results.append(result)
        label = "version" if args == ("--version",) else "help"
        captured[label] = outcome.stdout.decode("utf-8", "replace")
        (evidence / f"{label}.stdout.txt").write_bytes(outcome.stdout)
        (evidence / f"{label}.stderr.txt").write_bytes(outcome.stderr)
        if outcome.stderr and label == "help" and not outcome.stdout:
            captured[label] = outcome.stderr.decode("utf-8", "replace")
        if outcome.launch_error or outcome.timed_out or outcome.returncode != 0:
            stopped = f"{' '.join(args)}: launch failure, timeout or nonzero exit"
            break
        if record.violations or record.connections:
            stopped = f"{' '.join(args)}: monitor findings {record.violations}"
            break
        if (
            record.process.get("complete") is not True
            or record.process.get("active_after_teardown") != 0
        ):
            stopped = f"{' '.join(args)}: teardown not proven"
            break

    post_problems = verify_extracted(runtime_dir, members, manifest)
    write_new_json(
        evidence / "post-run-verification.json",
        {"members_verified": len(members), "problems": post_problems},
    )
    help_text = captured.get("help", "")
    help_truncated = any(
        r["output_truncated_at_cap"] for r in results if r["command"][1:] == ["--help"]
    )
    compat = analyze_help(help_text, truncated=help_truncated) if "help" in captured else None
    if compat is not None:
        write_new_json(evidence / "compatibility.json", compat)
    version_text = captured.get("version", "").strip()
    summary = monitor.summary()
    if stopped or post_problems:
        verdict = "FAIL"
    elif compat is None:
        verdict = "INCONCLUSIVE"
    else:
        verdict = compat["verdict"]
    body = {
        "stopped": stopped,
        "post_run_problems": post_problems,
        "version_first_line": version_text.splitlines()[0] if version_text else "",
        "commands": results,
        "compatibility": compat,
        "monitoring": summary,
        "file_access_events_by_request": [
            {"number": r.number, "files": sorted(set(r.files))} for r in monitor.session_records()
        ],
    }
    return _finish(evidence, verdict, body)


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
    args = parser.parse_args(argv)
    from tools.qualification.ai111.etw import etw_host_monitor, is_elevated

    if not is_elevated():
        print("Not elevated: open an Administrator terminal and rerun. Nothing was started.")
        return 2
    args.evidence_root.mkdir(parents=True, exist_ok=True)
    monitor = etw_host_monitor(OwnershipPolicy(), args.evidence_root / "d12a-ownership")
    try:
        result = run_d12a(
            archive=args.archive,
            passive_manifest=args.passive_manifest,
            evidence_root=args.evidence_root,
            monitor=monitor,
            authorization_text=args.authorization_text,
        )
    except D12aRefused as exc:
        print(json.dumps({"verdict": "NOT TESTED", "refused": str(exc)}, indent=2))
        return 1
    finally:
        monitor.close()
    print(json.dumps({k: result[k] for k in ("verdict", "stopped") if k in result}, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
