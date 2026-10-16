# StableNew Product–Engineering Value Assessment Playbook — v1.2

Status: repository assessment guidance v1.2, revised 2026-10-16 after an independent external repository audit and source-level adjudication. Publication and merge status come from Git. This is a repeatable method, not a claim that dated defects remain current. No historical SHA governs future runs.

## 0. Decision question and quality bar

Given one product objective and scarce developer/operator/GPU time, select the smallest high-confidence, high-return next intervention subject to safety and architecture constraints. Never conclude "refactor" merely from size or "feature" merely from demand. Value includes delivered user outcomes, reliability/data integrity, reduced operator toil, compounding enablement and reduced engineering rework. Show disconfirming evidence.

Assessment completeness is not universal code review. For Comprehensive, inventory every category and follow the highest signals through production code, tests and known incidents; declare uninspected branches/modules, local state, physical limitations and telemetry gaps. If absent operational access makes essential outcomes unverifiable, mark quality verdict **partial**, not pass.

## 1. Evidence acquisition and hierarchy

Source order: checkout SHA/diff (or explicitly remote SHA) > `AGENTS.md`/`STATUS.md` > relevant `CODEX_MAP.md` > architecture/testing/roadmap > underlying code and tests > actual hosted CI/accepted run logs > current verified operator evidence > durable decision rationale > older reports/chats. Actual code, tests, exact current CI and operator behavior can correct stale text. Timestamp all externally mutable observations. Recheck SHA before publishing; if changed, assess impact; do not silently transplant conclusions.

Record each finding with the following **status** (V/D/H/R/U), *and separately* the implementation-proof tier and impact-proof tier described in §12. A source observation must never be passed off as a physical incident. Statuses:
- **V** (verified current): inspected implementation + exact-run, test, or observed current behavior as applicable;
- **D** (documented residual): current authoritative repo records the gap, but no independent fresh reproduction;
- **H** (hypothesis): plausible, specified falsification method, not asserted as defective;
- **R** (resolved/merged): verified current implementation/disposition; removed from fresh-work ranking;
- **U** (unknown/blocked): essential evidence unavailable, not a negative finding.

For claims about model quality, actual image/video quality, GPU fault recurrence, Windows layout, or physical backend performance, code/doc inspection alone can at most establish D/H. PR narrative and deterministic CI do not prove physical acceptance. For code correctness, cite exact call paths and tests rather than GitHub PR title alone.

## 2. Map outcomes and cross-system journeys

At minimum: initial app start/readiness; create/import PromptPack; compose/preflight/model-policy; Run Now/queue; image backend dispatch; progress/restart/cancel; artifact/history/replay; Review/refine/photo; Learning/model comparison; SVD/video workflow/motion; managed/external WebUI/Comfy processes; diagnosed hardware/GPU loss; Windows UI reachability. Mark criticality; record intended/actual outcomes, user-visible failure, frequency, evidence quality, and dependencies. Count jobs or runs per journey instead of nominal user population when appropriate.

## 3. Target-category coverage

Every Comprehensive assessment must visit the twelve product categories **and the independent critical-control gate in §12**:
1. Core product outcomes and missing capability.
2. Reliability, data integrity, queue/process/recovery safety.
3. Model-family compatibility / prompt and artifact semantics.
4. Image generation, refinement, output quality and provenance.
5. Video/workflow motion quality and feasibility.
6. UX and accessibility / critical journey friction.
7. Architecture and maintainability / cross-boundary ownership.
8. Test truth, CI, tooling and developer flow.
9. Security, supply chain and adversarial/untrusted inputs.
10. Performance, resources and operating cost (GPU, latency, disk).
11. Observability, provenance and measurement coverage.
12. Roadmap dependencies, sequencing and documentation/knowledge drift.

Use ISO/IEC 25010:2023 as a quality-dimension completeness check rather than pretending to certify it. Use SRE critical user journeys for end-to-end reliability, DORA for throughput/instability with local-desktop adaptations, SPACE to avoid one-metric productivity optimization, NIST SSDF and OWASP for risk-based security review.

