# PR-VID-CAND-382: HunyuanVideo 1.5 candidate workflow and evaluation suite (record)

Status: **retired by the owner, 2026-11-28** (section 0). The workflows stay registered as `experimental`; nothing is
deleted. They are never the Make Video default, never preselected and not QUALIFIED. The sections after section 0 are the
record as written before any physical run. Work package: `docs/work_packages/VID-CAND-382_HunyuanVideo15_vs_A14B_Eval.md`.

## 0. Retirement, 2026-11-28

Owner decision (relayed by the orchestrator session): "Retire Hunyuan, close it".

- **Basis:** a blind three-way ranking on nine pictures (VID-CAND-LTX25 section 7) put the 8-step arm at a 0.37 share
  against A14B, "no clear case" by the rule fixed before that run; likeness and stability tied, A14B had better motion on
  eight of nine. In that run its later clips took a median 295 s against 127 s for A14B with standard attention, about 2.3
  times as long, at a different size and frame rate; the default now runs CK attention, which was not timed beside it.
- **Stage 1** had run and was scored by the owner before the decision: likeness and same-subject means 5.00 for all three
  arms; the requested action was achieved 5 of 8 times for A14B and 4 of 8 for each Hunyuan arm.
- **Stage 2 is not run.** Its pick sitting ("which step count should run?") was withdrawn unanswered.
- **Unchanged:** both workflow ids stay registered as `experimental` (offered only with Show experimental), the specs,
  eval tooling, suites, model files and results are all kept. Nothing was deleted.
- A return needs a new owner decision.

## 1. Package contract

- **Execution class:** Standard (one catalog spec module, eval-kit content, one read-only tool package; no controller, schema or
  safety-rule change).
- **Model recommendation:** Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High (`docs/AI_MODEL_SELECTION.md`).
- **Controller Surface Assessment:** no controller or coordinator file touched; no ratchet ceiling moved.
- **Token-efficient validation plan:** focused `tests/video/test_vid_cand_382_hunyuan15.py` and
  `tests/tools/test_vid_cand382_eval.py`, then the catalog/version-pin tests and `python tools/ci/run_pr_gate.py` from an isolated
  worktree, then `git diff --check`.
- **Base:** `origin/main` `7885a184` (the hand-off was written at `d8ea1c86`); branch `video/vid-cand-382-hunyuan15`.

## 2. Why the earlier NO-GO does not decide this candidate

`PR-VID-160A_Consumer_GPU_Motion_Candidate_Feasibility.md` (lines 163-169) classed HunyuanVideo-1.5 NO-GO on Gate C because the
official floor was 14 GB VRAM; `PR-VID-110_Directed_Motion_Qualification.md` (line 163) and the video roadmap
(`docs/audits/2026-10-20_video_experience_roadmap.md` line 150, decision D5 line 280) deferred it and tied a revisit to more RAM.
The WAN-BENCH-373 engine survey (`C:\Users\rob\qual\bench373\wan-video-research.html`, section "4 - Other engines", 21 Nov
2026) re-rated it "test first": the Comfy-Org repack of the **480p I2V step-distilled FP8** build is about 8.3 GB with a 9.4 GB
text encoder, runs 121 frames in 8-12 steps on stock ComfyUI nodes and is published as fitting 12 GB VRAM / 32 GB RAM. That is a
different artifact from the one 160A rejected, and the claim is unmeasured here. Stage 0 of the plan is what tests it.

## 3. The candidate (implementation)

`src/video/workflow_catalog_hunyuan15.py`, registered in `build_builtin_workflow_specs`. Two workflow ids, each `1.0.0`
`experimental`, identical except the sampler step count (`hunyuan_video15_i2v_480p_8step_v1`, `..._12step_v1`). They are two ids,
not two versions, so the picker never offers the newer step count as the entry and each keeps its own warm hold.

Graph (stock nodes only; all verified present in the managed ComfyUI 0.38.0 tree, rev `6b747c04`:
`comfy_extras/nodes_hunyuan.py` `HunyuanVideo15ImageToVideo`, `nodes.py` `DualCLIPLoader` with type `hunyuan_video_15`,
`CLIPVisionLoader`, `CLIPVisionEncode`): `UNETLoader` + `DualCLIPLoader` (Qwen2.5-VL 7B and ByT5 glyph) + `VAELoader` +
`CLIPVisionLoader` -> `CLIPVisionEncode` of the source image -> `HunyuanVideo15ImageToVideo` (positive, negative, start image,
vision output) -> one `KSampler` (Euler/simple, CFG 1, `denoise` 1.0, 8 or 12 steps) -> `VAEDecode` -> `SaveImage`. No
`ModelSamplingSD3` node: the model's own flow shift is 7.0 (`comfy/supported_models.py::HunyuanVideo15`). StableNew encodes the
lossless frames at the native 24 fps.

