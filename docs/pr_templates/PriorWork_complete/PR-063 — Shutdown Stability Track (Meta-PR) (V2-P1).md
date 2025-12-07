PR-063 — Shutdown Stability Track (Meta-PR) (V2-P1)
A coordinated, multi-step plan to fully eliminate lingering Python/WebUI processes on exit.
Summary

StableNew still leaves behind one or more python.exe processes after GUI shutdown, even after PR-046/047 and the new PR-057 → PR-062 attempt. This is due to a mix of:

WebUI subprocesses spawning independent child processes

Threads that keep the Python interpreter alive

Journey tests that mis-detect unrelated Python processes

Tests killing StableNew with TerminateProcess, bypassing real shutdown

Lack of visibility into what’s still alive when shutdown “hangs”

PR-063 introduces a coordinated Shutdown Stability Track: a controlled sequence of PRs that must be implemented and verified in order. Codex must not skip steps or reorder them.

This PR does not implement new code. Instead, it defines the integration workflow, success criteria, and step-by-step execution for PR-057 → PR-062, ensuring a stable environment for them to succeed.

Objectives

Establish a controlled, deterministic shutdown stack that:

Always terminates the WebUI process tree

Always terminates all StableNew-owned threads

Always closes Tk cleanly

Leaves zero StableNew or WebUI Python processes running

Ensure journey tests measure real leaks, not false positives.

Ensure shutdown behaviors are tested using the real GUI exit path, not terminate().

Provide Codex with a strict execution order to prevent drift or partial fixes.

Allowed Files

This PR modifies documentation only.
No code changes permitted.

docs/pr_templates/PriorWork_incoming/PR-063-SHUTDOWN-STABILITY-TRACK.md (this file)

docs/Shutdown_Stability_Roadmap.md (optional helper doc, if created)

Forbidden Files

All files under:

src/**

tests/**

tools/**

This PR never touches code.

Shutdown Stability Sequence (MANDATORY ORDER)

Codex must follow this order exactly, verifying each stage before moving to the next.

Stage 1 — PR-057: WebUI Process Tree Termination & Diagnostics

Goal:
WebUI’s entire process tree must be killed on shutdown.

What Codex must verify:

Killing WebUI stops all children launched by webui-user.bat.

stop_webui() logs PID, exit code, and kill path.

After shutdown, no subprocesses tied to WebUI remain.

Gate:
Journey test still allowed to fail at this point.
Move to PR-058 next.

Stage 2 — PR-058: GUI Shutdown Watchdog & Hardened Close Path

Goal:
Ensure shutdown is deterministic and cannot hang.

Codex must:

Add shutdown watchdog

Add GuiInvoker.dispose() handling

Ensure _on_destroy cannot recursively call shutdown

Ensure root.quit() triggers root.mainloop() exit cleanly

Gate:
Codex must confirm:

GUI closes without freezing (manual/local)

Shutdown logs show _shutdown_completed=True
Proceed to PR-060.

Stage 3 — PR-060: Process Inspection & Journey Test Fix

Goal:
Ensure journey tests detect only true StableNew/WebUI leaks.

Codex must implement:

Proper psutil-based filtering

Ignore unrelated python.exe

Correct detection of SD-WebUI processes

Remove proc.terminate() as normal path

Gate:
Test still allowed to fail at this point, because we haven’t added auto-exit yet.
Proceed to PR-061.

Stage 4 — PR-061: Deep Shutdown Instrumentation

Goal:
Expose actionable logging on what’s still alive.

Codex must:

Log all live threads at shutdown

Log all child processes after shutdown

Provide explicit insight into remaining blockers

Gate:
Codex must confirm via log output:

Visible list of threads

Visible list of children
Proceed to PR-062.

Stage 5 — PR-062: Headless Auto-Exit Mode for Real Shutdown Tests

Goal:
Journey tests finally use the real GUI exit path, not process termination.

Codex must:

Implement schedule_auto_exit()

Add env variable STABLENEW_AUTO_EXIT_SECONDS

Modify journey test to rely ONLY on this clean shutdown path

Validate StableNew closes itself properly over multiple cycles

Gate (must pass):
After implementing PR-062, the journey test MUST PASS:

test_shutdown_relaunch_leaves_no_processes


Meaning:

No StableNew-related python.exe remain

No SD-WebUI python.exe remain

App exit path is stable

Process tree is clean

Rollout Order (Codex MUST follow)

Implement PR-057 → merge

Implement PR-058 → merge

Implement PR-060 → merge

Implement PR-061 → merge

Implement PR-062 → merge

Re-run journey test suite until green

Codex must not modify PR-057 or PR-058 once PR-060+ logic is applied unless the shutdown inspector logs contradict behavior.

Definition of Done

The Stability Track is complete only if ALL conditions are met:

✔ GUI closes cleanly when user presses X

✔ GUI closes cleanly via auto-exit in journey tests

✔ No SD-WebUI subprocesses remain

✔ No StableNew python.exe processes remain

✔ No non-daemon threads keep interpreter alive

✔ Journey shutdown test passes consistently across 3–5 cycles

Risks & Constraints

Windows process tree behavior is not deterministic; must use taskkill /T /F.

Third-party WebUI scripts may spawn subprocesses unexpectedly.

Thread enumerations may reveal plugin-related threads requiring future cleanup.

Strict sequencing is required to avoid partial/overlapping fixes.

Follow-On Work (Not Included Here)

If shutdown logs (PR-061) identify more issues, follow-on PRs may include:

PR-064 — Queue Worker Hard Shutdown

PR-065 — Preview/Subscription Thread Sanitization

PR-066 — Tk/Thread race patch (only if logs demand)