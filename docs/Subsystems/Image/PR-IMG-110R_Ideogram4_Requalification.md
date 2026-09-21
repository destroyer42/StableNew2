# PR-IMG-110R — Ideogram 4 Definitive Target-Hardware Requalification

Status: **COMPLETE — IDEOGRAM 4 NF4: PASS — CONSTRAINED on RTX 4070 Ti 12GB** (explicit
residency policy required; the earlier "hardware no-go" is retracted).
Qualification only. No production Diffusers/Ideogram backend, compiler/NJR/queue/runner/
artifact/history change, A1111 or SVD change, and no change to the production `.venv`.

## 1. Question and answer

Was the PR-IMG-110 rejection of Ideogram 4 NF4 on the 12 GB target caused by real hardware
limits, or by acquisition, harness, Diffusers/offload, dtype/kernel or runtime defects?

**Not a fundamental hardware-capacity no-go; the 12GB VRAM ceiling requires explicit component
residency management.** Every configuration PR-IMG-110 tried either kept ~15 GiB of NF4
weights resident on a 12 GiB card (Windows silently spilled the excess into shared system
memory, giving ~60 s per denoising step) or used an offload path that does not fit this
model's structure. With the same official weights and the same official denoising code, a
residency plan that keeps only one ~4.9 GiB transformer on the GPU at a time completed every
requested level, up to 1024x1024 `V4_QUALITY_48`, on two independent implementations, with
bit-identical output on repeat.

## 2. Environment and pins (all disposable, user-scoped, outside Git)

| Item | Value |
|---|---|
| Host | Windows 11 Home build 26100; RTX 4070 Ti 12,282 MiB (idle desktop use 0.46-1.03 GiB); driver 616.92; 31.8 GB RAM (~20-27 GB free at run start) |
| Runtime | Python 3.11.9; torch 2.14.0+cu130; transformers 5.17.0; accelerate 1.15.0; bitsandbytes 0.50.2 |
| Official path | `ideogram-oss/ideogram4` @ `990fe1c4e950bb9e9dc90e01c0ad98ba434f83c2` (2026-06-30), `ideogram-4 0.1.0`, weights `ideogram-ai/ideogram-4-nf4` @ `f664347839e0a87bc495f5c9483cc0014b8e344e` (`main` re-verified equal to the pin before every run) |
| Diffusers path | `diffusers 0.40.0` (current release; contains `Ideogram4Pipeline`), weights `ideogram-ai/ideogram-4-nf4-diffusers` @ `1874bc70267ba2c823a7239e1d70dd308c8d64dc` |
| Prompt | one fixed structured JSON caption (sha256 `88560d3f5865369c...`, 287 tokens), accepted by the official `CaptionVerifier` with no issues; seed 0 for every run |

Weight arithmetic (identical in both repos): text encoder 5.48 GB + two transformers
2 x 5.22 GB + VAE 0.17 GB = 16.1 GB = **15.0 GiB of NF4**; a 12,282 MiB card with ~0.5-1 GiB
in desktop use leaves ~11 GiB.

## 3. Audit of PR-IMG-110 (classification of every prior failure)

