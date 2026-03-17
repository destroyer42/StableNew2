# StableNew – Revised Top 20 Recommendations After Repo Review

## Method and confidence

This list is based on:
- direct inspection of the supplied repository snapshot
- review of the canonical architecture/governance documents and subsystem discovery docs
- inspection of key implementation modules in `src/`
- a lightweight `pytest --collect-only -q` sanity check in this environment, which collected **1,832 tests** and reported **102 collection errors**

I did **not** run the full execution suite end-to-end in this environment, so priorities are grounded in structure, code shape, documented architectural intent, and collection-time health rather than a full runtime verification.

## Overall BLUF

The repo is strong enough to support serious forward progress, but the next phase should **not** be “add more features everywhere.”  
The best path is:

1. finish the **v2.6 canonical migration**
2. remove **legacy/compatibility drag**
3. harden the **execution and recovery path**
4. make the **tests authoritative again**
5. then complete the highest-leverage product surfaces: **reprocess**, **learning loop**, and **video**

The biggest meta-risk is building new capability on top of partially migrated internals.  
That would create a repo that looks feature-rich but gets slower, less deterministic, and harder to trust.

---

## 1) Consolidate to one txt2img execution path

**BLUF:** Make `run_txt2img_stage()` / NJR execution the only txt2img path, migrate the CLI to it, and delete the older duplicate path.

**Why it is this high:** The repo already documents that there are two txt2img paths with different history/manifest behavior and that the production path is the stage-based one. That kind of duplication is exactly the sort of thing that causes “fixed it five times and it still breaks” regressions.

**Mini research dive / evidence from repo review:**
- The repo includes a dedicated debt analysis on duplicate txt2img execution paths.
- The production queue/GUI path is stage-based and NJR-oriented.
- The older path still exists largely for CLI/backward compatibility.
- The runner/executor surface is already big enough that keeping two “mostly similar” generation paths will continue to create metadata drift.

**Critical appraisal:**
This is a classic high-value cleanup item because it reduces future bug surface more than it adds visible capability. The weakness is that users may not immediately feel a visible UX win, so this can get deprioritized. That would be a mistake.

**2nd / 3rd / 4th order effects:**
- 2nd order: manifests, output naming, and model/vae recording become easier to reason about.
- 3rd order: tests shrink because there are fewer permutations to support.
- 4th order: future features like reprocess, learning, and video have a cleaner place to plug in.

**Caveats:**
Do not just delete the old path blindly. First rewrite the CLI against the canonical runner and add regression tests proving parity for the supported use cases.

---

## 2) Finish the NJR-only migration across queue, history, and controllers

**BLUF:** Remove remaining compatibility pathways around `Job.pipeline_config`, payload fallbacks, and legacy adapter behavior so the queue and history layers are truly NJR-first end to end.

**Why it is this high:** The canonical docs are very explicit: NJR is supposed to be the only execution format. The implementation still contains compatibility fields and fallback behavior. That gap between doctrine and code is where subtle bugs live.

**Mini research dive / evidence from repo review:**
- `queue/job_model.py` still carries compatibility semantics around `pipeline_config`.
- There are comments in queue/history code explicitly calling out legacy compatibility.
- The architecture and governance docs treat alternate job formats as invalid.
- Collection-time test debt suggests the migration is not fully complete in the surrounding test ecosystem.

**Critical appraisal:**
This recommendation is strong because it aligns the code with the project’s own declared architecture. The weakness is migration risk: if you hard-cut too early, you can break tools, replay, or older artifacts.

**2nd / 3rd / 4th order effects:**
- 2nd order: replay and history become more trustworthy.
- 3rd order: controller and GUI code stop needing “if old shape then...” branches.
- 4th order: AI agents and human contributors have a much smaller mental model to hold.

**Caveats:**
Treat this as a staged migration with instrumentation. First log every fallback usage, then drive the count to zero, then delete the shims.

---

## 3) Make the canonical stage contract match the real preferred flow

**BLUF:** Normalize the repo, docs, UI defaults, and tests around the actual preferred image pipeline: `txt2img → img2img (ADetailer) → final upscale`.

**Why it is this high:** Right now, part of the repo’s mental model still appears to reflect an older SDXL/refiner/hires-fix era. That causes drift between how the product really works and how contributors think it works.

