# Active Machine-Facing Guidance Manifest — StableNew v2.6

Status: Authoritative
Updated: 2026-09-05

## 1. Purpose

This manifest enumerates active instruction files for automated contributors.
It prevents archived or duplicate guidance from becoming accidental authority.

## 2. Active instruction surface

### 2.1 Repository-wide guidance

| File | Scope | Purpose |
|---|---|---|
| `AGENTS.md` | All sessions | Primary repository roles, workflow, boundaries, and architecture summary |
| `.github/copilot-instructions.md` | All sessions | Concise executor brief pointing to canon |

### 2.2 Agent mode profiles

| File | Mode | Purpose |
|---|---|---|
| `.github/agents/controller_lead_engineer.md` | controller lead | Planning/orchestration |
| `.github/agents/implementer.md` | implementer | Approved code execution |
| `.github/agents/gui.md` | GUI | GUI implementation |
| `.github/agents/pipeline_runtime.md` | pipeline runtime | Pipeline/runtime implementation |
| `.github/agents/refactor.md` | refactor | Approved refactoring |
| `.github/agents/tester.md` | tester | Test implementation/validation |
| `.github/agents/docs.md` | docs | Documentation work |

### 2.3 Path-scoped instructions

| File | Applies to | Purpose |
|---|---|---|
| `.github/instructions/archive.instructions.md` | archive areas | Archive rules |
| `.github/instructions/controller.instructions.md` | `src/controller/` | Controller rules |
| `.github/instructions/docs.instructions.md` | `docs/` | Documentation rules |
| `.github/instructions/gui.instructions.md` | `src/gui*/` | GUI rules |
| `.github/instructions/learning.instructions.md` | `src/learning/` | Learning rules |
| `.github/instructions/pipeline.instructions.md` | `src/pipeline/` | Pipeline rules |
| `.github/instructions/randomizer.instructions.md` | `src/randomizer/` | Randomizer rules |
| `.github/instructions/tests.instructions.md` | `tests/` | Test rules |
| `.github/instructions/tools.instructions.md` | agent tooling | Tool-use rules |
| `.github/instructions/utils.instructions.md` | `src/utils/` | Utility rules |

## 3. Precedence

For repository work, use:

1. `AGENTS.md` and explicit owner-approved records;
2. Tier 1 and Tier 2 canon from `docs/DOCS_INDEX_v2.6.md`;
3. `.github/copilot-instructions.md` as an operational summary;
4. the selected agent profile;
5. matching path-scoped instructions.

Lower levels may add constraints but may not contradict higher levels. If an
active conflict remains, stop affected implementation and resolve it through a
synchronized documentation amendment.

## 4. Non-active guidance

Files under `archive/`, `docs/archive/`, `docs/CompletedPR/`,
`docs/CompletedPlans/`, and `docs/NeedsReview/` are reference/history only.
Unlisted material in `docs/PR_Backlog/` is not an instruction until the active
roadmap admits it and the owner approves its spec.

## 5. Maintenance

- Register a new `.github/agents/*.md` profile here in the PR that creates it.
- Register a new `.github/instructions/*.instructions.md` file here in the PR
  that creates it.
- Remove deprecated guidance from the active tables in the same PR that archives
  it.
- Update this file and `AGENTS.md` together when the enumerated instruction
  surface or precedence changes.