## 4. Acquire evidence efficiently (one context pass)

- Read fresh `main` / active branch, merged PR heads, relevant diffs, issue state; do not treat a PR tagged "open" in `STATUS.md` as open if GitHub says merged.
- Inspect targeted call graph, failure paths, actual test assertions, and controller-surface ceilings for top candidates. Count raw file size as **screening only**; do not claim hotspot without history of churn, defect, ownership and coupling evidence. Use `git log --numstat`, changed-file/PR history, and regression incidence when available.
- Check required CI on the **same source SHA** and distinguish PR-head, main and older green runs. Record pass/fail and scope; note collection count separately from runtime and high-value coverage.
- For physical quality/Windows/GPU use existing owned artifacts/logs first. Do not execute tests requiring machine changes or user assets without owner approval.
- Check accepted prior work to remove already-resolved opportunities. Reuse current documentation only where verified and label its limitations.
- Record missing telemetry, sample bias, test-environment contamination and absent owner ratings as explicit unknowns.

## 5. Diagnostic reasoning

For every candidate: state a precise symptom, **hypothesized root cause**, owners, cross-workflow blast radius, counterexample, alternative explanation, evidence needed to falsify, and the minimal intervention. A successful PR or high line count alone does not prove residual problem. If a fix addresses multiple symptoms, identify the common boundary; don't count the same benefit multiple times.

## 6. Two-stage priority decision

**Stage A: non-compensatory gates.** Threat of data loss/irreversible operator changes, unsafe unknown-outcome generation replay, unauthorized external-process intervention, or currently blocked critical user journey requires risk disposition first; never dilute with an average impact score. Separate "mitigated but residual" from "actively reproducing". Hardware instability is not automatically a code defect. Require product-owner decision before material recovery-policy changes or physical inference.

**Stage B: economic choice.** For discretionary choices use ordinal evidence-backed fields: affected journey/reach frequency; per-instance user impact; confidence in problem and in solution (separate); effort including validation and downstream maintenance; cost of delay; enabling dependency count; uncertainty; opportunity cost. Standard RICE may be computed **only** when reach, impact, confidence and effort have defensible units on a common period; never use invented numeric point scores as measured ROI. Instead use a transparent value/effort matrix and sensitivity: would rank change if low-confidence assumptions fail, effort doubles, or a prerequisite is already merged? Always compare "do nothing/monitor", "diagnose first", and "bounded fix".

Recommendation bands: **P0** action to contain a verified acute risk; **P1** next decision-critical work; **P2** worthwhile after prerequisites; **P3** monitor/adjacent debt; **R** resolved/no new work; **U** insufficient evidence. These are sequencing signals, not severity badges. Within a band preserve dependencies. At most one active package. Separate **investigation** from an authorized change to product/host configuration.

## 7. Three runnable assessment procedures

### Lightweight (post-PR / post-incident)

Before disposition, use the §12 control-change screen. For affected security/CI/ownership/persistence/wiring controls, check their actual enforced negative path, not a PR summary. Unchanged controls need no repeated full audit.

1. Capture branch/SHA/diff/worktree and CI verdict. Verify package acceptance and any source drift.
2. Evaluate whether a critical journey, safety/owner boundary or product objective changed. Read only affected CODEX_MAP entries/docs.
3. Update 0–3 register rows: closed, remaining, new; preserve accepted tests if source unchanged.
4. Ask what could change the next priority; explicitly choose **continue / reorder / stop / request evidence**.
5. Produce one short disposition, doc-impact gate; do not create a work package unless needed.

### Focused (decision or subsystem)

Trace the relevant **real production composition and entry point** and test a negative/fail-open case. If the objective concerns user-facing function, prove the actual UI invocation route. Relevant §12 controls apply regardless of which subsystem nominally owns the task.

