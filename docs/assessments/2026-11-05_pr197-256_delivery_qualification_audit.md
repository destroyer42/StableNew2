# StableNew2 — Dated evidence: delivery, qualification, PR efficiency and model usage

> **Repository preservation note (PR-DOC-EVIDENCE-860, 2026-11-05).** Everything from the next line to the
> "Later verification notes" section is the owner-supplied audit text, copied unchanged (source file
> `StableNew2_PR197-256_Delivery_Qualification_Audit_2026-11-05.md`, SHA-256
> `7a337cb06912baa027f5cf52f864dd2dcf4cb2a3416dfffb1de6f3fce41501ba`). It is a dated evidence baseline for PR delivery,
> qualification and engineering efficiency. It does not supersede `AGENTS.md`, `STATUS.md`, live qualification evidence
> or current source, and it authorizes nothing. The companion policy-enforcement proposal is **not** adopted by
> this record.


**Evidence date:** 2026-11-05 (America/New_York). **Repository:** `destroyer42/StableNew2`.
**Original audit cut:** remote `main` `617a5aea02e7a0afcf10b7c47e780f37f69068b9`; GitHub PRs **#197–#256**, the 60 most recent at the initial audit. **Original PR state:** 59 merged, #256 open.
**Verification update (same local date, after the initial cut):** #256 merged as `a2794072a624ec75572916e403fd1f74afb19fcb`. Its `required`, `full-suite`, and `windows` checks succeeded. The conclusions below retain their original evidence cutoff; a current implementation contract must use the later main and recheck intervening changes.
**Evidence type:** read-only GitHub repository and PR metadata, selected source/test/configuration files, documentation, ledger, coverage register and hosted CI checks. **Not independently inspected:** local Windows checkout/worktrees, physical host state or external sealed acceptance archives. No real model execution or GPU qualification performed. This is a dated finding record, **not `STATUS.md`, an authorization, or a full line-by-line review of every PR diff**.

## Executive conclusion

StableNew2 has delivered substantial application functionality, but source-level implementation and green CI have not consistently become fully demonstrated, independently qualified operator outcomes. The evidence refutes the literal claim that "nothing was executed": earlier Forge and Wan real runs exist, Fun Control achieved a bounded FEASIBLE run, and the operator journeys exercised real Windows input against fake backend boundaries. The higher-confidence product concern is **unclosed GUI-to-artifact qualification, safety/reliability acceptance and quality judgment**. Some high-volume PR work created testing and qualification frameworks without conducting the corresponding physical tests. Work already done should be credited and reused; future work should end in an operator outcome or a concrete, evidence-supported blocker disposition, not another speculative framework.

The 60 PR changed-file lists yielded **49 PRs touching `src/`, eight with tooling/tests but no production `src/` modifications, and three documentation-only**. These are PR-level categories (a source-touching PR may primarily be infrastructure). Approximately 194,226 added and 7,129 deleted lines were observed across PR change lists; these gross figures double-count overlapping changes and are not repository growth. Examples of tool-heavy change sets: #240 +18,507 lines / 0 production source files; #239 +14,681 / 0; #253 +8,709 / 0; #250 +9,195 / 2.

The [golden-path coverage register](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/tools/operator_journey/golden/coverage_matrix.v1.json) records 27 workflows: 6 full desktop journeys, 6 partial, 14 integration-only, 1 untested. Its physical-GPU-through-GUI row is NOT RUN. The [SYSTEM-840 ledger](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/tools/qualification/system840/ledger.v1.json) has 50 entries: 0 QUALIFIED; 10 PARTIALLY QUALIFIED; 4 FEASIBLE; 22 NOT TESTED; 10 HOLD; 2 UNSUPPORTED; 1 NO-GO; 1 INCONCLUSIVE. **The ledger's `QUALIFIED` threshold is strict**: prior driver-only real runs do not automatically satisfy exact-current operator-GUI and human quality criteria ([rules](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/runbooks/qual_system_840.md#L22-L34)).

## 1. Partially delivered capability and missing evidence

