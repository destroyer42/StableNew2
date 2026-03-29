PR-CORE1-D11 – WebUI Crash Recovery + Stage Retry Gate.md

(Use PR TEMPLATE — v2.7.1-X.md structure exactly; below is filled in with explicit executor-safe steps for GPT-5.1 Codex-mini.)

0) PR Metadata

PR ID: PR-CORE1-D11

Title: WebUI Crash Recovery + Stage Retry Gate (stop connection-refused cascade; restore image outputs)

Risk Tier: Tier 2 (API + runner/controller interaction)

Primary Goal: If WebUI returns 500 or becomes unreachable during stage execution, StableNew:

captures actionable diagnostics (payload + WebUI tail logs),

restarts WebUI safely via ProcessManager,

retries the stage once (bounded), and

only then fails the job with a high-signal error.

1) Intent

Fix the real-world production failure where queued jobs repeatedly hit POST /sdapi/v1/txt2img → 500, followed by WebUI dying (connection refused), resulting in no images produced and WebUI repeatedly crashing.

2) Non-goals (to keep Codex from wandering)

Do not redesign GUI.

Do not change PromptPack sourcing rules.

Do not add new DTOs (reuse existing patterns).

Do not broaden retry loops beyond this PR’s bounded policy.

Do not alter SafeMode policy beyond explicit changes listed here.

3) Architectural Justification (v2.6 alignment)

Runner remains execution-focused; recovery is implemented as a well-bounded infrastructure safeguard.

WebUI lifecycle actions (restart, tail capture) belong with api/process manager, not PromptPack or GUI.

Failure artifacts go to run directories / diagnostics bundles, consistent with Debug/Diagnostics practices.

4) Problem Statement (observable symptoms)

From your run log:

txt2img returns 500 repeatedly.

Eventually fails with connection refused: WebUI is down.

Next jobs repeat immediately, amplifying the problem.

No “what payload did we send?” or “what did WebUI print right before dying?” is persisted, making debugging slow.

5) Proposed Change Summary

Add a Crash-Aware Stage Call Wrapper used by the pipeline execution path that:

Detects HTTP 500 and WebUIUnavailable.

Writes stage_failure_payload.json (sanitized) into the run folder.

Captures last N lines of WebUI stdout/stderr into a webui_tail.log artifact.

Performs one controlled restart of WebUI and re-probes readiness.

Retries the stage once after restart.

If still failing, job fails with an error envelope that points to saved artifacts.

6) File Modification Map

Modify / add only what’s needed.

Modify

src/api/webui_process_manager.py

src/api/webui_api.py

src/api/client.py

src/pipeline/executor.py

src/pipeline/pipeline_runner.py

src/controller/app_controller.py (only if needed to inject dependencies cleanly)

Add

src/api/webui_tail_capture.py (small helper; pure utility)

tests/integration/test_webui_crash_recovery.py

tests/api/test_client_txt2img_retry_policy.py

7) Detailed Implementation Steps (Codex-mini safe, explicit)
Step A — Add “tail capture” utility (no behavior change yet)

File: src/api/webui_tail_capture.py (new)

Implement a small helper that can:

accept a Popen-like process handle (or pid) and/or file paths used by your process manager logging

return a string with last ~200 lines of stdout/stderr if available

be defensive: if tail cannot be captured, return a clear placeholder string

Hard requirement: must never raise; always returns something.

Step B — Enhance WebUIProcessManager to expose “tail logs”

File: src/api/webui_process_manager.py

Add methods:

get_tail_logs(max_lines: int = 200) -> dict[str, str]

returns { "stdout": "...", "stderr": "..." }

is_process_alive() -> bool

restart_and_wait_ready(timeout_s: float) -> bool

must use the existing start/stop + readiness probe mechanisms already present (do not invent new launch logic)

Guardrails:

Restart must be serialized (lock) so multiple threads cannot restart at once.

If restart fails, it returns False and logs reason.

Step C — Define bounded recovery policy in the API client request layer

File: src/api/client.py

In _perform_request / request retry loop, add:

