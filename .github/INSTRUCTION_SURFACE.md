INSTRUCTION_SURFACE.md
Active Machine-Facing Guidance Manifest for StableNew v2.6

Status: Authoritative
Updated: 2026-03-12

---

## 1. Purpose

This manifest enumerates every file that carries machine-facing instructions for
GitHub Copilot, Codex, or other automated agents operating in this repo. It
defines the precedence order, marks which files are active vs. archived, and
prevents duplication of guidance.

---

## 2. Active Instruction Surface (in precedence order)

### 2.1 Primary Executor Brief

| File | Scope | Purpose |
|---|---|---|
| `.github/copilot-instructions.md` | All sessions | Root executor brief; references AGENTS.md and canonical docs |
| `AGENTS.md` | All sessions | Role boundaries, workflow, and forbidden/allowed behaviors |

These two files together constitute the top-level active instruction surface.
Any guidance in AGENTS.md that is repeated verbatim in copilot-instructions.md
should be removed from copilot-instructions.md and referenced by pointer instead.

### 2.2 Agent Mode Profiles

| File | Agent Mode | Purpose |
|---|---|---|
| `.github/agents/controller_lead_engineer.md` | controller_lead_engineer | Planner/orchestrator mode |
| `.github/agents/implementer.md` | implementer | Code execution mode |
| `.github/agents/gui.md` | gui | GUI execution mode |
| `.github/agents/pipeline_runtime.md` | pipeline_runtime | Pipeline/runtime execution |
| `.github/agents/refactor.md` | refactor | Refactoring work |
| `.github/agents/tester.md` | tester | Test writing/validation |
| `.github/agents/docs.md` | docs | Documentation work |

### 2.3 Path-Scoped Instructions

| File | Applies To | Purpose |
|---|---|---|
| `.github/instructions/archive.instructions.md` | `archive/` areas | Rules for archive work |
| `.github/instructions/controller.instructions.md` | `src/controller/` | Controller rules |
| `.github/instructions/docs.instructions.md` | `docs/` | Documentation rules |
| `.github/instructions/gui.instructions.md` | `src/gui*/` | GUI rules |
| `.github/instructions/learning.instructions.md` | `src/learning/` | Learning rules |
| `.github/instructions/pipeline.instructions.md` | `src/pipeline/` | Pipeline rules |
| `.github/instructions/randomizer.instructions.md` | `src/randomizer/` | Randomizer rules |
| `.github/instructions/tests.instructions.md` | `tests/` | Test rules |
| `.github/instructions/tools.instructions.md` | Agent tooling | Tool use rules |
| `.github/instructions/utils.instructions.md` | `src/utils/` | Utilities rules |

---

## 3. Precedence Order

When two active files give conflicting guidance, the following order applies:

1. `.github/copilot-instructions.md` (executor brief)
2. `AGENTS.md` (role/process rules)
3. Canonical docs (Tier 1 > Tier 2 per DOCS_INDEX_v2.6.md)
4. Agent mode profile (`.github/agents/*.md`)
5. Path-scoped instructions (`.github/instructions/*.instructions.md`)

A path-scoped instruction file may add constraints but must not contradict
the executor brief or canonical docs.

---

## 4. Archived Files (reference only — must not be used for new work)

All files under `archive/`, `docs/archive/`, or any legacy SOP folders are
reference-only. They must not be invoked as active guidance.

---

## 5. Rules for Updating This Manifest

- If a new `.github/agents/*.md` file is created, add it to §2.2 in the same PR.
- If a new `.github/instructions/*.instructions.md` file is created, add it to
  §2.3 in the same PR.
- If a guidance file is deprecated or archived, remove it from §2 and note it
  in §4 in the same PR.
- This file and `AGENTS.md` must both be updated when the instruction surface
  changes.

---

**Document Status**: ✅ CANONICAL
**Last Updated**: 2026-03-12
