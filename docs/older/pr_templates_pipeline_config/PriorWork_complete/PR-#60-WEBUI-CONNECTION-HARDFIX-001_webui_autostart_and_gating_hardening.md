# PR-#60-WEBUI-CONNECTION-HARDFIX-001: WebUI autostart & pipeline gating hardening

**Created:** 2025-11-23T20:08:22 (local repo time)

---

## 1. Title

**PR-#60-WEBUI-CONNECTION-HARDFIX-001: WebUI autostart & pipeline gating hardening**

---

## 2. Summary

This PR hardens the StableNew WebUI integration so that:

- WebUI **autostart works by default** via detection and app_config (env vars are optional overrides, not mandatory).
- Pipeline runs are **strictly gated** on WebUI readiness – no more hammering a dead API with retries when WebUI is not up.
- The GUI’s **Run / Queue controls and status bar** accurately reflect WebUI state and why a run is blocked.
- The behavior in real usage matches what the existing PR-56/57/58/59 tests describe.

It does this by:

- Making `app_config` provide sane defaults for WebUI workdir/command/autostart (detection-based).
- Centralizing WebUI process configuration via `webui_process_manager`.
- Ensuring `WebUIConnectionController` is the single gatekeeper for WebUI readiness and process autostart.
- Wiring `PipelineController` to **refuse runs when WebUI is not ready**, and exposing a simple readiness API for the GUI.
- Ensuring the composite V2 status bar shows WebUI state and provides Launch/Retry hooks that call the controller.

---

## 3. Problem Statement

Despite PR-56–59 and green tests, the current runtime behavior shows:

- Startup log: `WebUI autostart is disabled; GUI will launch without waiting.`
  - Indicates `autostart` is still interpreted as **disabled**, even after env var changes.
  - Suggests `main.py` / config still rely on fragile env-only logic.

- Running the pipeline when WebUI is down leads to tens of HTTP retries:

  - `src.api.client` repeatedly hits `/sdapi/v1/options` and `/sdapi/v1/txt2img` on `127.0.0.1:7860`.
  - Eventually errors with “No connection could be made because the target machine actively refused it”.

- There is **no visible GUI feedback** that WebUI isn’t running or that autostart failed.
- The status bar and WebUI controls tested in PR-56/57/59 exist in code, but practical usage shows:
  - No WebUI-specific controls appear.
  - Run is not visibly gated by WebUI readiness.

Root causes (inferred from behavior + prior PR outputs):

- WebUI autostart still depends heavily on env vars that may not be set in the actual shell where `python -m src.main` is run.
- Detection of `webui-user.bat` and sensible defaults are either not wired through, or not being used to set autostart=true by default.
- Pipeline run path can still reach the API client even when the connection controller says WebUI is not ready (or is never consulted).
- GUI wiring for status bar + WebUI controls is not aligned with the real controller paths/flags used in production.

We need to close this gap so that:

- The default behavior “just works” on a typical Windows install with a standard A1111 WebUI folder.
- The GUI clearly shows WebUI status and offers working Launch/Retry controls.
- The pipeline never silently runs against a dead WebUI again.

---

## 4. Goals

1. **Autostart that works out-of-the-box**  
   - If a standard `stable-diffusion-webui` folder with `webui-user.bat` exists, StableNew should be able to autostart WebUI **without requiring env vars**.
   - Env vars remain supported but become optional overrides, not the only configuration path.

2. **Strict pipeline gating on WebUI readiness**  
   - Pipeline runs must **not** start if WebUI is not in `READY` state as reported by `WebUIConnectionController`.
   - When gating blocks a run, the GUI and logs must say *why* (WebUI not ready), not just show a client error.

3. **Clear and actionable GUI feedback**  
   - Status bar shows WebUI state (Disconnected, Connecting, Ready, Error).
   - Composite bar exposes Launch / Retry buttons that call into `WebUIConnectionController.ensure_connected(...)`.
   - Run/Queue controls are enabled only when WebUI is ready.

