# PR-CORE1-D21C — Force diagnostics zip emission on watchdog violations + make watchdog tests deterministic

**Intent:** Guarantee diagnostics zips are created on watchdog violations and make watchdog tests deterministic by avoiding async bundle races.

---

## CODEX EXECUTOR PROMPT (PASTE THIS WHOLE BLOCK INTO CODEX)

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

### EXECUTION SCOPE (THIS PR ONLY)
This PR is about diagnostics emission + deterministic watchdog tests only. Do NOT refactor pipeline execution.


---

## 0) PR Metadata
- **PR ID:** PR-CORE1-D21C
- **Title:** Force diagnostics zip emission on watchdog violations + make watchdog tests deterministic
- **Risk Tier:** Tier 1–2

---

## 1) Canonical Inputs (Attach These)
- ✅ `StableNew v2.6 – Canonical Execution Contract.md`
- ✅ Repo snapshot zip + `repo_inventory.json`
- ✅ This PR doc

---

## 2) Scope of Change (NO DEVIATION)
### Files to Modify (EXACT)
- `src/services/watchdog_system_v2.py`
- `src/services/diagnostics_service_v2.py`
- `tests/system/test_watchdog_ui_stall.py`

---

## 3) Line-Level Change Plan (EXECUTOR MUST FOLLOW EXACTLY)
### 3.1 Make watchdog emit bundles synchronously (on watchdog thread)
**File:** `src/services/watchdog_system_v2.py`

At `_emit_violation()` (around **lines 62–70**):
- Replace:
  - `self._diag.build_async(reason=reason)`
- With:
  - `self._diag.build(reason=reason, context={...})`

The `context` dict MUST include:
- `ui_heartbeat_age_s`
- `queue_activity_age_s`
- `runner_activity_age_s`
- `queue_state` (the full dict returned by `app.get_queue_state()`)

### 3.2 Ensure DiagnosticsServiceV2.build() creates a zip in the requested output dir
**File:** `src/services/diagnostics_service_v2.py`
- `build()` MUST return the created zip Path.
- `build()` MUST be synchronous.

### 3.3 Fix watchdog tests to use real DiagnosticsServiceV2 (no dummy service)
**File:** `tests/system/test_watchdog_ui_stall.py`

In both tests:
- Replace `DummyDiagnosticsService` with:
  - `from src.services.diagnostics_service_v2 import DiagnosticsServiceV2`
  - `diag = DiagnosticsServiceV2(bundle_dir)`
- Keep the `diag.triggered` list behavior by asserting on filesystem (zip exists) rather than dummy state.

Update assertions:
- Keep zip glob assertion.
- Replace `assert any("ui_heartbeat_stall" in r for r in diag.triggered)` with:
  - Assert at least one zip exists AND (optional) verify the latest zip filename contains the reason substring if your builder encodes it; otherwise omit that check.

---

## 4) Tests (MANDATORY — COMMANDS + CAPTURED OUTPUT)
Run and paste:

```cmd
pytest -q tests/system/test_watchdog_ui_stall.py
```

---

## 5) Forbidden Symbols / Paths (MANDATORY PROOF)
Run and paste:

```cmd
git diff
git status --short
```

---

## 6) Acceptance Criteria (MUST)
- Watchdog-triggered diagnostics always emit a `stablenew_diagnostics_*.zip`.
- `tests/system/test_watchdog_ui_stall.py` passes reliably without sleeping for async bundle races.

---

## 7) Completion Proof Bundle (MUST INCLUDE IN RESPONSE)
1. `git diff` (full)
2. `git status --short`
3. All pytest outputs above
4. Grep outputs above
