Timestamp: 2025-11-22 18:40 (UTC-06)
PR Id: PR-#37-API-V2-WebUIProcessAndHealthCheck-001
Spec Path: docs/pr_templates/PR-#37-API-V2-WebUIProcessAndHealthCheck-001.md

# PR-#37-API-V2-WebUIProcessAndHealthCheck-001: WebUI Process Manager + Health Check Integration

## What’s new

- Introduces a dedicated **WebUIProcessManager** in the API layer to own starting, stopping, and supervising the Stable Diffusion WebUI process (A1111 or equivalent).
- Adds a **health-check loop** that verifies the SD WebUI HTTP API is reachable (base URL + txt2img or `/sdapi/v1/progress` probe) with bounded retries and clear error messages.
- Wires StableNew startup (e.g., `src/main.py` / app bootstrap controller) to optionally autostart WebUI before the first run, instead of relying on external manual launch.
- Adds tests for process management, timeout behavior, and health-check logic using mocks so no real WebUI process is required during CI.
- Documents the new behavior and invariants in the API section of the architecture and updates the rolling summary notes.

This PR is **API + bootstrap only**: it does not change pipeline logic, GUI layout, or queue semantics. It simply makes “is SD WebUI up?” a first-class, testable concern with explicit behavior.

---

## Files touched

> Adjust exact paths to match the repo, but keep changes within these areas.

### API layer

- `src/api/webui_process_manager.py` **(new)**
  - Implements `WebUIProcessManager` responsible for:
    - Resolving the WebUI executable / script path and working directory from config.
    - Spawning the WebUI process via `subprocess.Popen` (or platform-appropriate helper).
    - Tracking the child process handle and providing `start()`, `stop()`, and `is_running()` helpers.
    - Surfacing structured errors when the process fails to start or exits early.
  - Provides a small configuration dataclass (e.g., `WebUIProcessConfig`) capturing:
    - `command` / `args`
    - `working_dir`
    - `env_overrides` (optional)
    - `startup_timeout_seconds`

- `src/api/healthcheck.py` **(new or existing, depending on repo)**
  - Adds `wait_for_webui_ready(base_url: str, timeout: float, poll_interval: float)`:
    - Repeatedly probes a shallow endpoint (e.g. `GET /sdapi/v1/progress` or a minimal “ready” endpoint).
    - Raises a clear, typed exception if the timeout elapses or if unrecoverable errors are seen.
    - Does **not** log spammy stack traces; focuses on concise, user-facing error messages that can be bubbled up to GUI/CLI.

- `src/api/client.py`
  - Ensures a small, reusable “health check” operation is available:
    - Either via `client.check_health()` or reusing `wait_for_webui_ready(...)`.
  - No changes to existing txt2img/img2img/upscale contract or payload shaping.

### Bootstrap / entrypoint

- `src/main.py` (or `src/app/bootstrap.py`, depending on current layout)
  - Adds an **optional autostart** path:
    - Reads from config whether WebUI should be autostarted (e.g., `autostart_webui: bool`).
    - If enabled:
      - Constructs `WebUIProcessManager` with configured paths.
      - Calls `start()` and then `wait_for_webui_ready()` before proceeding to GUI/controller initialization.
    - If disabled:
      - Performs a single health check and:
        - On success: proceeds as normal.
        - On failure: surfaces clear guidance (e.g., “WebUI not reachable at {url}. Start it manually or enable autostart in settings.”).

### Config / utils

- `src/utils/app_config.py` (or equivalent)
  - Adds configuration fields, e.g.:
    - `webui_base_url: str`
    - `webui_autostart_enabled: bool`
    - `webui_command: List[str]` or `str`
    - `webui_working_dir: Optional[str]`
    - `webui_startup_timeout_seconds: float`
  - Provides safe defaults (no autostart by default, explicit base URL for localhost:7860).

### Tests

- `tests/api/test_webui_process_manager.py` **(new)**
  - Uses `unittest.mock` / `pytest` fixtures to:
    - Verify that `start()` calls `subprocess.Popen` with expected arguments.
    - Verify that failures to spawn are surfaced as structured exceptions.
    - Confirm that `stop()` attempts to terminate the process gracefully and handles already-exited processes.

- `tests/api/test_webui_healthcheck.py` **(new)**
  - Mocks `requests` (or the underlying HTTP client) to simulate:
    - Success on first try.
    - Success after several transient failures.
    - Persistent failure leading to timeout.
  - Asserts that:
    - Timeouts raise the appropriate exception type.
    - Error messages are concise and actionable.

- `tests/app/test_bootstrap_webui_autostart.py` **(new) or integrated into an existing bootstrap test**
  - Verifies:
    - When `autostart_webui` is true and WebUI is down, the manager is invoked and health check is run.
    - When `autostart_webui` is false but WebUI is reachable, startup proceeds without process spawn.
    - When WebUI is unreachable and autostart is false, a clear error path is taken (e.g., app exits early or displays a message).

### Docs

