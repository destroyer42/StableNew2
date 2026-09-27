# StableNew Highest-Value Next Work Assessment

> **PRE-DECISIONAL RESEARCH — NOT ROADMAP, STATUS, ARCHITECTURE, OR IMPLEMENTATION AUTHORITY**
>
> This report optimizes for **risk-adjusted product value**, not for severity of technical debt. It does not authorize implementation, backend promotion, model installation, GPU execution, user-data cleanup, architecture changes, or integration to `main`. Any recommendation below must become a bounded work package and receive the normal authorization required by current repository authority.

**Assessment date:** 2026-09-27 ET  
**Repository assessed:** `destroyer42/StableNew2`  
**Frozen remote baseline:** `main @ 0a2bb505acdb381726a401d9e74281e362fc44ea`  
**Latest integrated change on baseline:** PR #10 / PR-VID-184R Wan-Animate-2 pinned-memory re-adjudication  
**Open pull requests at assessment:** none  
**Research branch:** `research/value-priorities-2026-09-27`

---

## 1. Question

Given StableNew's current accepted architecture, recently completed work, unfinished work, technical debt, operator pain, target hardware, and the current image/video model ecosystem:

> **What are the ten next investments most likely to create the greatest total product value, and in what order should they actually be executed?**

This is deliberately different from asking for the ten largest weaknesses. Some severe weaknesses are not the highest-value active engineering package, and some high-value opportunities are not weaknesses at all.

---

## 2. Authority and evidence method

The assessment follows current repository authority:

1. current remote branch/SHA and PR state;
2. `AGENTS.md` and `STATUS.md`;
3. relevant `docs/CODEX_MAP.md`;
4. relevant architecture/testing/subsystem contracts;
5. current source/tests only where needed to validate an opportunity or dependency;
6. external current primary/upstream sources only where technology has materially changed since existing StableNew research.

The canonical production path remains:

`Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifact/History`

Nothing in this report recommends a second queue, runner, history store, compiler, cancellation authority, or process owner.

### Evidence reuse

The baseline SHA is unchanged from the immediately preceding critical-weaknesses assessment. Accepted exact-SHA repository and CI evidence from that report is therefore reused where the relevant source is unchanged. This report performs fresh external research where the market/model landscape affects value prioritization.

### Limits

- This report sees the current GitHub repository, not uncommitted local Windows worktree state.
- The user's production PromptPack library under `%LOCALAPPDATA%\StableNew\PromptPacks` was not rescanned in this package. PromptPack-cleanup value is based on the known product capability gap and operator-reported pain, not a fresh numerical inventory.
- No GPU workload, model download, driver/BIOS/XMP change, external process mutation, or user-data mutation was performed.
- No source or canonical authority document is changed by this report.

---

## 3. Value framework

The ranking is qualitative but uses five explicit dimensions.

### A. Direct operator value
Does the work materially improve output quality, capability, reliability, or daily usability?

### B. Frequency of benefit
Does the improvement help almost every generation session or only an occasional specialized workflow?

### C. Unlock / multiplier value
Does the work make several later features safer, cheaper, or possible?

### D. Time to first useful value
Can the benefit arrive in one bounded package, or only after a long architecture program?

### E. Risk-adjusted feasibility
How likely is the work to succeed on the RTX 4070 Ti 12-GB / 32-GB Windows target without destabilizing accepted architecture?

A ranking position is therefore **not** a raw technical-importance score. A lower-ranked item may be architecturally important but should wait until a higher-value dependency or product decision makes it necessary.

---

# 4. Top 10 highest-value next investments

## 1. Establish a stable workstation/GPU platform baseline

### Value thesis

A generation system that can hard-black-screen the workstation has a ceiling on every other form of value. Reliability multiplies the value of image quality, video capability, Learning, batching, automation, and future backends.

### Current evidence

DIAG-GPU-130 remains active with XMP-OFF ordinary-use observation. The historical black-screen family includes LiveKernel 141/1B8 evidence and GPU telemetry loss around StableNew/A1111 activity without a proven component-level cause. PR-VID-184 separately produced a lost-device event under extreme Windows commit pressure; PR-VID-184R completed the same frozen workload with pinned memory disabled, materially implicating that particular Comfy resource path without resolving DIAG-GPU-130.

### Initial action

Do **not** launch a new stress campaign. Continue the current one-variable XMP-OFF ordinary-use observation. If the black-screen family recurs, preserve evidence and move to exactly one next platform-baseline variable under a separately authorized diagnostic package.

### Independent challenge

Could this be over-ranked because there may be nothing active to code right now?

**Yes, operationally.** It is the highest-value outcome but not necessarily the next engineering branch. The current evidence correctly calls for observation rather than random interventions. Therefore this is **Priority 1 by value but a parallel diagnostic lane, not the next source-code package**.

### Verdict

**VALIDATED — highest total value, but execute as a parallel controlled diagnostic rather than blocking safe software work.**

### Higher-order effects

