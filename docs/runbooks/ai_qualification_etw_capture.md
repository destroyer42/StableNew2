# Operator-controlled ETW capture for AI qualification (PR-AI-QUAL-114E)

Kernel-Network and Kernel-File trace sessions cannot be started by a standard-user token, even one in `Performance Log Users`
(measured 2026-10-25: those starts return access denied; DNS-Client and PowerShell starts succeed). The owner chose
**operator-initiated, session-level capture** over a resident privileged broker. Model execution therefore never runs elevated.

## Who runs what

| Step | Terminal | Code | Elevated surface |
| --- | --- | --- | --- |
| one-time setup | **Administrator** (`powershell -NoProfile`) | OS commands only (below) | a system-wide Python and a protected copy of `capture_control.py` |
| start / stop / cleanup | **Administrator** | the protected copy of `tools/qualification/ai111/capture_control.py` (the entire elevated surface) | `logman -ets` start/stop/query on three session names derived from one validated capture id; one fresh directory under `<repo>/reports`; small create-new JSON state files |
| status | any | `capture_control status` | none (read-only) |
| canary, qualification, D12a | ordinary | `capture_session.py`, `physical.py`, `d12a.py` | none; they refuse an elevated or unreadable token |
| analysis | ordinary | `capture_analysis.py` | none; converts the stopped ETL with `tracerpt` as the standard user |

The elevated code does not import models, read prompts, run a downloaded binary, take a command or path from its arguments to
execute, touch the registry, firewall, provider ACLs or groups, register a persistent collector (`-ets` leaves no
configuration) or stay resident. `capture_control.py` imports only the standard library, so it is the whole elevated code path.

## Why the elevated Python must be protected

An administrator token that runs code a standard-user process can edit is not a privilege boundary: a same-user process could
change the script, the interpreter or the standard library between your review and your run. So every elevated command first
proves its own runtime (`runtime_trust_problems`) and **refuses, before starting or stopping anything**, unless:

* it was started `python -I -B ...` (isolated, no bytecode) and is not a virtual environment;
* the script, the interpreter, `os.py`, the Python base prefix, every `sys.path` entry and the directory of every loaded
  module are owned by Administrators, SYSTEM or TrustedInstaller and grant no write/replace/re-permission right
  (`F M W D WD AD DC WDAC WO GA GW`) to anyone else, and no ancestor directory lets a non-administrator delete, rename or
  re-permission them (creating a child is fine); and
* no module was loaded from outside the script's directory or the base prefix.

It does not walk every file of the install (that is what a system-wide install in `Program Files` guarantees), and it does not
make `logman`/`icacls` trustworthy beyond locating them by `GetSystemDirectoryW`. A per-user Python, a venv and the checkout
all fail by design. This host currently has only per-user Pythons, so setup below is a prerequisite.

### One-time setup (Administrator terminal, `powershell -NoProfile`)

1. Install a 64-bit CPython **for all users** from python.org (default `C:\Program Files\Python3xx`). Do not install packages
   into it. This is an owner action: it downloads and installs software.
2. Create the protected copy from the reviewed file:

   ```powershell
   $dir = Join-Path $env:ProgramData 'StableNewCap'
   New-Item -ItemType Directory -Path $dir | Out-Null
   icacls $dir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
   icacls $dir /setowner '*S-1-5-32-544' | Out-Null
   Copy-Item <checkout>\tools\qualification\ai111\capture_control.py (Join-Path $dir 'capture_control.py')
   (Get-FileHash (Join-Path $dir 'capture_control.py') -Algorithm SHA256).Hash
   ```

   Compare the printed hash with the SHA-256 in the completion report. Copy again after any change to the checkout's file; the
   copy refuses to run if the checkout's `capture_control.py` is not byte-identical (`--repo-root` check), so the hash the
   analysis and admission compare is the hash of what actually ran.

If a check fails, `start`/`stop`/`cleanup` print which path is writable or user-owned and do nothing.

## Capture states