If status is 500 and stage is txt2img|img2img|extra-single-image:

log a structured event that includes stage + attempt + payload keys (not full prompt)

raise a stage-specific exception (or reuse existing WebUIUnavailableError) that signals “server error likely transient / crash-related”.

Important: do not endlessly retry. This PR should keep request-level retries as-is, but allow upper layer to do one restart+retry.

Step D — Add crash-aware wrapper at the WebUIAPI layer

File: src/api/webui_api.py

Add a method:

generate_images_with_recovery(stage: str, payload: dict, run_dir: Path | None, job_id: str | None) -> outcome

Behavior:

Try normal client call: client.generate_images(...).

If success → return.

If failure is:

HTTP 500 (mapped from client), OR

WebUIUnavailable / connection refused,
then:

write failure artifact(s) if run_dir provided:

run_dir / "stage_failure_payload.json" (sanitize prompt text: store prompt length + hash, not full text)

run_dir / "webui_tail.log" (stdout+stderr tails)

call process_manager.restart_and_wait_ready(timeout_s=...)

retry exactly once

If still fails → return failure outcome with references to artifact paths (strings).

Do not put this logic in GUI or PromptPack.

Step E — Wire pipeline executor to call recovery wrapper (minimal)

File: src/pipeline/executor.py

Currently _generate_images() calls self.client.generate_images(...).

Change this so Pipeline can be constructed with either:

a plain SDWebUIClient, OR

a WebUIAPI (or adapter) that supports generate_images_with_recovery.

Executor-safe approach (smallest diff):

Introduce a tiny interface-like convention:

if hasattr(self.client, "generate_images_with_recovery"): call it and pass run_dir/job_id

else: call existing generate_images

This keeps tests and current wiring stable.

Step F — Ensure pipeline runner passes run_dir and job_id down

File: src/pipeline/pipeline_runner.py

When creating run directory / run metadata, ensure the runner has:

run_id

run_dir

job_id

Pass these into the executor stage calls so recovery artifacts land next to the run that failed.

Step G — Prevent “cascade job failures” after a detected crash

File: src/queue/single_node_runner.py (in repo snapshot; modify if present)

When a job fails specifically due to WebUI crash/unavailable:

before starting next job, call a lightweight readiness check (or just rely on restart_and_wait_ready being triggered during the failing job)

ensure runner does not immediately hammer the API again if WebUI is restarting (short sleep/backoff is OK, but keep it bounded and deterministic)

8) Tests Required
New unit tests

File: tests/api/test_client_txt2img_retry_policy.py

Simulate POST /txt2img returning 500 and confirm:

client maps it into the intended exception / failure signal

request-level retry count remains bounded

New integration test (critical)

File: tests/integration/test_webui_crash_recovery.py
Create a fake WebUIAPI + fake ProcessManager:

first call to generate returns 500

restart succeeds

second call returns success
Assert:

job result ends success

artifacts were written (payload + tail log)

restart was invoked exactly once

Proof the original failure is now actionable

Add assertions that when the second attempt also fails:

result is failed

error envelope references artifact paths

9) Manual Proof Commands (paste exactly)

Run these from repo root:

python -m pytest -q tests/api/test_client_txt2img_retry_policy.py
python -m pytest -q tests/integration/test_webui_crash_recovery.py
python -m pytest -q tests/pipeline/test_pipeline_io_contracts.py
python -m pytest -q tests/pipeline/test_pipeline_runner_cancel_token.py


Then run one real job:

python -m src.main


Verify:

On failure, a run folder contains:

stage_failure_payload.json

webui_tail.log

On transient crash, WebUI restarts once and job completes with images.

10) Tech Debt Impact

This PR reduces tech debt by:

making WebUI failures observable (payload + tail logs saved)

replacing “mysterious 500 then dead WebUI” with a controlled recovery path

preventing repeated job submissions from acting like a denial-of-service on your own WebUI

11) Rollback Plan

If recovery behavior introduces instability:

revert calls to generate_images_with_recovery

keep tail capture as a passive utility (safe to keep)

revert restart hook and return to fail-fast behavior