1. Define one product objective, observable target and boundaries.
2. Trace affected critical journey across GUI → compile → immutable NJR → JobService → repository/queue → runner → handler → artifact, as relevant.
3. Inspect current implementation, canonical docs, exact tests/CI, incident and counterevidence. Reproduce deterministic failure if authorized.
4. Generate 3–8 candidates including no-action and smallest fix; independently argue each could be wrong.
5. Rank with risk gate and ordinal economics; identify any owner decision, physical validation, or architectural stop.
6. Return one coherent package (or NO-GO) with testable acceptance, regression boundaries, both model recommendations.

### Comprehensive (portfolio reorientation)

**Do not call the result Comprehensive** until all §12 mandatory controls and §13 reachability/usage dimensions have evidence or explicit bounded gaps, and §14 adversarial pass is independently method-diverse. A green badge, passing tests, or a doc label cannot stand in for proof of effective enforcement.

1. Verify exact Git state and current source horizon; establish objectives and inventory all 12 target categories.
2. Sample every critical journey, then drill down on the highest material problems; log method, coverage and blind spots.
3. Enumerate and classify all important candidates V/D/H/R/U; locate proof, owner, disconfirmation, and impact on outcome.
4. Preliminary safety dispositions and discretionary rankings; preserve this **initial pass** verbatim.
5. Independent adversarial critique: check source staleness, reversals after merged fixes, selection bias, hardware/quality assumptions, missing direct code, missing usage denominator, unmeasured CI, double-counting, urgency inflation, security blind spots, alternative minimal options, operator fit and incorrect permission assumptions.
6. Critically challenge omissions using the §12 control coverage ledger, §13 capability/usage matrix and §14 blindspot prompt set; modify rubric/method **before** rerun, preserving the initial ranking and a version-change log naming what changed and why.
7. Rerun evidence reconciliation (including fresh merged state and changed baseline), category matrix and priority with revised method. Record changed rankings and rejected candidates; note which hypotheses remain unverified.
8. Produce final top category recommendation(s), one primary work-package acceptance contract, contingent follow-ons, required owner decisions, evidence debt and explicit source/time boundaries.

## 8. Opportunity record contract

`id | category | critical journey | user outcome | symptom | status V/D/H/R/U | implementation evidence tier | impact evidence tier | evidence & exact SHA | actual production reachability | current exposure | contradictory evidence | confidence(problem) | confidence(solution) | severity/risk gate | reach & recurrence/denominator | benefit | enabling dependencies | effort/validation | cost of delay | cheapest falsification | alternatives/no-action | proposed package | owner/action authorization | disposition | expiry/refresh trigger`

Do not store time-sensitive SHAs as durable behavioral rules; SHAs belong in dated assessment reports. Store sensitive user artifacts or host logs in their existing protected locations, not public repo reports. Link only safe paths and hashes.

## 9. Decision and validation contract for a proposed package

Identify one bounded product outcome; current starting SHA and no-stale-evidence gate; architectural invariants; observable before/after acceptance; failure injection/negative cases; exact tests and final gate; physical experiments only with explicit permission; data/process isolation; rollback/refusal behavior; docs impact; stop conditions; normal Git authority. Recommend exact **Claude Code** and **Codex** models/effort from current `docs/AI_MODEL_SELECTION.md`; prefer Local/Desktop only where machine state matters. No preauthorization to push, merge, force-push, deploy, tag or change runtime/hardware.

## 10. Review of the reviewer

Every Comprehensive report must include: §12 control coverage ledger, §13 feature reachability matrix, independent critique ledger (each critique Confirmed/Refuted/Partly confirmed, evidence and method change), pre-/post-change ranking delta, an adversarial failure test for each P1, an evidence coverage table by category, and a dated data-access limitation. Evaluate assessment process itself with: previous top-N recommendation relevance at next transition; false-positive rate ("already fixed"), stale-link rate, effort estimate direction, forecast vs realized impact, and percent of high-priority claims with falsifiable direct evidence. Avoid success theater and fake precision.

## 11. Supporting research and standards (informative, not repo authority)

