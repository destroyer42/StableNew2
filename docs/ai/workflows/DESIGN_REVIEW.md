# StableNew — Shared Architecture Design Review

## Purpose

Perform a bounded, evidence-based design assessment when a StableNew change presents material architectural ambiguity or a consequential technical decision.

This workflow supports Claude Code and Codex. It does not require a particular model, provider, advisor, subagent or paid entitlement.

## Trigger

Use this workflow when the requested work involves at least one of:

- Competing architectural approaches with significant tradeoffs.
- Unclear runtime, persistence, lifecycle or component ownership.
- A recurring defect that suggests a structural root cause.
- High-cost or difficult-to-reverse engineering decisions.
- An explicit owner request for independent architecture critique.

Do not use it for ordinary implementation, small known-root-cause repairs, documentation work or routine code review.

For external model/backend technology research, use the existing `technology-research` workflow where applicable. For approved feature implementation, use the normal feature-delivery procedure.

## Authority and scope

Follow `AGENTS.md` and `docs/AGENT_OPERATING_MODEL.md`.

This design assessment is read-only. Put any separately approved implementation in its own work package.

Verify current repository identity and worktree state. Read `STATUS.md`, the relevant `docs/CODEX_MAP.md` row and the smallest set of current source, tests and subsystem documents needed.

Do not use historical plans or stale model outputs as current truth.

## Procedure

1. **Frame the decision.** Define the operator outcome, design uncertainty and decision criteria.
2. **Establish evidence.** Identify current code ownership, test evidence, constraints and known unknowns.
3. **Generate alternatives.** Include the minimal-change approach and at least one credible alternative.
4. **Assess architecture.** Evaluate correctness, lifecycle, persistence, recovery, compatibility, security boundaries, implementation cost and testability where relevant.
5. **Challenge the recommendation.** Test the weakest assumption against evidence that could invalidate the preferred approach. Apply the relevant assessment depth and challenge method from [the assessment guidance](../../assessments/README.md).
6. **Resolve or stop.** Recommend a solution when the existing owner contract allows the decision. Otherwise present the material choice to the owner.
7. **Produce the contract.** Translate the recommendation into a coherent, testable work package using the [canonical template](../../CODEX_WORK_PACKAGE_TEMPLATE.md).

Do not require a fixed number of subagents, artificial debate rounds or unrestricted repository audits.

## Model and host selection

Read `docs/AI_MODEL_SELECTION.md`.

Choose the model and effort most likely to resolve the question at the lowest total successful-work cost.

Opus 5.5 is the preferred frontier default when capable and available. Fable 5.2 is an optional exceptional escalation, not a prerequisite.

If invoking Fable requires another host, account, paid access or permissions, do not assume those capabilities exist or are authorized.

Codex must not claim direct Claude delegation without a supported mechanism and actual invocation.

An assessment conducted by one model is not an independent second-model review.

## Required output

- Verified repository identity and evidence limitations.
- Problem and decision to be made.
- Relevant architectural invariants and ownership.
- Alternative designs and tradeoffs.
- Independent critique or explicit self-critique, correctly labeled.
- Recommended solution or NO-GO.
- Material unresolved owner decisions.
- Implementation acceptance contract, exclusions and tests.
- Both-host model/effort recommendations and expected usage.
- Stop conditions and authorization boundaries.

Stop at the approved assessment outcome. Do not begin implementation automatically.
