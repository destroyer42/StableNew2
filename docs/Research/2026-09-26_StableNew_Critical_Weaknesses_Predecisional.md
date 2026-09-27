# StableNew Critical Weaknesses and Sequencing Assessment

> **PRE-DECISIONAL RESEARCH — NOT ROADMAP, STATUS, ARCHITECTURE, OR IMPLEMENTATION AUTHORITY**
>
> This document is research context only. It does not authorize implementation, change the approved roadmap, select a backend, alter the canonical runtime, or supersede STATUS.md, AGENTS.md, CODEX_MAP.md, architecture/testing authority, or an owner decision. Any recommendation below must be converted into a bounded work package and separately authorized before implementation.

**Assessment date:** 2026-09-26 ET  
**Repository assessed:** destroyer42/StableNew2  
**Frozen remote baseline:** main @ 0a2bb505acdb381726a401d9e74281e362fc44ea  
**Latest integrated change on baseline:** PR #10 / PR-VID-184R Wan-Animate-2 pinned-memory re-adjudication  
**Research branch:** research/critical-weaknesses-2026-09-26  
**Scope:** recent work, current roadmap/status, unfinished work, technical debt, required/informational CI, recent qualification evidence, current upstream technology where it materially changes the conclusion.

## 1. Method and authority

The review followed current repository authority, not old chats or earlier plans:

1. Current remote main/SHA and recent PR/CI state.
2. AGENTS.md and STATUS.md.
3. docs/CODEX_MAP.md.
4. docs/ARCHITECTURE_v2.6.md, docs/StableNew_Coding_and_Testing_v2.6.md, docs/StableNew Roadmap v2.6.md, subsystem acceptance/diagnostic records, and current tests/source.
5. External current research only where it changes the interpretation of current technology or risk.

The canonical architecture remains unchanged:

Intent → Compiler → immutable NJR → JobService → SQLite Queue/Repository → PipelineRunner.run_njr → Handler/Executor → Artifact/History.

This assessment does **not** recommend a second queue, runner, history store, compiler, cancellation authority, or process owner. It also does not recommend migrating the accepted A1111 still-image path to ComfyUI.

### Important limitations

- This review can see the current GitHub repository and CI, but not an uncommitted local Windows worktree. The frozen evidence base is therefore remote main @ 0a2bb505...
- The user-scoped PromptPack library under %LOCALAPPDATA% was not scanned in this research package. PromptPack content-hygiene findings below are therefore a verified product capability gap plus previously observed operator pain, not a fresh quantitative census of the local library.
- No GPU workload, stress test, driver/BIOS/XMP change, model installation, process mutation, or production runtime change was performed.
- No product source or canonical authority document is changed by this report.

## 2. Executive conclusion

StableNew's **core architecture is materially healthier than its age and breadth suggest**. Queue-first submission, immutable NJRs, SQLite lifecycle authority, the sole public PipelineRunner.run_njr production entry, managed/external runtime ownership, versioned JSON PromptPacks, backend-neutral image/video contracts, the local asset registry, and human-controlled learning are all significant strengths.

The biggest present risks are concentrated elsewhere:

- **Reliability confidence:** the workstation still has an unresolved black-screen/GPU-loss failure family, and recent high-memory video qualification found an additional device-loss mode under very high Windows commit pressure.
- **Verification confidence:** required Python 3.11/3.12 CI passes, but the broader full suite and several semantic GUI journeys are currently failing for identifiable harness/integration-test reasons, reducing the value of non-required regression signals.
- **Maintainability:** the deprecated AppController remains 7,782 physical lines under the controller ratchet and PipelineController remains 1,785 lines.
- **Product capability:** accepted production video remains native SVD XT; directed/reference-bound locomotion remains experimental or qualification-only.
- **Backend expansion readiness:** resource/residency needs are currently represented by backend-specific guards and runtime transition policy rather than a minimal common resource-requirement contract.
- **Compatibility debt:** the historical video stage bridge still creates dual routing.
- **Research efficiency:** the video qualification line has produced useful evidence, but it has accumulated many bespoke qualification packages without one reusable promotion/defer framework.
- **Asset/prompt intelligence:** asset identity is now strong, but compatibility metadata and semantic PromptPack hygiene remain unfinished.
- **Agent/roadmap signal:** current truth exists, but roadmap frontier text and metadata can lag the actual accepted state, increasing the chance of agent rediscovery or wrong-next-step work.

The correct response is **not** a broad rewrite. The highest-return path is to restore trustworthy verification, continue controlled hardware isolation, reduce controller concentration incrementally, close the current video R&D decision loop, and only then expand production backend scope.

## 3. Top 10 current weaknesses/failings

### 1. Unresolved workstation/GPU/platform instability

**Evidence.** DIAG-GPU-130 records repeated black-screen/display-loss incidents with LiveKernel 141/1B8 evidence and a disappearance of GPU telemetry while StableNew/A1111 work was active. The package correctly does not attribute cause. DDR5-5600 alone did not eliminate recurrence. XMP-OFF is currently an observation-only isolation. PR-VID-184 separately observed a lost-device state during a Wan-Animate-2 qualification run while Windows commit was approximately 95–98%; PR-VID-184R completed the byte-identical workload with only pinned memory disabled, materially implicating that resource path without proving it as the sole cause.

