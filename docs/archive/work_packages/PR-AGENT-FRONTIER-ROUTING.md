# PR-AGENT-FRONTIER-ROUTING — Frontier Model Routing and Versioned Project Instructions

## Objective

Establish a durable, repo-visible, provider-compatible AI orchestration strategy for StableNew without changing production code, application behavior or repository authority.

The owner has approved:

- Opus 5.5 as the preferred frontier orchestrator for work that materially benefits from orchestration.
- Sonnet 5.5 and other lower-cost models for routine or well-understood execution when they can complete the whole package correctly.
- Fable 5.2 as an optional, availability-dependent design capability, not a permanent dependency or a required advisor.
- Use of the Opus orchestration prompt as the reusable default orchestration pattern.
- Temporary use of the read-only Fable architecture assessment prompt while access remains available.
- `AGENTS.md` as the only repository operating-rule authority.

These decisions are approved for configuration and documentation. They do not independently authorize implementation of future product changes, physical runs, publication or merge.

## Execution Profile and Model Recommendation

**Execution class:** Standard, documentation/agent-configuration only.

**Claude Code:** Sonnet 5.5 Medium.

**Codex:** GPT-6.1 Sol Medium.

Use the current productive local session. Both recommended tiers can handle the policy, provider layout and focused verification in one pass, avoiding a handoff or repeated discovery.

**Escalation:** High effort only if provider skill compatibility or instruction-resolution behavior proves materially more complicated. Do not invoke Fable merely to write these documentation files.

**Expected usage:** Approximately 1–3M cache-read tokens and 10–30k output tokens, with substantial uncertainty. Measure the entire package using the canonical method.

**Controller Surface Assessment:** No controller or application source changes. Not applicable.

**Security review:** No default specialist review for documentation. If changes unexpectedly touch provider tool permissions, executable hooks, credentials or configuration with privileged behavior, stop and reassess the security trigger under the operating model.

## 1. Establish the current authority

Before repository discovery, record:

- ISO 8601 task-start timestamp with timezone.
- Host, actual model, effort and session ID.
- Every additional participating session or subagent ID.

Verify:

- Local repository identity and current branch.
- Local HEAD and `origin/main`.
- Remote refs and worktree state.
- Dirty, staged and untracked files.
- Relevant existing skills and provider configuration.

Read:

- `AGENTS.md`
- `STATUS.md`
- `docs/CODEX_MAP.md`
- `docs/AI_MODEL_SELECTION.md`
- `docs/AGENT_OPERATING_MODEL.md`
- `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`
- `CLAUDE.md`
- `.github/copilot-instructions.md`
- Existing `.claude/skills/` workflows and any current Codex skill configuration.

The research reference is remote `main` at `682f432cf36660c062bdcf03816d922d47c14fcb`. This SHA is not a required implementation base if `main` has advanced.

Use current checkout evidence over this proposal wherever they differ.

## 2. Preserve authority

`AGENTS.md` remains authoritative.

Do not modify it merely to introduce Fable, Opus, project-instruction mirrors or skills. Its current authority, execution, protected-action and validation rules already support this package.

If inspection reveals a genuinely missing authoritative rule:

1. Identify the precise gap and why current policy cannot express the requirement.
2. Propose the smallest necessary amendment.
3. Stop and request an owner decision before changing `AGENTS.md`.

Do not duplicate repository invariants, model matrices, safety rules or protected-action policy in project instructions.

Preserve `CLAUDE.md` unless current evidence demonstrates a specific compatibility defect.

## 3. Update model-selection guidance

Modify `docs/AI_MODEL_SELECTION.md` in place.

Preserve:

- Its role as the single model-selection authority.
- Both-host model/effort recommendations.
- Expected-usage requirements.
- Exact timestamp/session-based usage measurement.
- The calibration rules based on PR outcomes.
- The existing 3x usage-investigation threshold.
- The distinction between recommendation, actual model and measured usage.

