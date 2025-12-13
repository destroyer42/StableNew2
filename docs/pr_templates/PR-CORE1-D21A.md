# PR-CORE1-D21A — Fix AppController init drift + wire watchdog/diagnostics (threaded) at app startup/shutdown

**Intent:** Restore v2.6 diagnostics correctness by fixing AppController init drift and starting SystemWatchdogV2 on its own thread with a real diagnostics service, stopped on shutdown.

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
You MUST implement **exactly** the changes listed in sections 2–6 below, in the exact files and line ranges. No additional refactors.

If any required line numbers do not match due to local drift, you MUST:
1) `git grep` the exact surrounding sentinel comment/string shown, and
2) report the new line numbers, and
3) continue with the change at the correct location.


---

## 0) PR Metadata
- **PR ID:** PR-CORE1-D21A
- **Title:** Fix AppController init drift + wire watchdog/diagnostics (threaded) at app startup/shutdown
- **Risk Tier:** Tier 2

---

## 1) Canonical Inputs (Attach These)
- ✅ `StableNew v2.6 – Canonical Execution Contract.md`
- ✅ Repo snapshot zip + `repo_inventory.json`
- ✅ This PR doc

---

## 2) Scope of Change (NO DEVIATION)
### Files to Modify (EXACT)
- `src/controller/app_controller.py`
- `src/app_factory.py`
- `src/services/watchdog_system_v2.py`
- **NEW:** `src/services/diagnostics_service_v2.py`

### Files NOT to Touch
- Any `tests/**` in this PR (tests are handled in PR-CORE1-D21C).

---

## 3) Line-Level Change Plan (EXECUTOR MUST FOLLOW EXACTLY)
### 3.1 Fix `AppController.__init__` indentation drift (CRITICAL)
**File:** `src/controller/app_controller.py`

At **lines ~347–389** in the snapshot, three methods are incorrectly nested inside `__init__` (they are indented under the constructor):
- `def update_ui_heartbeat(self) -> None:` (around **line 355**)
- `def notify_queue_activity(self) -> None:` (around **line 364**)
- `def notify_runner_activity(self) -> None:` (around **line 371**)

**Action (MANDATORY):**
- Move these three `def` blocks **out of** `__init__` to class scope (4-space indent).
- Ensure `__init__` continues executing after setting the heartbeat timestamps without being interrupted by nested defs.

**Sentinel proof (must exist in file):**
- The buggy region begins immediately after: `self._last_ui_heartbeat_ts = time.time()`
- The buggy region ends immediately before: `if pipeline_runner is not None:`

### 3.2 Add watchdog + diagnostics wiring into AppController
**File:** `src/controller/app_controller.py`

1) Add attributes initialized in `__init__` near the other timestamp fields (around **lines 345–353**):
- `self._diagnostics_service: DiagnosticsServiceV2 | None = None`
- `self._watchdog: SystemWatchdogV2 | None = None`

2) Add a class-scope method:
```python
def attach_watchdog(self, diagnostics_service: "DiagnosticsServiceV2") -> None:
    self._diagnostics_service = diagnostics_service
    if self._watchdog is None:
        self._watchdog = SystemWatchdogV2(self, diagnostics_service)
        self._watchdog.start()
```

3) In `shutdown_app` (around **lines 2145–2180**), stop the watchdog early:
```python
if self._watchdog is not None:
    self._watchdog.stop()
```

### 3.3 Implement a real DiagnosticsServiceV2
**File (NEW):** `src/services/diagnostics_service_v2.py`

Create a wrapper with this exact API:
- `__init__(self, output_dir: Path)`
- `build(self, *, reason: str, context: dict | None = None) -> Path`
  - MUST call `build_crash_bundle(output_dir=self.output_dir, reason=reason, context=context or {})`
  - MUST return the Path to the created zip

You MAY also implement `build_async`, but it is not required in this PR.

### 3.4 Wire watchdog startup in the app factory (V2 only)
**File:** `src/app_factory.py`

After:
- `window = MainWindowV2(...)` (around **line 62**)
- `app_controller.set_main_window(window)` (around **line 73**)

Add:
1) `diagnostics_service = DiagnosticsServiceV2(Path("reports") / "diagnostics")` (ensure dirs exist)
2) `app_controller.attach_watchdog(diagnostics_service)`

This MUST occur before `return window` (before **line 74**).

### 3.5 Ensure watchdog runs on its own thread
**File:** `src/services/watchdog_system_v2.py`

At `SystemWatchdogV2.start()` (around **lines 31–41**):
- Keep `daemon=True`
- Add `name="SystemWatchdogV2"` to the thread constructor.

---

## 4) Tests (MANDATORY — COMMANDS + CAPTURED OUTPUT)
Run exactly these commands and paste full output:

```cmd
pytest -q tests/controller/test_app_controller_shutdown_v2.py
pytest -q tests/gui_v2/test_main_window_smoke_v2.py
```

---

## 5) Forbidden Symbols / Paths (MANDATORY PROOF)
Run and paste output:

```cmd
git grep -n "def update_ui_heartbeat" src/controller/app_controller.py
git grep -n "def notify_queue_activity" src/controller/app_controller.py
git grep -n "def notify_runner_activity" src/controller/app_controller.py
```

---

## 6) Acceptance Criteria (MUST)
- AppController initializes fully (tests no longer claim missing `pipeline_controller`, `job_service`, `_is_shutting_down`).
- Watchdog starts during `build_v2_app()` and does not block UI.
- Watchdog stops during `shutdown_app()` without exceptions.

---

## 7) Completion Proof Bundle (MUST INCLUDE IN RESPONSE)
1. `git diff` (full)
2. `git status --short`
3. All pytest outputs above
4. Grep outputs above
