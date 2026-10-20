# PR-VID-MOTION-212 — Conditioning semantics and motion fidelity

Audit date: 2026-10-19. **Outcome A: repair a demonstrated verification defect.**
The registered Wan-Animate-2 conditioning graphs are compatible with the pinned native node.
No generation-path defect explaining failed reference-bound locomotion was established.
No improvement in generated motion is claimed; no generation was performed.

## Execution profile and boundaries

- Standard; Local/Desktop. Start: `1296aecd5418cad2beead7a661dd317d5344c90e`, including PR-210.
  Live `refs/heads/main` matched before work. Branch: `video/motion-212-conditioning-audit`;
  worktree: `C:/Users/rob/qual/StableNew-motion212`, initially clean.
- PR-211 owns the dirty `C:/Users/rob/projects/StableNew-main` checkout on
  `video/quality-211-experiment-review`. Its changes were neither copied nor edited.
- **Model recommendation:** Claude Code Sonnet 5.5 High / Codex GPT-6.1 Sol High: sufficient for
  version-sensitive source tracing and CPU regression coverage without a second discovery pass;
  retain the current productive host. Planning estimate from authorization: approximately 3M
  cache-read and 40k output tokens, not measured consumption. No specialist was needed.
- **Controller Surface Assessment:** no controller/coordinator modifications or line growth.
- **Token-Efficient Validation Plan:** reuse historical output verdicts; read pinned source without
  importing it; run new wiring/refusal tests, existing compiler/controls/version/PR-196/PR-210 tests,
  then the canonical local required gate once; inspect aggregate diff and whitespace. Hosted
  `required`, `full-suite`, `windows` remain a separate publication/integration verdict.
- No runtime start/stop/configuration, GPU/model inference, generation POST, weights download,
  graph edit, governance promotion, dependency addition or protected publication action.
  Native SVD XT remains the only accepted production video backend; Animate-2 remains per-job opt-in.

## Evidence notation and source identity

**S** = verified pinned-source fact (static inspection, not executed model behavior);
**R** = verified repository contract; **H** = historical experiment/accepted observation;
**I** = inference/hypothesis; **U** = unknown or untested. A tensor path is not quality evidence.

Both installed managed source trees were read and their Git HEAD and clean status verified:

| Catalog versions | Managed source checkout under `C:/Users/rob/AppData/Local/StableNew/ManagedComfy/` | Exact revision |
|---|---|---|
| 1.0.0, 1.1.0 | `v0.37.0-py313/source` | `73c9bad4d21e7addbe1d13bc92eee0f1431b017d` |
| 1.2.0 | `v0.38.0-py313/source` | `6b747c0428c343e1417219641db93a4fb7cb69ae` |

`config/managed_comfy_runtime.json` pins the latter. No runtime interpreter was executed.
`WanAnimate2ToVideo`'s class source, extracted with Python AST and hashed as UTF-8, is identical
in both: SHA-256 `7e1f497983ab63a68e5ef5439b3ef4e9295f79f78530c9dc5de16a8238475f05`.
The model implementations differ in attention/modulation plumbing and cache pinning; they are
not claimed byte-identical or numerically equivalent. The influence paths described below occur
in both. Read these paths at the revision for the job, never at an assumed latest release:

- `comfy_extras/nodes_wan.py`, `WanAnimate2ToVideo.execute` (v0.38.0 lines 1299–1382).
- `comfy/ldm/wan/model_animate2.py`, `WanAnimate2SelfAttention.forward_gen` and
  `WanAnimate2Model.forward_orig` (reference values at lines 49–50; pose values at 372–373).
- `comfy/model_base.py`, Animate-2 extra conditions; `comfy/samplers.py:608–627`.
- `comfy_extras/nodes_video.py`, `LoadVideo` / `GetVideoComponents`;
  `comfy_api/latest/_input_impl/video_types.py`, file decode and rotation.
- `comfy_extras/nodes_post_processing.py`, `ResizeImageMaskNode` / `scale_dimensions`;
  `comfy/utils.py:1107`, `common_upscale`; `nodes.py`, `CLIPVisionEncode` / `ImageFromBatch`;
  `comfy/clip_vision.py`, `encode_image`; `comfy/clip_model.py:6`, `clip_preprocess`.