- Google, Product-Focused Reliability for SRE: https://sre.google/resources/practices-and-processes/product-focused-reliability-for-sre/
- DORA, delivery performance and throughput/instability: https://dora.dev/insights/dora-metrics-history/
- Forsgren et al., SPACE developer productivity framework: https://doi.org/10.1145/3454122.3454124
- Intercom, RICE prioritization method: https://www.intercom.com/blog/rice-simple-prioritization-for-product-managers
- ISO/IEC 25010:2023: https://www.iso.org/standard/78176.html
- NIST SP 800-218 final SSDF v1.1: https://csrc.nist.gov/pubs/sp/800/218/final (rev.1 v1.2 was an initial public draft as of this assessment)
- OWASP risk method: https://community.owasp.org/OWASP_Risk_Rating_Methodology


## 12. Mandatory critical-control coverage (v1.2; independent of product categories)

A Comprehensive review must inspect **all eight** enforcement surfaces. An uninspected surface is a named gap; it is never implicitly safe. A Focused review covers all touched controls; a Lightweight review checks for deltas only. Each ledger row records: inspected entrypoint, enforcing code/config, default/negative path, tests, effective behavior, impact evidence, confidence, source SHA/time, and remaining uncertainty.

| Control | Required verification, including fail-open case |
|---|---|
| Repository governance | Branch protection/rulesets **effective**, required checks, bypass and direct-push posture; distinguish permission-denied API reads from proof of no protection; branch metadata/rulesets used where available |
| CI truth | Workflow event coverage (PR/push/schedule), actual job vs *overall* conclusion, `continue-on-error`, skipped checks, required-check protection; sample a failure case and compare full-census with selected test paths; exact head SHA |
| Production composition and authority | Trace actual launcher -> app factory -> controller constructors -> JobService, repository/queue, runner and admission gates; exercise disabled-by-default/missing-service paths, not just isolated test fixtures |
| Process/runtime ownership | OS job/process group names, handle semantics, multiple app/worktree instances, test isolation, shutdown/kills, externally owned process protection; Windows-only behavior must get Windows proof or explicit gap |
| Persistence and data integrity | Inventory **every** file/DB store including Learning, UI state, Photo, PromptPacks and LoRAs; write atomicity, fsync/replace, error visibility, torn writes, concurrent readers, corrupt-data behavior and safe rollback; local data never copied into public reports |
| Dispatch, timeouts, cancellation and replay | Retry certainty before/after POST, unknown outcome handling, long-running subprocesses, bounded waits, queue lifecycle transitions, interrupted startup, cancel semantics; avoid tests that invoke real GPU or user runtime by default |
| Security/trust boundaries | Public issue-comment/event workflows, untrusted branch checkout/execution, token permissions and secrets, shell/Windows executable lookup, crafted media/decompression, user paths and external runtime exposure. Check authorization separately from capability |
| Operator feature reachability | Navigate production UI event -> controller -> state -> effect; inspect hidden selectors, fallback values, paging/filtering and disabled controls; compare with intended critical-user outcome |

**Effective enforcement rule:** A test *collecting*, a workflow *showing success*, and a required job *existing* are not equivalent to the contract being mandatory on protected branches. Record all three separately. A doc assertion that a guard is enabled is not proof unless the live composition path actually enables it.

**Highest-risk negative probes:** two simultaneous Windows managers with disposable child processes; startup gate on a restored queue before readiness proof; interrupted Learning JSON write; one failed full-census shard with top-level workflow marked success; a privileged issue-comment from an unauthorized user; missing model-policy information from alternate NJR builders. Non-mutating static/fixture proofs are preferred; live unsafe probes require separate owner authorization.

## 13. Product capability and usage truth matrix (v1.2)

For each material capability record **six distinct answers:** exists in code; reachable from actual GUI; correct under its full contract; useful in completing a defined operator task; used with a grounded frequency/denominator; sustainable at measured maintenance/inference cost. Distinguish `not measured` from `zero`. A History list returning 20 jobs may be correct code but inadequate discoverability; an automation mode available as a string constant but without a visible input is not an operable feature. Include the no-feature, manual/external-backend alternative. Local SQLite/personal usage evidence must remain in private operator storage.

