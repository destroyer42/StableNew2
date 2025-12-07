# StableNew Development Doctrine
StableNew_Development_Doctrine.md
# StableNew Development Doctrine
*The Core Rules for StableNew’s Architecture, Process, and AI-Augmented Development*

---

## 1. Mission & Philosophy

StableNew is a modular creative engine designed for deterministic pipelines, intelligent defaults, and reliable automation across images, video, and distributed compute nodes.

The purpose of this doctrine is to ensure StableNew evolves through **modular, atomic, reversible improvements** validated with snapshot diffs and strict subsystem boundaries.

This is the antidote to:
- vibe coding  
- runaway refactors  
- legacy contamination  
- fragile hacks  
- ambiguity  
- accidental regressions  

---

# 2. Architectural North Star

StableNew follows a **4-layer architecture**, intentionally stable and easy to test.

---

## Layer 1 — GUI (V2 only)
- Pure presentation  
- Zero pipeline logic  
- Zero WebUI logic  
- Zero I/O  
- Talks ONLY to controller  
- Uses declarative zones: `header`, `left`, `center`, `bottom`  
- Every widget has 1 parent and 1 responsibility  

---

## Layer 2 — Controller  
- The **brain** of the system  
- Owns orchestration, validation, and glue  
- Updates config → runs stages → emits events  
- No Tkinter imports  
- No payload building  
- Must expose:
  - `list_models()`, `list_vaes()`, `list_samplers()`, etc.
  - `update_*` methods for config
  - `run_txt2img()`, `run_img2img()`, `run_upscale()`  

---

## Layer 3 — Pipeline Runtime  
- Transforms config into WebUI payload  
- Handles stage sequences  
- Emits structured learning records  
- No GUI or controller references  

---

## Layer 4 — API Layer  
- WebUI healthcheck  
- WebUI client  
- Resource discovery  
- Filesystem fallback  
- No business logic  

---

# 3. Subsystem Contracts (Non-Negotiable)

These contracts define the shape of the system.  
Any PR that breaks them = rejected.

---

## GUI Contract
- Uses controller exclusively  
- Dropdowns populated by resource service  
- No direct payload manipulation  
- StageCards conform to a standard API  
- Supports last-run config preloading  

---

## Controller Contract
- Only one `AppController`  
- Must attach to MainWindowV2 *after* zones exist  
- Exposes config update methods  
- Never holds GUI widgets inside itself  
- Owns resource lists and last-run config  

---

## Pipeline Contract
- Config is a dataclass  
- Output written to manifest + learning store  
- No hardcoded paths or model names  
- Payloads logged pre-flight  

---

## API Contract
- Unified healthcheck  
- Retry logic wrapped  
- Supports offline and filesystem-only mode  
- No UI imports  

---

# 4. Rules for AI-Assisted Development

---

## Rule A — Snapshot Before PR
No PR may begin until:
- Snapshot ZIP created  
- repo_inventory.json generated  
- Snapshot name added to PR header  

---

## Rule B — One PR = One File (or tiny cluster)
LLMs may only touch explicit files.

---

## Rule C — No Architecture Changes Without Proposal
If AI wants to:
- add classes  
- restructure modules  
- move files  
It must submit a design proposal first.

---

## Rule D — AI Must Read the File Before Editing
Never guess.  
Always request and read the file.

---

## Rule E — Explicit Approval Required for Core Files  
The following require override:
- executor.py  
- main_window_v2.py  
- theme_v2.py  
- main.py  
- pipeline_runner.py  
- anything under `/src/api/`  

---

## Rule F — Minimal Diff Always
- No whitespace churn  
- No drive-by refactors  
- Smallest possible change  
- Preserve indentation & formatting  

---

## Rule G — Tests Are the Oracle  
If a test breaks:
- Stop  
- Investigate  
- Fix by contract  

Never comment out a failing test.

---

# 5. Regression Prevention Systems

---

## 1. Snapshot System  
Before/after ZIPs are the ground truth.

## 2. Repo Inventory System  
Ensures file names & paths never drift.

## 3. File Lock List  
Prevents accidental modification of core modules.

## 4. Contract Tests  
Detect divergence of subsystem API/behavior.

## 5. PR Template Enforcement  
Anchor PRs to small scopes.

## 6. Unified Event Logging  
Every critical action logged—makes debugging trivial.

---

# 6. V2/V1 Boundary Rules

- No legacy imports  
- No V1 helpers  
- No V1 pipelines  
- No mixing of legacy StageCards  
- All V1 code stored in `/archive/*`  

---

# 7. Code Style & Structure Rules

- Use dataclasses  
- Avoid global mutable state  
- No widget creation in controller  
- No hardcoded paths  
- Payloads must be fully logged  
- Each file starts with a docstring  
- Async work must be cancellable  

---

# 8. Long-Term Vision Rules

- Video as a stage, not a separate pipeline  
- Randomization engine must be modular  
- Learning system uses JSONL  
- Distributed execution uses event bus + workers  

---

# 9. Decision-Making Hierarchy

AI proposes → Human approves → AI implements → Human validates

---

# 10. End State

This doctrine transforms StableNew into a system that is:

- robust  
- scalable  
- modular  
- future-proof  
- easy to maintain  
- impossible to accidentally break  

The result is a production-grade creative engine that grows intelligently over time.