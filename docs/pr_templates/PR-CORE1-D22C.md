## CODEX/Co-pilot EXECUTION PROMPT (PASTE AS FIRST MESSAGE TO EXECUTOR)

You are the **Executor** for this PR. You MUST follow **StableNew v2.6 – Canonical Execution Contract**.  
You MUST follow this PR document **exactly**. No shortcuts. No substitutions.

**Hard requirements:**
1) Implement **ALL** required changes in **ALL** listed files.  
2) Provide **machine-verifiable proof** for every MUST (git diff, git status, pytest output, grep output).  
3) If you cannot comply, STOP and report exactly what is blocking you (with file/line proof).

**Before coding (MANDATORY):**
- Print `git status --short`
- Print `python -m pytest --version`

**After coding (MANDATORY):**
- Print `git diff` (full)
- Print `git status --short`
- Run EXACT tests listed in this PR and paste full output.

**Forbidden:**
- “I ran tests” without output
- Partial implementation
- Editing files not in scope
- Leaving legacy bridge paths active (unless explicitly marked VIEW-ONLY)

Now execute the PR steps exactly as written below.


# EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK (MANDATORY)

## READ FIRST — EXECUTION CONTRACT ACKNOWLEDGEMENT

You are acting as an **Executor** for the StableNew v2.6 codebase.

By proceeding, you **explicitly acknowledge** that:

1. You have read and understand the attached document  
   **`StableNew_v2.6_Canonical_Execution_Contract.md`**

2. You agree that this document is the **single authoritative source of truth** for:
   - Architecture
   - Execution semantics
   - NJR enforcement
   - PromptPack lifecycle
   - Queue + Runner behavior
   - Diagnostics & watchdog behavior
   - Golden Path requirements
   - Executor obligations

3. You understand that:
   - PR instructions
   - Test expectations
   - Prior code behavior
   - Your own interpretations  

   **DO NOT override the Canonical Execution Contract**

---

## ABSOLUTE EXECUTION RULES (NON‑NEGOTIABLE)

### 1. Scope Completion
- You MUST implement **100% of the PR scope**
- You MUST modify **every file listed**
- You MUST delete **every file marked REQUIRED for deletion**
- Partial implementation is **explicitly forbidden**

### 2. NJR‑Only Enforcement
You MUST:
- Treat `NormalizedJobRecord (NJR)` as the **only valid runtime job**
- Reject:
  - `PipelineConfig`
  - dict‑based configs
  - legacy adapters in execution paths

Any execution path using those is a **hard violation**.

### 3. Proof Is Mandatory
For **every MUST**, you MUST provide **machine‑verifiable proof**, including as applicable:

- Full `git diff`
- `git status --short`
- pytest commands **with captured output**
- grep output for forbidden symbols
- Exact file + line references for behavioral changes

**Claims without proof are invalid.**

### 4. Tests Are Not Optional
You MUST:
- Run all tests explicitly required by the PR or Canonical Contract
- Show command + output
- Address failures immediately

Saying “tests pass” without output is **non‑compliance**.

---

## EXPLICIT PROHIBITIONS (FAILURE CONDITIONS)

You MUST NOT:

- Modify only one file when multiple are listed
- Skip deletions marked REQUIRED
- Claim tests ran when they did not
- Stop after “core logic” changes
- Replace required behavior with refactors
- Ignore or silence failing tests
- Invent reasons you “cannot” perform required steps

Any of the above = **PR rejection**

---

## DRIFT HANDLING

If you encounter:
- Ambiguity
- Missing context
- Conflicting instructions

You MUST:
1. STOP
2. State exactly what is blocking you
3. Request clarification

You MUST NOT guess, improvise, or partially proceed.

---

## ACKNOWLEDGEMENT STATEMENT (REQUIRED)

By continuing execution, you are operating as if you had stated:

> “I acknowledge the StableNew v2.6 Canonical Execution Contract.  
> I understand that partial compliance, undocumented deviations, or unverifiable claims constitute failure.  
> I will either complete the PR exactly as specified with proof, or I will stop.”

If you cannot comply with **all** of the above:

**STOP IMMEDIATELY. DO NOT PROCEED.**

---

# PR METADATA

## PR ID
`PR‑<AREA>-<NUMBER>-<SHORT‑TITLE>`

## Related Canonical Sections
(List exact section numbers from Canonical Execution Contract)

---

# INTENT (MANDATORY)

Describe **exactly** what this PR does and **what it does NOT do**.

---

# SCOPE OF CHANGE (EXPLICIT)

