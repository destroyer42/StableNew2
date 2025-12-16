PR-CORE1-D11A-WEBUI-FAILURE-DIAGNOSTICS.md
EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

(Executor must include acknowledgement exactly per PR TEMPLATE.)

PR METADATA
PR ID

PR-CORE1-D11A-WEBUI-FAILURE-DIAGNOSTICS

Related Canonical Sections

Canonical Execution Contract §3 (Proof), §7 (PipelineRunner Contract), §10 (Diagnostics & Watchdog), §15 (Drift Arrest)

INTENT (MANDATORY)

Do

When /txt2img returns 500 or connection failures occur, capture actionable diagnostics (request summary + WebUI stdout/stderr tail + session_id) and attach them to the error envelope/logs.

Trigger a DiagnosticsServiceV2 bundle on “WebUI crash suspected” (HTTP 500 + subsequent connection refused, or explicit process death detection).

Do NOT

Change queue semantics, retry policy, or restart behavior (those are in D11B).

Add any non-NJR execution paths.

SCOPE OF CHANGE (EXPLICIT)
Files TO BE MODIFIED (REQUIRED)

src/api/client.py — enrich error logging/exception context for HTTP 500 and connection refused; include session_id, endpoint, and response snippet if safe.

src/api/webui_process_manager.py — add a safe method to capture recent stdout/stderr tail for diagnostics without blocking.

src/utils/diagnostics_service_v2.py (or wherever DiagnosticsServiceV2 lives in repo) — add an entrypoint to include “webui tail” artifacts if provided.

src/pipeline/executor.py — when a stage fails due to WebUI 500/unavailable, include new diagnostic fields in the wrapped envelope (no behavior change).

Files TO BE DELETED (REQUIRED)

None.

Files VERIFIED UNCHANGED

src/pipeline/pipeline_runner.py (NJR-only entrypoint remains as-is)

src/controller/job_service.py and queue runner behavior (handled in D11B)

ARCHITECTURAL COMPLIANCE

 NJR-only execution path (no PipelineConfig)

 No dict-based execution configs introduced

 Diagnostics remain non-blocking (§10)

IMPLEMENTATION STEPS (ORDERED, NON-OPTIONAL)

SDWebUIClient diagnostics context

In src/api/client.py, in the request/response path that logs HTTPError POST ... status=500, capture:

endpoint (/sdapi/v1/txt2img)

session_id

HTTP status

a short response text snippet

For connection refused / NewConnectionError, classify it as webui_unavailable=True and include the last known session_id.

WebUI process tail capture

In src/api/webui_process_manager.py, implement:

get_recent_output_tail(max_lines=200) -> dict(stdout_tail:str, stderr_tail:str, pid:int|None, running:bool)

Must be safe when process is not running.

Attach tail to envelope/logs

In src/pipeline/executor.py, when wrapping PipelineStageError due to WebUI failures:

attach webui_stdout_tail, webui_stderr_tail, webui_pid, webui_running into error_envelope.context (or equivalent) only when available.

Diagnostics bundle hook

Add a call site (best location: where the error is first recognized as “crash suspected”) that asks DiagnosticsServiceV2 to emit a bundle with:

the webui tails

the last request metadata (endpoint, status, session_id; do not dump full prompt text unless already allowed elsewhere)

TEST PLAN (MANDATORY)
Commands Executed
python -m pytest -q tests/test_api_client.py
python -m pytest -q tests/api/test_webui_api_options_throttle.py
python -m pytest -q tests/system/test_watchdog_ui_stall.py
python -m pytest -q tests/journeys/test_jt03_txt2img_pipeline_run.py

New/Updated Tests Required

Add/extend a unit test that simulates:

HTTP 500 on /txt2img

then connection refused on retry

assert the logged/enveloped context contains session_id and that tail capture was attempted.

VERIFICATION & PROOF
git diff
git diff

git status
git status --short

Forbidden Symbol Check
grep -R "PipelineConfig" src/ | cat

GOLDEN PATH CONFIRMATION

Run and paste output for:

tests/journeys/test_jt03_txt2img_pipeline_run.py

FINAL DECLARATION

(Executor must complete template checklist with proof.)