**Why this is critical.** A hard display/device loss can corrupt evidence, interrupt queue execution, and make every high-load backend experiment ambiguous. It also makes “works on this GPU” a weaker production claim until the platform baseline is better bounded.

**Top action.** Keep DIAG-GPU-130 as the controlling diagnostic: continue ordinary-use XMP-OFF observation; if recurrence occurs, preserve evidence and change exactly one platform variable next. Do not combine driver, HAGS, power, BIOS, PCIe, memory, and GPU changes. Do not deliberately stress test unless separately authorized.

**Independent appraisal: CONFIRMED.** This is not merely a Wan/Comfy problem: the black-screen family predates Wan-Animate-2 and occurred during A1111. Conversely, PR-VID-184R shows the Wan device-loss event had a resource-path component that can be mitigated independently. The correct conclusion is twofold: platform stability remains unresolved, while pinned-memory handling is a specific additional risk for large Comfy workloads.

**Higher-order effects.**
- 2nd order: delaying high-risk GPU qualification reduces new evidence volume but increases the interpretability of the next incident.
- 3rd order: if XMP-OFF ordinary use remains stable for a meaningful exposure interval, future backend failures become easier to attribute to workload/resource paths; it still would not prove RAM/XMP was the root cause.
- 4th order: if instability persists across a clean platform baseline, hardware substitution or electrical/power-path testing becomes higher-value than repeated software tuning.
- Product consequence: backend promotion criteria should require not only successful output, but a stable resource envelope on the supported target machine.

**Condition to proceed.** Observation is active now. Any new deliberate high-load GPU test should require an explicit owner decision and should not introduce a second uncontrolled platform change.

---

### 2. Non-required CI and semantic journey tests currently provide a degraded regression signal

**Evidence.** On the PR-VID-184R head, the required StableNew CI jobs for Python 3.11 and 3.12 passed. However:
- informational full-suite jobs failed;
- the Journey Tests workflow failed;
- JT03/JT04/JT05/JT06 repeatedly timed out waiting for repository-backed history;
- logs show those mocked GUI journeys probing real 127.0.0.1:7860, entering WebUI readiness ERROR, and deferring queue autostart;
- the full-suite Linux run hit pytest INTERNALERROR because pathlib attempted to instantiate WindowsPath;
- tests/api/test_webui_process_manager.py monkeypatches src.api.webui_process_manager.os.name to "nt". Because the imported os module is a shared module object, this is a credible direct cause of global platform identity leakage into pathlib during the test.

**Why this is critical.** Required CI still protects the accepted gate, so this is not “the repository has no test safety.” The weakness is that broader integration/journey evidence is noisy or broken exactly where StableNew increasingly depends on cross-layer GUI → compiler → queue → runner → history behavior.

**Top action.** Split the repair into two bounded failure classes:
1. eliminate global platform mutation in the WebUI process-manager test by testing a module-local platform seam/helper rather than mutating os.name;
2. repair the deterministic journey harness so fake/mock backend readiness is injected at the correct production boundary and GUI journeys do not accidentally depend on a live A1111 endpoint.

After those two repairs, rerun the affected journeys and full suite. Only then decide whether any remaining failures are product defects versus legacy test debt.

**Independent appraisal: CONFIRMED, with scope correction.** Initial suspicion that recent PRs bypassed required CI was **refuted**: the required 3.11/3.12 jobs actually passed. The valid issue is degraded *additional* verification, not a violated required gate.

**Higher-order effects.**
- 2nd order: fixing the test seam may reveal real failures previously hidden behind the readiness timeout.
- 3rd order: once deterministic journeys are trustworthy, controller extraction and backend integration become materially safer and need less duplicated manual verification.
- 4th order: if journey tests become reliable enough, selected high-value journeys can eventually be considered for stronger gating without making real GPU/backends part of CI.
- Risk: fixing tests by bypassing production seams would create false confidence. The harness must use ordinary production submission/runner/history boundaries and mock only external transport/runtime readiness.

**Condition to proceed.** This is the highest-value immediate code package because it is GPU-independent and improves evidence quality for all later work.

---

### 3. Controller concentration remains a severe maintainability and change-risk hotspot

**Evidence.** tools/ci/controller_surface_baseline.json currently allows:
- src/controller/app_controller.py: 7,782 physical lines;
- src/controller/pipeline_controller.py: 1,785;
- src/controller/job_service.py: 1,246;
- src/controller/job_history_service.py: 647.

AppController is explicitly described in source as deprecated/legacy for GUI skeleton compatibility, yet it still coordinates a very broad surface: runtime/process state, queue interactions, diagnostics, learning, curation, image/video workflows, settings, and GUI coordination.