## Files TO BE MODIFIED (REQUIRED)
- `path/to/file.py` — purpose

## Files TO BE DELETED (REQUIRED)
- `path/to/legacy_file.py`

## Files VERIFIED UNCHANGED
- (explicitly list)

---

# ARCHITECTURAL COMPLIANCE

- [ ] NJR‑only execution path
- [ ] No PipelineConfig usage in runtime
- [ ] No dict‑based execution configs
- [ ] Legacy code classified (DELETED or VIEW‑ONLY)

---

# IMPLEMENTATION STEPS (ORDERED, NON‑OPTIONAL)

1. Step 1 (file + function + behavior)
2. Step 2
3. Step 3

---

# TEST PLAN (MANDATORY)

## Commands Executed
```bash
python -m pytest <exact paths>
```

## Output
```text
(paste full output)
```

---

# VERIFICATION & PROOF

## git diff
```bash
git diff
```

## git status
```bash
git status --short
```

## Forbidden Symbol Check
```bash
grep -R "PipelineConfig" src/
```

---

# GOLDEN PATH CONFIRMATION

List Golden Path tests executed and results.

---

# FINAL DECLARATION

This PR:
- [ ] Fully implements the declared scope
- [ ] Includes all required deletions
- [ ] Passes all required tests
- [ ] Includes verifiable proof

Incomplete PRs **must not be submitted**.

---

END OF TEMPLATE

# PR-CORE1-D22C — Tests + verification: NJR-only runner + typed results + typed API outcomes

## 0. Authority
- **Contract:** StableNew v2.6 – Canonical Execution Contract (attached)
- **Template:** PR TEMPLATE — v2.7.1-X (this format is mandatory)

## 1. Intent
Update affected unit tests to follow the v2.6 NJR-only runner contract and typed result/outcome expectations; run Golden Path gates.

## 2. Non-Negotiable Outcomes
- All updated tests call `PipelineRunner.run_njr(...)` (NJR-only).
- All result assertions use `PipelineRunResult` fields, not dict keys.
- `tests/test_cancel_token.py` uses typed `GenerateOutcome/GenerateResult` mocks (no dict result).
- Queue tests do not use `pipeline_config` attribute; they use v2.6 Job fields (`config_snapshot` and/or attached NJR).
- All listed tests pass, including Golden Path gates, with pasted output.


## 3. In Scope Files (exact)
- `tests/pipeline/test_pipeline_runner_cancel_token.py`
- `tests/pipeline/test_pipeline_runner_variants.py`
- `tests/pipeline/test_stage_sequencer_runner_integration.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/test_cancel_token.py`
- `tests/queue/test_job_variant_metadata_v2.py`
- `tests/queue/test_queue_njr_path.py`
- `tests/queue/test_single_node_runner_loopback.py`


## 4. Out of Scope
- Any changes not explicitly listed above.
- Any behavior changes outside the specified code paths.

## 5. Implementation Plan (line-level)
### 5.1 Update pipeline-runner tests to call NJR-only entrypoint and assert typed result

#### A) `tests/pipeline/test_pipeline_runner_cancel_token.py`

1) Replace every call to `runner.run(` (current hits at **lines 54, 95, 128, 140**) with `runner.run_njr(`.
2) Replace the `PipelineConfig(...)` objects (example around **lines 120–139**) with a schema=2.6 `NormalizedJobRecord`.
   - Use the existing local helper in this file if present; otherwise create a `_njr_from_minimal(prompt=..., stages=...)` helper **inside this test file**.
3) Update assertions:
   - Replace `result.success` / `result.variant_count` accesses expecting dict with typed `PipelineRunResult` fields.

#### B) `tests/pipeline/test_pipeline_runner_variants.py`

4) Replace `runner.run(config, ...)` at **line 49** with `runner.run_njr(njr, ...)`.
5) Replace `PipelineConfig(... variant_configs=...)` with NJR variant metadata (as expected by `build_run_plan_from_njr`).
6) Assert `result.variant_count == len(variant_cfgs)` using `PipelineRunResult.variant_count`.

#### C) `tests/pipeline/test_stage_sequencer_runner_integration.py`

7) Replace calls to `runner.run(...)` (hits at **lines 42, 68, 91**) with `runner.run_njr(...)`.
8) Ensure the test obtains pipeline calls from the runner in a way that still works with the v2.6 runner (if pipeline is injected/mocked, keep that).
9) Replace assertions:
   - `result.success` remains valid if `PipelineRunResult.success` exists.
   - `result.stage_events` must be asserted as a list on `PipelineRunResult.stage_events` (not dict).

