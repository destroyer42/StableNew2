# Evidence identity and documentary validation

## Intake and unchanged evidence

| Item | Exact identity / boundary |
|---|---|
| Start / sole participating session | `2026-11-07T23:23:35-05:00`, `codex:01a1b965-a170-7882-9da4-f4ccfd8213e7`; recorded before repository discovery; no subagents |
| Isolated branch/worktree | `research/ux850-b-operator-journeys`, `C:/Users/rob/qual/StableNew-ux850b`; newly created from refreshed `origin/main` |
| Source/base | `f51aa870824a0804202c438531f4f1c9e0bc231c`; accepted A merge [PR #263](https://github.com/destroyer42/StableNew2/pull/263); A head `5e081494fac33d96b47fde836a42a9a344c17ce0` |
| A evidence cut | `8e1ee82b5fd8cc18437274e86e9af4f59938a799`; application tree byte-identical in Git to `3399f8032182b65bd904f8f27818d927909cd6a3` |
| Complete owner input | [R1 OWNER_DECISIONS](../ux-850-r1/OWNER_DECISIONS.md), accepted PR #262, merge `8e1ee82b`; 73 confirmed IDs, pending 072 |
| Existing design input | [R1 EXPERIENCE_DESIGN](../ux-850-r1/EXPERIENCE_DESIGN.md) and [DELIVERY_PLAN](../ux-850-r1/DELIVERY_PLAN.md), proposals retained/refined rather than treated as delivered behavior |
| Preserved work | Shared main checkout at intake `8e1ee82b` with user-owned `presets/settings.json` modification; untouched, unstaged, never reset/stashed |

A's [84-entry source index](../ux850-a/SOURCE_INDEX.md), [screen inventory](../ux850-a/SCREEN_WORKFLOW_INVENTORY.md), [ownership/store map](../ux850-a/OWNERSHIP_BOUNDARY_MAP.md), [73-row evidence matrix](../ux850-a/DECISION_TRACEABILITY.md) and [gap/control ledger](../ux850-a/GAPS_RISKS_UNKNOWNS.md) remain the baseline. B checks Git blob/line applicability and unchanged relevant trees, rather than rerunning A's research or tests. Git blobs avoid checkout line-ending ambiguity in reusing exact-source evidence.

Reused evidence remains bounded: A/R1's 141 pure contract tests and 7 Experiment Library tests at application SHA `3399f803`, with no new application execution. Accepted application CI run [42442490513](https://github.com/destroyer42/StableNew2/actions/runs/42442490513) had individually checked successful required/census/full-suite/windows jobs as recorded in A; these are inherited evidence, not a new runtime pass or all-73 qualification. A's historical Tk `0xc0000008` attempt has no complete verdict and is not a reproduced current defect. A's docs-only PR [42446349710](https://github.com/destroyer42/StableNew2/actions/runs/42446349710) and merge [42446543295](https://github.com/destroyer42/StableNew2/actions/runs/42446543295) show required success with full-suite/shard/windows skipped by policy, not fresh test passes.

## Focused source inspection

After consulting AGENTS/STATUS/CODEX_MAP, generated CODE_MAP GUI entries, work-package/PR templates, operating model, model-selection and assessment guidance, inspect only the design-sensitive owners: navigation contract and MainWindow bindings, GUI ownership/settings/presentation contracts, History iteration and video/review handoff helpers, plus relevant PromptPack compilation, Review preservation, Storyboard and Learning sections in living subsystem docs. A already supplies exact source bindings for the remaining journey steps.

Two consequential refinements came from this pass: the startup resolver's exact legacy fallback condition must be preserved, and E67's video helper does not provide the generalized transactional/unsent-work semantics proposed in H4. Neither justifies production edits in this package.

## Static validation contract

The local documentary helper, kept outside Git in the session artifact directory, checks:

- Exactly 73 unique coverage rows, equal to 001–071 plus 005A/007A, with exact owner titles and twelve 071 facet rows; no confirmed 072 row.
- All 84 A index references against committed Git blobs and line bounds, plus unchanged source/test/config/tool/CI trees from the accepted application evidence. Every used E reference exists.
- Relative Markdown file/fragment targets across the changed documents; no invented missing delivery links. Source URLs are exact-SHA A anchors, validated against local committed content rather than fetched individually.
- All seven flowcharts against their deliberately small Mermaid subset: `flowchart LR`, quoted node declarations, directed edges, existing node references, nonempty labels and connected graphs. No desktop/browser renderer is invoked; visual layout/render quality is unverified.
- Complete five-journey/default/advanced/error/empty/outcome structure; handoff fields and replacement/identity rules are reviewed by the method-diverse paper challenge rather than asserted as runtime tests.
- Aggregate Markdown-only scope, unchanged existing files except the research navigation index, and whitespace. No source/test/config/dependency or qualification record edits.

Run the policy's cheap checks: `check_repository_completeness.py`, `check_controller_surface.py`, `ci_truth.py`, plus `git diff --check` and the existing PR evidence checker. The repository's `validation_plan.py` must classify the final aggregate diff as `docs_only=true`, `cheap_path=true`, `full_census=false`. Do not invoke `run_pr_gate.py`, full suites, GUI tests, resource probes or real generation in this research scope.

## Hosted CI and protected-action record

The final PR body is the live record of exact head/base/merge identities, check run IDs and **individual job conclusions**, review findings, branch protection, publication/merge authorization, local checks and measured usage. It avoids a self-referential extra commit solely to name the final SHA. Immediately before merge recheck main/head/ancestry, doc-only aggregate diff and clean worktree, applicable check conclusions, comments/reviews/unresolved threads and unchanged authorization; do not bypass or substitute another ref if anything drifts.

Expected docs policy: required executes the cheap checks; full-suite, census shard and Windows are skipped by policy. Skipped is not success of a runtime test. PR evidence advisory is a separate non-required check. Confirm the actual run rather than assuming these outcomes. After normal merge verify remote main/merge tree and applicable push CI. No automatic branch deletion, shared-checkout update or package C.

## Limits

Implementation is documentation only; demonstration is static documentary inspection/checking and A's explicitly inherited evidence; qualification is N/A. Usability, accessibility/DPI, model readiness, actual artifact quality and all new persistence/campaign/evaluator behavior are unverified/held. The [consistency critique](CONSISTENCY_CRITIQUE.md) is same-author and method-diverse; independent review was not performed. No canonical current-state truth changed, so STATUS, architecture and roadmap authorities are unedited.
