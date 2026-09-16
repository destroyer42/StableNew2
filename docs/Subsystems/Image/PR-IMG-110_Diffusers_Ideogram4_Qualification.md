# PR-IMG-110 — Diffusers / Ideogram 4 Qualification

Status: **COMPLETE — IDEOGRAM 4 NO-GO ON RTX 4070 Ti 12GB; DIFFUSERS SUBSTRATE VIABLE**

This is a target-machine qualification only. It did not register a production
Diffusers backend or change StableNew's compiler, NJR, queue, runner, GUI,
artifact/history, A1111, or SVD authorities.

## Scope and environment

- Parent / branch: `main @ 8f1c106e9a940747e1687a03d42bcfa142f7ee06` /
  `img/110-diffusers-ideogram-qualification`.
- Target: Windows 11 Home build 26100; NVIDIA GeForce RTX 4070 Ti, 12,282 MiB;
  driver 616.56 (CUDA UMD 13.4).
- Disposable environment only: Python 3.12.14; Torch `2.14.0+cu130` (CUDA
  13.0); Diffusers `0.41.0.dev0` from commit
  `d77d53044518ed45583ce3ff680f9f87f816aeb3`; Transformers 5.17.0;
  Accelerate 1.15.0; bitsandbytes 0.50.2.
- Production `.venv` was not modified. A1111 and ComfyUI were not running
  during qualification and were never adopted, stopped, or restarted.

## Ideogram artifact and prior paths

Authenticated access to the official Diffusers-formatted
`ideogram-ai/ideogram-4-nf4-diffusers` snapshot passed at revision
`1874bc70267ba2c823a7239e1d70dd308c8d64dc`. The normal user Hub cache snapshot
contains 27 files totaling 16,117,875,670 bytes. Header-only inspection found
split `to_q` / `to_k` / `to_v` projections in both transformers and no fused
`qkv`; this resolved the earlier local-artifact loader mismatch.

The official 48-step guidance schedule was required. At 1024x1024, seed 0:

| Path | Result |
|---|---|
| Normal CUDA | Pipeline loaded, but used about 11.9 GiB with about 0.13 GiB headroom; the first denoising step exceeded seven minutes. Operationally rejected. |
| Model CPU offload | About 1.25 GiB VRAM but about 21 GiB private host memory; no first inference progress inside the 120-second bound. Operationally rejected. |
| First group offload attempt | CUDA illegal-memory-access after load; `nvlddmkm` Event 153 recorded. Correctly terminated without retrying the poisoned context. |

Pre-reboot Event 153 records at 21:29:03 and 21:33:20 had EventData
`\Device\Video3` and `Error occurred on GPUID: 100`. They are evidence of the
first attempt and are not, by themselves, labeled as TDRs.

## CUDA isolation controls

After a normal reboot, idle VRAM was about 10.8–10.9 GiB free. The following
fresh-process controls passed with no new System GPU/WHEA/WER fault event:

- R3: CUDA query, allocation, 4096x4096 deterministic matrix multiply,
  synchronization, finite/exact result, and cache release; 326 MiB allocator
  peak.
- R4: 180.1 seconds / 4,318 deterministic matrix multiplications; 99–100%
  GPU utilization; 1.21 GiB Torch allocator peak and about 2.6 GiB
  driver-visible usage; 60–76 C and about 216–226 W; no exception.

Queued historical WER reports appeared immediately after reboot but reference
older watchdog dumps and were not attributed to R3/R4.

## R5 Diffusers substrate control

`stabilityai/stable-diffusion-3.5-medium` was gated. The authorized public
control `stabilityai/stable-diffusion-xl-base-1.0` was acquired through the
normal user Hub cache at revision `462165984030d82259a11f4367a4eed129e94a7b`
(57 files; 76,912,765,291 bytes, including repository variants).

One fresh `StableDiffusionXLPipeline` fp16 run used no xformers, custom
attention processor, bitsandbytes, NF4, or offload patch. It generated a
1024x1024 image from a fixed simple prompt and seed 0 in 25.703 seconds after
a 6.594-second CUDA load. The first callback occurred at 7.406 seconds; all
25 callbacks completed. Peak Torch allocation/reservation was 10,736.38 /
14,432 MiB. The output SHA-256 was
`0354b0fe2dedc3adfe5bee10233c96b77ab567f7559e6df58606f4b0c80e38d9`.
Post-exit GPU state was clean (11,727 MiB free) with no new System, WER, or
Reliability event.

**GENERAL DIFFUSERS SUBSTRATE — PASS.** This proves generic Torch/CUDA and a
normal Diffusers image pipeline in this disposable environment. It does not
prove NF4, bitsandbytes, group offload, or Ideogram viability.

## R6 fresh Ideogram group-offload retry and decision

After the clean SDXL control and an 11,718-MiB-free idle baseline, exactly one
fresh Ideogram group-CPU-offload retry was made using the official snapshot,
1024x1024, seed 0, and the official 48-step schedule. It loaded for 20.640
seconds but reached no callback or inference progress. It failed with:

`CUBLAS_STATUS_NOT_SUPPORTED` from `cublasGemmEx` on bfloat16 operands.

The process did no further CUDA cleanup after the exception. A separate-process
inspection found 11,622 MiB free and a new `nvlddmkm` Event 153 at 22:27:39
with EventData `\Device\Video3` / `Error occurred on GPUID: 100` (record
40098). There was no WER or Reliability event in the post-R6 window.

The repeated group-offload fault/no-inference outcome, combined with the
previously rejected normal-CUDA and model-CPU-offload paths, makes sequential
or disk offload diagnostic-only and ineligible for production. Therefore:

**PR-IMG-110 — IDEOGRAM 4 NO-GO ON RTX 4070 Ti 12GB; DIFFUSERS SUBSTRATE
VIABLE.**

No IMG-120 work is authorized from this result. Any future alternative model
qualification requires a separate product-owner decision and acceptance
contract.

## Evidence and validation

Local generated images, Hub caches, virtual environment, and incremental JSON
evidence remain user-scoped and untracked. Reusable qualification-only tools
are under `tools/qualification/img110/`; they contain no token, cache, or
machine-specific hardcoded path. Ruff passed on that directory; `git diff
--check` passed. The local `python tools/ci/run_pr_gate.py` was attempted but
was blocked because `mypy` was unavailable; this was a tooling limitation, not
a source or test failure. GitHub Actions run `35048397497` for feature SHA
`d48780a38b01580f58ae13589c3dba2198881600` passed the required Python 3.11 and
3.12 jobs, including repository completeness, controller-surface ratchet,
Ruff, mypy smoke, active test-surface collection, required positive-list smoke,
and clean-checkout validation. The informational full-suite jobs failed
outside this qualification-only change surface and remain non-blocking. No
production test or GPU qualification was rerun for this docs-only correction.

Controller surface assessment: not applicable; no controller/coordinator code
changed. Token-efficient validation reused accepted R1–R4 evidence, then used
one SDXL substrate control and exactly one fresh Ideogram group-offload retry.
