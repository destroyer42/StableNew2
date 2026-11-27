# VID-CAND-LTX25: LTX-2.5 distilled image-to-video candidate and three-way comparison

Status: researched, built offline and the model files downloaded and verified on 2026-11-27. **No LTX-2.5 clip has been
generated and neither graph has been validated by the real ComfyUI.** The two workflows are `experimental`, never the
Make Video default, never preselected and not QUALIFIED. The owner has approved the download and the section 7 run for
non-explicit clips only; every rating is the owner's (sections 1, 5 and 7).

Owner's words (2026-11-27): "Let's do both and compare. Still do the ltx-2.5 as well." The comparison is LTX-2.5
against HunyuanVideo 1.5 (VID-CAND-382) and the current default, Wan2.2 I2V-A14B 4-step 1.0.0.

## 1. Read first: the licence forbids sexually explicit content

LTX-2.5 is under the LTX-2.x Community License (dated 11 August 2026). Its Attachment A **incorporates Lightricks'
Acceptable Use Policy** "by reference" for the use of the model, its derivatives and the outputs, and says the version
in effect at the time of use governs. That policy (last updated 3 November 2026) has a section "Do Not Generate Sexually
Explicit Content": sexual intercourse or sex acts, content related to sexual fetishes or fantasies, incest or
bestiality, and erotic chats.

Sources, read 2026-11-27: the licence text at `https://huggingface.co/unsloth/LTX-2.5-GGUF/blob/main/LICENSE` (the
official model card links `https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x`);
`https://static.lightricks.com/legal/ltx-acceptable-use-policy.pdf`.

- The policy's own text speaks of Lightricks "Products" (apps, web services, API). The licence applies it to the open
  model by incorporation. That reading is this record's, not legal advice.
- Adult content is in the owner's scope (value assessment, 2026-11-27). So LTX-2.5 can only be considered for work that
  is not sexually explicit, whatever its quality. Community "uncensored" fine-tunes are Derivatives under the same
  licence.
- The 2026-11-27 value assessment recorded "worldwide and free for personal use" and listed the use restrictions as not
  read. Both statements about territory and price hold; the use restriction was missing.