- 2nd order: trustworthy hardware stability makes every later target-hardware qualification more interpretable.
- 3rd order: if ordinary use remains stable under XMP-OFF, software/resource-specific failures can be separated more cleanly from platform instability.
- 4th order: if recurrence persists across a clean platform baseline, hardware substitution/power/PCIe diagnostics become more valuable than repeated backend tuning.
- product effect: fewer lost jobs, fewer interrupted batches, less operator distrust, better evidence quality.

### Gate

No new deliberate stress/GPU qualification merely to test stability. New GPU qualification work should require explicit owner authorization and should not change a second platform variable at the same time.

---

## 2. Restore deterministic test/journey truth

### Value thesis

StableNew now has mature architecture and increasingly sophisticated cross-surface behavior. Reliable deterministic journey evidence is a development multiplier: it reduces regression risk, review time, agent token use, manual retesting, and fear of changing controllers/backends.

### Current evidence

Required Python 3.11/3.12 CI passes, so the accepted release gate is not broken. However informational full-suite and several semantic GUI journeys are failing for identifiable harness/test defects:

- a test mutates the shared `os.name` module state to `"nt"`, plausibly producing Linux `WindowsPath` pytest INTERNALERROR;
- mocked GUI journeys probe the real `127.0.0.1:7860` readiness path and defer queue autostart instead of executing against a deterministic fake-runtime seam.

### Initial action

One bounded **Test Truth Repair** package:

1. replace shared `os.name` mutation with a module-local/testable platform seam;
2. inject deterministic fake backend/runtime readiness at the correct production boundary for GUI journeys;
3. rerun only affected tests first;
4. run the normal required gate;
5. perform one aggregate full-suite/journey verification and classify any remaining failures.

### Independent challenge

Does this create more user value than a new model?

Indirectly, yes—because the effort is small relative to its multiplier effect. It should not consume a long cleanup program. If the repair expands into broad test modernization, its value falls rapidly.

### Verdict

**VALIDATED — highest-value immediate engineering package.**

### Higher-order effects

- 2nd order: may expose real product defects currently hidden behind harness failures.
- 3rd order: enables safer controller extraction and second-backend integration.
- 4th order: can reduce repeated manual acceptance and allow selected semantic journeys to become stronger regression gates later.
- cost effect: lower agent/reviewer rediscovery and fewer expensive failed implementation passes.

### Gate

Repair production-boundary fidelity; do not make tests green by bypassing canonical submission/runner/history paths.

---

## 3. Re-qualify the next image backend candidate around FLUX.2 Klein 4B, not automatically Ideogram 4

### Value thesis

Image generation is StableNew's most frequent core workflow. A materially stronger, faster, commercially usable next-generation model family could improve nearly every session and unlock true semantic image editing.

### Why the recommendation changed

The existing image roadmap was written when Ideogram 4 was the first candidate. That assumption is now stale as a value optimization.

Current upstream evidence:

- **FLUX.2 [klein] 4B** is Apache-2.0, supports both text-to-image and image-to-image/multi-reference editing, is available through Diffusers and ComfyUI, and is explicitly positioned for consumer GPUs.
- Its official model card says the full 4B pipeline is about a **13-GB VRAM** class workload and names RTX 3090/4070-class hardware. StableNew's target has 12 GB, so a target-hardware PASS must be proven rather than assumed.
- Official FP8 single-file weights also exist, but their smaller transformer file does not by itself prove total pipeline residency on StableNew's 12-GB target.
- **Ideogram 4 NF4** is already proven constrained-viable by StableNew, but the weights are under a non-commercial license and require custom staged residency plus structured prompt mapping.
- **Qwen-Image-2.1**, released September 2026, is technically attractive (7B visual transformer, generation + editing + RGBA + multi-reference), but its current license is research/non-commercial and its BF16 text encoder alone is about 17.5 GB; it is not the best first target for the current machine.
- FLUX.2 Klein 9B is a worse hardware fit; the official card places it around 29 GB VRAM.

### Initial action

Create a qualification-only **PR-IMG-11x next-candidate re-adjudication** before authorizing PR-IMG-120:

- use the existing backend-neutral image architecture and the official Diffusers path;
- pin exact model/revision/environment;
- compare against a frozen A1111/SDXL control on representative StableNew use cases;
- include at least portrait/person quality, prompt adherence, text/typography, one semantic edit, latency, VRAM, physical RAM/commit, and output/provenance;
- no production backend registration;
- no GUI changes;
- no assumption that 13 GB means the 12-GB card will work.

### Independent challenge

Should StableNew simply integrate Ideogram 4 because it already passed target-hardware qualification?

**No.** Ideogram 4 remains a viable research option, but its non-commercial license, special structured-prompt mapping, and custom residency lifecycle materially lower its product value compared with a newly available Apache-2.0 model that also brings editing. Existing qualification evidence should be preserved, not discarded.

Should Qwen-Image-2.1 win because it is the newest?

**No.** Recency alone is not value. Its research-only license and heavier memory footprint make it a poorer first production candidate on this target.

### Verdict

