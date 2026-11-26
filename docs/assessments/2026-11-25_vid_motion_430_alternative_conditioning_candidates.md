# StableNew Focused Assessment — PR-VID-MOTION-430 Workstream I: Alternative Motion-Conditioning Candidates — 2026-11-25

Framework: v1.2. Assessment class: Focused (technology research). Execution class: research only, no integration.
Status: draft for owner review. Completeness: PARTIAL by design. No generation, weight download, install or GPU probe was
performed, so every resource and quality statement below is either a vendor claim, an inference, or marked unknown.

This report is a decision aid. It does not supersede `AGENTS.md`, `STATUS.md` or `docs/Subsystems/Video/CONTROLLED_MOTION_ROADMAP.md`,
changes no code, catalog entry, weight or setting, and authorizes no physical run, download or promotion. Every
recommendation is **conditional on Phase 4 physical evidence that does not yet exist**.

Evidence notation: **V** verified this session (local source/file read, or a first-party page or file listing fetched on
2026-11-25); **C** vendor or author claim (not tested); **I** my inference; **U** unknown or untested.

## 1. Source lock and method

- Repo worktree `C:/Users/rob/qual/StableNew-vid-motion-430`, branch `feature/pr-vid-motion-430-conditioning-engine-eval`, HEAD
  `7885a184af66d44e57b84de7322d442aeaae4762`. Only this file was written.
- Pinned runtime (V): `config/managed_comfy_runtime.json` pins ComfyUI v0.38.0 at `6b747c0428c343e1417219641db93a4fb7cb69ae`,
  Python 3.13, torch 2.14.0+cu130, custom-node policy `none`. I read the installed source at
  `%LOCALAPPDATA%/StableNew/ManagedComfy/v0.38.0-py313/source` (git HEAD verified equal to the pin) and the installed
  `comfyui-workflow-templates` 0.11.70 package (templates JSON 0.1.96) with Grep and a read-only JSON parse of local template
  files. No ComfyUI code was imported or run.
- Web evidence: Hugging Face file listings and model cards (read through the HF tools), GitHub READMEs, arXiv pages, docs.comfy.org.
  Several pages were read through a summarizing fetch tool; figures taken that way are flagged "as summarized" and must be
  re-read at the source when a Phase 4 package pins them. Repository revisions of the HF repos were **not** captured here: the
  listings are "main as of 2026-11-25". A Phase 4 package must pin immutable revisions and SHA-256 before any download.
- Repo background read: roadmap section Phase 4, PR-VID-MOTION-212, -FUN-352, -MOTION-354, `docs/runbooks/video_eval_kit.md` sections
  9-10, `src/video/workflow_catalog_fun_control.py` and `workflow_catalog_wan_animate2.py`, the P4-2 assessment (format reference).

## 2. Executive summary

| # | Candidate | What it changes versus today | Pinned-Comfy support | New weights (approx.) | Recommendation (conditional) |
|---|---|---|---|---|---|
| 1 | **Fun Control with a pose-map or depth-map control video** (Wan2.2 Fun Control 5B first; A14B only as escalation) | Replaces the RGB/Canny driver with an identity-neutral pose or depth rendering; same engine family and graph shape as the registered Fun Control trial | Core node `Wan22FunControlToVideo` (V); official template exists for A14B (V); pose and depth extractors exist in core (V) | 5B: none new (already pinned). Pose extractor ~2.0 GB. A14B: 2 x 14.3 GB fp8 | **PURSUE first**: cheapest, tests the representation hypothesis directly |
| 2 | **SCAIL-2** (Wan2.1-14B-based, reference + driver + identity masks; optional 3D-pose driver) | A purpose-built character-animation engine with explicit subject/mask binding and an identity-neutral pose-driven mode | Core nodes `WanSCAILToVideo`, `SCAIL2ColoredMask`, `SAM3DBody_*` (V); official templates exist (V) | ~16.7 GB int8 + 1.2 GB LoRA + ~1.7 GB SAM3.1 + ~2-2.8 GB SAM3D Body | **PURSUE, gated by a Q0/Q1 resource check**: the only candidate aimed at attachment, but heaviest and unproven on 12 GB |
| 3 | **Wan VACE-style control** (Wan2.2-VACE-Fun-A14B, or Wan2.1-VACE) | Control video + reference image + mask in one model | Core node `WanVaceToVideo` (V); official templates are depth/Canny and reference only (V) | A14B: 2 x 17.3 GB fp8; Wan2.1-VACE-1.3B small | **DEFER**: overlaps candidate 1, no official pose template, single reference only |

Material findings that change the framing (all V unless marked):

