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

# PR-CORE1-D22B — Wiring: remove PipelineConfig imports and route controller one-off runs through run_njr

## 0. Authority
- **Contract:** StableNew v2.6 – Canonical Execution Contract (attached)
- **Template:** PR TEMPLATE — v2.7.1-X (this format is mandatory)

## 1. Intent
Update controller + adapters so nothing imports PipelineConfig from pipeline_runner, and any one-off execution routes through NJR-native PipelineRunner.run_njr.

## 2. Non-Negotiable Outcomes
- No module imports `PipelineConfig` from `src/pipeline/pipeline_runner.py` anymore.
- A new VIEW-ONLY legacy container exists at `src/pipeline/legacy/pipeline_config_legacy.py` with correct header.
- `AppController.run_txt2img_once` no longer calls any deleted runner entrypoint; it routes to NJR-native `run_njr`.
- Controller code treats run result as typed `PipelineRunResult` (no `dict.get(...)` on result).


## 3. In Scope Files (exact)
- `src/controller/app_controller.py`
- `src/pipeline/legacy_njr_adapter.py`
- `src/pipeline/legacy/pipeline_config_legacy.py` (NEW · VIEW-ONLY)
- `src/pipeline/__init__.py` (only if it re-exports PipelineConfig today)


## 4. Out of Scope
- Any changes not explicitly listed above.
- Any behavior changes outside the specified code paths.

## 5. Implementation Plan (line-level)
### 5.1 Create an explicit VIEW-ONLY legacy PipelineConfig container

**File:** `src/pipeline/legacy/pipeline_config_legacy.py` (NEW)

1) Create the file and add header on line 1:
   - `# VIEW-ONLY (v2.6) — legacy PipelineConfig container; execution forbidden`

2) Copy the `PipelineConfig` dataclass definition that currently lives in:
   - `src/pipeline/pipeline_runner.py` **lines 38–61** (from PR-CORE1-D22A)
   into this new file (same fields, same defaults).

3) Add a short module docstring stating:
   - Used only for VIEW-ONLY history display / migration tooling.
   - Must not be imported by runtime execution code paths.

### 5.2 Update legacy adapters to import PipelineConfig from the VIEW-ONLY module

**File:** `src/pipeline/legacy_njr_adapter.py`

4) Replace the import at **line 40**:
   - From: `from src.pipeline.pipeline_runner import PipelineConfig`
   - To: `from src.pipeline.legacy.pipeline_config_legacy import PipelineConfig`

5) Add (or keep) a VIEW-ONLY header at the top of this file if not present.
   - If it is used by runtime execution, that is a bug; this PR must make that explicit.

### 5.3 Remove/replace controller wiring that calls deleted runner methods

**File:** `src/controller/app_controller.py`

6) Fix imports at **line 51**:
   - If it imports `PipelineConfig` from runner: remove that import.
   - If it imports `PipelineRunner` only: keep.

7) Refactor the controller method `run_txt2img_once` (**starts line 284**) so it no longer calls `pipeline_runner.run_txt2img_once` (deleted in D22A):
   - Replace the call at **line 297**:
     - From: `result = self.pipeline_runner.run_txt2img_once(config)`
     - To: build a **minimal NJR** and call `self.pipeline_runner.run_njr(njr, cancel_token=...)`.

   **Minimal NJR construction rule:**
   - Use the v2.6 canonical NJR builder already in repo (search for job builder / prompt pack builder).
   - If no builder exists for “manual one-off txt2img”, create a minimal helper in an appropriate v2.6 module (NOT in controller) that produces a schema=2.6 NJR.

8) Ensure the method still logs + updates status, but it MUST treat the result as typed:
   - Instead of `result.get('output_path', ...)` at **line 298**, use `PipelineRunResult` fields.

### 5.4 Optional but allowed: update package exports to prevent accidental imports

**File:** `src/pipeline/__init__.py` (only if it re-exports `PipelineConfig`)

9) If `PipelineConfig` is exported from `src/pipeline/__init__.py`, remove that export and export only NJR-native symbols.



## 6. Tests (MANDATORY) + Exact Commands
Run exactly:

```cmd
python -m pytest -q tests/controller/test_app_controller_pipeline_bridge.py
python -m pytest -q tests/controller/test_core_run_path_v2.py
```

(If they fail due to missing builders, fix within this PR’s listed files only.)


## 7. Required Proof (MANDATORY)
- `git status --short` (before + after)
- `git diff` (full)
- `python -m pytest -q ...` commands above + full output
- Grep proof that AppController no longer calls `run_txt2img_once` on PipelineRunner:

```cmd
python -c "import pathlib; t=pathlib.Path('src/controller/app_controller.py').read_text(encoding='utf-8'); print('run_txt2img_once(' in t, 'pipeline_runner.run_txt2img_once' in t)"
```

Expected output: `True False` (method may still exist on controller, but must not call runner’s deleted method)


## 8. Rollback Plan
- Revert this PR commit(s).
- Confirm Golden Path tests still pass on main.