Update the model table to recognize current Claude model options, including Haiku 5.5, Sonnet 5.5, Opus 5.5 and Fable 5.2, subject to verification of host availability.

Make Opus the preferred frontier orchestrator, but not the mandatory executor of every small task.

Treat Fable as an exceptional optional design escalation, with High effort as its initial starting point. Document that limited promotional availability does not constitute a permanent supported capability or an API spending authorization.

Do not claim that StableNew's own PR history has already validated Fable's effectiveness. Existing PR-calibration rules remain controlling.

## 4. Add version-controlled project instructions

Create:

- `docs/ai/project-instructions/CODEX_PROJECT.md`
- `docs/ai/project-instructions/CLAUDE_CODE_PROJECT.md`
- `docs/ai/project-instructions/README.md`

Use the proposed file content supplied with this package, adapting only where current repository evidence demands it.

The two instruction files are mirrors of externally configured project instructions. They are not new authorities, and Git changes do not automatically synchronize external project configuration.

Document an explicit manual synchronization procedure, including comparison of source and destination text, reporting of sync state and verification of effective instruction loading where possible.

Do not write to any external project configuration as part of this PR without separate authorization.

## 5. Add reusable prompts

Create:

- `docs/ai/prompts/OPUS_ORCHESTRATOR.md`
- `docs/ai/prompts/FABLE_DESIGN_ASSESSMENT.md`

The Opus prompt is the durable default orchestration strategy. It must remain fully functional with no Fable access, advisor, API entitlement or additional spend.

Fable consultation is conditional on current availability, authorization and an identifiable architectural problem that warrants it.

The Fable prompt is a bounded, read-only design assessment. It must produce evidence, alternatives, critique and implementation-ready contracts, and must stop at owner-decision boundaries.

Do not create a permanent Fable-led implementation or multiagent orchestration requirement.

## 6. Add one portable design-review workflow

Create the shared procedure:

- `docs/ai/workflows/DESIGN_REVIEW.md`

Create thin discoverable entry points:

- `.claude/skills/stablenew-design-review/SKILL.md`
- `.agents/skills/stablenew-design-review/SKILL.md`

Both skill entries must reference the same shared procedure, use valid metadata/frontmatter and preserve repository-relative portability.

Use the skill for material architectural ambiguity, consequential alternative designs, ownership questions or high-cost structural decisions.

Do not trigger it for ordinary coding, known repairs, documentation maintenance or routine validation.

The workflow is provider-neutral. It may recommend Fable when actually available, but it must not assume that Codex can invoke a Claude model or that the host has native cross-provider delegation.

Do not create mandatory specialist sequences, Git mutation agents, scheduled work, new orchestrator services or external dependencies.

## 7. Validate compatibility and instruction hierarchy

Verify that:

1. Every new path exists, is spelled correctly and is referenced from the intended files.
2. Every skill contains valid YAML frontmatter and a specific trigger description.
3. Claude Code discovers its skill in a supported environment.
4. Codex discovers its skill in a supported environment.
5. A deliberately ordinary request does not cause the design skill to trigger unnecessarily.
6. The design-review workflow loads the shared procedure and produces the specified assessment format.
7. The instructions do not conflict with `AGENTS.md` or the single-lane model.
8. The default orchestration prompt can operate when Fable is unavailable.
9. The Fable assessment cannot accidentally authorize implementation, backend runs, publication or merge.
10. The two external project mirrors have an inspectable, non-authoritative sync procedure.
11. `AGENTS.md`, `CLAUDE.md` and other always-loaded instruction files remain appropriately small.
12. No credentials, personal paths, API keys, promotional entitlements or machine-specific configuration are introduced.

Use actual provider discovery or a supported local validation facility when available. Static file validation alone is not proof that a host discovered a skill.

If a provider client is unavailable, mark runtime discovery unverified and report the missing evidence. Do not install, repair or reconfigure the provider merely to satisfy this PR.