| Area | Implemented / positively observed | Remaining gate, not to be inferred from CI |
|---|---|---|
| Forge + SDXL | Default WebUI image path; prior real canonical driver output; prompt packs, profiles, queue and history | Frozen **real GUI** PromptPack -> Preview -> queue -> dispatch -> artifact -> History, resource/restart evidence and operator quality review |
| FLUX.2 Klein 4B FP8 | Exact Forge profile and some physical evidence | Current exact model/runtime GUI passage, safety, effectiveness and comparison |
| FLUX.2 Klein Base 9B | Explicit resource-risk refusal | NO-GO remains unless resources, policy and authorization change |
| Z-Image Turbo FP8 | Exact implementation and one observed generation | Clean shutdown/repeated stability inconclusive; no new physical run authorized |
| Qwen Image / generic image families | Prompt/model compatibility research and policy structures | Exact accepted image backend and production profile; distinct from GGUF Qwen AI Assist |
| ADetailer/upscale/ControlNet | GUI, reference maps, compilation | Real generation and output efficacy/quality for selected stages and images |
| Review inpaint/outpaint, Smart Review | Queue-first editing; SAM/Florence contained-CPU advisory surface | Real masked image quality, preserved original pixels, model CPU-forward resource/quality verification |
| History / Learning | Iterate, Compare with Parent, matrices, controlled studies, profile publication | Full physical parent-child path, meaningful controlled ratings and demonstrated reuse/payoff |
| Wan TI2V 1.2/1.3 | Approved Comfy production video; prior real runs and multi-shot sequences | Current GUI golden-path canary, identity/quality review and exact-source applicability |
| Native SVD | Accepted production video backend | Fresh campaign minimal native SVD clip + optional postprocess qualification |
| Fun Control 5B | Experimental integration; Motion Library, Blender conversion; #246 physical third run 14/14 FEASIBLE | Independent character retarget, visual-quality review, repeatability, safe admission; FEASIBLE is not promotion |
| Wan Animate-2 | Experimental, some partial evidence | Representative-host and quality/reliability completion |
| Wan A14B | Prior physical attempt INCONCLUSIVE | Verified teardown and child-process memory plus renewed exact owner budget |
| Movie Clips / Storyboard | Queued CPU assembly and persistent storyboards; prior accepted multi-shot sequence runs | Whole saved/reopened operator path, selective suffix regeneration separately unimplemented |
| Offline AI Assist | Prompt Suggest wired but disabled, bounded offline child and qualification contracts | Protected-interpreter ETW canary, model-specific S2+/D12 approvals and real quality/safety evaluation; six GGUF candidates not tested |

