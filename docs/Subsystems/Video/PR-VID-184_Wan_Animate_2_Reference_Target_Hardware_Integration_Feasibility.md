# PR-VID-184 - Wan-Animate-2 Reference Capability, Target-Hardware & Integration Feasibility

Status: **`PR-VID-184 — IN PROGRESS — REMOTE_REFERENCE_GATE_BLOCKED_BY_SUBSCRIPTION`**. This is a
research/feasibility-planning package. No Animate-2 output has been generated, no Comfy Cloud run
has occurred, no production `src/` change was made, no workflow was registered, and no
GPU/Comfy-config/pagefile/driver setting was changed. Q1-Q4 (see below) are not yet answered. The
owner created a Comfy Cloud account and fully configured the pre-registered workflow, but the first
attempted run was blocked **before queueing** with *"A cloud subscription is required to queue
workflows"* — no free credits were available on the account despite Comfy's own advertised Free
Tier/"5 free runs" claims (2026-09-26, owner-observed). **This is classified as an
infrastructure/access result, not a Wan-Animate-2 capability finding**, and this package is not
abandoned: see "Phase D — REMOTE_REFERENCE_GATE_BLOCKED_BY_SUBSCRIPTION" and the reframed Phase G
decision tree below for how the package continues without paid remote access.

## Execution profile

- **Execution class:** Standard (owner correction 2026-09-26, supersedes the original "Terra High"
  label) — research, qualification tooling, and docs; no `src/` change.
- **Model/reasoning recommendation:** Claude Sonnet 5, High effort for synthesis/writing; a
  general-purpose web-research subagent (current, dated, source-tagged) for Phase A and the
  Comfy-version-gap addendum, per the repository's provider-neutral capability guidance.
- **Controller surface assessment:** none. No `src/` production controller, coordinator, resolver,
  backend, runner, or graph changed. `src/video/video_backend_types.py` and
  `src/video/video_workflow_intent.py` were inspected read-only for Phase F contract mapping.
- **Token-efficient validation plan:** deterministic tests only (no GPU/network) for the scoring
  contract, the tracker, and the blinding tool; Ruff/format on the new Python surfaces;
  `git diff --check`; required GitHub Python 3.11/3.12 CI. Do not chase informational
  full-suite/Journey debt unrelated to this package.

## Owner amendment (2026-09-26, pre-upload/pre-generation)

Applies to PR #9 at or after `47a0588`; no Animate-2 output existed at amendment time, so this is a
pre-registration amendment, not a post-hoc change. It corrected five things, each reflected in the
sections below: (1) the cloud A/B is **Base+LightX2V vs. Distilled** (workflow identity), not
"Case A/B" (which already means gesture/locomotion in PR-VID-170/180/181, and retarget-off/on in
PR-VID-183 — reusing that label for a third meaning was rejected); (2) the 29-frame driving clip is
retrimmed to a longer window from the same source file; (3) the scoring contract must be
control-validated (against real detector output, not just frozen thresholds) before any upload;
(4) a fixed 5-run matrix with two pre-registered seeds, run remotely against shipped-default
settings for runs 1-4 and a cache-OFF local-candidate configuration for run 5; (5) a human verdict
gate — Rob scores the pre-registered rubric blind to metrics and to arm identity, and PR #9 does not
merge until that verdict is recorded. Never describe Base+LightX2V as pristine upstream Base (the
LightX2V LoRA already step-distills it; see "Official Base-oriented settings" below).

## Accepted prior evidence (not repeated)

