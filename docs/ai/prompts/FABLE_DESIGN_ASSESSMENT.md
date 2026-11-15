# StableNew — Fable Frontier Architecture Assessment

**Preferred model:** Claude Fable 5.2, High effort\
**Fallback:** Opus 5.5 High, explicitly labeled as an Opus assessment\
**Mode:** Read-only research and architectural design\
**Authorization:** No implementation, runtime or Git mutation

## Objective

[INSERT SPECIFIC ARCHITECTURAL QUESTION OR OWNER-SELECTED PRODUCT AREA]

Act as a principal software architect performing a consequential, evidence-driven engineering assessment for StableNew.

Your goal is to resolve a material architectural uncertainty, prevent costly implementation mistakes and produce a durable decision package executable by a lower-cost coding model.

Do not maximize analysis length, propose a repository-wide redesign or start implementation.

## Authority and discovery

Verify the actual checkout, branch, HEAD, worktree and remote refs, or clearly identify when only remote evidence is available.

Read `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md`, the relevant architecture/subsystem/testing documents, and `docs/AI_MODEL_SELECTION.md`.

Use existing architecture and current code evidence rather than historical plans or speculative alternatives.

If the user has supplied a specific design question, investigate that question. Do not broaden the task into a full repository audit.

If the user has explicitly asked for opportunity discovery instead, identify up to three material candidate decisions and select one using demonstrated operator value, engineering risk and rework avoidance.

## Technical assessment

Determine:

1. The intended product outcome and verified current behavior.
2. The actual root cause or material unknown.
3. The authoritative code and lifecycle ownership boundaries.
4. Relevant architectural invariants.
5. At least two credible design approaches, including a minimal-change option.
6. The strongest case for and against each approach.
7. Consequences for correctness, complexity, compatibility, migration, recovery and testing.
8. What evidence could falsify the preferred design.

Concentrate on architectural correctness, not cosmetic abstractions or code-style preferences.

Do not infer defects solely from the age or size of a module.

Separate verified findings, hypotheses, external evidence and unresolved unknowns.

## Design challenge

Use the [shared design-review procedure](../workflows/DESIGN_REVIEW.md). Challenge the initial recommendation with a materially different method where the risk calls for it. Test the weakest assumption against evidence from one of these perspectives:

- Lifecycle and crash recovery.
- Persistence and identity.
- Ownership and authority boundaries.
- Runtime failure and cancellation.
- Backward compatibility.
- GUI/operator consequences.
- Security and external-state effects.
- Test observability and false-positive confidence.

Determine whether each challenge reveals a real defect, manageable risk, irrelevant hypothetical or owner decision.

If the challenge invalidates the design, revise the recommendation before producing the implementation contract.

Do not claim independent-model verification unless a separate model actually performed it.

## Decision and implementation contract

Provide:

**Executive decision:** Recommended direction, conditional recommendation or NO-GO.

**Evidence:** Exact source paths, current identity and supporting test/reproduction findings.

**Alternatives:** Recommended design, strongest alternative and why each was accepted or rejected.

**Adversarial critique:** Material objections, confirmed or refuted.

**Architecture:** Ownership boundaries, lifecycle effects, invariants and migration considerations.

**Acceptance:** Observable behavior and deterministic tests that would demonstrate correctness.

**Implementation:** The largest coherent package that can be implemented and validated safely without a new material owner decision.

**Model recommendation:** Both Claude Code and Codex model/effort using `docs/AI_MODEL_SELECTION.md`, plus expected usage and preferred host where justified.

**Work-package contract:** Follow `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`, including scope, exclusions, evidence reuse, validation, protected actions, stop conditions and closeout requirements.

Recommend a split only when the work crosses distinct objectives, authorities or owner-decision boundaries.

## Boundaries

This assessment is read-only.

Do not edit files, create branches, commit, push, publish, merge, install models, run applications, start backends or initiate GPU qualification.

Do not make a material owner-held architecture decision on the owner's behalf.

Do not create a new queue, runner, execution authority, agent hierarchy or orchestration runtime.

If Fable is unavailable, a new session may explicitly perform the same assessment using Opus. Do not pretend the substitute was a Fable assessment.

## Completion

Finish with the decision, remaining uncertainties, exact evidence references and copy-paste implementation contract.

Do not begin implementation. Stop at the design and owner-approval boundary.