1. **The pinned ComfyUI v0.38.0 already contains** SCAIL/SCAIL-2 model support and nodes, SAM3 segmentation, SAM3D-Body 3D body
   estimation with a `scail` capsule renderer, SDPose whole-body keypoints with a keypoint-drawing node, Depth Anything 3, and
   `WanVaceToVideo`/`Wan22FunControlToVideo`/`WanTrackToVideo`. None of the three candidates needs a custom node, so the
   `custom_nodes: none` policy and `--disable-all-custom-nodes` launch used by `tools/qualification/fun354` are unaffected (V).
2. The Comfy docs page for Fun Control says pose and depth need custom preprocessors (`comfyui_controlnet_aux`). That is stale
   for this pin: core now has `SDPoseKeypointExtractor`/`SDPoseDrawKeypoints` and `LoadDA3Model`/`DA3Inference`/`DA3Render` (V).
3. The **already-pinned** Fun Control 5B model card claims Pose and Depth control, not only Canny (C). A pose or depth arm on
   the existing 5B weights therefore needs no new diffusion model.
4. No candidate is shown to solve the five operator problems. Evidence is vendor demos, a paper, and templates. Nothing here
   substitutes for Phase 4 physical runs on this GPU.

## 3. Problem coverage matrix

"Plausible" means a mechanism exists in the documented design; it is not evidence of success. The right column is what Phase 4
must measure.

| Operator problem | Why today's engines fail (repo evidence) | Cand. 1 pose/depth Fun | Cand. 2 SCAIL-2 | Cand. 3 VACE | Phase 4 measurement |
|---|---|---|---|---|---|
| Driver-appearance contamination | RGB drivers leak face, clothing, background (MOTION-354 visual review; Animate-2 consumes RGB per MOTION-212) | Plausible: a pose map carries no appearance (I). Depth keeps body volume and clothing shape (I) | Plausible in pose-driven mode (C: SCAIL-2 README). End-to-end RGB mode uses the raw driver plus masks, so contamination is open (U) | Plausible with pose/depth control (I) | `driver_contamination` rating, RGB vs pose vs depth vs silhouette on one driver |
| Subject attachment | Animate-2: motion lands on a different figure or ghosts (PR-192, MOTION-410) | Pose map position defines where the figure moves (I); no explicit binding (U) | Explicit per-identity colored masks bind driver region to reference (V in node source and template; effectiveness C) | Reference image + mask exist; attachment untested (U) | `subject_attachment` rating, ghost count |
| Initial-pose mismatch | Frontal reference vs lateral driver (PR-192, MOTION-420) | Reference is used as the start frame (V: Comfy docs), so the first control frame can disagree with it (I) | Reference is a latent slot, not frame 0 (V in node: `reference_latents`); effect on pose mismatch U | Mask can pin first frames (V in template note) | `start_end_pose` rating, aligned vs unaligned (MOTION-420) |
| Locomotion | Reference-bound travel not demonstrated (PR-183, PR-192) | Control follows the pose map's screen-space travel (I) | 3D capsules are camera-projected so depth and travel are encoded (C) | Control video travel (I) | `root_displacement` rating plus global motion diagnostic |
| Head turns | A body skeleton cannot express them | Whole-body pose has face landmarks (V: SDPose 133 keypoints); whether Fun was trained to use them is U | SAM3D-Body `mesh` render carries head orientation (I); the SCAIL paper says face control is landmark-only (V as summarized) | U | `head_turn` category cases, `action_direction` |

## 4. Candidate 1 — Fun Control with a pose-map or depth-map control video

### 4.1 What it is
Same model family and node as the registered `wan22_fun_control_5b_canny_i2v_v1` (V: catalog and `nodes_wan.py`). The only
change is the control video: instead of Canny of the RGB driver, feed an OpenPose-style whole-body map or a depth map.

### 4.2 Verified facts

