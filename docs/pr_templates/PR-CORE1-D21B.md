# PR-CORE1-D21B — Wire UI/queue/runner activity heartbeats for stall detection

**Intent:** Ensure watchdog stall detection uses real activity signals by wiring queue and runner events to AppController timestamps.

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
Implement only the activity/heartbeat wiring described below. Do NOT change watchdog thresholds or diagnostics packaging in this PR.


---

## 0) PR Metadata
- **PR ID:** PR-CORE1-D21B
- **Title:** Wire UI/queue/runner activity heartbeats for stall detection
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
- `src/controller/job_service.py`
- `src/queue/single_node_runner.py`

### Files NOT to Touch
- No GUI widget/layout changes.
- No tests in this PR (tests are in PR-CORE1-D21C).

---

## 3) Line-Level Change Plan (EXECUTOR MUST FOLLOW EXACTLY)
### 3.1 Record queue activity on enqueue
**File:** `src/controller/job_service.py`

At `enqueue()` (around **lines 254–313**):
- Add `self._on_queue_activity` + `self._on_runner_activity` optional callbacks stored on JobService.
- Add method:
```python
def set_activity_hooks(self, *, on_queue_activity=None, on_runner_activity=None) -> None:
    self._on_queue_activity = on_queue_activity
    self._on_runner_activity = on_runner_activity
```

- Immediately after `self._queue.submit(job)` (around **line 298**), call:
```python
if self._on_queue_activity:
    self._on_queue_activity()
```

### 3.2 Record runner activity on dequeue/execute and status change
**File:** `src/queue/single_node_runner.py`

1) Add optional callback `self._on_activity` (constructor param `on_activity=None` stored on self)
2) In `run_once()` call `self._on_activity()` at:
- right after dequeue (after `job = self.queue.get_next()` around **line 70**)
- right before `_run_job(job)` (around **line 77**)
- right after `_run_job(job)` returns or in `except:` before re-raising (around **lines 82–89**)

**File:** `src/controller/job_service.py`
At `_handle_job_status_change()` (around **lines 198–228**):
- After updating status and notifying callbacks, call:
```python
if self._on_runner_activity:
    self._on_runner_activity()
```

### 3.3 Wire hooks from AppController after PipelineController exists
**File:** `src/controller/app_controller.py`

After `self.pipeline_controller = PipelineController(...)` is assigned (currently around **lines 433–451**, immediately before `# Attach GUI log handler`):
- Add:
```python
self.pipeline_controller.job_service.set_activity_hooks(
    on_queue_activity=self.notify_queue_activity,
    on_runner_activity=self.notify_runner_activity,
)
```

If the attribute name differs, you MUST use the actual JobService instance on PipelineController (no new wrappers).

---

## 4) Tests (MANDATORY — COMMANDS + CAPTURED OUTPUT)
Run and paste:

```cmd
pytest -q tests/controller/test_job_queue_integration_v2.py
```

---

## 5) Forbidden Symbols / Paths (MANDATORY PROOF)
Run and paste:

```cmd
git grep -n "set_activity_hooks" src/controller/job_service.py
git grep -n "on_queue_activity" src/controller/job_service.py
git grep -n "on_runner_activity" src/controller/job_service.py
```

---

## 6) Acceptance Criteria (MUST)
- Enqueueing a job updates `AppController.last_queue_activity_ts` through the hook.
- Runner dequeue/execute + any status change updates `AppController.last_runner_activity_ts` through the hook.

---

## 7) Completion Proof Bundle (MUST INCLUDE IN RESPONSE)
1. `git diff` (full)
2. `git status --short`
3. All pytest outputs above
4. Grep outputs above