**Mini research dive / evidence from repo review:**
- Your correction is consistent with the code direction and current usage intent.
- The README still frames the system as V2.5 and references older stage emphasis.
- The runner and payload logic still carry refiner/hires paths, but those are no longer the preferred default flow.
- Stage types and stage sequencing are central enough that the “canonical happy path” must be unambiguous.

**Critical appraisal:**
This is not the same as deleting refiner and hires support. The stronger recommendation is to demote them from the default narrative and make them explicitly advanced/legacy-leaning paths unless a real use case justifies keeping them prominent.

**2nd / 3rd / 4th order effects:**
- 2nd order: onboarding gets easier.
- 3rd order: fewer UX decisions are made around outdated assumptions.
- 4th order: learning and reprocess features can focus on the stage chain that actually matters.

**Caveats:**
Do not conflate “not preferred” with “must be removed.” Preserve support where it still has value, but isolate it behind advanced controls and non-default tests.

---

## 4) Harden WebUI recovery so hangs and partial failures are first-class, not edge cases

**BLUF:** Expand crash recovery to handle timeouts, HTTP 500s, pre-stage readiness checks, and per-image degradation instead of treating only connection-refused cases as restart-worthy.

**Why it is this high:** When the external engine is unstable, the whole product feels unstable, no matter how good the architecture is.

**Mini research dive / evidence from repo review:**
- The repo already has a WebUI recovery analysis doc identifying gaps.
- The current detection logic is narrower than it should be.
- The runner/client layers already have retry structure; they just need a broader and more coherent recovery policy.

**Critical appraisal:**
This is one of the highest user-value items in the entire repo. The weakness is that retry logic can easily turn into “infinite maybe-recovery” behavior unless bounded carefully.

**2nd / 3rd / 4th order effects:**
- 2nd order: fewer “mystery failures” and less wasted generation time.
- 3rd order: queue statistics become more meaningful because job failure categories are more honest.
- 4th order: once recovery is trustworthy, you can support longer unattended runs and larger batches with more confidence.

**Caveats:**
Bound retries aggressively and make the failure envelope explicit. Recovery without good observability often just converts hard failures into slow failures.

---

## 5) Restore the test suite to authoritative status

**BLUF:** Spend a focused tranche getting collection to green, retiring obsolete tests, and making the suite a real signal again before adding many more major features.

**Why it is this high:** In this environment, `pytest --collect-only -q` reported **1,832 tests collected with 102 collection errors**. That is a serious health warning even if many core tests still pass.

**Mini research dive / evidence from repo review:**
- The repo has multiple test-analysis and cleanup documents.
- Older docs mention 15 collection issues earlier; the current snapshot shows a larger collection problem.
- Many errors are likely migration-related rather than proof of runtime breakage, but that still means the suite is not currently acting as a reliable guardrail.

**Critical appraisal:**
This is a classic “boring but essential” recommendation. The weakness is opportunity cost: it can feel like a pause on feature work. The better framing is that it accelerates feature work by restoring trust.

**2nd / 3rd / 4th order effects:**
- 2nd order: PRs get smaller because people stop hedging against unknown regressions.
- 3rd order: architecture decisions become enforceable.
- 4th order: LLM executor performance improves because the repo’s feedback loop gets cleaner.

**Caveats:**
Do not pursue “all green at any cost.” Some tests should be rewritten; some should be archived; some should be deleted. The objective is **good signal**, not preserving every historical test file.

---

## 6) Unify history, manifests, and replay around one durable artifact contract

**BLUF:** Define and enforce one canonical output/manifest contract for image, reprocess, and video jobs, then make history/replay consume only that contract.

**Why it is this high:** Output metadata is the glue between execution, history, learning, replay, and debugging. Inconsistent artifact semantics multiply downstream pain.

**Mini research dive / evidence from repo review:**
- There are multiple docs around manifest integrity and history schema.
- The duplicate txt2img path analysis already showed how metadata drift caused real user pain.
- Video and reprocess work will make the artifact surface even more complex.

**Critical appraisal:**
This recommendation is strong because it has cross-cutting payoff. The weakness is scope creep: “unify metadata” can turn into an endless design exercise.

