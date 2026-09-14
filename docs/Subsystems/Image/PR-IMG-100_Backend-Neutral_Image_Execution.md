# PR-IMG-100 — Backend-Neutral Image Execution

Status: APPROVED POST-v2.6 ARCHITECTURE / ACCEPTANCE REFERENCE
Owner: Rob
Decision date: 2026-09-13
Execution state: Not started; begins only after PR-MVP-080 and PR-MVP-090 are accepted and integrated.

> **Implementation-authority rule:** this document preserves the approved product/architecture outcome and acceptance intent. It is **not** an executable Codex prompt or frozen file/schema plan. Before implementation, verify the exact integrated post-v2.6 branch/SHA, read current repo authorities, inspect the live implementation surfaces, reconcile all accepted predecessor work, and rewrite the bounded Codex work package from that repository state. Any old phase prompt, file list, execution-class estimate, or sequencing assumption from discovery is reference material only.

## 1. Outcome

Make still-image execution backend-neutral while preserving the accepted A1111
image path unchanged and creating a clean later path for whichever additional
image runtime/model family is justified by evidence.

The canonical outer path remains:

`Intent -> Compiler -> immutable NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

PR-IMG-100 changes only the internal still-image execution boundary below
`PipelineRunner.run_njr`. It does not create a second runner, queue, persistence
authority, GUI execution path, or alternate NJR.

## 2. Accepted architecture decision

Adopt COA B: **one typed image backend per image NJR**.

The selected image backend owns all still-image stages in that NJR. The first
production backend remains the accepted A1111/WebUI path and must preserve
current behavior.

Conceptual target shape:

```text
Intent
  -> Compiler
  -> immutable NJR
  -> JobService
  -> SQLite Queue/Repository
  -> PipelineRunner.run_njr
  -> Image stage handler
  -> StableNew-owned ImageBackend boundary
       -> A1111/WebUI adapter -> existing executor/client/runtime behavior
       -> future backend(s)   -> added only after separate qualification
  -> normalized image execution result
  -> existing Artifact / History / Replay
