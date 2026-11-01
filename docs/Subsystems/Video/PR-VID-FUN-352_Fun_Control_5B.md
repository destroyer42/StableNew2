# PR-VID-FUN-352 — Reference-guided Canny motion

## Execution profile

Standard, difficult cross-file boundary. Fresh Codex desktop session
`01a1987f-aac4-7161-8d96-8b7c106afc99`, started 2026-11-01T14:04:33.6850682-05:00
(America/New_York), from verified clean main `29881845a15eccaaa770da1e7b7cc9f943b31843`.
Worktree `C:/Users/rob/qual/StableNew-fun352`, branch `video/fun-352-controlled-motion-5b`.
The separate local VID-QUALITY-351 worktree is untouched; no open PR was found at discovery.

**Model recommendation:** Claude Code Sonnet 5.5 XHigh / Codex GPT-6.1 Sol XHigh,
either local Windows host. Cross-file identity, preparation and readiness checks justify this
tier for expected successful completion including retries. Expected 18M cache-read / 90k output tokens.
Actual model/effort and measured usage are reported at closeout, never inferred from this recommendation.

**Controller Surface Assessment:** JobService still validates then atomically submits through its
existing repository authority. One domain-admission delegate composes retirement and workflow
eligibility checks. No controller growth, new lifecycle, queue, process manager, runner or schema.

**Token-Efficient Validation Plan:** one focused discovery and compatibility pass; deterministic
catalog/compiler/input/GUI tests and disposable FFmpeg media; one aggregate security review,
bounded repair, one late canonical gate. No physical model, GPU or Comfy execution. Publication
and hosted CI require separate authorization.

## Registered contract

`wan22_fun_control_5b_canny_i2v_v1@1.0.0`, backend `comfy`, **experimental**.
It uses a reference image for appearance and the ordered Canny edges of an accepted driving
clip for movement. It does not guarantee identity, exact first-frame pixels, end anchors,
camera-control semantics, realism or an improvement in motion quality.

The product envelope is 17–49 frames in steps of 4 (4n+1), default 49, fixed 24 FPS,
one output, source-aware 480x832 / 832x480 geometry. These are product limits, not hardware
qualification results. A concrete seed is required before Preview.

**Hardware is NOT QUALIFIED.** No Fun Control memory threshold has been measured. Its declared
resource policy therefore blocks Queue, canonical JobService admission and backend startup,
even with experimental opt-in and abundant reported RAM/VRAM. TI2V qualification floors are
not borrowed. A future separately authorized qualification must establish host allocation
headroom and GPU evidence before an executable resource policy can be accepted. Because
published versions are immutable, qualification must not silently alter this frozen version.

## Verified upstream and assets

Installed managed source: clean ComfyUI v0.38.0 at
`6b747c0428c343e1417219641db93a4fb7cb69ae`. Source was inspected without importing or starting Comfy.
No runtime, Python, Torch or CUDA pin changed; no custom nodes.

The [official template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan2_2_5B_fun_control.json)
was read at Git blob `9bfbbc6fcd0a000bff39a186679c8453697aa7f2`.
Its shift 8, 20 steps, CFG 5, uni_pc/simple, denoise 1 and Canny 0.1/0.6 are frozen.
Its 704x704 / 121-frame example is intentionally replaced with the bounded product envelope.
The output end uses the existing frames-out architecture.

LFS metadata was verified at immutable
[model repository revision](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/tree/7c2bf7cd56b55e483b78e02fd513ec8b774f7643).
Every repository path is `split_files/<folder>/<filename>`:

| File | Comfy model folder | Bytes | SHA-256 |
|---|---|---:|---|
| wan2.2_fun_control_5B_bf16.safetensors | diffusion_models | 10003303280 | ace4718a7c87ee3e5606a68ab79142c4395e81aece76b8120bc886f0fbbe1d16 |
| umt5_xxl_fp8_e4m3fn_scaled.safetensors | text_encoders | 6735906897 | c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68 |
| wan2.2_vae.safetensors | vae | 1409400960 | e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156 |

