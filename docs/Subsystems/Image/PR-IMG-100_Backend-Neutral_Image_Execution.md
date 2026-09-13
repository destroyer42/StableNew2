# PR-IMG-100 — Backend-Neutral Image Execution

Status: APPROVED POST-v2.6 ARCHITECTURE CONTRACT
Owner: Rob
Decision date: 2026-09-13
Execution state: Not started; begins only after PR-MVP-080 and PR-MVP-090 are accepted and integrated.

## 1. Outcome

Make still-image execution backend-neutral while preserving the accepted A1111 image path unchanged and creating a clean later path for a Diffusers image backend, initially qualified against Ideogram 4.

The canonical outer path remains:

`Intent -> Compiler -> immutable NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

PR-IMG-100 changes only the internal still-image execution boundary below `PipelineRunner.run_njr`. It does not create a second runner, queue, persistence authority, GUI execution path, or alternate NJR.

## 2. Accepted architecture decision

Adopt COA B: **one typed image backend per image NJR**.

The selected image backend owns all still-image stages in that NJR. The first production backend remains the accepted A1111/WebUI path and must preserve current behavior. A later Diffusers backend may initially support only `txt2img`.

Initial target shape:

```text
Intent
  -> Compiler
  -> immutable NJR
  -> JobService
  -> SQLite Queue/Repository
  -> PipelineRunner.run_njr
  -> Image stage handler
  -> ImageBackendRegistry
       -> A1111WebUIImageBackend -> existing Pipeline / SDWebUIClient / WebUI
       -> DiffusersImageBackend  -> later model-family adapter (Ideogram 4 first candidate)
  -> ImageExecutionResult
  -> existing Artifact / History / Replay
