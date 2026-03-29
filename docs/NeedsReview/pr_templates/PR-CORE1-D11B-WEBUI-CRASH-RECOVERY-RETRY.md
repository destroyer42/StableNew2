PR-CORE1-D11B-WEBUI-CRASH-RECOVERY-RETRY.md
EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

(Executor must include acknowledgement exactly per PR TEMPLATE.)

PR METADATA
PR ID

PR-CORE1-D11B-WEBUI-CRASH-RECOVERY-RETRY

Related Canonical Sections

§8 Queue & Runner Semantics

§10 Diagnostics & Watchdog

§11 Golden Path Enforcement

§15 Drift Arrest Mechanism

INTENT (MANDATORY)

Do

When a job fails due to WebUI 500/unavailable:

pause/hold queue processing briefly

restart WebUI

retry the same NJR job once (single retry only)

Prevent “retry storms” that repeatedly kill WebUI.

Do NOT

Change PipelineRunner’s NJR-only contract.

Change PromptPack invariants.

Add new run modes or new execution entrypoints.

SCOPE OF CHANGE (EXPLICIT)
Files TO BE MODIFIED (REQUIRED)

src/queue/single_node_runner.py (or the actual runner module in snapshot) — implement retry-on-crash policy at the runner boundary.

src/api/webui_process_manager.py — add restart_webui() (or equivalent) that is idempotent and blocks until readiness.

src/api/webui_api.py — expose a “wait until ready” method used by restart.

src/controller/job_service.py — only if needed to surface job retry metadata into job status/history.

Files TO BE DELETED (REQUIRED)

None.

Files VERIFIED UNCHANGED

src/pipeline/pipeline_runner.py (no new entrypoints)

src/pipeline/job_requests_v2.py (DTO stability)

ARCHITECTURAL COMPLIANCE

 Runner remains the single execution authority (§8.2)

 Retry is deterministic, bounded (max 1), and logged

 Queue state remains consistent (no silent drops)

IMPLEMENTATION STEPS (ORDERED, NON-OPTIONAL)

Define crash-eligible failures

Add a helper predicate near the runner:

returns true for:

HTTP 500 from txt2img/img2img/upscale endpoints

connection refused / “actively refused”

“WebUI unavailable …”

Must not match prompt errors or validation errors.

Add bounded retry to SingleNode runner

For a job execution attempt:

attempt #1 runs normally

if crash-eligible failure:

log QUEUE_JOB_WEBUI_CRASH_SUSPECTED

call process manager restart

attempt #2

if attempt #2 fails again for same reason:

mark failed and log QUEUE_JOB_WEBUI_RETRY_EXHAUSTED

Restart & readiness

restart_webui() must:

stop existing process if running

start WebUI

block until check_api_ready() passes

Must include a conservative backoff (e.g., sleep 1s → 2s) and a hard cap.

Job metadata

Record retry count in job runtime metadata (and/or history record) so you can see “this job was retried”.

TEST PLAN (MANDATORY)
Commands Executed
python -m pytest -q tests/pipeline/test_run_modes.py
python -m pytest -q tests/journeys/test_jt03_txt2img_pipeline_run.py
python -m pytest -q tests/journeys/test_jt06_prompt_pack_queue_run.py

New/Updated Tests Required

New runner unit test:

fake client returns HTTP 500 once, then success

assert: restart_webui() called once, job completes, retry_count==1

New runner unit test:

always connection refused

assert: retry_count==1, job failed, queue continues to next job (no deadlock)

VERIFICATION & PROOF

(include git diff, git status --short, grep for PipelineConfig, and pytest outputs)

GOLDEN PATH CONFIRMATION

Run and paste output for:

tests/journeys/test_jt06_prompt_pack_queue_run.py

FINAL DECLARATION

(Executor must complete template checklist with proof.)