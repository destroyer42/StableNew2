# QUAL-CAMPAIGN-920 — Wave 0: plan for qualifying the capability ledger

Status: Wave 0 planning record, 2026-11-18. It changes no code, ledger status, plan, authorization or runtime. It maps
every capability in `tools/qualification/system840/ledger.v1.json` to the harness that could produce qualifying evidence,
names the gaps, orders the work and proposes the human quality rubric. The ledger, `STATUS.md` and `AGENTS.md` stay the
authorities; where this record and live code disagree, live code wins.

## 1. What QUALIFIED requires

From `tools/qualification/system840/ledger.py` (`derive_status`), `verdict.py` and `docs/runbooks/qual_system_840.md`:

- **All three ledger dimensions — resource, quality, integration — must be QUALIFIED.** Quality is NOT TESTED on all 50
  entries today, so no amount of resource/integration evidence alone produces a QUALIFIED entry.
- **Quality and usability are human judgments.** `verdict.py` records automated measures beside them, never in their place;
  only a human `PASS` with `rated_by` can carry the quality dimension.
- **Evidence must be physical, GUI-driven and identity-matched.** A driver-path run reaches PARTIALLY QUALIFIED at most; a
  result for a different model, workflow or runtime revision does not apply (`applies_to` must equal the identity).
- **Every physical run needs the owner.** A frozen plan, an `APPROVE <arm> <digest12>` authorization (never issued by an
  agent; a named delegate may type the launch phrase once per digest), a typed `RUN <digest12>` and passing readiness.
- **A status changes only by an owner-accepted, reviewed edit of the ledger JSON.**
- Standing hold `HOLD-GPU-DEVICE-LOSS`: any new device loss stops the campaign. GPU arms never run concurrently, and CPU
  inference (AI Assist, Smart Review) never shares a session with a GPU arm.

## 2. Scope: about 35 qualifiable entries

| Out of scope for this campaign | Count | Reason |
| --- | --- | --- |
| `AI-Q0`, `AI-Q1` (6 candidates), `AI-Q2` | 8 | HOLD on `HOLD-AI-ETW-CANARY` |
| `IMG-Q1.zimage-turbo-fp8`, `IMG-Q4.forge-vs-comfy-still`, `VID-Q4.wan-a14b-480p` | 3 | structural holds; need new exact owner decisions |
| `IMG-Q1.klein-base-9b` | 1 | NO-GO is the verdict |
| `IMG-Q1.qwen-image`, `IMG-Q1.other-generic-families` | 2 | UNSUPPORTED |
| `IMG-Q4.ideogram4-diffusers` | 1 | waits on the PR-IMG-120 owner decision |
| `VID-Q0.wan22-ti2v-5b-legacy-1.0.0-1.1.0` | 1 | superseded; kept only for replay of stored jobs |

The rest — 21 NOT TESTED plus 11 PARTIALLY QUALIFIED plus 2 FEASIBLE (`IMG-Q2.controlnet-openpose`,
`VID-Q2.fun-control-5b-canny`) — are in scope.

## 3. The key gap: almost nothing has a physical lane

Physical qualifying evidence comes from the golden-path harness (`python -m tools.operator_journey --suite golden-paths
--mode physical`). The campaign coordinator ships no physical adapter for any arm (`coordinator.py` `UnwiredAdapter`
refuses and points at the retained harness).

| Journey | Physical lane | Drives |
| --- | --- | --- |
| IMG-01 | **yes** | PromptPack txt2img through queue and History |
| VID-01 | **yes** | reference image → Wan2.2 TI2V in Video Workflow, in-app playback, History |
| LRN-01 | **yes** | designed Learning experiment and rating persistence |
| IMG-02 | simulated only | PromptPack/model profiles/effective settings |
| IMG-03 | simulated only (`run_img03` raises "IMG-03 has no physical lane") | History → Review masked edit → Compare with Parent → provenance |
| VID-02 | simulated only | Batch Convert Motion, Motion Library, Use as Driving Video, Prepare Motion Source |
| VID-03 | simulated only | Storyboard author/save/reopen/queue a sequence |
| LRN-02, OPS-01 | simulated only | profile publication; backend-fault recovery |