4. **Single source of truth for WebUI process config**  
   - `webui_process_manager` builds the process config from `app_config` (detection + env) and is used by `WebUIConnectionController` for autostart.

5. **No regressions to queue, learning, or assembler behavior**  
   - Only gating and WebUI process handling are in scope.

---

## 5. Non-goals

- No redesign of the queue/job/cluster system.
- No changes to randomizer or learning behavior.
- No changes to the main pipeline stage order or config assembler logic, beyond WebUI gating.
- No full GUI theme/layout redesign; only footer/status wiring and enable/disable logic where necessary.

---

## 6. Context & References

This PR assumes the following are already in place from earlier work:

- **WebUI health + gating:**
  - `WebUIConnectionController` that can probe WebUI and (in theory) autostart it.
  - `test_webui_connection_controller.py`, `test_pipeline_controller_webui_gating.py` asserting basic gating.
- **GUI V2:**
  - Composite StatusBarV2 that includes WebUI status + Launch/Retry controls (from PR-59).
  - `test_api_status_panel_webui_states_v2.py` and `test_status_bar_v2_composite.py` validating widget behavior.
- **Startup alignment:**
  - `main.py` using `WebUIConnectionController` for autostart decisions (PR-58).

Additional reference docs (do not modify in this PR):

- `docs/codex_context/ARCHITECTURE_v2_COMBINED.md`
- `docs/codex_context/PIPELINE_RULES.md`
- `docs/codex_context/LEARNING_SYSTEM_SPEC.md`
- `docs/codex_context/PROJECT_CONTEXT.md`

---

## 7. Allowed Files

You may modify:

- **Config & process config**  
  - `src/config/app_config.py`  
  - `src/api/webui_process_manager.py`  

- **Controllers**  
  - `src/controller/webui_connection_controller.py`  
  - `src/controller/pipeline_controller.py`  

- **GUI wiring (only for WebUI state + gating)**  
  - `src/gui/status_bar_v2.py` (or equivalent composite bar implementation)  
  - `src/gui/api_status_panel.py` / `src/gui/api_status_panel_v2.py` (whichever is actually used for WebUI state)  
  - `src/gui/app_layout_v2.py`  
  - `src/gui/main_window.py`  

- **Tests**  
  - `tests/controller/test_webui_connection_controller.py`  
  - `tests/controller/test_pipeline_controller_webui_gating.py`  
  - `tests/gui_v2/test_api_status_panel_webui_states_v2.py`  
  - `tests/gui_v2/test_status_bar_v2_composite.py`  
  - `tests/gui_v2/test_main_window_webui_integration.py` (if present; otherwise add a small new one)  

- **Docs**  
  - `docs/codex_context/ROLLING_SUMMARY.md` (append PR-60 entry only)

If actual filenames differ slightly, adapt, but keep scope equivalently narrow.

---

## 8. Forbidden Files

Do **not** modify:

- Any modules under `src/pipeline/`  
- Any modules under `src/learning/`  
- Any modules under `src/queue/` or `src/controller/cluster_controller.py`  
- `src/utils/structured_logger.py` and other logging primitives  
- `docs/codex_context/ARCHITECTURE_v2_COMBINED.md`  
- `docs/codex_context/PIPELINE_RULES.md`  
- Any GUI panel unrelated to WebUI status or run/queue enablement (prompt editor, core config, negative prompt, resolution, output, model manager, etc.)  

---

## 9. Step-by-step Implementation

### 9.1 app_config: detection-based defaults and env overrides