**2nd / 3rd / 4th order effects:**
- 2nd order: replay becomes simpler and more deterministic.
- 3rd order: learning ingestion stops depending on stage-specific guesswork.
- 4th order: future distributed execution becomes more feasible because artifact boundaries are cleaner.

**Caveats:**
Keep the contract pragmatic. Define required core fields and a typed extensibility section rather than trying to freeze every possible future field today.

---

## 7) Turn reprocess into a real productized subsystem, not a partial runner trick

**BLUF:** Promote reprocess from “starting with input image paths and a start stage” into a documented, validated, test-backed workflow with a clear UI and artifact model.

**Why it is this high:** Reprocess is one of the most leverage-rich capabilities because it reuses existing generation infrastructure while enabling much more practical editing and iterative work.

**Mini research dive / evidence from repo review:**
- The runner already has explicit reprocessing hooks (`input_image_paths`, `start_stage`).
- There are docs and issues around reprocess batching and refresh behavior.
- The feature exists conceptually, but its contract appears only partially productized.

**Critical appraisal:**
This is a very good “build next” item because it deepens utility without inventing a brand-new engine. The weakness is UX ambiguity: reprocess can sprawl into many unrelated editing concepts if left unbounded.

**2nd / 3rd / 4th order effects:**
- 2nd order: output curation and second-pass workflows become much better.
- 3rd order: it creates the natural bridge toward targeted editing and canvas-based tools.
- 4th order: learning can compare original vs reprocessed outcomes, which is valuable training data.

**Caveats:**
Keep Phase 1 narrow: selected inputs, selected start stage, deterministic output routing, and history linkage back to source images.

---

## 8) Finish the controller event API cleanup and kill reflective dispatch patterns completely

**BLUF:** Make every GUI-to-controller interaction use explicit, typed entrypoints and remove the last dynamic or stringly-typed dispatch remnants.

**Why it is this high:** In Tkinter-heavy apps, implicit UI wiring becomes a long-term maintenance trap.

**Mini research dive / evidence from repo review:**
- The architecture doc explicitly calls out the typed event API and retirement of reflective dispatch.
- The size and breadth of the GUI/controller surface make strict event contracts unusually valuable here.
- The test suite includes controller event API and UI dispatch contract tests, which suggests this is already recognized as important.

**Critical appraisal:**
This is a structural hygiene move. The weakness is that it can seem like a purely internal nicety. In reality, it directly affects debuggability and testability.

**2nd / 3rd / 4th order effects:**
- 2nd order: GUI tests become less brittle.
- 3rd order: agent-generated code is less likely to invent new hidden pathways.
- 4th order: migrating parts of the GUI or adding alternate frontends becomes more realistic.

**Caveats:**
Pair this with targeted tests. Event API cleanup without a contract suite tends to regress quietly.

---

## 9) Add architecture enforcement checks so the repo can defend itself

**BLUF:** Encode the most important architecture rules into import checks, grep-like invariants, linting, or contract tests so violations are caught automatically.

**Why it is this high:** The repo already has strong architecture doctrine. The next step is enforcement.

**Mini research dive / evidence from repo review:**
- The docs are unusually explicit and governance-heavy.
- There is already a pre-commit setup and CI structure to hang enforcement on.
- Current migration drift suggests documentation alone is not enough.

**Critical appraisal:**
This is very high leverage. The weakness is over-enforcement: if the rules are too strict or too noisy, people route around them.

**2nd / 3rd / 4th order effects:**
- 2nd order: legacy drift slows dramatically.
- 3rd order: PR review becomes more about design than hunting for obvious contract violations.
- 4th order: the repo becomes much friendlier to executor agents because the system pushes back on bad moves.

**Caveats:**
Start with a short list: no forbidden imports, no legacy prompt sources, no direct runner invocation from UI, no new `pipeline_config` dependencies.

---

## 10) Make queue cancellation, pause/resume, and checkpoint semantics trustworthy

**BLUF:** Finish queue lifecycle semantics so pause/cancel/resume/checkpoint behaviors are explicit, recoverable, and reflected correctly in the UI and history.

**Why it is this high:** The queue is central to the product. If queue lifecycle behavior is ambiguous, users do not trust batch execution.

**Mini research dive / evidence from repo review:**
- There are docs around queue checkpoint/resume.
- Past issue lists mention queue visual and lifecycle weaknesses.
- The queue/runner/history relationship is mature enough that lifecycle semantics now matter more than just getting jobs to run.

