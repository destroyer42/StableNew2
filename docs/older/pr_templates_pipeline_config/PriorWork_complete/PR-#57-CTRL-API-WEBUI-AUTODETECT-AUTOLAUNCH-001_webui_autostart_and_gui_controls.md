# PR-#57-CTRL-API-WEBUI-AUTODETECT-AUTOLAUNCH-001: WebUI auto-detect, auto-launch, and GUI controls

**Created:** 2025-11-23T18:20:08 (local repo time)

---

## 1. Summary / What’s new

This PR replaces the fragile, env-var–driven WebUI autostart behavior with a controller + config–driven flow that:

- Auto-detects a likely Stable Diffusion WebUI install (e.g., a `stable-diffusion-webui` folder near the repo) and builds a `WebUIProcessConfig` from that.
- Allows a user-configurable WebUI working directory + command (e.g., `webui-user.bat`) without hard-coding user-specific paths.
- Lets StableNew **launch the GUI immediately** without blocking on WebUI health.
- Provides a **WebUI Connection panel** that:
  - Shows WebUI connection state (`Disconnected`, `Connecting`, `Ready`, `Error`).
  - Exposes **“Launch WebUI”** and **“Retry Connection”** buttons.
- Uses `WebUIConnectionController` + `WebUIProcessManager` to:
  - Probe WebUI (fast health check).
  - Autostart WebUI when configured (no env-var dependency).
  - Retry health checks with timeouts from app config.
- Keeps pipeline runs **gated on WebUI readiness**:
  - If WebUI is not `READY`, attempts to start a pipeline are rejected and surfaced in the GUI.
- Updates docs and the rolling summary to describe the new WebUI auto-detect/auto-launch behavior.

This is the UX you described:
> StableNew should launch WebUI (or at least try), show connection health in the GUI, and prevent pipeline runs unless WebUI is actually reachable — without you ever touching environment variables.

---

## 2. Problem statement

Current behavior (post PR-56):

- WebUI autostart relies heavily on environment variables (`STABLENEW_WEBUI_*`).  
- In practice on Windows, `setx` does **not** reliably populate these in the running PowerShell session; behavior varies across terminals.
- As a result, you see:
  - `WebUI autostart is disabled; GUI will launch without waiting.`
  - No automatic launch of `webui-user.bat`.
  - No clear UI affordance inside StableNew to:
    - Start WebUI.
    - Retry a connection if something goes wrong.

This is:

- **Non-discoverable**: Users don’t know they must set env vars.
- **Brittle**: Behavior depends on shell/session details.
- **Not user-first**: You reasonably expect the app to *find* WebUI and start it, not vice versa.

We want a robust and user-centric design that aligns with `ARCHITECTURE_v2_COMBINED.md` and `PIPELINE_RULES.md`:

- Controllers own orchestration behavior.
- No hard-coded user-specific paths.
- GUI shows clear status and actions.
- Pipeline runs only when WebUI is healthy.

---

## 3. Goals

1. **Remove env-var dependency for core WebUI autostart**  
   - Environment variables may still be allowed as overrides, but they must not be required for basic operation.

2. **Add WebUI auto-detection and configurable launch settings**
   - Auto-detect a `stable-diffusion-webui` folder relative to the StableNew repo (e.g., sibling directories one level up).
   - Default to a sensible command on Windows: `webui-user.bat --api --xformers`.
   - Allow configuration for:
     - Working directory (where WebUI lives).
     - Launch command + arguments.

3. **Launch GUI immediately; manage WebUI in the background**
   - `python -m src.main` must always open the GUI, regardless of WebUI state.
   - WebUI health checks and autostart should be background operations, *not* blockers.

4. **Expose WebUI control in the GUI**
   - A status surface (likely the existing API / WebUI status panel) that shows:
     - `Disconnected`, `Connecting`, `Ready`, `Error`.
   - Buttons:
     - **Launch WebUI**: Start the process if we have a path/command.
     - **Retry Connection**: Re-run the health probe without relaunch if WebUI is already running.

5. **Gate pipeline runs on WebUI readiness**
   - If WebUI isn’t `READY`, controller prevents pipeline runs and surfaces a clear reason to the GUI.