- This package adds no content filter and blocks nothing in StableNew. It states the restriction on the workflow
  (description, notes, fixed settings) and as a typed N1 warning (`video_licence_restriction`, declared by the catalog
  entry's `licence_warning`) that shows beside Queue and is recorded on each job.
- **Owner decision, 2026-11-27 (relayed by the orchestrator session):** still wanted, **for non-explicit clips only**.
  The owner approved downloading the five files of section 5 after accepting the gate themselves, and the section 7 run
  once the GPU is free and the app, Forge and ComfyUI are closed. Every suite prompt and source must be non-explicit:
  verified safe-for-work subjects, never the output library.
- **Owner confirmation of the sources, 2026-11-27 (relayed by the orchestrator session):** all 16 source images in
  VID-CAND-382's stage 1 and stage 2 suites come from the output library. Asked to choose between a new safe-for-work set
  and reusing them, the owner chose "I'll vouch for the 16", confirming they are non-explicit and allowing them for
  LTX-2.5. They are reused exactly as frozen (same paths and hashes). No agent opened them to check. This covers these 16
  files only; every prompt must still be non-explicit.
- **Download, 2026-11-27:** the owner accepted the gate and the five files of section 5 were downloaded at the pinned
  revision (13:22-13:30 UTC), each matching its size and SHA-256, and placed as section 5 says.

Other terms: free below USD 10M annual revenue (personal use free); the licensee must not remove or disable provenance
marks or watermarks and must disclose that disseminated content is machine generated; the licensor reserves the right
to restrict use in breach; New York law. Access to the weights is gated: accepting shares the account's contact details
with Lightricks. The text encoder's base model, Gemma 4 12B, is Apache-2.0
(`https://huggingface.co/google/gemma-4-12B-it`).

## 2. Package contract

- **Objective:** an experimental, catalog-registered LTX-2.5 I2V workflow (silent and with audio) that runs through the
  normal Video Workflow path, and one blind comparison with VID-CAND-382's arms.
- **Explicit exclusions:** no promotion; no change to A14B, Hunyuan specs or VID-CAND-382's frozen suites; no custom
  ComfyUI nodes; no runtime change. The build did no download, licence acceptance or GPU work; the download and the
  section 7 run come under the owner's later approval (section 1).
- **Execution class:** Standard (one catalog spec module, two picker-tier rows, one read-only tool package).
- **Model recommendation:** Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High (`docs/AI_MODEL_SELECTION.md`).
- **Controller Surface Assessment:** no controller or coordinator file touched; no ratchet ceiling moved.
- **Token-efficient validation plan:** the two new test files, the catalog and picker tests, ruff, then
  `python tools/ci/run_pr_gate.py` and `tests/system tests/tools`.
- **Base:** `origin/main` `4a702000`, later merged with VID-FRAME (both the licence and the cropped-source warnings are
  kept); branch `claude/vid-cand-ltx25`.
- **Task start and session:** 2026-11-27T11:21Z; Claude Code session `local_31f44c29-0d98-4204-bd5a-15b788a5ac6a` with
  two web-reading subagents.

## 3. Verified facts (all read 2026-11-27)

### Established (primary sources or the installed runtime)

| Claim | Evidence |
|---|---|
| Release: LTX-2.5, a 22B joint audio-video diffusion transformer, `dev` and `distilled` checkpoints; repository revision `69ecadd4932572caf956135d41cbcdbd697aa442` (modified 2026-11-26); ComfyUI support announced 12 August 2026 | `https://huggingface.co/Lightricks/LTX-2.5` (card and Hub API); `https://blog.comfy.org/p/ltx-25-day-0-support-in-comfyui` |
| Official ComfyUI files: distilled and dev transformers in bf16 (42.0 GB), Comfy int8 convrot (21.5 GB) and, distilled only, NVFP4 (18.7 GB); Gemma 4 12B encoder bf16 (26.3 GB) or int8 (15.4 GB); two video VAEs (diffusion decoder 1.47 GB, convolutional 1.45 GB); audio VAE and vocoder (0.36 GB); x2 spatial upscaler (1.0 GB) | Hub file listing of `Lightricks/LTX-2.5` |
| ComfyUI needs 0.32.0 or later | the ComfyUI blog post above ("Update ComfyUI to the latest version 0.32.0") |
| The managed ComfyUI 0.38.0 already holds the nodes and the official templates (`video_ltx2_5_i2v.json`, `..._t2v`, `..._flf2v`), so **no runtime change is needed** | read-only inspection of the managed install (`comfy_extras/nodes_lt*.py`, `comfyui_workflow_templates_json` 0.1.96) |
| The template's I2V recipe: 8 distilled steps at half size, x2 latent upscaler, 3 steps at full size, `euler_ancestral`, CFG 1, 24 fps, tiled decode; optional prompt enhancer (a second Gemma model, off) | the installed template |
| Distilled: fixed 8-step schedule, CFG 1; width and height divisible by 32; frames `8n+1`; image-to-video and synchronized audio supported | model card |
| A plain (non-nested) video latent runs the model with no audio tokens, so a silent graph is genuinely audio-free | `comfy/ldm/lightricks/av_model.py` and `comfy/samplers.py` in the managed install |
| No ComfyUI changelog entry after 0.38.0 that was read mentions an LTX-2.5 fix; 0.40.0 adds a three-stage "DFR" template | `https://docs.comfy.org/changelog` (the part read verbatim) |
| Provenance marking (invisible, PixelSeal and AudioSeal) is opt-in in Lightricks' own `ltx-pipelines` (`--marker-root-path`); its page does not mention ComfyUI | `https://huggingface.co/Lightricks/LTX-2-Marking` |

### Community evidence (not controlled measurements)

- One RTX 3060 12 GB user: a 15 s 960x544 text-to-video clip "in just about 5 minutes" on the default ComfyUI
  workflow; system RAM, files and frame count not stated
  (`https://huggingface.co/Lightricks/LTX-2.5/discussions/25`, 12 August).
- GGUF quantisations (8.5-22.8 GB, e.g. `UD-Q4_K_XL` 14.0 GB) exist with published error tables
  (`https://huggingface.co/unsloth/LTX-2.5-GGUF`). They need the ComfyUI-GGUF **custom node**, which the managed
  runtime does not allow, so they are not used. NVFP4 gives no speed gain on this non-Blackwell card.
- Third-party guides disagree on a VRAM floor (12 GB to 16 GB). No official figure exists.

### Inferences

- 12 GB cannot hold the 21.5 GB transformer, so ComfyUI must stream it from RAM. About 39 GB of weights pass through
  the 48 GB host; A14B (about 37 GB of weights) left 10.7 GiB free in today's VID-CAND-382 run, so LTX-2.5 should fit
  with less margin.
- LTX-2.5's latent is 32x spatial and 8x temporal, so 768x1344x121 is about 16,000 tokens, half of A14B's 480x832x81.
  Time is likely dominated by weight streaming and the video decode.

### Unknown until a run

Time, VRAM and RAM peaks on this host; whether the diffusion video decoder fits 12 GB at 768x1344x121; identity and
anatomy on the owner's sources; behaviour on content the base model may not have been trained to draw; audio quality;
whether ComfyUI output carries any mark.

## 4. The candidate (implementation)

`src/video/workflow_catalog_ltx25.py`, registered in `build_builtin_workflow_specs`; both ids in the picker's
**Show experimental** tier. Two ids, each `1.0.0`, differing only in audio:

| Id | Output |
|---|---|
| `ltx25_distilled_i2v_v1` | video-only latent, `SaveImage`; StableNew encodes the frames at 24 fps (as A14B and Hunyuan) |
| `ltx25_distilled_i2v_audio_v1` | audio latent through both stages, `CreateVideo` + `SaveVideo`; ComfyUI encodes (the frames-out path has no audio), so its picture is not compared with other engines |

The two do not produce the same picture from one seed: audio changes the denoising.

Frozen values: portrait 768x1344, landscape 1344x768 (stage 1 at half; both edges multiples of 64; aspect 0.571
against A14B's 0.577; 2.6 times A14B's pixels); 25-121 frames, default 121 (5.04 s); the job's seed drives stage 1 and
stage 2 uses the template's fixed seed 42; `--disable-pinned-memory`; VRAM floor 9,500 MiB and RAM 24 GB advisory
(**unmeasured**); history timeout 2400 s; keep-warm 120 s. The template's long-side resize node is not used because
admission already prepares the source at the target size. Longer clips (the model's 10-15 s) are a later version.

## 5. Download list (downloaded and verified 2026-11-27)

Source: `https://huggingface.co/Lightricks/LTX-2.5` at revision `69ecadd4932572caf956135d41cbcdbd697aa442`. The gated
terms were accepted by the owner, not by an agent.

| File (repository path) | Bytes | Destination |
|---|---|---|
| `diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | 21,504,034,224 | ComfyUI models `diffusion_models` |
| `text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | 15,372,969,374 | ComfyUI models `text_encoders` |
| `vae/ltx-2.5-video-vae-bf16.safetensors` | 1,472,223,346 | ComfyUI models `vae` |
| `latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | 995,778,752 | managed ComfyUI `source\models\latent_upscale_models` |
| `vae/ltx-2.5-audio-vae-bf16.safetensors` | 364,866,540 | ComfyUI models `vae` |

Total **39,709,872,236 bytes (39.7 GB, 37.0 GiB)**. The first three and the last go to the desktop ComfyUI models
folders the managed runtime already searches. Its model-path file maps no `latent_upscale_models` folder, so the
upscaler goes into the managed install's own folder (under
`%LOCALAPPDATA%\StableNew\ManagedComfy\v0.38.0-py313`); a runtime reinstall would drop it. Not downloaded unless a
later version needs it: the convolutional VAE (1,452,269,922 bytes), the stage-1 fallback if the diffusion decoder does
not fit.

SHA-256, in table order:

```
c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334
6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f
847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3
eb5a71fe4068ee87ccdb1c3aa635e547ca76bd2d30ae20ae889f2c325c0677e8
c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5
```

How they were established: the Hub masks digests of a gated repository but publishes each file's Git LFS pointer id.
Each digest was read from a public copy and confirmed by rebuilding the pointer
(`version https://git-lfs.github.com/spec/v1`, `oid sha256:<digest>`, `size <bytes>`) and matching its Git blob id to
the official one. All five downloaded files matched their size and SHA-256 from this list.

## 6. Shared three-way comparison

Agreed with the VID-CAND-382 session on 2026-11-27: LTX-2.5 runs its own suites on the same images, prompts and seeds;
its comparison sheet goes in a separate folder; it stays off the GPU and the app until VID-CAND-382's stage 1 has
finished; its timings are labelled as measured in another session, with no speed ratio against A14B across sessions;
cases are joined only on equal image hash, prompt, negative prompt and seed, and VID-CAND-382's run folders are only
read. That agreement authorizes no LTX run.

Rules, thresholds, stop rules and budget are in `tools/qualification/vid_cand_ltx25/plan.py` and copied into the plan.

| LTX suite | Jobs | Seed | Cases |
|---|---|---|---|
| stage 0 smoke | 2 | 382 | two **different** VID-CAND-382 cases, cold then warm (VID-CAND-382's two identical smoke jobs returned a cached result) |
| stage 1 | 8 | 371 | VID-CAND-382 stage 1 cases, unchanged |
| stage 2 | 8 | 372 | VID-CAND-382 stage 2 hard cases, unchanged |
| audio | 4 | 371 | first four stage 1 cases plus one fixed sound sentence, audio workflow |

22 generations (cap 30), no automatic retry, 121 frames, RIFE off.

- **Rating:** `ratings.csv` per run (unchanged eval kit), then a blind sheet per stage built across runs:
  `threeway.csv` with names hidden, order shuffled from a recorded seed, and one ranking per dimension (fidelity,
  stability, motion), for example `B>A=C`. It takes up to four arms, so both Hunyuan step counts can be ranked.
- **Blindness limits:** resolution and frame rate can reveal an engine; and a case already rated with names visible is
  no longer blind. For a blind verdict, rank the three-way sheet **before** opening the VID-CAND-382 reports.
- **NO-GO:** any allocation failure or OOM; host commit >= 0.95; stage 1 action achieved below 6/8; more than one
  critical identity break; mean fidelity or stability below 4; or a 2+ point drop or a new break against A14B on 2+
  cases.
- **As good or better:** no NO-GO, stage 1 means within 0.25 of A14B, and LTX-2.5 ranked above A14B in at least half of
  the blind rankings.
- **Speed:** LTX-2.5's cold and warm times are reported as measured, with no cross-model verdict (orchestrator ruling,
  2026-11-27): it runs at 768x1344 against A14B's own size, and quality ranking comes first. No A14B re-run for speed
  in this package; if LTX-2.5 wins the blind ranking, a matched speed run is a follow-up with its own plan.
- **Audio:** reported, not gated (present, usable, in step with the motion, extra time and memory).
- **Recorded per job:** cold and warm wall time, VRAM, host commit and available RAM peaks, and failures.

## 7. Physical run plan (approved by the owner for non-explicit clips; not yet run)

Before any of it: the section 5 files present with matching SHA-256; VID-CAND-382 reports the GPU free; VID-FRAME's GPU
test, which is queued first, has finished; StableNew, Forge and ComfyUI closed; and a one-line go/no-go check to the
owner (relayed by the orchestrator session) before the run starts.

VID-CAND-382's stage 1 has run. Its stage 2 has not (it waits on the owner's choice of 8 or 12 steps), so the LTX stage 2
three-way sheet can be built only after it does.

1. **Offline, no GPU.** From a clean worktree at the accepted commit, build the suites and plan. This writes four new
   suite files into the owner's `<Output>\eval_plans\video` folder and a plan into a private folder; report the digest.

   ```powershell
   python -m tools.qualification.vid_cand_ltx25 build --stage1-suite <Output>\eval_plans\video\20261125_vidcand382_stage1_head_to_head_v001.suite.json --stage2-suite <Output>\eval_plans\video\20261125_vidcand382_stage2_hard_cases_hy8_v001.suite.json --suites-out <Output>\eval_plans\video --plan-out <private folder> --base-commit <sha>
   ```

2. **Runner.** A copy of VID-CAND-382's private operator runner with the LTX plan and stage names: production chain
   (preview, one submit, queue, `run_once`), a stage-local job database, outputs under `<Output>\video_eval`, a
   one-second memory and GPU sampler with naive-UTC timestamps (the verifier cannot read zoned ones). A dry preview
   first. Preflight: ComfyUI port free, `--disable-pinned-memory`, at least 10,000 MiB VRAM and 15 GiB RAM free, PCIe
   x16.
3. **GPU, in order, stopping at the first stop rule:** stage 0 (2 jobs) -> stage 1 (8) -> stage 2 (8) -> audio (4).
   After stage 0, go on only if both jobs completed and the clip decodes. Per-job budget 1500 s. Duration is
   **unmeasured**; expect 1-3 hours, and at most about 9 hours if every job used its whole budget.
   - **Stop rules:** device loss, allocation failure or any retry; commit >= 0.97, available RAM < 0.25 GiB or headroom
     < 1 GiB. The runner stops only a ComfyUI it launched. No settings change and no rerun within the frozen plan.
   - If stage 0 fails in the video decode, stop and report: the convolutional VAE is a new version and a new download.
4. **Offline.** Verify each run (identity, wall time, telemetry), build the blind sheets, report. The owner rates; an
   agent never fills a sheet.

   ```powershell
   python -m tools.qualification.vid_cand382 verify --run-dir <LTX run> --suite <LTX suite> --stage stage1 --plan <LTX plan> --jobs-db <stage jobs db> --telemetry <telemetry.json>
   ```

   ```powershell
   python -m tools.qualification.vid_cand_ltx25 threeway --source <382 stage 1 run> a14b_base --source <382 stage 1 run> hy15_8step --source <LTX stage 1 run> ltx25_distilled --seed 382 --out-dir <Output>\video_eval\vidcand_threeway_stage1
   ```

## 8. Acceptance and evidence boundary

| Category | What |
|---|---|
| Implementation | Spec module and registration, picker tier, `tools/qualification/vid_cand_ltx25`, this record, VIDEO_PIPELINE, CODEX_MAP, CODE_MAP and tools README entries |
| Demonstration | `tests/video/test_vid_cand_ltx25.py` and `tests/tools/test_vid_cand_ltx25_eval.py`: registry, opt-in, pins, graphs, probe, fake-Comfy runs, eval-kit admission, three-way sheet, all on synthetic data. Graph inputs were checked by reading the installed node sources; **the real ComfyUI has not validated either graph** |
| Qualification | None. No ledger entry |
| Held or unverified | All physical stages, ratings, and every value marked unmeasured |

## 9. Recommendation and smallest next step

LTX-2.5 stays a candidate for non-explicit work only, whatever its quality (section 1). The smallest next step that can
change the decision is stage 0: two jobs that show whether it loads and decodes on 12 GB, and how long it takes.