1. In `src/config/app_config.py`, introduce or refine helpers:

   - `detect_default_webui_workdir() -> Path | None`  
     - Try common locations, e.g.:  
       - A sibling to the StableNew repo (`../stable-diffusion-webui`)  
       - `~/stable-diffusion-webui`  
       - Any simple heuristic you already have in PR-57.

   - `get_webui_workdir() -> Path | None`  
     - If `STABLENEW_WEBUI_WORKDIR` env var is set, return that path.  
     - Else, call `detect_default_webui_workdir()`.  
     - Return `None` if nothing is found.

   - `get_webui_command() -> list[str]`  
     - If `STABLENEW_WEBUI_COMMAND` is set, use it (split appropriately).  
     - Otherwise, default to `["webui-user.bat"]` on Windows, or a reasonable default on other platforms.

   - `get_webui_autostart_enabled() -> bool`  
     - If `STABLENEW_WEBUI_AUTOSTART` env var is set:  
       - Interpret `"1"`, `"true"`, `"yes"`, `"on"` (case-insensitive) as **True**.  
       - Interpret `"0"`, `"false"`, `"no"`, `"off"` as **False**.  
     - If env var is **not** set:  
       - Default to **True if** `get_webui_workdir()` returns a non-None path; otherwise **False**.

2. Make sure these helpers are the **only** place where WebUI-specific env vars are interpreted.  
   - `main.py` and controllers should no longer manually read `os.environ` for WebUI flags.

### 9.2 webui_process_manager: canonical process config builder

3. In `src/api/webui_process_manager.py`, add or refine a function:

   - `build_webui_process_config(app_cfg) -> WebUIProcessConfig | None`

   This should:

   - Call `get_webui_workdir()`  
   - If it returns `None`, return `None` (cannot autostart).  
   - Compute a full command list based on `get_webui_command()` and workdir (e.g., `[str(workdir / "webui-user.bat"), "--xformers", "--api"]` if you want to bake in standard flags).  
   - Return a `WebUIProcessConfig` dataclass instance with:
     - `workdir: Path`
     - `command: list[str]`
     - Any other needed fields (env, timeout) already present in your type.

4. Ensure `WebUIConnectionController` uses **only this builder** for autostart and does not duplicate env parsing.

### 9.3 WebUIConnectionController: single gatekeeper for readiness

5. In `src/controller/webui_connection_controller.py`:

   - Ensure it exposes a **state enum**, e.g. `WebUIConnectionState` with values like:  
     - `DISCONNECTED`  
     - `CONNECTING`  
     - `READY`  
     - `ERROR`  

   - Implement or verify a method:

     - `ensure_connected(autostart: bool) -> None`  
       - If `state` is `READY`, return immediately.  
       - Probe the health endpoint; if reachable, set `state = READY` and notify listeners.  
       - If not reachable and `autostart` is True:
         - Use `build_webui_process_config(app_cfg)` to get a process config.
         - If `None`, set `state = ERROR` with a helpful message (e.g., “WebUI workdir not found; configure path or start WebUI manually”).  
         - If config exists, spawn the process and poll health until ready or timeout.
       - If not reachable and `autostart` is False:
         - Set `state = DISCONNECTED` or `ERROR` as appropriate and return.

   - Provide a simple read-only API for others:
     - `get_state() -> WebUIConnectionState`  
     - Optionally, `is_ready() -> bool`

   - Ensure it can register listeners (callbacks) so GUI can update on state changes, or re-use any existing callback mechanism from PR-57/58/59.

### 9.4 PipelineController: strict gating

6. In `src/controller/pipeline_controller.py`:

   - Ensure it has access to the `WebUIConnectionController` instance.

   - In the method that kicks off a pipeline run (direct and queue-mode paths), enforce a gating check:

     - If `webui_connection_controller.is_ready()` is False:
       - **Do not start** the pipeline worker or queue job.
       - Instead, surface a clear error:
         - Log: `WebUI not ready; refusing to start pipeline.`
         - Optionally, notify GUI via the existing error channel (e.g., a callback or structured error event).

   - Only proceed to schedule the actual pipeline run when WebUI is `READY`.

7. Make sure gating applies to both:

   - Direct run (immediate pipeline execution).  
   - Queue-backed run (job submission); jobs should either be refused at the controller, or the queue should be aware that WebUI readiness is required before execution.

