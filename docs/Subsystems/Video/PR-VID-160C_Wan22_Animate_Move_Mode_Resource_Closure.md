# PR-VID-160C — Wan2.2-Animate True Move-Mode Resource Closure

Status: **COMPLETE / RESOURCE GATE CLOSED — `MOVE_MODE_RESOURCE_PASS_32GB`** (commit-aware
adjudication; supersedes the interim `MOVE_MODE_RESOURCE_NO_GO_RAM` reading from the first run's
physical-RAM-only guard — see "Adjudication" below). This is a qualification-only
resource-feasibility probe. It adds no production `src/` change, no backend, no queue/history
authority, and no Wan production graph/settings change. Start
`main @ a4d27fe539520076b25f393a023d60150d53e3d3`.

## Outcome asked

Can the already-proven Wan2.2-Animate-14B Q3_K_M configuration complete one small generation with
an actual `pose_video` supplied to `WanAnimateToVideo`, without exceeding RTX 4070 Ti 12-GB VRAM /
32-GB RAM limits, triggering the safety stop, losing the GPU, or violating runtime ownership?

**Yes, on adjudication.** This package ran the identical pose-driven configuration **twice**.

**Run 1** (below, unchanged/preserved) was safety-stopped by a coarse guard: available *physical*
RAM dropped to 0.77 GB (below a frozen 1.0 GB threshold) for two consecutive samples, and the tool
correctly, cleanly interrupted its own prompt. That proved the guard fired as designed; it did
**not** by itself prove Windows/Comfy could not have completed with 32 GB RAM, because Windows
reports reclaimable standby-cache pages as "unavailable" the same way it reports genuinely
committed memory, and low physical availability alone does not establish virtual-memory (commit)
exhaustion.

**Run 2**, the commit-aware adjudication authorized by this continuation, resubmitted the
byte-identical graph/assets/settings with Windows-native system-commit telemetry added and the
coarse physical-RAM-only abort replaced by a commit-aware rule (physical RAM demoted to a warning
signal only). Run 2 **completed successfully**: valid output, no safety stop of any kind (physical
RAM never even fell below the original 1.0 GB warning threshold this time), system commit peaked at
only 69.1% of a 63.76 GB commit limit with 19.71 GB of commit headroom remaining throughout, no CUDA
OOM, no GPU loss, clean teardown. This closes PR-VID-160B's open resource gate with a favorable
answer for this exact envelope: **`MOVE_MODE_RESOURCE_PASS_32GB`**. See "Adjudication" below for
the full commit-aware evidence and the Run 1 vs Run 2 comparison.

## Inherited PR-VID-160B baseline (reused unchanged)

- Sub-finding: `ANIMATE_BACKBONE_RESOURCE_FLOOR_PASS`.
- Model: `Wan2.2-Animate-14B-Q3_K_M.gguf` (`QuantStack/Wan2.2-Animate-14B-GGUF@33c51bb8`), staged
  unchanged, byte-identical to PR-VID-160B (verified present, same size, before dispatch).
- Reused unchanged: `clip_vision_h.safetensors`, existing `umt5_xxl_fp8_e4m3fn_scaled.safetensors`,
  existing `wan_2.1_vae.safetensors`, installed `ComfyUI-GGUF` (`6ea2651e`), existing Comfy
  environment, existing `ComfyProcessManager`, PR-VID-160B's `ProbeResourceSampler` telemetry and
  safety-stop logic (imported directly, not reimplemented), the same reference image
  (`reports/vid110/inputs/source_fullbody.png`), and seed `1733123036`.
- No quant switch, no redownload, no dimension/frame/step increase.

## Phase A — local `WanAnimateToVideo` pose semantics (re-verified against the installed file)

Re-read `comfy_extras/nodes_wan.py` in the exact same installed ComfyUI 0.3.65 (unchanged since
PR-VID-160B; no upstream update occurred):

- `pose_video` is `io.Image.Input(..., optional=True)` — a plain `IMAGE` batch tensor, exactly
  like `reference_image`/`face_video`/`background_video`.
- Resize/crop: `comfy.utils.common_upscale(pose_video[:length].movedim(-1,1), width, height,
  "area", "center").movedim(1,-1)` — same "area" interpolation, center-positioned, as the
  reference-image path.