**Critical appraisal:**
This is a meaningful quality-of-life and reliability item. The weakness is complexity: “pause” and “resume” can mean very different things at stage boundaries vs per-image vs process-level suspension.

**2nd / 3rd / 4th order effects:**
- 2nd order: long batch runs become practical.
- 3rd order: recovery work becomes easier because the queue state machine is clearer.
- 4th order: cluster/distributed execution becomes less risky later.

**Caveats:**
Be honest about scope. A robust checkpoint-at-stage-boundary system is better than a fake “pause anywhere” button that cannot actually guarantee correctness.

---

## 11) Complete the learning loop, but keep Phase 1 modest

**BLUF:** Finish the minimum useful learning loop—capture, review, store, recommend—before attempting more autonomous or self-modifying behavior.

**Why it is this high:** The learning subsystem has real potential, but partially wired learning can become architectural drag if it grows ahead of its evidence model.

**Mini research dive / evidence from repo review:**
- There is extensive learning code and roadmap material.
- The current learning surface appears partially functional rather than fully closed-loop.
- The repo already contains record builders, review stores, recommendation logic, and output scanning.

**Critical appraisal:**
This is a strong recommendation, but only if the scope is disciplined. The weakness is trying to jump from “records exist” to “the system meaningfully improves itself” without enough curated feedback quality.

**2nd / 3rd / 4th order effects:**
- 2nd order: you get a much better basis for settings recommendations.
- 3rd order: model/profile defaults can become evidence-backed instead of intuition-backed.
- 4th order: future AI assistance features become safer because they rest on explicit data rather than hidden heuristics.

**Caveats:**
Do not let the system auto-rewrite core prompts/configs based on sparse or noisy data. Keep the first loop advisory and inspectable.

---

## 12) Centralize and type-check config validation at the pipeline boundary

**BLUF:** Build one strong validation/normalization layer that all jobs pass through before they become NJRs or execution payloads.

**Why it is this high:** A large share of StableNew’s complexity is config-shape complexity. Strong validation reduces the cost of every downstream subsystem.

**Mini research dive / evidence from repo review:**
- The runner currently collects fields from multiple places (`njr.config`, attributes, `extra_metadata` in some cases).
- Learning and video introduce more config variation.
- The project already values deterministic merging and explicit contracts.

**Critical appraisal:**
This recommendation is excellent for long-term maintainability. The weakness is that it can feel redundant if there are already many validators scattered around. That is exactly why centralization matters.

**2nd / 3rd / 4th order effects:**
- 2nd order: fewer late-stage runtime failures.
- 3rd order: clearer error messaging for GUI users.
- 4th order: easier serialization, history, and replay because the job shape is normalized earlier.

**Caveats:**
Keep validation close to the canonical build path. Avoid duplicating the same rules separately in GUI, controller, builder, and runner.

---

## 13) Refresh the docs/readme/source-of-truth package so it matches reality

**BLUF:** Bring the top-level README, docs index, and current-state onboarding docs fully into alignment with v2.6 and the real subsystem status.

**Why it is this high:** The repo’s own narrative still contains outdated framing. That costs time for every contributor and every agent.

**Mini research dive / evidence from repo review:**
- README still presents the project as V2.5 and points to a V2.5 docs index.
- The canonical docs are clearly v2.6-oriented.
- The real preferred image pipeline and subsystem maturity have moved.

**Critical appraisal:**
This is often treated as low priority, but in a repo with heavy LLM-assisted development it is actually infrastructure. The weakness is that docs-only work can drift again quickly unless tied to real enforcement and ownership.

**2nd / 3rd / 4th order effects:**
- 2nd order: faster onboarding and fewer incorrect assumptions.
- 3rd order: better output from coding agents.
- 4th order: strategic planning gets clearer because people share the same state model.

**Caveats:**
Do this after or alongside the migration work, not before. Otherwise you will just write polished docs for a moving target.

---

## 14) Build a cleaner observability story across runner, WebUI, queue, and persistence

**BLUF:** Consolidate runtime logging, structured events, retry envelopes, and diagnostics bundles into one coherent observability model.

**Why it is this high:** When systems get this layered, debugging quality becomes a product feature.