Important receipts: [model profiles, lines 27–60](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/Subsystems/Image/MODEL_PROFILES.md#L27-L60); [production vs experimental video, lines 15–29](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/Subsystems/Video/VIDEO_PIPELINE.md#L15-L29); [STATUS holds, lines 124–135](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/STATUS.md#L124-L135); [#246 Fun Control physical three-attempt record](https://github.com/destroyer42/StableNew2/pull/246); [#249 Storyboard implemented](https://github.com/destroyer42/StableNew2/pull/249); [#254 golden-path fixes](https://github.com/destroyer42/StableNew2/pull/254); [#233 LFM3 contract](https://github.com/destroyer42/StableNew2/pull/233); [#235 qualification harness](https://github.com/destroyer42/StableNew2/pull/235).

**Execution-tool discontinuity:** [SYSTEM-840 coordinator `UnwiredAdapter`, lines 76–84](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/tools/qualification/system840/coordinator.py#L76-L84) deliberately refuses physical dispatch. [Runbook lines 98–106](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/runbooks/qual_system_840.md#L98-L106) say real physical harnesses remain separate. A coordinated plan is not a physical qualification. Reuse existing executable harnesses before authoring a new adapter.

## 2. Testing, PR efficiency and maintenance cost

1. **Maintain strong CI:** current `required`, `full-suite` (three shards) and `windows` merge gates are meaningful; ordinary Python CI does not prove real GPU/Forge/Comfy/SVD behavior. The [testing authority](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/Subsystems/Testing/TESTING_AND_CI.md#L17-L45) distinguishes docs-only cheap routing and executable full census.
2. **Load-sensitive local tests remain:** #251, #252, #254 report Tk timing, load and ambient WebUI/collision issues that pass alone. #254 hosted checks later all passed. This is not proof of a current hosted regression. Run controlled baseline/branch reproduction; repair synchronization/isolation, not assertions or CI strength.
3. **Previously fixed test problems must not recur as backlog:** [Phase B1 slimming evidence, lines 13–22 and 50–55](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/Subsystems/Testing/PR-DEVEX-TEST-SLIM-120_Phase_B1_Deterministic_Test_Slimming.md#L13-L22) reduced its focused set 185.1 s to 14.8 s and removed the pytest-only generation hook. Other test-mode branches require case-specific proof before changing.
4. **Tooling multiplication:** #239, #240 and #253 added large measurement/coordination packages without new production source; retained harnesses have named importers and retirement conditions [qualification inventory](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/tools/qualification/README.md#L19-L40). Avoid another framework unless existing tools demonstrably cannot fulfill a required outcome.
5. **Weighted sharding (#256):** initial audit recorded the PR open; subsequent exact-head checks and merge to `a2794072` succeeded. One observed earlier slowest shard 637 s versus #256's 585 s (8.2% difference), but revisions differed; do not attribute all improvement to scheduling without comparable repeats. This is a useful optimization, not a cure for flaky isolation.

## 3. Token and coding model calibration

| PR | Expected cache-read -> observed | Expected output -> observed | Interpretation |
|---|---|---|---|
| [#237](https://github.com/destroyer42/StableNew2/pull/237) | 2M -> 19.4M | 20k -> 50.6k | Long context plus publication/CI work; no PR repair pass; cache 9.7x |
| [#236](https://github.com/destroyer42/StableNew2/pull/236) | 5M -> 16.2M | 30k -> 76.2k | Retained context, repeated measurement and review; cache 3.2x |
| [#239](https://github.com/destroyer42/StableNew2/pull/239) | about 12M -> 29.8M | about 60k -> 269.5k | Huge harness, shared tail and reviewer not fully counted; 4.5x output |
| [#242](https://github.com/destroyer42/StableNew2/pull/242) | about 10M -> 33.3M | about 66k -> 171.2k | Fresh independent reviewer and repair/reverification; cache 3.3x |
| [#249](https://github.com/destroyer42/StableNew2/pull/249) | 12M -> 12.75M | 70k -> 64.8k | Close forecast; actual GPT-6.1 Sol High completed despite XHigh recommendation |

These are heterogeneous PR-body reports, **not normalized full-package measurements**. Some shared context, missing reviewer usage, imprecise start timestamps and incomplete closeout logging limit causal comparisons. [AI_MODEL_SELECTION.md lines 9–34](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/AI_MODEL_SELECTION.md#L9-L34) requires pre-discovery timestamps plus every participating session and explicitly states `--since-commit` is post-commit, not a full-package measure. Broad High/XHigh recommendations occur because the [current matrix](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/AI_MODEL_SELECTION.md#L36-L60) labels normal substantial known-architecture work High and difficult cross-file work XHigh. The calibration rule at lines 69–86 should be applied to comparable packages rather than escalations justified only by file count.

Strongest mechanisms: accumulating per-turn context rereads; underestimated framework/review output; separate reviewer cold starts; CI/debugging churn; incomplete scope definition and measurement boundaries. Not established: intrinsic inadequacy of Medium models or one provider's token-cost superiority. Counterexamples include [#238 Medium success](https://github.com/destroyer42/StableNew2/pull/238) and #249 High successful against XHigh recommendation.

## 4. Current-truth drift requiring disposition

- [STATUS lines 82–85](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/STATUS.md#L82-L85) still names persistent Storyboard as upcoming after #249 merged. Update active outcome in place.
- [STATUS lines 124–135](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/STATUS.md#L124-L135) describes an earlier general owner lifting of GPU hold; [qualification inventory lines 3–5](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/tools/qualification/README.md#L1-L5) calls physical runs held; [roadmap lines 90–96](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/audits/2026-10-26_product_capability_roadmap.md#L90-L96) explicitly requires a fresh named authorization. Treat qualification runs as **not authorized without current explicit owner consent**, regardless of old general hold language.
- [AGENTS lines 39–43](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/AGENTS.md#L39-L43) and [VIDEO_PIPELINE 19–29](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/Subsystems/Video/VIDEO_PIPELINE.md#L19-L29) approve Wan TI2V 1.2/1.3; [qualification inventory line 28](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/tools/qualification/README.md#L27-L29) still calls Wan experimental awaiting promotion.
- SYSTEM-840 ledger source snapshot `d76d1acd` predates #254/#255/#256 and must be reconciled to current live catalog and accepted evidence. A newer source SHA alone does **not** invalidate compatible evidence; do not auto-promote or revoke status.
- [STATUS line 135](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/STATUS.md#L135) says LFM3 needs a contract-driven harness, though #235 exists; model qualification remains held.
- [GUI-850 decision handoff](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/docs/research/stablenew-experience/DECISION_HANDOFF.md) says B2/B3/B5 have not run, while #255 includes the later simulated runs against an older code snapshot; report history rather than edit dated evidence silently.
- [Learning runner stub](https://github.com/destroyer42/StableNew2/blob/617a5aea02e7a0afcf10b7c47e780f37f69068b9/src/learning/learning_runner.py#L1-L15) still returns placeholder results. Do not equate with production Learning path or delete without import/reachability proof.

## 5. Recommendations ranked by product impact

1. **Close one existing, safe, authorized operator-golden-path qualification** (beginning with existing Forge SDXL IMG-01 evidence candidate); do not physically run until explicit, current plan-level authorization and device-loss preflight. Exit: sealed GUI intent->NJR->queue->backend->artifact/History proof with telemetry, teardown and human quality rating, or specific STOP/NO-GO.
2. **Finish existing CPU-only and previously proven video/editing payoffs** (Movie Clips, Storyboard reopening, History iteration) with direct operator acceptance; reuse prior Wan 1.3.0 evidence when exact applicability is demonstrated. No new speculative backend.
3. **Make current truth and qualification ledgers accurate** as part of the next accepted outcome, not an expansive research cycle. One source of rules (`AGENTS.md`), one status (`STATUS.md`), one qualification ledger (`system840`).
4. **Reproduce and repair local Tk/timing flakes** on current and pristine baseline with controlled load and clear classification, avoiding test weakening.
5. **Unblock exactly one Offline AI candidate** only after protected ETW/explicit model authorization, rather than attempting a six-model expansion or new executor.
6. **Enforce fresh-session and measured-usage calibration** using existing AI model selection rules; try Medium for eligible bounded packages with comparisons.
7. **Retire unnecessary qualification/test harnesses** only with importer proof, preserved historical verdict and relevant ratchet update; no deletion quota.

## 6. Measurable changes / falsification

| Signal | Observed baseline | Proposed validation |
|---|---|---|
| Strictly qualified capabilities | 0/50 in dated ledger | At least one properly evidenced, owner-reviewed new verdict; no status change from CI alone |
| Physical GUI golden-path accepted | 0 recorded in 27-workflow register | One sealed, independently verified journey on exact approved plan (or named safety HOLD) |
| Full desktop journey coverage | 6/27 | Add only high-value missing complete journeys, count independent from physical quality |
| Current qualification truth | ledger source `d76d1acd` at original cut | Reconcile against actual source, cite `applies_to`, no unsupported auto-status promotion |
| Load-sensitive flake repair | #254 local nine failures, individually passing; hosted green | Controlled A/B same source, no unexplained local-versus-hosted failures across repeated runs |
| Token >3x estimate | Documented in several sampled PRs | Record comparable complete scopes, investigate every threshold breach, and test one-step tier changes per canonical rule |
| Weighted census slowest shard | 637 sec earlier vs 585 sec #256 PR | Same-source repeated hosted samples before claiming effect size |
| Documentation drift | Specific contradictions listed above | Zero unresolved contradictions in current authority docs, dated reports retained |

## 7. Adversarial critique and limits

- **“Nothing executed” is false.** Evidence exists for real historical Forge/Wan, physical Fun Control and simulated GUI journeys. Yet those do not satisfy every precise production-GUI/quality qualification criterion.
- **“Every merged PR is user value” is false.** Production source changes are not adoption/quality proof; some code changes implement instrumentation or policy.
- **“No qualified means nothing works” is false.** Ledger criteria are deliberately stricter than successful output. Do not conflate production approval with this campaign's current qualification.
- **“CI is broken” is unsupported.** Selected current hosted checks passed. Local load instability remains a hypothesis to reproduce; do not weaken the full census.
- **“Use the biggest model for every PR” is unproven.** Usage forecasts depend on clean boundaries, session freshness, actual repair rates and comparable task classes. Model family change is not justified by a few confounded cases.
- **“A newer ledger source SHA means every previous physical run is stale” is false.** Identity/version/source applicability and changed runtime behavior matter more than bare chronology.
- **“Add one more qualification platform” is not justified.** Existing SYSTEM-840 coordinates evidence; retain harnesses perform the physical work under separate authority. Demonstrate the missing path before adding infrastructure.

**Confidence:** high for PR merges, changed-file categories, currently committed ledger statuses and CI policy; medium for exact next highest-value capability and token overrun mechanisms; lower for physical quality and root cause of local load failures until local evidence is independently verified. The audit is not a full eight-control production/Windows persistence trace or physical requalification and must not be labelled a fully verified Comprehensive source audit.

## 8. Source of authority and use of this document

Current implementation, exact branch/SHA, `AGENTS.md`, `STATUS.md`, subsystem and testing authority outrank this dated evidence. Reuse as a *historical diagnostic baseline*, not a plan or merge authorization. Decisions about safety, production support, hardware, adoption and protected Git actions remain with the owner. The companion implementation proposal describes process hardening and should be converted to bounded packages only after a current-source check.

## Later verification notes (added 2026-11-05 by PR-DOC-EVIDENCE-860; not part of the original audit)

Checked on branch `docs/pr197-256-evidence-truth-860` from `main` `a2794072a624ec75572916e403fd1f74afb19fcb` (equal to
`origin/main` at the time of the check). These notes add verification; they do not rewrite the dated findings above.

- **Snapshot identities confirmed.** `617a5aea02e7a0afcf10b7c47e780f37f69068b9` is the merge commit of #255 (GUI-UX-850
  research). #256 merged as `a2794072a624ec75572916e403fd1f74afb19fcb`; the diff from `617a5aea` to `a2794072` touches
  only CI census tooling and its tests, the CI workflow and testing docs (11 files), so no product, ledger or qualification source changed between
  the original cut and this check. Every repository path in the permalinks above exists at `617a5aea`.
- **Counts re-derived from source at `a2794072`.** `tools/qualification/system840/ledger.v1.json` has 50 capabilities
  with the statuses listed in the executive conclusion. `python -m tools.qualification.system840 ledger --check --live`
  (offline, read-only) exits 0 and reports no drift against the live catalog and registry. The ledger's last change is
  `4fe62fa6` (PR-QUAL-SYSTEM-840); its recorded source snapshot is still `d76d1acd`. No verdict was changed here; any
  ledger reconciliation belongs to its own package. The golden coverage matrix (v1.2.0) still has 27 workflows:
  6 full desktop journeys, 6 partial, 14 integration-only, 1 untested, and physical GPU NOT RUN.
- **Section 4 dispositions in this PR.** The `STATUS.md` Storyboard line (#249), the AI Assist harness line (#235;
  physical inference, S2+ and the protected-capture canary stay open) and the GPU-hold wording were corrected in place;
  the retained-harness inventory in `tools/qualification/README.md` now states the approval of Wan TI2V-5B 1.2.0/1.3.0
  and separates the 2026-10-18 general hold lift from qualification authorization. The GUI-850 research README now
  acknowledges the executed B2/B3/B5 baseline; `DECISION_HANDOFF.md` is left as the record of what was pending at its
  own decision point.
- **B2/B3/B5 applicability.** The executed B2/B3/B5 baseline measured code at `ed1e989f` (PR #253). #254 (golden-path
  reliability repairs) merged after that SHA, so B2's failures are not evidence about current `main` without a new run.
- **Not changed or not verified here.** The Learning runner stub, the local Windows evidence archives, physical host
  state and the token figures quoted from PR bodies were not re-examined. No physical, GPU, model or runtime action was
  taken.
