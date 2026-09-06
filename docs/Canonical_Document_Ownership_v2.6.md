# StableNew Canonical Document Ownership v2.6

Status: Authoritative
Updated: 2026-09-05

## 1. Ownership

| Document/surface | Tier | Owner | Update trigger |
|---|---:|---|---|
| `docs/ARCHITECTURE_v2.6.md` | 1 | Planner + Rob approval | Structural/runtime contract change |
| `docs/GOVERNANCE_v2.6.md` | 1 | Planner + Rob approval | Process, authority, or safety rule change |
| `docs/StableNew Roadmap v2.6.md` | 1 | Planner + Rob approval | MVP scope, priority, status, or ordering change |
| PromptPack lifecycle and builder deep-dive | 2 | Planner | Intent/compiler/PromptPack contract change |
| Coding/testing standards and golden paths | 2/3 | Planner + test reviewer | Verification or release-gate change |
| Debug/enforcement docs | 2 | Planner | Diagnostics/enforcement contract change |
| PR template | 2 | Planner | Planning/approval/closeout process change |
| Docs index and this ownership map | 2 | Planner | Active file, tier, status, or precedence change |
| `AGENTS.md`, Copilot brief, instruction manifest | 2 | Planner + Rob approval for rule changes | Agent rule or active instruction-surface change |
| Tier 3 subsystem references | 3 | Planner/domain reviewer | Subsystem behavior change |
| Approved PR specs | 4 | Planner; Rob approves | Work enters execution |

## 2. Precedence

1. Owner decisions recorded in an approved canonical amendment or PR spec.
2. Tier 1.
3. Tier 2.
4. Tier 3.
5. Approved Tier 4 PR spec for its bounded implementation details.
6. Research, completed, needs-review, and archive material as evidence only.

Within a tier, the more specific active document wins. If equally specific
active docs still conflict, stop affected implementation and synchronize them.

## 3. Truth-status rule

An active architecture may define a target that code has not reached only when
it labels that target, lists contrary current evidence in the architecture gap
register, and assigns a closing roadmap PR. The implementation remains
incomplete until tests and clean-checkout verification support removal of the
gap.

Working code and passing tests do not automatically become canon. Conversely,
canon must not claim current implementation that evidence disproves.

## 4. Required synchronization

No PR may knowingly leave active documents contradictory. At minimum:

- NJR/source changes update architecture, governance, builder/lifecycle,
  coding/testing, relevant golden paths, roadmap, and affected tests;
- repository changes update architecture, coding/testing, golden paths,
  migration/runbook material, and roadmap;
- PromptPack format changes update lifecycle, builder, tests, and migration docs;
- runner/backend scope changes update architecture, subsystem docs, tests, and
  roadmap;
- agent-rule changes update `AGENTS.md`, the Copilot brief, and the instruction
  manifest when its enumerated surface or precedence changes.

## 5. Disposition

- `docs/CompletedPR/`: one final record per completed PR.
- `docs/CompletedPlans/`: completed multi-PR sequences and retired roadmaps.
- `docs/NeedsReview/`: applicability uncertain; non-active.
- `docs/archive/`: superseded/history only.
- `docs/PR_Backlog/`: open specs/plans; only roadmap-listed, owner-approved specs
  are executable.

Closing a PR requires roadmap/index/gap updates and removal or relocation of its
backlog copy. Completion history does not remain an active planning surface.

## 6. Amendment record

`PR-ARCH-MVP-001` is the owner-approved September 2026 reconciliation. It
authorizes the v2.6 amendments that separate typed intent from NJR, immutable
work from mutable execution state, PromptPack source identity from other
sources, SQLite repository authority from legacy files, and native SVD MVP
scope from post-MVP video systems.