| File (under `split_files/`) | Loader input | Size (bytes) | SHA-256 (Hub LFS id) |
|---|---|---|---|
| `diffusion_models/hunyuanvideo1.5_480p_i2v_step_distilled_fp8_scaled.safetensors` | `UNETLoader.unet_name` | 8,335,127,098 | `30263626...63b1` |
| `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` | `DualCLIPLoader.clip_name1` | 9,384,670,680 | `cb5636d8...c0b4` |
| `text_encoders/byt5_small_glyphxl_fp16.safetensors` | `DualCLIPLoader.clip_name2` | 438,643,184 | `516910bb...fb48` |
| `vae/hunyuanvideo15_vae_fp16.safetensors` | `VAELoader.vae_name` | 2,521,292,758 | `e7c30919...97ae` |
| `clip_vision/sigclip_vision_patch14_384.safetensors` | `CLIPVisionLoader.clip_name` | 856,505,640 | `1fee501d...fb33` |

Source: Hugging Face `Comfy-Org/Hunyuan-Video-1.5` (formerly `Comfy-Org/HunyuanVideo_1.5_repackaged`, which still resolves) at
revision `1405a2b738c29b890cf6d03fc038d8d3e92eeed7` (Hub metadata read 2026-11-25; nothing downloaded). Full digests are in the
spec. Total about 21.5 GB on disk. Licence: the Tencent HunyuanVideo-1.5 community licence (Hub `license: other`) excludes the EU,
the UK and South Korea; the spec records that text.

Runtime policy, frozen but **unmeasured** (stage 0 replaces them in a new version): frames out at 24 fps, 17-121 frames (4n+1,
default 121 = 5.04 s, equal to A14B's 81 frames at 16 fps = 5.06 s); targets 480x848 / 848x480 (the node's native 480p bucket;
A14B runs 832x480, so Hunyuan carries 1.9 % more pixels, stated in the plan); `--disable-pinned-memory` (A14B's flag, kept so the
arms run in comparable processes); VRAM floor 9,500 MiB (above A14B's measured-footprint floor of 8,600), host RAM 16 GB advisory,
history timeout 1200 s, keep-warm 120 s, per-job opt-in. Besides the stock-node and file checks the dependency probe requires
that `DualCLIPLoader.type` offers `hunyuan_video_15` and that `HunyuanVideo15ImageToVideo` accepts `clip_vision_output`, so an
older runtime refuses before dispatch instead of mis-conditioning.

## 4. Evaluation design (frozen in the plan; built by `tools/qualification/vid_cand382`)

Fairness rules, thresholds, stop rules and budget are written into `tools/qualification/vid_cand382/plan.py` and copied into
the plan JSON (`stablenew.vid-cand-382-plan.v1`). Summary:

| Stage | Suite (canonical name, under `<Output>/eval_plans/video/`) | Jobs | Seed | Design |
|---|---|---|---|---|
| 0 smoke | `20261125_vidcand382_stage0_smoke_v001` | 2 | 382 | One CLIP-371 case x Hunyuan 8-step, two jobs: first is cold, second warm. Measures load, completion, VRAM and commit; sets the floor |
| 1 head-to-head | `20261125_vidcand382_stage1_head_to_head_v001` | 24 | 371 | The 8 CLIP-371 structured cases x {A14B 1.0.0 (81 f), Hunyuan 8-step, Hunyuan 12-step (121 f)} |
| 2 hard cases | `..._stage2_hard_cases_hy8_v001` / `..._hy12_v001` | 16 | 372 | Eight full-body sources: five CLIP-371 stage 2 actions plus hands interacting, two-step action and fast turn, x {A14B, the Hunyuan arm the owner names after stage 1}. Both suites are pre-frozen so one digest each exists whichever arm wins |

Frozen on 2026-11-25 against `origin/main` `7885a184`: the four suites sit in the main checkout's `output/eval_plans/video/` (gitignored,
private images) and the plan in the private qual folder (`vid_cand382/vid_cand_382_plan.v1.json`); plan digest
`d6de57f1849a65500b191a2cb9e00f2d871a060b5b5ce20aadb0136509e565d6` (SHA-256 of the canonical JSON; `digest12` `d6de57f1849a`).
Stage 1 reuses the eight CLIP-371 structured cases unchanged (same image, hash, prompt and negative prompt). No authorization exists.

Budget: 42 generations (2 + 24 + 16), cap 60, no automatic retry. Arms run arm-major, so the first job of each arm is a cold start and
the rest are warm; speed is compared warm to warm and cold to cold.

- **NO-GO:** any allocation failure/OOM; host commit >= 0.95; stage-1 action achieved (achieved or partially) below 6/8; more than
  one critical identity break; mean fidelity or stability below 4; or a drop of 2+ points on fidelity/stability, or a break A14B
  lacks, on 2+ cases.
