"""PR-AI-QUAL-114E: the standard-user half of the operator-controlled capture: admission, clock beacons and the monitor.

The operator starts the ETW capture from an Administrator terminal (``capture_control.py``). Everything here runs in an
ordinary token, and the bounded runner stays the only process-lifecycle owner:

* ``CaptureAdmission`` decides, from the operator's capture *as the OS reports it*, whether a downloaded binary may be
  launched at all: the capture is ACTIVE, before its deadline, started by this tool version with this exact provider
  configuration, writing to the directory and run id this session was told to use, and (for a qualification session) a prior
  canary capture proved the providers can see the events monitoring depends on.
* ``RetrospectiveMonitor`` is the ownership monitor for a capture whose events can only be read after it is stopped. It keeps
  the real-time guarantees of ``OwnedSessionMonitor`` (job-object containment, descendant and token checks, verified
  teardown, cancellation through the runner) and records each request's owned process windows in ``windows.jsonl``. It does not
  and cannot say what files a request opened or whether it tried to connect: those findings come from
  ``capture_analysis.py`` after the operator stops the capture, and until then the session is *not* verified. A violation found
  only retrospectively invalidates the run; it is not a real-time fail-closed stop. The independent barrier against egress is the
  operator-managed outbound firewall restriction, not this monitor.
* Clock beacons tie the two clock domains together. The harness creates and deletes a uniquely named file at the start and end
  of the session and records the performance counter around it; the analyzer finds that same file operation in the trace and
  derives a bounded offset between the counter and the trace timestamps. No offset is ever guessed.

The harness never starts, stops or sweeps a trace session, so it can leak none: a session left running is the operator's, and
``capture_control status`` / ``cleanup`` handle it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.utils.managed_process import ProcessOutcome, run_bounded
from src.utils.process_observation import OwnedTreeEvidence
from tools.qualification.ai111 import capture_control as control
from tools.qualification.ai111 import tokens
from tools.qualification.ai111.capture_analysis import ANALYZER_VERSION
from tools.qualification.ai111.ownership import (
    CHANNELS,
    ChannelEvent,
    OwnedSessionMonitor,
    OwnedWindow,
    OwnershipPolicy,
    RequestOwnership,
    Runner,
    _int_or_none,
)
from tools.qualification.ai111.tool_runner import bounded_tool

RETROSPECTIVE = "retrospective_capture"
PROOF_MAX_AGE = timedelta(hours=24)
#: A capture whose per-session file is this full is close to its size cap, where events begin to be lost.
SIZE_WARN_FRACTION = 0.9
_QUERY_TTL_SECONDS = 2.0


class CaptureNotActive(RuntimeError):
    """The operator's capture is not in a state that allows a request to be launched."""


# -- the window log -----------------------------------------------------------------------------------------------------


