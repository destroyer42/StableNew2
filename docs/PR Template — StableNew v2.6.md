PR Template — StableNew v2.6.md
 (Canonical)

This template MUST be used for all PRs.
No PR may be merged unless every section is completed.

PR-### – Title (Short, Declarative)

Author:
Date:
Subsystem(s):
Risk Tier: (Tier 1 — GUI, Tier 2 — Controllers, Tier 3 — Pipeline/Queue/Runner)
Dependencies: (If referencing a CORE PR or Architecture version bump, list it here.)
Architecture Version: v2.6

1. Purpose / Intent (Required)

Explain why this PR exists in 3–6 sentences.

What problem does it solve?

What behavior or capability does it restore or enable?

How does it align with the v2.6 architecture invariants?

2. Summary of Changes (High-Level)

List the major outcomes of this PR:

What is being created?

What is being removed?

What is being replaced or rewritten?

What invariants or constraints does this PR introduce?

Use bullets, not paragraphs.

3. Architectural Alignment (Mandatory)

Every PR must answer the following:

3.1 PromptPack-Only Compliance

Does this PR maintain the rule that all jobs originate from Prompt Packs?

Does this PR remove or touch any GUI prompt field? (If yes → must be deleted, not patched.)

3.2 Single Canonical Pipeline Path Compliance

Every PR must preserve:

PromptPack → ConfigMergerV2 → RandomizerEngineV2 → UnifiedResolvers → JobBuilderV2 → NormalizedJobRecord →
Queue → Runner → Outputs → History → Learning


List where this PR fits in that chain.

List any obsolete paths this PR removes.

3.3 Ownership Boundaries

Affirm you are respecting v2.6 ownership boundaries:

Domain	Owner	Notes
Prompt text	Pack TXT	Immutable inside pipeline
Matrix values	Pack JSON	Managed by PromptPack editor only
Global negative	App Settings	Never written into pack JSON
Sweeps	Pipeline Tab only	Must not mutate PromptPack
NJR	Builder pipeline	Immutable
3.4 No Partial Migrations / No Shims

State clearly:

Does this PR complete a migration?

Does it delete all related legacy paths?

4. Change Specification (Exact Engineering Work)

This is the most important section for Codex.
It must be explicit, detailed, and mechanically actionable.

For each subsystem touched:

4.X File: src/.../...py

Add:

Modify:

Delete:

Refactor:

For each function or class, specify:

New signature (if changed)

Expected inputs/outputs

New invariants

Removal of deprecated code

How this aligns with architectures v2.6

Codex follows whatever is written here exactly.

5. Allowed Files / Forbidden Files (Mandatory)
Allowed Files to Modify

(List exact paths; Codex may ONLY modify these.)

Forbidden Files

Codex must not modify these unless explicitly authorized:

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/main.py

src/pipeline/executor.py

Any pipeline runner core

Any healthcheck core

Any file not explicitly listed in Allowed Files

6. Tech Debt Evaluation (MANDATORY)
6.1 Tech Debt Removed in This PR

List every instance of debt removed, including:

Legacy paths

Duplicate logic

Unused functions

Part-migrated structures

Old DTOs

Deprecated state managers

Shims, adapters, compatibility bridges

6.2 Tech Debt Introduced (Should Be Zero)

If ANY tech debt is introduced, list it here AND:

6.3 Immediate Remediation (Required)

You must fix the introduced tech debt in this same PR.
No deferrals allowed.

If something breaks, fix everything it impacted so the architecture stays coherent.

7. Tests (Required)
7.1 New Tests

List each new test added, and its purpose.

Tests must follow:

Golden Path rules

PromptPack-only architecture

NJR-only execution model

Deterministic builder pipeline

7.2 Updated Tests

List any tests updated due to architectural changes.

7.3 Test Coverage Expectations

State what behaviors must be covered (builders, queue, resolvers, etc.).

8. Documentation Updates (Required)

This PR must update ANY document affected by its changes:

ARCHITECTURE_v2.6.md

PROMPT_PACK_LIFECYCLE_v2.6.md

Builder Pipeline Deep-Dive (v2.6).md

Roadmap_v2.6.md

Coding_and_Testing_v2.6.md

new subsystem docs if required

For each doc updated, list:

File: /docs/...
Sections Modified:
Summary of Changes:

9. Acceptance Criteria

Every PR must define clear pass/fail criteria.

Example:

Builder pipeline produces correct NJRs

Queue receives only NJRs

UI shows correct previews

No legacy functions remain in the touched files

Tests pass and cover required scenarios

Documentation updated and consistent

10. Migration & Rollback Plan
10.1 Migration Steps

Describe sequential deployment steps

Any one-time conversions

Data/state impacts

10.2 Rollback Plan

Define how to revert if needed:

What files must revert?

What functionality is impacted?

11. Risks & Mitigations (Mandatory)

List risks:

Architectural divergence

Loss of determinism

Breakage in Queue/Runner contract

Legacy code reactivated

UI states not aligned with PromptPack-only rules

And planned mitigations.

✔️ END OF PR TEMPLATE v2.6 — CANONICAL