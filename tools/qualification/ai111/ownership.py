"""PR-AI-QUAL-113 ownership-bound session monitoring for the AI-111 physical harness.

The bounded runner stays the only process lifecycle owner. This module only *reads*: it asks ``run_bounded`` for the
owned container's own record of the whole process tree (every creation and exit, and a verified teardown), and it
attributes channel events (connection attempts, file access) to processes in that record. It never discovers a process
by command line, never kills anything itself (a violation is raised through the runner's own cancel path), and never
starts a runtime that has not first been shown to be watched.

Coverage is declared per channel and proven, not assumed:

* ``lifetime_complete``: the provider observes every event for the whole life of every owned process.
* ``sampled``: the provider looks at moments in time and can miss anything shorter than its interval.
* ``unavailable``: the provider cannot observe the channel.

A physical session is ready only when every required channel has a ``lifetime_complete`` provider *and* a canary child
(a trusted, inline Python script, never a downloaded runtime) performed a known file read, a known connection attempt and
a short-lived descendant under the monitor and each was reported back, attributed to the canary's own tree. A monitor
that cannot show that is refused before any runtime or model is imported.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.utils.managed_process import OwnedChildObservation, ProcessOutcome, run_bounded
from src.utils.process_observation import OwnedTreeEvidence, ProcessLifecycleEvent
from tools.qualification.ai111 import tokens

COMPLETE = "lifetime_complete"
SAMPLED = "sampled"
UNAVAILABLE = "unavailable"
CHANNELS = ("connections", "files")
_MAX_HASHED_EXECUTABLE_BYTES = 64 * 1024 * 1024

Runner = Callable[..., ProcessOutcome]


@dataclass(frozen=True, slots=True)
class ChannelEvent:
    """One observation, global to the host until attributed. ``mode`` is read/write/unknown for files."""

    pid: int
    detail: str
    ts_ns: int | None = None
    mode: str = "unknown"


class ChannelProvider(Protocol):
    channel: str
    coverage: str

    def begin(self) -> None:
        """A request window opens. Called before the child is launched."""

    def poll(self, owned_pids: frozenset[int]) -> None:
        """Called about every 50 ms with the pids the container has reported so far (sampling providers look here)."""

    def end(self, owned_pids: frozenset[int]) -> list[ChannelEvent]:
        """The window closed after verified teardown. ``owned_pids`` is every pid the container reported, so a
        system-wide provider can keep only those (and count the rest) instead of returning the whole host's events."""


@dataclass(frozen=True, slots=True)
class OwnershipPolicy:
    #: Processes other than the root and the allowed helpers. A llama.cpp one-shot CLI starts none; provisional [U].
    max_descendants: int = 0
    #: System images the OS itself adds to a console child's tree (at most one each): the console host that
    #: ``CREATE_NO_WINDOW`` gives a piped console program. Matched on the full System32 path, never on a name alone.
    helper_images: tuple[str, ...] = ("conhost.exe",)
    read_roots: tuple[Path, ...] = ()
    write_roots: tuple[Path, ...] = ()
    allow_connections: bool = False


def descendant_findings(
    events: Sequence[ProcessLifecycleEvent], root_pid: int, policy: OwnershipPolicy
) -> list[str]:
    """Judge the owned record's members: anything but the root and the allowed OS helpers is unexpected, and a member
    whose image could not be read is reported as such (never presumed to be a helper)."""

    system32 = _norm(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32")
    helpers_seen: dict[str, int] = {}
    created: dict[int, int] = {}
    extra = 0
    findings: list[str] = []
    for event in events:
        if event.kind != "new":
            continue
        if event.pid is None:
            if "unresolved_member_pid" not in findings:
                findings.append("unresolved_member_pid")
            continue
        created[event.pid] = created.get(event.pid, 0) + 1
        # The first creation of the root pid is the root; a second one means the pid was reused inside the tree.
        if event.pid == root_pid and created[event.pid] == 1:
            continue
        if created[event.pid] > 1 and "pid_reused_in_tree" not in findings:
            findings.append("pid_reused_in_tree")
        if event.image is None:
            if "unresolved_member_image" not in findings:
                findings.append("unresolved_member_image")
            continue
        image = _norm(event.image)
        name = os.path.basename(image)
        is_helper = any(
            image == os.path.normcase(os.path.join(system32, helper)) and name == helper.lower()
            for helper in policy.helper_images
        )
        if is_helper:
            helpers_seen[name] = helpers_seen.get(name, 0) + 1
            extra += helpers_seen[name] > 1
        else:
            extra += 1
    if extra > policy.max_descendants:
        findings.append("unexpected_descendants")
    return findings


def _norm(path: str | Path) -> str:
    text = str(path)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.realpath(text))


