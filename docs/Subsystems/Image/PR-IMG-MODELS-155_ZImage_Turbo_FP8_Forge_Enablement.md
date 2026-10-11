# PR-IMG-MODELS-155 - Z-Image-Turbo FP8 exact-bundle Forge enablement

Disposition: **LOCAL_VALIDATION_COMPLETE / READY_FOR_PUBLICATION_REVIEW**. The owner explicitly selected Klein's existing 32-GB-class
total-RAM gate and pressure diagnostics, accepting removal of the provisional available-RAM and commit-headroom floors.
The exact v1 profile is implemented through the existing production path. No physical run or publication is authorized
in this package. The original PR-154B result remains `INSTRUMENTATION_GAP`.

Integrated baseline: `ef3fba8a0776548c4ac34a003452fa2402bdef32` (PR #84), freshly fetched for this package.
Local branch: `codex/img-models-155-zimage-exact-bundle`, worktree `C:\Users\rob\projects\StableNew-main`.

Execution Profile + Model/Reasoning Recommendation: Standard, substantial but bounded model integration within the
existing image architecture. Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High; Local/Desktop fits the local evidence,
model files and Windows resource context. Cross-command profile identity, actual payload and replay parity make repair
cost significant; High is the lowest effective recommendation for this package. One primary implementation session and
one independent read-only aggregate reviewer; no chain of agents.

Controller Surface Assessment: no new controller responsibilities or ratchet increase. Use the existing backend/profile,
compiler and model-policy projection seams. The managed-runtime utility adds read-only pin/launch verification;
production lifecycle and process ownership remain unchanged.

Token-Efficient Validation Plan: first reconcile the preserved exact evidence without GPU work; resolve the resource
decision; then deterministic profile/compiler/NJR/backend/executor/GUI/replay regressions with temporary state, focused
Klein/SDXL/A1111/readiness regressions, one final local PR gate and diff check, followed by independent aggregate review.
Reuse source-identical qualification evidence. No hosted CI verdict can be claimed before separately authorized publication.

## Verified physical evidence

Local evidence: `%LOCALAPPDATA%\StableNew\Qualification\IMG154B_ZIMAGE_TURBO_FP8\evidence\case-df34833e09d1-20261011T014521Z`.
The report, manifest and exact effective request were read; all 45 indexed files were rehashed without mismatch. The PNG
was independently decoded as a nonconstant 1024x1024 image. It is 937,523 bytes, SHA-256
`871ee082e875ed0f89c9b758f95a3510499ebab2aa653e1e89422d0cda67bd06`. The report validates seed 424254, effective
infotext and checkpoint/module identities; the requested API body carries `distilled_cfg_scale: 9.0`, `cfg_scale: 1.0`,
Euler, Beta, 9 steps and one image. Its per-HTTP journal is empty; ordered durable stages, console and returned output
provide execution evidence. No raw response/readback transcript is preserved, so their validation is supported by the
captured validation report and exact executed source rather than an independently re-parsed raw API response.

The served transformer, encoder and VAE were freshly read and hashed without loading tensors; each matched its exact
manifest bytes and SHA-256. The executed source was clean `a4ee0464d92cd512923530ced8181fe97fec717e`, source SHA-256
`c4ec1aa3545d864cf1de9f52cdd36de80f6c4f133bc26be5d5511d84230b0b15`.

Both stable ledgers are terminal and consumed. Their manifest/intent/wire bindings and historical owner records were
verified at each recorded claim time, including record digest and exact code binding. Case 1 (`471c18ba071a`) recorded
startup attempt only and zero generation stages. Case 2 (`df34833e09d1`) used a distinct identity and recorded exactly one
generation stage after confirmed selection. It was an explicitly continued new case, not replay of the first ledger or
an ambiguous generation POST.

The official result is `INSTRUMENTATION_GAP`: the immediate shutdown snapshot was not verified clean and reported
20 surviving PIDs. Complete telemetry covers 187 samples, maximum gap 1.02062 seconds; no monitor halt, new fault events
or boot change was recorded after the 120-second settle. The separate observation at 2026-10-11T01:52:26Z found none of
the recorded PIDs or the port 7886 listener. That later observation does not retroactively establish clean shutdown.
Visual quality, repeated-run stability, broader hardware margins and production support remain unestablished.

## Exact product envelope

Immutable reference: `backend_options.image.model_profile = {"id": "z_image_turbo_fp8_scaled", "version": 1}`.
The name identifies a candidate; only exact served-file hashes, the managed source pin and verified selection admit it.

| Role | Filename | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Transformer | `zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors` | 6158115074 | `59610861d46ae8d5d1d371ab7b2532ce64c0835052b395551a8550fa0e3eb3cf` |
| Encoder | `qwen3_4b_2964436.safetensors` | 8044982048 | `6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a` |
| VAE | `flux1AE_v10.safetensors` | 335304388 | `afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38` |

Forge WebUI only, pinned revision `d70373ebcf1a96d210b78cd6f77196459e783e2a`. One 1024x1024 `txt2img` image per NJR;
Euler/Beta/9 steps/CFG 1/shift 9; bounded natural-language positive prompt and user seed. Reject negative prompts,
conflicting components, optimizer/global-term transformations, LoRA/textual inversion/ControlNet/hypernetworks/aesthetic
modifiers, hires/refiner/ADetailer/upscale/img2img, other geometry/settings and multi-image requests. No silent dropping.
The GUI projects fixed/unsupported values, explains limited evidence, retains other-model drafts and never switches the
backend automatically. Normal Run Now/Send Job remain queued; qualification passphrase and ledgers never enter production.

## Bounded production integration

Keep `Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Forge backend ->
Artifacts/History`. `exact_model_profile.py` is a small shared resolver for independent Klein and Z-Image contracts,
not a second registry or executor. New NJR stamping, model policy, compilation and backend/replay resolution use it;
frozen Klein v1/v2 semantics remain intact, with unknown versions and unsupported dependency-bearing models refused.

The existing served-asset identity/hash cache and Forge catalogs bind the exact trio to the actual files the endpoint
serves, including reference-home paths. The existing managed-runtime marker plus read-only Git checks bind the owned
launch to clean pinned source. Missing, substituted or ambiguous paths refuse. Both modules are selected through the
existing client; final options readback verifies checkpoint, modules and the pinned sampling options before the POST.
Ordinary module-baseline normalization is preserved. No lifecycle adoption, restart or ambiguous POST replay is added.

`executor.py::run_txt2img_stage` invokes one small profile-specific projection and immediately-before-dispatch readback.
The exact POST has the PR-154B field set, `distilled_cfg_scale: 9.0` and CFG 1; `shift` cannot substitute. Non-Z-Image
payloads are untouched. Existing image manifests and artifact/history results record profile, family, verified assets,
pin, requested/effective parameters, confirmed selection, seed and canonical job lineage. No qualification ledger is used.

The GUI uses the existing model-policy projection for fixed settings and limited-support wording. Klein's selected
geometry and ordinary-model drafts survive Z-Image transitions. Optional controls are locked without deleting stored
PromptPack/feature intent; stored conflicts must be disabled before selecting Z-Image and receive explicit preflight
rejection if submitted. The advanced CLIP-skip display projects the pinned default 1 and restores its previous draft.
Natural-language prompts accept up to 10,000 characters, without weighted or adapter/embedding syntax; seeds accept
integer -1 (normal canonical random seed) or 0 through 4294967295. Native PromptPack unsupported elements are checked
before adaptation can omit them. Compiler and backend independently reject conflicting values/stage extras.

## Owner-selected resource admission

These are approximately 1 Hz observed samples from one exposure, not upper workload bounds or validated safe thresholds.

| Metric | Observed second case |
| --- | ---: |
| Claim-boundary commit headroom | 41.87 GiB |
| Claim-boundary available RAM | 21.47 GiB |
| Peak reported Forge private commit | 29.174 GiB |
| Peak reported Forge working set | 18.327 GiB |
| Lowest commit headroom | 12.744 GiB |
| Lowest available RAM | 4.259 GiB |
| Peak dedicated VRAM | 9.789 GiB |
| Peak shared GPU memory | 0.124 GiB |
| Peak sampled GPU temperature | 61 C |

Existing `forge_klein_readiness.check_klein_host_memory` requires 32e9 total physical bytes and treats available RAM and
Windows commit headroom as observations only. Reusing that gate unchanged removes the experiment's provisional
37 GiB commit-headroom / 20 GiB available-RAM launch floors; the single successful output does not validate that reduction.
The existing executor pressure diagnostics do not establish replacement Z-Image host-memory limits.

| Alternatives considered before owner selection | Concrete behavior and limitation |
| --- | --- |
| Retain the provisional 37 GiB commit / 20 GiB available-RAM floors before every dispatch | Explicitly carries those conservative experimental floors into v1; unknown readings refuse. Not claimed safe or calibrated. A retained model may block the next job until the operator releases resources; no automatic unload/restart is added. |
| Prepare the profile but keep production dispatch disabled pending separately approved canonical acceptance | No production resource-risk expansion; the first full StableNew generation and final admission policy remain separately authorized work. This does not meet normal enablement yet. |
| Reuse the 32-GB-class total-RAM gate and current pressure diagnostics only | Allows dispatch without the experimental available-RAM/commit floors. Owner must explicitly accept the changed risk; neither observations nor the profile label imply safe repeated operation. |

The owner explicitly selected the third alternative: the existing total-RAM gate and pressure diagnostics only, accepting
removal of the provisional available-RAM/commit floors. Dispatch refuses below 32,000,000,000 total physical bytes;
available RAM and commit headroom are observational only. This choice is risk acceptance, not validated safe repeated-run
headroom. No pagefile/CUDA/offload/GPU configuration is changed.

## Deterministic validation and delivery boundary

New focused suites cover profile identity/version/replay, near names, conflicting intent including nested module fields,
native PromptPack rejection before adaptation, CLI construction, tiny served-file full hashes/cache invalidation,
missing/ambiguous/wrong catalog paths, pin/marker/source drift, owned endpoint requirements, total-RAM-only admission,
Tk-free fixed/optional control projection and draft restoration, and canonical JobService/SQLite/runner/executor/HTTP
execution. The HTTP fake proves the exact POST, image manifest/history provenance, Z-Image/Klein/SDXL module transitions,
sampling drift refusal, asset/pin refusal before module writes, unconfirmed selection and one ambiguous POST without replay.
The fake image is not a physical image-quality or hardware acceptance result.

Validated source commit: `cf2eb3382f2d20cb98b0edb71eeec2bf1d16c106` (base
`ef3fba8a0776548c4ac34a003452fa2402bdef32`). The subsequent closeout changes documentation only and reuses this evidence.

| Local check | Result |
| --- | --- |
| Affected deterministic suites | 583 passed in 34.71 s: image backends, Klein/Z-Image compilation and canonical integration, PromptPack/CLI builders, GUI projections and managed-runtime pin checks |
| Full repository Ruff | PASS |
| Supplementary scoped mypy | PASS, 8 source files; pre-existing missing `psutil` typing stubs excluded with `--disable-error-code=import-untyped`; no dependency or canonical gate change |
| `python tools/ci/run_pr_gate.py` | PASS: completeness (536 tracked Python sources), controller ratchet (4 controllers, unchanged ceilings), Ruff, required mypy (10 files), isolated collection (8,324 tests), required smoke/contracts (386 passed) |
| Collection/smoke repository-content guards | PASS, repository unchanged |
| Independent read-only aggregate review | PASS after repairing nested module-selection conflict validation and adding both alias regressions; profile identity, wire payload, asset/pin checks, transitions, compiler/admission parity and qualification wording reviewed |
| Scoped aggregate diff and `git diff --check` | PASS |

The canonical fake traverses JobService, SQLite and `PipelineRunner.run_njr` to the real executor and client HTTP boundary.
It records the exact 14-field generation POST with `distilled_cfg_scale: 9.0`, CFG 1, Euler/Beta/9, 1024x1024 and one image;
the saved image manifest and history carry the same effective request and confirmed selection. It also verifies frozen
NJR identity, profile/module transitions and refusal without replay after an ambiguous POST. These deterministic results
establish application behavior, not physical image quality or hardware stability.

No local source/test blocker remains. Hosted required Python 3.14 CI has not run for this branch, so this is ready for
publication review, not merge-ready. Publication and the first normal StableNew Z-Image physical acceptance require
separate current authorization. No physical qualification case was rerun, promoted, edited or cleared by this package.
