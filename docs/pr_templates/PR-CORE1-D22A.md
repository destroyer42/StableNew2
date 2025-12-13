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

# PR-CORE1-D22A — NJR-only runner core cleanup (remove PipelineConfig + dict execution paths)

## 0. Authority
- **Contract:** StableNew v2.6 – Canonical Execution Contract (attached)
- **Template:** PR TEMPLATE — v2.7.1-X (this format is mandatory)

## 1. Intent
Make PipelineRunner strictly NJR-only by deleting PipelineConfig + config-based execution entrypoints, leaving a single canonical run_njr that returns PipelineRunResult.

## 2. Non-Negotiable Outcomes
- `src/pipeline/pipeline_runner.py` contains **no** `PipelineConfig` symbol and **no** NJR→PipelineConfig conversion.
- `PipelineRunner` has exactly **one** public execution entrypoint: `run_njr(...)`.
- All runner execution returns `PipelineRunResult` (typed), never dict.
- Executor provides grep-proof that `PipelineConfig` is absent from `pipeline_runner.py`.


## 3. In Scope Files (exact)
- `src/pipeline/pipeline_runner.py` (primary)

## 4. Out of Scope
- Any changes not explicitly listed above.
- Any behavior changes outside the specified code paths.

## 5. Implementation Plan (line-level)
### 5.1 Remove PipelineConfig and config-based execution from PipelineRunner (NJR-only)

**File:** `src/pipeline/pipeline_runner.py`

1) **DELETE** the embedded legacy `PipelineConfig` dataclass.
   - Remove **lines 38–61** (`@dataclass class PipelineConfig ...`) entirely.
   - Rationale: PipelineConfig is forbidden in execution code (contract §4.1, §7.2).

2) **DELETE** the legacy one-off config execution entrypoint.
   - Remove **lines 154–227** (`def run_txt2img_once(...)` and its body) entirely.
   - Also remove any helper calls that exist only to support this path:
     - Remove `_execute_with_config` (**starts line 229**) and its full implementation block up to just before the next method (`def __init__` at **line 179** is currently out-of-order; see step 5.2 to reorder the class).
   - NOTE: This file currently contains interleaved/duplicated methods; deletion must be done carefully to leave exactly one public entrypoint (run_njr).

3) **DELETE** all NJR→PipelineConfig conversion helpers and any remaining PipelineConfig symbols.
   - Remove the duplicate/legacy `run_njr` implementation that begins at **line 484** (this one is tied to config bridging).
   - Remove `_pipeline_config_from_njr` (**line 505**) and any helpers it depends on.

4) **ENFORCE**: `PipelineRunner` exposes **only**:
   - `run_njr(self, njr: NormalizedJobRecord, cancel_token: CancelToken | None = None) -> PipelineRunResult`
   - `replay_njr(...)` (if present/needed), but it MUST accept NJR and return PipelineRunResult.
   - Any other “run” or config-based helper MUST be:
     - deleted, OR
     - moved to a **VIEW-ONLY** legacy module (see D22B), and must not be imported by runtime code.

5) **REORDER / CLEANUP** the class so methods are not duplicated or interleaved.
   - Ensure there is exactly **one** `run_njr` method definition in the class.
   - Ensure there are **zero** references to `PipelineConfig` in this module after this PR.

### 5.2 Make run_njr execute via RunPlan built from NJR (no inference)

**File:** `src/pipeline/pipeline_runner.py`

6) In the remaining canonical `run_njr` (currently the short one that begins at **line 68**):
   - Keep: `plan = build_run_plan_from_njr(njr)` (**lines 109–112**)
   - Ensure execution delegates to a single internal function that consumes **RunPlan only** (e.g., `_execute_plan(plan, cancel_token)`), and that it returns **PipelineRunResult**.
   - Ensure cancel_token is threaded through every stage execution call.

7) Ensure **all returns** from runner code paths are `PipelineRunResult`, never dict.
   - Verify the type at the end of `run_njr` (currently returns `result` at **line 150**).
   - If any internal helper returns dicts, refactor them to return typed results.

### 5.3 Add hard “forbidden symbol” guardrails in runner module

**File:** `src/pipeline/pipeline_runner.py`

8) Add a module-level comment near the top (after imports) that marks forbidden symbols and intended entrypoint:
   - “NJR-only. PipelineConfig forbidden in execution. Only run_njr is public.”

9) Add a minimal unit-testable guard:
   - If any other code attempts to call a config-based path (if any remains), it must raise `RuntimeError("PipelineConfig execution is forbidden in v2.6")` immediately.



## 6. Tests (MANDATORY) + Exact Commands
Run exactly:

```cmd
python -m pytest -q tests/pipeline/test_pipeline_runner.py
python -m pytest -q tests/pipeline/test_pipeline_runner_cancel_token.py
python -m pytest -q tests/pipeline/test_pipeline_runner_variants.py
```

(These will still fail until D22C lands; still run them and paste output as proof of current state.)


## 7. Required Proof (MANDATORY)
- `git status --short` (before + after)
- `git diff` (full)
- `python -m pytest -q ...` commands above + full output
- `python -m pytest --version`
- Grep proof that PipelineConfig is gone from runner module:

```cmd
python -c "import pathlib; p=pathlib.Path('src/pipeline/pipeline_runner.py'); t=p.read_text(encoding='utf-8'); print('PipelineConfig' in t)"
```

Expected output: `False`


## 8. Rollback Plan
- Revert this PR commit(s).
- Confirm Golden Path tests still pass on main.

