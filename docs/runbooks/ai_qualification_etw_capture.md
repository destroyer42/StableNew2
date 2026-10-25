# Operator-controlled ETW capture for AI qualification (PR-AI-QUAL-114E)

Kernel-Network and Kernel-File trace sessions cannot be started by a standard-user token, even one in `Performance Log Users`
(measured 2026-10-25: those starts return access denied; DNS-Client and PowerShell starts succeed). The owner chose
**operator-initiated, session-level capture** over a resident privileged broker. Model execution therefore never runs elevated.

## Who runs what

| Step | Terminal | Code | Elevated surface |
| --- | --- | --- | --- |
| start / stop / cleanup | **Administrator** | `tools/qualification/ai111/capture_control.py` (this file is the entire elevated surface) | `logman -ets` start/stop/query on three session names derived from one validated capture id; one fresh directory under `<repo>/reports`; small create-new JSON state files |
| status | any | `capture_control status` | none (read-only) |
| canary, qualification, D12a | ordinary | `capture_session.py`, `physical.py`, `d12a.py` | none; they refuse an elevated or unreadable token |
| analysis | ordinary | `capture_analysis.py` | none; converts the stopped ETL with `tracerpt` as the standard user |

The elevated code does not import models, read prompts, run a downloaded binary, take a command or path from its arguments to
execute, touch the registry, firewall, provider ACLs or groups, register a persistent collector (`-ets` leaves no
configuration) or stay resident. `capture_control.py` imports only the standard library, so it is the whole elevated code
path; always run it as `python -I -B <path to capture_control.py> ...` (isolated mode: no working-directory, `PYTHONPATH` or
user-site imports; no `.pyc` use). Review it and compare its SHA-256 with the value in the completion report before running it
elevated:

```powershell
Get-FileHash tools\qualification\ai111\capture_control.py -Algorithm SHA256
```

## Capture states

`NOT_STARTED -> STARTING -> ACTIVE -> STOPPING -> STOPPED -> VERIFIED`, plus `FAILED`, `EXPIRED` (past its deadline) and
`CLEANUP_REQUIRED` (a StableNewCap session is running when it should not be, or only some sessions are). `status` derives the
state from the directory and from what the OS reports running. Anything other than `ACTIVE` refuses model execution.
`VERIFIED` means an analysis was written, not that it passed: read `verdict` in `analysis.json`.

## Bounds

`logman -ets` has no run-for time, so the capture is bounded by: a per-session size cap (`--max-mb`, 16-1024, default 256;
sequential file mode, never circular, so a full file stops recording and is reported as incomplete), a recorded deadline
(`--minutes`, 1-120, default 30; admission and the analyzer refuse an expired or late-stopped capture), and your `stop`.
`start` refuses unless free space covers 2 x cap x 17 + 2 GiB (the tracerpt XML is far larger than the ETL).

Measured on the target host (2026-10-25, idle desktop): the system-wide Kernel-File session wrote about 60 MB (162k events) in 171 s, roughly 21 MB per minute, and the network and DNS sessions about 20 MB and 9 MB. Plan windows of a few minutes, start the capture just before the session and stop it right after, and size `--max-mb` for it (256 MB is about 12 minutes). Admission refuses new requests once a file reaches 90% of its cap, and an analysis of a capture that reached 98% is INCONCLUSIVE.

## Live canary (no downloaded executable, no model)

Run from the repository checkout. Replace `<id>` with the capture id that `start` prints.

1. Administrator terminal:

   ```powershell
   python -I -B tools\qualification\ai111\capture_control.py start --evidence-dir reports\ai114\ai114e-canary-1\capture --run-id ai114e-canary-1 --max-mb 64 --minutes 10
   ```

2. Ordinary terminal:

   ```powershell
   python -m tools.qualification.ai111.capture_control status --evidence-dir reports\ai114\ai114e-canary-1\capture
   python -m tools.qualification.ai111.capture_session canary --capture-dir reports\ai114\ai114e-canary-1\capture --run-id ai114e-canary-1
   ```

3. Administrator terminal:

   ```powershell
   python -I -B tools\qualification\ai111\capture_control.py stop --capture-id <id> --evidence-dir reports\ai114\ai114e-canary-1\capture
   ```

4. Ordinary terminal:

   ```powershell
   python -m tools.qualification.ai111.capture_analysis analyze --capture-dir reports\ai114\ai114e-canary-1\capture
   ```

A `PASS` analysis (kind `canary_capture`) is the proof a qualification session needs (`--canary-proof analysis.json`, same host,
same `capture_control.py` and provider configuration, under 24 h old, from a *different* capture). A qualification capture is the
same four steps with `physical.py` / `d12a.py` in step 2, followed by `stage_a_report --capture-analysis`.

## When something goes wrong

* `start` reports `FAILED`: nothing is left running; read `problems` and `state-02-failed.json`. Fix the cause (usually free
  space, a broad directory ACL, or a stale session) and start again; a new attempt always uses a new directory.
* `start` or `stop` reports `CLEANUP_REQUIRED`: a session could not be proved gone. From the Administrator terminal run the
  `logman stop "<name>" -ets` lines it printed, then `logman query -ets` and confirm no `StableNewCap-` row remains. Only
  `StableNewCap-*` sessions are ever yours to stop; never stop `NT Kernel Logger`, `Circular Kernel Context Logger` or other
  applications' sessions.
* Shell closed or crashed, `stop` forgotten, or the machine rebooted: `capture_control cleanup --capture-id <id>` (id from
  `capture.json` in the directory) stops anything still running. A reboot ends `-ets` sessions on its own; the directory then
  shows `STOPPED` with a problem "no recorded operator stop", and the analysis will treat the run as invalid. A capture that
  was not stopped cleanly is never a pass; start a new one.
* Residual: the capture directory is user-writable by design (the standard-user harness writes `windows.jsonl` and
  `beacons/` into it) and the elevated trace writer creates the ETL files in it. `start` refuses a pre-existing ETL path and the
  analyzer refuses a linked ETL and one whose header does not name this capture, but a write by another process into the
  directory during the capture is detected only because it appears as an out-of-policy file event in the capture itself.
* A session that runs after its deadline is `EXPIRED`: stop it, and discard the run.

## Privacy and storage

Raw ETL and the derived XML are system-wide traces. They stay in the Git-ignored directory under `reports/`, which `start`
refuses to use if its ACL grants `Everyone`, `BUILTIN\Users`, `Authenticated Users`, `INTERACTIVE` or `Guests` (matched
against this machine's own names for those well-known SIDs, so a localized Windows is covered; an ACL listing the tool cannot
parse is refused; confirm the ACL yourself anyway). The analyzer deletes the XML after a completed analysis
(`--keep-xml` keeps it for diagnosis), writes only owned-process evidence (executable file names, counts, policy violations and
the owned paths/addresses that violated policy), and nothing exports a raw trace. Do not attach ETL or XML to a PR, CI artifact
or chat; delete the directory when the run is no longer needed.

## What this is not

Retrospective ETW evidence proves what happened in the captured interval; it does not stop anything. Real-time containment is
`run_bounded` (job object, caps, timeout, cancel, descendant and token checks). The preventive egress barrier is the
operator-managed outbound firewall restriction, which these tools neither create nor verify. A violation found only after the
run invalidates the run. Known ETW limits remain: a truncate or memory-mapped write of an existing file opened for read is not
seen, and activity outside the owned job is not attributed.