**VALIDATED — the next image action should be candidate re-selection/qualification, with FLUX.2 Klein 4B as the lead target.**

### Higher-order effects

- 2nd order: if FLUX.2 Klein passes, StableNew gains a commercially permissive path to both stronger generation and semantic editing.
- 3rd order: a successful 4B backend reduces pressure to force oversized 9B/Qwen/Ideogram models onto 12 GB merely for model novelty.
- 4th order: the image-backend abstraction becomes proven by real product value, not abstraction-for-abstraction's-sake.
- architecture effect: capability vocabulary may need to expand only for real edit/reference features required by the accepted backend.

### Gate

Do not integrate anything until target-hardware qualification and owner product decision. If it cannot meet a useful envelope on 12 GB without pathological host-memory spill, stop rather than creating a fragile production backend.

---

## 4. Complete PR-ASSET-120: provenance-rich compatibility profiles, then VAE/adapter guidance

### Value thesis

StableNew already solved the difficult identity problem: the AssetRegistry knows which bytes are actually installed. The next value is helping the operator use those assets correctly.

This affects daily image generation:

- which VAE belongs with a checkpoint;
- whether a checkpoint has a baked VAE;
- SDXL versus SD1.x/other-family LoRA compatibility;
- embedding family/encoder compatibility;
- adapter trigger words and expected base family;
- duplicate aliases versus actual duplicate content;
- assets installed locally but not exposed by the current A1111 instance.

### Current evidence

PR-ASSET-110 explicitly identifies PR-ASSET-120 as the next package: provenance-rich asset metadata and compatibility profiles, observational first.

### Initial action

Implement PR-ASSET-120 as offline observational enrichment:

- architecture/model family;
- trusted embedded metadata;
- content hash/provenance;
- source/confidence for each inferred fact;
- VAE relationship evidence;
- LoRA/embedding compatibility profile;
- ambiguous/unknown state rather than invented certainty.

Then, in a later separately authorized package, expose **advisory** VAE/adapter guidance to Pipeline/PromptPack authoring.

### Independent challenge

Would another scanner or internet lookup service create more value?

**No.** Another scanner would duplicate solved authority. Network enrichment may eventually help, but should come after local provenance/confidence is coherent so remote metadata cannot become a second identity authority.

### Verdict

**VALIDATED — one of the highest-value low-risk software investments.**

### Higher-order effects

- 2nd order: fewer wasted generations from incompatible assets.
- 3rd order: Learning receives cleaner controlled evidence because invalid adapter combinations can be flagged/excluded.
- 4th order: future image backends can reuse content identity and compatibility metadata without making A1111 names canonical.
- UX effect: StableNew can eventually explain *why* a VAE/LoRA is recommended rather than silently changing settings.

### Gate

First package remains observational. Automatic selection requires a later owner decision, provenance/confidence rules, and manual override.

---

## 5. Build a non-destructive PromptPack and saved-setting quality audit

### Value thesis

PromptPack/settings quality is one of the most direct sources of operator friction and bad output. The storage architecture is already repaired; the next value is reducing bad content inside valid storage.

### Initial action

Build an audit, not a rewrite:

**Tier 1 — deterministic hard findings**
- empty packs/empty effective prompts;
- exact duplicate packs/rows;
- normalized duplicate rows;
- missing referenced assets;
- dead aliases;
- invalid/impossible saved enum or generation values;
- settings that reference assets no longer present.

**Tier 2 — compatibility findings after PR-ASSET-120**
- incompatible checkpoint/VAE;
- likely wrong-family LoRA/embedding;
- conflicting model-family assumptions.

**Tier 3 — advisory semantic quality**
- obvious positive/negative contradictions;
- repeated or redundant prompt terms;
- mutually cancelling style/quality instructions;
- variants whose differences cannot alter execution.

Present findings with evidence and proposed actions. Use existing backup/quarantine/storage authority for any confirmed cleanup and require operator confirmation before bulk mutation.

### Independent challenge

Is semantic prompt linting too subjective to be valuable?

Partly. That is why semantic findings belong in Tier 3 and must stay advisory. Tier 1 and Tier 2 are objective enough to deliver substantial value without asking an LLM to rewrite creative content.

### Verdict

**VALIDATED — high-frequency daily value, especially after asset compatibility exists.**

### Higher-order effects

- 2nd order: less choice clutter and fewer invalid jobs.
- 3rd order: stronger experimental baselines and cleaner Learning evidence.
- 4th order: future prompt-assistance can operate over a curated corpus instead of learning/recommending from contradictory historical packs.
- migration effect: backup/quarantine remains the protection mechanism; no new PromptPack authority is needed.

### Gate

Do structural audit first. Do not start bulk cleanup of user-scoped packs until a local census is produced and operator-confirmed actions are explicit.

---

## 6. Close the Wan-Animate-2 adjudication and force a PROMOTE / DEFER / REJECT decision

### Value thesis

True directed/reference-bound body motion is one of the largest remaining user-visible capability gaps. PR-VID-184R materially improved the feasibility picture: the first local run failed, while the same frozen workload completed with pinned memory disabled and produced a reference-looking moving subject.