No journey at all drives: Regenerate with Changes, outpainting, the Review → Make Video hand-off, the video eval kit,
ControlNet units or reference-map creation, native SVD (and its RIFE/loop export), Movie Clips assembly as a queued job,
or Smart Review (`coverage_matrix.v1.json` lists these as `integration_only` or not at all).

## 4. Capability-by-capability map (in-scope entries)

Lane: G = GPU, C = CPU-only, O = offline (no inference). "Harness" is what exists today.

| Capability | Status | Lane | Harness today | Gap to close before a run | Depends on |
| --- | --- | --- | --- | --- | --- |
| IMG-Q0.sdxl-forge-baseline | PARTIAL | G | IMG-01 physical | none (owner says no more canary needed); needs a coverage-stage plan and a quality rating | — |
| IMG-Q1.sdxl-family | PARTIAL | G | IMG-01 physical | per-checkpoint target in the IMG-01 plan | IMG-Q0 |
| IMG-Q1.klein-4b-fp8 | PARTIAL | G | IMG-01 physical | new frozen plan for case A through the GUI | IMG-Q0 |
| IMG-Q2.adetailer-face | PARTIAL | G | none physical (IMG-01 turns ADetailer off) | IMG-01 variant with the stage on, or the PR-REFINE-160 operator procedure | IMG-Q0 |
| IMG-Q2.adetailer-hands | PARTIAL | G | none physical | as above, matched with/without | adetailer-face procedure |
| IMG-Q2.upscale | PARTIAL | G | none physical (IMG-01 turns upscale off) | IMG-01 variant with upscale on/off matched pair | IMG-Q0 |
| IMG-Q2.controlnet-openpose | FEASIBLE | G | none | ControlNet journey (CNET-211 step 2); SDXL ControlNet models not found in the searched roots | IMG-Q0 |
| IMG-Q2.controlnet-canny | NOT TESTED | G | none | ControlNet journey | openpose |
| IMG-Q2.controlnet-depth | NOT TESTED | G | none | ControlNet journey | openpose |
| IMG-Q2.reference-map-creation | NOT TESTED | C | none | reference-map journey (deterministic Canny first) | — |
| IMG-Q3.masked-inpaint | NOT TESTED | G | IMG-03 simulated | **IMG-03 physical lane** | IMG-Q0 |
| IMG-Q3.original-pixel-preservation | NOT TESTED | G | IMG-03 simulated | IMG-03 physical lane (same run) | masked-inpaint |
| IMG-Q3.compare-with-parent | NOT TESTED | O | IMG-03 simulated | IMG-03 physical lane (same run) | masked-inpaint |
| IMG-Q3.outpaint | NOT TESTED | G | none | outpaint step in IMG-03 | masked-inpaint |
| IMG-Q3.regenerate-with-changes | NOT TESTED | G | none | Regenerate step (History iterate) on an IMG-01 job | IMG-Q0 |
| IMG-Q3.replay-and-provenance | NOT TESTED | G | none physical | replay step on an IMG-01 job | IMG-Q0 |
| VID-Q0.wan22-ti2v-5b-1.3.0 | PARTIAL | G | VID-01 physical | VID-01 plan for a 17-frame 1.3.0 job | — |
| VID-Q0.wan22-ti2v-5b-1.2.0 | PARTIAL | G | VID-01 physical | reuse the 1.3.0 run | 1.3.0 |
| VID-Q5.playback-and-history | NOT TESTED | G | VID-01 physical | none beyond the VID-01 run | VID-Q0 1.3.0 |
| VID-Q5.make-video | NOT TESTED | G | VID-01 starts in Video Workflow, not Review | Review → Make Video hand-off step | VID-Q0 1.3.0 |
| VID-Q5.storyboard-save-reopen | NOT TESTED | G | VID-03 simulated | **VID-03 physical lane** | VID-Q0 1.3.0 |
| VID-Q5.two-three-segment-sequence | PARTIAL | G | VID-03 simulated | VID-03 physical lane plus resume/replay | storyboard |
| VID-Q5.movie-clips-assembly | NOT TESTED | C | VID-01 only sends to Movie Clips | queued assembly step | two finished clips |
| VID-Q5.eval-kit-and-ratings | NOT TESTED | O | none | eval-kit step on a finished clip | one finished clip |
| VID-Q5.prepare-motion-source | NOT TESTED | O | VID-02 simulated | VID-02 physical (offline) lane | — |
| VID-Q2.motion-library | NOT TESTED | O | VID-02 simulated | VID-02 physical (offline) lane | — |
| VID-Q2.motion-convert-blender | PARTIAL | O | VID-02 simulated | VID-02 physical lane with Blender | — |
| VID-Q2.fun-control-5b-canny | FEASIBLE | G | `tools/qualification/fun354` driver | run 4 after PR-VID-MOTION-355; reach is false today, so GUI evidence needs operator reachability first | prepare-motion-source |
| VID-Q3.wan-animate-2 | PARTIAL | G | dedicated 184R/S telemetry contract | pinned-OFF run after ordinary use | — |
| VID-Q1.svd-xt-native | NOT TESTED | G | none | SVD journey | — |
| VID-Q1.svd-rife-smoothing | NOT TESTED | G | none | SVD journey RIFE step | svd-xt |
| VID-Q1.svd-loop-export | NOT TESTED | G | none | SVD journey loop step | svd-xt |
| AI-Q3.sam21-small | NOT TESTED | C | none | owner gate decision, then a Smart Review journey and a fixed corpus | owner decision |
| AI-Q3.florence2-base-ft | NOT TESTED | C | none | as above | owner decision |