`NOT_STARTED -> STARTING -> ACTIVE -> STOPPING -> STOPPED -> VERIFIED`, plus `FAILED`, `EXPIRED` (past its deadline) and
`CLEANUP_REQUIRED` (a StableNewCap session is running when it should not be, or only some sessions are). `status` derives the
state from the directory and from what the OS reports running. Anything other than `ACTIVE` refuses model execution.
`VERIFIED` means an analysis was written, not that it passed: read `verdict` in `analysis.json`; every analysis of a capture is
listed in the next result (`earlier_analyses`).

## Bounds and capacity

`logman -ets` has no run-for time, so the capture is bounded by: a per-session size cap (`--max-mb`, 16-1024, default 256;
sequential file mode, never circular, so a full file stops recording and is reported as incomplete), a recorded deadline
(`--minutes`, 1-120, default 30; admission and the analyzer refuse an expired or late-stopped capture), and your `stop`.
`start` refuses unless free space covers 2 x cap x 17 + 2 GiB (the tracerpt XML is far larger than the ETL).

Measured on the target host (2026-10-25, idle desktop, 171 s): Kernel-File 62.9 MB (162,847 events, about 386 bytes each, roughly
21 MB per minute and burst-dominated), Kernel-Network 19.9 MB, DNS-Client 9.4 MB. The owned processes were 0.68% of the events: the
volume is the whole machine, not the model. A **64 MB cap therefore holds under about 3 minutes** and cannot also carry the canary
children; use at least 256 MB for any canary and qualification capture.

Admission enforces this before every request instead of hoping. For each session it projects
`size now + max(measured average rate, floor rate) x (request timeout + 60 s) + 32 MiB` (the buffers `logman stop` still flushes;
floor rates: file 400 kB/s, network 160 kB/s, DNS 80 kB/s) and refuses the request if that exceeds 90% of the cap, or if the
request plus 60 s would pass the capture deadline. An analysis of a capture whose file reached 98% of its cap is INCONCLUSIVE, and
so is a live session that reports buffers lost (an unreadable counter counts as lost). Largest request timeout per capture is
roughly `(0.9 x cap - 32 MiB) / rate - 60 s`: about 7 minutes at 256 MB and about 36 minutes at 1024 MB at the floor rate.

**Stage A sizing:** one capture per model arm, `--max-mb 1024` (512 only for an arm of 10 minutes or less), `--minutes` = the arm's
planned duration + 15, started just before the arm and stopped right after it, a start and an end canary inside each capture and a
separate analysis per capture. Never widen a cap to rescue a failed window; the zero-loss rule stays.
The 1024 MB gate needs 36 GiB free for the conversion.

## Live canary (no downloaded executable, no model)

Run from the repository checkout. Replace `<id>` with the capture id that `start` prints and `<py>` with the system-wide
interpreter (for example `C:\Program Files\Python314\python.exe`).

1. Administrator terminal:

   ```powershell
   & <py> -I -B "$env:ProgramData\StableNewCap\capture_control.py" --repo-root <checkout> start --evidence-dir <checkout>\reports\ai114\ai114e-canary-2\capture --run-id ai114e-canary-2 --max-mb 256 --minutes 10
   ```

2. Ordinary terminal:

   ```powershell
   python -m tools.qualification.ai111.capture_control status --evidence-dir reports\ai114\ai114e-canary-2\capture
   python -m tools.qualification.ai111.capture_session canary --capture-dir reports\ai114\ai114e-canary-2\capture --run-id ai114e-canary-2
   ```

3. Administrator terminal:

   ```powershell
   & <py> -I -B "$env:ProgramData\StableNewCap\capture_control.py" --repo-root <checkout> stop --capture-id <id> --evidence-dir <checkout>\reports\ai114\ai114e-canary-2\capture
   ```

4. Ordinary terminal:

   ```powershell
   python -m tools.qualification.ai111.capture_analysis analyze --capture-dir reports\ai114\ai114e-canary-2\capture
   ```

A `PASS` analysis (kind `canary_capture`) is the proof a qualification session needs (`--canary-proof analysis.json`). The proof
must come from a *different* capture, the same host, the same `capture_control.py`, provider configuration, `capture_analysis.py`
and analyzer version, and be under 24 h old; **any other analysis of that capture that is FAIL or unreadable voids it** (an
earlier INCONCLUSIVE does not). A qualification capture is the same four steps with `physical.py` / `d12a.py` in step 2,
followed by `stage_a_report --capture-analysis`.

