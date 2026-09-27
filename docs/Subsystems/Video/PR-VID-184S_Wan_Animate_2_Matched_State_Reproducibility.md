# PR-VID-184S — Wan-Animate-2 Matched-State Pinned-Memory B1→A→B2 Reproducibility

## Purpose

[PR-VID-184R](PR-VID-184R_Wan_Animate_2_Pinned_Memory_Readjudication.md) classified
`PINNED_MEMORY_PATH_MATERIALLY_IMPLICATED` from a single run against a single run, with disclosed
uncontrolled state differences (different starting commit level, different physical RAM headroom).
This package asks two narrower questions under a matched-state protocol, using exactly three
authorized GPU submissions in the order **B1 → A → B2**:

- **Q1 — Reproducibility.** Does the PR-VID-184R successful configuration (`--disable-pinned-memory`)
  complete repeatedly on this machine?
- **Q2 — Matched-state pinned-memory effect.** When the immediately-pre-dispatch machine state is
  deliberately matched to B1 within frozen bands, does enabling pinned memory reproduce the
  GPU-loss behavior or a materially higher resource-pressure pattern seen in PR-VID-184?

## Owner motion-value verdict (recorded before the new runs)

**`WAN_ANIMATE_2_OWNER_MOTION_VALUE_PASS`** — the owner's assessment of the accepted PR-VID-184R
Arm-B output: the motion visually matches the intended driving motion, is very smooth, meets the
intended product goal, and clearly justifies further engineering.

This is a product-value judgment, separate from and not overwriting the automated frozen metric,
which remains as previously reported and is reconfirmed below for all three new outputs:

| Metric | PR-VID-184R value | Gate | Result |
|---|---|---|---|
| Primary subject continuity | 1.0 | ≥ 0.90 | PASS |
| Ghost-actor persistence | 0 frames | ≤ 2 frames | PASS |
| Root translation fraction | 0.623 | ≥ 0.15 | PASS |
| Motion-curve correlation | 0.151 | ≥ 0.30 | **FAIL** |

Product interpretation kept explicit and non-overwriting: **automated motion characterization
remains PARTIAL, while the owner visual/product-value verdict for the tested case is PASS.**

## Start state and environment lock

