PR-API-0121-WebUI-Crash-Guard.md

Related Canonical Sections

PR execution rules + proof requirements: PR TEMPLATE — v2.7.1-X.md 

PR TEMPLATE — v2.7.1-X

Agent execution discipline: AGENTS.md 

AGENTS

INTENT (MANDATORY)

This PR makes WebUI option updates deterministic, rate-limited, and thread-safe, and prevents StableNew from spamming /sdapi/v1/options or applying aggressive option payloads at startup.
It does not change pipeline execution semantics, NJR, queue/runner logic, GUI flows, or stage payload composition.

SCOPE OF CHANGE (EXPLICIT)
Files TO BE MODIFIED (REQUIRED)

src/api/webui_api.py — make /options throttling thread-safe and immune to concurrent callers.

src/api/client.py — add safe guards around option updates and stop unsafe defaults from being applied implicitly.

tests/api/test_webui_api_options_throttle.py — new tests proving thread-safety + throttle behavior.

Files TO BE DELETED (REQUIRED)

None

Files VERIFIED UNCHANGED

Anything not listed above (especially pipeline/runner/controller/gui).

ARCHITECTURAL COMPLIANCE

 NJR-only execution path (unchanged)

 No PipelineConfig usage in runtime (unchanged)

 No dict-based execution configs (unchanged)

 Legacy code classified (unchanged)

IMPLEMENTATION STEPS (ORDERED, NON-OPTIONAL)
1) src/api/webui_api.py — add a lock to make throttling real

Goal: guarantee only one thread can evaluate + mutate _last_options_payload_hash / _last_options_applied_at at a time.

Import threading.

In WebUIAPI.__init__, add self._options_lock = threading.Lock().

In apply_options(...), wrap all logic from if not updates: through the final state update in a with self._options_lock: block.

Ensure logging stays the same, but now reflects correct skip/apply behavior.

Why: current code is vulnerable to concurrent callers defeating throttling 

webui_api

.

2) src/api/client.py — stop “unsafe defaults” from being silently applied

Goal: eliminate the possibility that StableNew applies apply_upscale_performance_defaults() during startup/resource refresh in a way that destabilizes WebUI.

Modify apply_upscale_performance_defaults() to:

Clamp payload values to the safer ceilings used by ensure_safe_upscale_defaults() (max tile 768, overlap 128, max mp 8 by default) unless explicitly overridden by caller.

OR (preferred) convert it into a thin wrapper that calls ensure_safe_upscale_defaults(...) and logs that it is enforcing safe ceilings.

Add SDWebUIClient.close() that calls self._session.close() (best-effort).

Add a __del__ that calls close() (best-effort, swallow exceptions).

Ensure any /options call site inside client.py:

does not POST if there is no change (you already do this in ensure_safe_upscale_defaults 

client

; make sure the “performance defaults” path has the same property).

Why: right now the “performance defaults” payload is huge (1920 tiles, 16MP) 

client

 and is the strongest “Copilot introduced this; it happens early; then WebUI dies” candidate.

3) Tests — prove the lock works and prevents back-to-back updates

Create tests/api/test_webui_api_options_throttle.py:

Test A — concurrent apply_options only calls update once

Create a stub client object with update_options counting calls.

Construct WebUIAPI(client=stub, options_min_interval=999, time_provider=fixed_time).

Start two threads that call apply_options({"a": 1}, stage="x") at the same time.

Assert stub.update_calls == 1.

Test B — identical payload hash is skipped

Call apply_options({"a": 1}) twice with time advanced beyond interval or same time; assert second call returns False and does not call update again.

Test C — throttle interval blocks rapid different payloads

Call apply_options({"a": 1}) then immediately apply_options({"a": 2}) with options_min_interval=8 and same time_provider; assert second is skipped.

TEST PLAN (MANDATORY)
Commands Executed
python -m pytest tests/api/test_webui_api_options_throttle.py -q
python -m pytest tests/api -q

Output

Executor must paste full output.

VERIFICATION & PROOF
git diff
git diff

git status
git status --short

Targeted grep proof
git grep -n "apply_upscale_performance_defaults" -n src/api/client.py
git grep -n "_options_lock" -n src/api/webui_api.py

TECH-DEBT IMPACT

Removes tech debt: makes “throttled options plumbing” true (thread-safe) instead of best-effort.

Introduces no new tech debt: lock is localized; tests pin behavior.