## 8. Token-Efficient Validation Plan

Use the changed-file classifier to confirm the docs-only path, then run its cheap checks once. Reuse evidence for unchanged application surfaces. Run targeted checks first:

- Git diff and whitespace checks.
- Markdown structure and link/path checks.
- YAML/frontmatter parsing.
- Relative file-reference checks.
- Any existing repository tests specifically applicable to agent configuration, instructions or documentation.
- Relevant `ci_truth.py` documentation/completeness checks.
- The repository's applicable docs-only PR gate.

Do not run the full application test census, GPU checks, Forge, A1111, ComfyUI, Tk journeys or physical qualification.

Do not weaken a repository gate. If the prescribed docs-only path unexpectedly requires expensive validation, identify the reason and follow current policy rather than silently bypassing it.

Inspect the final aggregate diff for duplicated policy, misleading authority, stale model claims, unbounded delegation and unjustified files.

## 9. Scope exclusions

This package does not authorize:

- Production Python code changes.
- Runtime architecture or persistence changes.
- GPU/model/backend generation or qualification.
- Modifying external provider accounts, subscriptions, billing or project settings.
- API credit purchases or paid Fable invocation.
- Repository protection or CI-policy weakening.
- Changes to unrelated skills, agents or user work.
- Mandatory Delivery/Release handoffs.
- Automated prompt synchronization.
- A new prompt-management application or custom orchestration runtime.
- Push, PR publication or merge without the required owner authorization.

## 10. Stop conditions

Stop and report if:

- Current `AGENTS.md` requires a material authoritative change.
- A provider's actual skill-loading behavior invalidates the proposed layout and a material design choice is needed.
- Cross-provider delegation requires new credentials, billing or elevated permissions.
- The task expands into application code, runtime configuration or unrelated agent refactoring.
- Worktree ownership is ambiguous or existing work would be overwritten.
- More than two materially distinct failure classes emerge.
- The bounded repair/reverification budget is exhausted.
- The docs-only acceptance contract has been met.

Resolve ordinary documentation, file-path and frontmatter details within the approved scope without unnecessary owner escalation.

## 11. Acceptance criteria

The package is complete when:

- Both project instruction mirrors are committed and explicitly non-authoritative.
- The manual synchronization procedure is complete and actionable.
- The Opus default prompt and temporary Fable assessment prompt are committed.
- Opus orchestration functions without Fable or an advisor.
- The shared design-review procedure has discoverable, valid Claude and Codex skill entries.
- Fable is optional, not a dependency.
- Model guidance is updated without discarding the established PR-calibration method.
- Existing authority and single-lane execution rules remain intact.
- Applicable docs-only checks pass.
- The final aggregate diff contains no unrelated code or configuration changes.
- Report any provider-runtime checks that could not be performed.
- Exact usage telemetry is reported where available.

## 12. Completion report

Provide:

**Outcome:** PASS, FAIL or BLOCKED.

**Repository:** local branch, parent SHA, final SHA, remote reference and worktree condition.

**Changed files:** additions and modifications with a concise explanation.

**Authority impact:** confirm whether `AGENTS.md` and `CLAUDE.md` remained unchanged; identify any exceptions.

**Validation:** exact commands, results and limitations.

**Skill discovery:** Claude verified/unverified; Codex verified/unverified; explanation for gaps.

**Prompt behavior:** evidence that Opus-only operation does not depend on Fable and the design-review skill remains read-only.

**External project sync:** mark as NOT SYNCED unless the owner separately confirms or authorizes synchronization.

**Model / usage:** actual host, model, effort, repair passes, result, task-start/task-end timestamps, session IDs and measured token categories using `tools/usage_report.py`.

Do not substitute `--since-commit` for full-package measurement. Do not invent missing telemetry or costs.

**Publication:** Publish the scoped feature branch and open the PR against `main` under the owner’s publication authorization. Monitor the PR head’s applicable CI and stop at the merge approval boundary.
