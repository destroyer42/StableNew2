# PR-RUNTIME-WEBUI-WATCHDOG-120 - WebUI startup / UI watchdog lifecycle correctness

Result class: **RUNTIME LIFECYCLE CORRECTNESS (bounded).** No queue, runner, NJR, history, process-ownership or retry-policy
change. Execution profile: Standard (Claude Code, Sonnet 5.5).

## Contract

> Slow or temporarily unavailable WebUI startup is allowed within explicit, bounded readiness contracts. A frozen StableNew GUI is not.

The UI-heartbeat watchdog observes **Tk responsiveness only**. It is independent of WebUI readiness: WebUI startup latency is
absorbed by the readiness/startup contracts below, never by suppressing or delaying UI-stall detection.

Unchanged and intentional (verified, not edited): normal managed WebUI startup of roughly 15-30 s; the AppController
initial resource-probe grace (30 s) and the asynchronous bootstrap startup-probe grace (20-30 s derived from the configured
startup timeout); `WebUIProcessConfig.startup_timeout_seconds` (60 s default); `WebUIConnectionController.ensure_connected()`
(bounded fast probe, managed start, warm-up, bounded retries, bounded alternate-port discovery); the executor pre-generation
true-readiness gate; bounded managed restart/recovery; managed-vs-external ownership (an external WebUI is never adopted,
killed or restarted); and the HTTP-100 no-replay rule for dispatched generation POSTs.

## What changed

1. **Watchdog activation order.** `build_v2_app` previously attached and started the watchdog before `MainWindowV2` existed, so it
   monitored a heartbeat nobody was producing yet (contradicting the documented "attach after GUI construction"). It is now attached
   after the window is constructed and bound (the heartbeat ticker is installed during `MainWindowV2` construction), still exactly
   once and idempotently, with the same single watchdog authority (`AppController.attach_watchdog`).
2. **First trigger is independent of host uptime.** `SystemWatchdogV2._last_trigger_ts` and the diagnostics bundle guard
   (`_LAST_BUNDLE_TS`) used `0.0` as "never triggered" while comparing against `time.monotonic()` (host uptime), so the 120 s
   watchdog cooldown (and the 30 s bundle cooldown) silently suppressed the *first* trigger on a recently booted host. "Never
   triggered/emitted" is now an explicit `-inf`. Repeat-event damping is unchanged: one diagnostic per continuing stall, repeats
   suppressed inside the existing cooldown (120 s for `ui_heartbeat_stall`), an eligible later stall after the cooldown triggers
   again. `UI_STALL_S = 10.0` and the cooldown values are unchanged.
3. **WebUI GUI controls no longer block Tk.** The status-panel Launch and Retry callbacks and the periodic 3-disconnect
   autoreconnect in `src/main.py` called `WebUIConnectionController.ensure_connected()` / `reconnect()` synchronously on the Tk
   thread; those routines legitimately outlast the 10 s stall threshold. They now run the same controller call on a tracked
   `ThreadRegistry` thread (`_run_webui_connection_off_tk`) and deliver the result on the Tk thread (`window.run_in_main_thread`,
   the marshalling the async Run submission already uses). A single-flight guard (read/written only on the Tk thread) prevents
   overlapping launch/retry/autoreconnect operations. The panel projects CONNECTING immediately and READY/ERROR when the bounded
   attempt ends; an exception projects ERROR and clears the guard. No new connection controller, state store, queue or process
   manager was added.

Audited and left alone: `PipelineController.start_pipeline_v2` / `start_pipeline` call `ensure_connected` synchronously, but the
production GUI Run/Run Now path already performs that readiness off the Tk thread (`prepare_queue_run_submission` +
`ensure_run_submission_ready` in a tracked thread); the synchronous form is the headless/non-threaded path.

## Evidence

Deterministic tests (injected clocks/events; no real 10/30/60/120 s waits): `tests/services/test_watchdog_first_trigger_120.py`
(first stall triggers at a tiny monotonic origin, healthy heartbeat never triggers, continuing stall is damped and re-triggers only
after the cooldown, runner-stall sentinel, first diagnostics bundle at a tiny origin then cooldown),
`tests/app/test_webui_connection_off_tk_120.py` (Launch/Retry/autoreconnect run off the Tk thread, single flight, bounded
never-ready WebUI ends in ERROR and leaves the GUI usable, exceptions project ERROR; a simulated 30 s WebUI startup produces no
`ui_heartbeat_stall` while a frozen heartbeat afterwards does) and `tests/gui_v2/test_app_factory_watchdog_order_120.py`
(watchdog attaches exactly once, after the heartbeat source is installed). The Phase B1 `test_watchdog_still_triggers_on_true_stall`
is restored to its original form and now passes at any host uptime without seeding. The new tests fail against the previous sources.

## Not changed / follow-ups

* `AppController.on_launch_webui_clicked` / `on_retry_webui_clicked` call the process manager synchronously, but in the production
  application the status-panel callbacks are replaced by the connection-controller callbacks above; their consolidation is separate.
* The ownership/launch-profile and process-logging tests are order-sensitive in some ad-hoc selections on unmodified `main`
  (unrelated; a Phase B1.1 candidate).
* No physical WebUI startup observation was made for this package (an external A1111 may be running on the workstation); the
  deterministic tests are the evidence.
