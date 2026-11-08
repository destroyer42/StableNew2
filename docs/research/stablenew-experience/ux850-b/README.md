# UX-850-B — unified information architecture and operator journeys

**RESEARCH / PROPOSED.** This package specifies an application-wide experience; it changes no application behavior. Recommendation: retain the existing task groups and nine tab identities, strengthen their in-place action/context presentation, and connect their existing artifact views through explicit handoffs. A dedicated Library destination, collections store, new persistence, campaigns and adaptive submission remain separately gated.

## Read this package

| Document | Review question |
|---|---|
| [Navigation and alternatives](NAVIGATION.md) | Where does an operator go, and why prefer this feasible arrangement? |
| [Five detailed journeys](JOURNEYS.md) | What happens from entry to a reviewed artifact or evidence outcome, including failure? |
| [Handoffs](HANDOFFS.md) | Which context crosses workflows and which identity or approval must not cross? |
| [Shared interaction semantics](INTERACTION_SEMANTICS.md) | What do Apply, Preview, Submit, Review, Cancel and Recovery mean? |
| [73-decision interaction coverage](DECISION_COVERAGE.md) | Where does every confirmed direction appear, including advanced and held work? |
| [Consistency challenge](CONSISTENCY_CRITIQUE.md) | Does the recommendation survive alternative-first and negative-case analysis? |
| [Evidence and validation](EVIDENCE_AND_VALIDATION.md) | What was actually inspected and what remains unknown? |

## Execution Profile + Model/Reasoning Recommendation

- Class: **Standard research/design**, Local/Desktop; one fresh top-level session, no delegated agents.
- Start before discovery: `2026-11-07T23:23:35-05:00`; session `codex:01a1b965-a170-7882-9da4-f4ccfd8213e7` is the only participating session.
- Worktree: `C:/Users/rob/qual/StableNew-ux850b`; branch `research/ux850-b-operator-journeys`; base `f51aa870824a0804202c438531f4f1c9e0bc231c` (accepted A, PR #263).
- **Model recommendation:** Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High. This substantial known-architecture research needs cross-workflow consistency in one context; a lower tier risks another evidence/repair pass. No host switch offers a material advantage. Expected usage: about 5M cache-read / 40k output, a planning prior rather than a measured result. Actual model/usage belongs in the final PR record from `tools/usage_report.py`.
- Authorization: research Markdown/diagrams only; publish this branch/one PR to `destroyer42/StableNew2`, repair in-scope findings, merge to `main` only after applicable exact-head CI and final checks. No production implementation, runtime execution, migration, external-state configuration or next package C.

## Controller Surface Assessment

No controller/coordinator code is changed. Future presentation work should reuse AppStateV2, the existing navigation/presentation ports and dispatcher, cohesive profile/edit/sequence/Learning services, and JobService admission. No new responsibilities or ceiling increases in ratcheted controllers are proposed. A future general Library or campaign must first define ownership; this research does not grant it execution/persistence authority.

## Token-Efficient Validation Plan

1. Reuse A's source index and all 73 six-dimension rows after checking blob applicability against this base; inspect only navigation, handoff and relevant subsystem contracts needed to refine the journeys.
2. Check all confirmed-ID mappings, relative links/fragments, source anchors, diagrams and shared semantics using documentary/static tools. Challenge routes by a separate failure-state method in the same session; do not label this independent review.
3. Run the existing cheap documentation checks and the PR evidence checker. No full PR gate or application/GUI/model tests: current policy classifies these Markdown-only files as docs-only.
4. Review aggregate diff and whitespace once, then verify remote base/head, exact-head CI job conclusions, review findings, scope and protected-action authorization immediately before publication/merge. Preserve the shared checkout's `presets/settings.json` edit.

## Acceptance and evidence boundary

**Implementation:** these design specifications, alternatives, annotated flows, identity rules and complete direction mapping. **Demonstration:** source/document inspection and static documentary checks recorded with exact commit identity in the PR; no observed operator task. **Qualification:** N/A; no qualification authority or verdict changed. **Unverified/held:** usability, accessibility/DPI, real generation/quality, model readiness, crash recovery beyond existing stores, advanced Library/media/evaluator/campaign functions and material decisions listed in [the critique](CONSISTENCY_CRITIQUE.md#material-decisions-retained).

This is a focused design synthesis using A's **partial Comprehensive** assessment, not completion of its unexamined critical controls. `STATUS.md`, architecture, runtime ownership and roadmap priorities are unchanged. The research recommendation is ready for owner review; merging the report is not approval to implement its proposals.
