PR-API-D27 — HTTP Connection Lifecycle.md + /options Throttling (Stop 7860 Port Exhaustion / “Connection Refused” During Runs)
Intent

Fix the “WebUI is up, resources hydrate, but runs fail with WinError 10061 connection refused + tons of TIME_WAIT / CLOSE_WAIT / FIN_WAIT_2 on :7860” symptom by:

Fixing HTTP connection lifecycle (Session reuse + always closing responses + sane timeouts/pooling), and

Throttling /sdapi/v1/options so we don’t spam options calls during execution (especially around model switching / upscale defaults).

Scope / Non-Goals

Does

Prevent local port/socket churn that leads to refusal mid-run (the netstat pattern you posted strongly suggests connection lifecycle issues, not “wrong port”).

Reduce /options calls to “only when needed” and “not more than once per short window”.

Does NOT

Change NJR-first execution architecture.

Change run-mode semantics or queue logic (that’s in the prior PR).

Redesign GUI.

Symptoms / Acceptance Criteria (Binary)

When WebUI is running and a job starts, requests should not flood the port with unbounded short-lived connections.

/sdapi/v1/options should be called:

0 times if no options need applying,

1 time per job (or per meaningful change), not repeatedly per stage,

and never in tight loops.

A queue job should reach COMPLETED and generate images (when WebUI is actually healthy), or reach FAILED fast (when WebUI is actually down) — without accumulating hundreds of dead sockets.

Evidence via netstat: the run should not create the “CLOSE_WAIT=client PID” snowdrift pattern you’re currently seeing.

Allowed Files (HARD BOUNDARY — touch ONLY these)

If any file path differs or is missing: STOP (do not guess).

Area	Path	Allowed change
HTTP client lifecycle	src/api/client.py	session reuse, pool sizing, timeouts, always-close responses, request wrapper
WebUI API orchestration	src/api/webui_api.py	throttle /options, call ordering (but no new flows)
Resource service (optional)	src/api/webui_resource_service.py	only if it currently triggers /options repeatedly; otherwise do not touch
Retry policy	src/api/retry_policy_v2.py	only if needed for sane connect/read timeouts; keep behavior-compatible
Tests (new)	tests/api/test_webui_options_throttle_v2.py	NEW test for /options throttling
Tests (modify)	tests/api/test_webui_retry_policy_v2.py	update/extend to cover connection-error classification if required
Tests (modify)	tests/api/test_client_generate_images.py	add assertion that requests close/reuse path is used (light-touch)
Ordered Implementation Steps (NON-OPTIONAL)
Step 1 — Fix HTTP connection lifecycle (Session reuse + always-close + timeouts)

File: src/api/client.py

Add a single requests.Session owned by the client instance (or a module-private singleton if the design already uses static helpers).

Must not create a new Session per request.

Configure an HTTPAdapter with bounded pooling:

pool_connections and pool_maxsize set to a reasonable fixed number (e.g., 10–50).

pool_block=True to prevent unbounded socket creation when the app spikes.

Ensure every request closes response objects:

Use with session.request(...) as resp: pattern or resp = ...; resp.raise_for_status(); data = resp.json(); finally: resp.close().

This is critical to eliminate CLOSE_WAIT leakage.

Enforce explicit timeouts everywhere:

Connect timeout (short) + read timeout (reasonable), e.g. (3.0, 60.0) for generation endpoints.

Do not rely on requests default (infinite read timeout).

Ensure the request wrapper consumes response content before close (json/text), to avoid keep-alive weirdness.

Add (or preserve) structured logging showing:

endpoint path,

attempt number,

whether we are reusing the session,

timeout values.

Exit criteria for Step 1

All POST/GET calls go through the shared session wrapper.

Response objects are always closed.

Step 2 — Throttle /sdapi/v1/options (dedupe + minimum interval)

File: src/api/webui_api.py

Identify current code path(s) that call /sdapi/v1/options during a run (your logs show repeated POST /options with stage=null).

Implement a throttle/dedupe guard:

Keep last_options_payload_hash and last_options_applied_at (monotonic timestamp).

If new payload hash == last hash → skip applying.

Else if (now - last_applied_at) < MIN_INTERVAL_SEC → skip or delay (skip preferred; do not block UI or queue).

MIN_INTERVAL_SEC should be small but non-trivial (e.g., 5–10s).

Ensure stage execution calls do not re-apply options repeatedly:

Options should be applied once per job before first stage call, or only when a stage truly requires a change.

When /options fails due to connection error:

That should surface as the typed “WebUI unavailable” path you already introduced, and must not trigger a tight retry loop via repeated apply attempts.

Exit criteria for Step 2

In a single job, /options is called at most once unless the payload actually changes meaningfully.

Step 3 — Ensure retry policy doesn’t create port churn

File: src/api/retry_policy_v2.py (only if needed)

Confirm retry policy does not:

retry in a hot loop with no backoff,

multiply retries across /options and stage calls.

Ensure backoff exists and is not zero.

Ensure connection errors are not retried excessively for generation endpoints.

Exit criteria for Step 3

Retry behavior remains compatible with existing tests, but no “hammering” on refusal.

Step 4 — Add tests for options throttling + client lifecycle
4A) New throttling test

File: tests/api/test_webui_options_throttle_v2.py (NEW)

Test cases:

Dedupe: calling “apply options” twice with identical payload results in 1 POST to /options.

Interval throttle: calling with different payload within MIN_INTERVAL_SEC results in 0 or 1 additional call (match implementation choice; must be deterministic).

Does not interfere with stage: if stage call happens after options apply, it should still call stage endpoint exactly once.

Use monkeypatch/mocks around the request wrapper in src/api/client.py so you can count calls without spinning up WebUI.

4B) Lightweight “responses are closed” test

File: tests/api/test_client_generate_images.py (modify lightly)

Patch the underlying request method to return a fake response object whose .close() flips a flag.

Assert .close() was called even on exceptions.

Test Plan (MANDATORY — exact commands)

Run these commands exactly and include the output blocks in the PR result:

python -m pytest -q tests/api/test_webui_options_throttle_v2.py
python -m pytest -q tests/api/test_client_generate_images.py
python -m pytest -q tests/api/test_webui_retry_policy_v2.py
python -m pytest -q tests/api
python -m pytest -q tests/controller tests/queue tests/gui_v2


If any fail: fix immediately (no skipping).

Evidence Commands (MANDATORY)
git diff
git diff --stat
git status --short

git grep -n "sdapi/v1/options" src/api
git grep -n "Session(" -n src/api/client.py
git grep -n "timeout=" -n src/api/client.py


Manual evidence (required)

Start app:

python -m src.main


Before starting a run:

netstat -ano | findstr :7860


Start a queue run (1 job). During “RUNNING”, run again:

netstat -ano | findstr :7860


Acceptance proof: you should not see the runaway CLOSE_WAIT accumulation tied to the client PID, and the run should not devolve into connection refused while WebUI is up.