**Mini research dive / evidence from repo review:**
- There are diagnostics, watchdog, process, and debug-hub artifacts already.
- The current repo appears to have strong raw instrumentation but not yet the simplest unified story.
- Recovery hardening will need better telemetry to be safe.

**Critical appraisal:**
This is high leverage, but only if it is opinionated. The weakness is building more logs instead of better logs.

**2nd / 3rd / 4th order effects:**
- 2nd order: triage gets faster.
- 3rd order: automated issue bundling becomes more useful.
- 4th order: the learning system can eventually leverage operational telemetry too.

**Caveats:**
Optimize for actionability, not volume. Every event should answer: what job, what stage, what engine state, what artifact, what next step.

---

## 15) Finish SVD Phase 1 as a dedicated, native, queue-backed tab

**BLUF:** Build the native SVD image-to-video flow as a separate tab that reuses queue/history/output semantics but does not get tangled into the main A1111 pipeline.

**Why it is this high:** This is the cleanest video win available because the architectural separation is already well reasoned and the repo already contains meaningful groundwork.

**Mini research dive / evidence from repo review:**
- The repo contains `src/video/svd_*` modules and discovery docs pointing toward a dedicated native tab.
- The service layer already reflects a real native SVD direction.
- The main missing piece is turning that groundwork into a coherent product surface.

**Critical appraisal:**
This is a good build-next item precisely because it has a relatively clean architectural boundary. The weakness is dependency/runtime complexity, especially around memory pressure and environment setup.

**2nd / 3rd / 4th order effects:**
- 2nd order: broadens the product without increasing WebUI dependence.
- 3rd order: establishes a pattern for non-WebUI runtimes sharing the same queue/history model.
- 4th order: positions StableNew as a broader media workflow orchestrator, not just an image frontend.

**Caveats:**
Keep Phase 1 small: single selected image, a few key parameters, MP4 output, clear errors, no cinematic sequencing yet.

---

## 16) Build AnimateDiff as a distinct stage with a very explicit artifact contract

**BLUF:** Add AnimateDiff only after the core migration and output contract are stronger, and model it as a real stage with strict ordering and output semantics.

**Why it is this high:** AnimateDiff is desirable, but it touches many more parts of the existing pipeline than SVD does.

**Mini research dive / evidence from repo review:**
- The repo contains multiple AnimateDiff discovery docs and a staged approach.
- The stage-sequencing and artifact semantics matter more here because AnimateDiff fits into the main image pipeline.
- The docs already warn against rushing implementation before the contract is pinned down.

**Critical appraisal:**
This is worth doing, but later than some people would instinctively place it. The weakness is feature excitement outpacing architectural readiness.

**2nd / 3rd / 4th order effects:**
- 2nd order: adds a compelling new workflow.
- 3rd order: stresses the stage model, output contract, and UI complexity.
- 4th order: if implemented carefully, it strengthens the platform; if implemented hastily, it becomes a new source of pipeline drift.

**Caveats:**
Treat it as a final-stage output producer in Phase 1 and avoid overloading the initial UI with too many motion knobs.

---

## 17) Make output routing and naming deterministic across all major job types

**BLUF:** Standardize how images, videos, reprocess outputs, and learning artifacts are routed and named so users can predict where work went and why.

**Why it is this high:** Storage clarity matters more as the system supports more workflows and larger batch runs.

**Mini research dive / evidence from repo review:**
- The repo already has output routing and safe filename logic.
- Previous bugs around variant indexing and output-folder opening show that this area is user-visible and fragile.
- Reprocess and video will raise the stakes.

**Critical appraisal:**
This is a very practical recommendation. The weakness is that naming debates can spiral. The focus should be predictability, not perfection.

**2nd / 3rd / 4th order effects:**
- 2nd order: easier manual review and cleanup.
- 3rd order: better history linkage and replay lookup.
- 4th order: better data hygiene for downstream learning.

**Caveats:**
Keep the file paths human-readable but stable. Do not overfit names to every possible metadata field.

---

## 18) Finish model/resource discovery and refresh semantics cleanly

**BLUF:** Make model, VAE, sampler, and ADetailer resource refresh behavior consistent, explicit, and decoupled from fragile UI assumptions.

**Why it is this high:** Resource lists are a deceptively important part of user trust. Bad refresh behavior makes the whole app feel flaky.