## When something goes wrong

* A command prints `REFUSED ... runtime is not protected`: nothing was started or stopped. Fix the named path (or use the protected
  copy and the system-wide interpreter) and run it again.
* `start` reports `FAILED`: nothing is left running; read `problems` and `state-02-failed.json`. Fix the cause (usually free
  space, a broad directory ACL, or a stale session) and start again; a new attempt always uses a new directory.
* `start` or `stop` reports `CLEANUP_REQUIRED`: a session could not be proved gone. From the Administrator terminal run the
  `logman stop "<name>" -ets` lines it printed, then `logman query -ets` and confirm no `StableNewCap-` row remains. Only
  `StableNewCap-*` sessions are ever yours to stop; never stop `NT Kernel Logger`, `Circular Kernel Context Logger` or other
  applications' sessions.
* Shell closed or crashed, `stop` forgotten, or the machine rebooted: `cleanup --capture-id <id>` (id from `capture.json` in the
  directory) stops anything still running. A reboot ends `-ets` sessions on its own; the directory then shows `STOPPED` with a
  problem "no recorded operator stop", and the analysis will treat the run as invalid. A capture that was not stopped cleanly is
  never a pass; start a new one.
* Residual: the capture directory is user-writable by design (the standard-user harness writes `windows.jsonl` and `beacons/`
  into it) and the elevated trace writer creates the ETL files in it. `start` refuses a pre-existing ETL path, and the analyzer
  refuses a linked ETL and one whose header does not name this capture. While a session runs, `windows.jsonl` is held open with a
  deny-write share mode so no other process can open it for writing, and the analysis is INCONCLUSIVE if the directory holds any
  entry this tool chain does not create (or a link). **A write into the directory by another process is not otherwise detected:**
  the trace is filtered to owned processes, so such a write is not an event in the analysis.
* A session that runs after its deadline is `EXPIRED`: stop it, and discard the run.

## Privacy and storage

Raw ETL and the derived XML are system-wide traces. They stay in the Git-ignored directory under `reports/`, which `start`
refuses to use if its ACL grants `Everyone`, `BUILTIN\Users`, `Authenticated Users`, `INTERACTIVE` or `Guests` (matched
against this machine's own names for those well-known SIDs, so a localized Windows is covered; an ACL listing the tool cannot
parse is refused; confirm the ACL yourself anyway). The analyzer deletes the XML after a completed analysis
(`--keep-xml` keeps it for diagnosis), writes only owned-process evidence (executable file names, counts, policy violations and
the owned paths/addresses that violated policy), keeps beacon files as relative names, and nothing exports a raw trace. Do not
attach ETL or XML to a PR, CI artifact or chat; delete the directory when the run is no longer needed.

## What this is not

Retrospective ETW evidence proves what happened in the captured interval; it does not stop anything. Real-time containment is
`run_bounded` (job object, caps, timeout, cancel, descendant and token checks). The preventive egress barrier is the
operator-managed outbound firewall restriction, which these tools neither create nor verify. A violation found only after the
run invalidates the run. Known ETW limits remain: a truncate or memory-mapped write of an existing file opened for read is not
seen, and activity outside the owned job is not attributed.

## How a process is placed in a request (analyzer v3)

An owned pid's window runs from the request launch to the runner's observed exit, which is after the real exit. An event is
**owned** when its measured clock interval (zero slack) lies inside exactly one window and nothing else touches it; **ambiguous**
when the slack-widened interval touches a window edge, there is no timestamp or clock, or several windows qualify; **recycled**
(counted as foreign) when it is clearly outside every window of that pid; the verdict is FAIL on any hard violation, otherwise
INCONCLUSIVE on any capture problem or ambiguity, otherwise PASS. Beacon offsets must intersect (they may miss by at most one
timestamp slack, 5 ms, and the interval then spans the gap). The first live capture's 195 recycled-pid events preceded the
windows by 24.2-56.1 s; the 14 events v1 called ambiguous sat inside the 5 ms slack before the observed exit (the closest
0.66 ms, the furthest 4.90 ms before it), and both verdicts (v1 INCONCLUSIVE, v2 PASS) are kept in that capture directory.
