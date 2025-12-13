PR TEMPLATE — v2.7-X.md (EXECUTOR-ENFORCED / ZERO-LATITUDE)
🔒 CODEX / EXECUTOR PROMPT (MUST BE COPIED VERBATIM)

SYSTEM / EXECUTOR INSTRUCTION — DO NOT IGNORE

You are acting as a deterministic code executor, not a collaborator.

You MUST:

Execute every step in this PR literally

Modify every file listed

Run every test suite listed

Report file-by-file diffs

You MUST NOT:

Skip steps

Mark steps as optional

Reinterpret instructions

Claim work is done unless verified

REQUIRED BEHAVIOR

For each section below, you must output:

[VERIFIED] or [REFUSED]

Evidence (file path + line numbers or command output)

If any step cannot be completed, you MUST:

Stop immediately

Explain precisely why

Make zero code changes

Partial completion is considered FAILURE.

0. EXECUTOR LOCK-IN RULES (ABSOLUTE)

This PR MUST be executed atomically

If any file, test, or invariant fails → REFUSE

Silence, omission, or assumption = FAILURE

1. Purpose / Intent (DECLARATIVE, NOT DESCRIPTIVE)

What invariant is being enforced

What illegal state is being eliminated

Why the current system is provably incorrect

No future tense. No “should”.

2. Scope Declaration (NON-NEGOTIABLE)
2.1 Files That MUST Be Modified

Executor MUST modify all of the following or REFUSE:

src/pipeline/pipeline_runner.py
src/pipeline/run_plan.py
src/pipeline/job_models_v2.py
src/pipeline/job_builder_v2.py
tests/pipeline/test_pipeline_runner*.py
tests/pipeline/test_run_plan*.py
tests/queue/test_queue_njr_path.py


❗ If any file exists but is not modified → REFUSE

2.2 Files That MUST Be DELETED (If Present)
src/pipeline/legacy_njr_adapter.py


Executor MUST:

Prove deletion with git status

Grep for references and show zero matches

3. Architectural Invariants (HARD FAIL IF VIOLATED)

Executor MUST PROVE:

❌ No PipelineConfig enters the runner

❌ No NJR → PipelineConfig conversion exists

❌ No dict-based runner return values

✅ PipelineRunResult is the only runner output

✅ run_njr() is the only public entrypoint

If any invariant is false → REFUSE.

4. File-Level Change Instructions (MACHINE-ENFORCEABLE)
4.1 FILE: src/pipeline/pipeline_runner.py
Preconditions (Executor MUST verify)

run_njr() exists

_execute_with_config() exists

normalize_run_result() exists

If any precondition fails → REFUSE.

Required Operations (ALL MANDATORY)

DELETE

Entire _execute_with_config() function

Entire _pipeline_config_from_njr() function

MODIFY

Replace run_njr() body with:

Direct call to build_run_plan_from_njr

Execution without PipelineConfig

Typed PipelineRunResult return ONLY

REPLACE

normalize_run_result(dict) →

normalize_run_result(PipelineRunResult)

Executor MUST show before/after code.

4.2 FILE: src/pipeline/run_plan.py

ADD

Explicit assertion:

assert isinstance(njr, NormalizedJobRecord)


DELETE

Any code path accepting dicts or configs

5. Test Enforcement (NO EXCEPTIONS)

Executor MUST run:

pytest tests/pipeline -q
pytest tests/queue -q


Executor MUST:

List failing tests before fix

Show them passing after fix

“No tests found” = REFUSE

6. GUI / Queue Stall Diagnostics (MANDATORY)

Executor MUST ensure:

UI heartbeat timestamp is updated on main loop

Queue runner heartbeat updated per job stage

Watchdog runs on its own thread

Diagnostics zip is forced on:

UI stall

Queue stall

Executor MUST prove:

Zip file creation

Filename pattern: stablenew_diagnostics_*.zip

7. Evidence Section (REQUIRED)

Executor MUST provide:

git diff --stat

git grep PipelineConfig

git grep _execute_with_config

Test output summaries

Missing evidence = FAILURE.

8. Acceptance Criteria (BINARY)

 Add-to-Queue no longer blocks UI

 Queue runner progresses jobs

 No legacy adapters exist

 All tests pass

 Diagnostics fire on forced stall

❌ EXECUTOR FAILURE CLAUSE

If executor claims completion without satisfying every section above, the PR is invalid and must be rejected.

✔ END OF TEMPLATE — v2.7-X