**Mini research dive / evidence from repo review:**
- The repo has model/resource adapters and refresh flows.
- There are docs and fixes related to refresh behavior and WebUI resources.
- Compatibility shims still exist around parts of discovery and launcher behavior.

**Critical appraisal:**
This is not glamorous, but it removes friction from daily use. The weakness is underestimating edge cases when the engine is mid-startup or partially ready.

**2nd / 3rd / 4th order effects:**
- 2nd order: fewer invalid config selections.
- 3rd order: smoother controller and tab initialization.
- 4th order: easier future multi-engine support.

**Caveats:**
Tie refresh semantics to actual readiness gates, not just “button clicked, ask whatever endpoint exists.”

---

## 19) Do the next wave of GUI/UX polish only after the architectural fixes above

**BLUF:** Continue dark mode, preview, queue feedback, tooltips, and panel polish—but deliberately after the core migration/reliability tranche, not before it.

**Why it is this high:** The GUI clearly needs continued polish, but the repo already shows multiple rounds of UI cleanup. The higher leverage now is stabilizing the substrate those controls sit on.

**Mini research dive / evidence from repo review:**
- There is a large backlog of GUI polish docs and PRs.
- Many of the remaining GUI items are worthwhile, but several tie directly into deeper queue/output/runtime correctness.
- UX work will land better once the behavior beneath it is stable.

**Critical appraisal:**
This is a revision from what might otherwise rank higher. The weakness in earlier thinking would be overweighting visible polish over structural stability.

**2nd / 3rd / 4th order effects:**
- 2nd order: a more stable runtime makes UX polish stick.
- 3rd order: fewer UI regressions from backend churn.
- 4th order: support burden drops because polish is built on predictable behavior.

**Caveats:**
Do not freeze UX entirely. Fix user-hostile bugs now, but avoid large polish-only campaigns that distract from migration and reliability.

---

## 20) Design the canvas/object-editing future as an architecture-first extension, not a one-off feature

**BLUF:** Treat canvas-based remove/modify workflows as a deliberate next-generation editing subsystem built on reprocess + artifact linkage, rather than stuffing it straight into the current pipeline tab.

**Why it is this high:** This is probably a strategically good direction, but it is not yet the next thing to ship.

**Mini research dive / evidence from repo review:**
- The repo already hints at reprocess and future editing directions.
- The architecture is not yet ready for a broad editing surface without risking sprawl.
- The right move now is to define the contract, data model, and artifact relationships first.

**Critical appraisal:**
This recommendation intentionally lands lower than raw excitement might suggest. The weakness of building it too early is obvious: it could become a large, bespoke side-path that bypasses the canonical system.

**2nd / 3rd / 4th order effects:**
- 2nd order: if designed well, it can become a major differentiator.
- 3rd order: it pushes StableNew toward a richer post-generation workflow platform.
- 4th order: it opens up future localized-learning opportunities around edits and user intent.

**Caveats:**
Do not let canvas editing create a second architecture. It should produce canonical reprocess/edit jobs with source-output linkage and history visibility.

---

# Priority order summary

1. Consolidate to one txt2img execution path  
2. Finish the NJR-only migration  
3. Normalize the canonical stage contract to the real preferred flow  
4. Harden WebUI recovery  
5. Restore the test suite to authoritative status  
6. Unify history/manifests/replay  
7. Productize reprocess  
8. Finish controller event API cleanup  
9. Add architecture enforcement checks  
10. Make queue lifecycle semantics trustworthy  
11. Complete the modest learning loop  
12. Centralize config validation  
13. Refresh README/docs/source-of-truth package  
14. Build a cleaner observability story  
15. Finish SVD Phase 1  
16. Build AnimateDiff Phase 1 carefully  
17. Standardize output routing and naming  
18. Clean up model/resource discovery and refresh  
19. Continue GUI/UX polish after the structural tranche  
20. Design canvas/object editing as an architecture-first extension

# Final synthesis

If I compress the whole review to one sentence:

**StableNew should spend its next major tranche becoming more canonical, more reliable, and more testable before it spends heavily on net-new surface area.**

That sequencing gives you a much better base for reprocess, learning, SVD, AnimateDiff, and future editing without recreating the migration debt you have already worked hard to escape.