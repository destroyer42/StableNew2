# UX-850-D — cross-workflow state, persistence, recovery and lifecycle

**Architectural RESEARCH / PROPOSED extensions.** The existing NJR → JobService → SQLite queue/repository → `PipelineRunner.run_njr` spine can support the experience directions without a competing execution authority. Reuse it. Keep editable intent, immutable authorized snapshots, authoritative job lifecycle and GUI projections separate. Proposed metadata below has **no production approval**; merging this research adopts no schema, policy, store, scheduler or behavior.

The consequential gaps are scoped draft recovery and locks, campaign authorization/continuation, Library disposition/import trust, and evaluator applicability. They are future decision gates, not new job states. No verified new acute threat was established by the bounded static work; this is not a safety clearance or a complete persistence/security audit.

## Review route and complete artifact inventory

| Artifact | Question answered |
|---|---|
| [Ownership and persistence](OWNERSHIP_PERSISTENCE.md) | Who writes each state class, where is the boundary, and what is only proposed? |
| [Lifecycle diagrams](LIFECYCLES.md) | What transitions already exist in high-risk workflows, and where would proposed intent stop? |
| [Draft and submission contracts](DRAFT_SUBMISSION_CONTRACTS.md) | What becomes frozen, what invalidates approval, and what can recovery replace? |
| [Restart, replay and failure matrix](RECOVERY_FAILURE_MATRIX.md) | How do duplicate, partial, stale, missing and ambiguous cases reconcile? |
| [Migration and compatibility](MIGRATION_COMPATIBILITY.md) | Which future changes need explicit compatibility, migration and rollback decisions? |
| [Extension seams and owner gates](EXTENSION_SEAMS_GATES.md) | Where can later work fit without taking runtime ownership? |
| [Method-diverse challenge](CHALLENGE.md) | What survived a separate assertion/wiring/counterexample method? |
| [Source index](SOURCE_INDEX.md) | Which exact source identities and existing negative tests support the report? |
| [Evidence and validation](EVIDENCE_AND_VALIDATION.md) | What was checked, what was reused, and what remains unverified? |

These ten Markdown files, including this entry point, are the complete maintained D package. Helper code, identities/assertion manifests, check logs and the filled PR body/ready capsule remain outside Git in the author's session artifact directory.

## Execution Profile + Model/Reasoning Recommendation

- **Class / location:** Architectural research only, Local/Desktop; one fresh top-level Codex session, no subagents or independent reviewer claimed.
- **Start before discovery:** `2026-11-08T06:41:08.9487872-05:00`, America/New_York; sole participant `codex:01a1baf6-29d0-7f01-aa17-1f58c240ca16`.
- **Actual executor:** Codex Desktop, `gpt-6.1-sol`, `xhigh`, confirmed by logged turn metadata. Exact measured usage belongs in the external PR body and capsule; expected usage is not actual usage or a budget.
- **Model recommendation:** Codex GPT-6.1 Sol XHigh / Claude Code Sonnet 5.5 XHigh, per [model selection authority](../../../AI_MODEL_SELECTION.md). This bounded lifecycle/persistence analysis reuses accepted inventories; one strong shared context and a distinct-method challenge should minimize total successful-work cost, including rediscovery and retries. No host switch or delegation has a material benefit. Expected about **8M cache-read / 55k output** tokens, a planning assumption.
- **Controller Surface Assessment:** source/test/controller/coordinator changes: **none**. Inspected `AppController`, `PipelineController`, `JobExecutionController`, `JobService`, Learning and sequence adapters only to establish ownership. Future extensions belong behind existing cohesive services and view contracts. No new runtime coordinator, ratchet increase, persistence/lifecycle duplication or backend policy is adopted. Existing ceilings remain 6,816 / 1,697 / 1,227 / 647 lines for the four ratcheted controllers, with the 600-line new-controller limit.
- **Token-Efficient Validation Plan:** reuse A/B/C identities and all 84 unchanged A anchors; inspect only persistence/recovery-sensitive source; challenge with existing test assertions and production composition; check links, source identities, diagram structure/semantics and all requested state surfaces; run the three cheap documentation policy checks, classification, PR-evidence advisory and aggregate `git diff --check`. No application tests, full local gate, GUI, GPU, backend or physical suites rerun.

## Exact baseline and accepted inputs

| Input | Identity and use |
|---|---|
| D base / local and live remote main at start | `d05d4a2d769d7076c902b3b3a63d626fea192112`; origin `https://github.com/destroyer42/StableNew2.git` |
| Worktree / branch | `C:/Users/rob/qual/StableNew-ux850d` / `research/ux850-d-state-lifecycle`, fresh and isolated |
| A / PR #263 | head `5e081494fac33d96b47fde836a42a9a344c17ce0`, merge `f51aa870824a0804202c438531f4f1c9e0bc231c`; evidence cut `8e1ee82b5fd8cc18437274e86e9af4f59938a799` |
| B / PR #264 | head `6c909dc144c786e9a7361928318b49916e273ddb`, merge `f39d748fc2508a69a59e194ac9dcd8f690fed976`; five journeys J1–J5, H1–H10 handoffs, N1 recommendation |
| C / PR #265 | head `53125db88e194d5ec7d0deb991d1ef04863bc93c`, merge equal to D base; presentation specs/static wireframes only |
| Complete owner register | [73 confirmed decisions 001–071 plus 005A/007A](../ux-850-r1/OWNER_DECISIONS.md); **072 pending**. A's abridged predecessor input is not the full source |

Git comparison confirms no changes under `src`, `tests`, `config`, `presets`, requirements or `pyproject.toml` between A's evidence cut and D's base. All 84 accepted A source blobs match. Reuse [A ownership](../ux850-a/OWNERSHIP_BOUNDARY_MAP.md), [A F1–F8](../ux850-a/GAPS_RISKS_UNKNOWNS.md), [B handoffs](../ux850-b/HANDOFFS.md), [B interaction scopes](../ux850-b/INTERACTION_SEMANTICS.md) and [C future acceptance](../ux850-c/ACCEPTANCE.md) within their original limits. A remains **partial Comprehensive**. C supplies no actual Tk/DPI/operator proof.

Shared `C:/Users/rob/projects/StableNew-main` remains on the supplied base with its pre-existing modified `presets/settings.json`, SHA-256 `818257bab7d1e3972d188c7cfe85ce34ae05967b98d85bcc965be2808bc7047d`. No stage, stash, reset, rewrite, application restart or user-data action is part of D.

## Authority and disposition

Current AGENTS/STATUS, task/code maps, architecture, operating/model/work-package guidance, assessment v1.2 and living Runtime/Testing/Learning/Profile/Video/PromptPack/Review authorities govern. The older SVD-only architecture sentence and historical physical-hold wording in the owner register do not override current AGENTS/STATUS or the approved workflow catalog. This package authorizes no physical work regardless of those historical statements.

Only this research directory changes. Canonical behavior/qualification truth is unchanged, so no STATUS, roadmap, architecture authority or code-map narration is added. The final commit, complete diff, validation and usage records live in the external ready capsule. **Hosted CI, publication and merge: PENDING coordinator.** D authoring stops at that capsule. E begins only in a fresh session after the coordinator accepts/merges D.
