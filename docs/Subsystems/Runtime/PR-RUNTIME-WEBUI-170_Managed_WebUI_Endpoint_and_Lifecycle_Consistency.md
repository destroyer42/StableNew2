# PR-RUNTIME-WEBUI-170 - Managed WebUI endpoint and lifecycle consistency

## Execution Profile + Model/Reasoning Recommendation

Standard-difficult runtime lifecycle repair inside existing ownership. Codex: GPT-6.1 Sol High. Claude Code:
Sonnet 5.5 High. Preferred host: Local/Desktop (the Windows launch environment matters for physical validation,
which this package did not perform).

## Controller Surface Assessment

No ratcheted-controller growth. `WebUIConnectionController` (not a ratcheted controller) gained a lock and a
stale-result guard; `AppController` lost an unreferenced method.

## Verified findings (current source)

| Finding | Result |
|---|---|
| `ensure_connected` rebound its URL provider to a port found by `find_webui_port` (7860-7864, 8000, 8080, 5000; never 7871) before the endpoint passed readiness | **Confirmed**, removed |
| `AppController._create_api_client_with_discovery` scanned 7860-7869 | **Confirmed, unreferenced**; removed |
| `WebUIProcessManager.check_health` already refused alternate ports for Forge but still rebound `_config.base_url` for A1111 | **Confirmed**, refused for every runtime; `discover_webui_port` removed |
| `StatusBarV2` disabled Launch/Retry only for the string `"connected"`; the enum value is `"ready"` | **Confirmed**, both handled |
| `start()` was unserialized | **Confirmed** (4 concurrent callers spawned 4 processes on unmodified source), now one |
| `ensure_running()` stopped and relaunched an owned process whose health check had not yet passed, even inside its normal startup window | **Confirmed**, now waits within the window |
| A stale readiness backoff (cooldown after two refused connections) made explicit connection attempts fail instantly although the runtime was up | **New finding**; an explicit attempt clears the backoff for its endpoint |
| An old attempt's ERROR could overwrite a newer manager READY (race) | **Confirmed by construction**, guarded by ready epoch |
| Different readiness meanings | See limitation 1 |

Which of these produced the originally observed port cycling on a given installation was not established from
logs; the package removes every credible mechanism and records distinct events.

## Behavior

* The configured runtime endpoint (`resolve_effective_webui_base_url`) is authoritative for the manager, the
  connection controller, the browser-launch URL and the API client. No alternate port is probed or adopted; a
  refusal logs `webui_port_discovery_refused` with the configured endpoint and owned PID. A WebUI that already
  answers the configured endpoint is still used as an external API connection (never adopted, stopped or restarted).
* `ensure_connected` is single-flight: a concurrent caller joins the in-flight attempt and receives its result
  (`reconnect` likewise). Owned startup uses the existing `wait_for_managed_startup` (bounded, slice-cleaned,
  early-exit diagnostics), whose manager readiness epoch is the one announcement; no second fixed-sleep retry loop.
* A connection failure is published only if no newer readiness proof arrived meanwhile
  (`webui_stale_failure_ignored`).
* `start()` is serialized; `ensure_running()` does not stop an owned, not-yet-proven process inside its startup
  window (`startup_timeout_seconds`), and keeps the existing bounded restart after it.
* READY projects Launch and Retry as disabled.

## Acceptance evidence

`tests/controller/test_webui_endpoint_lifecycle_170.py` (16): 7871 throughout while 7860 answers; one epoch;
no rebinding for any runtime; one process under concurrent start (deterministic, real-clock hold); single-flight
join; stale failure vs newer READY; stale backoff; no premature restart and unchanged recovery after the window;
READY controls; endpoint agreement; startup failure evidence (PID, exit code, output tail); occupied external
endpoint never launched over or stopped; removed mechanisms absent. 10 of 13 initial tests failed on the unchanged
source. Existing connection/lifecycle tests that encoded alternate-endpoint adoption were updated.

## Unchanged

Queue, NJR, JobService, runner, model profiles and backend fallback; A1111 as an explicit rollback; CLI discovery
(`src/cli.py`, outside this package); external-process ownership rules. No real WebUI was started.

## Limitations

1. Health levels are not collapsed: READY still means "API responsive" (`wait_for_webui_ready`: models **or**
   options), while generation gating keeps the stricter `is_webui_ready_strict` (process, port, both endpoints).
   Making the displayed READY require the strict proof changes many readiness seams and is left as an explicit
   follow-up decision.
2. The status bar's Launch/Retry still reach `AppController.on_launch_webui_clicked` -> `ensure_running()` as a
   second entry point alongside the connection controller; both are now safe against restart-during-startup and
   duplicate launch, but they are not merged.
3. Physical validation on the Windows install (port cycling, slow Forge startup) requires separate authorization.
4. Queue-level outage containment is PR-QUEUE-WEBUI-171 and is not started.