def _within(path: str, roots: Sequence[Path]) -> bool:
    target = _norm(path)
    for root in roots:
        base = _norm(root)
        if target == base or target.startswith(base.rstrip("\\/") + os.sep):
            return True
    return False


@dataclass(frozen=True, slots=True)
class OwnedWindow:
    pid: int
    start_ns: int
    end_ns: int | None


def owned_windows(
    events: Sequence[ProcessLifecycleEvent], *, request_start_ns: int
) -> dict[int, OwnedWindow]:
    """Per owned pid, the interval during which a channel event may be attributed to it.

    The start is the request's launch (a creation notification is drained after the fact, so it is never an earlier
    bound than the event it names), the end is that pid's exit or termination notification. Both bounds err toward
    attributing too much, never too little: a misattribution fails closed, a dropped owned event would not."""

    ends: dict[int, int] = {}
    members: set[int] = set()
    for event in events:
        if event.pid is None:
            continue
        if event.kind == "new":
            members.add(event.pid)
        elif event.kind in ("exit", "abnormal_exit", "terminated"):
            ends[event.pid] = max(ends.get(event.pid, 0), event.observed_ns)
    return {pid: OwnedWindow(pid, request_start_ns, ends.get(pid)) for pid in members}


def attribute(
    channel_events: Sequence[ChannelEvent], windows: dict[int, OwnedWindow]
) -> tuple[list[ChannelEvent], int, int]:
    """Split a provider's global events into (owned, foreign, ambiguous).

    ``foreign`` events name a pid that was never in the owned record. ``ambiguous`` events name an owned pid but a time
    outside its window (a recycled pid or a clock-domain mismatch) and are never silently dropped by the caller.
    An event with no timestamp cannot be placed in a window and is attributed on its pid alone (fail closed)."""

    owned: list[ChannelEvent] = []
    foreign = 0
    ambiguous = 0
    for event in channel_events:
        window = windows.get(event.pid)
        if window is None:
            foreign += 1
        elif event.ts_ns is None or (
            event.ts_ns >= window.start_ns
            and (window.end_ns is None or event.ts_ns <= window.end_ns)
        ):
            owned.append(event)
        else:
            ambiguous += 1
    return owned, foreign, ambiguous


@dataclass
class RequestOwnership:
    number: int
    executable: str
    executable_sha256: str | None
    process: dict[str, Any]
    connections: list[str]
    files: list[str]
    foreign_events: int
    violations: list[str]
    canary: bool = False
    #: ``False``: the live child's token was read and is not elevated. ``None``: not read (the child ended before the first
    #: poll, or the probe could not open it). ``True`` is a violation and cancels the request.
    child_token_elevated: bool | None = None
    #: Why a provider failed (channel -> the OS tool's own message, truncated). Diagnostic only; the violation stays the verdict.
    provider_errors: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "executable": self.executable,
            "executable_sha256": self.executable_sha256,
            "process": self.process,
            "connection_attempts": self.connections,
            "file_events": self.files,
            "events_not_attributed_to_the_owned_tree": self.foreign_events,
            "violations": self.violations,
            "canary": self.canary,
            "child_token_elevated": self.child_token_elevated,
            "provider_errors": self.provider_errors,
        }


