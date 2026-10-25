"""Synthetic stand-ins for PR-AI-QUAL-113: a cooperative "complete" provider and a scriptable child.

Nothing here observes the real machine. ``JournalProvider`` reads events that a synthetic child itself reports to a
journal file, so a test can make a monitored child do a known thing (open a file, attempt a connection, start a
descendant, outlive its parent) and check what the monitor attributes, kills and cleans up. The *process* evidence
under test is real: it comes from the owned job object through the real bounded runner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.qualification.ai111.ownership import (
    COMPLETE,
    ChannelEvent,
    OwnedSessionMonitor,
    OwnershipPolicy,
)

#: Run in place of the model: perform the behaviors named by ``TEST_BEHAVIOR:`` prompt lines, report them to the journal,
#: then hand over to the ordinary fake model child.
WRAPPER = r"""
import json, os, runpy, socket, subprocess, sys, time
journal, fake, *argv = sys.argv[1:]
prompt = open(argv[argv.index("-f") + 1], encoding="utf-8").read()
lines = [l.split(":", 1) for l in prompt.splitlines() if l.startswith("TEST_BEHAVIOR:") or l.startswith("TEST_PATH:")]
behaviors = [v for k, v in lines if k == "TEST_BEHAVIOR"]
paths = [v for k, v in lines if k == "TEST_PATH"]

def report(channel, detail, mode="unknown", pid=None):
    with open(journal, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"channel": channel, "pid": pid or os.getpid(), "detail": detail,
                                 "mode": mode, "ts_ns": time.perf_counter_ns()}) + "\n")

for behavior in behaviors:
    if behavior == "read_model":
        report("files", argv[argv.index("-m") + 1], "read")
    elif behavior == "write_outside":
        open(paths[0], "wb").write(b"x")
        report("files", paths[0], "write")
    elif behavior == "egress":
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        client = socket.socket(); client.settimeout(1.0)
        try:
            client.connect(("127.0.0.1", port))
        except OSError:
            pass
        client.close()
        report("connections", f"127.0.0.1:{port}")
    elif behavior == "descendant":
        subprocess.run([sys.executable, "-I", "-c", "pass"])
    elif behavior == "survivor":
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(120)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(paths[0], "w") as handle:
            handle.write(str(child.pid))
    elif behavior == "foreign_noise":
        report("connections", "8.8.8.8:53", pid=4)
sys.argv = [fake, *argv]
runpy.run_path(fake, run_name="__main__")
"""

#: The canary a journal-based monitor uses: it reports exactly what it does, so the provider can be proven against it.
CANARY = r"""
import json, os, socket, subprocess, sys, time
marker, port = sys.argv[1], int(sys.argv[2])
journal, silent = {journal!r}, {silent!r}

def report(channel, detail, mode="unknown"):
    if silent:
        return
    with open(journal, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"channel": channel, "pid": os.getpid(), "detail": detail,
                                 "mode": mode, "ts_ns": time.perf_counter_ns()}}) + "\n")

open(marker, "rb").read()
report("files", marker, "read")
s = socket.socket(); s.settimeout(1.0)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    pass
s.close()
report("connections", f"127.0.0.1:{{port}}")
done = subprocess.run([sys.executable, "-I", "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
print(done.stdout.strip())
"""


class JournalProvider:
    """A provider that claims ``coverage`` and reports what synthetic children wrote to the journal."""

    def __init__(self, channel: str, journal: Path, coverage: str = COMPLETE) -> None:
        self.channel = channel
        self.coverage = coverage
        self.journal = journal
        self._offset = 0
        self.fail_begin = False
        self.fail_end = False

    def begin(self) -> None:
        if self.fail_begin:
            raise RuntimeError("provider could not open its window")
        self._offset = self.journal.stat().st_size if self.journal.exists() else 0

    def poll(self, owned_pids: frozenset[int]) -> None:
        return None

    def end(self) -> list[ChannelEvent]:
        if self.fail_end:
            raise RuntimeError("provider lost its trace")
        if not self.journal.exists():
            return []
        with self.journal.open("rb") as handle:
            handle.seek(self._offset)
            lines = handle.read().decode("utf-8").splitlines()
        rows = [json.loads(line) for line in lines if line.strip()]
        return [
            ChannelEvent(r["pid"], r["detail"], r["ts_ns"], r["mode"])
            for r in rows
            if r["channel"] == self.channel
        ]


def journal_monitor(
    directory: Path,
    *,
    policy: OwnershipPolicy | None = None,
    silent_canary: bool = False,
) -> tuple[OwnedSessionMonitor, Path]:
    journal = directory / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    monitor = OwnedSessionMonitor(
        policy or OwnershipPolicy(),
        [JournalProvider("connections", journal), JournalProvider("files", journal)],
        kind="hermetic",
        canary_script=CANARY.format(journal=str(journal), silent=silent_canary),
    )
    return monitor, journal


def wrapped_command(wrapper: Path, journal: Path, fake_child: Path):
    # The base interpreter: a venv's python.exe is a launcher that adds a second process to the job.
    python = getattr(sys, "_base_executable", sys.executable)
    return lambda _exe, argv: [python, str(wrapper), str(journal), str(fake_child), *argv]


__all__ = [
    "CANARY",
    "WRAPPER",
    "JournalProvider",
    "journal_monitor",
    "wrapped_command",
]
