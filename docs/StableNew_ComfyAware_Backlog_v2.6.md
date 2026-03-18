
# StableNew Comfy-Aware Migration Backlog v2.6

## Purpose
Complete migration to canonical architecture while preserving ComfyUI as a pluggable backend.

## Core Invariant
StableNew owns:
- Job model (NJR)
- Config
- Queue
- Runner
- Artifacts

Backends (Native SVD, ComfyUI) ONLY execute.

---

## Key Requirement (GLOBAL)

ALL PRs must preserve:
- backend-agnostic execution path
- no Comfy imports outside backend layer
- NJR as single source of truth

---

## PR-MIG-101 — Introduce VideoExecutionRequest + Backend Interface

### BLUF
Create canonical video execution contract before removing legacy paths.

### Tasks
- Create:
  - src/video/contracts/video_execution_request.py
  - src/video/contracts/video_execution_result.py
  - src/video/backends/base_backend.py

### Interface
class VideoBackend:
    def execute(request): pass

### Success
- Native SVD wrapped in backend

---

## PR-MIG-102 — Backend Registry

### BLUF
Introduce selection layer between service and execution.

### Tasks
- Create:
  src/video/backends/registry.py

- Implement:
  select_backend(request.backend)

### Backends
- svd_native
- (future) comfy_ltx

---

## PR-MIG-103 — Refactor SVD to backend

### BLUF
Move SVD execution behind backend interface.

### Tasks
- Wrap SVDRunner inside NativeSVDBackend
- Remove direct controller calls to SVD

---

## PR-MIG-104 — NJR extension for video

### BLUF
Ensure NJR supports backend + workflow selection.

### Add fields
- video_backend
- workflow_preset_id
- backend_options

---

## PR-MIG-105 — Config DTO split

### BLUF
Separate canonical vs backend config.

### Canonical
- prompt
- anchors
- frames
- output

### Backend
- svd params
- comfy workflow mapping

---

## PR-MIG-106 — Architecture Guard (Comfy Safe)

### Add Rules
- no comfy imports outside:
  src/video/backends/**
- GUI cannot import backend code

---

## PR-MIG-107 — Remove archive + finalize routing

### BLUF
Route ALL execution through:
Controller → Service → Backend → Runner

---

## PR-MIG-108 — Comfy Adapter Stub

### BLUF
Create empty backend placeholder.

### Add:
src/video/backends/comfy_backend.py

(no logic yet)

---

## Done Definition

- backend switch possible without UI change
- no Comfy leakage
- NJR drives all execution
