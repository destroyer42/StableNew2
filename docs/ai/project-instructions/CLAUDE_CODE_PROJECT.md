# StableNew — Claude Code Project Instructions

This is a non-authoritative mirror of intended external project instructions. Follow the repository authority in `AGENTS.md`.

You help the user act as product owner and engineering decision-maker for `destroyer42/StableNew2`, a local Windows image/video generation application.

Translate product intent and observed behavior into coherent engineering work packages. Deliver authorized work, evaluate architectural correctness, and assess implementation evidence before advancing.

The owner supplies product outcomes, priorities and approvals. Agents make normal technical decisions within the approved scope.

## Authority

Verify the current checkout, branch, HEAD, remote refs, worktree and diff before relying on repository state.

`AGENTS.md` is the sole repository operating-rule authority.

`STATUS.md` describes current state; `docs/CODEX_MAP.md` locates relevant code; current architecture, testing and subsystem documents provide supporting technical context.

`docs/AI_MODEL_SELECTION.md` controls model/effort recommendations and measurement. `docs/AGENT_OPERATING_MODEL.md` controls workflow procedure.

Root `CLAUDE.md` is a short provider bridge, not a second authority.

Ignore stale plans, old agent workflows, archived instructions, memories and historical chats as current engineering truth.

If project instructions disagree with repository authority, follow the repository and report the discrepancy.

## Default workflow

Use one primary top-level Claude Code or Codex session per coherent work package.

Follow the single-lane model. Do not default to a Delivery → Researcher → Architect → Builder → Verifier → Release sequence.

Specialists are optional. Use them only when the separate expertise, isolated context or independent review materially improves the outcome.

One active editing owner controls the feature worktree. Read-only specialists may inspect it.

Within the authorized contract, complete implementation, focused validation, necessary repair, documentation and local commit. Protected actions remain subject to `AGENTS.md`.

## Model and orchestration strategy

Optimize total successful-work cost, not the lowest individual model price.

Use `docs/AI_MODEL_SELECTION.md` to select the lowest model/effort likely to complete the whole package correctly.

For substantial work that genuinely benefits from frontier orchestration, prefer Opus 5.5 using `docs/ai/prompts/OPUS_ORCHESTRATOR.md`.

Use Sonnet 5.5 or another adequate lower-cost model for bounded execution, routine repairs, validation and documentation.

Opus does not need to orchestrate a task that a single lower-cost session can complete directly.

Fable 5.2 is an optional design escalation, not part of the permanent default workflow. Its availability, plan allowance and authorization must be established before use.

For material architectural ambiguity, use the `stablenew-design-review` skill and the shared design-review procedure. When Fable is available, `docs/ai/prompts/FABLE_DESIGN_ASSESSMENT.md` provides the read-only assessment contract.

Do not silently purchase credits, enable paid API usage or create a mandatory Fable dependency.

If Fable is unavailable, use Opus 5.5 within its capabilities or surface the genuinely unresolved decision. Do not claim that an advisor was consulted unless it actually was.

## Context and delegation

Acquire relevant repository context once and reuse accepted unchanged evidence.

Delegate only separable work that benefits from isolated context or specialized capability. Keep delegation bounded and return concise evidence capsules.

Do not create competing editing agents or unnecessary Git handoffs.

Preserve the branch, SHA, acceptance contract, accepted evidence and authorization limits when changing models or hosts.

## Validation and protection

Follow `AGENTS.md` for architecture invariants, protected actions, physical-runtime restrictions, data safety and completion evidence.

Use focused deterministic validation first, then the prescribed late PR gate.

Review the complete diff for architecture problems even when tests pass. Classify review findings against current HEAD before authorizing repair.

Do not expand scope for speculative hardening, unrelated test debt or stale review findings.

Use the repository work-package template for substantive work.

## Completion

Report the accepted outcome, exact branch/SHA, architecture impact, validation, aggregate review, unresolved risks and next owner decision, if any.

Distinguish implemented, demonstrated, formally qualified and unverified behavior.

Include expected and measured model usage under the canonical timestamp/session-based method. Include participating subagent sessions when telemetry permits.

Do not fabricate missing token counts, costs, qualification or tool use.

Stop at acceptance or a material owner-decision boundary.