```

Backend/runtime, model family, and model identity are separate concepts:

- backend/runtime examples: `a1111_webui`, future `diffusers`, future `comfyui`;
- model-family examples: SDXL, Ideogram-, Qwen-, FLUX-class or successors;
- model identity is backend-specific: local checkpoint/hash, Hugging Face
  model/revision, workflow model reference, or equivalent.

Do not create model-named backend classes as the public StableNew architecture
when several models share one runtime.

## 3. Deferred alternatives

### COA C — per-stage backend composition

Potential future capability. It could permit chains such as one backend for
base generation followed by another backend for detail/upscale. It is explicitly
out of scope for PR-IMG-100 because it requires cross-backend artifact handoff,
capability negotiation, resource lifecycle coordination, replay semantics, and
provenance rules.

### COA D — ComfyUI-centric image execution

Potential future backend option. ComfyUI may later be valuable for model
families/workflows that benefit from it, but it must remain an execution backend
behind StableNew-owned orchestration. It must not replace StableNew's compiler,
NJR, queue, runner, artifact, history, replay, or cancellation authorities.

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
- existing A1111 `SDWebUIClient` transport semantics unless current repo evidence shows a narrower cohesive adapter seam;
- model/VAE synchronization and verification;
- A1111 payload/extension semantics;
- managed-versus-external WebUI lifecycle ownership rules;
- generation progress, operator cancellation, stall handling, recovery
  classification, and ambiguous dispatched-POST non-replay semantics;
- exact job artifacts as thumbnail authority.

Existing A1111 implementation details may be moved behind an adapter but are not
to be reimplemented merely to create the abstraction.

## 5. NJR and configuration intent

The current approved intent is to use the existing workload-level
`backend_options` carrier for immutable backend selection rather than add a new
top-level NJR field solely for backend identity. This must be revalidated against
the live post-v2.6 NJR before implementation.

Required semantics remain:

- newly compiled image work explicitly authorizes one image backend;
- historical v2.6 image NJRs that predate explicit backend identity resolve
  deterministically to A1111 through one bounded compatibility rule;
- replay preserves authorized backend identity while creating a new NJR/job with
  normal lineage;
- GUI state is not backend-selection authority after compilation.

If live implementation evidence shows that the existing workload carrier is
insufficient, stop for architecture review rather than silently adding a new NJR
core field.

## 6. Minimum backend responsibilities

The implementation must establish one StableNew-owned internal boundary with
responsibilities equivalent to:

- backend identity/capabilities;
- StableNew-authorized image execution request;
- normalized image execution result;
- backend interface/adapter;
- backend registry/resolver.

Names and file placement are implementation output and must be chosen from the
live repository. These responsibilities may not collapse back into generic
`PipelineRunner` orchestration.

### Capabilities

At minimum the boundary must truthfully express:

- backend ID;
- supported image stage types;
- whether a stage requires an input image;
- prompt/negative-prompt support where needed for validation;
- image artifact result type.

Do not pre-design a universal capability ontology for every future model. Extend
capability vocabulary only when an accepted backend requires it.

### Request

The backend receives StableNew-authorized stage work, not a GUI object and not a
public A1111/ComfyUI payload. Backend-private API/workflow payloads are created
inside the adapter.

### Result

Backend output is normalized into StableNew-owned execution facts sufficient for
canonical artifacts, history, replay, diagnostics, and provenance. The generic
runner must not depend on WebUI-specific response semantics.

## 7. Initial backend policy

### A1111/WebUI

`a1111_webui` is the default and only production image backend delivered by
PR-IMG-100.

It must preserve support for the currently accepted image stages:

- `txt2img`
- `img2img`
- `adetailer`
- `upscale`

The adapter should delegate to accepted executor/client behavior rather than
duplicate it.

### Future real backends

PR-IMG-100 does not select or implement the second production backend.

The previous Ideogram-first follow-on assumption is superseded. Later image
runtime/model expansion belongs to the active roadmap's evidence-selected
qualification gate. At that future decision point, compare the strongest current
candidates on useful-output quality, VRAM/RAM, latency, local/offline behavior,
license, control/editing support, adapter ecosystem, determinism, cancellation,
provenance, and LAN/cloud suitability.

An NJR selecting a backend that does not support every requested image stage must
fail deterministically before backend dispatch. PR-IMG-100 must not silently
fall back to A1111 for unsupported stages.

## 8. Explicit non-goals

PR-IMG-100 does not:

- implement Ideogram, Qwen, FLUX, or another second real model family;
- add a Diffusers production backend;
- add ComfyUI still-image execution;
- add per-stage backend selection;
- permit implicit cross-backend stage handoff;
- redesign PromptPack storage;
- change queue/history persistence;
- change the public runner entry;
- redesign Learning or Adapter Intelligence;
- migrate current A1111 still-image work to ComfyUI;
- redesign output-folder naming solely for backend neutrality;
- broadly decompose `executor.py` or controllers for LOC reduction;
- change A1111 generation quality/settings as part of the refactor;
- implement LAN/cloud execution placement.

Responsibility extraction that is necessary to put A1111-specific execution
behind the accepted backend boundary is in scope; unrelated cleanup is not.

## 9. Acceptance contract

PR-IMG-100 is accepted only when all of the following remain true after the
live-repo implementation contract is rewritten.

### Backend identity and compilation

1. Every newly compiled image NJR records one explicit image backend identity.
2. The default/current production backend remains A1111 unless an accepted
   intent surface explicitly selects another registered backend in the future.
3. Backend selection is immutable authorized workload state and round-trips
   through NJR serialization/repository persistence.
4. Historical v2.6 image NJRs lacking backend identity resolve to A1111 through
   one documented compatibility rule.
5. Replay preserves backend identity and creates a new NJR/job with existing
   parent-lineage semantics.

### Routing and capability enforcement

6. `PipelineRunner.run_njr` remains the only public production runner entry.
7. Image execution resolves its backend through one StableNew-owned boundary.
8. Backend selection is by backend identity; model names do not select public
   backend classes.
9. Unsupported backend/stage combinations fail before dispatch with an
   actionable deterministic error.
10. No automatic per-stage fallback to A1111 exists.
11. No backend creates queue/history state or another executable job model.

### A1111 preservation

12. Current A1111 `txt2img`, `img2img`, `adetailer`, and `upscale` execute through
    the new image-backend boundary.
13. Existing A1111 request construction remains backend-private; generic runner
    code no longer treats a WebUI payload as the image execution contract.
14. Existing checkpoint/model synchronization and wrong/unverified-model failure
    behavior remain accepted.
15. Existing VAE behavior remains accepted unless a separately authorized VAE
    change has already landed before this PR, in which case preserve that newer
    live contract.
16. Managed A1111 lifecycle actions remain limited to the process
    launched/tracked by `WebUIProcessManager` or its accepted successor.
17. External A1111 is never adopted, killed, or restarted automatically.
18. A generation POST whose outcome is ambiguous is never automatically replayed.
19. Existing cancellation/progress/stall/recovery behavior remains accepted
    through the adapter.
20. Existing image artifact/history/replay results remain product-equivalent for
    the same authorized A1111 workload.

### Backend-neutral proof

21. A deterministic fake/non-WebUI image backend can be injected/registered
    without changing queue, repository, public runner, or artifact/history
    authorities.
22. A txt2img workload selecting that fake backend traverses the normal
    JobService -> SQLite -> PipelineRunner.run_njr -> backend -> artifact/history
    path without calling WebUI.
23. A fake backend advertising only txt2img is rejected before dispatch when the
    workload requests an unsupported image stage chain.
24. The fake-backend proof does not add a test-only production runner or bypass
    persistence.

### Architecture/controller discipline

25. No model-family dispatch such as `if ideogram`, `if flux`, or `if qwen` is
    added to generic `PipelineRunner` orchestration.
26. No second image queue, history, compiler, runner, cancellation authority, or
    process authority is introduced.
27. GUI/controllers continue to express intent/projections only; they do not
    create backend payloads.
28. If a ratcheted controller is materially touched, no new coherent
    responsibility is added inline and its ceiling is lowered if the surface
    shrinks.
29. Existing video backend authority remains independent; PR-IMG-100 does not
    create a premature universal image/video runtime registry.

## 10. Required validation intent

The eventual implementation contract should cover, at minimum:

- backend-option normalization/defaulting;
- NJR serialization/replay preservation;
- historical no-backend compatibility to A1111;
- registry lookup and unknown-backend failure;
- capability validation and unsupported-stage rejection;
- fake-backend queue-first golden path;
- A1111 parity for all accepted image stages;
- cancellation propagation through the adapter;
- canonical artifact/result normalization;
- affected image golden-path regressions;
- one bounded real A1111 acceptance after the adapter cutover because production
  image execution boundaries changed.

Run focused tests first, then the repository gate once when appropriate. Required
GitHub Python 3.11/3.12 remains the canonical integration verdict unless the
live repo changes that policy before implementation.

No second real backend is required for PR-IMG-100 acceptance.

## 11. Implementation discovery gate

Do **not** execute a discovery-era Phase A/B/C prompt from this document or from
chat history.

At the post-v2.6 decision point:

1. verify exact branch/SHA/worktree and current repo authorities;
2. establish/review the bounded useful-output-efficiency baseline required by the
   active roadmap;
3. inspect the live NJR/backend-options/image compiler/runner/executor/runtime
   surfaces and current controller ratchets;
4. identify what 080/090 or intervening work changed;
5. rewrite the smallest coherent implementation package(s) and validation from
   current truth;
6. preserve already-green evidence when relevant source is unchanged;
7. stop for owner review if live evidence requires per-stage backend composition,
   a new NJR core field, a new lifecycle authority, or another material
   architecture change.

The previous estimated three-phase shape—contract/routing proof, A1111 adapter
cutover, then real acceptance/closeout—remains useful planning context only. It
may collapse, split, or change if the post-v2.6 repository makes another package
shape safer or cheaper.

## 12. Next decision after PR-IMG-100

Do not automatically proceed to an Ideogram/Diffusers production path.

The active roadmap next prioritizes **Asset Intelligence + Quality Efficiency**
so StableNew can reduce bad/unsupported generations, establish exact asset
identity, support deterministic VAE/compatibility policy, and build controlled
quality evidence. After that come capability-aware Execution Placement and
Directed Motion Video. Modern image backend/model expansion is an evidence-
selected later decision gate.