```

Backend/runtime, model family, and model identity are separate concepts:

- backend/runtime examples: `a1111_webui`, `diffusers`, future `comfyui`;
- model-family examples: `sdxl`, `ideogram4`, future `flux`, `qwen_image`;
- model identity is backend-specific: local checkpoint name, Hugging Face model/revision, workflow model reference, or equivalent.

Do not create model-named backend classes as the public StableNew architecture when several models share one runtime.

## 3. Deferred alternatives

### COA C — per-stage backend composition

Potential future capability. It could permit chains such as Ideogram/Diffusers `txt2img` followed by an A1111 detail or upscale stage. It is explicitly out of scope for PR-IMG-100 because it requires cross-backend artifact handoff, capability negotiation, resource lifecycle coordination, replay semantics, and provenance rules.

### COA D — ComfyUI-centric image execution

Potential future backend option. ComfyUI may later be valuable for model families or workflows that benefit from it, but it must remain an execution backend behind StableNew-owned orchestration. It must not replace StableNew's compiler, NJR, queue, runner, artifact, history, replay, or cancellation authorities.

## 4. Existing authority preserved

PR-IMG-100 must preserve:

- immutable v2.6 NJR as the authorized workload;
- `JobService.submit_njrs` as submission boundary;
- SQLite queue/repository lifecycle authority;
- `PipelineRunner.run_njr` as the only public production runner entry;
- queue-first Run Now / Send Job behavior;
- canonical artifact/history/replay contracts;
- PromptPack native JSON authority;
- existing learning consumption path;
- current image stage order: `txt2img -> optional img2img -> optional adetailer -> optional upscale`;
- existing A1111 `SDWebUIClient` transport;
- model/VAE synchronization and verification;
- A1111 payload construction and extension semantics;
- managed-versus-external WebUI lifecycle ownership rules;
- generation progress, operator cancellation, stall handling, recovery classification, and ambiguous dispatched-POST non-replay semantics;
- exact job artifacts as thumbnail authority.

Existing A1111 implementation details may be moved behind an adapter but are not to be reimplemented merely to create the abstraction.

## 5. NJR and configuration contract

No new top-level NJR field or NJR schema version is required solely for backend selection. `ImageWorkloadSpec.backend_options` is the authorized immutable carrier.

Newly compiled image work after PR-IMG-100 must persist an explicit image backend identity under the existing backend-options layer. The exact normalized shape may be chosen during Phase A, but it must be singular, typed/validated, round-trip completely, and remain backend configuration rather than GUI state.

Required semantics:

```text
backend_options.image.backend_id = a1111_webui
```

for the existing production path.

Historical v2.6 image NJRs with no explicit image backend resolve deterministically to `a1111_webui`. This is a bounded compatibility rule for persisted pre-PR-IMG-100 records, not permission for new compilers to omit backend identity.

Replay of a persisted NJR preserves the selected backend through normal NJR replacement/lineage semantics.

## 6. Minimum typed image-backend contract

PR-IMG-100 must introduce one StableNew-owned internal contract equivalent in responsibility to:

- `ImageBackendCapabilities`
- `ImageExecutionRequest`
- `ImageExecutionResult`
- `ImageBackendInterface`
- `ImageBackendRegistry`

Names and exact file placement may change if current repo structure provides a better cohesive home, but the responsibilities may not be collapsed back into `PipelineRunner`.

### 6.1 Capabilities

At minimum, capabilities must identify:

- backend ID;
- supported image stage types;
- whether a stage requires an input image;
- prompt/negative-prompt support where needed for truthful validation;
- artifact type (`image`).

Do not pre-design a universal feature taxonomy for every future image model. Extend capability vocabulary only when an accepted backend requires it.

### 6.2 Request

The request contains StableNew-authorized stage work, not an A1111 payload. It should carry the minimum required set of:

- backend ID;
- stage name;
- prompt and negative prompt as applicable;
- normalized stage configuration;
- output directory;
- input image path(s) where applicable;
- requested image name/output identity context;
- job ID;
- immutable backend options needed by the selected backend;
- cancel token;
- context/provenance metadata needed for canonical artifacts and diagnostics.

Backend-private API/workflow payloads are created inside the backend adapter.

### 6.3 Result

The result normalizes backend output into StableNew-owned execution facts:

- backend ID;
- stage name;
- primary path;
- output paths;
- manifest path where applicable;
- canonical artifact record;
- backend metadata;
- diagnostics/error context;
- optional raw/private result retained only where current contracts require it.

The runner and downstream history/replay code consume this normalized result rather than WebUI response semantics.

## 7. Initial backend policy

### 7.1 A1111/WebUI

`a1111_webui` is the default and only production image backend delivered by PR-IMG-100.

It supports all currently accepted image stages:

- `txt2img`
- `img2img`
- `adetailer`
- `upscale`

The adapter should delegate to the existing executor/client implementation and preserve behavior rather than duplicate it.

### 7.2 Future Diffusers

`diffusers` is the planned second backend family but is not implemented by PR-IMG-100.

The first qualification target is Ideogram 4. Initial production support, if later accepted, may advertise only `txt2img`.

An NJR selecting a backend that does not support every requested image stage must fail deterministically before backend dispatch. PR-IMG-100 must not silently fall back to A1111 for unsupported stages.

## 8. Explicit non-goals

PR-IMG-100 does not:

- implement Ideogram 4 inference;
- add a Diffusers production backend;
- add ComfyUI still-image execution;
- add per-stage backend selection;
- permit implicit cross-backend stage handoff;
- redesign PromptPack storage;
- change queue/history persistence;
- change the public runner entry;
- redesign learning or Adapter Intelligence;
- migrate current A1111 still-image work to ComfyUI;
- redesign output-folder naming solely for backend neutrality;
- broadly decompose `executor.py` for LOC reduction;
- change A1111 generation quality/settings as part of the refactor.

## 9. Acceptance contract

PR-IMG-100 is accepted only when all of the following are true.

### 9.1 Backend identity and compilation

1. Every newly compiled image NJR records an explicit image backend ID.
2. The default/current backend ID is `a1111_webui` unless an accepted intent surface explicitly selects another registered backend.
3. Backend selection is immutable authorized workload state and round-trips through NJR serialization/repository persistence.
4. Historical v2.6 image NJRs lacking backend identity resolve to `a1111_webui` through one documented compatibility rule.
5. Replay preserves backend identity and creates a new NJR/job with existing parent-lineage semantics.

### 9.2 Routing and capability enforcement

6. `PipelineRunner.run_njr` remains the only public production runner entry.
7. Image execution resolves a backend through one registry/resolver owned below the runner contract.
8. The selected backend is resolved by backend ID; model names do not select public backend classes.
9. Unsupported backend/stage combinations fail before dispatch with an actionable deterministic error.
10. No automatic per-stage fallback to A1111 exists.
11. No backend creates queue/history state or another executable job model.

### 9.3 A1111 preservation

12. Current A1111 `txt2img`, `img2img`, `adetailer`, and `upscale` execute through the new image-backend boundary.
13. Existing A1111 request construction remains backend-private; generic runner code no longer treats a WebUI payload as the image execution contract.
14. Existing checkpoint/model synchronization and wrong/unverified-model failure behavior remain unchanged.
15. Existing VAE behavior remains unchanged.
16. Managed A1111 lifecycle actions remain limited to the process launched/tracked by `WebUIProcessManager`.
17. External A1111 is never adopted, killed, or restarted automatically.
18. A generation POST whose outcome is ambiguous is never automatically replayed.
19. Existing cancellation/progress/stall/recovery behavior remains accepted through the adapter.
20. Existing image artifact/history/replay results remain product-equivalent for the same authorized A1111 NJR.

### 9.4 Backend-neutral proof

21. A deterministic fake/non-WebUI image backend can be injected or registered without changing the queue, repository, public runner, or artifact/history authorities.
22. A `txt2img` NJR selecting that fake backend traverses the normal `JobService -> SQLite -> PipelineRunner.run_njr -> backend -> artifact/history` path without calling WebUI.
23. A fake backend advertising only `txt2img` is rejected before execution when the NJR requests `txt2img -> adetailer`.
24. The fake-backend proof does not add a test-only production runner or bypass persistence.

### 9.5 Architecture and controller discipline

25. No `if ideogram`, `if flux`, `if qwen`, or equivalent future-model dispatch is added to generic `PipelineRunner`.
26. No second image queue, history, compiler, runner, cancellation authority, or process authority is introduced.
27. GUI/controllers continue to express intent and projections only; they do not create backend payloads.
28. If a ratcheted controller is materially touched, the change does not add a new coherent responsibility inline and its ceiling is lowered if the surface shrinks.
29. Existing video backend authority remains independent; PR-IMG-100 does not merge video and image registries into a premature universal runtime abstraction.

## 10. Required deterministic validation

Focused validation must cover at least:

- image backend option normalization/defaulting;
- NJR serialization round-trip with explicit image backend;
- historical v2.6 no-backend compatibility to A1111;
- replay backend preservation;
- registry lookup and unknown-backend failure;
- supported-stage capability validation;
- fake backend queue-first golden path;
- fake backend unsupported-stage rejection;
- A1111 `txt2img` adapter parity;
- A1111 `img2img` adapter parity;
- A1111 ADetailer adapter parity;
- A1111 upscale adapter parity;
- cancellation propagation through adapter;
- canonical artifact/result normalization;
- existing affected image golden-path tests.

Run focused tests first. Then run `python tools/ci/run_pr_gate.py` once when practical. Missing local Ruff/mypy/etc. is reported as a tooling blocker rather than repaired inside this PR. Required GitHub Python 3.11/3.12 remains the canonical integration verdict.

A final real-A1111 acceptance is required after the adapter cutover because the refactor touches the accepted production execution boundary. Reuse prior expensive runtime evidence only for behavior whose relevant source did not change.

No Ideogram, ComfyUI, or other second real image backend is required for PR-IMG-100 acceptance.

## 11. Work estimate

Expected size: **medium architectural refactor**, not a rewrite.

Discovery estimate:

- approximately 3–5 new small image-backend contract/registry/adapter modules;
- approximately 8–15 existing production/test/documentation files materially touched across the full PR;
- approximately 90% of StableNew authorities and behavior preserved;
- approximately 8% materially refactored around still-image execution/config routing;
- approximately 2% made obsolete, chiefly generic-runner assumptions that image execution inherently means A1111/WebUI/SDXL.

These percentages are architecture-surface estimates, not LOC targets or acceptance metrics.

## 12. Phased implementation sequence

The PR is one acceptance contract, but Codex executes one bounded phase per invocation unless explicitly authorized otherwise.

### Phase A — Contract, backend identity, deterministic routing proof

**Execution class/model:** Architectural — GPT-5.6 Sol, Medium. Use Local/Desktop if local worktree state matters; Cloud is acceptable only from the exact pushed clean post-v2.6 parent because this phase is source/test/docs-only.

**Outcome:** Introduce the typed image backend contract and registry/resolver, persist explicit A1111 backend identity in newly compiled image NJRs, provide historical no-backend compatibility, and prove routing with a fake backend. Do not cut production A1111 execution over yet.

**Likely starting surfaces:**

- `src/pipeline/njr_core_v26.py`
- `src/pipeline/config_contract_v26.py`
- image NJR compilers/builders identified through targeted references to `ImageWorkloadSpec`
- `src/pipeline/pipeline_runner.py`
- `src/controller/ports/runtime_ports.py`
- `src/controller/ports/default_runtime_ports.py`
- new cohesive image-backend contract/registry home chosen from current repository structure
- focused pipeline/config/replay tests

**Phase A acceptance:** acceptance items 1–11 and 21–24 are deterministically proven, while current A1111 production dispatch is unchanged.

**Stop:** checkpoint after deterministic fake-backend proof and focused validation. Do not begin A1111 cutover.

### Phase B — A1111 adapter cutover

**Execution class/model:** Architectural — GPT-5.6 Sol, Medium. Prefer Local/Desktop because A1111 behavior and local runtime contracts are directly affected even though deterministic tests come first.

**Outcome:** Route all four accepted image stages through `a1111_webui` behind the typed backend interface, preserving current A1111 implementation and moving A1111-specific preparation out of generic runner orchestration where required.

**Likely starting surfaces:**

- image backend contract/registry from Phase A
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/pipeline/payload_builder.py`
- `src/api/client.py` only if adapter integration requires it; do not redesign transport
- A1111-focused pipeline/executor tests and helpers

