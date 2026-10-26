# StableNew — Product Capability Assessment and Forward Roadmap (2026-10-26)

**Status:** Owner-selected product-priority direction, not new code/merge/physical-runtime authorization. **Evidence:** remote main at 2142e9d95aceaa72c152a89e1a27a0c83d226a5e (October 26, 2026), plus current PR and CI metadata. Local Windows checkout, assets, live Tk UI and physical devices **not examined**. This is a **partial v1.2 Comprehensive assessment**, not an all-controls-green certification.

**Important later discovery:** [PR #223, IMG-EMBED-720](https://github.com/destroyer42/StableNew2/pull/223) already fixes the aesthetic-embedding syntax defect highlighted in the original October 26 report. At this verification point it is open, with successful required/full-suite/Windows checks, and not merged. The requested IMG-EMBED-730 must **not duplicate** it.

## Executive decision

StableNew is beyond its initial MVP. The best next work is to demonstrate complete, reliable value from the large recent investment in model profiles, PromptPacks, History, Learning, GUI, editing and video. The current primary package is [WF-740 model/profile/Learning round-trip](../work_packages/WF-740_model_profile_learning_roundtrip.md). The existing [#223](https://github.com/destroyer42/StableNew2/pull/223) owns the aesthetic syntax repair; [IMG-EMBED-730](../work_packages/IMG-EMBED-730_conditional_post_720_fidelity.md) is a conditional follow-up only for a distinct reproduced gap after #223's disposition.

The 2026-10-16 [repository audit](2026-10-16_repo_audit_and_roadmap.md) remains historical baseline and structural inventory, not today's open-task log. Current source/SHA, [AGENTS.md](../../AGENTS.md) and [STATUS.md](../../STATUS.md) remain above this dated decision report. The owner-accepted video roadmap (2026-10-20) and GUI audit (2026-10-22) remain specialist evidence, rechecked before every new package.

## Verified evidence and scope limits

- Main 2142e9d9 had successful [required/full-suite/Windows CI](https://github.com/destroyer42/StableNew2/actions/runs/40365723929). Main was protected in branch metadata; detailed privileged bypass setting was not accessible. At the first scan there were zero open PRs; #223 appeared afterward and is open with green required, full-suite and Windows checks. Neither green CI nor a merged PR proves live operator visual quality.
- Canonical execution remains Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History. Fresh Run Now and Send Job are queue-first. Replay creates lineage. External A1111/Forge/Comfy is never adopted, killed or restarted. An ambiguous dispatched POST is not replayed.
- AGENTS.md **now authorizes** native SVD XT and individually approved Comfy video workflows for production; TI2V-5B 1.2.0/1.3.0 are approved. Older SVD-only project material is superseded. Wan A14B physical feasibility ran three dispatches but froze an **INCONCLUSIVE** technical verdict (teardown verification missing), not a production promotion.
- [PR #208](https://github.com/destroyer42/StableNew2/pull/208) added versioned Research/Custom/Learning generation profiles and saved startup defaults; [#213](https://github.com/destroyer42/StableNew2/pull/213) enabled explicit immutable Learning profile publication; [#210](https://github.com/destroyer42/StableNew2/pull/210), [#212](https://github.com/destroyer42/StableNew2/pull/212) and [#222](https://github.com/destroyer42/StableNew2/pull/222) improved guided Learning, independent baselines and Prompt x Model comparison. No real live Windows end-to-end round-trip was independently run for this assessment.
- [#201](https://github.com/destroyer42/StableNew2/pull/201) added Iterate from History, while parent/child visual compare is still out of scope. Masked editing, outpaint, reference-map ControlNet and Smart Review are implemented; real visual/model-quality qualification remains deferred.
- Video has Make Video, in-app playback, Movie Clips, one-job multi-shot sequences, ledger and strict resume. Persistent Storyboard, FLF control and selective shot rerender remain. Offline AI Assist Suggest is wired but disabled until a qualified offline installation; protected ETW/model qualification is still pending.
- The October 16 audit's claims that main was unprotected, CI full census informational and Windows absent are obsolete. Its architectural risks (composition, multiple NJR producers, large controllers, tested vs production divergence) remain candidates requiring fresh proof.

## Critical-control ledger (eight surfaces)

| Control | Current evidence | Unverified / next step |
| --- | --- | --- |
| Governance | main protected; PR workflow | Detailed admin/bypass enforcement |
| CI | required, full-suite and Windows all green on assessed SHA | Prove hermetic tests, no ambient WebUI or real-time wait reliance |
| Production composition | Canonical JobService/NJR/SQLite/runner path; stage-handler extraction merged | P3-2 single composition root still owner-gated |
| Windows process ownership | Process isolation, runtime handoff and startup gates in production docs | Physical restart/device-loss proof and local ownership tests |
| Every durable store | SQLite authority, atomic writes, immutable profile revisions, sequence ledger | Complete store-by-store negative/fail-open audit; backfill decisions |
| Dispatch/cancel | Ambiguous POST never retried, backend-scoped hold and Comfy cancellation | Native SVD postprocessing/cancellation edge behavior |
| Privilege/untrusted | Hash-pinned assets, bounded workers and offline AI safeguards | Smart Review real inference and AI elevated ETW canary/model qualification |
| GUI reachability | GUI task grouping, Tk boundary extractions, responsive Review/Photo Optimize | Live Windows/DPI, latency, accessible full journeys |

This ledger is an **inventory with open gates**, not an independent re-execution of all controls. A fresh v1.2 Comprehensive audit requires a separate method-diverse adversarial pass and all durable store/production composition traces.

## Capability/use map — six dimensions

The six-factor evaluation is: implementation; user reachability; executed correctness; installed-resource readiness; runtime/physical qualification; demonstrated operator payoff. The last three cannot be inferred from merged source or CI.

| Journey | Implemented | Remaining user-facing value/evidence |
| --- | --- | --- |
| Model-aware generation | Forge default, A1111 rollback, exact Klein and Z-Image slices, Research/Learning/Custom profiles and startup defaults | Broader source-backed recommendations, real profile->Preview->queue parity, Z-Image repeated-run stability |
| Prompt and conditioning | PromptPacks, optimizer, adaptation, Matrix, LoRA asset UI, guided Canny/depth/pose ControlNet | Actual effective outbound prompt evidence and ControlNet/image quality; current aesthetic syntax fixed by pending #223 |
| Edit and curate | Quick Edit/Managed Photo Set, masked inpaint, outpaint, Smart Review advisory | Physical output and SAM/Florence real-model quality, before/after comparison |
| Learn | Design/Preview/Run/Compare/Rate, controlled one-variable, two-axis, LoRA/Embedding/Prompt Slot/Prompt x Model studies and publication | End-to-end profile payoff, saved rating usage, provenance validation; descriptive studies correctly do not auto-recommend |
| Reuse history | Search/pagination, replay, single-image Iterate, parent lineage | Parent/child visual and effective-recipe diff, richer search |
| Video | SVD and approved Wan, Movie Clips, sequence ledger and checkpoint/resume | Persistent Storyboard, selective shot rerender, end-frame control, quality/identity assessment |
| Offline assistance | Prompt Suggest and bounded Smart Review CPU children | Model and installation qualification gates, safe operator evaluation |

## Current roadmap phase adjudication

- **Phase 0 and Phase 1:** safety governance, main/CI, pinned development environment, Windows lane and ratchets implemented. Do not reopen on stale historical claims.
- **Phase 2:** compact STATUS, AGENTS as rules authority, generated CODE_MAP and living subsystem documents done; retained qualification harnesses require their named retirement evidence.
- **Phase 3:** contained processes, typed Comfy transport/cancellation, provenance identity, queue discipline and first dead-code removal landed. **P3-2 single composition root and durable CANCELLING remain open owner decisions.**
- **Phase 4:** P4-1 stage handlers and GUI-SEAM-700/710/720 implemented; unified compile core, typed stage settings and broader Learning controller extraction are unimplemented candidates.
- **Phase 5:** considerable image/video/History/Learning value has been implemented early. Reassess remaining operator gaps rather than re-run P5 tasks already delivered.
- **Qt:** [#215](https://github.com/destroyer42/StableNew2/pull/215) recommends NO-GO/DEFER; continue Tk and toolkit-neutral seams until measured need supports migration.

## Priority-ordered portfolio and dependencies

Safety-gating read-only GPU/device-loss analysis runs alongside discretionary work and overrides it if a new confirmed threat appears. The remaining sequence is ordinal judgment, not fabricated ROI scoring.

| Order | Work package | Outcome / dependency |
| --- | --- | --- |
| Current overlapping repair | **IMG-EMBED-720 #223** | Already fixes aesthetic outbound notation; review accepted diff/CI and obtain separate owner merge decision; **no duplicate PR** |
| 1 | **WF-740** | Verify and narrowly repair model -> working settings -> Preview/NJR -> queue -> controlled Learning -> explicit profile reuse; [full contract](../work_packages/WF-740_model_profile_learning_roundtrip.md) |
| Conditional | **IMG-EMBED-730** | Only a separately proven post-720 mismatch in Preview or actual TI evidence; [NO-GO/conditional contract](../work_packages/IMG-EMBED-730_conditional_post_720_fidelity.md) |
| 2 | TEST-HERMETIC-750 | Test-only production branches and ambient retries/endpoint dependencies, selected by fresh reproduction |
| 3 | HISTORY-610B | Parent-child media and effective-recipe comparisons on existing lineage |
| 4 | VID-STORYBOARD-350 | Persistent ordered shot plans, selective rerender, anchored shot boundaries using existing one-job sequence authority |
| 5 | VID-QUALITY-351 | Controlled motion, temporal quality, consistency and human preference acceptance before model promotion |
| 6 | GUI-COMPLETE-760 | Remaining real DPI/keyboard/reachability and Tk-thread I/O, not wholesale rewrite |
| Architecture decision | P3-2 | One composition root; **material owner approval first**, followed by golden wiring/ownership tests |
| Architectural candidates | P4-2, P4-3, P4-4 | NJR compiler policy parity; split Learning from Tk; typed stage settings, bounded parity packages |
| Conditional expansion | MODEL-EDIT-800, AI-QUAL-115, VIDEO-MODEL-360 | Qualified Qwen/Flux editing, safely enabled offline AI, new video models only after actual resource/quality proof |
| Release maturity | RELEASE-900 | Fresh install, readiness, restart/recovery, version/license and documented operator journey proof |

### Waves and measurable product exits

1. **Existing-work payoff:** WF-740 with a legitimate no-code PASS if all contracts hold; review #223 rather than building the same syntax fix. Exit: model/profile and Preview/NJR admit equality, explicit qualified Learning publication/reuse.
2. **Complete image and video journey:** HISTORY-610B, editing acceptance, saved multi-shot Storyboard and selective shot reuse. Exit: input -> iteration -> compared output and saved shots -> checkpoint -> playable movie.
3. **Risk-reducing architecture:** P3-2 only after decision, then P4-2/P4-3/P4-4 via parity gates. Exit: single service authority and fewer cross-cutting model/GUI files, no behavior or test regressions.
4. **Qualified expansion:** broader exact model families, offline AI, advanced video after deliberate resource/safety/visual promotion evidence. Exit: new production capability proven on target and consented.
5. **Release:** reproducible Windows install, clear missing assets, reliable recovery, version/license and bounded start-to-output acceptance.

No assumed weeks or pseudo-percent-complete bars. One coherent PR and one top-level agent session per outcome; PR gate and review are fixed costs, so avoid artificial micro-PRs but stop at distinct owner decisions.

## Holds, owner choices and conflict handling

- Physical device-loss root cause remains unresolved (STATUS reports repeated events and quarantine); no new physical GPU/model run or WebUI/Comfy restart without fresh explicit owner authorization even though STATUS notes the prior general hold lifted October 18. Z-Image stability work specifically remains not authorized.
- Offline AI Assist is not qualified or enabled; model runtime ETW/safety/corpus tests remain owner-gated. Smart Review real model inference, mask/caption usefulness also unqualified.
- P3-2 composition, CANCELLING status, moving executor to image_backends, new NJR SourceKind, destructive user-data migration, releasing/training and licensing/version each require explicit owner decision.
- Learning experiment snapshot dedup is forward-only decided; historical backfill and deleted-artifact job pruning require separate evidence and authorization. Character Training stays held.
- Protected actions: branch publication/open PR is separate from merge to main, tag/release, force push, destructive migrations and secrets changes, each needing explicit current target authorization.
- The latest STATUS and source always prevail; newly merged repairs may render an entire proposed package unnecessary. Do not turn the dated report into an append-only PR diary.

## Independent challenge and stop logic

**Challenge A:** WF-740's functions may already be proven end-to-end. Build an acceptance coverage grid first and seek one falsifying gap; if none exists, accept with no source change. **Challenge B:** a newly evidenced current GPU safety threat outranks feature delivery. **Challenge C:** a whole-application rewrite or Qt migration would introduce more risk than measured value; prefer extracted toolkit-neutral ownership. **Challenge D:** more Learning modes and new models are attractive but don't show actual payoff without operator-tested iteration and rating use. **Challenge E:** initial IMG-EMBED-730 planning was superseded by #223; the correct decision is to reuse implementation rather than spend another CI cycle.

## Next action

Select the current source and exact SHA; finish review/disposition of #223 through its existing PR lane, without implicitly merging it. Execute WF-740 as the next newly authorized bounded implementation package; if actual data supports only a small residual embedding UI/readback defect, first make an independent acceptance case before activating IMG-EMBED-730. Keep STATUS.md's current-state and next-action lines aligned with this selected priority, never with old candidate lists.