| PR-IMG-110 observation | Class | Finding |
|---|---|---|
| Local artifact loader mismatch (fused `qkv` vs split `to_q/k/v`) | (a) acquisition/schema | Different repo layouts: official code needs `ideogram-4-nf4`, Diffusers needs `ideogram-4-nf4-diffusers`. Corrected before, confirmed here (each path uses its own repo). |
| Normal CUDA: ~11.9 GiB used, 0.13 GiB headroom, first step >7 min | (e)+(f) VRAM overcommit of the *all-resident* configuration | 15 GiB of weights cannot be resident on 12 GiB. Reproduced with the official code as shipped: Torch allocated up to 16.3 GiB, 6.2 GiB of it spilled into shared system memory, first step 59.6 s (§5). A property of the configuration, not of the model. |
| Model CPU offload: no first callback in 120 s, ~21 GiB host memory | (c) runtime/API/offload + (b) harness bound | `from_pretrained` puts every NF4 component on the GPU at load; `enable_model_cpu_offload` chains offloads in a fixed text_encoder -> transformer -> unconditional_transformer order and never parks the unconditional transformer when the conditional one runs again, so both stay resident (§5 steps 2-7 at 14 s). The 120 s bound was shorter than a normal load-plus-encode (~45 s) plus the slow steps; the same path completes a 512x512 image in 130 s. |
| Group offload: illegal memory access, then `CUBLAS_STATUS_NOT_SUPPORTED`, `nvlddmkm` 153 | (c)/(d) software: group offload of bitsandbytes NF4 | Diffusers' group offloading moves parameters by replacing `.data` (`group_offloading.py`), with a special case only for TorchAO tensors, so a bitsandbytes `Params4bit` `quant_state` is not moved with its data. Module-level `.to()` of NF4 modules round-trips bit-exactly (a small bitsandbytes test here, then every swap run in §5), so NF4 and bf16 GEMM on this GPU are fine. **Probable** cause by code inspection and elimination; not re-run (it poisoned the CUDA context twice and the brief forbids re-poisoning it). |
| Event 153 records | not by themselves a capacity signal | A new 153 appeared only when this work force-terminated a process that had 6.2 GiB spilled into shared memory (§6); the GPU was healthy afterwards. |

Further defects found in the previous runner (`tools/qualification/img110/run_ideogram.py`):
plain-text prompt (the official guide states plain text is off-distribution and can trip the
safety filter); Diffusers default `max_sequence_length=2048` (pads the text to 2048 tokens,
official pads only to the prompt: 287); no residency plan at all; a git-dev Diffusers
(0.41.0.dev0) and Python 3.12 instead of the release; no per-step timing or shared-memory
evidence. Nothing in it was an authoritative reference implementation.

## 4. Methodology: old versus corrected

| Aspect | PR-IMG-110 | PR-IMG-110R |
|---|---|---|
| Reference | none (custom runner over Diffusers) | official reference code + independent Diffusers release, both pinned |
| Prompt | plain text | structured JSON caption, official verifier |
| Presets | default 48 steps only | official `V4_TURBO_12` / `V4_DEFAULT_20` / `V4_QUALITY_48` (values asserted equal to the official registry at run time; guidance order reversed for Diffusers) |
| Text length | 2048 padded | exact (287) |
| Residency | all-resident, model offload, group offload | as-shipped baseline **plus** text encoder first then released, and one-transformer-resident swap (official `staged_swap`), component-wise Diffusers load + swap; Torch allocator cap 11,200 MiB so real exhaustion is an explicit OOM instead of silent spill |
| Bounds | 120 s to first callback | 900-2,400 s, per-step timings, fresh process per run, incremental flushed evidence, host-RAM guard |
| Evidence | Torch stats | driver VRAM, Torch allocated/reserved, process private memory, host RAM, GPU util/power/temp/throttle, shared-memory counters, output SHA-256, System/WER events per run window |

The residency policy changes only *where weights sit*: the official code's own text encoder,
transformers, sampler and VAE run unchanged, the text features are computed once by the
official `_encode_text` and handed back, and the swap is a forward pre-hook using module
`.to()`. Proof: the all-resident run and the swap run of the official code at 512x512 produce
the **same PNG** (sha256 `e83cd23b9dc4...`).

## 5. Result matrix

`gen` = image generation after load. VRAM = highest driver-visible sample (12,282 MiB card).