**Phase B acceptance:** items 12–20 and 25–29 are deterministically proven. All four stages pass adapter-parity tests. Existing WebUI lifecycle/recovery authorities remain unchanged.

**Stop:** checkpoint after deterministic parity/cancellation validation. Do not perform unrelated executor cleanup, add another backend, or begin real-backend closeout without review.

### Phase C — A1111 real acceptance, CI, documentation closeout

**Execution class/model:** GPT-5.6 Luna High for bounded integration/docs once Phase B architecture is accepted; escalate only if real acceptance exposes cross-boundary design defects. Use Local/Desktop.

**Outcome:** Establish that the accepted A1111 operator path remains product-equivalent through the new backend boundary, finish required CI, and update canonical documentation from target to implemented truth.

**Required evidence:**

- exact Phase B parent SHA/diff reviewed;
- focused tests remain green;
- `python tools/ci/run_pr_gate.py` once where practical;
- required GitHub Python 3.11/3.12 integration verdict;
- one real A1111 queue-first image golden path through `PipelineRunner.run_njr` and the new A1111 backend adapter;
- cancellation/ownership/ambiguous-POST evidence repeated only where changed source invalidates prior proof;
- artifact, history, and replay agreement;
- documentation impact gate completed.

**Stop:** PR-IMG-100 acceptance. Do not begin Diffusers/Ideogram qualification.