Current official Wan-Animate-2 remains active and directly targets driving-video character animation and identity preservation.

### Initial action

Do the cheapest unanswered step first:

1. owner/human visual verdict on the already-generated PR-VID-184R artifact;
2. no new GPU work for that verdict;
3. if the verdict is promising, define one specific remaining uncertainty;
4. authorize at most one controlled replicate/second-seed or representative-length case if platform conditions permit;
5. make a product decision: **PROMOTE experimental workflow / DEFER / REJECT for current target**.

### Independent challenge

Is this more valuable than further Wan2.2 TI2V prompt tuning?

**Yes.** Existing evidence already showed structured prompting improves local gestures but not locomotion. More prompt tuning attacks the wrong limitation.

Should StableNew integrate Wan-Animate-2 immediately because it produced an output?

**No.** Motion timing correlation missed the frozen threshold, evidence is one seed/short clip, and the owner visual gate is not complete.

### Verdict

**VALIDATED — high upside, but decision closure is more valuable than another long characterization chain.**

### Higher-order effects

- 2nd order: a promote decision creates real demand for resource/preparation policy and capability-aware UI.
- 3rd order: a defer/reject decision stops sunk-cost research and redirects effort to image/asset/prompt value.
- 4th order: retained frozen evidence makes later re-entry cheap if hardware or upstream implementation improves.

### Gate

Human verdict now. New GPU submission only after explicit authorization and without changing another DIAG-GPU-130 platform variable.

---

## 7. If FLUX.2 Klein qualifies, ship a second production image backend for **new capability**, not merely another T2I checkbox

### Value thesis

A second backend is worth its complexity only if it creates product value A1111/SDXL cannot deliver well. The strongest candidate value is not “choose another model”; it is:

- stronger prompt following/modern image quality;
- semantic image editing;
- reference-aware editing;
- potentially multi-reference composition;
- faster interactive workflows if target-hardware evidence supports it.

### Initial action

If qualification passes and the owner approves:

1. implement one Diffusers production backend behind the existing image backend interface;
2. start with the smallest accepted task set;
3. preserve A1111 as the current/default mature backend unless product evidence supports changing defaults;
4. extend `ImageBackendCapabilities` only for the concrete edit/reference controls actually required;
5. make the UI capability-aware only after those capabilities exist;
6. keep one backend per image NJR initially.

### Independent challenge

Would a pure alternate-T2I backend justify the integration cost?

**Maybe not.** If output improvement is modest and editing cannot fit the target envelope, the ROI can fall below asset/prompt improvements. The go decision should therefore be based on measured user-visible advantage, not on “proving backend neutrality.”

### Verdict

**VALIDATED CONDITIONALLY — high value only if qualification demonstrates material quality/editing advantage at acceptable latency/resources.**

### Higher-order effects

- 2nd order: StableNew becomes future-proof at the product level, not only architecture level.
- 3rd order: capability-aware UI prevents A1111-specific settings from leaking into newer model families.
- 4th order: future models can enter through a proven Diffusers adapter/model-family mechanism rather than another runner rewrite.
- risk effect: a second backend increases GPU residency/process/resource complexity, making #8 necessary only when evidence demands it.

### Gate

No production slice before target qualification + owner decision. Do not combine initial integration with per-stage cross-backend composition.

---

## 8. Add a minimal backend resource/preparation profile only when the second heavy backend becomes real

### Value thesis

Recent qualifications prove that **how** a model is resident can determine whether it runs:

- Ideogram 4 needs staged residency to avoid shared-memory spill;
- Wan has explicit RAM/VRAM floors;
- Wan-Animate-2 may require pinned memory disabled;
- StableNew already coordinates release of conflicting *owned* runtimes.

Once there are multiple heavy production backends, resource preparation becomes correctness, not tuning.

### Initial action

Do not build a scheduler. Define the smallest typed backend preparation/resource profile required by the first approved second backend:

- required owned-runtime releases;
- evidence-backed minimum RAM/commit/VRAM headroom;
- required runtime flags;
- residency strategy identifier when load order matters;
- experimental/production gate;
- fail-before-dispatch reason.

Keep lifecycle ownership with existing process/runtime owners.

### Independent challenge

Should this be built now because several qualifications already need resource logic?

**No.** Building a universal abstraction before a second backend is selected risks architecture speculation. Existing backend-specific qualification guards are sufficient for research.

### Verdict

**VALIDATED, but strictly dependency-triggered. Not immediate work.**

### Higher-order effects

- 2nd order: backend availability becomes explainable and testable.
- 3rd order: GUI can show actionable readiness without learning backend-specific memory rules.
- 4th order: future hardware profiles can change resource requirements without changing queue/lifecycle authority.

### Gate

Begin only after an actual second production backend is selected.

---

## 9. Build one reusable qualification evidence framework before another multi-package model research cycle

### Value thesis

The image/video ecosystem is changing faster than StableNew can justify bespoke multi-PR evaluation harnesses forever. The product's long-term advantage is not betting perfectly on one model; it is being able to evaluate and adopt the right model cheaply and safely.