| Runtime | Level (res, preset) | Result | load | 1st step | gen | VRAM peak | Torch alloc / reserved |
|---|---|---|---|---|---|---|---|
| official as-shipped | L1 512x512 TURBO_12 | timed out at 900 s while denoising (`performance_only`) | 177 s | **59.6 s** | - | 11,907 MiB | 16.3 / 17.1 GiB (6.2 GiB in shared memory) |
| official, encoder released, both transformers resident | L1 | success, valid | 184 s | 57.3 s | 688 s | 11,932 MiB | 11.2 / 11.7 GiB (1.1 GiB shared) |
| official, one-transformer swap | L1 | success (same PNG as above) | 152 s | 3.2 s | **41.9 s** | 7,698 MiB | 6.2 / 6.6 GiB |
| official swap | L2 768x1024 TURBO_12 | success x2, **identical sha256** `69dea980...` | 153 s | 4.7 s | 60.4 / 60.6 s | 10,862 / 10,615 MiB | 8.0 / 9.7 GiB |
| official swap | L3 1024x1024 DEFAULT_20 | success | 151 s | 5.9 s | 116 s | 10,623 MiB | 9.0 / 10.7 GiB |
| official swap | L4 1024x1024 QUALITY_48 | success | 152 s | 5.8 s | 279 s | 11,799 MiB | 9.0 / 10.7 GiB |
| Diffusers documented (`from_pretrained` + `enable_model_cpu_offload`) | L1 | success, valid; steps 4.0, 6 x 14 s, 5 x 2.4 s | 15 s | 4.0 s | 130 s | 11,901 MiB | 11.0 / 11.5 GiB |
| Diffusers component-wise load + swap | L2 | success x2, **identical sha256** `20b884fe...` | 18 / 20 s | 5.6 s | 66.8 / 66.9 s | 10,602 / 10,619 MiB | 8.3 / 9.7 GiB |
| Diffusers swap | L3 | success | 19 s | 6.6 s | 130 s | 11,119 MiB | 9.3 / 10.2 GiB |
| Diffusers swap | L4 | success | 19 s | 6.6 s | 312 s | 11,118 MiB | 9.3 / 10.2 GiB |
| Diffusers default `from_pretrained` under the 11.2 GiB cap | L2 | `OutOfMemoryError` while loading (allocating 4.66 GiB with 9.8 GiB already allocated): the loader puts all 15 GiB of NF4 on the GPU | - | - | - | - | - |
| Diffusers, `callback_on_step_end` on Python 3.11 | L1 | `KeyError: 'latents'` at the first callback (release `pipeline_ideogram4.py:717` uses `locals()` inside a dict comprehension, which needs Python 3.12 semantics); harness switched to module hooks | - | - | - | - | - |

Text encoding: 0.5-1.2 s once the encoder is on the GPU (official encoder load 4.6-5.6 s);
27-28 s when the encoder is partly in shared memory (as-shipped) or is onloaded by the offload
hook (documented Diffusers path). All valid images are the fixed still life
(blue teapot, lemon, "OPEN" sign) at the requested size; the official and Diffusers outputs
are both correct but not bit-identical (different numerics), as expected. GPU under load:
100% utilisation, 220-240 W, 59-75 C, throttle bitmask `0x401` (idle bit plus an unnamed
`0x400` bit; it never ran below 2,670 MHz while busy). Host RAM: the official loader builds a float32 skeleton first
(~48-54 GiB private commit, host RAM fell to ~0 GB free, 178 s load); building it in bfloat16
(harness policy, values unchanged) cut that to ~36 GiB and 0.65 GB free minimum; the Diffusers
component-wise load stays near 30 GiB with 8.9 GB free minimum.

## 6. Faults and system events

Eleven successful GPU runs (several of 4-7 minutes near 75 C) produced **no** GPU/WHEA/WER/
Kernel-Power event and no context poisoning. The only System event was one `nvlddmkm` id 153
(`\Device\Video3`, "Error occurred on GPUID: 100") at 10:26:05, seconds after the orchestrator
terminated the as-shipped run at its 900 s bound while ~6.2 GiB of its allocations sat in
shared memory (the run and the event agree to the second: 10:11:06 start + 900 s). `nvidia-smi` and idle VRAM (459 MiB) were healthy afterwards. This matches the
event's earlier appearance after an aborted CUDA process, and it is why the orchestrator set
"reboot before further CUDA inference" and no later CUDA run was made. It is recorded, not
explained; it did not affect any result. (The workstation's separate history of unexplained
resets is documented in PR-VID-110 section 9 and did not recur during these runs.)

## 7. Root-cause classification of this work's failures