## 13. Codex prompt template — Phase A

Before use, replace the exact-start placeholders with the verified integrated post-v2.6 branch and SHA. Do not reuse the discovery SHA.

```text
Title: PR-IMG-100 Phase A — Image Backend Contract + Deterministic Routing

Execution class/model: Architectural — GPT-5.6 Sol, Medium.
Execution environment: Cloud only if the exact parent below is pushed and clean; otherwise Local/Desktop.

Exact start branch: <VERIFY_POST-v2.6_BRANCH>
Exact start SHA: <VERIFY_POST-v2.6_SHA>

Outcome:
Introduce the StableNew-owned typed still-image backend boundary without changing production A1111 execution yet. Newly compiled image NJRs must explicitly authorize backend `a1111_webui`; historical v2.6 image NJRs with no image backend must deterministically resolve to A1111. Prove the boundary with a fake txt2img-only backend through the canonical queue/repository/runner/artifact path.

Read first:
1. AGENTS.md
2. STATUS.md
3. the Image backend-neutralization row in docs/CODEX_MAP.md
4. docs/ARCHITECTURE_v2.6.md section 7 and relevant gap/target text
5. docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md
6. only the relevant testing section

Evidence/root-cause hypothesis:
Image NJR already carries immutable backend_options and GUI/config layering already exposes backend_options, but image compilation does not establish backend identity and PipelineRunner still embeds A1111/WebUI image semantics. Video proves typed backend adapters fit the architecture. The smallest coherent fix is one image backend per NJR, not per-stage composition.

Architecture invariants:
- Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History.
- PipelineRunner.run_njr remains the only public production runner entry.
- No new queue/history/compiler/runner/cancellation/process authority.
- GUI/controllers never build backend payloads.
- A1111 production execution behavior is unchanged in Phase A.
- Do not add model-family dispatch to generic runner.
- One backend owns all image stages in an NJR.
- No implicit cross-backend fallback.
- Preserve video backend authority separately.

Bounded scope:
- typed image capabilities/request/result/interface/registry-resolver;
- normalized backend_options.image backend identity;
- centralized defaulting for newly compiled image NJRs;
- bounded compatibility rule for historical v2.6 image NJRs lacking backend identity;
- replay preservation;
- fake backend injection/registration and deterministic golden-path proof;
- capability rejection for unsupported stage chain.
Do NOT cut A1111 execution over to the adapter in this phase.

Validation:
Run focused backend-option/NJR/replay/registry/fake-backend tests first. Prove fake txt2img reaches JobService -> SQLite -> PipelineRunner.run_njr -> fake backend -> canonical artifact/history without WebUI. Prove fake txt2img-only backend rejects txt2img+adetailer before dispatch. Run the PR gate once if practical; required GitHub Python 3.11/3.12 remains canonical.

Work budget / stop conditions:
One focused discovery pass, one implementation pass, one repair pass, one final verification. Stop after Phase A acceptance is true. Stop if more than two materially different failure classes appear, scope expands into A1111 cutover/Ideogram/ComfyUI/per-stage composition, or a higher execution class is required.

Completion report:
Return exact branch/SHA, files changed, backend-options shape chosen, compatibility rule, deterministic tests and results, PR-gate/CI state, architecture/controller effect, known blockers/debt, and whether Phase A acceptance is fully true. Do not begin Phase B.
```