- `docs/ARCHITECTURE_v2_COMBINED.md`
  - Extend the **API Layer** section to mention:
    - WebUIProcessManager.
    - Health-check behavior and expectations.
    - Autostart as an optional, config-driven feature.

- `docs/PROJECT_CONTEXT.md`
  - Note the existence of the WebUI process manager and how it relates to:
    - API client (HTTP integration).
    - Controller and GUI expectations.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Add bullets as described in the “Rolling summary update” section at the end of this PR.

---

## Behavioral changes

- **Startup behavior**
  - Previously:
    - StableNew assumed SD WebUI was already running and reachable at the configured base URL.
    - Failures manifested later, when the first pipeline call hit an unreachable endpoint.
  - Now:
    - On startup, StableNew can optionally:
      - Spawn the WebUI process.
      - Wait until it responds to a health check.
    - If WebUI is not reachable (autostart disabled or failing):
      - The user sees a clear, early error instead of a cryptic failure during the first generation.

- **Error handling**
  - Errors about WebUI availability are now:
    - Typed (e.g., `WebUIStartupError`, `WebUIHealthCheckTimeout`).
    - Routed via controller/CLI to user-facing messages.
  - No changes to:
    - SD WebUI API payload formats.
    - Pipeline stages.
    - Learning hooks.

- **Configuration**
  - New config keys control:
    - Whether StableNew attempts to autostart WebUI.
    - How to invoke WebUI (command + working dir).
    - What base URL / port to probe.
    - How long to wait for WebUI to become ready.

- **Non-goals / unchanged behavior**
  - This PR does **not**:
    - Introduce new GUI controls for WebUI management (that can be a future GUI PR).
    - Change any pipeline defaults.
    - Alter queue behavior or job semantics.
    - Modify learning system behavior.

---

## Risks / invariants

- **Invariants**
  - GUI and controller layers must **not** import `subprocess` or make HTTP calls directly; all WebUI process and health logic remains confined to the API layer, in line with `ARCHITECTURE_v2_COMBINED.md`.
  - Pipeline behavior must remain unchanged when WebUI is reachable:
    - Same payloads.
    - Same responses.
    - Same error-handling semantics as defined in `PIPELINE_RULES.md`.
  - Learning remains **opt-in** and unaffected:
    - This PR does not change `LEARNING_SYSTEM_SPEC.md` behavior or JSONL writer semantics.
  - No hard-coded, user-specific paths:
    - All WebUI-related paths and URLs must come from config/env, per `PROJECT_CONTEXT.md` and `PIPELINE_RULES.md`.

- **Risks**
  - Misconfigured WebUI command or working directory could prevent StableNew from starting WebUI successfully.
  - Health-check false negatives:
    - If the chosen endpoint is not consistently available during startup, the health check might timeout even though WebUI is effectively “up”.
  - Platform differences:
    - `subprocess.Popen` behavior may differ across Windows vs Linux; tests must mock process creation and not assert on platform-specific details.

- **Mitigations**
  - Keep process manager logic small and test-driven.
  - Use feature flags/config to disable autostart if it causes issues.
  - Log detailed diagnostics for startup failures to assist in troubleshooting.
  - Avoid touching unrelated modules; keep scope constrained to API + bootstrap.

---

## Tests

Run at minimum:

- API-specific tests:
  - `pytest tests/api/test_webui_process_manager.py -v`
  - `pytest tests/api/test_webui_healthcheck.py -v`

- Bootstrap / smoke tests:
  - `pytest tests/app/test_bootstrap_webui_autostart.py -v` (or equivalent)

- Regression tests:
  - `pytest tests/pipeline -v`
  - `pytest tests/controller -v`
  - `pytest tests/gui_v2 -v`
  - `pytest -v`

Expected results:

- New tests validate:
  - Correct invocation of WebUI process spawn and shutdown behavior.
  - Correct handling of successful, delayed, and failed health checks.
- Existing tests remain green:
  - No regressions in pipeline execution, controller lifecycle, learning behavior, or GUI tests.

---

## Migration / future work

This PR establishes a **clean API-layer primitive** for managing SD WebUI. Follow-on work can safely build atop it:

- Add GUI V2 controls:
  - Display WebUI status (Running/Stopped/Unreachable).
  - Allow manual restart commands via the controller.
- Add controller-level orchestration:
  - Enforce “WebUI must be healthy before queue jobs are allowed to run”.
  - Integrate WebUI status checks into queue/job scheduling (e.g., pause queue if WebUI is down).
- Extend health checks:
  - Include version checks (ensure specific SD WebUI version).
  - Validate presence of required extensions/models up front.

When integrating with cluster/worker nodes in later PRs, a variant of this WebUI process/health contract can be reused for remote workers.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date (e.g., `## 2025-11-22`):

- Added a dedicated **WebUIProcessManager** in the API layer to own SD WebUI startup/shutdown and keep process handling out of GUI/controllers.
- Introduced a **WebUI health-check helper** that validates the SD WebUI API is reachable with bounded retries and clear error messages.
- Updated the app bootstrap path to optionally **autostart WebUI on launch**, improving failure transparency when the backend is unavailable.
