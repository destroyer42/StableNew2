
# StableNew Architecture v2.6

## CURRENT STATE (Observed)

### Strengths
- NJR pipeline exists
- SVD uses queue + job service
- artifacts + manifests exist

### Weaknesses
- archive remnants still referenced
- controller too coupled to SVD
- config not fully unified
- no backend abstraction
- architecture guard allows legacy

---

## TARGET ARCHITECTURE

### Core Flow

PromptPack → NJR → Queue → Runner → Artifacts

---

## VIDEO EXECUTION MODEL

Controller
→ VideoJobService
→ VideoExecutionRequest
→ BackendRegistry
→ SelectedBackend
→ Execution
→ Result → Artifacts

---

## BACKEND MODEL

StableNew:
- owns intent
- owns config
- owns history

Backend:
- executes only

---

## BACKENDS

### Native
- SVDRunner

### Comfy
- Workflow execution
- node graph
- polling

---

## RULES

1. No backend imports outside backend layer
2. No UI knowledge of workflows
3. No direct execution outside runner
4. NJR required for all jobs

---

## CONFIG LAYERS

### Canonical
- user intent

### Backend
- execution details

---

## FAILURE MODEL

StableNew handles:
- validation
- retry
- replay

Backend handles:
- execution only

---

## FUTURE STATE

- multiple backends
- workflow registry
- replay across backends
- deterministic runs

---

## SUMMARY

StableNew = orchestrator
Backends = execution engines