**Why this is critical.** StableNew's architecture is intentionally strict about ownership. A very large coordinator increases the probability that a small feature crosses queue, runtime, GUI, or persistence boundaries accidentally. It also increases agent context cost and makes independent review harder.

**Top action.** Continue the existing ratchet; do **not** rewrite AppController. Every package that touches AppController/PipelineController should:
- first use existing app_controller_services / pipeline_controller_services extraction homes where ownership is clear;
- prefer net LOC/responsibility reduction;
- lower the ratchet ceiling whenever a controller shrinks;
- add no new inline domain logic;
- extract one cohesive responsibility at a time with focused tests.

A dedicated extraction package is justified only for a responsibility with clear ownership and high churn; it should not be a general “clean up the controller” epic.

**Independent appraisal: CONFIRMED.** The ratchet has prevented growth, but a 7.8k-line deprecated coordinator is still a structural risk. The repo has already selected the correct mitigation pattern: strangulation/extraction, not replacement.

**Higher-order effects.**
- 2nd order: extraction lowers token/context cost for future agents and makes review more local.
- 3rd order: clearer ownership reduces the temptation to create parallel services/authorities.
- 4th order: after enough extraction, AppController can become a thin compatibility shell and its ceiling can fall rapidly; attempting that end state directly would be substantially riskier.
- Risk: extracting before test signal is repaired can move defects rather than reduce them.

**Condition to proceed.** Make #2 the prerequisite for any dedicated controller-decomposition package. On ordinary feature work, keep the ratchet active immediately.

---

### 4. Production video capability still does not satisfy the directed/reference-bound motion goal

**Evidence.** Native SVD XT remains the only accepted production video backend. The experimental Wan2.2 TI2V path can generate materially more motion but did not reliably produce whole-body locomotion. The Animate qualification line progressively established resource feasibility, interpretable output, real driving-pose behavior, and then Wan-Animate-2 local execution with pinned memory disabled. PR-VID-184R still classifies model capability as PARTIAL/unadjudicated because one required motion-correlation metric missed threshold and the human visual verdict gate has not been performed.

Current external evidence supports continuing to take Wan-Animate-2 seriously: the official Wan-Video/Wan-Animate-2 project released inference scripts and Base/Distillation weights on 2026-08-07 and describes direct driving-video consumption plus text-driven viewpoint control. The repository is Apache-2.0. That makes it a credible technology candidate, not a dead end. It does not establish suitability on this target machine.

**Why this is critical.** The user's motivating video outcome is not “produce any MP4”; it is meaningful body/limb/action motion. StableNew can produce accepted SVD clips, but the product-value gap that drove the recent research remains open.

**Top action.** Close the existing decision loop before starting a new candidate search:
1. perform the already-identified human visual verdict on the existing PR-VID-184R artifact — no new GPU work;
2. if the visual verdict is promising and DIAG-GPU-130 permits further deliberate testing, authorize at most one controlled replicate/second-seed or representative-length run with the same pinned-memory mitigation;
3. then make an explicit owner decision: promote to a bounded experimental StableNew workflow, defer pending hardware/ecosystem change, or reject this candidate for the current target.

Do not start another long characterization chain without that decision.

**Independent appraisal: CONFIRMED.** “Integrate Wan-Animate-2 now” is not validated. “Close the Wan-Animate-2 adjudication and either promote or defer” is validated.

**Higher-order effects.**
- 2nd order: a promotion creates demand for resource-policy, environment-provenance, GUI capability exposure, and replay tests.
- 3rd order: a defer decision frees engineering capacity for reliability, image/asset intelligence, and controller debt instead of allowing sunk-cost continuation.
- 4th order: if target hardware changes later, the retained frozen qualification evidence gives a clean re-entry point without rediscovering the entire candidate.
- Risk: repeated one-off seeds can create false confidence; a second run should answer a specific uncertainty, not become an open-ended benchmark program.

**Condition to proceed.** Human verdict can happen immediately. New GPU execution should wait for explicit authorization and should respect the active platform-isolation state.

---

### 5. Multi-backend resource/residency requirements are not yet a first-class minimal contract

**Evidence.** StableNew already has two useful mechanisms:
- PR-RUNTIME-100 coordinates release of conflicting StableNew-owned runtimes before the selected backend prepares;
- experimental Wan workflow_readiness has an observe-only resource guard and explicitly is not a scheduler/lease.

However, resource needs remain backend/workflow-specific. Ideogram 4 qualification required a particular staged residency sequence to fit the 12 GB card. Wan qualifications rely on explicit host-RAM/VRAM safeguards. PR-VID-184R shows a Comfy launch/runtime flag, --disable-pinned-memory, can materially change viability. The current upstream ComfyUI CLI still exposes --disable-pinned-memory, --disable-dynamic-vram, --fast-disk, VRAM reservation/headroom controls, and related offload settings. Current ComfyUI issues #14250 and #15255 also document HostBuffer/pinned-memory failure families where disabling pinned memory is a working mitigation for some affected configurations.