def _process_summary(evidence: OwnedTreeEvidence) -> dict[str, Any]:
    return {
        "root_pid": evidence.root_pid,
        "total_processes": evidence.total_processes,
        "complete": evidence.complete,
        "problems": list(evidence.problems),
        "runner_terminated_tree": evidence.runner_terminated_survivors,
        "active_after_teardown": evidence.active_after_teardown,
        "job_io_bytes": {
            "read": evidence.io_read_bytes,
            "write": evidence.io_write_bytes,
            "other": evidence.io_other_bytes,
        },
        "events": [[e.kind, e.pid, e.image] for e in evidence.events],
    }


def policy_violations(
    policy: OwnershipPolicy, connections: Sequence[str], files: Sequence[str]
) -> list[str]:
    """The file and egress rules, applied to attributed ``connections`` and ``mode:path`` ``files`` entries."""

    found: list[str] = []
    if connections and not policy.allow_connections:
        found.append("egress_attempt_observed")
    for entry in files:
        mode, _, path = entry.partition(":")
        # Only an access a provider positively reports as a read may use the read roots; anything else is a write.
        roots = (*policy.read_roots, *policy.write_roots) if mode == "read" else policy.write_roots
        if not _within(path, roots):
            found.append("file_access_outside_policy")
            break
    return found


def _executable_identity(command: Sequence[str]) -> tuple[str, str | None]:
    exe = Path(str(command[0])) if command else Path("")
    try:
        if exe.is_file() and exe.stat().st_size <= _MAX_HASHED_EXECUTABLE_BYTES:
            return str(exe), hashlib.sha256(exe.read_bytes()).hexdigest()
    except OSError:
        pass
    return str(exe), None