- Frame-count behavior: truncates to at most `length` frames; if fewer than `length` remain after
  truncation, **pads by repeating the last frame** (`torch.cat` with `(pose_video[-1:],) *
  (length - pose_video.shape[0])`) rather than erroring. A pose clip with exactly `length` frames
  (this package's case) needs no padding.
- `pose_video` is **fully independent**: its own `if pose_video is not None:` block, no coupling to
  `face_video`, `character_mask`, `background_video`, or `continue_motion`. Confirmed no hidden
  companion input is required when `pose_video` is present alone.
- `face_video` remains **independently optional** in the installed revision, confirmed by its own
  separate `if face_video is not None:` block.
- Compute-cost detail material to this package's result: supplying `pose_video` adds a **second
  VAE-encode pass** (`vae.encode(pose_video[:, :, :, :3])`, on top of the reference-image encode
  already present in the backbone graph) and attaches the resulting `pose_video_latent` as an
  additional resident conditioning tensor on both `positive` and `negative`. This is exactly the
  additional cost PR-VID-160B could not measure by omitting `pose_video`.

No hidden dependency requirement was found. No environment mutation was needed for the node itself.

## Phase B — pose asset: reused and deterministically adapted, no new dependency

**Source (reused, not regenerated):** `reports/vid110/inputs/pose_user.mp4` — an already-accepted,
skeleton-on-black control clip from PR-VID-110's pose-skeleton-only lane (MediaPipe pose,
strength 0.7). 480x832, 24 fps, 49 frames, no RGB scene/background imagery (confirmed visually via
the existing `pose_sheet.png` contact sheet: colored skeleton lines on a fully black background).

**Adaptation (deterministic, `tools/qualification/vid160c/pose_asset.py`, OpenCV/numpy only —
already installed in the project venv, no new package):**

1. Decode all 49 source frames.
2. Select exactly 13 frames via evenly spaced indices (`numpy.linspace(0, 48, num=13)`; identical
   sampling convention to `tools.qualification.vid110.metrics.contact_sheet`).
3. Center-crop each selected frame to a square (480x480, since source width 480 < height 832).
4. Resize to 256x256 with `cv2.INTER_AREA`.
5. Write to `reports/vid160c/pose_control_256x256_13f.mp4` (mp4v, 8 fps container metadata; frame
   *count*, not container fps, is what `WanAnimateToVideo` consumes).

**Frozen asset record:**

| Field | Value |
|---|---|
| Source | `reports/vid110/inputs/pose_user.mp4` (reused, unmodified) |
| Original frames | 49 (480x832, 24 fps) |
| Final frames | **13** |
| Final dimensions | **256x256** |
| `ffprobe` confirmation | `codec_name=mpeg4, width=256, height=256, r_frame_rate=8/1, nb_frames=13` |
| SHA-256 | `1517b9daef601b264f6841154e09306d63e44e4ec6f0f63a4b86aad5bc981e8f` |
| Contact sheet | `reports/vid160c/pose_control_contact_sheet.png` (visually confirmed: skeleton-on-black, clearly changing leg/hip articulation across all 13 frames — a hip-hinge motion sequence, not a static or duplicated pose) |

No MediaPipe, DWPose, `comfyui_controlnet_aux`, KJNodes, SAM2, VideoHelperSuite, or any other new
model/package/environment was installed to produce this asset. No post-adaptation changes were made
before the physical run.

## Phase C — control-asset freeze confirmation

- Contains genuine pose motion: confirmed (contact sheet inspection above).
- No face/background/control branch added: confirmed — only `pose_video` is wired; `face_video`,
  `background_video`, `character_mask` remain absent from the graph (Phase D, and asserted by
  `tests/tools/test_vid160c_qualification.py`).
- Frozen before dispatch; unchanged after.

## Phase D — qualification-tool extension

`tools/qualification/vid160c/` — reuses PR-VID-160B tooling rather than duplicating it:

- `pose_asset.py` — the deterministic adaptation above (new, qualification-only).
- `graph.py` — `build_pose_probe_graph()` imports the frozen model-file constants
  (`UNET_GGUF_FILENAME`, `CLIP_FILENAME`, `VAE_FILENAME`, `CLIP_VISION_FILENAME`) directly from
  `tools.qualification.vid160b.graph` rather than redefining them, and reproduces the exact
  PR-VID-160B backbone graph plus two additional stock nodes: `LoadVideo` (`file` = the staged pose
  clip) → `GetVideoComponents` (output `images`) → wired into `WanAnimateToVideo.pose_video`.
  `LoadVideo`/`GetVideoComponents` are the same already-accepted stock nodes
  `tools/qualification/vid110/workflows.py` uses for its VACE control-video lanes — no new custom
  node. `validate_graph()` additionally asserts `pose_video` is present and wired to node 17, and
  that `face_video` is absent.