### 9.5 GUI: status bar & run button wiring

8. In `src/gui/status_bar_v2.py` (composite bar) and `src/gui/api_status_panel.py`:

   - Confirm there is a clear interface to:

     - `set_webui_state(state: WebUIConnectionState)` – updates label text and any icons/colors.  
     - `set_webui_launch_callback(cb)` – Launch button calls `cb()`.  
     - `set_webui_retry_callback(cb)` – Retry button calls `cb()`.

9. In `src/gui/app_layout_v2.py`:

   - Ensure the **composite status bar** is the one instantiated for V2 and attached to the bottom of the main window.

   - Expose references on the owner (e.g., `owner.status_bar_v2`) so `MainWindow` can call the WebUI setter methods.

10. In `src/gui/main_window.py`:

    - After controllers and layout are constructed:

      - Wire **status bar buttons** to the controller:

        - Launch: `status_bar_v2.set_webui_launch_callback(lambda: webui_connection_controller.ensure_connected(autostart=True))`  
        - Retry: `status_bar_v2.set_webui_retry_callback(lambda: webui_connection_controller.ensure_connected(autostart=False))`

      - Subscribe to WebUI state changes from `WebUIConnectionController` and call `status_bar_v2.set_webui_state(...)` accordingly.

    - Tie **Run/Queue control enablement** to WebUI readiness:

      - When `state != READY`, disable or gray out Run/Queue.  
      - When `state == READY`, enable them.

    - When a run attempt is blocked because WebUI is not ready, ensure the GUI provides a clear indication:
      - e.g., leaving Run disabled and relying on the status bar message, or showing a non-modal message through an existing diagnostics area.

### 9.6 Tests

11. Update `tests/controller/test_webui_connection_controller.py`:

    - Add/extend tests that simulate:
      - WebUI reachable without needing autostart.
      - WebUI not reachable, autostart disabled → state remains `DISCONNECTED`/`ERROR`, no process spawn.
      - WebUI not reachable, autostart enabled with valid process config → process spawn + eventual `READY` (mocked).
      - No valid workdir → `ensure_connected(autostart=True)` sets `ERROR` with an informative message.

12. Update `tests/controller/test_pipeline_controller_webui_gating.py`:

    - Ensure that when `is_ready()` is False, `start_pipeline` (and queue-based equivalent) **does not** call into the pipeline runner.
    - When `is_ready()` is True, runs proceed as before.

13. Update `tests/gui_v2/test_api_status_panel_webui_states_v2.py`:

    - Confirm state → label text mappings still match expectations.
    - Confirm Launch/Retry callbacks are invoked when buttons are “clicked” in the test harness.

14. Update `tests/gui_v2/test_status_bar_v2_composite.py`:

    - Confirm that the composite bar:
      - Still shows base status text.
      - Properly forward-calls Launch/Retry callbacks.
      - Updates WebUI state display via `set_webui_state(...)`.

15. Update or introduce `tests/gui_v2/test_main_window_webui_integration.py`:

    - Use a mocked `WebUIConnectionController` exposing `get_state()`, `is_ready()`, and `ensure_connected`:

      - On startup with autostart disabled:
        - Composite status bar shows disconnected state.
        - Clicking Launch/Retry calls `ensure_connected(...)` with correct flags.

      - When state is changed to `READY` (by test):
        - Run/Queue controls become enabled.

### 9.7 Rolling summary

16. Append a short PR-60 entry to `docs/codex_context/ROLLING_SUMMARY.md` describing:

    - Detection-based WebUI autostart defaults.
    - Strict gating of pipeline runs on WebUI readiness.
    - Status bar WebUI controls and visible feedback when WebUI is not ready.

---

## 10. Behavioral Changes

After this PR:

