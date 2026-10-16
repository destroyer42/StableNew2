# Product and Engineering Value Assessments

Status: v1.2 repository assessment guidance, revised 2026-10-16. Publication and merge status come from Git, not this document.
Scope: StableNew2. Maintainer: product owner; assessor: one bounded read-only primary Codex/Claude session as needed.

## Purpose

Choose the next smallest coherent work package by **measured product outcomes, exposure, risk, effort, and enabling value**, rather than issue count, cosmetic architecture quality, or historical plans. The assessment is a decision aid, not a new change-control authority and not an autonomous license to execute work.

## Three cadences

| Level | Trigger | Evidence | Exit product |
|---|---|---|---|
| Lightweight | After each substantive package, incident, user report or release | Exact HEAD/diff, acceptance status, affected critical journey, one targeted dependency scan | 1-page decision: continue/stop/reorder; 0–3 follow-ups, no default new PR |
| Focused | Roadmap handoff, clustered failures, uncertain cross-subsystem prerequisite | Scoped current source/target docs, reproductions or tests, change maps, affected users/workflows, risk & cost estimates | Problem-specific 3–8 opportunities, counterhypotheses, one coherent package/NO-GO |
| Comprehensive | Major roadmap milestone, exceptional sustained debt/quality signal, or owner request | All product journeys and target categories, fresh source/ref inventory, PR/CI evidence, product/runtime evidence if authorized, deep dives on material risks, independent critique and rerun | Evidence-bound portfolio, all 12 categories and 8 critical controls, prioritized portfolio, first actionable package and assessment-framework improvements |

No fixed calendar ceremony; assess when a decision can change. A docs-only closeout uses lightweight assessment, not a full audit. Reuse accepted exact-source evidence where source/conditions are unchanged.

## New v1.2 completeness gate
A Comprehensive assessment requires an **eight-surface critical-control ledger** (repo governance, CI effective enforcement, production composition, Windows/process ownership, every durable store, dispatch/cancellation, privileged/untrusted inputs and GUI reachability), plus the **six-factor product capability/use map**. The audit must include negative/fail-open cases and a second adversarial pass using a different method. If any control cannot be checked, label the report partial and name the gap; do not call it green. For Lightweight check *changed controls* only; for Focused check the relevant end-to-end production path. Details: `ASSESSMENT_PLAYBOOK.md` §§12–16.

A verified unmitigated security/data/process ownership threat is a priority gate, not a number in RICE. A failure in a non-required CI job can coexist with an overall green workflow; explicitly check per-job conclusions and enforced branch rules. Accepted tests are evidence, not a substitute for verifying that production actually wires in the intended guard. Avoid broad rewrites and arbitrary deletion/line-count targets without a bounded benefit and safety case.

## Entry authority

1. `git status --short --branch`, `git rev-parse HEAD`, `git remote -v`, compare `origin/main` and branch, diff including untracked; inspect conflicting worktrees/stack ancestry if relevant. If only remote access, explicitly label it **remote main snapshot; local worktree unverified**.
2. Read `AGENTS.md`, `STATUS.md`, relevant `docs/CODEX_MAP.md` and affected architecture/testing sections; `docs/AI_MODEL_SELECTION.md` for any work package.
3. Map product user objectives first; identify recent integrated changes and current outstanding/held decisions. PR descriptions, `STATUS.md` and historical research may disagree: use merge state + source as truth, record drift.
4. Set product-outcome horizon and no-go boundaries. No physical generation, GPU probing or runtime changes merely to perform an assessment.

## Exit authority

Present (a) evidence inventory; (b) actual coverage and gaps; (c) findings with state and falsification tests; (d) safety gates; (e) ranked discretionary work with sensitivity/uncertainty; (f) scoped acceptance; (g) framework critique; (h) any docs impact. Owner selects next package. Never modify `main` directly. Never create a parallel queue, runner, history, lifecycle, compiler or source of record.

Use the [playbook](ASSESSMENT_PLAYBOOK.md) for precise methods, the [template](ASSESSMENT_TEMPLATE.md) for reusable records, and the [dated comprehensive assessment](COMPREHENSIVE_ASSESSMENT_2026-10-15.md) as an example **not ongoing truth**. The [critique trail](ASSESSMENT_DRY_RUN_AND_CRITIQUE_2026-10-15.md) preserves the earlier method and ranking. A row in an old assessment is not a current implementation instruction.

## Dated evidence amendment
The 2026-10-15 comprehensive report was **superseded for prioritization** by the 2026-10-16 v1.2 adjudication addendum following an external production-wiring, security and CI audit. Do not execute `GATE-1` as first work from the old ranking. Read the addendum and recheck actual source/CI settings before making any package decision. The date is historical; nothing here preapproves a code/runtime/branch protection action.

The [2026-10-16 integration correction](COMPREHENSIVE_ASSESSMENT_2026-10-15.md#2026-10-16-integration-verification-and-governance-correction)
supersedes the addendum's unprotected-`main` claim: current branch metadata reports
protection and a `required` check for non-admins; privileged bypass is unverified.
The [opportunity register](OPPORTUNITY_REGISTER.csv) is a compact dated triage
index, not a schedule or authorization. Its priorities and V/D/H/R/U classifications
inherit the cited assessment's evidence limits; governance is refreshed only to the
verified level. Other rows require current confirmation and the full playbook
record before selection. No Comprehensive assessment was rerun for this integration.