- `run.py` — imports `preflight`, `_Stack`, `_teardown` directly from `tools.qualification.vid160b.run`
  (unchanged), and `ProbeResourceSampler` directly from `tools.qualification.vid160b.telemetry`
  (unchanged safety-stop thresholds). Adds only `stage_pose_video()`, a plain filesystem copy of the
  frozen pose clip into the Comfy-configured `input/` directory (parsed from the same
  `--base-directory` launch argument `build_default_comfy_process_config` already sets) — the
  reused `ComfyClient` has no dedicated video-upload HTTP helper, so this mirrors the existing
  direct-filesystem-staging pattern already used for the model assets. Submits exactly one prompt;
  no retry loop; releases only the Comfy process its own manager owns; writes
  `reports/vid160c/evidence.json` even on exception.

**Graph delta versus PR-VID-160B, exactly:** two added nodes (`LoadVideo`, `GetVideoComponents`)
and one changed input (`WanAnimateToVideo.pose_video` now wired instead of absent). Every other
node, filename, and setting is identical.

## Phase E — deterministic validation before GPU work

`tests/tools/test_vid160c_qualification.py` — **22 passed**: pose_video present and correctly wired
to `GetVideoComponents`; `face_video`/`background_video`/`character_mask` never present; frozen
spec fields (`width`, `height`, `length`, `steps`, `cfg`, `shift`, `seed`, `sampler`, `scheduler`)
asserted identical to PR-VID-160B's `ProbeSpec`; frozen model-file constants asserted identical;
dimension/length validation; pose-asset frame-sampling determinism (`sample_indices` reproducible,
bounded, sorted) and square-crop geometry; external-runtime refusal; dry-run non-submission;
exactly-one-attempt with no automatic retry; partial-evidence-preservation-and-teardown on
exception; owned-vs-unowned process cleanup; safety thresholds (`LOW_RAM_GB=1.0`,
`LOW_RAM_CONSECUTIVE=2`, `HIGH_SWAP_PERCENT=90.0`) asserted unchanged from PR-VID-160B;
pose-video staging copies without mutating the source and requires `--base-directory`. Ruff clean.
`git diff --check` clean.

## Phase F — pre-run physical gate

Immediately before dispatch: GPU 1,808 MiB / 12,282 MiB used, 0% utilization (idle); no A1111
process; no external Comfy process; `nvidia-smi`/`tasklist` showed no lingering
Comfy/Python/StableNew process; Comfy endpoint unreachable (never launched this session, confirming
no external adoption risk); no DIAG-GPU-120 event since PR-VID-160B; staged model assets reverified
present and byte-size-unchanged; pose asset frozen and unchanged; graph frozen; safety thresholds
unchanged (reused, not modified). All conditions met; dispatch proceeded (no deferral needed).

## Phase G — safety thresholds (reused unchanged)

Identical to PR-VID-160B, imported directly rather than reimplemented: available RAM < 1.0 GB for
2 consecutive samples → stop; swap ≥ 90% while RAM also < 1.0 GB → stop; CUDA OOM / Comfy
allocation failure → fail; GPU-lost/black-screen/max-fan → stop immediately; only the owning
`ComfyProcessManager` may interrupt/stop. Not loosened, not tuned, not retried.

## Phase H — one true pose-driven physical attempt

**Submitted, exactly once.** `prompt_id=370f9fca-c626-41c2-962c-33e5c3e900e8`.