### Current evidence

The VID-110 → 184R line shows excellent individual experiment discipline but repeated custom machinery:

- frozen hashes/manifests;
- one-dispatch/no-retry rules;
- telemetry;
- process ownership;
- output validation;
- motion metrics;
- human gates;
- final classifications.

### Initial action

Create a tools-only common evidence layer with adapters:

- frozen source/control hashes;
- immutable run manifest;
- exact environment/revision fingerprint;
- one-submit/no-retry guard;
- resource telemetry;
- owned-process startup/teardown evidence;
- artifact/media validation;
- metric plug-ins;
- explicit human-verdict slot;
- `PROMOTE / DEFER / REJECT / INCONCLUSIVE` classification.

Do not refactor old completed harnesses just for consistency.

### Independent challenge

Should this block the immediate FLUX.2 Klein qualification?

**No.** One bounded high-value qualification can reuse current patterns. This framework becomes high value before the *next* broad model-candidate cycle.

### Verdict

**VALIDATED — strategic multiplier, but not a reason to delay near-term product evidence.**

### Higher-order effects

- 2nd order: lower cost per model/backend evaluation.
- 3rd order: more comparable image/video candidate evidence.
- 4th order: less sunk-cost drift because every experiment must end in an explicit decision classification.
- agent effect: smaller, repeatable research packages and less rediscovery.

### Gate

Keep completely outside production runtime authority. Production `src/` must not depend on qualification tools.

---

## 10. Reduce controller concentration opportunistically, attached to value work rather than as a standalone rewrite

### Value thesis

`AppController` remains 7,782 physical lines and `PipelineController` 1,785. This increases change cost, review cost, and risk. But pure refactoring competes with high-value product improvements.

### Initial action

Continue the ratchet and make every adjacent value package pay down the responsibility it touches:

- no new coherent responsibility inline;
- prefer existing `app_controller_services/` / `pipeline_controller_services/` homes;
- extract one responsibility only when tests are reliable;
- lower the ceiling whenever the controller shrinks;
- use dedicated decomposition only for a high-churn responsibility with clear ownership.

### Independent challenge

Would a large controller cleanup create more value by making everything else easier?

**No.** A big-bang rewrite creates long time-to-value and high regression risk. StableNew already has the correct strangler pattern. Controller reduction is a multiplier, not the current product mission.

### Verdict

**VALIDATED as an execution policy; REFUTED as a standalone top-priority rewrite.**

### Higher-order effects

- 2nd order: lower agent context and review cost.
- 3rd order: easier enforcement of queue/runtime ownership.
- 4th order: eventually leaves AppController as a thin compatibility shell without a dangerous migration event.

### Gate

Dedicated extraction should follow #2 test-truth repair. Otherwise reduce controllers only where adjacent authorized work naturally exposes a cohesive seam.

---

# 5. Suggestions considered but not in the final top 10

## A. Integrate Ideogram 4 immediately

**REFUTED as the default next image move.**

StableNew's target-hardware requalification is useful and should be retained, but a newer Apache-2.0, unified generation/editing candidate now has higher potential product value. Ideogram remains a valid comparison candidate.

## B. Prioritize Qwen-Image-2.1 because it is newest

**REFUTED for the current target.**

Qwen-Image-2.1 is technologically compelling, but its September 20, 2026 research license is explicitly non-commercial, and its BF16 pipeline is heavy. It belongs in future research, not ahead of FLUX.2 Klein 4B for this 12-GB Windows target.

## C. More Wan2.2 TI2V prompt engineering

**DEPRIORITIZED.**

PR-VID-150 already established that structured prompting improves local motion but does not unlock reliable locomotion. Presets may be a small later usability win, but they do not solve the main video value gap.

## D. Add more Learning automation now

**DEFERRED.**

The current Learning subsystem already has evidence-gated recommendations and confirmation-gated curation. Increasing automation before asset compatibility and PromptPack quality are improved risks making bad inputs easier to reuse. Clean input/config evidence first.

## E. Full GPU scheduler / universal lease system

**REFUTED.**

Owned-runtime transition and observe-only readiness already address current production needs. Add only the minimal resource contract demanded by an approved second heavy backend.

## F. Big GUI redesign

**NOT VALIDATED as a top-10 investment.**

Current high-value GUI work should be capability-driven and attached to actual backend/asset/PromptPack behavior. A broad redesign would have high scope and weak measured value relative to the opportunities above.

## G. Big controller rewrite

**REFUTED.**

Continue ratchet/extraction. Do not replace the coordinator wholesale.

## H. Retire the video legacy stage bridge immediately

**DEFERRED.**

It is bounded debt with an explicit removal condition. Retirement becomes high value when another production video backend is promoted or when the remaining producers are already being touched. It should not displace current user-value work.

---

# 6. Revised product-value implications from current external research

## 6.1 FLUX.2 Klein 4B changes the image-backend ROI calculation