PyTorch's August 2026 pinned-memory developer note explains why pinned buffers can have long lifetimes and why allocators may intentionally retain them, reinforcing that host pinned memory is not equivalent to ordinary pageable RAM.

**Why this is critical.** As long as A1111 is the only production image backend and SVD is the production video backend, bespoke guards are tolerable. The moment StableNew promotes a second heavy production backend, resource requirements become part of correct backend selection and preparation.

**Top action.** Before a second heavy production backend is authorized, define a **minimal typed backend resource/preparation profile**, not a general scheduler. Candidate fields should be limited to evidence-backed needs such as:
- conflicting owned-runtime releases;
- minimum physical RAM / commit headroom / VRAM headroom where required;
- required launch/runtime flags;
- model residency strategy identifier where correctness depends on load order;
- whether the backend is allowed only as experimental;
- fail-before-dispatch behavior and actionable operator message.

Keep it under backend capability/preflight ownership. It must not become a second lifecycle authority and must never adopt/kill external processes.

**Independent appraisal: CONFIRMED in reduced form.** An earlier idea to build a full GPU lease/scheduler now is **refuted as premature**. The justified work is only the smallest resource contract needed by an actually approved second backend.

**Higher-order effects.**
- 2nd order: resource requirements become inspectable and testable instead of being implicit in one harness.
- 3rd order: GUI can truthfully explain why a backend is unavailable without learning backend-specific memory rules.
- 4th order: future hardware profiles can reuse the same contract without changing queue/runner ownership.
- Risk: over-generalizing before two real production backends exist will create abstraction debt. Build only from demonstrated requirements.

**Condition to proceed.** Design research may continue now; implementation should be gated on owner authorization of a second production backend.

---

### 6. The historical video stage-owned backend bridge still creates dual-routing debt

**Evidence.** src/video/video_execution_resolver.py has the neutral canonical video_execution block, but retains LEGACY_STAGE_BINDINGS for svd_native, animatediff, and video_workflow. Repo authority states the bridge remains for the SVD producer, AnimateDiff, PromptPack/reprocess-built video_workflow stages, and historical replay. Its removal condition is explicit: every producer must compile neutral execution and historical replay normalization must be proven.

**Why this is critical.** This is bounded debt, not a present architecture violation. But every additional video backend increases the cost of carrying two ways to infer backend selection. Leaving it indefinitely risks backend identity once again becoming coupled to stage names.

**Top action.** Migrate remaining *producers*, not the resolver first:
1. SVD producer emits explicit neutral video_execution while retaining SVD behavior;
2. PromptPack/reprocess video_workflow producers emit neutral blocks;
3. decide whether AnimateDiff remains supported; if yes, neutralize it; if no, retire it through a separate compatibility decision;
4. add historical replay normalization/fixture coverage;
5. delete LEGACY_STAGE_BINDINGS and stage lookup only when all removal conditions are proven.

**Independent appraisal: CONFIRMED.** Because the bridge has a named removal condition and is not live fallback ambiguity, it ranks below reliability/test/controller risks. It is still important before adding multiple new video backends.

**Higher-order effects.**
- 2nd order: replay and producer tests must become stronger before deletion.
- 3rd order: once removed, backend capability selection becomes simpler and future backend addition no longer multiplies stage-routing cases.
- 4th order: CODEX_MAP and architecture become easier for agents to reason about, reducing accidental legacy-path edits.
- Risk: deleting too early would break historical replay or existing SVD/PromptPack production.

**Condition to proceed.** Start only after #2 restores trustworthy journey/integration evidence. Complete before or alongside promotion of another production video backend.

---

### 7. Video qualification evidence plumbing is too bespoke and lacks one reusable promotion/defer gate

**Evidence.** The current roadmap/status contains a long qualification lineage: VID-110, 130, 140, 150, 160A/B/C, 170, 175, 180, 181, 183, 184, and 184R. These packages have been disciplined and often excellent individually: frozen controls, hashes, resource telemetry, one-submission rules, no automatic replay, visual/metric gates, and explicit non-production boundaries. But those mechanisms are repeated across tools/qualification/vid* harnesses and documents rather than expressed as one reusable qualification framework.

**Why this is critical.** Bespoke harnesses increase implementation/review cost and make it easier for a future experiment to omit a safety or evidence field. More importantly, the product needs a stopping rule so qualification does not become the default response to ambiguous evidence.

**Top action.** Create a reusable **qualification-only** evidence harness/library that remains outside production runtime authority. Reuse only proven common concerns:
- source/control SHA locks;
- immutable run manifest;
- exact command/environment provenance;
- one-dispatch/no-retry guard;
- resource telemetry;
- managed-process ownership/teardown;
- output validation;
- metric collection hooks;
- required human-verdict field where objective metrics are insufficient;
- final classification with explicit PROMOTE / DEFER / REJECT / INCONCLUSIVE semantics.

Domain-specific graph construction and metrics should remain adapters. Production src/ must not import the qualification harness.

**Independent appraisal: CONFIRMED, but not as a rewrite of existing tools.** The value is consolidating common safety/evidence plumbing for *future* qualification, not refactoring every historical harness.