| Field | Value |
|---|---|
| Frozen spec | Q3_K_M, ref image, seed 1733123036, 256x256, 13 frames, 8 fps, 4 steps, cfg 5.0, shift 8.0, uni_pc/simple — identical to PR-VID-160B, plus `pose_video` |
| Wall time | 30.2 s (interrupted, not a completed run) |
| VRAM baseline / observed peak | 1,972 MiB / 10,646 MiB (observed at interruption — **not** a true completed-run peak; see Phase I) |
| Host RAM available, minimum | **0.77 GB — below the 1.0 GB stop threshold** |
| Swap used, peak | 1.32 GB (3.9%) |
| Temperature, peak | 61 °C |
| Power, peak | 172.25 W |
| Stop reason | `"available RAM < 1.0 GB for 2 consecutive samples (last=0.77 GB)"` |
| Comfy execution status | interrupted by the qualification tool's own safety guard (`ComfyClient.interrupt_own`), not a Comfy-side error |
| Output existence | **none** — generation did not reach completion, so no video was produced (expected and correct given the interruption) |
| Owned-runtime teardown | clean: `managed_comfy_owned: true`, `teardown_errors: []` |
| Post-run GPU/process state | GPU returned to 1,811 MiB / 12,282 MiB, 0% utilization (matches pre-run baseline); no lingering Comfy/Python process; host free RAM recovered to ~18.05 GB (`FreePhysicalMemory` 18,924,528 KB) — confirming the RAM pressure was load-transient, not a leak |

No CUDA OOM occurred (the host-RAM gate tripped first). No GPU-lost/black-screen/max-fan signature.
No retry was attempted.

## Phase I — 160B → 160C resource delta (what did adding `pose_video` cost?)

| Metric | PR-VID-160B (no pose_video) | PR-VID-160C (pose_video added) | Delta |
|---|---|---|---|
| Result | completed | safety-stopped | — |
| VRAM baseline | 1,563 MiB | 1,972 MiB | +409 MiB (baseline, before generation) |
| VRAM peak *observed* | 11,396 MiB (completed run) | 10,646 MiB (interrupted run) | **not comparable** — 160C's figure is a peak-at-interruption, not a completed-run peak; the true Move-mode VRAM peak, had the run been allowed to continue, is unknown and plausibly higher given the extra `pose_video_latent` conditioning tensor and encode pass |
| Host RAM minimum available | 4.7 GB | **0.77 GB** | **−3.93 GB** — the decisive, comparable finding |
| Swap peak | 5.4% (1.85 GB) | 3.9% (1.32 GB) | lower — RAM depletion, not swap pressure, is what tripped the stop rule's first branch |
| Wall time | 30.4 s (completed) | 30.2 s (interrupted) | not comparable — similar elapsed time but different outcome |
| Temperature peak | 59 °C | 61 °C | +2 °C |
| Power peak | 209.06 W | 172.25 W | −36.8 W — plausibly because the interruption landed during a lower-intensity phase (e.g. the additional VAE encode / video decode, before the sampler reached its own peak draw) |
| Stability outcome | clean completion | clean interruption, clean teardown, full recovery | both stable; no crash in either |

**Conclusion of the comparison:** the single clearly comparable, decisive number is host RAM —
adding `pose_video` (a second VAE-encode pass, a second video decode via `LoadVideo`, and an
additional resident conditioning tensor) drove available host RAM from a comfortable 4.7 GB minimum
down to 0.77 GB, crossing the safety threshold before generation could complete. VRAM and wall-time
comparisons are not meaningful because the run did not reach completion. This is not a quality
judgment — no identity, locomotion, or output-quality claim is made or possible, since no output
was produced.

## Run 1 interim classification (superseded — see Adjudication below)

**`MOVE_MODE_RESOURCE_GUARD_TRIGGERED`** (originally recorded as `MOVE_MODE_RESOURCE_NO_GO_RAM`;
relabeled on product-owner review, evidence unchanged).

The host-memory safety-stop rule tripped during Run 1's one attempt: available *physical* RAM fell
below the frozen 1.0 GB threshold for two consecutive samples, and the tool correctly interrupted
its own prompt. This proved the guard fired exactly as designed. It did **not** by itself prove
Windows/Comfy could not complete with 32 GB RAM: `psutil`-reported available physical RAM includes
reclaimable standby-cache pages, and Microsoft's own guidance treats system *commit* (virtual
memory: RAM + pagefile) versus the commit limit as the more meaningful exhaustion signal. Run 1's
own telemetry is consistent with either "the guard was protective but premature" or "32 GB is
genuinely insufficient" — both were compatible with the observed swap usage (only 1.32 GB / 3.9%,
not spiking towards the pagefile ceiling) and the interruption landing almost exactly when the
prior completed run (PR-VID-160B) normally finished. **This package's own thresholds had not yet
distinguished those two hypotheses; the Adjudication below does.**

All Run 1 telemetry, evidence, and the original Phase A-I content above remain unmodified and are
preserved as the historical first-attempt record; nothing above this section was rewritten.