## 14. Codex prompt template — Phase B

Fill the exact start from the accepted Phase A checkpoint.

```text
Title: PR-IMG-100 Phase B — A1111 Image Backend Adapter Cutover

Execution class/model: Architectural — GPT-5.6 Sol, Medium.
Execution environment: Local/Desktop preferred.

Exact start branch: <ACCEPTED_PHASE_A_BRANCH>
Exact start SHA: <ACCEPTED_PHASE_A_SHA>

Outcome:
Route the four accepted still-image stages through the Phase A image-backend contract using `a1111_webui`, while preserving current accepted A1111 behavior. Generic PipelineRunner orchestration must stop treating WebUI payloads/model-VAE operations as the universal image contract. Reuse the existing executor/client safety logic rather than rewriting it.

Read first:
AGENTS.md, STATUS.md, Image row in CODEX_MAP, architecture section 7, PR-IMG-100 contract, then inspect only the Phase A backend modules plus current PipelineRunner/executor/payload-builder/A1111 tests needed for the cutover.

Architecture invariants:
Preserve every PR-IMG-100 invariant, especially queue-first NJR authority, one public runner, one backend per image NJR, managed/external WebUI ownership, wrong-model pre-generation failure, no ambiguous POST replay, and no second cancellation/process authority.

Bounded scope:
- implement A1111 backend adapter around existing image executor behavior;
- route txt2img/img2img/adetailer/upscale through registry-selected A1111 adapter;
- move only A1111-specific preparation that must leave generic runner code;
- normalize results through ImageExecutionResult/canonical artifacts;
- update focused tests/helpers for parity and cancellation.
Do NOT implement Diffusers/Ideogram/ComfyUI, per-stage backend selection, broad executor cleanup, output-layout redesign, learning redesign, or unrelated controller refactors.

Validation:
Prove deterministic parity for all four stages, model/VAE propagation, cancellation, result/artifact normalization, and unsupported-stage behavior. Reuse existing safety evidence only where relevant source is unchanged. Run PR gate once if practical; required GitHub Python 3.11/3.12 is canonical.

Work budget / stop conditions:
One discovery pass, implementation pass, repair pass, final verification. Stop after deterministic Phase B acceptance. Stop after two materially different failure classes or if cutover requires changing queue/repository/public runner/process ownership semantics.

Completion report:
Return exact branch/SHA, diff summary, what moved behind A1111 adapter vs remained unchanged, focused tests, PR-gate/CI state, any accepted evidence invalidated by source changes, controller/architecture effect, blockers/debt, and whether Phase B acceptance is fully true. Do not begin Phase C.
```

