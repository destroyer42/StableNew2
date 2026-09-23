# PR-VID-160C — Wan2.2-Animate True Move-Mode Resource Closure

Status: **COMPLETE / RESOURCE GATE CLOSED — `MOVE_MODE_RESOURCE_NO_GO_RAM`**. This is a
qualification-only resource-feasibility probe. It adds no production `src/` change, no backend,
no queue/history authority, and no Wan production graph/settings change. Start
`main @ a4d27fe539520076b25f393a023d60150d53e3d3`.

## Outcome asked

Can the already-proven Wan2.2-Animate-14B Q3_K_M configuration complete one small generation with
an actual `pose_video` supplied to `WanAnimateToVideo`, without exceeding RTX 4070 Ti 12-GB VRAM /
32-GB RAM limits, triggering the safety stop, losing the GPU, or violating runtime ownership?

**No.** The one authorized physical attempt was safety-stopped by design: available host RAM
dropped to 0.77 GB (below the frozen 1.0 GB threshold) for two consecutive telemetry samples before
the generation could complete. The run was cleanly interrupted, no CUDA OOM occurred, no GPU was
lost, and the manager-owned Comfy process tore down cleanly with a full recovery to idle
afterward. This closes PR-VID-160B's open resource gate with a definite answer: adding real
`pose_video` conditioning, even at the smallest already-proven geometry, costs materially more host
RAM than this exact 32 GB machine currently has margin for.

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

## Decision classification

**`MOVE_MODE_RESOURCE_NO_GO_RAM`**

The host-memory safety-stop rule tripped during the one authorized attempt: available RAM fell
below the frozen 1.0 GB threshold for two consecutive samples. This is not a reinterpreted
ambiguous result — it is exactly the condition the rule exists to catch, and it closes the
resource gate PR-VID-160B left open with a definite, unfavorable answer at this smallest-credible
scale.

## DIAG-GPU-120

One additional exposure, ending in a clean, tool-initiated interruption rather than an
uncontrolled stop: no GPU-lost/black-screen/max-fan signature, no hard reset, full recovery to idle
confirmed by direct `nvidia-smi`/process re-check afterward. This is not a DIAG-GPU-120 PASS and
makes no hardware/root-cause conclusion; DIAG-GPU-120 remains observation-only.

## Product consequence (not implemented; recommendation only)

Per this package's own NO-GO consequence: **return to the PR-VID-160A candidate evidence rather
than tuning quant/settings inside this package.** Wan2.2-Animate-14B's Move-mode resource cost is
now demonstrated to exceed this machine's practical host-RAM margin even at the smallest credible
geometry (256x256, 13 frames) with the most memory-conservative already-proven quant (Q3_K_M,
chosen specifically for margin over the task's own Q4_K_M default). Further quant reduction within
the Animate-14B family was already judged not "credible enough" in PR-VID-160B's own quant-selection
rationale; a smaller geometry than this probe's would no longer be a meaningfully "small-envelope"
test of the real capability. The next coherent step is a fresh PR-VID-160A-style re-screen of
remaining candidates (or newer entrants) against this concrete, now-measured host-RAM ceiling,
rather than continued Wan2.2-Animate-specific tuning.

## Architecture effect

None. Identical to PR-VID-160B: direct dispatch to a manager-owned Comfy instance; no
`VideoWorkflowController`/NJR/`VideoExecutionResolver` touched; no second queue/history/runner; no
production `src/` change; Animate remains unregistered as a StableNew workflow.

## Validation

- 22 focused deterministic tests passed (`tests/tools/test_vid160c_qualification.py`).
- Ruff clean on `tools/qualification/vid160c/` and the new test file.
- `git diff --check` clean.
- No broader suite run.
- Physical acceptance evidence: one real Comfy run, clean tool-initiated interruption via the
  existing `ComfyClient.interrupt_own`/`abort_reason` mechanism, telemetry captured throughout,
  clean teardown and full system recovery verified by direct `nvidia-smi`/process/RAM re-check
  afterward.

## Docs/Git

New: `tools/qualification/vid160c/` (`__init__.py`, `pose_asset.py`, `graph.py`, `run.py`),
`tests/tools/test_vid160c_qualification.py`, this report. `STATUS.md` updated (the Move-mode gate
is now closed with a durable NO-GO). `CODEX_MAP.md` given one new row for the reusable
`tools/qualification/vid160c/` seam. No architecture-doc change (no authority changed). No pose
video, generated MP4, telemetry, or Comfy runtime file was committed (all under `reports/`, which
is gitignored); no model asset was committed.

## Explicit confirmations

Exactly one prompt was submitted this session
(`prompt_id=370f9fca-c626-41c2-962c-33e5c3e900e8`); no second submission and no retry occurred
after the safety stop. No quant was switched, no dimensions/frames/steps were increased, no
`face_video` was added, no pose-extraction custom node (`comfyui_controlnet_aux`/KJNodes/DWPose/
MediaPipe/SAM2/VideoHelperSuite) was installed. No production Animate integration, GUI/controller/
resolver work, or GPU/BIOS/XMP/driver change occurred. `src/controller/app_controller.py` and
`presets/global_positive.txt` (pre-existing unrelated local state) remained untouched and unstaged
throughout.