- Repository: `destroyer42/StableNew2`, base `origin/main` at `0a2bb505acdb381726a401d9e74281e362fc44ea`
  (PR-VID-184R, PR #10), confirmed in ancestry before work began.
- Branch: `feature/pr-vid-184s-matched-state-reproducibility`, created from `origin/main`.
- Environment: the same preserved isolated qualification install used by PR-VID-184/184R
  (`C:\Users\rob\qual\vid184\env`), untouched. StableNew-managed ComfyUI (`E:\Users\rober\ComfyUI`)
  was not touched.
- Frozen workload identity, verified by the harness gate immediately before every one of the three
  submissions (all three matched, zero drift):
  - ComfyUI checkout: `73c9bad4d21e7addbe1d13bc92eee0f1431b017d`
  - torch: `2.14.0+cu130`; comfy-aimdo: `0.5.5`
  - Graph, reference image, 39-frame driving clip and all four model files: SHA-256 matched the
    PR-VID-184R frozen manifest in every gate.
  - Seed `58819112904309696`, cache OFF, legal generation length 41 trimmed to the 39-frame evidence
    window, scoring contract hash `30608f7a3595d5db000946fbb4941918fdf6dd09cdf8fa1387a7953ed706543c`
    (`sc.verify_contract_unchanged()` passed for every scored output).
  - No forbidden flag present in any arm's launch args (`hidden_flag_check` empty for B1/A/B2).
  - Arm B1/B2 launch args are identical (`execution_equivalent` true); Arm A differs from B1/B2 by
    exactly the `--disable-pinned-memory` flag plus arm/evidence identity (`ALLOWED_DIFF_KEYS`).

## Frozen matched-state thresholds (set before Arm B1, unchanged after any result)

| Quantity | Band | Reference |
|---|---|---|
| Windows commit percent | ± 3.0 percentage points | Arm B1 immediately-pre-dispatch snapshot |
| Physical RAM available | ± 1.5 GB | Arm B1 immediately-pre-dispatch snapshot |
| Free GPU VRAM | ± 512 MiB | Arm B1 immediately-pre-dispatch snapshot |
| Fresh-boot ceiling | ≤ 60 minutes since boot | each arm's own boot |
| "Materially higher pressure" (A vs B1) | commit peak Δ ≥ 10.0 percentage points | pre-registered |

No memory was artificially consumed or freed to force a match; every arm entered the bands under
an ordinary fresh-boot idle state.

## Per-arm preflight

| | B1 | A | B2 |
|---|---|---|---|
| Boot time | 2026-09-27T06:04:59-04:00 | 2026-09-27T06:14:27-04:00 | 2026-09-27T06:23:33-04:00 |
| Minutes since boot at gate | 3.27 | 2.03 | 1.51 |
| Pre-dispatch commit % | 29.76 (reference) | 28.22 (Δ −1.54, within ±3.0) | 29.00 (Δ −0.76, within ±3.0) |
| Pre-dispatch RAM available | 19.69 GB (reference) | 20.09 GB (Δ +0.40, within ±1.5) | 19.90 GB (Δ +0.21, within ±1.5) |
| Pre-dispatch free VRAM | 10,964 MiB (reference) | 11,040 MiB (Δ +76, within ±512) | 10,937 MiB (Δ −27, within ±512) |
| Matched-state gate | n/a (sets reference) | **PASSED** | **PASSED** |
| Other GPU compute processes | none | none | none |
| Port 8189 | free | free | free |
| Outputs dir | empty | empty | empty |

Each arm's pre-dispatch GPU query also confirmed idle VRAM headroom consistent with the table
above (`pre_dispatch_gpu`), and no other Comfy/A1111/webui process was running before any submission
(operator-confirmed and harness-gated).

## Per-arm execution and resource result

| | B1 (pinned off) | A (pinned on) | B2 (pinned off) |
|---|---|---|---|
| Outcome | **COMPLETED** | **COMPLETED** | **COMPLETED** |
| Sampler steps | 10/10 @ 14.50 s/it | 10/10 @ 14.38 s/it | 10/10 @ 14.53 s/it |
| `Prompt executed in …` | 163.15 s | 161.93 s | 163.38 s |
| Harness wall time | 163.6 s | 163.9 s | 163.6 s |
| VRAM peak | 11,807 MiB | 11,732 MiB | 11,839 MiB |
| Temp peak | 80 °C | 82 °C | 82 °C |
| Power peak | 253.77 W | 257.57 W | 255.09 W |
| Commit peak | **52.91 %** | **73.15 %** | **52.13 %** |
| Commit min headroom | 25.79 GB | 14.71 GB | 26.21 GB |
| Physical RAM min available | 13.99 GB | **1.94 GB** | 14.27 GB |
| `Enabled pinned memory` line | absent (correct) | `Enabled pinned memory 13010.0` (correct) | absent (correct) |
| HostBuffer / CUDA / traceback / GPU-lost counts | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| GPU state post-teardown | idle, 698 MiB used | idle, 683 MiB used | idle, 660 MiB used |
| Genuine GPU-loss/WHEA/Kernel-Power events in window | none | none | none (3 unrelated ID=1 informational events; not 41/6008/nvlddmkm/WHEA — same known filter false-positive noted in PR-VID-184R) |

**Arm A did not reproduce the PR-VID-184 GPU-loss failure under matched state.** It completed
cleanly, but its commit peak (73.15 %) was 20.24 percentage points above Arm B1's (52.91 %) — well
past the pre-registered 10-point "materially higher pressure" threshold — and its minimum physical
RAM available fell to 1.94 GB, a low margin that never triggered the commit-aware safety stop
(thresholds: commit ≥ 97 % or headroom < 1.0 GB for 2 consecutive samples, or physical RAM
< 0.25 GB).

## Output identity and comparison

| | B1 | A | B2 |
|---|---|---|---|
| File | `vid184_run5_generated_00001_.webm` | `vid184_run5_generated_00001_.webm` | `vid184_run5_generated_00001_.webm` |
| SHA-256 | `f6b6de6f66e8…794d4` | `c9c5953bc638…9bb` | `e165244e28f2…9cd7d` |
| Codec / geometry / fps | vp9, 480×848, 24 | vp9, 480×848, 24 | vp9, 480×848, 24 |
| Decoded / trimmed frames | 41 / 39 | 41 / 39 | 41 / 39 |

### Frozen metrics on the 39-frame evidence window (re-run from the saved output for all three arms)

| Metric | B1 | A | B2 | Gate | Result |
|---|---|---|---|---|---|
| Primary subject continuity | 1.0 | 1.0 | 1.0 | ≥ 0.90 | PASS (all) |
| Ghost-actor persistence | 0 | 0 | 0 | ≤ 2 | PASS (all) |
| Root translation fraction | 0.623 | 0.628 | 0.623 | ≥ 0.15 and direction-matched | PASS (all) |
| Motion-curve correlation (vs driving clip) | 0.151 | 0.139 | 0.151 | ≥ 0.30 | **FAIL (all)** |
| Identity-hist mean (corroborating only) | 0.950 | 0.950 | 0.950 | — | — |
| Camera drift (px) | 0.004 | 0.004 | 0.004 | — | — |
| Motion-area fraction | 0.274 | 0.273 | 0.274 | — | — |

The frozen contract's `ROOT_TRANSLATION_DIRECTION_MUST_MATCH` gate is enforced, not just the
magnitude threshold: the driving clip's own primary-track centroid moves left-to-right (first
centroid x 28.6px → last 275.4px of 464px width), and all three arms' outputs move the same
direction (B1/B2 first 71.2px → last 370.0px; A first 69.0px → last 370.7px, of the 480px output
width) — direction-matched in all three, so this does not change any pass/fail result above.