| Failure | Class | Cause |
|---|---|---|
| official as-shipped: 60 s/step, timeout | (e)/(f) resource overcommit by configuration | 15 GiB of weights + activations on a 12 GiB card; shared-memory spill |
| official all-resident, encoder released: 57 s/step | (e)/(f) | 9.7 GiB of transformers + ~1.1 GiB CUDA context/activations/desktop exceed 11 GiB by ~1 GiB |
| Diffusers documented offload: 14 s steps at 512x512 | (c) runtime/offload | both transformers stay resident; spill until settled |
| Diffusers default load OOM under cap | (e) in the *loader configuration* | all NF4 components to the GPU at once |
| Diffusers callback KeyError | (b)/(c) harness/environment | Python 3.11 vs release code needing 3.12 semantics |
| Official loader host-RAM collapse | (e) host memory, performance | float32 skeleton; mitigated by a bf16 default in the harness |

No failure was attributable to model capacity on this GPU, dtype/kernel support, or the driver.

## 8. Verdict

**PASS — CONSTRAINED.** Ideogram 4 NF4 completes reliably and reproducibly on the RTX 4070 Ti
12GB at every tested level, with valid output, **but only with an explicit residency policy**
that neither reference implementation ships.

Supported envelope (measured):

- Up to **1024x1024** and up to **`V4_QUALITY_48`** (2048x2048 was not tested).
- Residency policy required: load the text encoder first, encode once, release it, keep only one
  transformer on the GPU at a time (swap the conditional/unconditional transformers each step),
  Torch allocation ceiling ~11.2 GiB; components loaded one at a time (Diffusers) or the
  official loader with a bf16 skeleton.
- Latency per image after load: 768x1024 Turbo ~60-67 s; 1024x1024 Default ~116-130 s;
  1024x1024 Quality ~279-312 s; load 18 s (Diffusers) or ~152 s (official loader), amortisable
  only by a resident process.
- Headroom: peak 10.4-11.5 GiB of 12.0 GiB (0.5-1.6 GiB free); exclusive use of the GPU is assumed
  (A1111/SVD/other GPU applications would not coexist); ~16-20 GB free host RAM.
- The unmodified documented paths (all-resident official code, `enable_model_cpu_offload`) are
  **not** practical at 768x1024 or larger, so this is not PRACTICAL: PRACTICAL requires an
  unmodified documented path to work at a StableNew-class size.

Diffusers path: **viable with the same policy** (independent second implementation, identical
repeat output, 18 s load); the documented default path is defective for a 12 GiB card
(software/runtime findings above). Not classified SOFTWARE/RUNTIME NO-GO overall because a
corrected Diffusers path succeeds.

## 9. Documentation and gate consequences

- The PR-IMG-110 "Ideogram 4 NO-GO ON RTX 4070 Ti 12GB" wording is **incorrect** and has been
  marked superseded there, in STATUS, the roadmap and the Codex map. Its evidence sections stay as
  history; its generic-Diffusers (SDXL) finding is unchanged.
- **IMG-120 remains not authorized**, but is now *eligible for a separate product-owner
  decision*. Retain Ideogram 4 as constrained/experimental if pursued. Decisions this result does
  not make and a backend would need: whether a StableNew backend may implement a custom GPU
  residency lifecycle and exclusive GPU lease (architecture); how NJR/prompt intent maps to the
  structured JSON caption the model requires; and whether the Ideogram 4 Non-Commercial license
  fits the intended use.

## 10. Reproduction and evidence

Tooling: `tools/qualification/img110r/` (`caption`, `common`, `harness`, `run_official`,
`run_diffusers`, `orchestrate`, `verdict`); deterministic tests in
`tests/tools/test_img110r_qualification.py` (caption schema, presets and guidance order,
failure classification, verdict rules, preflight refusal after a fault, no production reference).
Runs execute in `~/img110r/venv-ref` and `venv-dfz` (disposable; created with the pins above):

    python -m tools.qualification.img110r.orchestrate run --runtime official-staged-swap --level 2
    python -m tools.qualification.img110r.orchestrate matrix

Raw JSON, per-second telemetry, logs and images are in the git-ignored `reports/img110r/`.

Not done, by design: a re-run of group offload (would re-poison the context; classified by code
evidence), `diffusers-cuda`, the documented Diffusers path at 768x1024 and above (predicted
spill; would end in another forced termination), 2048x2048, concurrent A1111/SVD use, and any
BIOS/driver/power change.