PR-VID-150 through PR-VID-183 discovery is treated as established (see `STATUS.md` and each
package's own report under `docs/Subsystems/Video/`). In particular: native SVD XT remains the only
production/default backend; Wan2.2 TI2V-5B prompt-directed motion is
`local_motion_viable_locomotion_weak`; Wan2.2-Animate v1 became resource-feasible and 480x832
interpretable, real detector-derived pose materially improved gesture transfer, but clean
reference-bound locomotion/root translation was never demonstrated — locomotion repeatedly produced
either a planted reference subject or a separate moving/ghost figure, including after basic
retargeting (PR-VID-183: `BASIC_RETARGET_APPLIES; REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`).
Background instability remained cross-case. Animate v1 remains unregistered. This package does not
spend further effort tuning Animate v1, `face_video`, FLUX enhanced retargeting, sampling settings,
or more v1 pose preprocessing.

---

## Phase A — Current upstream / Comfy inventory

Researched 2026-09-26 via a dedicated web-research pass (current sources only; first-party facts
distinguished from community reports; no community anecdote used as acceptance evidence).

**Naming.** The model is "Wan-Animate-2" (paper/GitHub org) but shipped files/HF repos use
"Wan2.2-Animate-2-14B" branding; both names refer to the same released model. [FIRST-PARTY]

1. **Upstream repo/release.** `github.com/Wan-Video/Wan-Animate-2` (Wan-Video org, Alibaba Tongyi
   Lab). Released 2026-08-07: inference scripts plus Base and Distillation weights. Paper:
   arXiv:2608.06009, "Wan-Animate-2: Pushing the Application Boundaries of Character Animation"
   (submitted 2026-08-06). HF model: `Wan-AI/Wan2.2-Animate-2-14B`. [FIRST-PARTY]
2. **Released variants.** Base (14B) and Distillation are actually released (weights + code,
   2026-08-07). **Lite is NOT released** — described in the paper/README as a real-time
   self-forcing-distillation method, but no weights/code are out; two open, unanswered upstream
   issues (#2, #4, opened 2026-08-09/08-11) ask when/if it will ship. [FIRST-PARTY]
3. **License.** Apache License 2.0 (GitHub README + HF model card). No commercial restriction
   found. [FIRST-PARTY]
4. **Official inference settings.** Base: 40 sampling steps with classifier-free guidance,
   demonstrated up to 720P (8xA800) / 480P (2xA800) in the README's own example flags. Distillation:
   `--step 10`, `--sample_guide_scale 1.0` (no CFG). [FIRST-PARTY, GPU-count/resolution pairing
   lightly paraphrased from README prose]
5. **Official Comfy workflows — the working hypothesis is confirmed.** Two distinct official
   supported-model pages exist:
   - Base-oriented: `wan_animate_2_int8_convrot.safetensors` (INT8 ConvRot) used with the LightX2V
     LoRA `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` for step-reduced sampling.
   - Native distilled: `wan_animate_2_distill_int8_convrot.safetensors`, a separate model file.
   Official tutorial: `docs.comfy.org/tutorials/video/wan/wan-animate-2`, template
   `video_wan_animate2`. **Both INT8 ConvRot files are quantized — neither is pristine bf16 upstream
   Base.** A `wan_animate_2_bf16.safetensors` full-precision file exists separately for users who
   want unmodified Base weights (and `wan_animate_2_distill_bf16.safetensors` for unmodified
   Distillation). So: the "official Comfy Base-oriented workflow" is an accelerated/modified Base,
   not pristine upstream Base. [FIRST-PARTY; some exact filenames via page summarization, corroborated
   across two independent fetches]
6. **Comfy version/nodes.** Docs specify current/nightly ComfyUI (announcement 2026-08-08). No
   third-party custom nodes required — implemented as core ComfyUI nodes (`WanAnimate2ToVideo`,
   `WanAnimate2Cache`, `WanAnimate2LoopSampler`). [FIRST-PARTY]
7. **Assets — sizes filled in 2026-09-26 (continued no-cost research after the subscription
   block).** Verified directly from the `Comfy-Org/Wan-Animate-2` Hugging Face repository (119 GB
   total):

   | File | Size | Used in this package's pre-registered runs? |
   | --- | ---: | --- |
   | `wan_animate_2_bf16.safetensors` (pristine Base) | 32.8 GB | No |
   | `wan_animate_2_distill_bf16.safetensors` (pristine Distilled) | 32.8 GB | No |
   | `wan_animate_2_int8_convrot.safetensors` | 16.7 GB | Yes — Base+LightX2V (runs 2, 4) |
   | `wan_animate_2_distill_int8_convrot.safetensors` | 16.7 GB | Yes — Distilled (runs 1, 3, 5) |
   | `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` (LoRA) | 738 MB | Yes — Base+LightX2V only |
   | `umt5_xxl_fp16.safetensors` | 11.4 GB | No |
   | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6.74 GB | Yes — both workflows |
   | `Wan2_1_VAE_bf16.safetensors` | 254 MB | Yes — both workflows |
   | `clip_vision_h.safetensors` | 1.26 GB | Yes — both workflows |

   The 32.8 GB pristine-bf16 figure independently **cross-validates** item 10's upstream bug report,
   which separately estimated "~32.8 GB expected" bf16 DiT memory from a different angle (a
   dtype-residency argument, not a file-size lookup) — two independent methods landing on the same
   number is corroborating, not coincidental. **Combined on-disk footprint for this package's actual
   pre-registered Distilled workflow is ~25.0 GB** (16.7 + 6.74 + 0.254 + 1.26), and **~25.7 GB for
   Base+LightX2V** (+0.738 GB LoRA) — both far exceed a 12 GB card's VRAM as a naive simultaneous
   sum, confirming that sequential/offloaded loading (not all components resident in VRAM at once)
   is **mandatory**, not optional, for any local attempt on the RTX 4070 Ti — carried into the Phase E
   budget below. [FIRST-PARTY, Hugging Face repository file listing]
8. **Frame/geometry conventions.** The official `WanAnimate2Cache` doc's own reference example uses
   480x832, 81 frames, bf16. Comfy Cloud's landing page cites "81 frames, 18 fps, 640x640, 4-step"
   as its credit-cost example. 720P/480P are the named supported tiers. An open, unresolved upstream
   issue (#1, opened 2026-08-09) reports driving-clip length effectively capped near 5 seconds in
   practice (81 frames at ~16 fps is ~5.06 s) — consistent with 81 frames being close to the
   practical duration ceiling, not an arbitrary example number. [FIRST-PARTY figures; COMMUNITY
   practical-ceiling complaint]
9. **`WanAnimate2Cache` — confirmed speed-for-memory tradeoff, hypothesis correct.** It caches the
   pose-branch per-block activations once so they are not recomputed every sampling step, roughly
   **halving generation time** at the cost of **extra memory** (~12.5 GB system RAM at
   480x832/81 frames/bf16, scaling with resolution/length/context-window count). It defaults to
   `device="cpu"` (RAM) because VRAM usually cannot hold cache plus model; int8/int4 cache-dtype
   options reduce but do not eliminate the cost; only the `static_standard` schedule reuses the
   cache correctly. This is unambiguously a speed-for-memory tradeoff, not a memory saver: the
   "default OFF for memory-constrained qualification" recommendation is well-supported by the
   documented mechanism, now with a concrete quantified cost (~12.5 GB extra RAM). [FIRST-PARTY]
10. **RAM/VRAM/consumer-GPU evidence.** No official 12-GB-class benchmark was found for Wan-Animate-2
    specifically. A materially relevant open first-party bug report exists: **upstream issue #5**
    (opened 2026-08-12, unresolved) — `set_default_dtype` is called *after* the transformer is
    built, so the DiT may end up resident in fp32 instead of bf16 on **single-GPU** setups (roughly
    65.6 GB vs. an expected ~32.8 GB); multi-GPU sharded setups mask the bug. **This is directly
    load-bearing for the RTX 4070 Ti 12 GB single-GPU target** (see Q2/Phase E) and is treated as an
    open risk, not a confirmed blocker, since it has not been independently reproduced here.
    General Wan2.2-family community guidance (not Animate-2-specific) recommends GGUF-quantized
    loaders and small resolutions for 8 GB cards and warns full fp16 will OOM a 12 GB card; no direct
    Wan-Animate-2 12 GB OOM report was found. [FIRST-PARTY bug report #5; COMMUNITY general Wan2.2
    guidance, not confirmed Animate-2-specific]
11. **Comfy Cloud compatibility.** A live "Run Wan Animate 2" template exists at
    `comfy.org/wan-animate-2/`; the cloud Templates panel is kept current with stable ComfyUI
    releases. Pricing: Standard/Creator/Pro/Team tiers at $20/$35/$100/$700/month (~20% less billed
    yearly), metered via GPU-time credits (4,200/7,400/21,100/147,700 respectively); a 5-second
    Wan2.2-class video costs roughly ~11 credits. **5 free GPU runs are offered with no card
    required.** Whether the cloud template runs the official workflow completely unmodified versus a
    Comfy-hosted variant was **not confirmed** by any reachable source. [FIRST-PARTY pricing/
    availability; UNKNOWN on unmodified-workflow claim]
12. **Driving-video ingestion — confirmed single-stage.** "The driving video goes straight into the
    transformer. No intermediate motion extractor sits between your source footage and the model"
    (official announcement), matching the paper's decoupled dual-branch attention / time-aligned
    positional encoding / sparse reference attention claims. This removes the v1 intermediate
    pose-extractor chain entirely. [FIRST-PARTY]
13. **Reference-bound locomotion / identity binding / ghosting — the single most important, and
    weakest-answered, question.** The paper claims improved motion fidelity and identity
    preservation, including cross-identity transfer across very different body shapes, attributed to
    removing the old pose-extractor chain — but this is the authors' own claim, not independent
    validation. A credible independent counter-report exists: **upstream issue #6** (opened
    2026-08-22, unresolved) reports character-consistency drift, with InsightFace similarity scores
    dropping to 40-50% in non-degenerate views. **No first-party or community source specifically
    addresses "ghosting"/duplicate-person artifacts during walking/locomotion** — no locomotion
    benchmark or gallery example was found either confirming or ruling this out. **Net: the exact
    PR-VID-181/183 failure mode (planted reference subject with motion carried by a separate
    figure) is neither confirmed nor ruled out anywhere in current upstream/community sources for
    Wan-Animate-2.** This is why Phase D's own controlled test — not further literature review — is
    the only way to answer Q1.
14. **Other current open upstream issues** (all unresolved as of 2026-09-26): #7 multi-camera
    animation control unclear (2026-09-21); #6 identity drift (see 13); #5 possible fp32/2x-memory
    bug (see 10); #4/#2 Lite release status (see 2); #1 practical duration ceiling (see 8); #3
    README correction request (2026-08-10).

### Base vs Distilled

Neither is assumed superior. The **official Comfy Base-oriented path** (INT8 ConvRot + LightX2V
LoRA) is an accelerated/modified Base, not pristine upstream Base — a separate unaccelerated
`wan_animate_2_bf16.safetensors` exists for anyone who wants the pristine checkpoint. The **official
Comfy native Distilled path** (`wan_animate_2_distill_int8_convrot`) is upstream's own distillation,
using lower-step/no-CFG-style inference per current upstream settings (`--step 10`,
`--sample_guide_scale 1.0`).

---

## Phase B — Frozen reference-capability experiment (pre-registered, not yet run)

**Experiment design (owner amendment, 2026-09-26):** the remote capability A/B is not
"gesture vs. locomotion." It isolates the two official Comfy Wan-Animate-2 execution variants using
the SAME frozen reference image and the SAME frozen locomotion driving video, named by workflow
identity (never "Case A/B" — that label already means gesture/locomotion in PR-VID-170/180/181 and
retarget-off/on in PR-VID-183):

- **Base+LightX2V:** official current Comfy Base-oriented Wan-Animate-2 workflow
  (`motion_transfer_wan_animate_2.json`) at its normal reference envelope/settings. Never described
  as pristine upstream Base — the LightX2V LoRA already step-distills it to 6-step LCM sampling (see
  "Official Base+LightX2V settings" below).
- **Distilled:** official current Comfy native Distilled Wan-Animate-2 workflow
  (`motion_transfer_wan_animate_2_distilled.json`) at its normal reference envelope/settings.

This determines whether the official Comfy reference stack can deliver reference-bound locomotion
at all, and whether Base+LightX2V vs. Distilled materially changes the result, before any local
RTX 4070 Ti compromise is introduced. Gesture evidence from PR-VID-181 Case A remains historical
context only; no primary cloud qualification run is spent on gesture unless the locomotion A/B
completes and a further run is separately justified.

**Frozen assets (both workflows, unchanged between them):**

- **Reference image:** `reports/vid110/inputs/source_fullbody.png`, SHA-256
  `362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb`, 480x832 RGB. StableNew-generated
  synthetic person (Wan2.2 TI2V-5B text-to-video, seed 110110 — see PR-VID-110), not a real photo, so
  it carries no third-party rights/privacy question. Reused unchanged since PR-VID-110 through
  PR-VID-183 (six prior packages). **Not pre-resized** — fed to each template's own load/resize path
  as-is; the effective generation geometry will be recorded from the actual run, not assumed.
- **Driving video — retrimmed 2026-09-26 (resolves the frame-count gap):** a **longer window of the
  same Mixkit #583 source file**, using PR-VID-181's exact fixed crop unchanged
  (`crop=377:676:140:20,scale=464:832:flags=lanczos` from `tools/qualification/vid181/driving_prep.py`,
  called directly, not reimplemented) — only the time window changed, no tracking/panning crop (that
  would erase the root translation being measured).

  | Field | Value |
  | --- | --- |
  | Source file (verified, unchanged since PR-VID-181) | `583-720.mp4`, SHA-256 `da49964c6d418ae7a7cc6b8972617d6e35bff588e656d55f67d645974b4cd346`, 1280x720/24fps/240 frames (10 s) |
  | Window | 2.30 s - 4.80 s (was 3.0-4.2 s) |
  | Frame count / fps / duration | **60 frames / 24 fps / 2.50 s** |
  | Crop | `x=140,y=20,377x676` (identical to PR-VID-181), scaled to 464x832 |
  | Retrimmed file SHA-256 | `d0f7abeaaa3bc0a37ceefca76c130afdfbb3bb3b81d30480c6fd07321bd1d72f` |
  | Encoding | H.264, `crf=12`, `preset=slow`, `yuv420p` (same as PR-VID-181) |

  **Window selection:** contact sheets at 0.25 s and then per-frame (1/24 s) granularity across the
  full 10 s source (under the exact fixed crop above) showed the subject enters the crop around
  t=2.24-2.28 s and exits abruptly around t=4.87-4.90 s (a fast sprint-away exit). The chosen
  2.30-4.80 s window sits with margin inside that fully-in-frame range on both ends; every one of the
  60 frames was visually spot-checked via a full contact sheet — the subject stays completely in
  frame throughout, transitioning from high-knee running to a full sprint stride with continuous
  left-to-right root translation.
  **The 81-frame official default was not reachable**: the subject is only continuously,
  fully in-frame for about 2.6 s under this exact crop (extending it further would need panning the
  crop, which the amendment explicitly forbids since it would erase the measured root translation).
  60 frames is documented here as the largest valid count, per the amendment's own fallback
  instruction, not the 81-frame target.
  **Frame-rate/sampling note:** direct inspection of the official blueprint's internal subgraph
  (`GetVideoComponents`, `TrimVideoLatent`, `ImageFromBatch` nodes) found no explicit fps-resampling/
  retiming node — the driving video is decoded and consumed at its own native rate with no
  configurable resample widget. The retrimmed clip is a direct 24fps crop of the original real-time
  footage (never sped up/slowed down), so it is supplied in real-time motion as required. Whether
  frames beyond the driving clip's own 60 are looped, padded, or simply absent relative to the
  template's 81-frame `length` target was **not determined from the static graph alone** — this is a
  real open question only the actual run will answer, which is exactly why using the largest valid
  real window was the responsible choice rather than guessing at padding/looping semantics with a
  much shorter clip. The 29-frame PR-VID-181 file remains historical evidence and is **not**
  uploaded.
  It shows one intended person, clear lateral locomotion/root-translation, a static camera, full body
  visible, no bystanders — the same underlying source PR-VID-181/183 already used, preserving direct
  historical comparability against the documented Animate-v1 failure
  (`ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY` / `BASIC_RETARGET_APPLIES;
  REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`).

**License (resolved by explicit owner risk-acceptance, not by a favorable license reading).** Direct
verification of Mixkit's actual terms (`mixkit.co/terms/`, `mixkit.co/llm-info/`, corroborated by an
independent third-party license guide) found the operative clause: *"rent, license, sublicense, sell,
resell or otherwise commercially exploit or make Mixkit or any Item available to any third party,"*
summarized elsewhere as *"cannot redistribute raw, unedited clip files... on any platform."* No
source found an explicit carve-out for third-party AI/ML use. The owner was given this exact finding
and explicitly directed proceeding anyway: **"Accept the risk explicitly... a two-run internal
qualification test, not redistribution or competing-service use, is low-risk enough to proceed
anyway"** (owner decision, 2026-09-26), reaffirmed when authorizing Comfy Cloud use for this specific
retrimmed clip from the same source file. Not a general finding that the license permits third-party
AI use, and does not extend beyond this qualification test.

No source/reference substitution has been made — same source file, longer window, same crop. The
Base+LightX2V / Distilled pair against this frozen reference/driving asset pair is the pre-registered
Phase D case (see "Run matrix" under Phase D below for the full 5-run schedule, seeds, and settings).

### Official Base+LightX2V settings (verified from the current shipped Comfy-Org blueprint JSON, internal node graph, not just outer widgets)

Source: `Comfy-Org/workflow_templates` repo, `blueprints/motion_transfer_wan_animate_2.json`,
downloaded and parsed directly — both the outer subgraph's exposed widgets and the internal
28-node subgraph definition (`WanAnimate2ToVideo`, `BasicScheduler`, `ModelSamplingSD3`,
`KSamplerSelect`, `SamplerCustom`, `WanAnimate2Cache`, `ResizeImageMaskNode` x2,
`ContextWindowsManual`, `GetVideoComponents`, `TrimVideoLatent`, etc. — 28 nodes total).

| Setting | Value |
| --- | --- |
| Checkpoint | `wan_animate_2_int8_convrot.safetensors` + LoRA `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` |
| Text encoder / CLIP vision / VAE | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` / `clip_vision_h.safetensors` / `Wan2_1_VAE_bf16.safetensors` |
| Outer exposed resolution / length | 482x854 (`resize_type.width`/`height_1`) / 81 frames |
| `ResizeImageMaskNode` (x2) actual resize targets | 481x854 and 482x854, mode `scale dimensions`/`center`/`area` |
| `WanAnimate2ToVideo` node's own raw widget defaults | `[832, 480, 81, 1, 0, 1, 0, 1, 1]` — width/height ordering not independently confirmed field-by-field; likely overridden by the linked outer resize control rather than used as-is (not conclusively verified without running ComfyUI itself) |
| Sampler / scheduler / shift | `lcm` / `simple` / 5 |
| Steps / cfg | **6** / 1 (`BasicScheduler=['simple',6,1]`, `SamplerCustom=[True,2,'randomize',1]` → cfg=1) |
| reference_image_strength / pose_strength / pose_start-end_percent | 1 / 1 / 0-1 (applied across the full clip) |
| enable_context_window / trim_duplicated_frame | False / False (gated by `PrimitiveBoolean=[False]` / `ComfySwitchNode=[False]`) |
| `WanAnimate2Cache` node | `['gpu','int8']` — present as a normal graph node with no separate enable/disable toggle found; this is the shipped default, not a documentation assumption |
| Default seed control | `control_after_generate='randomize'` — **must be overridden to `'fixed'` with the pre-registered seed** for runs 1-4 (see run matrix) |

**Correction to Phase A's framing:** despite the "Base-oriented" name, this shipped template does
**not** run pristine Base's own 40-step CFG sampling — the LightX2V LoRA already collapses it to
6-step LCM sampling with `cfg=1` (i.e., no classifier-free guidance). A test of pristine,
unaccelerated Base (`wan_animate_2_bf16.safetensors`, no LoRA, 40 real CFG steps) would require a
materially different, non-default workflow and is not what this shipped template runs. Per the
owner amendment, this arm is named **Base+LightX2V**, never "pristine Base."

**Also corrects Phase A item 9's cache assumption:** the shipped default here is `cache_device=gpu`,
`cache_dtype=int8`, not the CPU/off default that general Comfy documentation described as advisable
for memory-constrained setups; the `WanAnimate2Cache` node stores activations as lossy int8. Whether
the node can be reconfigured or bypassed by the operator was not determined from the JSON alone —
run 5's local-candidate configuration (Phase E) makes disabling it an explicit, documented graph
change rather than assuming it is already off.

### Official Distilled settings (verified from the current shipped Comfy-Org blueprint JSON)

Source: `blueprints/motion_transfer_wan_animate_2_distilled.json`, same repo, fetched and parsed
directly (also 28 internal nodes).

Identical to the Base+LightX2V table above except: **checkpoint** is
`wan_animate_2_distill_int8_convrot.safetensors` alone (no LoRA — it is upstream's own native
distillation, not an accelerated Base), and **steps = 10** (`BasicScheduler=['simple',10,1]`, vs. 6
for Base+LightX2V). Sampler (`lcm`), scheduler (`simple`), shift (5), cfg (1),
resolution/length (482x854/81), reference/pose strengths, context-window/trim/cache defaults are all
identical between the two templates.

**Material finding for the owner's stated purpose:** the two official templates' sampling recipes
are nearly identical (same sampler/scheduler/shift/cfg/geometry/cache), differing mainly in
checkpoint (LoRA-accelerated Base vs. native-distilled unet) and step count (6 vs. 10). Any output
difference between Base+LightX2V and Distilled would therefore mainly reflect the checkpoint/
step-count difference, not a fundamentally different sampling paradigm — useful context for
interpreting a Base-vs-Distilled delta once the runs exist.

**Terminology finding relevant to Phase F:** both official blueprints label the raw-driving-video
input socket `pose_video` (type `VIDEO`), even though Wan-Animate-2 takes it as a raw, unprocessed
driving video with no separate pose-extraction stage — confirmed directly from the input labels in
the downloaded blueprint JSON (`{"label": "pose_video", "name": "video", "type": "VIDEO"}`), not
inferred. Upstream/Comfy itself reuses the "pose_video" name for a raw driving video. See Phase F for
the owner's correction that raw RGB driving footage is not `pose_video` in StableNew's own semantic
sense, notwithstanding Comfy's own socket label.

---

## Phase C — Pre-registered scoring contract (frozen)

`tools/qualification/vid184/scoring_contract.py` freezes the Phase D/E evaluation plan **before**
any Animate-2 output exists, with `FROZEN_CONTRACT_SHA256` pinning the exact metric set/thresholds
(`tests/tools/test_vid184_scoring_contract.py`, 8 deterministic tests, no GPU/network, all passing).

| Metric | Gate | Threshold | Anchor |
| --- | --- | --- | --- |
| `motion_curve_correlation` | pass/fail | >= 0.30 | PR-VID-181 Case A (accepted pass) = 0.419; Case B (accepted fail) = -0.132; synthetic noise floor (PR-VID-180) = -0.089 to 0.005 |
| `root_translation_fraction` | pass/fail | >= 0.15 | PR-VID-181's own driving control moved 0.40 of frame width; the documented failure case produced ~0 displacement |
| `primary_subject_continuity` | pass/fail | >= 0.90 frame coverage | New metric; deliberately cannot alone detect a planted-but-present subject — must be read with `root_translation_fraction` |
| `ghost_actor_persistence` | pass/fail | <= 2 consecutive frames | PR-VID-181/180 documented a persistent second figure carrying the driven motion while the reference stayed planted |
| `identity_hist_mean`, `camera_drift_px`, `motion_area_fraction` | corroborating only | none | PR-VID-181 states these are corroboration, not sole truth, and that background hallucination contaminates optical flow |
| `human_visual_rubric` | manual, raw 1-5, not averaged | none (qualitative) | Same rubric/convention as PR-VID-181/183 |

`motion_curve_correlation`, `identity_hist_mean`, `camera_drift_px`, and `motion_area_fraction` are
**reused** from `tools/qualification/vid110/metrics.py` (`motion_curve`, `curve_correlation`,
`clip_metrics`) without modification. `primary_subject_continuity` and `ghost_actor_persistence`
are **new** and require a person detector; their thresholds were frozen before any scorer code
existed, so they could not be tuned to fit results that did not yet exist. No threshold was chosen
after viewing any Animate-2 output — none has been generated.

### Scorer implementation and control validation (owner amendment section 3.2, complete)

`tools/qualification/vid184/detect_runner.py` runs the same pinned `yolov10m.onnx` detector
PR-VID-181 already used (SHA-256 `89b526498a6d55f869a6ab52e3a2eb20ad45b3711c1f7de3dd9ca0b399dfd6d7`,
verified unchanged), executed **only** in the disposable CPU-only environment (same isolation split
as every prior PR-VID-1xx package: detector inference outside the StableNew `.venv`, consuming only
plain JSON in the production interpreter). `tools/qualification/vid184/tracking.py` is pure stdlib
(no numpy/cv2/onnxruntime import) — a greedy nearest-centroid single-track algorithm over the
per-frame person boxes, computing `primary_subject_continuity`, `ghost_actor_persistence`, and
`root_translation_fraction`. It has no identity/ReID model, so it cannot itself confirm the tracked
figure matches the *reference image's* identity — only that a single detection persists
continuously; this scope limit is recorded, not hidden. 14 deterministic synthetic-box tests
(`tests/tools/test_vid184_tracking.py`, `tests/tools/test_vid184_scoring_contract.py`) pass with no
GPU/network dependency.

Per the amendment's required gate, the scorer was run against real video before any upload:

| Case | Role | Frames | `primary_subject_continuity` | `ghost_actor_persistence` | `root_translation_fraction` | All 3 pass? |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Retrimmed driving clip (frozen, this package) | positive control | 60 | 1.000 (pass, >=0.90) | 1 (pass, <=2) | 0.827 (pass, >=0.15) | **yes** |
| PR-VID-181 Case B output (`ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY`) | negative control | 13 | 0.769 (**fail**) | 6 (**fail**) | 0.124 (**fail**) | no |
| PR-VID-183 Arm A output (`REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`) | negative control | 13 | 1.000 (pass) | 0 (pass) | 0.025 (**fail**) | no |
| PR-VID-183 Arm B output (same classification) | negative control | 13 | 1.000 (pass) | 2 (pass, boundary) | 0.079 (**fail**) | no |

The scorer separated the controls correctly on the first attempt — no iteration was needed. It also
recovered documented nuance rather than a blunt pass/fail: the PR-VID-181 case (a literal second
"ghost" figure carrying the motion) fails continuity and ghost-persistence in addition to root
translation, while the two PR-VID-183 arms (documented as a distorted/non-translating figure, not a
second figure) pass continuity and ghost-persistence but fail specifically on root translation —
matching each package's own prose findings. Full results, hashes, and the acceptance rule are
committed in `tools/qualification/vid184/control_validation.json`; the negative-control output files
themselves (located in a sibling checkout's `reports/vid181/` and `reports/vid183/` — not the
`StableNew-main` git-ignored `reports/` tree) and the detector JSON stay in the disposable qual
workspace, not committed, consistent with every prior PR-VID-1xx package.

The arm-blinding mechanism for the post-generation human verdict gate (amendment section 6) is
built and tested now, ahead of having real outputs: `tools/qualification/vid184/blind_seal.py`
copies each run's output to a randomly-ID'd filename and commits only the SHA-256 of the
label-to-ID mapping before Rob's review; a `verify` command later confirms the revealed mapping
still matches that committed hash, so a mapping cannot be silently altered between commit and
reveal. 4 deterministic tests (`tests/tools/test_vid184_blind_seal.py`) pass.

---

## Phase D — REMOTE_REFERENCE_GATE_BLOCKED_BY_SUBSCRIPTION (2026-09-26)

**Superseded claim, corrected in place rather than deleted (audit trail):** this document and
`STATUS.md` previously stated Comfy's current official mechanism is *"a Free Tier of 400
credits/month, no card required"* with a separate *"5 free runs on real GPUs"* claim, sourced from
Comfy's own marketing/support pages (`blog.comfy.org`, `comfy.org/pricing`). **That claim is now
superseded for this package by directly observed product behavior on the owner's real account: the
owner created the account, fully configured the pre-registered Distilled workflow, and the first
attempted run was blocked before queueing with the literal message *"A cloud subscription is
required to queue workflows"* — no free credits were available.** No source found afterward
distinguishes whether this is a Wan-Animate-2-specific gate (a "premium"/partner-node template
excluded from the general free tier) or the general free-tier claim simply not matching current
product behavior; that distinction was not resolved and is not load-bearing for this package either
way. **First-hand observation of the actual product on the actual account overrides the earlier
secondary marketing/support-page research** — this is not a case of picking one source over another
arbitrarily, it is live evidence superseding a documentation claim, which is the correct precedence.
Verified privacy facts (not use for AI training, private-by-default) are unaffected by this
correction and still stand. No files have been uploaded and no cloud spend has occurred.

**Classification: `REMOTE_REFERENCE_GATE_BLOCKED_BY_SUBSCRIPTION`.** This is an infrastructure/
access result, not a Wan-Animate-2 capability finding — it says nothing about whether the official
Comfy reference stack can or cannot deliver reference-bound locomotion (Q1 remains genuinely
unanswered, not "failed"). Per explicit owner instruction: **do not subscribe, purchase credits,
create another cloud account/provider, or upload/run anything further without separate owner
authorization.** This package is **not abandoned** — see "Phase G — decision tree" below for how it
continues, and "Reframed next physical recommendation" for what changes.

The 5-run matrix below **remains the pre-registration of record** (unchanged, still valid) for if
and when remote access is separately authorized in the future (subscription, or an alternate
rented-GPU provider, each its own future owner decision) — it is not deleted, just currently
unexecutable.

### Run matrix (pre-registered, amendment section 4; full detail in `tools/qualification/vid184/run_manifest.json`)

Two fixed seeds, derived deterministically from the frozen driving clip's own SHA-256 (first/next 14
hex chars as integers — reproducible, fixed before any generation, not chosen after seeing output):
**S1 = 58819112904309696**, **S2 = 46017787086728211**. Both official templates default their seed
control to `'randomize'` — **this must be changed to `'fixed'`** with the seed below before each run.

| # | Workflow | Frames | Cache | Seed | Purpose |
| --- | --- | --- | --- | --- | --- |
| 1 | Distilled | 60 (frozen driving-clip count) | shipped default (gpu/int8) | S1 | reference capability |
| 2 | Base+LightX2V | 60 | shipped default | S1 | reference capability |
| 3 | Distilled | 60 | shipped default | S2 | seed replication |
| 4 | Base+LightX2V | 60 | shipped default | S2 | seed replication |
| 5 | Distilled | 13 (local-candidate; paper-only hypothesis, see Phase E) | **OFF** (remove/bypass the `WanAnimate2Cache` node — documented graph change) | S1 | local-candidate configuration, run remotely; separates configuration effects from future hardware effects; not a reference arm, cannot establish Q1 alone |

Runs 1-4 use shipped template settings exactly (sampler `lcm`, scheduler `simple`, shift 5, cfg 1,
reference/pose strengths 1, pose applied across the full clip), except the pre-registered
reference/driving inputs, seeds, and the frame-count deviation (60 vs. the 81-frame default,
documented above as the largest valid real window). **If credits run out, stop in table order and
report what completed — no paid top-up.**

### Pre-generation blocker resolution (addendum, 2026-09-26, before any run)

Opening the live template surfaced four real gaps the static blueprint JSON alone did not answer.
All four are resolved below from **ComfyUI's actual node source**
(`comfy_extras/nodes_wan.py`, `Comfy-Org/ComfyUI`, fetched directly), not inference. Full detail,
including every per-run widget value, is in `tools/qualification/vid184/run_manifest.json`.

**1-2. Prompt / pose_prompt text (identical across all 5 runs, official upstream format).** The
shipped Comfy Cloud template ships demo placeholder text (a pink-hair character / street-dance
description) — this is a hosted-template onboarding default, not present in the raw downloaded
blueprint JSON (whose own `widgets_values` show empty strings there). It must be fully cleared, not
left concatenated with the text below. The official upstream convention (`Wan-Video/Wan-Animate-2`
README, verified with a real example) is two labeled sections combined into one string —
*"Character appearance description: ... Background description: ..."* — objective/factual, no
action or emotion. `pose_prompt` is a separate field (feeds `positive_pose`, per the node's own
tooltip: "Prompt for the pose-video branch, describing the motion rather than the character"),
written the same objective way but describing only the driving clip's motion.

- **`prompt`:** "Character appearance description: A young adult woman with dark hair pulled back,
  standing upright and facing forward with her arms relaxed at her sides. She wears a fitted dark
  navy short-sleeve athletic top with a V-neck and dark navy full-length leggings, with white
  athletic sneakers featuring teal accent trim. Background description: An abstract, softly blurred
  backdrop of pale white, lavender, and pale green geometric and glass-like shapes, evenly and
  brightly lit, with no other objects or decoration." (written from directly viewing the frozen
  reference image, not assumed)
- **`pose_prompt`:** "A person performs a high-knee running drill that transitions into a full
  sprinting stride, moving laterally from left to right across a static frame with continuous
  forward locomotion and alternating arm-leg swing." (written from the same contact-sheet visual
  inspection used to select the retrim window)

**3. `length` when it exceeds/undershoots the driving clip's real frame count — confirmed from
`WanAnimate2ToVideo.execute()`.** If the driving video has **more** frames than `length`, it is
truncated: `pose_video[video_frame_offset:][:length]` — no error. If it has **fewer**, the tail is
padded by **holding the last frame**: `torch.cat((pose_video,) + (pose_video[-1:],) * (length -
pose_video.shape[0]), dim=0)` — a frozen repeat, not new motion; still no error. The UI's `step=4`
on the `length` widget is a spinner-increment nicety, not a validated constraint in `execute()` —
any positive integer is legal. **Exact legal length per run:** runs 1-4 use **length=60** (not the
81 default — deliberately, so the padded/frozen tail that 81 would produce doesn't dilute
`root_translation_fraction`); run 5 uses **length=13**, which truncates the *same* 60-frame driving
file to its first 13 frames via this same mechanism — no separate short driving asset is needed.

**4. Cache OFF for run 5 — confirmed from `WanAnimate2Cache.define_schema()`: the exposed widgets
cannot do it.** `device` options are exactly `['cpu','gpu']` (no off/none); `dtype` options are
exactly `['default','int8','int4']`. The node unconditionally attaches a `PoseBranchCache` to the
model whenever it sits in the graph — no combo value disables it. True cache-OFF requires bypassing
the node inside the subgraph:
1. Open (double-click, or right-click → Open Subgraph/Enter) the "Motion Transfer (Wan Animate 2)"
   subgraph for the Distilled workflow.
2. Inside it, find the node named `WanAnimate2Cache` (single MODEL in, single MODEL out, between the
   model/LoRA chain and the sampler).
3. Select only that node.
4. Right-click → "Bypass" (or select it and press Ctrl+B) — it should render muted/dashed.
5. Confirm the MODEL wire now passes straight through it (ComfyUI auto-routes a bypassed
   single-in/single-out node's matching-type wire).
6. Exit back to the top-level graph.
7. Leave the outer `cache_device`/`cache_dtype` widgets at their shipped defaults — once bypassed,
   the node that would read them never executes, so their values are inert.

**5. Second (bypassed) Motion Transfer subgraph:** leave it bypassed for all 5 runs — not part of
this matrix; do not enable, connect, or run it.

**6. Which saved video is needed:** **both**. The plain generated clip is required for the
detector-based scorer — the side-by-side comparison doubles the frame width and puts the driving
clip's own subject in the same frame, which would corrupt the person-detector's box coordinates and
could register a false "ghost" detection. The side-by-side is for Rob's own visual review at the
human verdict gate only; the scorer never reads it. Ten files total (5 runs × 2 videos), named
`run{index}_{workflow}_{seed-label}_generated.mp4` / `..._sidebyside.mp4`.

**7. Post-return validation (added to the checklist):** before scoring, check each returned file's
embedded workflow metadata (if present) and Rob's exported workflow JSON against
`run_manifest.json` — confirm the actual checkpoint, seed, length, and cache-bypass state match what
was pre-registered before treating any output as valid evidence. A mismatch is reported, not
silently scored.

### Human verdict gate (amendment section 6) — remains valid pre-registration for if/when remote runs occur

Unchanged and still binding whenever the 5-run matrix eventually executes (remote or as a future
comparison baseline): Rob reviews all outputs **before** seeing any metric score. Best-effort
blinding: `tools/qualification/vid184/blind_seal.py` relabels each output with a random sealed ID
and this package commits only the hash of that mapping before hand-off — the real mapping is not
committed until after Rob's review is recorded, so it is provably the same mapping before and after.
Rob then scores the pre-registered human-visual-rubric (Phase C) per clip and gives a **PASS /
PARTIAL / FAIL** verdict for reference-bound locomotion. That verdict is the capability
classification; metrics are corroboration, and any disagreement between them is recorded explicitly
rather than silently resolved either way. **PR #9's merge authorization remains suspended until a
verdict is recorded and the classification is final** — currently blocked on `Q1` being unanswered
at all (see below), not on the review mechanics.

### Reframed next physical recommendation (2026-09-26, following the subscription block)

With the remote reference gate blocked by access rather than capability, and no automatic
continuation to paid access authorized, the pragmatic next evidence-gathering step — **if the
owner separately authorizes it** — is **one bounded local Wan-Animate-2 Distilled run on the RTX
4070 Ti 12 GB / 32 GB machine, cache OFF, at the smallest credible locomotion-preserving envelope**
(paper-only leading hypothesis: 13 frames / 480x832, per Phase E below — unverified for
Wan-Animate-2's architecture/quant, not yet run). This is **not authorized by this update** — it
requires the same explicit GPU-workload authorization every prior local qualification package in
this line has required, and none has been given here.

**The interpretive limit must travel with this recommendation, not be lost:** because there is no
remote reference baseline, a local failure at this envelope would be **genuinely ambiguous** — it
could mean Wan-Animate-2 cannot do reference-bound locomotion at all, or it could mean this
specific constrained local envelope (small resolution/frame-count, INT8 quant, cache OFF, a 12 GB
card) is simply insufficient while the model is capable at its full official settings. Neither this
package nor any future one may quietly resolve that ambiguity in either direction without new
evidence.

- **If the local run later succeeds** (clean reference-bound locomotion at this envelope): that is
  sufficient positive evidence on its own — **a paid remote baseline becomes unnecessary**, since a
  local pass at a harder (more constrained) envelope implies capability at the easier official
  settings.
- **If the local run later fails or is ambiguous:** paid Comfy Cloud access, an alternate rented-GPU
  provider, or a pristine-upstream adjudication each become **a separate ROI decision for the owner**
  — ambiguous local evidence does not by itself authorize automatically continuing to paid access;
  that authorization must be sought explicitly, the same way this package has sought it at every
  other spend/access boundary.

No GPU/CUDA/pagefile/driver/Comfy-configuration change is authorized in PR-VID-184 regardless of
this reframing.

Q1 (reference-bound locomotion capability) cannot be answered without an actual controlled test —
remote (currently blocked) or local (not yet authorized). Given Phase A item 13's finding that no
upstream/community source addresses the ghosting/locomotion question either way, there is no
literature substitute for running one.

---

## Phase E — Target-hardware feasibility: preliminary paper-only budget

No physical local run has occurred and none is authorized in PR-VID-184. This remains paper-only
synthesis of Phase A/B facts already gathered. Originally scoped to pre-register run 5's remote
"minimal documented graph change" and local-candidate window; now doubles as the budget behind the
reframed next physical recommendation above, since the remote gate is currently blocked.

**Cache modes, budgeted separately (amendment requirement):**
- **Cache OFF (local default unless the budget below proves headroom):** removes the
  `WanAnimate2Cache` node's ~12.5 GB additional cost entirely (Phase A item 9, quantified from
  Comfy's own docs at 480x832/81f/bf16 — our candidate window is smaller, so the real cost would be
  less, but no smaller-window figure was published). Costs sampling *time* (no activation reuse),
  not memory.
- **Cache GPU mode (the shipped default):** stores int8 activations in **VRAM** — direct competition
  with the 12 GB budget already carrying the 14B UNET/LoRA/text-encoder/VAE/CLIP-vision stack; not
  recommended for a first local attempt.
- **Cache CPU mode (an alternative `device` value the node exposes, not the shipped default for
  either official template):** moves the ~12.5 GB cost to **host RAM** instead of VRAM — direct
  competition with the 32 GB RAM budget, which StableNew's own accepted Wan2.2 5B telemetry already
  shows can run with near-zero headroom under load (PR-VID-150/160C history). Not evaluated further
  here; recorded as the theoretical middle option between OFF and GPU.

**Local default recommendation stays cache OFF** unless a future budget pass, informed by real
telemetry from an actual run (remote or local), proves headroom for GPU or CPU mode. This is now
the primary reason cache OFF is not merely a memory-savings default but a **precondition**: Phase A
item 7's real asset sizes put the Distilled workflow's combined on-disk footprint at ~25.0 GB
(checkpoint + text encoder + VAE + CLIP vision) against a 12 GB card — cache's own ~12.5 GB
additional cost (scaled down for our smaller candidate window, exact figure unpublished) would only
worsen an already offload-dependent budget.

**Material new risk (Phase A item 10, carried forward):** an open, unreproduced upstream bug report
(issue #5) describes the DiT possibly loading in fp32 instead of bf16 on single-GPU setups
(~65.6 GB vs. an expected ~32.8 GB) due to `set_default_dtype` being called after the transformer is
built. This is directly adverse to any 12 GB/32 GB local attempt and must be checked (reproduced,
avoided, or confirmed patched) before a real physical budget is finalized — not yet done.

**Leading local-candidate window (paper-only hypothesis, run 5):** 13 frames / 480x832 — the
proven-safe Wan2.2-Animate-14B local envelope already used successfully on this exact RTX 4070 Ti
across PR-VID-160C/170/175/180/181 (Q3_K_M quant, not the INT8 ConvRot quant Wan-Animate-2 ships).
This is carried over as a starting hypothesis only — it has **not** been independently verified for
Wan-Animate-2's different architecture/quantization, and is explicitly labeled as such in
`run_manifest.json`.

**Comfy version gap (amendment section 7, dedicated research pass, complete):** StableNew's existing
managed Comfy Desktop install is pinned at **ComfyUI 0.3.65** (`comfyui_version.py`; also
`src/video/workflow_catalog.py:509`), **PyTorch 2.8.0+cu129**, **Python 3.10.6**, at
`E:\Users\rober\ComfyUI\.venv-explicit` — externally-managed, not a StableNew pip dependency.
Wan-Animate-2's native `WanAnimate2ToVideo`/`WanAnimate2Cache` nodes shipped in **ComfyUI v0.31.0**
(2026-08-07/08, `docs.comfy.org/changelog`) — a real gap of roughly 10 months and ~30 GitHub
releases, not a patch bump. No first-party evidence of a forced PyTorch/CUDA bump (ComfyUI's own
`requirements.txt` has never pinned an exact torch version across `0.3.65`/`0.31.0`/current
`0.37.0`), so a version-only upgrade is plausible but unconfirmed without attempting it.
**A separate, fully isolated ComfyUI install (own directory, own venv, own port) is standard,
uncomplicated architecture and does not require touching the existing managed install's environment,
node set, or version pin at all** — the only shared resource is the physical GPU and its one
kernel-mode driver (userspace CUDA ships bundled per-install inside each install's own torch wheel,
so two installs can run different CUDA userspace versions concurrently without conflict). This means
a second isolated install introduces **no new software-version variable** into DIAG-GPU-130, though
running any GPU workload on it is still GPU activity of the kind DIAG-GPU-130's current "XMP-OFF
isolation in progress / observation only" state asks not to combine with deliberate stress-testing —
a scheduling/timing consideration for the owner, not an architectural blocker. **Recommendation for
the eventual local physical probe: an isolated install, not an upgrade of the existing managed
Comfy.**

**CUDA Sysmem Fallback Policy:** not changed and not researched further in this pass beyond what
prior packages already recorded; still explicitly out of scope for any setting mutation in
PR-VID-184.

---

## Phase F — Backend-neutral contract mapping (complete; read-only, no production change)

Inspected `src/video/video_backend_types.py` and `src/video/video_workflow_intent.py`.

- `src/video/video_backend_types.py` defines `KNOWN_VIDEO_CONTROLS` including
  `CONTROL_CONTROL_VIDEO` ("control_video") and `CONTROL_POSE_VIDEO` ("pose_video") as backend-neutral
  semantic input forms on `VideoExecutionRequest`. Confirmed unchanged by this package.
- `src/video/video_workflow_intent.py` currently contains **no reference** to `control_video` or
  `pose_video` (confirmed via search) — the Video Workflow producer does not yet emit either
  control, matching this package's starting fact.
- **Owner correction (amendment section 7): raw RGB driving footage is not `pose_video`.** A raw
  Wan-Animate-2 driving video is a single continuous motion source consumed directly by the
  transformer (Phase A item 12), not a pre-extracted pose representation — StableNew's existing
  `pose_video` semantic was defined for the v1 pipeline's *rendered pose skeleton* (see
  `tools/qualification/vid181/`'s `src_pose.mp4` artifacts), a materially different thing even
  though Comfy's own official blueprint JSON happens to label its raw-video input socket
  `"pose_video"` too (verified directly from the downloaded template — see Phase B). Reusing
  StableNew's `pose_video` control for a raw driving clip would conflate two different concepts that
  merely share a name upstream. `control_video` is also not a clean fit (undifferentiated video
  conditioning generally, not defined with Wan-Animate-2's single-stage architecture in mind). A
  future, distinct neutral concept such as `motion_source_video` is more honest to what Wan-Animate-2
  actually consumes, but **no contract change is made in this package**: PR-VID-184 does not add a
  new video task or control merely to reserve one, and no Animate-2 integration is authorized yet
  regardless.
- **Durable identity for the driving input (amendment section 7):** consistent with native-SVD
  source provenance (where paths are convenience references, not durable identity), any future
  Animate-2 contract must key the driving input's identity on its **content SHA-256**
  (`d0f7abeaaa3bc0a37ceefca76c130afdfbb3bb3b81d30480c6fd07321bd1d72f` for this package's frozen
  clip), not a filesystem path. Replay semantics must resolve the driving input the same way native
  SVD resolves source-image provenance today. License provenance (Mixkit #583, item page URL, the
  ambiguous-terms finding, and the owner's explicit risk-acceptance) must travel with that identity
  wherever it is recorded, not just in this document. No contract change implementing this is made
  in this package; it is a requirement for whichever future package adds the driving-input control.
- `VideoExecutionRequest.workflow_inputs` (a `dict[str, Any]`) and `backend_options` (opaque,
  adapter-private) already exist and could carry a resolved driving-video path without any schema
  change, the same way other backend-specific inputs are threaded today — this was confirmed by
  reading the dataclass, not by adding code.
- Architecture requirement preserved: StableNew semantic intent must never expose Comfy node names
  (`WanAnimate2ToVideo`, `WanAnimate2Cache`), backend socket names, or model filenames; any future
  adapter would translate a neutral motion/control-source semantic into Comfy-specific inputs
  privately, exactly as the existing native-SVD and Wan2.2 v1 adapters already do.
- **Conclusion for Q3 (pending Q1/Q2):** the existing
  `Intent -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr ->
  VideoExecutionResolver -> backend_id=comfy -> versioned experimental workflow` path can carry a
  future Animate-2 adapter without adding a second queue, runner, process manager, lifecycle
  authority, or model-specific controller. The smallest future contract change, if capability and
  feasibility are both established, is likely a new neutral control (tentatively
  `motion_source_video`) rather than overloading `pose_video`; this is a recommendation for a future
  package, not a decision made or contract change applied here.

---

## Phase G — Decision tree (current node: gate blocked by access)

The original decision tree framed five outcomes keyed to a remote reference-capability result that
has not been obtainable. Recorded here in full for the first time (previously only referenced by
name), plus the new branch this package's actual path took.

- **Current node — remote gate blocked by access, not capability (this package, 2026-09-26):**
  neither a pass nor a fail; classified `REMOTE_REFERENCE_GATE_BLOCKED_BY_SUBSCRIPTION`. Per the
  reframed recommendation above, the next step *if separately authorized* is one bounded local
  Distilled run (cache OFF, smallest credible envelope) rather than waiting indefinitely on
  currently-inaccessible paid remote access. This is not a substitute for Outcomes 1-5 below — it is
  the path taken because none of them could be reached.
- **Outcome 1 — remote official Comfy reference fails** (both workflows fail stable reference-bound
  locomotion, if/when actually run): classify the Comfy reference path NO-GO/PARTIAL precisely; do
  not proceed to local hardware squeezing on that basis alone; do not claim the whole open-model
  ecosystem is incapable; recommend parking reference-bound locomotion for this StableNew release
  unless the owner explicitly authorizes a pristine-upstream/rented-GPU adjudication; retain
  gesture/local-motion options separately.
- **Outcome 2 — remote passes, local resource outlook is poor:** reframe the next owner decision as
  ROI among 64 GB system RAM, a higher-VRAM GPU, remote/cloud execution, or deferring the capability.
  64 GB RAM should be listed as available only after DIAG-GPU-130 concludes — memory is the variable
  currently under isolation. Do not launch an open-ended optimization campaign.
- **Outcome 3 — remote passes and local execution is plausible:** recommend one bounded physical
  qualification package — Distilled first, cache OFF, smallest credible legal temporal window
  preserving locomotion evidence, 480-class geometry, exactly one physical attempt initially,
  telemetry and existing commit-aware safety handling, no silent sysmem-policy change. (This is the
  same shape the current-node recommendation above borrows, decoupled from requiring a prior remote
  pass, since remote access is currently blocked rather than merely unattempted.)
- **Outcome 4 — local later passes but quality regresses versus remote:** permit at most one bounded
  adjudication of a clearly identified resource/quality compromise; do not begin iterative tuning.
- **Outcome 5 — capability and local feasibility both pass:** the next package may implement an
  EXPERIMENTAL StableNew vertical slice through `video_execution -> VideoExecutionResolver ->
  backend_id=comfy -> versioned workflow`, with explicit per-job opt-in; native SVD remains
  production/default until separately promoted.

---

## Package outcome — Q1-Q4

- **Q1 (reference capability):** **NOT YET ANSWERED — remote gate blocked by access, not
  capability.** `REMOTE_REFERENCE_GATE_BLOCKED_BY_SUBSCRIPTION` (Phase D). No current
  upstream/community source resolves it either way (Phase A item 13) — no literature substitute
  exists. The pre-registered 5-run matrix and human verdict gate remain valid for whenever remote
  access is separately authorized; the reframed next step is one bounded local run, itself not yet
  authorized.
- **Q2 (target-hardware feasibility):** **NOT YET ANSWERED.** A preliminary paper-only budget is
  complete (Phase E): cache-mode tradeoffs quantified, a material new risk (upstream issue #5,
  possible fp32 2x-memory bug on single-GPU setups) is on record, a leading local-candidate window is
  hypothesized (13f/480x832, cache OFF — unverified), and the Comfy version-gap research recommends
  an isolated install for the eventual physical probe. This budget is now also the basis for the
  reframed next-step recommendation, not gated on a remote pass it cannot currently obtain.
- **Q3 (backend-neutral integration fit):** **Answered, conditionally.** Yes — the existing
  backend-neutral contract can carry a future Animate-2 adapter without adding a second queue,
  runner, lifecycle authority, or model-specific controller (Phase F), provided a future control
  keys driving-input identity on content SHA-256, not a path, and does not conflate Comfy's
  `pose_video` socket label with StableNew's own `pose_video` semantic. No production change was
  made or is authorized.
- **Q4 (product decision):** **Not reached.** The decision tree (Phase G) currently sits at the
  "gate blocked by access" node, not any of Outcomes 1-5 — those require an actual remote or local
  run this package has not been authorized to execute.

## Validation

- `tools/qualification/vid184/` (`scoring_contract.py`, `detect_runner.py`, `tracking.py`,
  `blind_seal.py`) and `tests/tools/test_vid184_*.py`: `ruff check` clean, `ruff format --check`
  clean, `python -m pytest tests/tools/test_vid184_scoring_contract.py
  tests/tools/test_vid184_tracking.py tests/tools/test_vid184_blind_seal.py -q`: **18 passed**, no
  GPU/network dependency for any committed test (detector inference itself requires the disposable
  CPU-only environment and real video files, exercised for this report's control-validation pass but
  not part of the committed CI-run test suite).
- `git diff --check`: clean.
- No `src/` production file was modified; `src/video/video_backend_types.py` and
  `src/video/video_workflow_intent.py` were read-only inspected.
- No model, Comfy config, pagefile, driver, or GPU setting was changed. No workflow was registered.
  The owner created the Comfy Cloud account; this package uploaded nothing and incurred no spend.
- **Security Review:** not triggered. `vid184` tooling built in this package performs no network
  access and downloads no remote content; `detect_runner.py` reads a local video file and a local
  pinned ONNX model and writes local JSON; `blind_seal.py` copies local files and writes local JSON.
  Per the amendment's own trigger condition, this stays unreviewed until/unless that changes.

## Docs / Git

New: this report, `tools/qualification/vid184/scoring_contract.py`,
`tools/qualification/vid184/detect_runner.py`, `tools/qualification/vid184/tracking.py`,
`tools/qualification/vid184/blind_seal.py`, `tools/qualification/vid184/control_validation.json`,
`tools/qualification/vid184/run_manifest.json`, `tests/tools/test_vid184_scoring_contract.py`,
`tests/tools/test_vid184_tracking.py`, `tests/tools/test_vid184_blind_seal.py`, the `STATUS.md`
entry, and the `docs/CODEX_MAP.md` row for PR-VID-184. Not committed: the retrimmed driving clip,
the frozen reference image copy, detector JSON, and the negative-control output videos used for
control validation — all stay in disposable local workspaces
(`C:\Users\rob\qual\vid184\`, plus the negative controls read from a sibling checkout's
`reports/vid181/`/`reports/vid183/`), consistent with every prior PR-VID-1xx package; their content
hashes are committed in `control_validation.json`/`run_manifest.json` instead.

## What is explicitly NOT authorized next

- **Subscribing to Comfy Cloud, purchasing credits, or creating another cloud account/provider** —
  explicit owner instruction after the subscription block; any of these requires a new, separate
  owner authorization naming the action.
- Any local physical Animate-2 GPU workload (Phase E execution, including the reframed
  recommendation's bounded local run) — paper-only budget/recommendation only in this package; not
  authorized to execute.
- Any production `src/` change, workflow registration, GUI/controller change, new backend, or model
  promotion.
- Any Comfy config, pagefile, driver, or GPU-setting mutation (including the CUDA Sysmem Fallback
  Policy research question, which remains research-only in this package).
- Any further upload or run against the existing Comfy Cloud account (it cannot queue without a
  subscription regardless).
- Merging PR #9 before the human verdict gate is recorded and final — currently blocked on `Q1`
  being unanswered at all, not just on review mechanics.
- Beginning the local physical Animate-2 qualification or an experimental production vertical slice
  in this same package, even after Q1-Q4 are answered — those remain separate, separately authorized
  future packages per the decision tree (Phase G).

## Hand-off: awaiting owner decision (remote gate blocked)

Everything above this line is pushed to `feature/pr-vid-184-wan-animate2-feasibility` / PR #9 as the
pre-registration of record — it remains valid for whenever remote access is separately authorized.
**No execution is pending hand-off right now**: the Comfy Cloud account cannot queue workflows
without a subscription, and this package does not subscribe, pay, or open another account/provider
on its own. The next action is an owner decision, not a checklist to run:

- Authorize a Comfy Cloud subscription or an alternate paid/rented-GPU provider (a new, separate
  spend decision) and this package resumes the 5-run matrix hand-off below unchanged; or
- Authorize the reframed bounded local run (RTX 4070 Ti, Distilled workflow, cache OFF, ~13f/480x832
  leading candidate — Phase E/G) as the next evidence-gathering step instead; or
- Decide neither is warranted right now and leave PR-VID-184 open/paused with this evidence as the
  record.

If/when remote access is authorized, the original hand-off checklist still applies (kept below for
that future point):

1. On the Comfy Cloud account, open the **Wan Animate 2** template (both the Base-oriented and
   Distilled workflow variants are available from the same template page).
2. Upload the frozen reference image (`reports/vid110/inputs/source_fullbody.png` in this repo,
   SHA-256 `362c86cc...`) and the frozen driving clip
   (`C:\Users\rob\qual\vid184\src\B_locomotion_driving_60f.mp4`, SHA-256 `d0f7abea...`) — do not
   pre-resize either.
3. Clear the demo placeholder text and enter the pre-registered `prompt`/`pose_prompt` text from
   "Pre-generation blocker resolution" above, identically for all 5 runs.
4. For each of the 5 rows in the run matrix above (full machine-readable detail in
   `tools/qualification/vid184/run_manifest.json`): select the named workflow, set `length` (60 for
   runs 1-4, 13 for run 5), set the seed control to fixed with the given seed, leave every other
   setting at the shipped default, and — **only for run 5** — bypass the `WanAnimate2Cache` node
   inside the subgraph per the 7-step procedure above. Leave the second (already-bypassed) Motion
   Transfer subgraph untouched. Run it and save **both** the generated clip and the side-by-side
   comparison.
5. Stop in table order if credits run out; no paid top-up.
6. Send the output files (or however many completed) back for scoring and the blind-seal/human
   review steps in Phase D.

No further action from this session until the owner decides which path (remote access
authorization, local-run authorization, or pause) to take.