6. **Keep architecture and tests aligned with v2**
   - WebUI orchestration lives in controller + API layers.
   - No GUI → HTTP calls.
   - Tests cover:
     - WebUIConnectionController behavior.
     - Controller gating of pipeline runs.
     - GUI-level behavior for status + buttons.

---

## 4. Non-goals

- No changes to the underlying SD WebUI HTTP client API contract.
- No cluster/worker-level WebUI coordination in this PR (single node only).
- No persistence of WebUI settings into a separate on-disk settings file; we will:
  - Provide detection and in-memory configuration via app_config.
  - Leave “GUI preferences persistence” to a later PR.
- No redesign of the entire status bar/panel UX; we will augment existing V2 surfaces, not replace them.

---

## 5. Context & references

- `docs/codex_context/ARCHITECTURE_v2_COMBINED.md`  
  - Layer boundaries: GUI → Controller → API.  
  - Controllers own lifecycle, not GUI or pipeline.

- `docs/codex_context/PIPELINE_RULES.md`  
  - WebUI availability is a **precondition** for pipeline runs.  
  - No hard-coded user paths; use config and detection heuristics.

- `src/config/app_config.py`  
  - Contains WebUI health defaults that are currently env-driven and non-configurable via GUI.

- `src/controller/webui_connection_controller.py`  
  - Encapsulates WebUI connection workflow, but still defers to env vars and uses a generic `["python", "webui.py"]` command.

- PR-56 summary (from Codex):
  - Introduced `WebUIConnectionController` and gating logic.
  - Added API status panel V2 state display and tests.
  - Still depends on env-based autostart toggle and a generic command.

This PR builds directly on PR-56 and replaces env-first autostart with **detection-first, config-driven** behavior.

---

## 6. Allowed files

**Controller / API**

- `src/controller/webui_connection_controller.py`
- `src/api/webui_process_manager.py`
- `src/controller/pipeline_controller.py` (only for WebUI gating logic; do not alter pipeline config assembly or queue semantics).

**Config**

- `src/config/app_config.py`

**GUI**