## Adjudication — commit-aware retest (Run 2)

Authorized as a direct continuation of this same package (an adjudication of the same acceptance
question, not a new product objective), because Run 1 left genuine ambiguity between "the guard
was conservative" and "32 GB is the real ceiling." Exactly one additional physical submission was
authorized and used; the exact Run 1 graph/assets/settings were reused unchanged, and only the
telemetry depth and the safety-decision rule were replaced.

### Adjudication Phase A — Windows commit telemetry (new)

`tools/qualification/vid160c/win_memory.py` — a small `ctypes`-only module (no new dependency)
reading:

- **System-wide**, via `GetPerformanceInfo`/`PERFORMANCE_INFORMATION` (psapi.dll): `CommitTotal`,
  `CommitLimit`, `CommitPeak`, page size, converted to commit-total/limit/peak GB, derived commit
  headroom (`limit - total`) and commit percentage. `GlobalMemoryStatusEx`-equivalent physical
  totals are read from the same structure (`PhysicalTotal`/`PhysicalAvailable`).
- **Per the owned Comfy process**, via `OpenProcess` (no admin privileges: only
  `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ`) and `GetProcessMemoryInfo`: attempts
  `PROCESS_MEMORY_COUNTERS_EX2` first (adds `PrivateWorkingSetSize`/`SharedCommitUsage`) and falls
  back cleanly to `PROCESS_MEMORY_COUNTERS_EX` (`WorkingSetSize`, `PeakWorkingSetSize`,
  `PrivateUsage`, `PagefileUsage`, `PeakPagefileUsage`) when EX2 is unavailable, returning `None`
  rather than raising if the process cannot be opened.

Sanity-checked against the live machine before use: baseline commit limit **63.76 GB** (physical
RAM 31.76 GB + a pagefile of roughly the same size again), baseline commit headroom **45.43 GB** at
idle — confirming meaningful virtual-memory capacity beyond physical RAM alone exists on this
machine, which is exactly the capacity Run 1's physical-RAM-only guard could not see. EX2 fields
populated correctly on this Windows/Python combination (no fallback needed at runtime; the fallback
path is still unit-tested).