## 14. Independent critique protocol (v1.2)

Pass A maps user journeys, candidate opportunities, accepted PR evidence, and high-signal source paths. **Pass B must use different methods**, not merely reread Pass A summaries: production entrypoint/call-chain trace; GitHub Actions configuration **and actual failed runs**; OS process-name/handle collision audit; persistent-store discovery; AST missing-symbol/broad-exception scan; UI binding/reachability scan; dead-code/import-graph claims with explicit dynamic-use caveats; high-churn and context-cost checks. An ordinary work package need not spawn agents; one independent, method-diverse read-only challenge suffices. Where independently gathered evidence is impossible, state that openly.

Every high-priority claim must have (1) a falsifiable production mechanism, (2) a negative-case proof or specified authorized test, (3) evidence that it is *not already corrected*, (4) impact evidence separate from code evidence, and (5) a least-change option. Preserve a critique ledger: confirmed / partial / refuted / unverified; action accepted / narrowed / deferred; reason; exact source. Explicitly test whether the proposed fix is overengineered (e.g. consolidating every NJR constructor, archiving unique tests, arbitrary line-count ceilings, or changing risk-based CI without comparing actual resources).

## 15. Corrective lessons from the 2026-10-16 external audit

A stronger external audit reported failures that a previous repository-summary-first assessment missed: an alleged absence of effective protection on `main` (**superseded by the correction below**); failed census jobs that still yielded workflow success; public-comment AutoFix executing checkout code in a privileged context; constant Windows job-object naming; the production startup gate not wired in the app factory path; direct JSON writes in Learning; a missing state override method covered by broad exception handling; worker-thread callback fallback; and History/Learning limitations hidden behind implemented code. These are dated source-level findings unless a safe reproduction and observed user impact are established. The external audit's local counts (e.g. user job totals, ratings, torn session file, multi-run CI medians, total mypy errors) have **not** been independently reproduced in this assessment; mark them as externally reported, not current measured fact.

**Governance correction, 2026-10-16:** live branch metadata reports `main`
protected with `required` enforced for non-admins; the empty ruleset list does
not negate branch protection. Protection-detail access is denied (403), so
privileged bypass remains unverified. See the dated report's
[integration evidence](COMPREHENSIVE_ASSESSMENT_2026-10-15.md#2026-10-16-integration-verification-and-governance-correction).
The lesson is to verify effective enforcement and access limitations, not to
assume that protection is absent.

**Priority reversal:** Disposition of verified security/ownership/enforcement failures precedes GPU-180 *residual* analysis. The old 2026-10-15 `GATE-1` #1 ranking is **superseded**, not erased. The October 16 addendum to the dated report contains the corrected priority. Do not automatically adopt a proposed 10-week roadmap, blanket 100%-suite rule, one-compiler rewrite, global abstraction or mass harness deletion. Evaluate evidence and whole-package cost before selection.

## 16. Operational checks before concluding an assessment

- Verify latest branch/remote SHA and whether the local worktree was actually available. Never claim a local repo edit when only remote GitHub reads occurred.
- For any CI claim, inspect at least one run with per-job conclusions and exact source SHA; check whether a GitHub rule **enforces** the check.
- For each safety claim, trace production composition and a negative path end-to-end; avoid a smoke test or PR summary standing alone.
- For persistence, enumerate all durable stores, not just SQLite.
- For user value, prove UI reachability and report task-denominator evidence, or explicit lack thereof.
- If critical controls were not examined, downgrade Comprehensive to **partial**, with precise missing coverage.
- Never use a numerical priority formula to average away a P0 containment problem. Assess effort over full validation and regression work, not one agent's first edit.
- Keep shared repo changes in a short-lived feature branch; docs-only outcomes do not authorize push/merge or deletion. New report does not change governance settings or runtime policy.