StableNew's prior image roadmap reasonably selected Ideogram 4 as the first future Diffusers candidate. As of September 2026, that assumption should no longer be treated as current truth.

Official FLUX.2 Klein 4B claims:

- Apache 2.0;
- text-to-image;
- image-to-image / multi-reference editing;
- fast/distilled interactive operation;
- roughly 13-GB VRAM class consumer-GPU operation;
- Diffusers and ComfyUI support.

This combination directly addresses three StableNew goals at once: better modern image generation, editing capability, and backend future-proofing.

The 12-GB target is just below the published approximate full-pipeline memory class, so **qualification is mandatory**. The value finding is “this is now the best lead candidate to test,” not “it is already proven to fit.”

Sources:
- https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B
- https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8

## 6.2 Qwen-Image-2.1 is high-capability but a weaker current StableNew fit

Qwen-Image-2.1, released under the Qwen Research License on September 20, 2026, offers:

- 7B visual transformer;
- unified generation/editing;
- up to ten reference images;
- transparent RGBA generation/editing;
- strong typography/portrait claims.

But:

- the license grants non-commercial research/evaluation use only unless a separate commercial license is obtained;
- BF16 component sizes are substantial (text encoder about 17.5 GB; transformer about 14.2 GB);
- target-machine execution has not been qualified.

It should remain on the watchlist rather than displace a better-licensed/lighter first candidate.

Sources:
- https://huggingface.co/Qwen/Qwen-Image-2.1
- https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE

## 6.3 Ideogram 4 remains strong research evidence, but licensing/residency lower its relative product value

StableNew has already proven Ideogram 4 NF4 can run on the RTX 4070 Ti 12 GB with explicit staged residency. Upstream model cards continue to describe it as a frontier open-weight image model, but the model license remains non-commercial.

Therefore the StableNew evidence is not obsolete; the **priority** is what changed.

Source:
- https://huggingface.co/ideogram-ai/ideogram-4-nf4-diffusers

## 6.4 Wan-Animate-2 remains a credible directed-motion technology, but StableNew must finish its own gate

The official project directly consumes driving video and targets identity-preserving character animation. StableNew's pinned-memory re-adjudication now shows one viable local execution path.

That is enough to justify finishing the decision. It is not enough to claim production capability.

Source:
- https://github.com/Wan-Video/Wan-Animate-2

---

# 7. Value ranking versus actual execution order

The ten items above are ranked by total expected value. They should **not** be executed strictly 1→10 because some depend on observation or owner decisions.

## Parallel lane P0 — workstation stability

Continue XMP-OFF ordinary-use observation now. This remains the highest-value outcome but does not justify random active interventions.

If recurrence occurs:
- stop affected GPU qualification;
- preserve telemetry/Windows evidence;
- open the next one-variable platform isolation package.

---

## Engineering sequence E1 — Test Truth Repair

**Do first.**

Why:
- GPU-independent;
- low/moderate effort;
- unlocks reliable verification for every later code package;
- addresses two already-identified failure classes rather than speculative debt.

**Model/execution class:** Terra Medium or Luna High if the final fix is narrow; Local/Desktop for Tk journey reproduction.

**Stop:** if repair exposes a materially new product/runtime defect, classify it rather than broadening into a third failure class.

---

## Engineering sequence E2 — PR-ASSET-120 observational compatibility profiles

**Do next while the hardware diagnostic remains observation-only.**

Why:
- no GPU-heavy model work required;
- high-frequency operator value;
- enables better PromptPack audit and future Learning quality;
- already has a repository-defined next-package boundary.

**Model/execution class:** Terra High, Local/Desktop.

**Stop:** before automatic recommendations, network enrichment, or job mutation.

---

## Engineering sequence E3 — PromptPack structural audit

Implement the Tier-1 read-only/non-destructive audit after asset identity/profile surfaces are stable enough to consume.

Do not bulk-clean user data yet.

**Exit:** produce an operator-readable census of empty, duplicate, missing-reference, and invalid packs/settings with proposed actions.

**Model/execution class:** Terra Medium/High, Local/Desktop.

---

## Product decision D1 — existing Wan-Animate-2 human verdict

This requires no new generation. Review the retained PR-VID-184R output and record the owner verdict.

If clearly poor:
- DEFER/REJECT;
- stop new Wan-Animate-2 GPU work.

If promising:
- identify exactly one unresolved capability question before authorizing another GPU run.

---

## Qualification sequence Q1 — FLUX.2 Klein 4B target-hardware qualification

Begin only when:

- Test Truth Repair is accepted;
- the platform diagnostic does not have an unresolved fresh recurrence that would invalidate evidence;
- model download/environment/GPU execution are explicitly authorized.

Qualification-only. No production backend.

**Model/execution class:** Terra High for bounded qualification; Sol Medium only if resource ownership/residency architecture becomes ambiguous.

**Decision:** PASS / CONDITIONAL / NO-GO for this target.

---

## Product decision D2 — choose the next production image backend, if any