- **As good or better:** no NO-GO, stage-1 means (fidelity, stability, action score) no more than 0.25 below A14B, and stage-2 blind
  pairwise preference for Hunyuan >= 50 % (ties split).
- **Faster:** warm wall-time median <= 0.8 x A14B's, same host session.
- **Stop rules:** device loss, allocation failure or any retry; commit >= 0.97, available RAM < 0.25 GiB or headroom < 1 GiB; an arm that
  cannot be admitted. No settings downgrade after a resource failure inside a frozen plan.
- **Ceiling effect:** A14B saturated ratings at 5/5 in VID-CLIP-371, so stage 2 adds a blind pairwise sheet (`pairwise.csv`, three
  dimensions, A/B/tie, arm order shuffled from a recorded seed, clips copied to neutral names). `ratings.csv` is unchanged. The helper
  is under `tools/` because it exceeds the 150-line bound for `src/video/`.

Commands (all offline; none queues, starts a runtime, downloads or authorizes):

```powershell
python -m tools.qualification.vid_cand382 build --stage1-suite <clip371 stage 1> --stage2-suite <clip371 stage 2> --suites-out <Output>\eval_plans\video --plan-out <private folder> --base-commit <sha>
python -m tools.qualification.vid_cand382 verify --run-dir <Output>\video_eval\<run_id> --suite <suite file> --stage stage1 --plan <plan> --jobs-db state\jobs.sqlite3 [--ratings F] [--telemetry F]
python -m tools.qualification.vid_cand382 pairwise --run-dir <run dir> --candidate-arm hy15_8step --seed 382
python -m tools.qualification.vid_cand382 score-pairwise --sheet <run>\pairwise.csv --key <run>\pairwise_key.json
```

`verify` reproduces the VID-CLIP-371 `verify_s2.py` checks (suite digest, seed, job count, workflow id/version, frozen prompt, negative
prompt, frame count and runtime identity per clip) over a read-only job repository, splits wall time cold/warm per arm, reads the
owner's ratings and an optional telemetry sample file, and applies the thresholds. It was run read-only against the VID-CLIP-371
stage 2 run: every check passed, A14B wall times matched the recorded 140-176 s. Anything not evidenced (no telemetry, no ratings)
is reported as such, never passed. The sample telemetry file format is `{"samples": [{"time" (ISO), "commit_fraction", "available_ram_gb",
"vram_used_mib"}]}` (peaks are reported overall and, from `time`, per arm window); the eval kit itself records none, so the sitting must capture it (for example with the WAN-BENCH-373 sampler).

The shareable synthetic examples are `docs/runbooks/examples/video_eval_hunyuan15_stage{0_smoke,1_head_to_head,2_hard_cases}.suite.json`
(`docs/runbooks/video_eval_kit.md` section 11); the real suites use the owner's private images and live only in the Output plan folder.

## 5. Evidence

| Category | What |
|---|---|
| Implementation | Spec module and registration; example suites; `tools/qualification/vid_cand382` (plan, verify, pairwise, CLI); VIDEO_PIPELINE 1.1/4.2; CODEX_MAP; tools README |
| Demonstration | `tests/video/test_vid_cand_382_hunyuan15.py` (registry, opt-in refusal, picker default unchanged, pins, graph, probe, fake-Comfy run, readiness, example previews of 24 jobs) and `tests/tools/test_vid_cand382_eval.py` (design, builder, verifier, pairwise), all on synthetic data and a fake Comfy |
| Qualification | None. No ledger entry; the spec says NOT QUALIFIED |
| Held or unverified | Everything in section 7; the sampler values, VRAM floor, launch-flag need, VAE-decode memory (stock `VAEDecode`, no tiled decode) and keep-warm grace are untested on the host |

## 6. Not touched

The A14B spec and the picker default, `presets/settings.json`, any controller or schema, ComfyUI or its custom nodes, and every
downloaded model (none exists locally).

## 7. Held for the owner (closed by section 0)

1. **Licence acceptance** for HunyuanVideo 1.5 on this host and **the download** of the five files in section 3 (about 21.5 GB) to
   the managed Comfy `diffusion_models`, `text_encoders`, `vae` and `clip_vision` folders.
2. **Each physical stage:** the plan digest, then the owner's typed `RUN <digest12>` (or the eval-kit equivalent the owner names).
   An agent never issues it. Stage 2 needs the owner's choice of 8 or 12 steps after stage 1.
3. **Ratings** (`ratings.csv`) and the **pairwise sheet**. An agent never fills them.
4. **Any promotion** (`approved` alternate or default): an owner decision under VIDEO_PIPELINE section 13; this package reports a
   verdict only.
