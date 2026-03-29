PR-CORE1-0123 — WebUI Crash Mitigation.md : Options SafeMode + No-Op Model Switching + Juggernaut Default

Problem statement (observed): WebUI runs stably when launched standalone, but when launched/connected via StableNew it exits shortly after resources populate; then StableNew sees WinError 10061 actively refused on /sdapi/v1/options and /sdapi/v1/txt2img. Your netstat snapshots show lots of short-lived connections and at least one CLOSE_WAIT on the StableNew PID, consistent with the server going away while the client still has sockets open.
Hypothesis (most likely): StableNew’s early /sdapi/v1/options traffic (even if throttled) is triggering an unstable WebUI state during/after init (or immediately after a user-initiated run begins). The fastest way to prove/mitigate is to stop writing /options entirely (SafeMode), while preserving normal image generation (/txt2img) and making model switching a true no-op when already on the desired model.

Goals

Stop crashing WebUI by introducing a default-on “Options SafeMode” that prevents all /sdapi/v1/options POSTs from StableNew unless explicitly enabled.

Ensure StableNew can still generate images (txt2img/img2img/etc.) without relying on options writes.

Make model switching truly no-op when the WebUI is already on the requested checkpoint (prevents unnecessary /options writes and model reload churn).

Make Juggernaut XL Ragnarok the StableNew default selected model, without forcing a switch if WebUI already started with it.

Improve diagnosability: when WebUI dies, capture exit code + last stdout/stderr tail in StableNew logs.

Non-goals (for this PR):

Redesigning queue/run UX.

Reworking all resource refresh behavior.

Solving every possible WebUI-side crash cause (we’re carving out the highest-probability trigger first).

Primary user impact

On startup, StableNew will not push any /options changes by default.

Jobs should no longer die immediately due to /options being hammered/posted at a fragile time.

If you want the old behavior back, you’ll flip one config flag.

Allowed files (strict)

Modify:

src/api/client.py

src/api/webui_api.py

src/api/webui_process_manager.py

src/pipeline/executor.py

src/utils/config.py

Add tests:

tests/api/test_webui_api_options_safemode.py (new)

tests/pipeline/test_executor_model_switch_noop.py (new)

Do not touch anything else.

Design
A) “Options SafeMode” (default ON)

Add a single config flag (read from existing config mechanisms in src/utils/config.py):

webui_options_write_enabled: bool = False (default)

When False:

Any code path attempting to POST /sdapi/v1/options should log and skip, not fail the stage.

When True:

Existing throttling/dedupe logic continues to apply.

Key principle: SafeMode must be enforced in the lowest possible layer (the client), so no accidental call site can bypass it.

B) No-op model switching

Right now the executor logs “Switching to model …” and then hits /options. We need to avoid that unless it’s truly necessary.

Implementation approach:

On first connection-ready, do one /sdapi/v1/options GET (read-only) to discover current sd_model_checkpoint.

Normalize/compare:

If requested model matches current (string match after normalization), treat as no-op.

Only if different:

If SafeMode is ON: do not switch, but log a warning that model switching is disabled.

If SafeMode is OFF: proceed to set via /options POST (existing path).

This gives you:

Default UI choice = Juggernaut,

But StableNew won’t churn or crash WebUI by trying to “switch” to what’s already loaded.

C) WebUI crash tail logging

When WebUI exits (“Press any key to continue” / bat termination), StableNew should log:

Exit code

Last ~200 lines stdout

Last ~200 lines stderr

This is not to “fix” the crash directly, but it makes the next iteration deterministic.

Step-by-step implementation plan (executor-safe)
1) src/utils/config.py — add the flag

Add a config accessor for WEBUI_OPTIONS_WRITE_ENABLED (env var) and/or existing config store you already use.

Default value: False.

Acceptance:

You can print/log the resolved value at startup (once) without spam.

2) src/api/client.py — enforce SafeMode at the bottom

Add to the WebUI client:

A field like: self._options_write_enabled: bool

A helper: _options_write_allowed() -> bool

Then in every method that POSTs /sdapi/v1/options:

If not allowed:

log OPTIONS_WRITE_SKIPPED with reason and a short hash of the intended payload

return a sentinel “skipped” result (or False) without raising

Make sure this captures:

update_options(...)

set_model(...) (if it uses options)

ensure_safe_upscale_defaults(...)

any “performance defaults” setter

Acceptance:

With SafeMode ON, StableNew never emits a “Request POST … /sdapi/v1/options” log line, because it never attempts the POST.

With SafeMode OFF, behavior remains as before (including throttle/dedupe).

3) src/api/webui_api.py — don’t fight the client

Keep your locking + throttling logic, but before doing anything:

If client says options writes are disabled, return “skipped”.

apply_options() should be able to return one of:

APPLIED

SKIPPED_SAFEMODE

SKIPPED_THROTTLE

FAILED

Acceptance:

Callers can log a single line stating what happened, without ambiguity.

4) src/pipeline/executor.py — no-op model switching + SafeMode behavior

In the model switching function:

Introduce a “current model resolver”:

On first call, attempt a single GET /sdapi/v1/options to read sd_model_checkpoint.

Cache it as self._current_model_checkpoint (or reuse your existing tracking field).

If desired == current:

return immediately (no POST)

If desired != current:

If SafeMode ON:

log: “Model switch requested but options writes disabled; continuing with current model.”

do not error

Else:

proceed as today

Also: set StableNew’s default selection to Juggernaut without forcing a switch:

Make the default model string match the title you see in /sdapi/v1/sd-models (likely juggernautXL_ragnarokBy.safetensors [dd08fa32f9] or its title form).

Prefer storing the exact model title used by WebUI to avoid mismatch churn.

Acceptance:

Startup no longer immediately triggers “Switching to model …” unless it’s genuinely different.

With SafeMode ON, queue runs should not attempt /options POST at all.

5) src/api/webui_process_manager.py — crash tail logging

Ensure stdout/stderr are buffered (ring buffer).

When process exits:

log structured payload with exit code and tails

update connection state to a distinct “CRASHED” (or at least DISCONNECTED with reason)

Acceptance:

The log contains actionable tail output the moment WebUI exits.

Test plan
New: tests/api/test_webui_api_options_safemode.py

Create a stub client where options_write_enabled=False

Call apply_options() with a payload

Assert:

returns SKIPPED_SAFEMODE

underlying POST is never invoked

New: tests/pipeline/test_executor_model_switch_noop.py

Stub /options GET to return sd_model_checkpoint = "juggernautXL_ragnarokBy.safetensors [dd08fa32f9]" (or whatever your normalized form is)

Request the same model in the executor

Assert:

no call to client.set_model / update_options

Also test: SafeMode ON + desired != current:

does not raise

logs warning

continues

Rollback plan

Flip WEBUI_OPTIONS_WRITE_ENABLED=1 (or equivalent config) to restore pre-SafeMode behavior.

No data migration.