class OwnedSessionMonitor:
    """Wraps the bounded runner so each request yields ownership-bound evidence and a fail-closed verdict."""

    def __init__(
        self,
        policy: OwnershipPolicy,
        providers: Sequence[ChannelProvider],
        *,
        kind: str,
        evidence_dir: Path | None = None,
        clock: Callable[[], int] = time.perf_counter_ns,
        canary_script: str | None = None,
        forbid_elevation: bool = False,
        self_elevated: Callable[[], bool | None] = tokens.current_process_elevated,
        token_probe: Callable[[int], bool | None] = tokens.process_token_elevated,
    ) -> None:
        #: The privilege boundary: with this set, an elevated harness is refused before anything runs, and a child whose
        #: token is read as elevated is stopped through the runner's cancel path.
        self.forbid_elevation = forbid_elevation
        self._self_elevated = self_elevated
        self._token_probe = token_probe
        self._child_token: bool | None = None
        self.policy = policy
        self._canary_script = canary_script or _CANARY_SCRIPT
        self.providers = list(providers)
        self.kind = kind
        self.evidence_dir = evidence_dir
        self._clock = clock
        self.records: list[RequestOwnership] = []
        self.canary_report: dict[str, Any] | None = None
        self._proven: dict[str, bool] = {}
        self._pending = ""

    # -- readiness ----------------------------------------------------------------------------------------------------

    def bind_roots(self, *, read_roots: tuple[Path, ...], write_roots: tuple[Path, ...]) -> None:
        """Fix the file-access policy to the session's own directories (known only once the evidence root exists)."""

        self.policy = dataclasses.replace(
            self.policy, read_roots=read_roots, write_roots=write_roots
        )

    def provider_problems(self) -> list[str]:
        """Why this monitor can never be ready, without running anything: the platform or a channel's declared coverage."""

        problems: list[str] = []
        if os.name != "nt":
            problems.append(
                "ownership evidence requires the Windows job object; this host has none"
            )
        if self.forbid_elevation:
            elevated = self._self_elevated()
            if elevated is not False:
                problems.append(
                    "privilege: the harness token is elevated or unreadable; the runtime import and every child must run "
                    "under a standard-user token"
                )
        for channel in CHANNELS:
            mine = [p for p in self.providers if p.channel == channel]
            if not mine:
                problems.append(f"{channel}: no provider")
            elif not any(p.coverage == COMPLETE for p in mine):
                best = "sampled" if any(p.coverage == SAMPLED for p in mine) else UNAVAILABLE
                problems.append(
                    f"{channel}: no {COMPLETE} provider (best available is {best}); a sampler can miss a short attempt"
                )
        return problems

    def readiness(self) -> list[str]:
        """Why a physical session may not start. Empty means every channel is lifetime-complete and canary-proven."""

        problems = self.provider_problems()
        if self.canary_report is None:
            problems.append("monitor canary has not been run")
        elif not self.canary_report["passed"]:
            for channel in CHANNELS:
                if not self._proven.get(channel):
                    problems.append(
                        f"{channel}: the canary did not show this channel detecting a known event"
                    )
            if self.forbid_elevation and self.canary_report["saw"].get("standard_user") is not True:
                problems.append("privilege: the canary child did not report a non-elevated token")
            if not self.canary_report["saw"]["descendant"]:
                problems.append(
                    "process: the canary's short-lived descendant was not in the owned record"
                )
            if not problems:
                problems.append("the canary child did not complete cleanly under the monitor")
        return problems

    # -- the wrapped runner -------------------------------------------------------------------------------------------

    def runner(self, inner: Runner = run_bounded, *, canary: bool = False) -> Runner:
        def run(command: Sequence[str], **kwargs: Any) -> ProcessOutcome:
            return self._run(inner, command, kwargs, canary)

        return run

    def _run(
        self, inner: Runner, command: Sequence[str], kwargs: dict[str, Any], canary: bool
    ) -> ProcessOutcome:
        self._pending = ""
        self._child_token = None
        observation: list[OwnedChildObservation] = []
        outer_observe = kwargs.get("observe")
        outer_cancel = kwargs.get("cancel")
        started = self._clock()
        failures: list[str] = []
        errors: dict[str, str] = {}
        executable, digest = _executable_identity(command)  # before launch: what is about to run
        for provider in self.providers:
            try:
                provider.begin()
            except Exception as exc:  # noqa: BLE001 - a provider that cannot open its window cannot be trusted
                failures.append(f"provider_failed:{provider.channel}")
                errors[provider.channel] = _error_text(exc)
        if failures:
            # Nothing is launched while any channel is not being watched.
            refused = RequestOwnership(
                number=len(self.records) + 1,
                executable=executable,
                executable_sha256=digest,
                process={},
                connections=[],
                files=[],
                foreign_events=0,
                violations=sorted(set(failures)),
                canary=canary,
                provider_errors=errors,
            )
            self.records.append(refused)
            self._write(refused)
            return ProcessOutcome(
                returncode=None, launch_error="monitoring provider could not open its window"
            )

        def observe(child: OwnedChildObservation) -> None:
            observation.append(child)
            if outer_observe is not None:
                outer_observe(child)

        def cancel() -> bool:
            stop = _stop_requested(outer_cancel)
            if observation and not self._pending:
                self._pending = self._poll(observation[0], canary)
            return stop or bool(self._pending)

        kwargs = {
            **kwargs,
            "observe": observe,
            "cancel": cancel,
            "record_ownership": True,
            "require_containment": True,
        }
        try:
            outcome = inner(command, **kwargs)
        except BaseException:
            # The runner raised after a child may have started: that request is on the record as unverified, never absent.
            failed = RequestOwnership(
                number=len(self.records) + 1,
                executable=executable,
                executable_sha256=digest,
                process={},
                connections=[],
                files=[],
                foreign_events=0,
                violations=["runner_raised", *failures],
                canary=canary,
            )
            self.records.append(failed)
            self._write(failed)
            raise
        evidence = outcome.ownership
        record = RequestOwnership(
            number=len(self.records) + 1,
            executable=executable,
            executable_sha256=digest,
            process={},
            connections=[],
            files=[],
            foreign_events=0,
            violations=list(failures),
            canary=canary,
            child_token_elevated=self._child_token,
        )
        windows: dict[int, OwnedWindow] = {}
        if evidence is None:
            record.violations.append("ownership_record_missing")
        else:
            record.process = _process_summary(evidence)
            windows = owned_windows(evidence.events, request_start_ns=started)
            if not evidence.complete:
                record.violations.append("ownership_record_incomplete")
            if evidence.active_after_teardown != 0:
                record.violations.append("teardown_not_verified")
            if not canary:
                record.violations += descendant_findings(
                    evidence.events, evidence.root_pid, self.policy
                )
        for provider in self.providers:
            try:
                events = provider.end(frozenset(windows))
            except Exception as exc:  # noqa: BLE001
                record.violations.append(f"provider_failed:{provider.channel}")
                record.provider_errors[provider.channel] = _error_text(exc)
                continue
            owned, foreign, ambiguous = attribute(events, windows)
            record.foreign_events += foreign
            if ambiguous and not canary:
                record.violations.append("ambiguous_attribution")
            if provider.channel == "connections":
                record.connections += [e.detail for e in owned]
            else:
                record.files += [f"{e.mode}:{e.detail}" for e in owned]
        if not canary:
            record.violations += self._policy_violations(record)
        if self._pending:
            record.violations.append(self._pending)
        record.violations = sorted(set(record.violations))
        self._on_request(record, evidence, windows, started, self._clock())
        self.records.append(record)
        self._write(record)
        return outcome

    def _on_request(
        self,
        record: RequestOwnership,
        evidence: OwnedTreeEvidence | None,
        windows: dict[int, OwnedWindow],
        started_ns: int,
        ended_ns: int,
    ) -> None:
        """A finished request's record is about to be stored. The default does nothing; the retrospective monitor logs the
        owned process windows here so a later analysis can attribute a separately captured trace to this request."""

    def _poll(self, child: OwnedChildObservation, canary: bool) -> str:
        try:
            events = child.process_events()
            pids = frozenset(e.pid for e in events if e.kind == "new" and e.pid is not None)
            findings = [] if canary else descendant_findings(events, child.pid, self.policy)
        except Exception:  # noqa: BLE001 - an unreadable owned record stops the request
            return "ownership_unreadable"
        if self.forbid_elevation and self._child_token is None:
            # Read once, while the owned child is alive. An elevated child is stopped; an unreadable token is not guessed.
            self._child_token = self._token_probe(child.pid)
            if self._child_token is True:
                return "child_token_elevated"
        for provider in self.providers:
            try:
                provider.poll(pids)
            except Exception:  # noqa: BLE001
                return f"provider_failed:{provider.channel}"
        return findings[0] if findings else ""

    def _policy_violations(self, record: RequestOwnership) -> list[str]:
        return policy_violations(self.policy, record.connections, record.files)

    def bind_evidence(self, directory: Path) -> None:
        """Point evidence output (and any provider that keeps raw capture files) at the session's own directory."""

        self.evidence_dir = directory
        for provider in self.providers:
            binder = getattr(provider, "bind_directory", None)
            if binder is not None:
                binder(directory)

    def close_and_report(self, directory: Path | None) -> list[str]:
        """Close the providers, then record which trace sessions (if any) are still live. Returns the leaked sessions."""

        self.close()
        leaked = self.leaked_traces()
        if directory is not None and directory.is_dir():
            path = directory / "trace-teardown.json"
            if not path.exists():
                with path.open("x", encoding="utf-8") as handle:
                    json.dump({"trace_sessions_left_running": leaked}, handle, indent=2)
                    handle.write("\n")
        return leaked

    def leaked_traces(self) -> list[str]:
        """After ``close``: trace sessions a provider reports still live. A provider that cannot say is reported as such."""

        found: list[str] = []
        for provider in self.providers:
            checker = getattr(provider, "leaked", None)
            if checker is None:
                continue
            try:
                found += list(checker())
            except Exception:  # noqa: BLE001 - an unreadable session list is itself a finding
                found.append("session list unreadable")
        return sorted(set(found))

    def close(self) -> None:
        """Release whatever a provider holds open (an ETW trace session outlives its process unless stopped)."""

        for provider in self.providers:
            closer = getattr(provider, "close", None)
            if closer is not None:
                try:
                    closer()
                except Exception:  # noqa: BLE001 - best effort; a leaked trace is also swept at the next start
                    pass

    # -- results ------------------------------------------------------------------------------------------------------

    def session_records(self) -> list[RequestOwnership]:
        return [r for r in self.records if not r.canary]

    def violations(self) -> list[str]:
        return sorted({v for r in self.session_records() for v in r.violations})

    def connection_attempts(self) -> int:
        return sum(len(r.connections) for r in self.session_records())

    def teardown_verified(self) -> bool:
        records = self.session_records()
        return bool(records) and all(
            r.process.get("complete") is True and r.process.get("active_after_teardown") == 0
            for r in records
        )

    def summary(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requests_monitored": len(self.session_records()),
            "violations": self.violations(),
            "connection_attempts": self.connection_attempts(),
            "teardown_verified": self.teardown_verified(),
            "channel_coverage": {
                c: sorted({p.coverage for p in self.providers if p.channel == c}) for c in CHANNELS
            },
            "canary": self.canary_report,
        }

    def _write(self, record: RequestOwnership) -> None:
        if self.evidence_dir is None:
            return
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        label = "canary" if record.canary else "request"
        path = self.evidence_dir / f"ownership-{label}-{record.number:05d}.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(record.as_json(), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    # -- canary -------------------------------------------------------------------------------------------------------

    def run_canary(self, inner: Runner = run_bounded) -> dict[str, Any]:
        """Show, with a trusted synthetic child, that each channel reports a known event attributed to the owned tree."""

        self.canary_report = (
            None  # a canary that raises or is interrupted leaves no earlier pass behind
        )
        self._proven = {}
        with tempfile.TemporaryDirectory(prefix="ai113-canary-") as scratch:
            marker = Path(scratch) / "canary-marker.bin"
            marker.write_bytes(b"canary")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[
                    1
                ]  # closed again at once: the attempt is refused, which is still an attempt
            outcome = self._run(
                inner,
                [sys.executable, "-I", "-c", self._canary_script, str(marker), str(port)],
                {"timeout_seconds": 30.0, "max_stdout_bytes": 4096},
                True,
            )
            record = self.records[-1]
            reported = outcome.stdout.decode("utf-8", "replace").split()
            grandchild = _int_or_none(reported[0]) if reported else None
            # The canary reports its own token (0 = standard user) after the descendant's pid; absent means "not shown".
            canary_elevated = _int_or_none(reported[1]) if len(reported) > 1 else None
            evidence_pids = {e[1] for e in record.process.get("events", []) if e[0] == "new"}
            seen = {
                "descendant": grandchild is not None and grandchild in evidence_pids,
                "standard_user": (not self.forbid_elevation)
                or (canary_elevated == 0 and record.child_token_elevated is not True),
                "files": any(
                    _norm(marker) == _norm(entry.partition(":")[2]) for entry in record.files
                ),
                # A create-and-write, then a rename and a delete: a provider that only sees opens would miss all three.
                "writes": all(
                    any(
                        entry.partition(":")[0] == "write"
                        and _norm(Path(scratch) / name) == _norm(entry.partition(":")[2])
                        for entry in record.files
                    )
                    for name in (CANARY_WRITTEN, CANARY_MOVED)
                ),
                # Some ETW network events carry the port in network byte order; accept either spelling of the port.
                "connections": any(
                    entry.rpartition(":")[2] in (str(port), str(((port & 0xFF) << 8) | (port >> 8)))
                    for entry in record.connections
                ),
            }
        self._proven = {
            "files": seen["files"] and seen["writes"],
            "connections": seen["connections"],
        }
        ok = (
            outcome.returncode == 0
            and seen["descendant"]
            and bool(record.process.get("complete"))
            and not [v for v in record.violations if v != "unexpected_descendants"]
        )
        self.canary_report = {"passed": bool(ok and all(seen.values())), "saw": seen}
        return self.canary_report