**Higher-order effects.**
- 2nd order: future candidate comparisons become cheaper and more comparable.
- 3rd order: qualification results become easier to consume in roadmap decisions and less likely to require agent rediscovery.
- 4th order: a formal exit classification counters sunk-cost continuation and prevents experimental tooling from drifting into production authority.
- Risk: if too generic, the harness can hide model-specific evidence needs. Keep domain adapters and allow a package to declare additional gates.

**Condition to proceed.** Do this before starting another multi-PR video-candidate research sequence. Do not block the no-GPU human verdict for PR-VID-184R.

---

### 8. Asset identity is strong, but compatibility/provenance intelligence is still unfinished

**Evidence.** PR-ASSET-110 established AssetRegistry as the sole offline local-file identity/discovery authority using SHA-256 identity and safe metadata reading. Its own documentation explicitly names the next package: PR-ASSET-120 — Provenance-Rich Asset Metadata Enrichment and Compatibility Profiles, observational until separately authorized for recommendations.

That missing layer matters because identity alone cannot answer:
- whether a VAE is appropriate/required for a checkpoint;
- whether a LoRA/embedding targets SDXL versus SD1.x or another family;
- whether an adapter has known trigger words/base-model expectations;
- whether two filenames are the same bytes or merely similarly named;
- whether a referenced asset is installed but not exposed by the live A1111 instance.

**Why this is critical.** StableNew increasingly supports learning, saved PromptPacks, and reusable settings. Bad model/adapter combinations waste compute and contaminate learning evidence because the system may learn from an invalid configuration rather than from the intended variable.

**Top action.** Execute the already-defined PR-ASSET-120 boundary first as observational metadata/profile enrichment:
- base architecture/family;
- content hash/provenance;
- embedded metadata where trustworthy;
- source confidence;
- VAE relationship evidence;
- adapter compatibility hints with provenance/confidence;
- missing/ambiguous metadata states.

Do not auto-select or rewrite jobs in PR-ASSET-120. A later, separately authorized resolver can offer recommendations with explicit operator override after evidence quality is proven.

**Independent appraisal: CONFIRMED.** This is more valuable than building another scanner because the scanner/identity problem is already solved. The missing value is semantic compatibility.

**Higher-order effects.**
- 2nd order: PromptPack audits can distinguish “missing asset” from “installed but likely incompatible.”
- 3rd order: Learning can exclude uncontrolled experiments caused by incompatible adapters.
- 4th order: future backend-neutral model catalogs can reuse stable content identity/provenance without making A1111 names canonical.
- Risk: metadata from filenames/CivitAI-style conventions can be wrong. Confidence/provenance must be first-class, and network enrichment should remain a separate decision.

**Condition to proceed.** This is safe offline work and can follow #2 or run as a separate low-GPU lane. Recommendation/autoselection must remain a later decision.

---

### 9. PromptPack storage hygiene is solved, but semantic/content hygiene is not

**Evidence.** PR-PACKS-001 converged production PromptPack storage, migration backups/quarantine, and user-data authority. Schema/serialization validation exists. Repo search does not reveal a dedicated semantic PromptPack linter for empty/meaningless packs, normalized duplicates, contradictory/redundant prompt terms, or model/adapter compatibility. Several legacy repository pack backups also illustrate how old artifacts can survive even after authority moves, though they are not current runtime authority.

**Why this is critical.** Prompt quality is upstream of every generated artifact. A technically valid JSON pack can still be useless, redundant, internally contradictory, or configured with incompatible assets. That creates direct operator friction and poor outputs while also degrading experiment/learning signal.

**Top action.** Add a **non-destructive PromptPack audit** in stages:
1. structural content checks that do not require semantic AI judgment: empty packs/slots, exact duplicate content, normalized duplicate content, missing referenced assets, dead aliases, impossible enum/config values;
2. compatibility checks after PR-ASSET-120: model family versus VAE/LoRA/embedding/profile;
3. advisory semantic checks: repeated tokens, obvious positive/negative contradictions, excessive redundant boilerplate, duplicate variants that cannot change execution.

Results should be warning classes with evidence. Repairs should use existing backup/quarantine/storage authority and require operator confirmation. Do not autonomously rewrite creative prompt text.

**Independent appraisal: CONFIRMED as a capability gap; local severity needs a fresh census.** The storage architecture is **not** broken and should not be rewritten. The unimplemented semantic/content audit is the valid weakness.

**Higher-order effects.**
- 2nd order: fewer invalid jobs and easier pack selection.
- 3rd order: cleaner experimental inputs improve Learning recommendation quality.
- 4th order: once compatibility/profile data is stable, StableNew can provide “why this is risky” guidance without making prompts/backend choices for the user.
- Risk: semantic contradiction detection can be subjective. Keep it advisory and distinguish hard-invalid from likely-low-value.

**Condition to proceed.** Structural audit can be designed now. Compatibility audit should follow #8. Any bulk repair requires a local user-data census and explicit confirmation.