## 5. Installed assets (read-only check, 2026-11-18)

`python -m tools.qualification.system840 ledger --json --model-root ...` over the owner host's ComfyUI and A1111
`models` folders and the Hugging Face cache, plus targeted name searches and the app's own RIFE resolver. Nothing was downloaded, moved, hashed or modified.

| Asset | Result |
| --- | --- |
| Wan2.2 TI2V-5B (`wan2.2_ti2v_5B_fp16.safetensors`) | found (ComfyUI `diffusion_models`) |
| Wan2.2 Fun Control 5B | found (ComfyUI `diffusion_models`) |
| Native SVD XT (`svd_xt.safetensors`, also XT 1.1) | found (Hugging Face cache) |
| RIFE (`rife-ncnn-vulkan.exe`) | found by `find_rife_executable()` |
| SDXL baseline checkpoint (`cyberrealisticXL_v90-16fp`) | not under the searched A1111 `models` root; the managed Forge runtime resolves it from its `forge_ref_a1111_home` reference, and readiness verifies the SHA-256 at plan time |
| SDXL ControlNet models (OpenPose/Canny/Depth) | not found in the searched roots (ComfyUI `controlnet` is empty) |
| SAM 2.1 Small, Florence-2 Base FT weights | not found in the searched roots |

Not found here means "not in these folders", not "absent". Readiness checks the exact frozen identity before any run, and a
missing model is a HOLD, never a download.

## 6. Waves

Each physical wave is one owner sitting: plans are frozen in advance, the owner approves each digest, runs are launched
one at a time, and the owner rates the outputs with the rubric in section 7.

| Wave | Content | Prerequisite build packages |
| --- | --- | --- |
| 0 (this record) | map, inventory, order, rubric | — |
| 1 — offline/CPU | VID-02 physical (motion library, Prepare Motion Source, Blender convert); reference-map creation | VID-02 physical lane; reference-map journey |
| 2 — Forge SDXL | IMG-01 coverage stage (first QUALIFIED candidate: IMG-Q0 with a quality rating); upscale matched pair; ADetailer face procedure; IMG-03 masked edit (inpaint, pixel preservation, Compare with Parent); outpaint; Regenerate with Changes; replay | IMG-03 physical lane; IMG-01 stage variants; Regenerate/replay/outpaint steps |
| 3 — ControlNet | OpenPose → Canny → Depth | ControlNet journey; owner confirms which SDXL ControlNet models are installed |
| 4 — Wan 5B video | VID-01 1.3.0 run (also playback/History); Make Video hand-off; VID-03 Storyboard; assembly; eval kit | Make Video step; VID-03 physical lane; assembly and eval-kit steps |
| 5 — SVD | SVD XT → RIFE → loop export | SVD journey |
| 6 — Smart Review | SAM 2.1, Florence-2 | owner gate decision; Smart Review journey and corpus |