CANARY_WRITTEN = "canary-written.bin"
CANARY_MOVED = "canary-moved.bin"

_CANARY_SCRIPT = (
    "import os, socket, subprocess, sys\n"
    "marker, port = sys.argv[1], int(sys.argv[2])\n"
    "open(marker, 'rb').read()\n"
    "scratch = os.path.dirname(marker)\n"
    f"written, moved = os.path.join(scratch, {CANARY_WRITTEN!r}), os.path.join(scratch, {CANARY_MOVED!r})\n"
    "with open(written, 'wb') as handle:\n"
    "    handle.write(b'canary')\n"
    "os.replace(written, moved)\n"
    "os.remove(moved)\n"
    "s = socket.socket(); s.settimeout(1.0)\n"
    "try:\n"
    "    s.connect(('127.0.0.1', port))\n"
    "except OSError:\n"
    "    pass\n"
    "s.close()\n"
    "done = subprocess.run([sys.executable, '-I', '-c', 'import os; print(os.getpid())'],\n"
    "                      capture_output=True, text=True)\n"
    "import ctypes\n"
    "print(done.stdout.strip(), int(bool(ctypes.windll.shell32.IsUserAnAdmin())) if os.name == 'nt' else 0)\n"
)


def _error_text(exc: BaseException) -> str:
    """The failure's own message (an OS tool's stderr), bounded; never a path or secret the harness did not already log."""

    return f"{type(exc).__name__}: {exc}"[:400]