---

### 10. The current decision frontier is harder to read than it should be

**Evidence.** STATUS.md content is substantially current and includes PR-VID-184R, so the hypothesis that STATUS is materially stale is false. However its header date lags the latest integrated evidence, and the roadmap's “Next action” section still begins from already-completed post-v2.6 packages before describing later state. STATUS also carries a very large amount of chronological acceptance narrative.

**Why this matters.** StableNew deliberately uses repo-local documentation as the shared brain for agents. When frontier information is buried among completed history, agents spend tokens rediscovering state and are more likely to propose already-completed work.

**Top action.** Perform a docs-only frontier hygiene package:
- update dates only when content actually changes;
- make the first current-state section explicitly list “active diagnostic,” “current owner decision,” “next authorized engineering objective,” and “blocked/deferred”;
- keep deep qualification narratives in subsystem records and summarize them in STATUS with links;
- update the roadmap “Next action” tail to the current frontier without changing approved priorities;
- do not create a second roadmap/status document.

**Independent appraisal: CONFIRMED at low severity.** The strong initial claim “canonical status is stale” is **refuted**. The real issue is information compression/frontier clarity, so this ranks tenth rather than near the top.

**Higher-order effects.**
- 2nd order: lower agent rediscovery/token cost.
- 3rd order: fewer stale work packages and fewer accidental scope jumps.
- 4th order: cleaner status makes the proposed reusable qualification framework more valuable because detailed evidence can live out of the main status narrative.
- Risk: over-pruning STATUS can remove useful accepted evidence. The rule should be summary + durable link, not deletion of truth.

**Condition to proceed.** Docs-only and low risk. Do it after this report is reviewed and after the current video owner decision so the frontier can be written once rather than churned repeatedly.

## 4. Hypotheses explicitly refuted or narrowed

The independent review rejected several initially plausible recommendations:

### A. “Recent video PRs were merged without required CI”
**REFUTED.** PR body checkboxes were not reliable evidence of final run state. GitHub Actions for the PR-VID-184R head show required Python 3.11 and 3.12 jobs passed. The defect is the failing informational/full journey signal, not required-gate bypass.

### B. “STATUS.md is materially stale”
**REFUTED.** STATUS contains the current PR-VID-184R result and XMP-OFF diagnostic state. Only its header/frontier compression and roadmap-tail wording lag.

### C. “Build a full GPU scheduler/lease now”
**REFUTED as premature.** StableNew already has owned-runtime transition and observe-only resource readiness. A full scheduler would add authority and complexity before a second production heavy backend is approved. The validated recommendation is a minimal backend resource/preparation profile only when real requirements justify it.

### D. “Move still-image execution to ComfyUI to gain modern model support”
**REFUTED.** A1111 remains the accepted still-image production path and backend neutrality already exists at the execution contract. New image backends should be added only for demonstrated product value; they should not force migration of current A1111 work.

### E. “PromptPack architecture/storage needs another rewrite”
**REFUTED.** JSON authority, deterministic compile, storage hygiene, backup/quarantine, and user-scoped authority are already established. The remaining gap is semantic/content hygiene and asset compatibility, not storage ownership.

## 5. Cross-cutting external research findings

### 5.1 ComfyUI pinned memory is a real current ecosystem risk, not a StableNew-only anomaly

Current upstream evidence materially strengthens PR-VID-184R's interpretation:

- ComfyUI issue #14250 (June 2026) reports Wan 2.2 HostBuffer/OOM failures fixed by --disable-pinned-memory for that reporter.
- ComfyUI issue #15255 (August 2026) tracks dynamic-VRAM/HostBuffer failures; maintainer guidance includes --disable-pinned-memory for affected configurations, and the thread distinguishes multiple failure classes including single-GPU high-RAM/commit-pressure reports.
- Current ComfyUI CLI still exposes --disable-pinned-memory, --disable-dynamic-vram, --fast-disk, VRAM headroom/reservation, and asynchronous offload controls.
- Current ComfyUI model-management code contains explicit Windows pin-pressure/eviction logic and comments about Windows commit-charge/system destabilization risks during model loading.
- PyTorch's 2026 pinned-memory developer note explains that pinned-memory allocators may retain memory for asynchronous transfers/CUDA graphs, so “the operation finished” does not necessarily imply immediate host-memory release.

**Implication for StableNew:** keeping pinned-memory settings as evidence-backed backend preparation/configuration is reasonable if Wan/Comfy becomes production-capable; hard-coding a universal “disable pinned memory” rule is not justified.

### 5.2 Wan-Animate-2 remains a credible current candidate

The official Wan-Video/Wan-Animate-2 project released inference scripts and model weights on 2026-08-07. It is specifically designed around driving-video character animation and text-driven viewpoint control and is Apache-2.0 licensed.

**Implication for StableNew:** the correct next action is adjudication, not dismissal based only on the first failed local attempt. PR-VID-184R already changed the resource-feasibility evidence. Capability still must meet StableNew's own target-hardware and motion-quality gates.