#### D) `tests/pipeline/test_pipeline_runner.py`

10) Update the contract test(s) so they enforce:
   - `PipelineRunner.run_njr` is the public entrypoint
   - No config-based entrypoint exists (or it raises fast).
   - If the test currently references `.run(...)`, update it to `.run_njr(...)` and/or assert that `.run` is absent.

### 5.2 Fix GenerateOutcome mocks to return typed GenerateResult, not dict

**File:** `tests/test_cancel_token.py`

11) Replace `_success_outcome` at **lines 18–19**:
   - From: `SimpleNamespace(ok=True, result={"images": images})`
   - To: return a real `GenerateOutcome(ok=True, result=GenerateResult(...))`

   Required fields for `GenerateResult` (from `src/api/types.py`):
   - `images` (list[str])
   - `info` (str or dict as defined)
   - `stage` (str)
   - `timings` (dict[str, float] or as defined)

12) Update `mock_client.generate_images` and any other API mocks in this file that currently return dicts so they match the executor’s expectations.

### 5.3 Fix queue tests to build v2.6 Jobs correctly (no pipeline_config attribute)

#### A) `tests/queue/test_job_variant_metadata_v2.py`

13) Replace `_make_job` helper usage that passes `pipeline_config=` (hits at **lines 18, 27, 28, 30**) with v2.6-valid Job construction:
   - Use `Job(job_id=..., priority=JobPriority.NORMAL, config_snapshot=<dict>, ...)`
   - If you need an NJR for the job, store it on the job via the repo’s expected mechanism (e.g., `_normalized_record` attribute), but do not use `pipeline_config`.

14) Replace any attempt to set `job.pipeline_config = ...` with `job.config_snapshot = ...`.

#### B) `tests/queue/test_queue_njr_path.py`

15) Fix the legacy test path that assigns `job.pipeline_config = PipelineConfig(...)` (hit at **line 99**):
   - Replace with `job.config_snapshot = {...}` OR create an NJR and attach it to the job as the v2.6 queue expects.
   - If “legacy pipeline_config-only job” is no longer supported per v2.6 contract, rewrite this test to assert VIEW-ONLY behavior (no execution).

#### C) `tests/queue/test_single_node_runner_loopback.py`

16) Fix incorrect Job construction that passes `PipelineConfig` into the `priority` positional argument (hit at **line 24**):
   - Replace `Job("j1", _cfg())` with keyword args:
     - `Job(job_id="j1", priority=JobPriority.NORMAL, config_snapshot=_cfg_dict())`

### 5.4 Ensure watchdog tests aren’t blocked by D22 changes

17) Do not modify watchdog tests here unless they fail due to runner API changes; keep D22C scoped to runner+queue test contract fixes.



## 6. Tests (MANDATORY) + Exact Commands
Run exactly:

```cmd
python -m pytest -q tests/pipeline/test_pipeline_runner.py
python -m pytest -q tests/pipeline/test_pipeline_runner_cancel_token.py
python -m pytest -q tests/pipeline/test_pipeline_runner_variants.py
python -m pytest -q tests/pipeline/test_stage_sequencer_runner_integration.py
python -m pytest -q tests/test_cancel_token.py
python -m pytest -q tests/queue/test_job_variant_metadata_v2.py
python -m pytest -q tests/queue/test_queue_njr_path.py
python -m pytest -q tests/queue/test_single_node_runner_loopback.py
```

Then run Golden Path gates (contract §11.1):

```cmd
python -m pytest -q tests/journeys/test_jt01_prompt_pack_authoring.py
python -m pytest -q tests/journeys/test_jt03_txt2img_pipeline_run.py
python -m pytest -q tests/journeys/test_jt06_prompt_pack_queue_run.py
python -m pytest -q tests/gui_v2/test_main_window_smoke_v2.py
python -m pytest -q tests/system/test_watchdog_ui_stall.py
```


## 7. Required Proof (MANDATORY)
- `git status --short` (before + after)
- `git diff` (full)
- Full pytest output for **every** command listed above
- Grep proof that no test calls `runner.run(` anymore:

```cmd
python -c "import pathlib; import re; root=pathlib.Path('tests'); bad=[]; 
for p in root.rglob('*.py'):
    t=p.read_text(encoding='utf-8')
    if 'runner.run(' in t: bad.append(str(p))
print('BAD:', bad)"
```

Expected output: `BAD: []`


## 8. Rollback Plan
- Revert this PR commit(s).
- Confirm Golden Path tests still pass on main.

