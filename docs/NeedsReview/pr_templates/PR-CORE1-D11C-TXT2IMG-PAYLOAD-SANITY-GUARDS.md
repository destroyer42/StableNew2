PR-CORE1-D11C-TXT2IMG-PAYLOAD-SANITY-GUARDS.md
EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

(Executor must include acknowledgement exactly per PR TEMPLATE.)

PR METADATA
PR ID

PR-CORE1-D11C-TXT2IMG-PAYLOAD-SANITY-GUARDS

Related Canonical Sections

§7 PipelineRunner Contract (return typed results; still NJR-only)

§9 Cancellation Semantics

§15 Drift Arrest (this PR is a “repair”, not a feature)

INTENT (MANDATORY)

Do

Add payload validation/sanitization right before API calls to reduce likelihood of WebUI 500/crash.

Specifically guard:

non-serializable values

NaN/Inf floats

invalid sizes/steps

control characters in prompt/negative prompt

Do NOT

Change prompt content policies.

Change stage sequencing.

Change SafeMode or options behavior.

SCOPE OF CHANGE (EXPLICIT)
Files TO BE MODIFIED (REQUIRED)

src/pipeline/executor.py — add a validate_webui_payload(stage, payload) step before calling client; raise a typed validation error (not a raw exception).

src/api/client.py — ensure JSON encoding errors are caught and wrapped with clear error messages.

tests/pipeline/ add a focused test module, e.g. tests/pipeline/test_payload_validation.py.

Files TO BE DELETED (REQUIRED)

None.

Files VERIFIED UNCHANGED

src/pipeline/pipeline_runner.py

queue runner modules

ARCHITECTURAL COMPLIANCE

 Still NJR-only runtime

 Fail-fast validation produces deterministic failures (no retries for validation failures)

IMPLEMENTATION STEPS (ORDERED, NON-OPTIONAL)

Implement validate_webui_payload(stage, payload):

Ensure payload is JSON-serializable.

Normalize strings:

remove \x00 and other control chars except \n/\t

Validate numeric ranges (conservative defaults):

width/height > 0 and <= configured max

steps > 0 and <= configured max

cfg_scale finite number

Call this validator in the stage methods right before client.generate_images(...).

Tests:

a payload containing NaN cfg_scale fails with a typed error

prompt containing \x00 is sanitized (or rejected — pick one and lock it in)

validator does not mutate unrelated keys

TEST PLAN (MANDATORY)
Commands Executed
python -m pytest -q tests/test_cancel_token.py
python -m pytest -q tests/pipeline/test_payload_validation.py
python -m pytest -q tests/journeys/test_jt03_txt2img_pipeline_run.py

VERIFICATION & PROOF

(include git diff, git status --short, grep for PipelineConfig, and pytest outputs)

GOLDEN PATH CONFIRMATION

Run and paste output for:

tests/journeys/test_jt03_txt2img_pipeline_run.py

FINAL DECLARATION

(Executor must complete template checklist with proof.)