### 5.3 Ideogram 4 is technically viable but does not create an urgent production-backend mandate

Current Ideogram 4 NF4 artifacts support Diffusers/CUDA and StableNew's PR-IMG-110R showed a constrained target-hardware pass. However Ideogram's current model agreement is explicitly non-commercial. Its public model card also labels NF4 as CUDA/Diffusers supported under the non-commercial license.

**Implication for StableNew:** the image-neutral contract is valuable, but PR-IMG-120 should remain conditional on an owner decision about product value, residency complexity, and license suitability. Do not let “backend neutrality exists” become pressure to integrate a second image backend merely to prove the abstraction.

## 6. Prioritized execution sequence

Risk severity and execution order are not identical. Hardware stability is the highest-severity risk, but its current authorized action is observation rather than active code work. The recommended sequence is:

### Sequence 0 — Maintain the safety baseline now
- Continue DIAG-GPU-130 XMP-OFF ordinary-use observation.
- No deliberate stress/GPU retest unless separately authorized.
- Preserve new incident evidence if recurrence occurs.

### Sequence 1 — Restore trustworthy non-required verification
**Do next as the primary engineering package.**
- Fix global os.name mutation / WindowsPath full-suite failure.
- Fix deterministic GUI journey backend-readiness injection.
- Run focused affected tests, then the normal required gate, then one aggregate journey/full-suite verification.
- Stop if a newly exposed product failure is a materially different failure class.

**Exit condition:** affected journeys execute through queue/runner/history with deterministic fake transport/runtime; full suite no longer crashes from platform identity leakage; remaining failures are individually classifiable.

### Sequence 2 — Tighten the development change surface
- Enforce controller ratchet on all touched work.
- If test evidence is now reliable, extract one high-churn cohesive AppController responsibility using existing service homes.
- Do not start a big-bang controller rewrite.

**Exit condition:** controller ceilings never grow; any dedicated extraction lowers a named ceiling and preserves behavior.

### Sequence 3 — Standardize qualification safety/evidence before another research tranche
- Build only the reusable qualification evidence plumbing needed by future candidate work.
- Keep it tools-only/read-only with respect to production authority.

**Exit condition:** a future qualification can declare frozen inputs, one-run policy, telemetry, output/metric/human gates, and final promote/defer/reject classification without cloning another entire harness.

### Sequence 4 — Close the current Wan-Animate-2 decision
- First: human visual verdict on existing PR-VID-184R output.
- If promising and platform state permits: one explicitly authorized controlled replicate/second seed or representative case.
- Make a product-owner PROMOTE / DEFER / REJECT decision.

**Exit condition:** no more open-ended “one more characterization” without a new decision question.

### Sequence 5A — If Wan-Animate-2 or another heavy backend is promoted
1. define the minimal backend resource/preparation profile;
2. prove managed/external process ownership is unchanged;
3. neutralize remaining video producers and replay path as necessary;
4. remove the legacy stage bridge only after its explicit removal conditions are met;
5. add capability-aware GUI exposure only after the backend truly exists.

### Sequence 5B — If Wan-Animate-2 is deferred/rejected
- Stop video backend integration work.
- Preserve evidence and redirect capacity to reliability, test confidence, asset compatibility, PromptPack hygiene, and controller debt.

### Sequence 6 — Complete asset compatibility intelligence
- Execute observational PR-ASSET-120.
- No automatic recommendations in the first package.

### Sequence 7 — Audit and clean PromptPack content
- Run structural duplicate/empty/missing-reference checks first.
- Add model/adapter compatibility checks after asset profiles exist.
- Keep semantic contradiction/redundancy checks advisory.
- Use backup/quarantine and explicit operator confirmation for repair.

### Sequence 8 — Refresh current frontier documentation
- Update STATUS/frontier summary and roadmap next-action tail after the current owner decision.
- Do not turn this research report into canonical status automatically.

## 7. Recommended stop/go gates

### New production video backend: GO only if
- model capability meets explicit motion/identity/anatomy/temporal gates;
- target-hardware execution has a repeatable safe envelope;
- DIAG-GPU-130 does not make the evidence uninterpretable;
- backend resource/preparation requirements are explicit;
- execution stays through canonical NJR → JobService → SQLite → PipelineRunner.run_njr → resolver/backend;
- managed/external process ownership rules remain intact;
- replay/history/artifact semantics are proven;
- required CI and repaired deterministic journeys are green.

### New production image backend: GO only if
- it provides product value that A1111 cannot reasonably provide;
- license is acceptable for the intended use;
- residency/resource behavior is bounded on target hardware;
- backend payloads stay inside the adapter;
- A1111 remains available and is not silently displaced;
- no second lifecycle/queue/runner authority is created.

### Controller extraction: GO only if
- one responsibility has a clear destination owner;
- test evidence around the responsibility is reliable;
- the extraction lowers the existing ceiling or removes inline responsibility;
- it does not create a shadow coordinator.