class WindowLog:
    """Append-only JSON lines, flushed and synced per line, so a crash leaves a readable prefix and no line is rewritten."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, value: dict[str, Any]) -> None:
        line = json.dumps(value, sort_keys=True, allow_nan=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


# -- admission ----------------------------------------------------------------------------------------------------------


@dataclass
class CaptureAdmission:
    """Whether the operator's capture may be relied on right now. ``problems()`` empty means a request may be launched."""

    capture_dir: Path
    run_id: str
    tools: control.TraceTools = field(default_factory=lambda: control.TraceTools(bounded_tool))
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    reports_root: Path = control.REPORTS_ROOT
    proof_path: Path | None = None
    require_proof: bool = True
    monotonic: Callable[[], float] = time.monotonic
    _cache: tuple[float, list[str]] | None = field(default=None, init=False, repr=False)
    manifest: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def static_problems(self) -> list[str]:
        """Directory, manifest, tool version, provider configuration, run identity and the canary proof."""

        problems: list[str] = []
        try:
            directory = control.validate_existing_directory(self.capture_dir, self.reports_root)
        except control.CaptureRefused as exc:
            return [str(exc)]
        manifest = control._read_json(directory / "capture.json")
        self.manifest = manifest
        if manifest is None:
            return ["capture.json is missing or unreadable"]
        if manifest.get("run_id") != self.run_id:
            problems.append(
                f"the capture belongs to run {manifest.get('run_id')!r}, not this session's {self.run_id!r}"
            )
        if manifest.get("provider_config_sha256") != control.provider_config_sha256():
            problems.append("the capture's provider configuration differs from this tool version's")
        if manifest.get("tool_sha256") != control.tool_sha256():
            problems.append(
                "the capture was started by a different capture_control.py than the current one"
            )
        if self.require_proof:
            problems += self._proof_problems(manifest)
        return problems

    def live_problems(self) -> list[str]:
        """The OS's own view of the sessions: all running, as configured, before the deadline, below the size cap."""

        cached = self._cache
        if cached is not None and self.monotonic() - cached[0] < _QUERY_TTL_SECONDS:
            return list(cached[1])
        problems = self._live()
        self._cache = (self.monotonic(), problems)
        return list(problems)

    def _live(self) -> list[str]:
        try:
            directory = control.validate_existing_directory(self.capture_dir, self.reports_root)
            manifest = control._read_json(directory / "capture.json")
            if manifest is None:
                return ["capture.json is missing or unreadable"]
            capture_id = str(manifest.get("capture_id", ""))
            live = self.tools.live()
            state = control.derive_state(directory, live, self.now())
        except control.CaptureRefused as exc:
            return [f"capture status could not be read: {exc}"]
        problems: list[str] = []
        if state.get("state") != "ACTIVE":
            return [
                f"the capture is {state.get('state')}, not ACTIVE: {'; '.join(state.get('problems', []))}"
            ]
        max_mb = int(manifest.get("max_mb_per_session", control.DEFAULT_MAX_MB))
        try:
            names = control.session_names(capture_id)
        except control.CaptureRefused as exc:
            return [str(exc)]
        for spec in control.SESSIONS:
            etl = directory / f"{spec.kind}.etl"
            try:
                info = control.parse_query(self.tools.query(names[spec.kind]))
            except control.CaptureRefused as exc:
                problems.append(f"{spec.kind}: {exc}")
                continue
            problems += control.verify_session(info, spec, etl, max_mb)
            if info.get("buffers_lost") not in (0, None):
                problems.append(f"{spec.kind}: the session has already lost buffers")
            try:
                size = etl.stat().st_size
            except OSError:
                size = 0
            if size >= max_mb * 1024 * 1024 * SIZE_WARN_FRACTION:
                problems.append(
                    f"{spec.kind}: the trace file is near its {max_mb} MB cap; events will soon be lost"
                )
        return problems

    def problems(self) -> list[str]:
        return self.static_problems() + self.live_problems()

    def _proof_problems(self, manifest: dict[str, Any]) -> list[str]:
        if self.proof_path is None:
            return ["no canary proof was supplied: run a canary capture and analyze it first"]
        try:
            proof = json.loads(self.proof_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return [f"the canary proof is unreadable: {exc}"]
        problems: list[str] = []
        if not isinstance(proof, dict) or proof.get("kind") != "canary_capture":
            return ["the canary proof is not an analyzed canary capture"]
        if proof.get("verdict") != "PASS":
            problems.append(f"the canary proof verdict is {proof.get('verdict')!r}, not PASS")
        if proof.get("analyzer_version") != ANALYZER_VERSION:
            problems.append("the canary proof was produced by a different analyzer version")
        if proof.get("provider_config_sha256") != control.provider_config_sha256():
            problems.append("the canary proof used a different provider configuration")
        if proof.get("tool_sha256") != control.tool_sha256():
            problems.append("the canary proof used a different capture_control.py")
        if proof.get("host") != platform.node():
            problems.append("the canary proof is from another host")
        if proof.get("capture_id") == manifest.get("capture_id"):
            problems.append(
                "the canary proof is this capture's own; a prior canary capture is required"
            )
        try:
            finished = datetime.fromisoformat(str(proof.get("finished_utc")))
            finished = finished if finished.tzinfo else finished.replace(tzinfo=UTC)
        except ValueError:
            return [*problems, "the canary proof has no valid finish time"]
        age = self.now() - finished
        if age < timedelta(0) or age > PROOF_MAX_AGE:
            problems.append(f"the canary proof is {age} old (limit {PROOF_MAX_AGE})")
        return problems


class CaptureWindowProvider:
    """A channel whose events are read after the capture stops: it only checks, per request, that the capture is still ACTIVE."""

    coverage = RETROSPECTIVE

    def __init__(self, channel: str, admission: CaptureAdmission) -> None:
        self.channel = channel
        self._admission = admission

    def begin(self) -> None:
        problems = self._admission.live_problems()
        if problems:
            raise CaptureNotActive("; ".join(problems))

    def poll(self, owned_pids: frozenset[int]) -> None:
        return None

    def end(self, owned_pids: frozenset[int]) -> list[ChannelEvent]:
        return []

    def leaked(self) -> list[str]:
        return []  # the harness never starts a trace session, so it cannot leak one


# -- the monitor --------------------------------------------------------------------------------------------------------


class RetrospectiveMonitor(OwnedSessionMonitor):
    """``OwnedSessionMonitor`` for a capture that is analysed after the operator stops it."""

    def __init__(
        self,
        policy: OwnershipPolicy,
        admission: CaptureAdmission,
        *,
        clock: Callable[[], int] = time.perf_counter_ns,
        forbid_elevation: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            policy,
            [CaptureWindowProvider(channel, admission) for channel in CHANNELS],
            kind="host_retrospective",
            clock=clock,
            forbid_elevation=forbid_elevation,
            **kwargs,
        )
        self.admission = admission
        self.log = WindowLog(admission.capture_dir / "windows.jsonl")
        self._begun = False
        self._ended = False
        self._canary_expect: dict[str, Any] | None = None
        self._beacons = 0
        self.end_canary_report: dict[str, Any] | None = None

    # -- readiness ----------------------------------------------------------------------------------------------------

    def provider_problems(self) -> list[str]:
        problems: list[str] = []
        if os.name != "nt":
            problems.append(
                "ownership evidence requires the Windows job object; this host has none"
            )
        if self.forbid_elevation and self._self_elevated() is not False:
            problems.append(
                "privilege: the harness token is elevated or unreadable; the runtime import and every child must run "
                "under a standard-user token"
            )
        problems += [f"capture: {p}" for p in self.admission.problems()]
        return problems

    def readiness(self) -> list[str]:
        problems = self.provider_problems()
        report = self.canary_report
        if report is None:
            problems.append("monitor canary has not been run")
            return problems
        saw = report["saw"]
        if self.forbid_elevation and saw.get("standard_user") is not True:
            problems.append("privilege: the canary child did not report a non-elevated token")
        if not saw.get("descendant"):
            problems.append(
                "process: the canary's short-lived descendant was not in the owned record"
            )
        if not report["passed"] and not problems:
            problems.append("the canary child did not complete cleanly under the monitor")
        return problems

    # -- beacons and the log ------------------------------------------------------------------------------------------

    def _run(
        self, inner: Runner, command: Sequence[str], kwargs: dict[str, Any], canary: bool
    ) -> ProcessOutcome:
        # The opening beacon must precede the first child, so a request can never run before the interval the beacons
        # prove was captured. When the capture is not active nothing is written and the request is refused below.
        if not self._begun and not self.admission.live_problems():
            self._ensure_begun()
        return super()._run(inner, command, kwargs, canary)

    def _ensure_begun(self) -> None:
        if self._begun:
            return
        if self.admission.manifest is None:
            self.admission.static_problems()
        self._begun = True
        manifest = self.admission.manifest or {}
        self.log.write(
            {
                "type": "header",
                "schema": 1,
                "capture_id": manifest.get("capture_id"),
                "run_id": self.admission.run_id,
                "harness_pid": os.getpid(),
                "host": platform.node(),
                "started_utc": datetime.now(UTC).isoformat(),
                "clock": "perf_counter_ns",
                "tool_sha256": control.tool_sha256(),
                "provider_config_sha256": control.provider_config_sha256(),
            }
        )
        self.beacon("start")

    def beacon(self, tag: str) -> dict[str, Any]:
        """Create and delete a uniquely named file inside the capture directory, recording the counter around it."""

        directory = self.admission.capture_dir / "beacons"
        directory.mkdir(exist_ok=True)
        self._beacons += 1
        path = directory / f"beacon-{self._beacons:03d}-{uuid.uuid4().hex[:8]}.tmp"
        before = self._clock()
        with path.open("xb") as handle:
            handle.write(b"b")
        os.remove(path)
        after = self._clock()
        entry = {
            "type": "beacon",
            "n": self._beacons,
            "tag": tag,
            "pid": os.getpid(),
            "path": str(path),
            "before_ns": before,
            "after_ns": after,
        }
        self.log.write(entry)
        return entry

    def _on_request(
        self,
        record: RequestOwnership,
        evidence: OwnedTreeEvidence | None,
        windows: dict[int, OwnedWindow],
        started_ns: int,
        ended_ns: int,
    ) -> None:
        self._ensure_begun()
        policy = self.policy
        self.log.write(
            {
                "type": "request",
                "number": record.number,
                "canary": record.canary,
                "executable": record.executable,
                "executable_sha256": record.executable_sha256,
                "start_ns": started_ns,
                "end_ns": ended_ns,
                "root_pid": None if evidence is None else evidence.root_pid,
                "members": [
                    {"pid": w.pid, "start_ns": w.start_ns, "end_ns": w.end_ns}
                    for w in windows.values()
                ],
                "process_complete": bool(record.process.get("complete")),
                "active_after_teardown": record.process.get("active_after_teardown"),
                "token_elevated": record.child_token_elevated,
                "realtime_violations": list(record.violations),
                "provider_errors": dict(record.provider_errors),
                "canary_expect": self._canary_expect if record.canary else None,
                "policy": {
                    "read_roots": [str(p) for p in policy.read_roots],
                    "write_roots": [str(p) for p in policy.write_roots],
                    "allow_connections": policy.allow_connections,
                    "max_descendants": policy.max_descendants,
                },
            }
        )

    # -- canary -------------------------------------------------------------------------------------------------------

    def run_canary(self, inner: Runner = run_bounded) -> dict[str, Any]:
        """Start of the session: the first beacon, then the trusted canary child (its file and network events are judged
        by the analyzer; its process, descendant and token facts are judged here)."""

        self.canary_report = None
        self._ensure_begun()
        self.canary_report = self._canary_child(inner, "start")
        return self.canary_report

    def _canary_child(self, inner: Runner, tag: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="ai114-canary-") as scratch:
            marker = Path(scratch) / "canary-marker.bin"
            marker.write_bytes(b"canary")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[
                    1
                ]  # closed again at once: a refused attempt is still an attempt
            self._canary_expect = {
                "tag": tag,
                "marker": str(marker),
                "scratch": str(scratch),
                "port": port,
            }
            outcome = self._run(
                inner,
                [sys.executable, "-I", "-c", self._canary_script, str(marker), str(port)],
                {"timeout_seconds": 30.0, "max_stdout_bytes": 4096},
                True,
            )
        record = self.records[-1]
        reported = outcome.stdout.decode("utf-8", "replace").split()
        grandchild = _int_or_none(reported[0]) if reported else None
        canary_elevated = _int_or_none(reported[1]) if len(reported) > 1 else None
        members = {e[1] for e in record.process.get("events", []) if e[0] == "new"}
        saw = {
            "descendant": grandchild is not None and grandchild in members,
            "standard_user": (not self.forbid_elevation)
            or (canary_elevated == 0 and record.child_token_elevated is not True),
            "files": None,
            "writes": None,
            "connections": None,
        }
        ok = (
            outcome.returncode == 0
            and saw["descendant"]
            and bool(record.process.get("complete"))
            and not [v for v in record.violations if v != "unexpected_descendants"]
        )
        self.log.write(
            {
                "type": "canary_report",
                "request": record.number,
                "tag": tag,
                "grandchild_pid": grandchild,
                "reported_elevated": canary_elevated,
                "returncode": outcome.returncode,
            }
        )
        return {
            "passed": bool(ok and saw["descendant"] and saw["standard_user"]),
            "saw": saw,
            "retrospective": True,
        }

    # -- results ------------------------------------------------------------------------------------------------------

    def connection_attempts(self) -> int | None:  # type: ignore[override]
        return None  # unknown until the capture is analysed: never read as zero

    def summary(self) -> dict[str, Any]:
        base = super().summary()
        base.update(
            {
                "mode": RETROSPECTIVE,
                "connection_attempts": None,
                "capture_id": (self.admission.manifest or {}).get("capture_id"),
                "file_and_egress_findings": "pending: only the post-capture analysis can judge them",
                "capture_analysis_required": True,
                "violations_realtime_only": base.get("violations", []),
            }
        )
        return base

    def close_and_report(self, directory: Path | None) -> list[str]:
        """End of the session: the closing canary and beacon. The harness never owns a trace session, so it reports none."""

        if self._begun and not self._ended:
            self._ended = True
            try:
                self.end_canary_report = self._canary_child(run_bounded, "end")
                self.beacon("end")
                self.log.write({"type": "end", "utc": datetime.now(UTC).isoformat()})
            except Exception as exc:  # noqa: BLE001 - a missing closing bracket is recorded, and the analysis refuses it
                self.log.write(
                    {"type": "end_failed", "error": f"{type(exc).__name__}: {exc}"[:300]}
                )
        self.close()
        return []

    def leaked_traces(self) -> list[str]:
        return []


# -- command line -------------------------------------------------------------------------------------------------------


def _build_admission(args: argparse.Namespace, *, require_proof: bool) -> CaptureAdmission:
    return CaptureAdmission(
        capture_dir=args.capture_dir,
        run_id=args.run_id,
        proof_path=getattr(args, "canary_proof", None),
        require_proof=require_proof,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    canary = sub.add_parser(
        "canary",
        help="run the trusted synthetic canary children inside an ACTIVE capture (ordinary terminal; no model, no download)",
    )
    canary.add_argument("--capture-dir", type=Path, required=True)
    canary.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    if tokens.current_process_elevated() is not False:
        print(
            json.dumps(
                {
                    "refused": "this process is elevated or its token is unreadable; run from an ordinary terminal",
                    "nothing_started": True,
                },
                indent=2,
            )
        )
        return 2
    admission = _build_admission(args, require_proof=False)
    monitor = RetrospectiveMonitor(OwnershipPolicy(), admission)
    problems = monitor.provider_problems()
    if problems:
        print(json.dumps({"refused": problems, "nothing_started": True}, indent=2))
        return 2
    monitor.run_canary()
    monitor.close_and_report(None)
    realtime = monitor.readiness()
    report = {
        "start_canary": monitor.canary_report,
        "end_canary": monitor.end_canary_report,
        "realtime_problems": realtime,
        "requests": len(monitor.records),
        "sha256_of_windows_log": hashlib.sha256(
            (admission.capture_dir / "windows.jsonl").read_bytes()
        ).hexdigest(),
        "next": "ask the operator to stop the capture, then run capture_analysis analyze",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    end_ok = bool(monitor.end_canary_report and monitor.end_canary_report["passed"])
    return 0 if not realtime and end_ok else 1


if __name__ == "__main__":
    sys.exit(main())