If FLUX.2 Klein materially beats the accepted A1111 workflow or enables valuable editing at an acceptable envelope:
- authorize a bounded Diffusers production slice.

If not:
- retain A1111;
- keep Ideogram/Qwen/other candidates as research options;
- do not integrate a second backend merely because the abstraction exists.

---

## Product decision D3 — Wan-Animate-2 promote/defer

If the human verdict is promising and one remaining test is justified, run at most the authorized bounded adjudication.

Then choose:
- **PROMOTE experimental StableNew workflow**;
- **DEFER pending hardware/upstream change**;
- **REJECT for current product target**.

No open-ended sequence.

---

## Architecture sequence A1 — minimal resource/preparation contract

Only if D2 or D3 selects a second heavy production backend.

This is dependency work, not an independent initiative.

---

## Efficiency sequence X1 — common qualification evidence layer

Implement before another broad model-candidate campaign, but do not delay the single bounded FLUX.2 qualification merely to perfect research tooling.

---

## Continuous policy C1 — controller ratchet/extraction

Throughout all packages:

- never increase controller responsibilities without explicit exception;
- lower ceilings when surfaces shrink;
- attach extractions to the value package touching that responsibility.

A dedicated controller package should be created only after Test Truth Repair and only for a clearly high-churn responsibility.

---

# 8. Recommended candidate work-package queue

This is a **pre-decisional candidate queue**, not an approved roadmap.

### WP-VALUE-001 — Deterministic Test Truth Repair
**Outcome:** repair platform-identity leakage and fake-runtime journey readiness so broad deterministic evidence is trustworthy again.  
**Execution:** Terra Medium / Local.  
**Value:** development multiplier.  
**GPU:** none.

### PR-ASSET-120 — Provenance-Rich Asset Metadata Enrichment and Compatibility Profiles
**Outcome:** observational compatibility/provenance layer over the accepted AssetRegistry.  
**Execution:** Terra High / Local.  
**Value:** daily configuration correctness.  
**GPU:** none.

### WP-PACK-AUDIT-100 — PromptPack & Saved-Settings Quality Census
**Outcome:** non-destructive objective audit; no bulk mutation.  
**Execution:** Terra Medium / Local.  
**Dependency:** PR-ASSET-120 for compatibility tier; structural tier can precede it.  
**GPU:** none.

### PR-IMG-115 candidate — 2026 Image Backend Candidate Re-adjudication
**Outcome:** target-hardware comparison of FLUX.2 Klein 4B against current A1111/SDXL; retain Ideogram 4 as comparison evidence, no production integration.  
**Execution:** Terra High / Local/Desktop.  
**GPU/model action:** explicit authorization required.  
**Primary question:** does it provide enough quality/editing value on 12 GB to justify a production backend?

### PR-VID-185 candidate — Wan-Animate-2 Final Capability Adjudication
**Outcome:** human verdict first; at most one subsequently authorized GPU adjudication if needed; final PROMOTE/DEFER/REJECT.  
**Execution:** Terra High; Sol only on new architecture ambiguity.  
**GPU:** not required for first phase.

### PR-IMG-120R candidate — Diffusers Production Value Slice
**Conditional:** only after PR-IMG-115 PASS + owner approval.  
**Outcome:** real second image backend with the smallest valuable capability set.  
**Execution:** Sol Medium due resource/capability/ownership boundaries.  
**Security review:** triggered by model/runtime/dependency/process surfaces.

### WP-RUNTIME-RESOURCE-110 — Minimal Backend Resource Preparation Profile
**Conditional:** only when a second heavy backend is actually selected.  
**Outcome:** typed evidence-backed preflight/preparation requirements, not a scheduler.  
**Execution:** Sol Medium.

### WP-QUAL-100 — Common Qualification Evidence Layer
**Outcome:** reusable frozen-manifest/telemetry/process/artifact/verdict plumbing for future model research.  
**Execution:** Terra High; tools-only.

### Continuous controller-ratchet reductions
**Outcome:** shrink touched controller surfaces during adjacent work.  
**Execution:** included within relevant package, not a standalone rewrite by default.

---

# 9. Opportunity dependencies

```text
DIAG-GPU-130 observation --------------------------------------------+
                                                                     |
Test Truth Repair ----+----------------------------------------------+----> safer GPU/model integration
                      |
                      +--> PR-ASSET-120 --> PromptPack compatibility audit
                      |                      |
                      |                      +--> cleaner Learning evidence later
                      |
                      +--> FLUX.2 Klein qualification --> product decision
                      |                                   |
                      |                                   +--> Diffusers production slice
                      |                                          |
                      |                                          +--> capability-aware UI
                      |                                          +--> minimal resource profile
                      |
Existing 184R output --> owner visual verdict --> Wan decision
                                              |
                                              +--> optional one bounded GPU adjudication
                                              +--> experimental integration only if promoted

Qualification common layer --> lowers cost of later model cycles
Controller ratchet ---------> lowers risk/cost across all packages
```

---

# 10. What should *not* block near-term value

The following should be preserved but should not become prerequisites for every value package:

