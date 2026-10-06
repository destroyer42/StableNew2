# PR-RUNTIME-WEBUI-LIFECYCLE-130 - WebUI-family lifecycle convergence, recovery truth, runtime selection

Result class: **RUNTIME LIFECYCLE CORRECTNESS (bounded).** No queue, runner, NJR, history, retry-policy or backend change.
`WebUIProcessManager` remains the sole process lifecycle authority; there is no second manager, runner or fallback runtime.

## Contract

> There is one authoritative managed WebUI lifecycle from application startup through readiness, recovery, status
> projection and resource refresh. A proven-ready runtime leaves StableNew fully READY with fresh resource lists.

External A1111 or Forge is observed/used where supported but never adopted, stopped, restarted or killed; an occupied
external endpoint stays action-required. Native SVD and Comfy work stays independently admissible: nothing on the queue
path consults the WebUI manager, the WebUI connection controller or the WebUI readiness probe.

## What was wrong (each reproduced by a failing deterministic test before the repair)

| Finding | Behaviour on the previous source |
|---|---|
| Startup never delivered the manager | `bootstrap_webui` waited for readiness before the manager reached the window/controller; a timeout or early exit discarded it |
| Competing managers | `WebUIProcessManager.__init__` always replaced the global registration; `WebUIConnectionController.ensure_connected` built a second manager (and `start()` could launch a duplicate); `stop()` of any manager cleared the owner's registration |
| Recovery was invisible | a successful `restart_webui` proved TRUE-READY on a throwaway client and told nobody: no READY event, no resource refresh |
| Stale poison | readiness backoff recorded while the owned runtime restarted survived the proof and kept the executor classifying it `startup_backoff` |
| Stale PID | the connection controller kept the dead process's PID, so strict readiness failed after every restart |
| No operator choice | Engine Settings exposed the URL and autostart but not `webui_runtime_identity` |

## What changed

1. **One registration rule.** A manager registers globally unless another manager already owns a live process; `stop()`
   clears only its own registration; `start()` refuses to launch while another manager owns a live process.
2. **Readiness epochs.** `WebUIProcessManager.mark_ready(source=...)` records one proven-ready epoch, clears only stale
   readiness backoff for the endpoint, and notifies listeners (a listener added later receives the current epoch once). Only
   a real proof calls it: the startup probe, or TRUE-READY after an owned restart (never a restart without a proof).
3. **One observer.** `WebUIConnectionController.attach_process_manager` follows the manager's epochs: it adopts the new
   PID, drops the cached strict verdict, sets READY and announces it once through its existing ready callbacks, which is
   how `AppController.on_webui_ready` runs the single resource refresh (and resets the shared client's startup grace and
   failure/cooldown state so a stale cooldown cannot suppress that refresh). `ensure_connected` reuses the attached or
   active owned manager and only builds one when none exists.
4. **Startup truth.** `bootstrap_webui` delivers the manager before starting it and waits through
   `wait_for_managed_startup`: bounded 5 s slices that re-check the process between slices, so an early exit is reported
   with PID, runtime identity, launch profile, endpoint, exit code and a bounded stdout/stderr tail (40 lines / 4000
   characters) instead of after the full timeout. Connection refusals while an owned process boots are expected, so
   readiness backoff recorded by a slice is cleared. A slow startup is allowed up to the configured timeout and a timeout
   keeps truthful ownership; nothing is killed. The wait runs on the existing bootstrap worker thread, never on Tk.
5. **Status wiring.** The periodic status check refreshes the sidebar once per readiness epoch and no longer triggers a
   second `on_webui_ready`.
6. **Runtime selector.** Engine Settings has one application-level selector: **Default - Managed Forge** (persists a blank
   identity) and **A1111 Compatibility** (persists `webui_runtime_identity = a1111_webui`). It shows the endpoint from the
   existing identity-aware resolver, moves an identity-default URL with the selection, keeps a custom URL, never writes an
   identity-default endpoint as an explicit URL, writes the identity only when the selection changed, and fails closed on an
   invalid persisted identity (neither runtime is selected and saving is blocked until one is chosen).

## Runtime switching is restart-required

Saving a different runtime only changes configuration. The running manager is not stopped, adopted or switched. Because
new image work is built for the configured identity, a job created before the restart is rejected before dispatch by the
existing runtime-identity guard until StableNew is restarted; the dialog says so. There is no fallback in either direction.

## Evidence

Deterministic (fake process and probes, no waits): `tests/api/test_webui_process_manager_lifecycle_130.py` (registration,
duplicate refusal, one epoch per proven restart, backoff cleared yet a real later failure still recorded, late listeners,
exit diagnostics, startup slices), `tests/controller/test_webui_lifecycle_convergence_130.py` (bootstrap delivery and
diagnostics, single-manager connection, one READY event, resources reach `AppState` and its listeners after an
unavailable -> restart -> TRUE-READY sequence, a failed refresh never becomes final, no second refresh from the periodic
wiring, saving a runtime switch leaves the running manager untouched),
`tests/gui_v2/test_engine_settings_runtime_selector_130.py` and
`tests/integration/test_webui_lifecycle_non_webui_admission_130.py` (a video job completes through the ordinary queue while
the WebUI family is down and its backoff is poisoned, consulting none of it).

Physical (no generation): one bounded startup and one owned restart of the configured managed Forge on the target
workstation. The manager reached the window before the process started; startup produced readiness epoch 1 and the restart
epoch 2; each caused exactly one resource refresh and populated models, VAEs, samplers, schedulers, upscalers and ADetailer
models; only the owned process was stopped.

## Not changed / follow-ups

* An externally started runtime (no manager) is still announced READY by the connection controller's own probe.
* `AppController.on_launch_webui_clicked` / `on_retry_webui_clicked` still call the manager synchronously and are
  superseded in the production application by the connection-controller callbacks; consolidating them is separate.
* No Forge/A1111 runtime, dependency or model change; no per-job backend picker; no automatic A1111 <-> Forge fallback.
