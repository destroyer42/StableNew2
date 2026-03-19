# PR TEMPLATE — v2.7-X (Executor‑Enforced Edition)

---

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