### Cross-output similarity/variance (frame-level comparison of the 39-frame trims)

| Pair | PSNR mean / min (dB) | HSV-hist correlation | Root-trajectory correlation / RMS (px) | Motion-curve correlation (between outputs) |
|---|---|---|---|---|
| B1 ↔ B2 | 99.0 / 99.0 | 1.000 | 1.000 / 0.0 | 1.000 |
| B1 ↔ A | 29.45 / 23.56 | 0.999 | 1.000 / 0.9 | 0.994 |
| A ↔ B2 | 29.45 / 23.56 | 0.999 | 1.000 / 0.9 | 0.994 |

B1 and B2 decode to pixel-identical frames (PSNR at the tool's ceiling, i.e. zero measured MSE)
despite different container SHA-256 hashes — the file-level hash difference is VP9
container/encoder non-determinism, not a content difference; same seed, same launch args, same
frozen workload reproduces the same generation exactly. Arm A's output is visibly close but not
identical to B1/B2 (mean PSNR ≈ 29 dB, motion-curve correlation between outputs 0.994): a small,
consistent numerical effect of enabling pinned memory on this otherwise identical run, well short of
a different or degraded result. No output looks materially worse than the accepted PR-VID-184R
artifact; B1/B2 are that same artifact (byte-for-byte at the decoded-frame level).

## Pre-registered classification (applied mechanically by `tools/qualification/vid184s/arms.classify`)

All three arms completed, so:

- **`WAN_ANIMATE_2_LOCAL_EXECUTION_REPRODUCIBLE_WITH_PINNED_MEMORY_DISABLED`** — B1 and B2 both
  completed with pixel-identical output, answering **Q1 (reproducibility): YES** for this
  configuration on this machine.
- **`ORIGINAL_PINNED_MEMORY_FAILURE_NOT_REPRODUCED_UNDER_MATCHED_STATE`** — Arm A completed rather
  than losing the GPU, so the original PR-VID-184 failure did not recur when starting from a state
  matched to B1's.
- **`PINNED_MEMORY_RESOURCE_PRESSURE_EFFECT_REPRODUCED`** — recorded separately: Arm A's commit peak
  (73.15 %) was 20.24 points above B1's (52.91 %), above the pre-registered 10-point threshold, and
  its minimum RAM headroom (1.94 GB) was markedly tighter. This weakens (does not eliminate) the
  inference that disabling pinned memory is *necessary* for successful execution on this exact
  workload — pinned memory measurably increases resource pressure here, but that pressure did not,
  this time, cross into GPU loss.

## Causal conclusions supported

- The `--disable-pinned-memory` configuration is reproducible: two independent fresh-boot runs
  (B1, B2) completed identically.
- Enabling pinned memory measurably and reproducibly raises Windows commit pressure and lowers
  physical RAM headroom on this exact frozen workload, even when it does not cause failure.
- Under this specific matched-state trial, enabling pinned memory did not reproduce a GPU-loss
  failure.

## Causal conclusions NOT supported

- That pinned memory is the sole or even a necessary cause of the original PR-VID-184 GPU loss:
  Arm A completed this time.
- That the PR-VID-184 hardware/configuration failure will not recur under pinned memory: this is
  n=1 for Arm A: one successful pinned-memory run does not establish the failure is unreachable,
  only that it did not occur in this one matched-state trial. Windows commit pressure and system
  state are inherently variable session to session even under a matched immediately-pre-dispatch
  snapshot (e.g. background services, driver/OS state not captured by the three matched-state
  variables).
- That this result changes PR-VID-184's or PR-VID-184R's own historical record: both remain
  accurate records of their own tested configurations and are not rewritten.
- Any hardware clearance or DIAG-GPU-130 result: no DIAG-GPU-130 event, black-screen, or
  system-level fault occurred in any arm, so there is nothing new to cross-reference there.

## Architecture boundary

No `src/` change. No workflow registration, production Animate-2 backend, GUI exposure,
VideoExecution contract change, queue/runner/process-manager change, or production Comfy upgrade.
The qualification environment remains isolated from both the StableNew-managed Comfy install and
the canonical execution path (Intent → Compiler → NJR → JobService → Queue/Repository →
PipelineRunner.run_njr → Handler → Artifacts/History), which this package does not touch.

## Changed files

- `docs/Subsystems/Video/PR-VID-184S_Wan_Animate_2_Matched_State_Reproducibility.md` (this report)
- `tools/qualification/vid184s/arms.py` — B1/A/B2 manifests, frozen bands, log analysis,
  pre-registered classification
- `tools/qualification/vid184s/run_arm.py` — per-arm harness extending PR-VID-184R's
  `run_arm_b.py` (gates, ownership check, teardown, telemetry, safety stop reused; adds sequencing,
  matched-state gate, fresh-boot check, per-arm evidence)
- `tools/qualification/vid184s/output_scoring.py` — frozen-metric re-scoring and cross-output
  comparison from saved Comfy output (CPU venv, no GPU); enforces the frozen contract's
  root-translation direction-match gate against the driving clip, not just its magnitude
- `tests/tools/test_vid184s_arms.py` — 19 deterministic tests (manifest equivalence, matched-state
  bands, all classification branches, log analysis, gpu_lost-overrides-COMPLETED precedence)
- `tests/tools/test_vid184s_run_arm.py` — 10 regression tests for the post-review harness
  hardening (protocol-stop sequencing including the matched-state-gate-miss retry case,
  GPU-loss-vs-clean-failure precision, the frozen-bands write-once/mismatch lock, singleton and
  pre-submit-event handling)
- `tests/tools/test_vid184s_output_scoring.py` — 4 tests for the direction-sign helper
- `STATUS.md`, `docs/CODEX_MAP.md` — PR-VID-184S entries
- Evidence outside the repo (kept intact): `C:\Users\rob\qual\vid184\env\evidence_184s\{B1,A,B2}\`
  (gates, logs, telemetry, summaries, arm_records, outputs) and
  `C:\Users\rob\qual\vid184\env\analysis_184s\{B1,A,B2}\` (trims, detections, scores, driving-clip
  detection)

## Validation

- `pytest tests/tools/test_vid184*.py`: 71 passed (37 pre-existing + 19 new + 10 post-review
  hardening regression tests + 5 output-scoring tests).
- Ruff check and format: clean on all touched Python.
- `git diff --check`: clean. `git diff -- src`: empty.
- Local `python tools/ci/run_pr_gate.py`: stops on the known missing-mypy tooling blocker (unchanged
  from prior packages).
- No additional GPU run was used for validation; all validation is deterministic/CPU-only against
  already-captured evidence.

## Next product-owner decision

Not started, and each needs separate authorization:

- A controlled, larger-N repeat (more than one B1/A/B2 cycle) to firm up the Q2 answer beyond n=1
  per arm.
- Root-causing *why* pinned memory raises commit pressure this much (e.g. instrumenting the
  comfy-aimdo HostBuffer path) rather than only observing the effect.
- Production Wan-Animate-2 integration planning, now informed by an owner PASS on product motion
  value and a reproducible local execution path, but still gated on the above and on the
  unresolved question of whether the original hardware failure mode can recur under pinned memory
  in a less favorable system state.