Expected owner effort: roughly 15–20 canary runs for the 21 NOT TESTED entries, plus coverage-stage runs for entries that
pass their canary, each with an approval, a launch and a rating.

## 7. Proposed quality rubric (owner decision)

The rater records `PASS` or `FAIL` per capability attempt with `rated_by`, and one line of reason. Automated measures are
shown beside the rating and never replace it. A capability needs a quality `PASS` on its coverage-stage evidence, not only
on the canary.

| Class | PASS when all hold | FAIL on any |
| --- | --- | --- |
| Image generation (IMG-Q0/Q1) | subject and composition match the prompt; anatomy and faces plausible at full size; no banding, colour cast or artefacts that would stop you using it | an unusable image at the plan's settings; a systematic defect across the batch |
| Image refinement (ADetailer, upscale) | the refined output is at least as good as the unrefined pair everywhere and better where targeted | the pass damages untargeted regions, changes identity, or adds artefacts |
| Image editing (inpaint, outpaint, Regenerate) | the edit does what was asked inside the region; seams invisible at 100 %; protected pixels unchanged (also checked automatically by hash) | visible seam or halo; change outside the region; ignored instruction |
| ControlNet / reference maps | the output follows the control (pose, edges, depth) closely; the map itself is clean | control ignored or misread; a map with obvious errors |
| Video generation (Wan, SVD, sequences) | motion follows the prompt; subject stays coherent across frames; no flicker or warping that would stop you using the clip; segment joins acceptable | identity drift, melting, strobing, frozen frames, a broken join |
| Video tooling (RIFE, loop, assembly, motion source) | the output plays smoothly with the expected length/fps and no added artefacts | stutter, duplicated or dropped frames, wrong length, visible loop seam |
| Smart Review (SAM, Florence) | masks cover the clicked object with clean edges; captions are accurate and useful | wrong object, ragged mask, misleading caption |

Usability is rated the same way on the GUI flow itself: could you complete the task without workarounds, and were all
messages truthful.

## 8. Owner decisions this plan needs

1. Accept or amend the rubric in section 7.
2. Smart Review: is AI-Q3 in scope, and under what authorization (the ledger notes no owner gate exists)?
3. Pace: one sitting per wave with several plans approved together, or one run at a time.
4. Confirm the out-of-scope list in section 2.
5. Which SDXL ControlNet models are installed (Wave 3 cannot be planned until this is known).

## 9. Proposed build packages (no physical work)

Each is a separate, CI-tested harness package. None runs a model; each adds a lane that stays refused until a frozen,
owner-authorized plan exists.

- **QUAL-921 IMG-03 physical lane**: masked edit, pixel preservation, Compare with Parent, plus outpaint, Regenerate with
  Changes and replay steps. Unblocks five entries in Wave 2.
- **QUAL-922 VID-02 physical (offline) lane**: unblocks Wave 1 (three entries).
- **QUAL-923 VID-03 physical lane plus Make Video, assembly and eval-kit steps**: unblocks Wave 4 (five entries).
- **QUAL-924 SVD journey**: unblocks Wave 5 (three entries).
- **QUAL-925 ControlNet and reference-map journey**: unblocks Wave 3 and reference-map creation (four entries); needs
  decision 5.
- **QUAL-926 IMG-01 stage variants** (ADetailer on, upscale on/off matched pair, per-checkpoint targets): unblocks the
  Wave 2 refinement entries.