The encoder and VAE match the existing TI2V identities. The official template uses these
architectures and bytes. Installed supporting files passed size/hash verification in place;
the Fun Control model is **missing**. No weights were downloaded, copied or loaded.

The repackaged revision's short README has no license declaration or license file.
The [upstream Fun Control model card](https://huggingface.co/alibaba-pai/Wan2.2-Fun-5B-Control/blob/03b7b533ee2580530b0a6d598cab6191e96c09f9/README_en.md)
declares Apache-2.0. The catalog records this underlying license source explicitly.

Local integrity reads only configured Comfy source/model folders and safe YAML model-path
declarations. It verifies full sizes and streaming SHA-256 digests, including every ambiguous
matching path. Unknown/mismatched revisions, missing files, truncation and wrong digests fail.
Selection makes no model-network request and never installs anything. Integrity work runs in
the existing readiness worker, outside Tk. Supporting weights are reused in place.

## Node and transport mapping

| Pinned node | Verified inputs / outputs used |
|---|---|
| UNETLoader / CLIPLoader / VAELoader | exact names; default weight dtype; CLIP type wan |
| ModelSamplingSD3 | model, shift 8 |
| CLIPTextEncode (two) | clip, positive/negative text |
| LoadImage | image; output 0 to ref_image |
| LoadVideo | file; output 0 is VIDEO |
| GetVideoComponents | video; output 0 is ordered IMAGE frames (audio is output 1) |
| Canny | image, low_threshold 0.1, high_threshold 0.6; IMAGE output 0 |
| Wan22FunControlToVideo | required positive, negative, vae, width, height, length, batch_size; optional ref_image, control_video; outputs positive, negative, latent |
| KSampler | frozen seed/settings; all three conditioning/latent outputs from Fun Control |
| VAEDecode / SaveImage | decoded samples to lossless PNG frames |

`start_image` appears in the Python implementation signature but **not its advertised schema**;
it is never bound. `ref_image` goes to reference latents, not exact start-frame conditioning.
The pinned node resizes/crops per frame and takes `control_video[:length]`; admission prevents
an unnoticed length mismatch. The pinned video decoder reads frames in decode order; it does
not convert frame rate on this path.

The existing `pose_video` carrier is reused as explicitly permitted by the package. For this
workflow its bytes are Driving / Control Video source material for Canny, not precomputed pose
maps. Wan-Animate-2's established interpretation and immutable versions are unchanged.

## Operator, Preview and integrity

Choose the workflow and reference; inspect the driving clip and use **Prepare Motion Source**.
For v1 an accepted prepared record is required, even for an already compatible clip, so the
ordered-frame verification evidence exists. Choose workflow-rate conversion if the clip is not
24 FPS. Preparation remains explicit, bounded, cancellable, lossless and content-addressed;
the existing plan shows selected/omitted/repeated/held frames before acceptance. No hidden
preparation occurs at dispatch. Missing evidence, a different length/rate or changed bytes refuse.

**Preview Frozen Plan** reuses the existing one-source batch preview worker/compiler and shows
the frozen seed, output length/geometry, reference/control hashes, graph digest, model manifest,
Canny settings and hardware hold. The preview remains readable while Queue is disabled. Form
edits invalidate it; file changes are refused by admission/dispatch checks. Unsupported anchor,
camera and depth controls stay hidden, and opt-in is never restored from saved state.

NJR stage config freezes the exact reference identities, full preparation record, graph/assets
and resource-policy identities. Build/admission rehash both original and derived files. Dispatch
rechecks geometry, FPS, legal length, seed, graph/assets and source bytes before runtime work and
again before upload. A hash-verified, at-most-256-MiB private upload snapshot prevents replacement
between validation and transport; its memory spool is 8 MiB and any disk spill is automatically removed.
No generation POST retry or process-ownership behavior changes. The existing frames-out encoder,
frame-count checks, RIFE support, artifacts/history and replay path are reused.

## Qualification handoff (proposal only)

VID-QUALITY-351 owns ratings; no duplicate evaluation implementation is added. Proposed paired
workflow cases: full-body forward walking, quarter turn, arm raise/reach, lateral camera move.
Baseline: approved TI2V-5B 1.3.0. Candidate: this exact experimental graph (or an explicitly
versioned later qualified successor). Use the same reference/intended motion and declared seeds
424242 and 424243; freeze driving-source identity, model/graph versions, frame counts and export.
Record source fidelity, subject stability, temporal continuity, anatomy/object integrity, scene
stability, action achievement and critical identity failures where the quality package supports them.

The candidate receives extra motion evidence: this compares complete operator workflows, not
an isolated model/sampler effect. Before any run, an owner-approved asset-acquisition/resource
qualification contract must name exact weights, telemetry, runtime authority and stop conditions.
Capture peak host allocation/commit and VRAM, device loss, cancellation/release behavior, completion,
frame integrity and owner visual ratings. Stop for device loss, unverified input/runtime identity,
allocation failure or unsafe teardown; no automatic replay, external-process kill or GPU recovery.
No study, weight acquisition, runtime launch or physical generation is authorized here.

## Accepted validation and review

The initial absence regression failed because the new workflow was not registered. The completed
feature-specific contract tests cover graph wiring, legal lengths, pinned assets and local byte
verification, exact prepared sources, canonical admission, frozen Preview identities, governance,
resource refusal and upload snapshots. A disposable 24-FPS FFmpeg clip independently verifies
the selected frame window in decode order. Historical spec digests remain unchanged; only the
new identity was added to catalog listings/snapshots.

Evidence retained outside the checkout at `C:/Users/rob/qual/vid-fun-352-20261101`:

| Evidence | Result |
|---|---|
| Initial broad focused run | 352 passed; two old catalog-list assertions subsequently updated |
| Updated focused GUI/catalog/upload set | 119 passed |
| Broad video + admission/GUI regression | 1462 passed, four existing opt-in/host skips; three catalog assertions subsequently updated and four FFmpeg-path failures subsequently verified with the installed explicit path |
| Repair core, including all seven prior assertion/FFmpeg failures | 141 passed, one existing source-opt-in skip |
| Affected Tk readiness contract file outside sandbox | 26 passed |
| Independent security/aggregate review | Two P2 blockers fixed together; independent bounded reverification PASS |
| Late canonical gate components | Completeness, controller, Ruff/mypy, formatting/architecture ratchets, Tk import boundary and isolated collection PASS; 15212 collected; required smoke 358 passed, one warning |
| Documentation/code-map and final diff checks | PASS |

The late gate initially stopped on unstaged new source, then typing/formatting issues, all corrected
without changing baselines. Passed components were retained and the canonical remaining steps
resumed. Sandbox socket restrictions blocked the smoke harness's disposable local fake server
with WinError 10013; the unchanged canonical smoke step passed outside the sandbox. A Tk/PIL
worker test also hit native 0xc0000008 under the sandbox, reproduced on unchanged starting main;
the complete affected test file passed outside the sandbox. Neither was repaired by changing
application behavior, skipping tests or weakening acceptance. Hosted required/full-suite/Windows
CI is not run because publication is not authorized.

Review findings closed: effective workflow identity now has the same normalized neutral-block
precedence at admission and execution; exact-prepared readiness no longer asserts automatic
raw-video hold/truncation/speed behavior. One inherited metadata phrase about the existing
negative-prompt default remains non-blocking, as does optional future prompt-equality hardening.
No physical Fun execution or quality claim is established by this evidence.

Participating review thread: `01a19891-42df-7723-8826-116a1c5e6d52`,
2026-11-01T19:23:46Z–19:31:34Z, including one bounded local review repair/reverification.
Session telemetry identifies the primary as GPT-6.1 Sol, High. Published repair passes are zero;
the whole-window token measurement and final SHA belong in the external closeout report.