| Item | Evidence |
|---|---|
| Upstream models | `alibaba-pai/Wan2.2-Fun-5B-Control` and `alibaba-pai/Wan2.2-Fun-A14B-Control`, Apache-2.0 on both cards (V; <https://huggingface.co/alibaba-pai/Wan2.2-Fun-5B-Control>, <https://huggingface.co/alibaba-pai/Wan2.2-Fun-A14B-Control>). Card "Updated" 11 Dec 2025 (A14B). |
| Vendor control claims | 5B: "Canny, Depth, Pose, MLSD, and trajectory control", trained at 121 frames, 24 FPS. A14B: same list, 512/768/1024, 81 frames, 16 FPS (C, README_en.md of each repo). A "Generic Control Video + Reference Image" pose demo exists (C). |
| Comfy node | `Wan22FunControlToVideo` takes `ref_image`, optional `start_image`, `control_video`; `WanFunControlToVideo` is the 2.1 variant (V, `comfy_extras/nodes_wan.py` lines 70-160 at the pin). |
| Official template | `video_wan2_2_14B_fun_control.json` and `video_wan2_2_5B_fun_control.json` ship in the installed templates package (V). The 14B template note says the model "supports multiple control conditions such as Canny, Depth, Pose, and trajectory control". The 5B template is the one the repo's catalog is already derived from (FUN-352). |
| Pose/depth extractors in core | `SDPoseKeypointExtractor`, `SDPoseDrawKeypoints`, `SDPoseFaceBBoxes`; `LoadDA3Model`, `DA3Inference`, `DA3Render`; blueprint "Video to Pose Map (SDPose Multi-Person)" uses `RTDETR_detect` + SDPose (V, source and `blueprints/`). SDPose weights: `Comfy-Org/SDPose` `sdpose_wholebody_fp16.safetensors` 1,916,645,792 bytes and `rt_detr_v4-x-hgnet_fp16.safetensors` 123,968,978 bytes, MIT (V; <https://huggingface.co/Comfy-Org/SDPose>). Upstream SDPose is a Stable Diffusion 2 U-Net fine-tune with a card license of MIT (V; <https://huggingface.co/teemosliang/SDPose-Wholebody>); whether the SD2 base adds license terms is **not verified**. |
| Reference semantics | Comfy docs: the uploaded image is a "Start frame for video generation", "not a style reference" (V as summarized; <https://docs.comfy.org/tutorials/video/wan/wan2-2-fun-control>). |
| A14B files (Comfy repack) | `wan2.2_fun_control_{high,low}_noise_14B_fp8_scaled.safetensors` 14,296,064,656 bytes each; bf16 28,579,237,064 each; 5B bf16 10,003,303,280 (V; <https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged>). Repo license apache-2.0 (V). |
| Compatibility with pin | All nodes above are in v0.38.0 source (V). No custom node. The existing 5B asset set (3 pinned files) is unchanged for the 5B arm. |

### 4.3 Input representation and the repo's own constraint
OpenPose-style or depth frames with the generation geometry. The roadmap already states that "a skeleton render is not an
OpenPose map" (V, roadmap Phase 4). The Blender skeleton renders from MOTION-354 are spindle solids, not OpenPose colored sticks,
so they are **not** a validated Fun pose input (I). A valid pose arm extracts keypoints from a real clip with SDPose, or renders a
Blender rig in the OpenPose color/topology convention (new work, not in the repo).

### 4.4 Resources
- 5B: peak 11.0-11.9 GB VRAM and 14/14 cases clean at 17/49 frames on this host (V, MOTION-354 run 3), with the caveat that two 4K inputs hit host-commit stops in runs 1-2. A pose/depth control video of the same geometry should not change DiT memory (I), but the extra extractor graph (SDPose + RT-DETR, or DA3) has **U** memory and time.
- A14B: two experts, run sequentially; fp8 14.3 GB each. Comfy's doc run was 83% of a 24 GB card at 640x640, 81 frames, fp8 (C, as summarized), which is above 12 GB. On 12 GB this needs weight offload; fit and host RAM/commit are **U**. The repo's Wan-Animate-2 (14B int8) did run on this card at about 7 min and 11.6 of 12.3 GB per 81-frame job (V, roadmap Phase 2), a loose analog only.
- A 16 GB host-RAM advisory applies; the Fun trial already uses it (V, FUN-352).

### 4.5 Integration surfaces and reuse
- New catalog version or sibling module modeled on `workflow_catalog_fun_control.py`; graph gains an extractor subgraph between `GetVideoComponents` and the conditioning node. `driving_frame_consumption.py` checks the ordered `LoadVideo -> GetVideoComponents -> ResizeImageMaskNode` path (V, MOTION-212), so a transform node in that path needs an explicit, reviewed predicate extension. Do not weaken it silently.
- Reusable now: Motion Library, Prepare Motion Source exact-frame preparation, alignment (420), Blender conversion for motion sources, the `tools/qualification/fun354` Q0/executor/teardown/telemetry harness, the eval kit v2 motion cases. Not reusable: `conditioning_preview.py` is Canny-only; a pose/depth preview would be new.
- Alternatively the pose map can be pre-rendered as an operator-prepared driver (a Prepare Motion Source derivative) so the graph stays unchanged. That moves extraction outside the job and changes provenance; it is a design decision, not made here.

### 4.6 Security and maintenance
No custom nodes. `.safetensors` only for Comfy-Org repacks (V filenames); SDPose loads through core. The repack provenance (Comfy-Org converting alibaba-pai weights) should be pinned by SHA-256 and compared with the upstream where possible (U: upstream is `.pth`/sharded; not compared here). Graph and node versions are frozen by the runtime pin.

### 4.7 Known limitations
Vendor-only quality evidence. Pose maps cannot express fine facial rotation unless face keypoints are drawn and the model was trained on them (U). Depth maps carry body shape and clothing silhouette, so depth reduces rather than removes leakage (I). The reference is the start frame (V), which leaves initial-pose mismatch unaddressed (I). Control is a hard structural constraint, so a mismatched reference proportion can distort the subject (I).

### 4.8 Recommendation: PURSUE first (conditional)
Lowest cost: zero new diffusion weights for the 5B arm, same engine as the existing trial, and it isolates the representation variable. Stop if pose/depth arms show equal or worse `driver_contamination`, or if extractor memory breaks Q0.

## 5. Candidate 2 — SCAIL-2

### 5.1 What it is
Wan2.1-14B-based character animation (C): reference image + driving video (+ per-identity masks) in an in-context design with no required intermediate skeleton. Modes: Animation, Replacement, experimental multi-reference (C, <https://github.com/zai-org/SCAIL-2>). Paper: arXiv 2606.10804 (<https://arxiv.org/abs/2606.10804>). SCAIL-2's README says it "supports ... zero-shot ... SAM3D-Body mesh rendering" as an alternate control intermediate (C, <https://huggingface.co/zai-org/SCAIL-2>, updated 15 Jul 2026). The predecessor SCAIL(-Preview) used NLFPose 3D skeleton rendered as cylinders (C/V, <https://arxiv.org/html/2512.05905v3> as summarized).

### 5.2 Verified facts

| Item | Evidence |
|---|---|
| In pinned Comfy | `comfy_extras/nodes_scail.py`: `WanSCAILToVideo`, `SCAIL2ColoredMask`, both `is_experimental=True`; `comfy/ldm/wan/model.py` `SCAILWanModel`/`SCAIL2WanModel`; model detection by `patch_embedding_mask.weight`/`patch_embedding_pose.weight` (V). Merged upstream 2026-06-09 as commit `184009c`, PR #14373 (V as summarized; <https://github.com/Comfy-Org/ComfyUI/pull/14373>). |
| Official templates | `video_wan21_scail2_character_replacement.json` and `_int8.json` in the installed package; the template note says it "requires ComfyUI PR#14373", which this pin contains (V). The template's `pose_video` input is the **driving video** and masks come from SAM3 tracking (V). No pose-only SCAIL-2 template ships. |
| Node semantics | `pose_video` is downscaled to half generation resolution, VAE-encoded, injected with strength/start/end; masks are 28-channel colored per-identity; width/height step 32; length step 4 (V, source). `replacement_mode` must match how the mask background was rendered (V). Chunked extension via `previous_frames`, 76-frame step, 5-frame overlap, manual per-segment queueing (V, template note). |
| Models (Comfy repack) | `Comfy-Org/SCAIL-2`: fp16 32,794,040,328; fp8_scaled 17,694,586,857; **int8_convrot 16,654,506,256**; mxfp8 17,150,733,432; nvfp4_mxpf8_mix 11,023,570,536 bytes; DPO LoRA and relight LoRA 1,226,936,552 each (V; <https://huggingface.co/Comfy-Org/SCAIL-2>, card updated 2026-09-23). The int8 template additionally uses `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16`, `Wan2_1_VAE_bf16`, `umt5_xxl_fp8_e4m3fn_scaled`, `clip_vision_h` (V). The last three are already pinned for Animate-2 (V, `workflow_catalog_wan_animate2.py`). |
| Mask/pose helpers | `Comfy-Org/sam3.1` `sam3.1_multiplex_fp16.safetensors` 1,745,546,848 bytes; `Comfy-Org/sam-3d-body` bf16 2,830,737,652 / int8_convrot 1,994,073,596 bytes (V). Both are under Meta's custom **SAM License** (HF license `other`, LICENSE text read in part) (V). |
| Upstream licensing | HF cards for `zai-org/SCAIL-2` and `Comfy-Org/SCAIL-2`: MIT (V). GitHub README: code under Apache-2.0, weights license not stated there (V as summarized). Conflict between sources is unresolved; owner should record the HF card as the weight license and keep the GitHub text. |
| Official checkpoint format | `zai-org/SCAIL-2` ships `fsdp2_rank_0000_checkpoint.pt` (65.6 GB) and `.pt` LoRAs (V listing). `.pt` is normally pickle-based (I). Use only the safetensors repack, never the official `.pt`, in a managed runtime. |
| Output geometry | 512p and 704p supported, H and W divisible by 32 (C, model card). StableNew's 480x832 passes the divisible-by-32 test (V arithmetic) but 480p-class vs trained 512/704p is a **U** quality question. |

### 5.3 Input representation
- **End-to-end mode (V in template)**: RGB driving video + SAM3 colored masks of the driver and the reference subject. RGB goes in, so appearance contamination is not structurally excluded (I). README warns that without a correct mask Animation mode "collapse[s] into Replacement-Mode behavior" (C).
- **Pose-driven mode (C)**: a pose render as `pose_video`. In core, `SAM3DBody_Predict` + `SAM3DBody_Render` with `render_style` = `mesh`, `silhouette`, `openpose_2d`, `openpose_3d` or `scail` (V, source). The `scail` style draws 3D capsules plus optional hand dots and face landmarks (V). Whether SCAIL-2 handles each style equally is **U**.
- **Blender reuse hypothesis (I)**: the MOTION-354 Blender `high_contrast_silhouette` or `character` render of a mannequin is an appearance-free driver by construction. It could be tested as an end-to-end driver with a mask derived from the render itself. This is not claimed by the vendor and is untested.

### 5.4 Resources (conservative)
- Weight-only footprint 16.7 GB int8 versus 12.3 GB VRAM means the DiT cannot be GPU-resident; offload is certain (I). Host RAM must stage the file; the 16 GB advisory and `--disable-pinned-memory` make RAM/commit headroom the likely binding constraint, the same failure class seen in FUN-354 runs 1-2 (V for that history, I for transfer).
- Evidence for 12 GB is one third-party PR comment: an RTX 4070 SUPER with `--novram`, ~16.9 GB offloaded, ~566 s sampling (V as summarized from the PR thread; anecdote, settings unknown).
- Paper numbers are H100 un-offloaded: 61.7-68.5 GB for the 14B SCAIL-Preview with CFG (C, as summarized). Not comparable to a quantized, offloaded run.
- Animate-2 (14B int8 convrot) ran on this host at ~7 min and 11.6 of 12.3 GB (V, roadmap). SCAIL-2 adds a pose/mask token stream (V in `SCAILWanModel`: extra tokens concatenated), so memory above Animate-2 is likely (I) but unmeasured (U).
- `nvfp4` and `mxfp8` files target Blackwell-class hardware (I, from format names); not expected to help an RTX 4070 Ti (U). The int8 convrot path is the only quantization already exercised on this host (V, Animate-2).
- Pre-extraction (SAM3.1 + SAM3D-Body) is additional GPU work; whether it runs in-graph or as a separate prepared step is a design choice with a provenance cost (see 5.5).

### 5.5 Integration surfaces
New catalog module modeled on `workflow_catalog_wan_animate2.py` (the closest existing consumer of a driving video plus reference). Open design questions the Phase 4 package must settle before authoring a graph:
1. Where mask and pose extraction run (in-graph subgraph versus prepared derivative). Prepared derivatives keep the job graph small and preserve the canonical path (`Intent -> Compiler -> NJR -> ... -> Handler`); they require a new, verified preparation contract under Prepare Motion Source (MOTION-210 pattern). No second runner or queue.
2. Per-identity color assignment is order-dependent (`sort_by`): the frozen NJR must record the identity-to-color mapping or replay is ambiguous (I).
3. Multi-segment: Comfy's template cannot loop; StableNew's existing sequence architecture (SEQ-330) is the likely owner of continuation (I).
4. Controls surfaced: `pose_strength`, `pose_start`, `pose_end`, `replacement_mode` (V in node). These are the same shape as Animate-2's declared controls (MOTION-212).

### 5.6 Security and maintenance
- Core nodes only, but flagged **experimental** in source (V). Upstream API drift is contained by the runtime pin.
- `SAM3DBody_Loader` loads with `comfy.utils.load_torch_file(..., safe_load=True)` (V). Weights are safetensors in the Comfy-Org repacks (V filenames).
- Meta SAM License governs SAM3.1 and SAM3D Body (V). Terms were not read in full; owner review is required before any download decision.
- The official `.pt` checkpoints and `scail_pose` submodule belong to a separate PyTorch inference stack (Python 3.10-3.12 per README, C) that the managed runtime (3.13) does not use. Do not adopt it.
- SCAIL-Preview has no first-party safetensors repack (V: HF search showed only community GGUF conversions); the official Preview weights are a 32.8 GB `.pt`. **Exclude Preview** from Phase 4.

### 5.7 Known limitations (authors, as summarized) and gaps
Multi-person pose less precise than single-person; facial control is landmark-based, fine expression not covered; heavy occlusion can drop a character; multi-reference "not optimized"; short prompts work worse (C). No source states limits for locomotion, initial-pose mismatch or head turn. SCAIL-2's synthetic training data introduces "synthetic discrepancy in detailed regions" (C, abstract). The 60K-pair training set was synthesized from teacher models including Wan-Animate (C), so SCAIL-2 may inherit teacher failure modes (I).

### 5.8 Recommendation: PURSUE, gated (conditional)
It is the only candidate whose design explicitly binds driver identities to reference identities, and the whole stack is inside the pinned core. Gate: a Q0 readiness check (hashes, host RAM/commit, disk ~25 GB new files) and a single 17-frame Q1 at 480x832 must be clean before any motion case. If Q1 hits a resource stop with complete telemetry, the verdict is NO-GO for this host; do not tune toward a pass.

## 6. Candidate 3 — Wan VACE-style control

### 6.1 Verified facts

| Item | Evidence |
|---|---|
| Models | `alibaba-pai/Wan2.2-VACE-Fun-A14B` (Apache-2.0; based on Wan2.2-T2V-A14B; "Canny, Depth, Pose, MLSD, trajectory control"; subject-driven generation; 512/768/1024, 81 frames, 16 FPS; 64 GB repo) (C; HF card README_en.md, <https://huggingface.co/alibaba-pai/Wan2.2-VACE-Fun-A14B>). `Wan-AI/Wan2.1-VACE-14B` and `-1.3B` (Apache-2.0, May 2025, V card). VACE paper arXiv 2503.07598 (<https://arxiv.org/abs/2503.07598>). |
| Comfy files | `wan2.2_fun_vace_{high,low}_noise_14B_fp8_scaled.safetensors` 17,346,056,104 bytes each; bf16 34,675,325,000 each (V; <https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged>). Wan2.1 templates use `wan2.1_vace_14B_fp16` or `wan2.1_vace_1.3B_fp16` (V in templates). |
| Core node | `WanVaceToVideo`: `control_video`, optional `control_masks`, `reference_image` (only the first reference is used: `reference_image[:1]`) (V, `nodes_wan.py` lines 291-345). |
| Official templates | `video_wan_vace_14B_v2v`, `_ref2v`, `_t2v`, `_flf2v`, `_inpainting`, `_outpainting` (V). The V2V template preprocesses with Canny; a note points to `comfyui_controlnet_aux` for other preprocessors (V). **No official pose-to-video VACE template** and no Wan2.2-VACE-Fun template ships in this templates package (V). Pose-driven VACE appears only in third-party tutorials (not evaluated). |
| Reference semantics | Template note: VACE "does not use data with style reference for training", reference works as object or background and should have a plain background; one reference only (V). |
| Speed note | Comfy template says the 14B takes ~40 min at 81 frames 720p on an RTX 4090 without CausVid LoRA, ~4 min with it (V in template text; vendor note, unmeasured here). |

### 6.2 Assessment
- Addresses: initial-frame pinning through masks is a unique mechanism (V in template: "control the starting frame"). It does not address contamination, attachment or head turns beyond what a pose/depth control video already provides in candidate 1 (I).
- Resources: A14B fp8 is 17.3 GB per expert, larger than Fun A14B (14.3 GB), so strictly harder than candidate 1's escalation (I). Wan2.1-VACE-1.3B would fit 12 GB comfortably (I) but is 480p-only (V template table) and a different quality class; no evidence it transfers body motion convincingly (U).
- Integration surface is another driving-video engine with a mask input. The repo has no mask-input workflow family yet; SCAIL-2 would introduce it first (I).
- Security: core node, safetensors repacks, Apache-2.0 (V). Nothing distinctive.

### 6.3 Recommendation: DEFER (conditional)
Revisit only if candidate 1 shows control-video fidelity but a persistent start-pose mismatch that mask-pinned first frames could fix, or if SCAIL-2 is NO-GO and a mask-based engine is still wanted. Never infer capability from VACE demos.

## 7. Considered and not selected (no deep evidence gathered)

| Option | Basis for not selecting | Status of evidence |
|---|---|---|
| SCAIL-Preview (v1, 3D pose cylinders) | No first-party safetensors; official weights are a 32.8 GB `.pt`; superseded by SCAIL-2 which can take the same pose render | V (HF listing, search) |
| `WanTrackToVideo` (trajectory/Wan-Move) | Present in core (V). Sparse point tracks do not express head turns (I). Not researched further | Node V only |
| LTX-2 "Pose to Video"/"Depth to Video" blueprints | Present in pinned blueprints (V filenames). Different model stack, new weights and unmeasured on 12 GB; not researched | Filename only |
| UniAnimate-class, MimicMotion-class | Not researched in this session; no evidence either way. Both would likely need custom nodes outside the `none` policy (I) | **U** |
| Wan-Animate-2 and Fun 5B Canny | Already registered; they are the baselines | V (repo) |

## 8. Comparative validation using the existing eval kit

Constraint: each physical run needs fresh exact owner authorization (roadmap section 7). Reuse `stablenew.video-eval-suite.v2` motion cases, the frozen-input admission, and the review/rating columns of runbook section 9. Nothing below is run now.

### 8.1 Gates before motion cases
| Stage | Content | Pass condition |
|---|---|---|
| Q0 (read-only) | Pin HF revisions and SHA-256 of every new file; disk; host RAM/commit recorded (not borrowed thresholds, per FUN-354); runtime commit; no custom nodes | READY, no download without owner approval |
| Q1 | One 17-frame generation per candidate at 480x832, one fresh owned runtime, FUN-354 stop rules, no auto-retry | Clean, exact frame count, clean teardown, telemetry complete |
| Q2 | 49 and 81 frames where the engine's envelope allows; cancel/release | Same as FUN-354 Q2 |

### 8.2 Motion arms (all share seed, source images, prompts)
Baselines: Animate-2 (registered) and Fun 5B Canny (registered, trial). Candidates: Fun 5B pose, Fun 5B depth, SCAIL-2 end-to-end, SCAIL-2 pose-driven (`scail` or `mesh` render), optionally Fun A14B pose (only if 5B pose shows value and Q1 is clean). Every arm differs from its comparator in declared fields so the report can classify one-variable versus multi-setting pairs (runbook 9.2).

### 8.3 Cases (categories already in the kit)
`head_turn`, `hand_wave`, `raise_arms`, `walk_forward` (locomotion), `turn_around`, plus a deliberately mismatched-start-pose case (front reference, side driver; uses MOTION-420 aligned vs unaligned). At least two distinct source subjects, because the kit needs two rated subjects for READY FOR OWNER REVIEW (V, runbook 9.4). The recent pilot (head turn, wave looked fine on Animate-2) is a positive-control reference, not a pass for the new arms.

### 8.4 Method-diverse challenge and critical controls (repo conventions)
1. **Representation ablation on one motion**: same driver as RGB, Canny, pose map, depth, silhouette. Primary metric `driver_contamination` plus `unintended_appearance_transfer`.
2. **Negative control**: a static/blank control video per arm. Must produce no invented travel; checks that motion is driven by the control and not by the prompt or seed.
3. **Mismatched-driver control**: same subject, a different action's driver. The action must follow the driver (`wrong_action` otherwise).
4. **Identity-neutral driver**: a Blender mannequin render (MOTION-354) versus a real-person clip for the same action. Checks contamination without relying on the representation alone.
5. **Independent measurement** that does not share the rater's method: the existing global image-motion diagnostic (a guardrail, not fidelity, per runbook 9.4) and, as optional new work, re-extracting keypoints from generated clips and comparing joint trajectories with the driver. The second is not in the repo and would need its own package.
6. Blind owner rating of motion columns separate from quality/identity (runbook 9.3). Unrated cells stay "not assessed".

### 8.5 Budget (ceilings, not authorizations)
Stage 1: 3 Q1 runs + 1-2 Q2 per surviving candidate. Stage 2: about 6 cases x 4-5 arms = 24-30 jobs, under the kit's 64-job limit and staged like MOTION-410 (3 / 12 / remainder). Per-job time is unknown for SCAIL-2 and Fun pose arms; Animate-2 at ~7 min is the only 14B reference.

## 9. What would change these recommendations

| Evidence | Effect |
|---|---|
| Fun 5B pose/depth Q1 clean but `driver_contamination` no better than Canny | Candidate 1 downgraded to REJECT for contamination; keep only if head-turn or locomotion benefit shows |
| Fun 5B pose fails to follow pose (static or garbled output) | Vendor pose claim for 5B unsupported; escalate to A14B only if Q1 resource-feasible, else reject |
| SCAIL-2 Q0/Q1 reaches a host-commit or VRAM stop with complete telemetry | NO-GO on this host; Candidate 2 becomes DEFER pending hardware or runtime change, not re-tuning |
| SCAIL-2 Q1 clean and attachment/ghost rate clearly better than Animate-2 on the same cases | Candidate 2 becomes the primary Phase 4 engine candidate; still no promotion without owner decision |
| SAM License review fails or the owner refuses SAM3.1/SAM3D Body | SCAIL-2 pose-driven and mask paths are unavailable as designed; Candidate 2 reduced to an RGB-only arm or REJECT |
| Conflict between GitHub (Apache-2.0 code, weights unstated) and HF (MIT) resolves against redistribution use | Re-evaluate Candidate 2 |
| A Phase 4 run shows start-pose mismatch dominating failures for candidates 1 and 2 | Promote Candidate 3 (VACE mask-pinned start frame) from DEFER to a bounded test |
| New ComfyUI release changes `Wan22FunControlToVideo`, `WanSCAILToVideo` or SAM3D nodes | Re-read at the pin; pinned runtime is unaffected until deliberately upgraded |
| Upstream publishes a SCAIL-2 pose-only template or 12 GB benchmark | Replace inference in section 5.4 with evidence |

## 10. Limitations of this assessment

- No physical evidence, no model executed, no workflow loaded or validated in Comfy. "Compatible with the pin" means the node classes and template files exist in the pinned source and package, not that a template runs unmodified on this machine.
- HF repo revisions and SHA-256 were not recorded. File sizes are from live listings on 2026-11-25 and can change.
- Several pages (SCAIL/SCAIL-2 GitHub, SCAIL paper, ComfyUI PR #14373 thread, Comfy docs page, VACE-Fun card) were read through a summarizing fetch tool. The PR thread was read only to ~100k of ~228k characters. Treat quoted numbers (H100 memory, 566 s, Mot-Acc) as leads, not facts.
- The SCAIL-2 pose-driven mode and the SAM3D-Body `scail`/`mesh` renders are described by the vendor; the core renderers were read only for options and tooltips, not tested. Whether core's capsule render matches the official `scail_pose` output is **U**.
- Fun Control pose training distribution (face keypoints, line widths, colors) and SDPose draw conformance with it are **U**; "OpenPose-style" here is the node's own description.
- Licenses: card-level only. Not read: SAM License full text, SD2 or Wan upstream terms, the Wan2.2 license. This is not legal review.
- Resource judgements for 12 GB are inference from file sizes plus analogs (Animate-2, Fun 5B). The only direct 12 GB datum for SCAIL-2 is an unverified forum-style report.
- UniAnimate, MimicMotion, LTX-2 pose control and trajectory engines were not researched; their absence is not a rejection.
- Method diversity: one read-only pass (source + model cards + templates). No independent second reviewer or agent challenged the candidate choice; the Section 3 matrix is the main place a different reader could disagree.

## 11. Evidence links

- Roadmap Phase 4: `docs/Subsystems/Video/CONTROLLED_MOTION_ROADMAP.md`
- Fun Control: `docs/Subsystems/Video/PR-VID-FUN-352_Fun_Control_5B.md`, `PR-VID-MOTION-354_Motion_Conversion_and_Fun_Qualification.md`, `tools/qualification/fun354/`
- Conditioning semantics: `docs/Subsystems/Video/PR-VID-MOTION-212_Conditioning_Semantics_and_Fidelity.md`
- Eval kit: `docs/runbooks/video_eval_kit.md` sections 9-10
- Pinned runtime: `config/managed_comfy_runtime.json`; local source `comfy_extras/nodes_scail.py`, `nodes_wan.py`, `nodes_sam3d_body.py`, `nodes_sdpose.py`, `nodes_depth_anything_3.py`
- Upstream: <https://github.com/zai-org/SCAIL-2>, <https://huggingface.co/zai-org/SCAIL-2>, <https://huggingface.co/Comfy-Org/SCAIL-2>, <https://huggingface.co/Comfy-Org/sam3.1>, <https://huggingface.co/Comfy-Org/sam-3d-body>, <https://huggingface.co/Comfy-Org/SDPose>, <https://github.com/Comfy-Org/ComfyUI/pull/14373>, <https://arxiv.org/abs/2606.10804>, <https://arxiv.org/html/2512.05905v3>, <https://huggingface.co/alibaba-pai/Wan2.2-Fun-5B-Control>, <https://huggingface.co/alibaba-pai/Wan2.2-Fun-A14B-Control>, <https://huggingface.co/alibaba-pai/Wan2.2-VACE-Fun-A14B>, <https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged>, <https://docs.comfy.org/tutorials/video/wan/wan2-2-fun-control>, <https://docs.comfy.org/tutorials/video/wan/vace>, <https://arxiv.org/abs/2503.07598>