`tools/qualification/vid160c/telemetry.py` (new; does **not** modify PR-VID-160B's
`ProbeResourceSampler`, which produced Run 1's evidence unchanged) — `CommitAwareResourceSampler`
adds these fields to every ~0.5 s sample, retaining all original fields (VRAM, temperature, power,
utilization, available physical RAM, swap): system commit total/limit/headroom/percent, and the
owned Comfy process's working-set and private-usage peaks. Flushed per row.

### Adjudication Phase B — Comfy memory policy (read-only, unchanged)

Configured launch command inspected directly: no `--lowvram`, `--novram`, `--highvram`,
`--gpu-only`, `--disable-smart-memory`, or custom `--reserve-vram`/VRAM-headroom flag was present
for Run 1, Run 2, or the original PR-VID-160B run — Comfy's default automatic ("smart") memory
management was used identically in all three runs. Not changed for this adjudication.

### Adjudication Phase C — revised safety policy (frozen before execution)

The original Run 1 rule (`available RAM < 1.0 GB` for 2 consecutive samples) is now recorded as a
**warning marker only** (`WARN_RAM_GB = 1.0`, tracked as `warn_ram_low_seen`) and no longer aborts
by itself. The frozen commit-aware abort rule (any one condition, each requiring
`CONSECUTIVE_SAMPLES = 2`):

1. system commit ≥ `COMMIT_PERCENT_ABORT = 97.0`% of commit limit; OR
2. system commit headroom < `COMMIT_HEADROOM_ABORT_GB = 1.0` GB; OR
3. available physical RAM < `EMERGENCY_RAM_GB = 0.25` GB (an emergency responsiveness floor,
   independent of commit); OR
4. CUDA OOM / Comfy allocation failure (surfaced by the Comfy HTTP client, unchanged); OR
5. GPU-lost/black-screen/max-fan (surfaced by the GPU sampler's own failure to reach `nvidia-smi`,
   unchanged).

Pagefile size was not altered, not disabled, and thresholds were not adjusted after seeing live
telemetry. The baseline commit-limit check (Phase F) found nothing unusually low, so no pre-run
stop was warranted.

### Adjudication Phase D — experiment controls (identical to Run 1)

`tools/qualification/vid160c/adjudicate.py` (new) reuses `tools.qualification.vid160c.graph`
entirely unchanged (same `PoseProbeSpec` defaults, same `build_pose_probe_graph`) and
`tools.qualification.vid160c.run.stage_pose_video`/`REQUIRED_NODE_CLASSES` plus
`tools.qualification.vid160b.run.preflight/_Stack/_teardown` directly. The only substitution is the
sampler (`CommitAwareResourceSampler` in place of `ProbeResourceSampler`). Same Q3_K_M transformer
(byte-identical file, reverified present before dispatch), same text encoder/VAE/CLIP Vision, same
reference image, same pose asset (**SHA-256 reverified unchanged**:
`1517b9daef601b264f6841154e09306d63e44e4ec6f0f63a4b86aad5bc981e8f`), no `face_video`, 256×256, 13
frames, 8 fps, 4 steps, same seed/CFG/shift/sampler/scheduler, same Comfy runtime configuration. No
graph optimization, no quant change, no workload size change.

### Adjudication Phase E — deterministic validation

`tests/tools/test_vid160c_commit_adjudication.py` — **15 passed**: Windows commit-metric conversion
(pages→GB, derived headroom/percent) against synthetic `PERFORMANCE_INFORMATION` bytes;
`GetPerformanceInfo` failure raises `OSError`; EX2→EX fallback (including "process cannot be
opened" → `None`, never raises); the exact Run 1 regression case — **0.77 GB available physical RAM
alone, with healthy commit headroom, must NOT trigger the new guard** (asserted directly); the 97%
commit-percent two-sample trigger; the commit-headroom-below-1GB two-sample trigger (isolated with
a small synthetic commit limit, since on this machine's real ~64 GB limit the two conditions are
mathematically coupled and always fire together); the 0.25 GB emergency-floor trigger, independent
of commit; frozen-threshold regression assertions; exactly-one-additional-submission with no retry;
external-runtime refusal; evidence persistence on exception; owner-only teardown. Combined with the
reused PR-VID-160B/first-160C suites: **53 tests passed**. Ruff clean. `git diff --check` clean.

### Adjudication Phase F — pre-run physical gate

Immediately before dispatch: GPU 681 MiB / 12,282 MiB, 0% utilization (idle, cooler than Run 1's
1,808 MiB baseline); no A1111/external Comfy/StableNew process running; Comfy endpoint unreachable
(not yet launched); no DIAG-GPU-120 event since Run 1; staged model assets reverified byte-size
unchanged; pose asset SHA-256 reverified unchanged; commit baseline healthy (63.76 GB limit, 45.43
GB headroom, 28.76% used — not unusually low); graph and thresholds frozen. All conditions met; no
deferral needed.

### Adjudication Phase G — the one additional physical attempt

**Submitted, exactly once.** `prompt_id=4a581195-7a0e-48c6-9e06-dd0efc803eda`.

| Field | Value |
|---|---|
| Comfy PID | 13704 |
| Comfy memory flags | none (confirmed default/auto, same as Run 1 and PR-VID-160B) |
| Baseline commit (pre-dispatch) | total 21.84 GB / limit 63.76 GB / headroom 41.92 GB / 34.25% / physical available 19.24 GB |
| Wall time | **33.4 s (completed)** |
| VRAM baseline / peak | 852 MiB / **10,684 MiB** (a true completed-run peak, unlike Run 1's interrupted reading) |
| Host RAM available, minimum | 2.95 GB — never crossed even the original 1.0 GB warning threshold (`warn_ram_low_seen: false`) |
| System commit total, peak | **44.06 GB** (of 63.76 GB limit) |
| System commit percent, peak | **69.09%** (well below the 97% abort) |
| System commit headroom, minimum | **19.71 GB** (well above the 1.0 GB abort) |
| Comfy process working-set / private-usage peak | 0.0 / 0.0 GB — **instrumentation gap** (see Limitations); the owned-process PID read returned near-zero values inconsistent with a real 8+ GB GGUF transformer process, most likely a PID/handle-lifetime issue in this new per-process sampling path. Does **not** affect the decisive system-wide commit/headroom/percent figures above, which use an independently verified code path (sanity-checked against this same live machine in Phase A) |
| Swap used, peak | 0.91 GB (2.7%) |
| Temperature, peak | 57 °C |
| Power, peak | 210.9 W |
| Stop reason | none — no abort condition fired |
| Comfy execution status | completed normally |
| Output validity | valid: `ffprobe` confirms H.264, 256×256, 8 fps, exactly 13 frames, matching the frozen spec; a middle frame is coherent (a bent/hip-hinge pose consistent with the pose-control clip's motion), not corrupted/noise — no identity/locomotion/quality claim is made |
| Owned-runtime teardown | clean: `managed_comfy_owned: true`, `teardown_errors: []` |
| Post-run recovery | GPU returned to 681 MiB / 12,282 MiB, 0% utilization (matches pre-run baseline exactly); no lingering Comfy/Python process |

No CUDA OOM, no Comfy allocation failure, no GPU-lost/black-screen/max-fan signature. No retry.

### Optional post-result phase attribution (no third generation; observed timestamps only)

Reading the persisted telemetry time series (`reports/vid160c/adjudication/telemetry.csv`):
roughly t=0–10 s shows commit fluctuating 24–40 GB with VRAM still low (852–2,186 MiB) — model/text
-encoder staging and loading; t=10.5–15 s shows VRAM ramping to ~9.5 GB as the transformer loads;
a VRAM dip and reclimb around t=15.5–23 s (1,682→9,074 MiB) is consistent with the pose-video VAE
encode/conditioning-tensor phase (the additional cost PR-VID-160B's backbone-only run never
exercised); the sustained high-VRAM plateau (~10.2–10.7 GB) with GPU utilization at 94–100% and
rising temperature/power from t≈24–32 s is the `KSampler` denoise loop; commit's true peak
(44.06 GB) lands inside that same plateau, consistent with the transformer weights, text encoder,
VAE, and the `pose_video_latent` conditioning tensor all being resident simultaneously during
denoising. No second generation was run to refine this attribution further.

### Adjudication classification

**`MOVE_MODE_RESOURCE_PASS_32GB`**

Every PASS condition was met: the identical pose-driven generation completed with valid output; no
allocation failure; no commit-aware safety stop of any kind; no GPU loss; clean owned-runtime
teardown. Resource margin, recorded honestly: minimum physical RAM available 2.95 GB (never even
approached Run 1's original 1.0 GB warning line), minimum commit headroom 19.71 GB against a 63.76
GB limit, peak commit usage 69.1% — comfortably clear of every abort threshold in the revised rule.
Low available *physical* RAM alone does not prohibit this classification, because meaningful
Windows commit headroom remained throughout.

## Run 1 vs Run 2 — explicit comparison (both results preserved, neither deleted)

| | Run 1 (original, physical-RAM-only guard) | Run 2 (commit-aware adjudication) |
|---|---|---|
| Classification | `MOVE_MODE_RESOURCE_GUARD_TRIGGERED` (a guard trigger, not a proof of exhaustion) | **`MOVE_MODE_RESOURCE_PASS_32GB`** |
| Result | safety-stopped before completion | **completed**, valid output |
| Available physical RAM, minimum | 0.77 GB (2 consecutive samples < 1.0 GB) | 2.95 GB (never < 1.0 GB) |
| System commit peak / limit | not measured (telemetry did not exist yet) | 44.06 GB / 63.76 GB (69.1%) |
| System commit headroom, minimum | not measured | 19.71 GB |
| Swap peak | 1.32 GB / 3.9% | 0.91 GB / 2.7% |
| VRAM peak | 10,646 MiB (at interruption, not a completed-run peak) | 10,684 MiB (a true completed-run peak) |
| Wall time | 30.2 s (interrupted) | 33.4 s (completed) |
| Comfy memory flags | default/auto (unchanged) | default/auto (unchanged, identical) |

**Answer to the adjudication question:** the original guard was **protective-but-premature**, not
predictive of real memory exhaustion, for this exact configuration. Windows' actual virtual-memory
(commit) capacity on this machine — physical RAM plus a comparably sized pagefile — comfortably
accommodated the identical workload with nearly 20 GB of commit headroom to spare, even while the
narrower "immediately available physical RAM" signal dipped hard enough on Run 1 to trip the
original coarse guard. Run 1's telemetry and evidence remain valid and unmodified as the record of
that guard-trigger event; they are not overwritten, only reinterpreted in light of Run 2's
additional, more diagnostic telemetry.

## DIAG-GPU-120

Two additional exposures now recorded for this package (Run 1 and Run 2), both controlled: no GPU
loss, no black screen, no hard reset in either. Run 1 ended in a clean, tool-initiated interruption;
Run 2 completed normally. Neither is a DIAG-GPU-120 PASS and neither supports a root-cause
conclusion; DIAG-GPU-120 remains **observation-only, in progress**.

## Product consequence (not implemented; recommendation only)

Per this package's PASS consequence: the next candidate package is a **bounded Wan2.2-Animate
motion-transfer characterization** using actual driving motion, evaluating identity retention,
locomotion/weight transfer, driving-motion adherence, anatomy, temporal coherence, and practical
resource margin at this same or a modestly larger scale — the first quality-oriented Animate
package. This package does not implement that consequence and does not authorize production
integration, geometry increases beyond what a future package would separately justify, or
governance promotion.

## Architecture effect

None. Identical to PR-VID-160B: direct dispatch to a manager-owned Comfy instance; no
`VideoWorkflowController`/NJR/`VideoExecutionResolver` touched; no second queue/history/runner; no
production `src/` change; Animate remains unregistered as a StableNew workflow.

## Validation

- Run 1 (original): 22 focused deterministic tests passed (`tests/tools/test_vid160c_qualification.py`).
- Run 2 (adjudication): 15 additional focused deterministic tests passed
  (`tests/tools/test_vid160c_commit_adjudication.py`), covering commit-metric conversion, EX2→EX
  fallback, the exact 0.77 GB-alone-does-not-trigger regression, all three new abort conditions in
  isolation, exactly-one-additional-submission, no retry, evidence persistence, owner-only teardown.
- Combined: **53 tests passed** across `tests/tools/test_vid160b_qualification.py`,
  `tests/tools/test_vid160c_qualification.py`, `tests/tools/test_vid160c_commit_adjudication.py`.
- Ruff clean on `tools/qualification/vid160c/` and both test files.
- `git diff --check` clean.
- No broader suite run.
- Physical acceptance evidence: two real Comfy runs (Run 1 interrupted, Run 2 completed), clean
  tool-initiated interruption/completion via the existing `ComfyClient.interrupt_own`/
  `abort_reason` mechanism, telemetry captured throughout both, clean teardown and full system
  recovery verified by direct `nvidia-smi`/process/RAM re-check after each.

## Docs/Git

New in Run 1: `tools/qualification/vid160c/` (`__init__.py`, `pose_asset.py`, `graph.py`,
`run.py`), `tests/tools/test_vid160c_qualification.py`. New in the adjudication continuation:
`tools/qualification/vid160c/win_memory.py`, `tools/qualification/vid160c/telemetry.py` (a new,
separate module — `tools.qualification.vid160b.telemetry` and Run 1's own
`tools.qualification.vid160c.run` are unmodified), `tools/qualification/vid160c/adjudicate.py`,
`tests/tools/test_vid160c_commit_adjudication.py`, and this report. `STATUS.md` updated: the
Move-mode gate is closed with the adjudicated `MOVE_MODE_RESOURCE_PASS_32GB` result, superseding
the interim NO-GO wording while retaining the historical Run 1 guard-trigger event. `CODEX_MAP.md`
row updated to the final classification. No architecture-doc change (no authority changed). No
pose video, generated MP4, telemetry, or Comfy runtime file was committed (all under `reports/`,
which is gitignored); no model asset was committed.

## Explicit confirmations

Exactly two prompts were submitted across this package's full lifetime: Run 1
(`prompt_id=370f9fca-c626-41c2-962c-33e5c3e900e8`, safety-stopped) and this continuation's one
authorized additional attempt, Run 2
(`prompt_id=4a581195-7a0e-48c6-9e06-dd0efc803eda`, completed). No third submission and no retry
occurred after either run. No quant was switched, no dimensions/frames/steps were increased, no
`face_video` was added, no pagefile size/disable change, no Comfy memory-management flag
(`--lowvram`/`--novram`/`--disable-smart-memory`/etc.) was changed, no pose-extraction custom node
(`comfyui_controlnet_aux`/KJNodes/DWPose/MediaPipe/SAM2/VideoHelperSuite) was installed. No
production Animate integration, GUI/controller/resolver work, or GPU/BIOS/XMP/driver change
occurred. `src/controller/app_controller.py` and `presets/global_positive.txt` (pre-existing
unrelated local state) remained untouched and unstaged throughout both runs.