- On a system where `C:\Users\<user>\stable-diffusion-webui\webui-user.bat` exists:

  - Running `python -m src.main`:

    - Starts the StableNew GUI immediately.  
    - Uses `app_config` + detection to determine that a valid WebUI workdir exists.  
    - Treats autostart as **enabled by default**, unless explicitly turned off via env var or config.  
    - `WebUIConnectionController` attempts to connect/autostart WebUI in the background.

  - The **status bar** shows:

    - `WebUI: Connecting...` while it probes or starts the process.  
    - `WebUI: Ready` once health checks succeed.  
    - `WebUI: Error` with a hint if workdir is missing or API never becomes reachable.

  - The **Run/Queue buttons**:

    - Are disabled until WebUI is `Ready`.  
    - Become enabled once WebUI transitions to `Ready`.  
    - If a user tries to run while disabled, they see the reason via status bar state (and optional tooltip/message).

  - If WebUI is not detected or detection fails:

    - Autostart defaults to False.  
    - Status bar shows a clear message (e.g., “WebUI not configured – set path or start manually”).  
    - Launch/Retry buttons still exist; Launch will attempt autostart if/when a valid config can be built.

- Pipeline runs will **never again** silently hammer `127.0.0.1:7860` if WebUI is totally offline; gating will block the run upfront.

---

## 11. Tests to Run

At minimum, run and paste results into the PR notes:

- `pytest tests/controller/test_webui_connection_controller.py -v`
- `pytest tests/controller/test_pipeline_controller_webui_gating.py -v`
- `pytest tests/gui_v2/test_api_status_panel_webui_states_v2.py -v`
- `pytest tests/gui_v2/test_status_bar_v2_composite.py -v`
- `pytest tests/gui_v2/test_main_window_webui_integration.py -v` (if present)
- `pytest tests/controller -v`
- `pytest tests/gui_v2 -v`
- `pytest -v`

Tk-related skips are expected.

---

## 12. Acceptance Criteria

This PR is complete when:

1. All tests in §11 pass (aside from known Tk-related skips).  
2. `app_config` no longer requires env vars for WebUI autostart in common cases and provides detection-based defaults.  
3. `WebUIConnectionController` is the single gatekeeper for WebUI readiness and process autostart; pipeline runs are blocked when not ready.  
4. The composite status bar clearly shows WebUI state and provides working Launch/Retry controls.  
5. Run/Queue controls in the GUI are disabled when WebUI is not ready and enabled once it is ready.  
6. `ROLLING_SUMMARY.md` includes a PR-60 entry summarizing the changes.

---

## 13. Rollback Plan

If this PR causes regressions:

1. Revert changes to:
   - `src/config/app_config.py`
   - `src/api/webui_process_manager.py`
   - `src/controller/webui_connection_controller.py`
   - `src/controller/pipeline_controller.py`
   - `src/gui/status_bar_v2.py`
   - `src/gui/api_status_panel*.py`
   - `src/gui/app_layout_v2.py`
   - `src/gui/main_window.py`
   - Any tests modified or added
   - `docs/codex_context/ROLLING_SUMMARY.md` (remove PR-60 entry)

2. Re-run:
   - `pytest tests/controller -v`
   - `pytest tests/gui_v2 -v`
   - `pytest -v`

3. Confirm behavior returns to PR-59 baseline (composite status bar exists, but WebUI may still behave as before this hardening).

---

## 14. Codex Execution Prompt (for GPT-4.1)

> Implement **PR-#60-WEBUI-CONNECTION-HARDFIX-001** exactly as described in this spec.  
> Focus on:
> - Making WebUI autostart detection-based with sensible defaults (env vars optional).  
> - Ensuring `WebUIConnectionController` is the single gatekeeper for readiness + autostart.  
> - Strictly gating pipeline runs on WebUI readiness.  
> - Wiring the composite status bar’s WebUI state and Launch/Retry controls to the controller.  
> Only modify files listed under “Allowed Files”.  
> After implementation, run all tests listed in §11 and paste the full output with a brief summary of the diffs (files changed, +/− lines) into the PR discussion.