## 15. Codex prompt template — Phase C

Fill the exact start from the accepted Phase B checkpoint.

```text
Title: PR-IMG-100 Phase C — A1111 Acceptance + Closeout

Execution class/model: GPT-5.6 Luna High for bounded integration/docs; escalate to Sol Medium only if acceptance reveals an unresolved architecture defect.
Execution environment: Local/Desktop.

Exact start branch: <ACCEPTED_PHASE_B_BRANCH>
Exact start SHA: <ACCEPTED_PHASE_B_SHA>

Outcome:
Prove the accepted A1111 still-image product journey remains correct through the new backend-neutral boundary, obtain required integration verdicts, and close documentation. Do not add another backend.

Acceptance:
Use the full PR-IMG-100 acceptance contract. At minimum, run one real queue-first A1111 image journey through JobService/SQLite/PipelineRunner/new A1111 backend, verify artifact/history/replay agreement, and repeat cancellation/ownership/ambiguous-request evidence only where changed source invalidated prior proof.

Validation:
Focused tests first; one PR gate where practical; required GitHub Python 3.11/3.12; bounded real A1111 acceptance. Do not rerun unaffected GPU/video/SVD evidence.

Documentation impact gate:
Update STATUS, architecture gap/implemented state, roadmap PR-IMG-100 status, CODEX_MAP concrete image-backend paths, and testing docs only if validation policy changed. Do not narrate commits or update unrelated authorities.

Stop:
When PR-IMG-100 acceptance is true. Do not begin PR-IMG-110 or any Diffusers/Ideogram work.

Completion report:
Exact final branch/SHA, acceptance verdict by contract section, focused/local/CI/real-backend evidence, architecture/controller effect, remaining debt, docs changed, and recommended next decision. No next-phase implementation.
```

## 16. Next decision after PR-IMG-100

PR-IMG-110 should be a separate **Diffusers / Ideogram 4 runtime qualification**, not production integration. It should qualify model access/license, exact Diffusers version floor, local cache policy, VRAM/RAM/offload behavior on target hardware, 1024-class viability, latency, seed behavior, progress/cancellation, unload/reload, and coexistence with A1111/SVD GPU lifecycle.

Production Diffusers/Ideogram support requires a separate owner acceptance decision after qualification evidence.
