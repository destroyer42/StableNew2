# PR-IMG-MODELS-155 - Z-Image-Turbo FP8 exact-bundle Forge enablement

Disposition: **HOLD_RESOURCE_ADMISSION_DECISION**. Evidence reconciliation and bounded design are complete;
production selection, profile resolution and dispatch are not enabled. The owner implementation contract requires a
decision before materially changing accepted hardware risk or establishing new resource thresholds. No physical run
is authorized in this package. The original PR-154B result remains `INSTRUMENTATION_GAP`.

Integrated baseline: `ef3fba8a0776548c4ac34a003452fa2402bdef32` (PR #84), freshly fetched for this package.
Local branch: `codex/img-models-155-zimage-exact-bundle`, worktree `C:\Users\rob\projects\StableNew-main`.

Execution Profile + Model/Reasoning Recommendation: Standard, substantial but bounded model integration within the
existing image architecture. Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High; Local/Desktop fits the local evidence,
model files and Windows resource context. Cross-command profile identity, actual payload and replay parity make repair
cost significant; High is the lowest effective recommendation for this package. One primary implementation session and
one independent read-only aggregate reviewer; no chain of agents.

Controller Surface Assessment: no new controller responsibilities or ratchet increase. Use the existing backend/profile,
compiler and model-policy projection seams. No production lifecycle or process-manager change is authorized.

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

## Proposed exact product envelope

Candidate immutable reference: `backend_options.image.model_profile = {"id": "z_image_turbo_fp8_scaled", "version": 1}`.
This reference does not exist in production until the resource decision is resolved and the integration is implemented.

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

## Bounded implementation design after the decision

Keep `Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Forge backend ->
Artifacts/History`. Add a small shared exact-profile resolver with independent Klein and Z-Image contracts, not a second
registry or executor. Route new NJR stamping, model policy, compilation and backend/replay resolution through that resolver;
retain frozen Klein v1/v2 semantics and refuse unknown profile references and unsupported dependency-bearing models.

Extend the existing served-asset identity and Forge catalog authorities for the exact trio; filenames only suggest a
candidate and never satisfy readiness. Verify served paths, fingerprint-bound full hashes and pin, confirm both modules,
select through the existing client, then verify readback. Preserve ordinary Forge module-baseline normalization and test
Z-Image/SDXL/Klein transitions. No lifecycle adoption, restart or ambiguous POST replay is added.

`executor.py::run_txt2img_stage` currently builds a fixed dictionary without `distilled_cfg_scale`. Add one small,
profile-specific payload projection and immediately-before-dispatch validation there; prove with a fake client at the
actual executor POST boundary that shift 9 reaches the wire as `distilled_cfg_scale`, never `shift`. SDXL, Klein and
A1111 payloads retain their existing meaning. Existing artifact/history provenance records the frozen profile, exact
identities, pin, requested/effective parameters, selection confirmation, seed and canonical job lineage.

## Resource decision required before enablement

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

| Alternative requiring owner selection | Concrete behavior and limitation |
| --- | --- |
| Retain the provisional 37 GiB commit / 20 GiB available-RAM floors before every dispatch | Explicitly carries those conservative experimental floors into v1; unknown readings refuse. Not claimed safe or calibrated. A retained model may block the next job until the operator releases resources; no automatic unload/restart is added. |
| Prepare the profile but keep production dispatch disabled pending separately approved canonical acceptance | No production resource-risk expansion; the first full StableNew generation and final admission policy remain separately authorized work. This does not meet normal enablement yet. |
| Reuse the 32-GB-class total-RAM gate and current pressure diagnostics only | Allows dispatch without the experimental available-RAM/commit floors. Owner must explicitly accept the changed risk; neither observations nor the profile label imply safe repeated operation. |

No alternative has been selected. No new numeric safe limit is invented, no pagefile/CUDA/offload/GPU configuration is
changed, and no production admission path is enabled while this decision is pending. Implementation, gate and aggregate
review remain to be completed after the owner choice; this branch is not merge-ready.