Current first-party context, consulted on the audit date:
[node documentation](https://github.com/Comfy-Org/docs/blob/main/built-in-nodes/WanAnimate2ToVideo.mdx),
[official template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan_animate2.json),
[announcement](https://blog.comfy.org/p/wan-animate-2-is-now-available-in).
These describe raw driving-video conditioning and separate motion text. The template's bytes
hashed to `951fb2140c55ef8011a1ddc60639b0c76a5bd99a77212a7ef587af1b7df74652`.
Its conditioning consumer 587 takes RGB from resize 600, reference from resize 590, motion text
from 585, reference vision from 589 and driving first-frame vision from 598/599. It includes
extension/length wiring beyond StableNew's bounded single clip. This supports architectural
compatibility, not identity of the whole latest template, settings or qualification envelope.
The pinned local code is the execution authority; online promises establish no success rate.

## Operator → NJR → compiler → graph → runtime trace

Repository entry points: `workflow_catalog_wan_animate2.py`, `video_workflow_njr_builder.py`,
`workflow_controls.py`, `workflow_compiler.py`, `comfy_workflow_backend.py`.
The compiler resolves declared `WorkflowInputBinding.source_field` values and renders the template;
the backend verifies/uploads file inputs and replaces local names with Comfy upload names.
It does not choose a different driving source or synthesize motion text.

| Operator/input | Frozen NJR / request and compiler binding | Graph input and pinned consumer | Class |
|---|---|---|---|
| Reference image | `freeze_inputs` prepares PNG; NJR `input_image_paths[0]` → request `input_image_path` → `source_image` | 7 `LoadImage.image` → 10 `reference_image`; node area/center-resizes first image, VAE-encodes RGB into the reference latent slot | R/S |
| Reference visual identity | Same prepared PNG, same binding | 7 → 8 `CLIPVisionEncode(crop=none)` → 10 `clip_vision_output`; model receives penultimate hidden states as generation visual context | R/S |
| Driving file | `video_workflow.pose_video_path` / `pose_video_sha256` → `pose_video`; prepared jobs name PR-210's derived file | 18 `LoadVideo.file` → 19 `GetVideoComponents` output 0 (images) → 20 resize → 10 `pose_video` | R/S |
| Driving geometry | Reference policy freezes `source_preparation.target_dimensions.width/height` → `target_width/height` | 20 `ResizeImageMaskNode`: scale dimensions, area, center; 10 reuses width/height and area/center-resizes again at matching dimensions | R/S |
| Pose representation | Same ordered decoded RGB frames, not skeletons | 10 slices offset then length, holds final frame if short, VAE-encodes RGB as `pose_video_latent`; model-base maps to `pose_latents`, consumed by the pose branch | S |
| Driving visual context | Same file and node-20 image batch | 20 → 21 `ImageFromBatch(batch_index=0,length=1)` → 22 `CLIPVisionEncode(crop=none)` → 10 `clip_vision_output_pose`; model-base maps hidden states to `clip_fea_pose` | R/S |
| Appearance/background prompt | Stripped form `prompt` → NJR stage/request `prompt` → binding `prompt` | 5 `CLIPTextEncode` → 10 `positive` → generation text context | R/S |
| Motion Prompt (1.1/1.2) | `resolve_operator_controls` strips explicit `pose_prompt`; blank/whitespace falls back to stripped main prompt; freezes `operator_controls.pose_prompt` | Binding of that field → 23 `CLIPTextEncode` → 10 `positive_pose` → first conditioning tensor as `cross_attn_pose` → model `context_pose`; same pose text also attached to negative conditioning | R/S |
| Motion text (1.0) | No operator control or node 23 | `positive_pose` unconnected, runtime falls back to `positive`. Preserved replay behavior | R/S |
| Negative Prompt | Blank uses catalog stock Wan negative; frozen stage/request → `negative_prompt` | 6 → 10 `negative` → 13 sampler; CFG=1 makes uncond unused under the graph's default sampling options. Changing negative text cannot fix this graph's motion | R/S |
| Pose Strength | 1.1/1.2 `operator_controls.pose_strength`, float 0–10, default 1 | 10 `pose_strength` → model condition → pose attention **values** multiplied by strength per block; keys remain. Zero does not remove the branch or its attention normalization | R/S |
| Pose Start / End | Floats 0–1, defaults 0/1; ordered start ≤ end; invalid/non-finite/out-of-range refused without clamping | 10 attaches pose values to conditioning sampling ranges; complementary ranges omit pose values, skipping pose branch. These percentages are denoising progress, not video frame windows | R/S |
| Reference Image Strength | Float 0–10, default 1; same validation | 10 attaches `reference_strength` outside pose windows; model scales reference-slot attention values at every block. It does not crop/reposition the reference or directly scale its CLIP embedding | R/S |
| Seed, length, output cadence | Seed/frame count frozen; legal 17–81, step 4, offset 1; default 41; FPS=24 | 13 noise seed; 10 length/zero offset/batch 1; 14 trims reference latent slots → 15 VAE decode → 16 `CreateVideo` at 24 → 17 save | R/S |

Sampler remains LCM/simple, 10 steps, CFG 1, shift 5; scheduler takes the unshifted loader model
while sampling takes node 9's shifted model, as qualified. No cache, context window, continuation,
pose extraction, face preprocessing or hidden temporal resampling is inserted.

**Geometry detail (S/R):** Reference preparation EXIF-transposes, converts to RGB and uses Pillow
LANCZOS with a floating centered cover box. Portrait/square targets are 480×832; landscape 832×480.
Comfy driving decode applies frame rotation; center crop uses integer symmetric offsets from
`round`, then area resize. Reference and driving interpolation therefore differ intentionally.
Both pose branches start from the same node-20 batch and frame 0; at offset zero there is no
temporal disagreement. CLIP `crop=none` still bicubic-resizes to its configured square encoder
size and normalizes pixels: it does not mean unchanged aspect ratio. Both reference and pose
vision use this policy. VAE input remains at video geometry; a square vision embedding and
video-shaped VAE latent serve different roles and are not a representation defect.
Temporal VAE compression and latent attention mean “one driving frame per output frame” describes
input selection, not guaranteed framewise generated pose correspondence.

**Provenance limits (R/U):** Version plus immutable template identifies geometry/wiring;
NJR freezes prompts, seed, controls, frame count, prepared reference path, driving path/hash and
source-preparation policy. PR-210 adds original/derived hashes, exact source indices, settings,
processing and decoded-frame verification. Batch source identity includes both reference hashes.
Execution `control_record` hashes the effective prepared reference, records driving identity,
controls and pinned provenance; manifest also records compiled workflow and reported actual runtime.
Server-reported version is not cryptographic attestation of a running checkout. An unprepared
job has no PR-210 per-frame identity record, and an unbatched NJR should not be described as
carrying every original reference hash. No new persisted authority is needed for this audit.

## Historical evidence reused and exact-input check

| Evidence record in this directory | Accepted observation retained (H) |
|---|---|
| PR-VID-150 motion characterization | Structured TI2V prompting improved a local gesture; requested steps left feet planted. Different model/path, not an Animate-2 contract test |
| PR-VID-181 real driving pose | Older Wan2.2-Animate detector-derived pose improved gesture; reference stayed planted while a separate figure moved; background unstable |
| PR-VID-182 basic retarget gate | That earlier reference/driving pair failed the conjunctive front-facing/stretched applicability gate; no retarget or generation occurred |
| PR-VID-183 controlled basic retarget A/B | Compliant source and materially different retargeted conditioning, but reference-bound locomotion still not demonstrated |
| PR-VID-184R/S and PR-VID-185 adjudication | Preserve `WAN_ANIMATE_2_OWNER_MOTION_VALUE_PASS` for its case alongside correlation 0.139–0.151 below frozen 0.30; representative resource/usability evidence remained insufficient for promotion |
| PR-VID-192 controls, section 8 | One source/seed: motion-only text removed ghosts and traveling action together; pose 1.5 raised a proxy without restoring action; reference 1.3 further suppressed movement |
| PR-VID-196 and PR-VID-MOTION-210 | Sequential decode-order frame consumption, no implicit FPS conversion, final-frame holds; optional explicit exact frame planning and verified preparation already exist |

PR-181–183 concern the older separate pose-preprocessing pipeline. They suggest a failure pattern,
not that native Animate-2 should receive skeletons. PR-185's historical “no integration” heading
does not supersede today's experimental catalog integration or authorize promotion.

PR-192's preserved result (ghost frames / correlation / root translation):

| Arm | Controls relative to A1 | Ghost frames | Correlation | Root translation |
|---|---|---:|---:|---:|
| A0 | Main prompt reused on pose branch (1.0.0) | 28/39 | 0.042 | 0.443 |
| A1 | Separate motion prompt; strengths 1; full window | 0/39 | 0.253 | 0.012 |
| A2 | Pose strength 1.5 | 0/39 | 0.315 | 0.025 |
| A3 | Reference strength 1.3 | 0/39 | 0.167 | 0.006 |

Read-only local cross-check: `C:/Users/rob/projects/StableNew/reports/vid192/experiment/acceptance.json`
and A1's persisted manifest under `workspace/output/Reprocess/20260930_072219_b8e2beceb77a-unknown-none/`
agree on inputs and seed 19103. Existing files were hashed again:

- Reference `C:/Users/rob/qual/vid184/env/inputs/source_fullbody.png`:
  `362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb`.
  Header/Pillow: 480×832, EXIF orientation 1; no geometry crop at this target.
- Driving `C:/Users/rob/qual/vid184/env/inputs/B_locomotion_driving_39f_candidate.mp4`:
  `d761eb58876cef2bd344731d3dd482b5f59cbd9478c6e8b5e0da94c48266677d`.
  Existing bounded inspector (metadata only): H.264/yuv420p, 464×832, no rotation, reported 39 frames,
  24/1 fps, duration 1.625 s; sample aspect ratio 376:377. The graph works on decoded pixel
  dimensions, not a SAR-based spatial correction.
- Pinned integer crop: `y=round((832 - 464/(480/832))/2)=14`, `x=0`; rows `[14,818)`
  retained (804/832), about **3.37%** of pixel area removed before resize to 480×832.
  This distinguishes the exact graph crop from the advisory's floating cover-box approximation.
- At 41 frames: source indices 0–38 then 38,38; no speed conversion (24/24); output 41/24 s.
  The two holds are verified selection behavior, not proof of a cause of the failed action.
- Existing driving contact sheet and reference were visually inspected: frontal upright reference
  versus a lateral running profile, with different initial limb pose and backgrounds. This is a
  visual observation from samples, not a detector-based coverage/scale/identity measurement. No
  claim is made that feet/hands remain visible in every decoded or cropped frame.

## Competing hypotheses and challenge

| Hypothesis | Supporting evidence | Counterevidence / limits | Classification |
|---|---|---|---|
| H1 framing/viewpoint mismatch | Sampled frontal reference versus lateral runner; initial pose differs; crop can lose extremities | Actual pixel-area loss is small for PR-192; no measured body coverage/scale across frames. Current reference/driving vision share intentional preprocessing policies | Plausible I; cause U |
| H2 motion-text conflict | A0→A1 removes duplicate and action; pose branch has independently encoded text and vision (S) | A1 already specifically describes lateral high-knee/sprint motion. Better wording is not demonstrated to recover action; one seed/source only | Effect confirmed H; remedy U |
| H3 reference values suppress displacement | Real reference attention-value scaling (S); 1.3 arm nearly static (H) | Dose response below 1.0 unknown; A3 also has worse histogram proxies; reference value scaling is not a monotonic motion control | Leading bounded experiment I; remedy U |
| H4 cadence/alignment | 39→41 ends with two holds; initial limb pose differs from reference | 24 fps matches output; no hidden resampling, trim or stale first-frame path in registered graphs; two final holds do not establish whole-clip suppression | Software timing mismatch refuted for these inputs; initial-state/model effect U |
| H5 wrong representation | Older Animate used extracted pose; name `pose_video` can mislead | Exact pinned node VAE-encodes RGB; repository graph and official native architecture agree; both pose branches share frame 0 geometry | Skeleton-replacement hypothesis refuted S/R |
| H6 model/input/settings limitation | Correct contract coexists with failure, and older/native paths differ; accepted native success exists for another case | Source inspection cannot measure capability or separate weights/input/seed effects; no universal impossibility conclusion follows | Unresolved U |

Challenge performed against a different method for each leading claim: dataflow versus node names
(H5), actual crop arithmetic/metadata versus visual framing impressions (H1/H4), paired historical
arms versus tooltip interpretation (H2/H3), and the accepted PR-185 success versus a model-wide
failure claim (H6). No independent second agent or fresh output review is claimed.

## Candidate decision: exactly one implementation outcome

| Candidate and mechanism | Evidence and contradiction | Operator value / feasibility / safety | CPU proof; physical evidence; contract effect |
|---|---|---|---|
| **A, selected: reject falsely verified source chains** | Reproduced on baseline: `LoadVideo.file=stale-driving.mp4`, `GetVideoComponents` output 1 (audio), or direct LoadVideo→pose each still returned verified. Correct catalog paths contradict a claim that this caused PR-192 | Trustworthy preparation eligibility and timing explanation; pure bounded traversal, no I/O/dependencies | CPU proves refusal and unchanged registered paths; no generation required for this defect. No published graph or model/runtime contract changes |
| B: add framing diagnostic | H1 credible; current readiness already reports crop/framing/rotation, reference preview and driving thumbnails; PR-210 provides exact selected-frame previews | A duplicate diagnostic adds little demonstrated value; omit | CPU could prove pixels/crops, never semantic transfer. No new diagnostic is justified here |
| C: reduce reference strength to 0.8 | Real value-scaling path and A3 suppression support testing; reverse-direction improvement is untested | High-value two-arm follow-on; physical risk and identity tradeoff require owner approval | CPU proves only binding; fresh outputs needed. Uses declared controls, no graph revision |
| Motion-text rewrite | A1 text materially changed outcome; existing A1 is already action-specific | Rank after reference-strength test; no automatic rewriting | Needs separately frozen wording and physical evidence; no authorized executable rewrite |
| Match source/reference viewpoint and initial pose | Sampled mismatch supports H1; small crop alone does not | Rank after the two-arm control test; asset-selection confounds need explicit new inputs/hashes | CPU can show input geometry, not fidelity. No automatic transform or retargeting |
| Replace RGB with skeletons | Contradicted by pinned consumer and native official architecture | Reject; would alter published graph/model input semantics | Requires a new version and separate owner decision; not implemented |

`driving_frame_consumption.py` now checks the **ordered** ResizeImageMaskNode→GetVideoComponents→
LoadVideo path, correct named input and integer output-0 ports, and terminal `{{input.pose_video}}`.
Malformed/cyclic/disconnected paths fail closed. Offset must be literal integer zero and continuation
must be absent. Node IDs may change; registered versions still verify. This repairs the proof
predicate consumed by advisories and `motion_source_contract`; it neither changes media nor repairs
the output-quality limitation. It is not a general attestation of all graph bindings or actual
server source. Broader conditioning wiring is protected by explicit compiled-graph regression tests.

## Future A/B preregistration — NOT EXECUTED / requires owner authorization

Question: for the PR-192 A1 inputs, does reducing **only reference-image strength** from 1.0 to 0.8
permit the intended reference character to perform lateral high-knee locomotion without losing
identity or producing another moving figure? This discriminates a reference-restraint mechanism
at one fixed input/seed, not model-wide capability.

- Two arms, **one seed (19103), one attempt per arm, two runs total**. A=1.0; B=0.8. Run A then B
  from the same documented owner-approved resource state. No sweep, retry, third arm or continuation.
  Historical A1 is context; a fresh paired A is required on the current pinned runtime.
- `wan_animate2_drive_i2v_v1@1.2.0`; Comfy `6b747c0428c343e1417219641db93a4fb7cb69ae`, managed
  Python 3.13 / Torch 2.14.0+cu130. Freeze actual runtime/launch identity before admission. Keep
  `--disable-pinned-memory` and existing launch policy, no cache/context windows/custom nodes.
- Reference and driving paths/hashes are the exact PR-192 identities above. Use the unprepared
  39-frame clip in both arms (no PR-210 conversion or changed window). Freeze prepared-reference
  bytes/hash from canonical admission before the first run and require equality across arms.
  Historical A1 prepared-reference SHA was `9c7915509bd7ac8961b255bda4ac1eca282056977389742eb782235c2aa74ec5`;
  a difference requires explanation and owner acceptance before proceeding.
- Model files/hashes, frozen from the catalog (verify identity before any future run):

| File | SHA-256 |
|---|---|
| `wan_animate_2_distill_int8_convrot.safetensors` | `d2e566ecac3f164cb1a6b63dc7d868d6678c9affa49fbceb3abe4f9458f89c8a` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68` |
| `Wan2_1_VAE_bf16.safetensors` | `1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9` |
| `clip_vision_h.safetensors` | `64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161` |

- Appearance text, byte-for-byte after canonical trimming:
  `A young woman in a navy athletic top, navy leggings and white sneakers exercising in a bright studio.`
- Motion text:
  `A person performs a high-knee running drill that transitions into a full sprinting stride, moving laterally from left to right across a static frame with continuous forward locomotion and alternating arm-leg swing.`
- Pose strength 1.0, window 0.0–1.0, offset 0, 480×832, 41 frames, 24 fps; same stock negative,
  LCM/simple, 10 steps, CFG 1, shift 5. Freeze full compiled graphs and digest; their only effective
  conditioning difference must be reference strength. Qualified original graph provenance remains
  `9ef8dae44d330e5af05c70fccd02d86d0855b4fb983d1913f8f7f8a012c3928c`, not a digest of every compiled job.
- Expected discriminating observation: B performs visible alternating high-knee steps and lateral
  root travel **on the reference character**, where A remains planted, without unacceptable identity,
  anatomy or scene degradation. Falsified for this pair if B remains planted, merely moves a ghost,
  changes identity, or increases undirected motion. If A already succeeds, the proposed baseline
  failure was not reproduced; record inconclusive mechanism rather than declaring B a fix.
- Review full clips for intended actor/action/direction, footfalls and root travel, persistent
  duplicates, identity/face, limb anatomy, temporal stability, scene continuity and actual usefulness.
  Owner judgment determines usefulness. Contact sheets and motion-curve/optical-flow proxies are
  supporting evidence only; no automatic winner, no universal 0.30 hard quality gate.
- Canonical submission only: Intent→Compiler→immutable NJR→JobService→SQLite queue→run_njr→handler→
  artifacts/history. Preserve NJR IDs, seed, file/graph/model hashes, source indices/holds, actual
  runtime, prompt correlation IDs, telemetry, manifests and output hashes/decodability. PR-211 is
  optional future rubric support, not a dependency.
- Future approval must explicitly authorize the two runs and their runtime lifecycle/resource
  monitoring. Honor existing readiness floors (10,000 MiB available-to-Comfy VRAM, 16 GB RAM),
  owned-process boundaries and per-job release. Refuse changed identities or insufficient readiness;
  stop on device loss, OOM or ambiguous submission, preserve evidence, and never auto-replay or
  reboot/reset/reconfigure. Do not invent new thresholds or treat previous clean runs as stability proof.

## Validation, review and closeout

- Focused new + PR-210 plan: **67 passed** (Python 3.14.8).
- Compiler, controls, version hashes, Wan-Animate-2, source preparation, all PR-196 and PR-210
  video tests plus new tests: **342 passed, 1 skipped**; optional qualified flat-graph fixture was
  not configured in that invocation. Both installed pinned-node source checks ran successfully.
  The located `C:/Users/rob/qual/vid184/env/evidence/run5_flat_graph.json` then enabled that exact
  skipped test: **1 passed**. All 343 scoped cases therefore have passing CPU evidence.
- The first sandbox invocation failed in pytest setup because its temp directory was unwritable.
  Re-running with dedicated `C:/Users/rob/qual/motion212-validation` temp storage passed; no
  source/test acceptance was weakened.
- `python tools/ci/run_pr_gate.py`: **PASS**; completeness, controller ratchet, `ruff check .`,
  strict smoke/mypy/format/architecture ratchets, isolated collection (**10,340 collected**) and
  required smoke (**349 passed, 1 warning**) all passed. Repository unchanged by gate. Log:
  `C:/Users/rob/qual/motion212-validation/pr-gate.log`. Full census/hosted Windows lane were not run.
- Aggregate review: only this report, the living video contract, the verification module and its
  new test file. `git diff --check` passed. No blocking in-scope finding remains; no post-review
  repair pass. The historical hypotheses remain output-validation questions, not repair requests.
- Existing coverage reused rather than duplicated: control defaults/ranges/fallback/refusals,
  unknown runtime revisions, published nine-spec digests, experimental admission, frame planning,
  lossless prepared identity and dispatch/replay checks. New coverage pins both visual branches'
  shared source/geometry and rejects counterfeit timing paths, including preparation refusal.
- Source repair is confined to the pure verification predicate. No review/rating/image Learning,
  repository/history schema, controller, process manager, workflow payload or dependency change.
  Security review triggers are not introduced by this static traversal repair.
- Residual risk: generated motion remains unqualified by this work; small historical sample,
  unmeasured per-frame body coverage, seed/input/model interactions, and runtime numerical
  differences remain. Source correctness cannot resolve them without authorized output evidence.
- No current capability, backend decision or hold changes: `STATUS.md`, roadmap, architecture and
  code maps remain unchanged. The living video contract changes only to describe verification.
- Publication/hosted CI: **not performed**. Stop after local commit. Next owner decision is whether
  to authorize publication of this bounded repair, and separately whether to authorize the two-run
  reference-strength A/B; neither authority follows from this report.