### Prompt/asset automation: GO only if
- identity/provenance is separated from recommendation policy;
- confidence and source are preserved;
- hard-invalid versus advisory-warning is explicit;
- user override remains available;
- no auto-deletion or autonomous creative rewrite occurs.

## 8. Suggested work-package queue (pre-decisional)

This is **not** an approved roadmap. It is a candidate queue derived from the evidence:

1. **Test Truth Repair — platform identity + deterministic journey readiness**
   - Model/execution class: Luna High or Terra Medium; Local/Desktop if reproducing Tk journey behavior.
2. **Controller Ratchet Extraction — one named responsibility only**
   - Terra Medium/High depending on surface.
3. **Qualification Harness Common Evidence Layer**
   - Terra High; tools-only, no production authority.
4. **Wan-Animate-2 Final Adjudication**
   - human verdict first; any GPU replicate requires separate owner authorization; Terra High/Sol Medium only if lifecycle ambiguity emerges.
5. **Backend Resource/Preparation Profile**
   - only after a second backend promotion decision; Sol Medium because ownership/residency boundaries are architectural.
6. **Video Legacy Bridge Retirement**
   - Terra High, after producer/replay proof.
7. **PR-ASSET-120 — Provenance-Rich Asset Metadata Enrichment and Compatibility Profiles**
   - Terra High; observational.
8. **PromptPack Semantic Hygiene Audit**
   - Terra Medium/High; structural first, compatibility after asset profiles.
9. **Current Frontier Documentation Hygiene**
   - Luna Medium; docs-only.

## 9. Evidence index

### Repository authority / current state
- AGENTS.md
- STATUS.md
- docs/CODEX_MAP.md
- docs/ARCHITECTURE_v2.6.md
- docs/StableNew_Coding_and_Testing_v2.6.md
- docs/StableNew Roadmap v2.6.md
- docs/AGENT_OPERATING_MODEL.md

### Reliability / GPU
- docs/Subsystems/Runtime/DIAG-GPU-130_Post_5600_Black_Screen_Recurrence.md
- docs/Subsystems/Video/PR-VID-184_Wan_Animate_2_Reference_Target_Hardware_Integration_Feasibility.md
- docs/Subsystems/Video/PR-VID-184R_Wan_Animate_2_Pinned_Memory_Readjudication.md

### Test evidence
- GitHub Actions StableNew CI run 36289796673 on PR-VID-184R head 0dac75ccfb324a507f0ee5b9f047d88a186b4ae2
- GitHub Actions Journey Tests run 36289796708 on the same head
- tests/api/test_webui_process_manager.py
- tests/journeys/conftest.py
- tests/journeys/journey_helpers_v2.py
- tests/journeys/test_jt03_txt2img_pipeline_run.py
- tests/journeys/test_v2_full_pipeline_journey.py

### Maintainability / routing
- tools/ci/controller_surface_baseline.json
- src/controller/app_controller.py
- src/controller/pipeline_controller.py
- src/video/video_execution_resolver.py

### Asset / PromptPack
- docs/Subsystems/Image/PR-ASSET-110_Local_Asset_Registry.md
- docs/StableNew Roadmap v2.6.md, PR-PACKS-001 section
- src/promptpacks/storage.py

### External current research
- PyTorch DevLog, “Pinned memory: what it is for, and why nobody gives it back,” 2026-08-09:
  https://docs.pytorch.org/devlogs/eager/2026-08-09-pinned-memory-allocator/
- ComfyUI issue #14250, Wan 2.2 HostBuffer/OOM fixed by --disable-pinned-memory for reporter:
  https://github.com/Comfy-Org/ComfyUI/issues/14250
- ComfyUI issue #15255, DynamicVRAM/HostBuffer Windows failure family and maintainer workarounds:
  https://github.com/Comfy-Org/ComfyUI/issues/15255
- Current ComfyUI CLI memory/offload flags:
  https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/cli_args.py
- Current ComfyUI memory management:
  https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_management.py
- Official Wan-Animate-2:
  https://github.com/Wan-Video/Wan-Animate-2
- Ideogram 4 NF4 Diffusers model card:
  https://huggingface.co/ideogram-ai/ideogram-4-nf4-diffusers
- Ideogram 4 non-commercial license:
  https://huggingface.co/ideogram-ai/ideogram-4-fp8/blob/main/LICENSE.md

## 10. Final assessment

The strongest conclusion from this review is that StableNew does **not** need another architectural reset. The canonical runtime and authority boundaries are comparatively mature. The current failure mode is a mismatch between that strong core and several expensive edges: unstable hardware evidence, weak broad-test signal, oversized coordinators, experimental video research that has not yet converted into a product decision, and incomplete semantic intelligence around assets/prompt content.

The highest-return strategy is therefore:

**stabilize evidence → shrink change risk → force a video promote/defer decision → add only the minimal resource contract required by an actually approved backend → retire bounded compatibility debt → improve asset/prompt intelligence.**

That sequence preserves the architecture that is working while directly attacking the areas that currently consume the most operator time, agent tokens, and diagnostic ambiguity.