- complete AppController decomposition;
- full video legacy-bridge retirement;
- universal GPU scheduler;
- broad GUI rewrite;
- automatic Learning tuning;
- per-stage image backend composition;
- ComfyUI still-image migration;
- exhaustive qualification of every new public model;
- perfect cleanup of all historical docs before feature work.

Each of these may become valuable when a concrete product need triggers it.

---

# 11. Final prioritization

## Highest-value outcomes

1. **Stable workstation baseline** — maximum multiplier; current action is controlled observation.
2. **Trustworthy deterministic verification** — best immediate engineering ROI.
3. **A next-generation image path chosen using current 2026 evidence** — FLUX.2 Klein 4B should now be first to qualify, not automatic Ideogram integration.
4. **Asset compatibility intelligence** — high-frequency daily correctness.
5. **PromptPack/settings quality cleanup** — high-frequency usability/output value.
6. **A final Wan-Animate-2 product decision** — potentially transformative video capability, but stop if evidence does not justify promotion.
7. **A production second image backend only when it brings measurable new capability**.
8. **Minimal resource preparation only when multi-backend production actually requires it**.
9. **Reusable qualification infrastructure before another large technology search cycle**.
10. **Controller reduction as a continuous tax on adjacent work, not a rewrite program**.

## Best actual execution sequence from the frozen baseline

```text
parallel: DIAG-GPU-130 ordinary-use XMP-OFF observation

1. Test Truth Repair
2. PR-ASSET-120 observational compatibility profiles
3. PromptPack/saved-settings structural audit
4. Wan-Animate-2 human verdict on existing artifact
5. FLUX.2 Klein 4B target qualification when GPU/platform gate permits
6. Image backend product decision
7. Wan-Animate-2 final promote/defer decision
8. Conditional second-backend production slice
9. Conditional minimal resource/preparation contract
10. Qualification common layer before the next broad candidate cycle

continuous: controller ratchet and opportunistic responsibility extraction
```

The sequence intentionally puts several low-risk, high-frequency improvements ahead of another GPU-heavy research campaign while the platform stability baseline is still being observed.

---

# 12. Bottom line

The most valuable StableNew strategy is no longer “keep adding features” or “clean up the repo before doing features.”

It is:

> **make evidence trustworthy → improve daily image configuration quality → qualify the best current modern image opportunity → force the directed-motion research into a product decision → productionize only technologies that demonstrate measurable new value → pay down architecture debt only where it reduces the cost/risk of that value.**

The largest new conclusion from this research is that **the image roadmap deserves a fresh candidate-selection checkpoint**. Ideogram 4 remains technically valid evidence, but FLUX.2 Klein 4B now appears to offer a better value proposition for StableNew to test first because it combines permissive Apache-2.0 licensing, generation, editing, consumer-GPU intent, and existing Diffusers/Comfy support. Its fit on the exact 12-GB target is unproven, so the recommendation is qualification—not integration.

---

# 13. Evidence index

## StableNew repository authority

- `AGENTS.md`
- `STATUS.md`
- `docs/CODEX_MAP.md`
- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/AGENT_OPERATING_MODEL.md`
- `.github/agents/stablenew-researcher.agent.md`
- `.github/agents/stablenew-architect.agent.md`
- `.github/agents/stablenew-verifier.agent.md`
- `.github/agents/stablenew-release.agent.md`

## Existing StableNew evidence

- `docs/Research/2026-09-26_StableNew_Critical_Weaknesses_Predecisional.md`
- `docs/Subsystems/Runtime/DIAG-GPU-130_Post_5600_Black_Screen_Recurrence.md`
- `docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`
- `docs/Subsystems/Image/PR-IMG-110R_Ideogram4_Requalification.md`
- `docs/Subsystems/Image/PR-ASSET-110_Local_Asset_Registry.md`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/Subsystems/Video/PR-VID-150_Wan22_Motion_Characterization.md`
- `docs/Subsystems/Video/PR-VID-184_Wan_Animate_2_Reference_Target_Hardware_Integration_Feasibility.md`
- `docs/Subsystems/Video/PR-VID-184R_Wan_Animate_2_Pinned_Memory_Readjudication.md`
- `tools/ci/controller_surface_baseline.json`

## Current external primary/upstream research

### FLUX.2 Klein 4B
- https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B
- https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8

### Qwen-Image-2.1
- https://huggingface.co/Qwen/Qwen-Image-2.1
- https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE
- https://github.com/huggingface/diffusers/blob/main/docs/source/en/api/pipelines/qwenimage21.md

### Ideogram 4
- https://huggingface.co/ideogram-ai/ideogram-4-nf4-diffusers

### Wan-Animate-2
- https://github.com/Wan-Video/Wan-Animate-2

---

## 14. Report status

**PRE-DECISIONAL RESEARCH ONLY.**

This document does not change the approved StableNew roadmap, authorize the candidate work-package queue, choose FLUX.2 Klein as a production backend, authorize another Wan-Animate-2 run, authorize user PromptPack mutation, or resolve DIAG-GPU-130.