def _int_or_none(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _stop_requested(signal: Any) -> bool:
    if signal is None:
        return False
    if hasattr(signal, "is_set"):
        return bool(signal.is_set())
    try:
        return bool(signal())
    except Exception:  # noqa: BLE001 - the runner treats a broken cancel probe as "not cancelled"; so do we
        return False


# -- host sampling providers: diagnostics only, never lifetime-complete -------------------------------------------------


@dataclass
class _SamplingProvider:
    channel: str
    coverage: str = SAMPLED
    errors: int = 0
    _seen: dict[tuple[int, str, str], ChannelEvent] = field(default_factory=dict)

    def begin(self) -> None:
        self._seen = {}

    def poll(self, owned_pids: frozenset[int]) -> None:
        import psutil

        for pid in owned_pids:
            try:
                for event in self._sample(psutil.Process(pid)):
                    self._seen.setdefault((event.pid, event.detail, event.mode), event)
            except psutil.NoSuchProcess:
                continue
            except Exception:  # noqa: BLE001 - recorded: a sampler that cannot look is itself a finding
                self.errors += 1

    def end(self, owned_pids: frozenset[int]) -> list[ChannelEvent]:
        return list(self._seen.values())

    def _sample(self, process: Any) -> list[ChannelEvent]:
        raise NotImplementedError


class SampledConnectionProvider(_SamplingProvider):
    def __init__(self) -> None:
        super().__init__("connections")

    def _sample(self, process: Any) -> list[ChannelEvent]:
        now = time.perf_counter_ns()
        return [
            ChannelEvent(process.pid, f"{c.laddr}->{c.raddr}", now)
            for c in process.net_connections(kind="inet")
        ]


class SampledOpenFileProvider(_SamplingProvider):
    def __init__(self) -> None:
        super().__init__("files")

    def _sample(self, process: Any) -> list[ChannelEvent]:
        now = time.perf_counter_ns()
        return [ChannelEvent(process.pid, f.path, now) for f in process.open_files()]


def default_host_monitor(
    policy: OwnershipPolicy, evidence_dir: Path | None = None
) -> OwnedSessionMonitor:
    """What this host can offer unprivileged: lifetime-complete process/teardown evidence and *sampled* channels.

    Sampled channels never satisfy ``readiness``; a lifetime-complete connection and file provider has to be added."""

    return OwnedSessionMonitor(
        policy,
        [SampledConnectionProvider(), SampledOpenFileProvider()],
        kind="host",
        evidence_dir=evidence_dir,
    )
