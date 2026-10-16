> **Priority supersession — 2026-10-16:** The original v1.1 ranking below was based on an incomplete critical-control audit. Its former #1 GPU residual-risk recommendation is **not** the current recommended first work. Read the end-of-file `2026-10-16 independent-audit adjudication (framework v1.2)` before using this document for decisions. Source findings do not prove historical incident causes; GitHub settings and local Windows/operator data have separate evidence limitations.

> **Historical record, corrected at integration on 2026-10-16:** The v1.1 report
> and v1.2 adjudication below preserve dated reasoning, not living STATUS or
> implementation instructions. The adjudication's unprotected-`main` claim is
> superseded by the [integration verification](#2026-10-16-integration-verification-and-governance-correction).
> All rankings require refreshed evidence and owner selection. Mandatory control
> coverage remains **PARTIAL**; this docs integration did not rerun the assessment.

# StableNew Comprehensive Product and Engineering Value Assessment — revised final pass (v1.1)

**Snapshot:** October 15, 2026, America/New_York; inspected remote `destroyer42/StableNew2` main at `d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e` (merge of PR #106). **Verdict:** broad-coverage **remote evidence assessment, PARTIAL physical/operator validation**. The local Windows worktree, real SQLite data, GPU/driver state, model paths, physical image/video output and real operator task timings were NOT accessible. No tests, inference, host probes, code changes, branch publication or external-process actions were performed. This is a rigorous prioritization analysis but **not** an end-to-end certified runtime audit.

## Executive decision

1. **Do not start a broad model-compatibility, GUI, test-slimming or Photo Optimize rewrite.** Their high-visibility historic problems have received substantial merged work. Further changes require a current reproduced gap.
2. **First disposition: GPU/host stability and queue-release residual risk.** The October 12 loss consumed 14 queued jobs and `PR-QUEUE-GPU-180` has since merged. The pure GPU classifier (`src/queue/gpu_loss_assessment.py`) confirms only host-reported loss; `gpu_loss_coordinator.py` releases only with explicit confirmation plus positive enumeration. Documented edge cases remain: suspected-only fault when NVIDIA still enumerates, unavailable `nvidia-smi`, and an immediate repeat context failure after release. Protect the queue first; separate hardware diagnosis from policy decisions. No physical job should be commissioned until the owner explicitly clears risk.
3. **Highest next user-outcome target after hardware clearance: directed human motion usefulness.** VID-192's one-source/one-seed controlled study did not deliver locomotion; VID-196 source-readiness UI is advisory only and never measured quality gain. A small owner-rated experiment is higher value than adding controls or another video backend without new evidence.
4. **Parallel low-cost evidence opportunities:** define a real operator critical-journey acceptance matrix and collect non-sensitive success/latency/failure evidence from existing projections; profile CURRENT CI and repeated repair toil before undertaking further slimming. Adopt this assessment process during normal closeouts; no recurrent ceremony.
5. **Low-cost canonical hygiene:** `STATUS.md` retains staging labels such as "VID-196 PR #104 open" and "PHOTO-223 local", while GitHub verifies #104 and #106 merged. Correct only affected lines in normal docs maintenance; never let stale text reorder work.

## Authority and evidence inventory

| Evidence | Observed result / limit |
|---|---|
| Remote source | Main `d43fdc39`, PR #106 merged 2026-10-16 02:46 UTC; source SHA pinned above; local branch/worktree unverified |
| Files/tree | 2,042 Git blobs: src 598, tests 946, docs 137, tools 200; size-only screening: `app_controller.py` 329,582 bytes; `executor.py` 301,620; `learning_controller.py` 177,183. **No churn-based hotspot ranking established.** |
| Governance | Read `AGENTS.md`, `STATUS.md`, `CODEX_MAP.md`, `AI_MODEL_SELECTION.md`, architecture, active roadmap and testing guide at pinned remote main |
| Recent merged status | #88 (model compatibility), #91 (global positive), #100 (GPU), #103 (Forge defaults), #104 (motion readiness), #105–106 (Photo Optimize) = merged, not new build candidates |
| CI | Latest inspected branch=main Actions listing contained a successful older run, NOT this exact HEAD. Recent PR reports contain bounded local/head CI evidence; **exact current-main integration verdict not independently obtained** |
| Code inspected | `src/queue/gpu_loss_assessment.py`, `gpu_loss_coordinator.py`, `backend_dependency.py`; `src/api/webui_failure_evidence.py`; `src/learning/model_comparison.py`; `src/video/workflow_motion_guidance.py`; `tools/ci/validation_plan.py` (read-only); selected subsystem docs and test evidence. Other source sampled via tree/docs; **not full source-code inspection** |
| Historic research | Phase B October 4 snapshot was reconciled against merged B1 and B2A rather than repeated as open work |
| Hardware/operator | No local worktree, Windows display, active A1111/Forge/Comfy, CUDA/GPU, datasets or user task recordings; absolute workflow success rates unknown |

## Critical journeys and outcome matrix

| Critical journey | Current deterministic state/evidence | Actual user-outcome verdict | Best additional proof |
|---|---|---|---|
| App launch/readiness | Explicit managed/external runtime policy; recent lifecycle PRs merged | Current workstation readiness **U** | Read-only health, ownership and cold-start operator journey |
| PromptPack/draft/model selection | 130A–C, 158–160 merged; `model_comparison.py` policy-driven candidate check, global positive once | Cross-model visual fidelity **U** | Current 3-family matrix with backend admission + output comparison where cleared |
| Queue/Run Now/restart/lineage | Single immutable NJR and SQLite authority, dispatch/evidence tests | Durable queue correctness has accepted test evidence; field recovery **U** | Disposable SQLite regression + actual operator acceptance (authorized) |
| GPU loss/claim isolation | `gpu_loss_assessment.py` host-confirmed only; coordinator operator + host gated | **D:** documented suspected-loss and post-release repeat exposure | Reproduce fake-host/transport counterexamples, inspect incident logs, decision on probation gate |
| Image output/refine/upscale | Forge backend and image integrity PRs; ADetailer/ControlNet contracts | Current quality improvements **U** | Blind operator ratings with controlled seeds/settings and decoded artifact checks |
| Review/photo/batch/history | PHOTO-222–223 merged, comprehensive deterministic persistence tests | Batch usefulness, migration and satisfaction **U** | Three-photo Windows task without touching real assets; user timing/errors |
| Learning/model comparison | Model policy and frozen-arm parity in code | Selected-best-output consistency **U** | Tested paired-arm operator rating protocol; no claim of generalized quality |
| Native SVD | Earlier acceptance known, MVP default preserved | Directed locomotion **not a justified SVD target** | 14-frame baseline for undirected motion only, if necessary |
| Wan/Animate 2 motion | VID-192 controlled one-sample failure of locomotion; 196 read-only guidance | **D:** useful human locomotion not established | Owner-rated reproducible A/B on selected target hardware after clearance |
| GUI controls/reachability | GUI-100 and 110 accepted; later GUI-111/112 fixes | Current small viewport friction **U** | Real Tk/Windows laptop viewport walkthrough |
| Development/CI | B1 replaced slow sleeps, B2A consolidated duplicates; `validation_plan.py` risk-aware | Current bottleneck **U** | Exact-SHA required/affected/full-census elapsed/test duration trend |
| Observability | Typed content-free failure evidence and job history; incomplete outcome telemetry | Value attribution **U** | Task-level baseline ledger from existing SQLite/projections, no new state authority |

## Revised category assessment and highest-value target in each (12-category coverage)

State key: **V** current code+contract directly inspected; **D** repo-documented residual not independently re-run; **H** hypothesis; **R** verified merged/resolved; **U** insufficient operator/runtime evidence. Priority: **P1** next decision-relevant, **P2** after prerequisite, **P3** adjacent/monitor, **R** no new work. Confidence concerns **problem**, not estimated financial ROI. Effort is a preliminary **small/medium/large** class, not an implementation estimate.

| # | Category | Highest justified target / direct owner seam | State / confidence | Priority & next falsification |
|---|---|---|---|---|
| 1 | Product outcomes | Directed, usable single-person motion; test task success vs requested human movement, not just clip validity | D / medium | **P1 conditional**: owner quality ratings of VID-192 sample and a bounded new trial after GPU clearance |
| 2 | Reliability / queue | Suspected device/context loss and post-release repeated-fault bounded containment; `gpu_loss_assessment.py` + `gpu_loss_coordinator.py` | V+D / high gap, uncertain incidence | **P1 safety decision**: fake-host fault matrix plus owner selection of release/probation behavior, without automatic retry |
| 3 | Model compatibility | Residual prompt loss, inline LoRA and cross-workflow admission where evidence says current behavior differs from user intent | R+H / low current defect confidence | **P2 conditional**: deterministic current Z-Image/Klein/SDXL matrix, not generic adaptation redo |
| 4 | Image quality/refine/provenance | Measurable face/hand/ControlNet improvement instead of new controls; protect positive-generation provenance | H / low | **P2**: blinded paired output rating, exact source/model/seed capture after physical clearance |
| 5 | Video/backend | Validate Animate-2 locomotion vs framing/crop/driving-video problem; reuse VID-196 evidence and VID-192 controlled protocol | D / medium | **P1 conditional**: one-variable cohort, no new backend, prompt-only guidance not credited as physical improvement |
| 6 | UX/Windows | User journey reachability and cognitive workload after GUI-100/110/111/112, including Photo Optimize and Video Workflow | R+U / medium | **P2**: measured real-Tk desktop task at compact resolutions; only fix reproduced current failure |
| 7 | Architecture | Avoid ownership growth in `AppController`/`executor.py`/Learning; incremental reduction with high-churn modification | V size / H cost | **P3 adjacent**: gather change-frequency+defect hotspot matrix before claiming a standalone refactor |
| 8 | Test/CI/DevEx | Exact-SHA CI duration/flake and test-selection truth, especially changed GUI → retained test lane routing; `validation_plan.py` | V+D / medium | **P2 diagnosis**: capture present lane coverage & repeat runs before new B3 slimming |
| 9 | Security & trust | Untrusted file/path sidecars and host tool lookup (Windows `shutil.which("nvidia-smi")` cwd search) in GPU recovery path | D / medium for hazard, low exploitability | **P2 adjacent to GPU**: read-only threat model + path-order provenance; repair only demonstrated unsafe trust boundary |
| 10 | Resource/performance | GPU fault response and useful clips per minute/VRAM rather than speculative model expansion | D+U / medium | **P2 after clearance**: characterize resource/quality under controlled settings; no driver/reset actions by default |
| 11 | Observability | End-to-end product result/quality and repair-cost ledger using existing queue/history and owner ratings | H / medium | **P1 enabling measurement**: minimal read-only critical journey outcomes; no new queue/history/store |
| 12 | Sequencing/KM | Reconcile stale staging status, index assessments, keep typed authority and dated reports separate | V / high | **P2 low effort**: docs-only pointer + surgical post-merge state correction, no broad docs churn |

## Risk disposition (do not average into generic benefit score)

**A. GPU-loss recovery (documented residual).** The classifier explicitly requires host evidence; unavailable/suspected evidence does not quarantine. Coordinator only releases with operator confirmation plus a fresh successful enumeration, not a CUDA-quality proof. In the same failure class, a poisoned but enumerating GPU could allow queue consumption; a first failure after release is not automatically re-quarantined. No proof of current recurrence exists. **Risk disposition:** keep current protection as accepted; owner may commission read-only incident/CPU-fake investigation. Introducing probation, consecutive-fault circuit breaker, changed release proof or managed restart requires explicit new product decision and focused acceptance. Never automatically resend an ambiguous generation POST; never restart external runtimes.

**B. Physical model and video inference.** October 12 GPU device-loss incident puts physical qualification on HOLD until owner authorizes safe testing after hardware state is understood. Neither an API check nor deterministic CI clears the risk. Do not claim a new backend/model is safe based on no test failures.

**C. File/asset/security.** PHOTO-223 has specific preserved-sidecar/path/readability protections, but concurrent external writers and legacy missing hashes remain explicitly qualified. These are contextual, not a demonstrated exploitable vulnerability; no blanket storage rewrite justified. Windows executable lookup in GPU probing merits a bounded security review, not an unverified critical alert.

**D. Data integrity/unknown dispatched HTTP.** Keep the existing fail-closed contract: never replay an ambiguous POST automatically; operator-reviewed new identity/lineage on replay only.

## Global opportunity portfolio (ranked after critique)

**Decision sequence rather than a single RICE total:**

1. **GATE-1 — Read-only GPU incident + release-policy adjudication (P1; problem evidence high; intervention uncertain).** Owner reviews actual post-180 incident logs and any continuing faults, assesses Win/NVIDIA readiness, reproduces fake-host suspect/clear/repeat scenarios and decides whether to keep policy or authorize a minimal probation circuit breaker. No hardware action is implicit. **Do not confuse with a P0 active failure**; P0 applies only on verified present repeated loss/data-integrity risk.
2. **OUTCOME-1 — Video motion quality evidence (P1 conditional on GATE-1).** Run one controlled, explicit physical study, owner-rated motion/adherence/identity/temporal stability vs current accepted references; choose improvement path only from measured result. A credible no-change finding is an allowed outcome.
3. **MEASURE-1 — Critical-journey outcome and operator acceptance checklist (P1 enabling; small-to-medium).** Read-only baseline across model preflight/queue/History, compact GUI, Photo and Video. Use current repository projections + user observations, with no new mutable production data store; fill absent frequency denominators before more product-feature prioritization.
4. **DEVEX-1 — Current CI selection/performance diagnosis (P2; small).** Compare exact code SHA required vs affected/full-census run durations and flaky/host-specific failures. Review GUI routing blind spot B2A observed; only propose slimming after measured impact. B1/B2A themselves **R**.
5. **UX-1 — Compact-workspace verification (P2 conditional; small).** Test real Windows geometry and critical end-to-end form reachability after GUI-110/112 and PHOTO-223; fix only if current failure reproduced. Broad facelift **not prioritized**.
6. **IMG-1 — Target-specific cross-model parity spot check (P2 conditional; small).** Current three-family matrix; safe prompt transformation semantics and explicit user notices; no unproven architecture rewrite. PR-158/159/160 **R**.
7. **IMG-QUALITY-1 — Controlled still-image/refinement qualification (P2 after clearance; medium).** Determine whether current face/hand/OpenPose/ADetailer actually improves usable outputs with blinded pairs.
8. **ARCH-1 — Change-hotspot measured extraction (P3 adjacent).** Controller/Executor size is a signal, but require recent git churn, defect and coupling evidence and an authorized adjacent feature; net reduction and ratchet only.
9. **SEC-1 — Untrusted-input/tool execution review (P2 adjacent to GATE-1).** Validate current path lookup behavior and actual working-directory adversary, then minimal repair if risk material.
10. **KM-1 — Surgical status-pointer hygiene (P2, trivial; fold into docs package).** Preserve current canonical definitions; stale PR snapshots do not establish progress.
11. **PHOTO-1 — Canceled review staging and user quality (P3).** PHOTO-223 notes empty staging directory debt; prioritize only on measured disk/toil impact or next photo change. **Do not reimplement merged promotion.**

### Sensitivity and alternatives

- If repeated device faults are absent and GPU readiness is documented, **GATE-1** becomes monitoring; **OUTCOME-1** can lead.
- If the owner ranks still-image quality above human motion, **IMG-QUALITY-1** takes its place; the report does not invent a universal user-value ranking.
- If recent quality studies show no useful locomotion at all under hardware constraints, avoid enlarging video GUI, model catalog or experiment manager; choose a minimal new evidence approach or stop.
- If exact-SHA CI is already fast and reliable, **DEVEX-1** ends with no PR; test count growth is not sufficient.
- If small-screen journeys already complete without friction, **UX-1** closes with no code change.
- If current model-family matrices pass correct semantic adaptation/notice, **IMG-1** ends with no code change.
- P1/P2 are ordinal decisions, **not** calculated ROI: user time saved, failure incidence, image quality and implementation estimates are not yet measurable.

## The first bounded work-package recommendation (owner may authorize separately)

**ID:** `WP-GPU-RECOVERY-ASSESS-310` — read-only GPU post-release residual risk and decision matrix. **Class:** Standard diagnostic with material policy ambiguity; no production edits until a separately approved decision.

**Goal:** Determine whether PR-QUEUE-GPU-180 leaves a material current opportunity to consume a queue during a suspected but unconfirmed device/context loss or after release; decide whether current strict host-proof policy is preferable to a bounded probation mechanism. Distinguish documented design limitation from observed recurrence and hardware root cause.

**Scope:** Reverify current checkout/branch/SHA/worktree; read `AGENTS.md` / `STATUS.md` / `CODEX_MAP.md` and the 180 contract; follow `gpu_loss_assessment.py`, coordinator, dependency classifier, atomic queue claim, typed failure and operator readiness; use only existing safe incident artifacts and CPU synthetic tests, no production state writes. Look for existing proof of same failure class and compare options: no change + monitor, bounded per-incident probation, host-probe re-evaluation and operator instruction. State per-option false-positive queue hold, missed device faults, restart safety and denial-of-service tradeoffs.

**Acceptance:** a table with exact current code/tests, confirmed vs hypothetical incidence, 3 synthetic paths (host lost; still enumerating poisoned context; release then repeat), compatibility with `JobQueue` authority, unknown-POST no-replay, external-process boundaries; owner decision request listing observable test before accepting any change. Stop if physical or policy change would be required, or current evidence cannot discriminate. No implementation, GPU reset, test generation, runtime kill, release or publication authorized.

**Model/effort:** Claude Code **Sonnet 5.5 High**; Codex **GPT-6.1 Sol High**. **Preferred host:** Local/Desktop, because Windows driver state, process identity, SQLite and read-only incident files matter. Execution in one top-level session. If a future approved bounded queue policy change spans lifecycle/concurrency, reconsider Claude Code Sonnet 5.5 XHigh / Codex GPT-6.1 Sol XHigh.

## Conditional second package (physical authorization required)

**ID:** `WP-VID-MOTION-310` — controlled single-person motion usefulness qualification. **Goal:** Improve evidence, not production behavior. Use VID-192 owner review first; define one movement, one available pinned workflow/runtime/source/driving clip, one changed independent control, constant dimensions/seed/source where feasible; collect operator ratings for action adherence, motion amount, identity, faces/limbs, temporal stability, background and duplicates; preserve all artifacts and exact provenance with existing workflow/NJR/job/history. A physical run is **not authorized by this report**, and requires confirmed hardware safety and explicit user scope. Stop if repeated GPU faults or actual hardware risk; no broad model/backend additions. Claude Code **Sonnet 5.5 High** / Codex **GPT-6.1 Sol High**, **preferred Local/Desktop**.

## Final critique and evidence limitations

The v0 → v1.1 adversarial review is preserved in `ASSESSMENT_DRY_RUN_AND_CRITIQUE_2026-10-15.md`. The rerun changed model compatibility, GUI, Photo and test slimming from presumed top defects to **resolved or proof-required**; elevated explicit GPU recovery uncertainty and video quality limitations; introduced outcome measurement, exact-SHA CI and source-staleness gates. Critical remaining weaknesses: cannot measure real operator frequency or throughput; source review sampled rather than all 598 source files; recent merged HEAD may advance during the session; no local Windows worktree or hardware; no test/CI run at HEAD; no independent reproduction of the documented GPU edge cases; reported physical motion outcomes based on earlier limited experiments, not newly rerun. These prevent false certainty, not decision support.

## Source and verification links (exact code snapshot, unless link is PR/standard)

- Repo: https://github.com/destroyer42/StableNew2/tree/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e
- AGENTS: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/AGENTS.md
- STATUS: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/STATUS.md
- CODEX_MAP: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/CODEX_MAP.md
- GPU classifier: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/src/queue/gpu_loss_assessment.py
- GPU coordinator: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/src/controller/gpu_loss_coordinator.py
- GPU contract: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/Runtime/PR-QUEUE-GPU-180_GPU_Loss_Dispatch_Containment.md
- VIDEO 192: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/Video/PR-VID-192_Animate2_Control_Truth.md
- VIDEO 196: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/Video/PR-VID-196_Motion_Source_Readiness.md
- Model comparison implementation: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/src/learning/model_comparison.py
- GUI 100/110: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/GUI/PR-GUI-100_Responsive_Workspace_and_Reachable_Controls.md ; https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/GUI/PR-GUI-110_Focused_Operator_Workspace.md
- Test B1/B2A: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/Testing/PR-DEVEX-TEST-SLIM-120_Phase_B1_Deterministic_Test_Slimming.md ; https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/Testing/PR-DEVEX-TEST-SLIM-130_Phase_B2A_Semantic_Duplicate_Consolidation.md
- CI plan code: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/tools/ci/validation_plan.py
- PHOTO 223: https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/docs/Subsystems/Image/PR-IMG-PHOTO-223_Historical_Result_Promotion.md
- External method references in `ASSESSMENT_PLAYBOOK.md`: ISO 25010:2023; DORA; SPACE; Google Product-Focused SRE; NIST SSDF; OWASP; Intercom RICE.


## 2026-10-16 independent-audit adjudication (framework v1.2; dated decision guidance)

**Evidence baseline:** remote `main` at `d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e`; **local Windows checkout, live runtime, private data and physical test environment not available to this assessment**. This appendix corrects the earlier priority after reading a separately supplied comprehensive repository audit and independently checking selected high-severity source paths and GitHub CI jobs. The supplied audit's measured local counts and proposed efforts have not been reproduced. No repo or production settings were changed by this assessment.

### Correction and independent confirmation ledger

| External finding | Adjudication | Evidence / limit | Product consequence |
|---|---|---|---|
| A1: main governance | **Original V source claim; superseded/refuted at integration** | Original claim: branch API `protected:false`; repository rulesets `[]`; branch-protection API access denied. The 2026-10-16 integration check instead reports `protected:true` with `required` enforced for non-admins; see correction below | The original absence-of-protection conclusion is not current truth; privileged bypass remains unknown |
| A2: CI can mask census failures | **V configured + job observed** | `.github/workflows/ci.yml` uses `continue-on-error: true` on affected, shards and aggregate; scheduled run [38566383907](https://github.com/destroyer42/StableNew2/actions/runs/38566383907) shows full-suite shard 2 and aggregate **failed** while workflow concluded **success** | CI signal misrepresents comprehensive testing; enforceable verdict needed |
| B1: Codex AutoFix | **V structural risk** | `.github/workflows/codex-autofix.yml` accepts an `issue_comment` with no author-association gate, checks out PR head branch, runs dependency setup and PR-code runner with write-capable token and referenced secret | Privileged untrusted-code risk; no exploit or secret exfiltration proven |
| B2: Windows job collision | **V implementation bug; impact needs Windows reproduction** | `webui_process_manager._init_process_container` passes fixed `webui_process_manager`; `process_container_v2` generates `StableNewJob-webui_process_manager`; `win_jobobject.WindowsJobObject` opens named job without reject-if-existing, calls `TerminateJobObject` | Plausible cross-manager termination; do not blame earlier Forge exits without evidence |
| B3: startup gate and strict NJR | **V production composition gap** | `src/main.py:build_v2_app` → `app_factory` passes no JobService → `AppController` creates `PipelineController`, which creates JobService with default `require_normalized_records=False`; `_build_job_service` branch carrying only `enable_startup_gate()` is bypassed | Documented restored-queue readiness gate/strict admission may be absent in live route; require real wiring test |
| B4: Learning file storage | **V code pattern; external incident unverified** | `src/learning/experiment_store.py::_write_json` direct `path.write_text`; the external report alleges a NUL session in private storage, not inspected here | Torn JSON vulnerability; require fault-injection and visible write failure contracts |
| B5: silent state override fallback | **V code path** | `PipelineController._build_normalized_jobs_from_state` calls undefined `_extract_state_overrides` under broad `except`, falling back | Certain preview/run fallback settings not preserved when this path is exercised; reproduce path before scope |
| B6: Learning scan callback | **V probable callback issue; caller proof pending** | scan worker uses `getattr(self,"_after_fn",None)` with direct `on_complete` fallback and a raw daemon thread | Potential off-Tk updates; verify caller and shutdown cases |
| G1/G2: History and Learning usability | **V implementation limitation** | history default `limit or 20`; Learning automation mode variable `suggest_only` does not have a visible input binding in inspected code | Value of existing provenance/rating work may not reach user; usage counts externally reported only |
| Other report claims | **mixed and unverified** | 1,701 mypy errors, 22,946 local jobs, corpus corruption, CI medians, entire dead-code estimate, and some Comfy/Video behaviors came from another audit | Treat as focused investigation hypotheses, not universal proof or automatically authorized implementation |

### Revised, risk-gated opportunity sequence (not a ten-week roadmap)

1. **SAFETY-A — Disable/retire privileged untrusted AutoFix path**, using a safe scoped workflow change and read-only verification; no credentials displayed. **Owner authorization required for publishing workflow changes**.
2. **GOV-A — Protect `main` and make required checks real (historical proposal; superseded by integration verification below).** Branch/ruleset settings are shared governance changes requiring the owner's explicit decision; adding an ordinary `push` CI trigger would require a separately authorized package. Protection is now confirmed by metadata for non-admins; do not commission a fix premised on its absence.
3. **RUNTIME-A — Disposable Windows two-manager reproduction and process-container ownership isolation.** Do not run against the operator's managed Forge; prove collision/lifecycle and ensure an instance cannot terminate another.
4. **STARTUP-A — Actual composition-root negative proof and bounded startup-gate/strict NJR repair.** Keep one SQLite lifecycle authority; prove restored WebUI work is held until fresh trusted readiness and identity evidence.
5. **DATA-A — Inventory all durable JSON stores and fix confirmed torn-write/failure-visibility seams** with safe tmp/fsync/replace semantics and user-visible refusal; original user data never touched in tests.
6. **CI-A — Enforce meaningful integration tests and compare sharded full census against affected routing**, measured in equivalent PR contexts. Removal of routing is conditional on cost/failure/coverage proof, not a slogan.
7. **WIN-A — Minimal deterministic Windows CI coverage** for job-object, filesystem/path, SQLite and Tk construction; does not replace authorized GPU hardware qualification.
8. **DEFECT-A — Focused tests of absent state method, Learning callback, silent tab creation, bounded SVD/Comfy waits and provenance refusal**; fix only proven in-scope behavior, not an indiscriminate monolith rewrite.
9. **KM-A — Fix verified stale documentation pointers and audit real reading/churn cost.** A 150-line hard cap and broad harness archive are *options to test*, not approved outcomes; preserve unique tests and canonical decisions.
10. **PRODUCT-A — Recompare History discoverability/replay-with-changes, Learning feedback, directed-motion usefulness and editing/inpainting** with actual user task outcomes. No new backend or large GUI refactor is yet justified.

**Former priority `GATE-1` (GPU-180 residual-release policy) is deferred** pending this safety/enforcement triage, unless a fresh recurring event elevates it. It remains a valid documented residual risk, not a refuted finding.

### Rejected or narrowed remedies and why

- The external report's numerical `(impact+risk)*(6-effort)` ranking and ten-week schedule are insufficiently grounded; safety gates, confidence and dependency evidence outrank subjective arithmetic.
- Require meaningful tests to block shared changes; **do not** delete risk-based affected routing until representative full-census timing and observed failure detection are compared.
- Do not require exactly one NJR constructor, one abstraction per domain, or arbitrary 3,000-line/4,000-line targets; prove loss of distinct policy/coupling first, preserve immutable NJR and runner boundary.
- Do not delete/archive qualification harnesses merely because large or old; prove replacement of unique regression/qualification signal and retrospective need.
- Do not treat user data counts from a separate local audit as accessible current source truth, and do not infer that a Windows collision caused prior GPU/device faults.
- Do not equate visible existence of an API backend with approved production compatibility or an automatic inpainting priority.

### Framework and assessment-quality correction

v1.1 failed to examine effective GitHub protections, actual failed CI jobs, privileged Actions, Windows job-object names, true startup wiring, stores outside SQLite, Tk callback negative paths and capability UI reachability. v1.2 now requires an **eight-control mandatory ledger**, independent implementation vs impact proof, a **six-factor feature use map**, deliberate negative-case search and a **method-diverse adversarial pass** before final rankings. These new requirements would have surfaced the major omissions without needing a new model or a second mandatory agent chain.

**No publication or operator-state change is implied by the assessment.** Canonical architecture, model/hardware safety, single top-level session, queue-first semantics and Git authority remain in force. The original report is retained above as a dated historical decision record, not silently rewritten to claim its old rankings were correct.

## 2026-10-16 integration verification and governance correction

This is a bounded documentation freshness check for PR-DEVEX-ASSESS-310, not
a new Comprehensive assessment or a new implementation authorization. The
local feature worktree was verified clean at parent
`d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e`, matching live remote `main` on
2026-10-16 (America/New_York). Existing worktrees and unfinished changes were
left in place. The ZIP integration helper was reviewed but not executed: its
`STATUS_CONTROL` would insert the superseded absence-of-protection claim.

| Surface | Independently rechecked evidence | Disposition and limit |
|---|---|---|
| Main protection | [Branch metadata](https://api.github.com/repos/destroyer42/StableNew2/branches/main): `protected:true`, protection enabled, `required_status_checks.enforcement_level=non_admins`, context `required` (GitHub Actions app 15368) | Refutes the original unprotected-main finding. Metadata establishes the non-admin check requirement; no direct-push or bypass experiment was performed |
| Rules and privileged bypass | [Repository rulesets](https://api.github.com/repos/destroyer42/StableNew2/rulesets) returned `[]`; [protection details](https://api.github.com/repos/destroyer42/StableNew2/branches/main/protection) returned 403 `Resource not accessible by integration` | Empty rulesets do not mean no branch protection. Detailed protection, admin enforcement, bypass actors and privileged direct-push posture remain unverified; denied access is an evidence gap |
| CI triggers/configuration | At the parent SHA, [ci.yml](https://github.com/destroyer42/StableNew2/blob/d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e/.github/workflows/ci.yml) has PR, manual and scheduled triggers, no ordinary push trigger; affected, census shards and aggregate use `continue-on-error: true` | Configured CI behavior and the enforced `required` context are distinct. No workflow or settings changed |
| Historical CI failure | [Scheduled run 38566383907](https://github.com/destroyer42/StableNew2/actions/runs/38566383907), 2026-10-14, source `ab0531e0e520606f1ba25dc4c1de32f3771fda3f`: overall `success`; `required` success; shard 2 failure, shards 0/1 success; `full-suite` failure; `affected` skipped | Confirms the dated job-versus-workflow discrepancy, not a verdict for current main or this docs branch |
| Current source CI visibility | The five latest [main-branch runs](https://api.github.com/repos/destroyer42/StableNew2/actions/runs?branch=main&per_page=5) returned no run for `d43fdc39`; [PR #106 head run 38840829699](https://github.com/destroyer42/StableNew2/actions/runs/38840829699) reports workflow success at `88e4c97961f3f4af1eb9b245a189e852a7fc1b77` | PR-head workflow success is not per-job evidence or an exact-main verdict. No new run was requested; no hosted verdict exists for the local-only docs commit |

The following PR lifecycle corrections were independently reconfirmed via the
PR API on 2026-10-16. Merge truth does not upgrade physical qualification or CI
claims in their acceptance reports.

| PR | Merged at (UTC) | Merge SHA |
|---|---|---|
| [#100 GPU containment](https://github.com/destroyer42/StableNew2/pull/100) | 2026-10-13 17:13:58 | `bbf855d415a14a1b3b09c0e0a043a608dc71eeba` |
| [#104 motion source readiness](https://github.com/destroyer42/StableNew2/pull/104) | 2026-10-15 12:38:01 | `5cab2431a523a2520124011e39d15665ce9c5a3c` |
| [#105 Photo scoped editing](https://github.com/destroyer42/StableNew2/pull/105) | 2026-10-15 18:54:42 | `d025d82a49fdbb2e477a2a4dfcdf1ee7a30921a9` |
| [#106 historical result promotion](https://github.com/destroyer42/StableNew2/pull/106) | 2026-10-16 02:46:05 | `d43fdc39d7f1e887c82a94fd81f0ff2f1ecac48e` |

**Priority-change ledger:** the October 15 v1.1 `GATE-1` first ranking remains
superseded by the October 16 critical-control adjudication. The original GOV-A
P0 proposal is now **U / partial verification**, because protection and the
non-admin check requirement are confirmed while privileged bypass is unknown.
The [register](OPPORTUNITY_REGISTER.csv) records that correction. It preserves
the remaining dated candidates; P0 is a risk-triage signal, never a scheduled
or authorized PR. Refresh each candidate against the selected base before
commissioning work. Other branches' uncommitted repairs do not establish
accepted or merged fixes on this baseline.

The AutoFix, process ownership, startup admission, Learning persistence and
other implementation findings remain **dated assessment findings** with the
original proof limits; no code repair, security exploit, user-state corruption
or past-crash attribution is established by this integration. In particular,
the external auditor's **22,946 jobs** and **1,701 mypy errors** were not
independently reproduced. Physical/operator data, Windows negative cases,
complete store coverage and privileged settings remain gaps, so the historical
assessment is **PARTIAL** under v1.2. The no-change alternative is to retain
existing controls and gather missing evidence; any minimal fix needs its own
bounded acceptance and owner authorization. No architecture decision is
needed to integrate this documentation.