- `src/gui/api_status_panel_v2.py` (or whichever V2 API/WebUI status panel exists in your tree)
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py`

**Tests**

- `tests/controller/test_webui_connection_controller.py`
- `tests/controller/test_pipeline_controller_webui_gating.py`
- `tests/gui_v2/test_api_status_panel_webui_states_v2.py`

If these files are named slightly differently in the repo, adjust the PR to match reality, but do not introduce new modules unless strictly necessary.

**Docs**

- `docs/codex_context/ARCHITECTURE_v2_COMBINED.md`
- `docs/codex_context/PIPELINE_RULES.md`
- `docs/codex_context/ROLLING_SUMMARY.md`

---

## 7. Forbidden files

Do **not** modify:

- Pipeline implementation:
  - Any `src/pipeline/*` modules.
- Randomizer:
  - `src/utils/randomizer.py` and related helpers.
- Learning:
  - `src/learning/*`.
- Logging core:
  - `src/utils/structured_logger.py` or similar.
- Cluster / queue:
  - `src/queue/*`, `src/controller/cluster_controller.py`, etc.
- Any `tools/`, `scripts/`, CI config, or unrelated docs beyond the three explicitly listed above.

All behavior changes must be localized to **config + controller + WebUI API helpers + GUI status panel**.

---

## 8. Step-by-step implementation plan

> **TDD-first:** Wherever feasible, update or add tests **before** implementing the behavior.

### 8.1 app_config: WebUI process config defaults

1. In `src/config/app_config.py`, add module-level variables and helpers for WebUI process config:

   - New private fields:
     - `_webui_workdir: str | None = None`
     - `_webui_command: str | None = None`
     - `_webui_autostart_enabled: bool | None = None` (separate from env-based function).

   - New helpers:
     - `webui_workdir_default() -> str | None`  
       - Try detection (see 8.2) via a helper function imported from API/utility if needed.  
       - Fallback: `None` (no assumption about user path).

     - `get_webui_workdir() -> str | None` / `set_webui_workdir(path: str | None) -> None`  
       - Use module-level memory; no disk persistence in this PR.

     - `webui_command_default() -> list[str]`  
       - On Windows (`os.name == "nt"`), default to `["webui-user.bat", "--api", "--xformers"]`.  
       - On non-Windows, default to `["bash", "webui.sh", "--api"]` or similar generic default.

     - `get_webui_command() -> list[str]` / `set_webui_command(cmd: list[str]) -> None`.

     - `get_webui_autostart_enabled() -> bool` / `set_webui_autostart_enabled(value: bool) -> None`  
       - Default should prefer a safe value (e.g., `True` if detection succeeded, else `False`).  
       - Env vars (`STABLENEW_WEBUI_AUTOSTART`) may be used only as an *optional override*, not the primary mechanism.

2. Update existing `webui_autostart_enabled_default()` and `is_webui_autostart_enabled()` to:

   - Use `get_webui_autostart_enabled()` as the primary check.
   - Optionally still honor env as a fallback for power users.

3. Keep existing health timeout defaults (initial timeout, retry count, etc.), but ensure they are **not** the only gate for autostart (we now have `get_webui_autostart_enabled()`).

### 8.2 WebUI path detection helper

3. In `src/api/webui_process_manager.py`, or a small helper in the same module, add:

   - A function like `detect_default_webui_workdir(base_dir: str | None = None) -> str | None`:

     - If `base_dir` is `None`, use the repo root or current working directory (e.g., `os.getcwd()`).
     - Walk **one or two levels upward** and look for a folder named `stable-diffusion-webui` that contains either:
       - `webui-user.bat` (Windows), or
       - `webui.sh` (non-Windows).
     - If found, return that directory path; otherwise, return `None`.

4. Integrate detection into `webui_workdir_default()` from 8.1:

   - Call `detect_default_webui_workdir()` once (memoized via module-level variable).
   - If a directory is found, use it as the default working dir; otherwise `None`.

5. Ensure there are **no user-specific hard-coded paths** (no `C:\Users\rober\...` in the code). Only relative/heuristic detection is allowed.

### 8.3 WebUIProcessConfig & WebUIConnectionController autostart

6. In `src/api/webui_process_manager.py`:

   - Extend `WebUIProcessConfig` (if needed) to carry:
     - `command: list[str]`
     - `working_dir: str | None`

   - Provide a helper `build_default_webui_process_config()` that:

     - Uses `app_config.get_webui_workdir()` and `app_config.get_webui_command()`.
     - If `get_webui_workdir()` is `None`, falls back to `detect_default_webui_workdir()`.

7. In `src/controller/webui_connection_controller.py`:

   - Update `ensure_connected()`:

     - Replace the current hard-coded `WebUIProcessConfig(command=["python", "webui.py"], working_dir=None)` with a call to `build_default_webui_process_config()`.

     - Use `app_config.get_webui_autostart_enabled()` to decide whether autostart is allowed when `autostart=True` is passed in.

   - Ensure state transitions:

     - Start with `CONNECTING` on probe.
     - If WebUI responds during initial probe → `READY`.
     - If no response and autostart disabled → `ERROR` (but GUI still runs).
     - If autostart enabled:
       - Start WebUI via `WebUIProcessManager`.
       - Wait for health up to the configured total timeout with retries:
         - On success → `READY`.
         - On failure → `ERROR`.

8. Add or update tests in `tests/controller/test_webui_connection_controller.py` to validate:

   - Detection of `build_default_webui_process_config()` usage.
   - Behavior when autostart is disabled vs enabled.
   - Correct state transitions for success/failure branches (using mocks for healthcheck and process manager).

### 8.4 PipelineController gating (ensure WebUI is ready before run)

9. In `src/controller/pipeline_controller.py`:

   - Ensure there is a `WebUIConnectionController` dependency (likely already present from PR-56). If not, inject one.

   - Before starting any pipeline run (direct or queue-backed), do:

     - If a WebUI gate is configured, verify state:

       - If state is `READY` → allow run.
       - If state is `DISCONNECTED` or `ERROR`:
         - Option A: Call `ensure_connected(autostart=True)` once, and proceed only if it returns `READY`.
         - If still not `READY` → refuse run and surface an error message accessible to the GUI.

   - Make sure this gate is independent of GUI; avoid Tk imports.

10. Update `tests/controller/test_pipeline_controller_webui_gating.py` to assert:

    - With WebUI state `READY`, runs proceed.
    - With WebUI state `ERROR` or `DISCONNECTED`, runs are blocked and a clear error is exposed (e.g., via a return value or error attribute).

### 8.5 GUI V2: WebUI status panel and buttons

11. In `src/gui/api_status_panel_v2.py` (or equivalent):

    - Extend the panel to:

      - Display WebUI connection state (`Disconnected`, `Connecting`, `Ready`, `Error`).  
      - Add two buttons:
        - **Launch WebUI**:
          - Calls a controller/adapter hook that triggers `WebUIConnectionController.ensure_connected(autostart=True)`.
        - **Retry Connection**:
          - Calls a hook that re-runs `ensure_connected(autostart=False)` (no relaunch; just probe).

    - Ensure callback wiring stays **controller-facing**; the panel must not import `requests` or any API modules directly.

12. In `src/gui/app_layout_v2.py` and/or `src/gui/main_window.py`:

    - Wire the status panel to receive:

      - A read-only view of the WebUI connection state (e.g., via callbacks from the controller layer).
      - Two actions:
        - `on_launch_webui_clicked()`
        - `on_retry_webui_clicked()`

    - Make sure initial GUI startup does **not** block on WebUI; the panel can show `Disconnected` initially and update as background controller work proceeds.

13. Update `tests/gui_v2/test_api_status_panel_webui_states_v2.py` to cover:

    - State display for each enum value.
    - Button click callbacks being invoked (using mocks).
    - No Tk errors when buttons are clicked in any state.

### 8.6 Docs & rolling summary

14. Update `docs/codex_context/ARCHITECTURE_v2_COMBINED.md`:

    - Add a short subsection under Controller/API describing WebUI orchestration as:
      - Detection + autostart via `WebUIConnectionController` and `WebUIProcessManager`.
      - GUI shows status + actions; no blocking at startup.

15. Update `docs/codex_context/PIPELINE_RULES.md`:

    - Clarify the rule that pipeline runs are gated on WebUI readiness.
    - Note that WebUI path/command is discovered or configured, not hard-coded.

16. Update `docs/codex_context/ROLLING_SUMMARY.md` with 3–6 bullets summarizing this PR:

    - e.g., “PR-#57: WebUI auto-detect and GUI controls for launch/retry; pipeline gating maintained.”

---

## 9. Behavioral changes

**From a user’s perspective:**

- `python -m src.main` **always** launches the StableNew GUI, even if WebUI is completely offline or misconfigured.
- WebUI status is visible in the GUI (e.g., “Disconnected”, “Connecting”, “Ready”, “Error”).
- The user can:
  - Click **“Launch WebUI”** to start SD WebUI from within StableNew.
  - Click **“Retry Connection”** to re-probe an already-running WebUI instance.
- If StableNew can find a `stable-diffusion-webui` folder (e.g., `../stable-diffusion-webui` with `webui-user.bat` present):
  - It will use that as the default working directory for `webui-user.bat` inside `WebUIProcessManager`.
- Pipeline runs (Run button) are **blocked** when WebUI is not `READY`. The GUI should display a clear error explanation (e.g., “Cannot start pipeline: WebUI not connected”).

**From a config/ops perspective:**

- Environment variables for WebUI autostart are now optional overrides, not required.
- WebUI process config (working dir + command) is controlled via `app_config` and path detection, not hard-coded user paths.
- Controllers remain the single orchestration layer for WebUI health and gating.

---

## 10. Risks / invariants

**Invariants that must hold:**

- The GUI must always start, even if WebUI autostart fails or is misconfigured.
- No GUI module may import `requests` or the SD WebUI client; all WebUI interaction happens via controller/API.
- Pipeline runs remain gated on WebUI readiness; this PR must not allow “run pipeline without WebUI” paths to sneak in.
- No user-specific path (like `C:\Users\rober\...`) may be baked into the code. Detection must be generic.

**Risks:**

- Mis-detection of WebUI folder could lead to launching the wrong script or failing silently; tests should mock detection and ensure error paths are visible.
- Poorly chosen defaults for the launch command could behave differently on non-Windows systems; keep the implementation conservative and well-guarded with `os.name` checks.
- If healthcheck timeouts are too aggressive, the GUI might flip to “Error” even though WebUI is just slow; tests should keep this logic well-factored.

---

## 11. Tests

At a minimum, run:

1. **Controller-level tests**

   - `pytest tests/controller/test_webui_connection_controller.py -v`  
   - `pytest tests/controller/test_pipeline_controller_webui_gating.py -v`  
   - `pytest tests/controller -v`

2. **GUI V2 tests**

   - `pytest tests/gui_v2/test_api_status_panel_webui_states_v2.py -v`  
   - `pytest tests/gui_v2 -v` (expect Tk-related skips as usual if Tk/Tcl is not fully available)

3. **Full suite (time permitting)**

   - `pytest -v`

Please paste full test output into the PR notes when Codex completes this work.

---

## 12. Acceptance criteria

This PR is complete when:

1. All new and updated tests in:

   - `tests/controller/test_webui_connection_controller.py`
   - `tests/controller/test_pipeline_controller_webui_gating.py`
   - `tests/gui_v2/test_api_status_panel_webui_states_v2.py`

   are passing.

2. Existing controller and GUI tests remain green (modulo Tk skips).

3. Manual checks confirm:

   - StableNew GUI launches even if WebUI is offline.
   - Clicking **“Launch WebUI”** actually starts WebUI (when a valid install exists) and transitions status to `Ready` within the configured timeout.
   - Clicking **“Retry Connection”** when WebUI is already running successfully updates the status from `Disconnected/Error` to `Ready` once the API is reachable.
   - Attempting to start a pipeline when WebUI is not ready is blocked and surfaces a clear message in the GUI.

4. `ROLLING_SUMMARY.md` has an entry for PR-#57 describing WebUI auto-detect/autostart behavior and GUI controls.

---

## 13. Rollback plan

If anything goes wrong with this PR:

1. Revert changes to:

   - `src/config/app_config.py`
   - `src/controller/webui_connection_controller.py`
   - `src/api/webui_process_manager.py`
   - `src/controller/pipeline_controller.py`
   - `src/gui/api_status_panel_v2.py`
   - `src/gui/app_layout_v2.py`
   - `src/gui/main_window.py`
   - Test files added/modified
   - Doc files touched

2. Remove the PR-#57 entry from `ROLLING_SUMMARY.md` and any related notes in `ARCHITECTURE_v2_COMBINED.md` or `PIPELINE_RULES.md`.

3. Re-run:

   - `pytest tests/controller -v`
   - `pytest tests/gui_v2 -v`
   - `pytest -v`

   to ensure the suite returns to the previous known-good state (PR-56 behavior).

---

## 14. Codex execution constraints (for GPT-4.1 / Copilot)

**For Codex / ChatGPT 4.1 (Implementer):**

1. Open this spec from:

   - `docs/codex/prs/PR-#57-CTRL-API-WEBUI-AUTODETECT-AUTOLAUNCH-001_webui_autostart_and_gui_controls.md` (file path may vary slightly; adjust as needed).

2. Constraints:

   - Only modify files listed under **Allowed files**.
   - Do **not** touch pipeline, learning, randomizer, or cluster modules.
   - Follow the implementation steps in order; keep diffs small and focused.
   - Implement TDD where feasible: adjust tests first when they describe a new behavior.

3. After implementation:

   - Run the tests listed in §11 and paste the full output into the PR notes.

4. If any file paths do not exist or differ, **stop and ask** for clarification rather than guessing or creating new folders that don’t match the repo.

---

## 15. Suggested Codex prompts (drop-in scripts)

You can use these directly with GPT-4.1/Codex in the IDE.

### 15.1 Step 1: Config + detection + controller wiring

> Implement PR-#57 Step 8.1–8.3 only (app_config WebUI process config helpers, WebUI path detection, and WebUIConnectionController autostart changes).  
> 
> Files you may edit:
> - src/config/app_config.py
> - src/api/webui_process_manager.py
> - src/controller/webui_connection_controller.py
> - tests/controller/test_webui_connection_controller.py
> 
> Steps:
> 1. Add get/set helpers for WebUI working dir, command, and autostart flag in app_config, with detection-based defaults.
> 2. Implement detect_default_webui_workdir in webui_process_manager and use it in a new build_default_webui_process_config helper.
> 3. Update WebUIConnectionController.ensure_connected to use build_default_webui_process_config and app_config.get_webui_autostart_enabled.
> 4. Update or add tests in tests/controller/test_webui_connection_controller.py to cover the new behavior.
> 
> Then run:
> - pytest tests/controller/test_webui_connection_controller.py -v
> - pytest tests/controller -v
> 
> Paste the full test output and the diff summary.

### 15.2 Step 2: Pipeline gating + GUI status/buttons

> Implement PR-#57 Step 8.4–8.5 (pipeline controller gating and GUI WebUI status panel with Launch/Retry buttons).  
> 
> Files you may edit:
> - src/controller/pipeline_controller.py
> - src/gui/api_status_panel_v2.py
> - src/gui/app_layout_v2.py
> - src/gui/main_window.py
> - tests/controller/test_pipeline_controller_webui_gating.py
> - tests/gui_v2/test_api_status_panel_webui_states_v2.py
> 
> Steps:
> 1. Ensure PipelineController uses WebUIConnectionController to gate pipeline runs on READY state.
> 2. Extend the API/WebUI status panel to show connection state and expose Launch/Retry buttons with callbacks.
> 3. Wire status + callbacks through app_layout_v2 and main_window into the controller layer.
> 4. Update tests to verify controller gating and GUI behavior.
> 
> Then run:
> - pytest tests/controller/test_pipeline_controller_webui_gating.py -v
> - pytest tests/gui_v2/test_api_status_panel_webui_states_v2.py -v
> - pytest tests/controller -v
> - pytest tests/gui_v2 -v
> 
> Paste the full test output and the diff summary.

### 15.3 Step 3: Docs & rolling summary

> Implement PR-#57 Step 8.6 (docs + rolling summary).  
> 
> Files you may edit:
> - docs/codex_context/ARCHITECTURE_v2_COMBINED.md
> - docs/codex_context/PIPELINE_RULES.md
> - docs/codex_context/ROLLING_SUMMARY.md
> 
> Steps:
> 1. Document the WebUI detection/autostart behavior under the controller/API sections.
> 2. Clarify that pipeline runs are gated on WebUI readiness.
> 3. Add a PR-#57 entry to ROLLING_SUMMARY.md.
> 
> Then run:
> - pytest -v  (if feasible)
> 
> Paste any test output (or note if tests were already run in Steps 1 and 2 without further code changes).

---

## 16. Smoke test checklist (manual)

After all tests pass, perform these manual checks on your Windows setup (where WebUI lives at something like `C:\Users\<user>\stable-diffusion-webui` with `webui-user.bat`):

1. **GUI launches without WebUI running**

   - Ensure SD WebUI is not running.
   - Run `python -m src.main` from the repo root.
   - Confirm:
     - StableNew GUI appears.
     - WebUI status shows `Disconnected` or similar, not a crash.

2. **Launch WebUI from StableNew**

   - Click **“Launch WebUI”** in the status panel.
   - Watch the WebUI console window appear.
   - Within ~20 seconds (or configured timeout), confirm the status flips to `Ready`.

3. **Retry connection when WebUI was started externally**

   - Close StableNew.
   - Manually start `webui-user.bat` in your WebUI folder.
   - Relaunch StableNew (`python -m src.main`).
   - Click **“Retry Connection”**.
   - Confirm the status panel updates to `Ready` without attempting a second process launch.

4. **Pipeline gating**

   - With WebUI `Ready`, run a simple txt2img pipeline; confirm it starts.
   - Stop WebUI and try to run the pipeline again:
     - Confirm that StableNew refuses to start the pipeline and shows a clear message about WebUI not being connected.

If all of the above are true and tests are green, PR-#57 can be considered complete.
