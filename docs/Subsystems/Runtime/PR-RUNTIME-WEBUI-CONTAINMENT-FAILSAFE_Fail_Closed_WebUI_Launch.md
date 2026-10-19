# PR-RUNTIME-WEBUI-CONTAINMENT-FAILSAFE: fail-closed WebUI launch

Contract: on Windows, a WebUI process StableNew launches cannot execute or create a descendant until it has been assigned to
an anonymous, kill-on-close job object owned by its `WebUIProcessManager`. If containment fails, the new child is killed and
startup fails visibly. External WebUI processes are never touched. Living truth is `QUEUE_AND_RUNTIME.md` (sections 7.2 and 12,
invariant 16); this record is the evidence for the change.

## Starting defects (reproduced on the unmodified manager)

* `_start_locked` created the child with `subprocess.Popen` and only then called `_attach_pid_to_container`, so the child could
  run and create grandchildren before it was in the job.
* The attach result was ignored (`add_pid` returning `False` was not even logged; an exception was logged at DEBUG), and a
  `NullProcessContainer` did not prevent launch: a refused assignment, a null container or a container that failed to build all
  produced a running, uncontained, "owned" WebUI.
* A failure after `Popen` (output capture, orphan monitor) wrapped the error but left the child, the container and the manager's
  `_process`/`_pid`/ownership state in place.
* A container built at construction was reused by every later launch, including after the process ended on its own.
* `stop_webui` could block indefinitely: with a descendant (here an orphaned grandchild no tree walk finds) holding the stdout pipe,
  `_stop_output_capture` called `stream.close()` on a stream whose reader thread was blocked in `readline`; close waits on the
  buffer lock that read holds. Reproduced: `stop_webui` had not returned after 30 s.

## What changed

* `src/utils/managed_process.py`: `launch_contained` is the one place a contained child is created, placed and resumed (suspended
  start, assignment, resume, kill-and-release on any failure or interrupt). `_spawn_contained` (`run_bounded`, `ManagedProcess`)
  now calls it, so PR #150's behavior is shared rather than duplicated. `ProcessContainer.resume_suspended` (Windows: via
  `NtResumeProcess`) keeps the resume with the container that created the job.
* `src/api/webui_process_manager.py`: a fresh container per launch; the child is published (pid, ownership, launch command, readers,
  orphan monitor) only after containment and resume succeed; `WebUIContainmentError` (a `WebUIStartupError`) for every
  containment failure; `_unwind_failed_launch` kills the child through its job, waits (bounded), releases the container, stops the
  readers and monitor and resets all launch state for any failure or interrupt after publication; `_reap_previous_launch` releases
  the container/readers/pid of a launch that ended on its own; `restart_webui` stops at a containment failure instead of looping;
  `get_status()["last_startup_failure"]`; output readers drain within `READER_DRAIN_SECONDS` and a still-blocked reader is
  abandoned with its stream left open.
* Tests: `tests/api/test_webui_containment_failsafe.py` (fake-process tests that run everywhere, and real job-object tests on the
  base interpreter that the hosted Windows lane executes); the autouse `tests/conftest.py` double is now an explicit successful
  container (`RecordingContainer`) instead of a `NullProcessContainer`, which a fail-closed launch correctly refuses; the file is a
  named target of `tools/ci/run_windows_lane.py` and pinned by `tests/tools/test_ci_windows_lane.py`.

## Launch modes validated on Windows (real job objects)

Direct interpreter launch, a `.cmd` launcher through `cmd.exe /d /s /c` with `shell=False`, and the optional new-console mode
(`STABLENEW_WEBUI_NEW_CONSOLE=1`), each with output capture (not in new-console mode) and shutdown killing the whole tree.
`CREATE_NEW_PROCESS_GROUP` is kept and `CREATE_BREAKAWAY_FROM_JOB` is never set. No physical Forge/A1111 launch was run.

## Residual risks

* An asynchronous interrupt delivered between `subprocess.Popen` returning and the next statements, or between `launch_contained`
  returning and `_publish_launch` starting, is not covered by a handler; the job handle is only closed with the process (kill on
  close), so such a child would stay contained but running until StableNew exits.
* Linux and other platforms keep best-effort containment, reported with a WARNING.
* A descendant that escapes containment and holds the output pipes is not killed by the manager; its reader is abandoned so
  shutdown is bounded, and the pipe closes when the descendant exits.
* The occupied-endpoint check runs before an earlier, ended launch is reaped: if that launch's root exited but its own server
  descendant still holds the port, the next start is refused as "external" and the descendant keeps running (still contained;
  it dies on `stop`, GUI exit or process exit).
* The 2 s reader drain can expire while a heavy WebUI is still dying; the reader is then abandoned and ends at EOF. Each launch
  uses fresh output tails, so an abandoned reader cannot write into the next launch's tails.
* `main_window_v2.py` swallows a startup exception; the manager therefore also logs a containment failure itself and keeps it in
  `get_status()["last_startup_failure"]`.
* The hosted `windows` check is the first run on the hosted runner; qualification against a real Forge launch is not part of this
  package.
