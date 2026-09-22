# PR-VID-160A — Consumer-GPU Directed-Motion Candidate Feasibility

Status: **COMPLETE / ACCEPTED / INTEGRATED**. This is research/decision evidence only: no model was
downloaded, no environment was changed, no GPU workload ran, and no production source changed.
Start `main @ 1b01ab5451a9cc8b86623728ac7fbbd03b379f34`.

## Purpose

Select the strongest candidate, if any, for the next bounded physical directed-motion
qualification on the actual StableNew target (RTX 4070 Ti 12 GB VRAM, 32 GB host RAM, Windows,
existing managed Comfy, current neutral video-execution architecture), given the PR-VID-150 gap:

Wan2.2 TI2V-5B produces useful local gesture/pose motion with structured prompts, but the
controlled locomotion case (`local_motion_viable_locomotion_weak`) produced higher measured
motion without actual stepping/body translation. This package does not reopen Wan locomotion
*prompt* tuning; it asks whether a different model or a different Wan2.2 *capability* (motion
transfer rather than text-prompted motion) is worth the next physical qualification slot.

## Research authority and evidence labeling

Every claim below is labeled **official** (upstream repo/model card/official docs), **community**
(third-party reproduction, GGUF conversion, tutorial, or forum report), or **inference** (this
document's own reasoning from the labeled evidence). Advertised minimum VRAM/RAM is never treated
as demonstrated feasibility on this workstation.

## Candidates investigated

FramePack (lllyasviel), LTX-Video 2B (`0.9.8-distilled` / `0.9.8-distilled-fp8`), LTX-2 (screened
separately per instruction), Wan2.2-Animate-14B, HunyuanVideo-1.5, and a landscape scan (SkyReels
family, Open-Sora 2.0, CogVideoX, MAGI-1/1.1, Kandinsky 5.0, Wan2GP as a runtime, not a model).

## Gate results by candidate

Gates: **A** whole-body motion capability · **B** identity/reference binding · **C** RTX 4070 Ti
12 GB feasibility · **D** 32 GB host-RAM feasibility · **E** Windows/Comfy runtime fit ·
**F** StableNew architecture fit · **G** licensing/support.

### FramePack — NOT RECOMMENDED (Gate C contradicted by evidence; Gate D undocumented)

- **A (official):** 13B Hunyuan-DiT-class I2V model using "next-frame-section prediction" to make
  generation length-invariant. No official or credible independent claim of superior whole-body
  locomotion/stepping specifically; its known strength is *long* clips, not *translational* motion.
- **B:** No official identity-preservation statement found either way. Unverified.
- **C (official vs. community-reproduced):** Official claim is 6 GB VRAM minimum for a 60 s/30 fps
  clip on the 13B model. **This claim is directly contradicted by a live, unresolved upstream
  report**: [GitHub issue #774](https://github.com/lllyasviel/FramePack/issues/774) — an RTX 4000
  (8 GB VRAM, 128 GB host RAM, Windows 11, official installer, default settings) used ~7.7 GB VRAM
  **and ~62.5 GB shared/host memory** to process a *1-second* clip from a 320×200 image, then
  failed with CUDA OOM. No maintainer response is recorded. This is exactly the kind of
  hardware/reliability counter-evidence this package is instructed to weigh over the advertised
  number.
- **D:** No official host-RAM figure at all. The 62.5 GB shared-memory spike above is the only
  concrete data point, and it is far above a 32 GB target.
- **E:** Windows one-click installer exists as a standalone Gradio app. **No official ComfyUI
  integration.** Community nodes exist (`ComfyUI_RH_FramePack`, `ComfyUI-FramePack-HY`,
  `TTPlanet_FramePack`) but are third-party, of uneven maturity, and not part of the model's own
  release process.
- **F (inference):** A standalone app plus unofficial Comfy nodes is a materially weaker
  architecture fit than a native ComfyUI workflow; adopting it would likely mean either running a
  second standalone runtime (a new process/lifecycle authority StableNew does not have) or trusting
  an unofficial node's graph translation.
- **G:** Permissive, Hunyuan-lineage licensing; acceptable in isolation.
- **Verdict:** Fails Gate C on direct contradicting evidence (not merely "unverified"), Gate D is
  undocumented with one bad data point, and Gate F is weak. Not recommended for qualification.

### LTX-Video 2B (`0.9.8-distilled` / `-fp8`) — NOT RECOMMENDED (maintenance trajectory)

- **A:** No official or independent claim that the 2B line specifically solves whole-body
  locomotion; it was positioned for speed/lightweight generation, not motion strength.
- **B:** No 2B-specific identity-binding evidence found.
- **C/D:** The only official hardware statement in the current `Lightricks/ComfyUI-LTXVideo`
  README targets the *current* (13B/22B-class) LTX line at 32 GB+ VRAM with FP8/offload strategies
  bringing it toward 16 GB; no official 2B-specific ≤12 GB VRAM or ≤32 GB RAM statement was found
  either way.
- **E/F:** Comfy-native support is real and official (`Lightricks/ComfyUI-LTXVideo`) — the best
  runtime/architecture fit of any candidate researched, *if* the 2B path were otherwise strong.
- **Maintenance (official, decisive):** Lightricks' active release cadence has moved to the LTX-2
  line — LTX-2 (Jan 2026), LTX-2.3 (Mar 2026), LTX-2.5 (Aug 2026) — all of which require 32 GB+
  VRAM per official guidance (see LTX-2 below). The legacy 2B checkpoints remain downloadable and
  the repo is not archived, but the company's own product and support attention has visibly shifted
  away from the 2B line, and the task's own brief notes pose/depth/canny control assets may be
  13B-only, meaning the 2B path may lack current control-mode parity.
- **Verdict:** Best architecture fit of any candidate, but no evidence it solves the identity/motion
  gap, and a real maintenance-trajectory risk (the vendor's own product line has moved past it,
  with the successor line already a hard hardware NO-GO). Deprioritized, not selected.

### LTX-2 (and 2.3/2.5) — NO-GO (per instructed default; confirmed, not overturned)

- **Official:** `Lightricks/ComfyUI-LTXVideo`'s official guidance is a CUDA GPU with 32 GB+ VRAM
  and 100 GB+ free disk; "comfortable 1080p" is described elsewhere as needing ~40 GB.
- **Community counter-evidence:** FP8 + FP4-mixed text encoder + sequential CPU offload has been
  reported down to 16 GB VRAM; one forum report claims 6 GB VRAM + **44 GB host RAM** for a 720p/
  10 s clip. That 44 GB figure alone already exceeds this project's 32 GB host-RAM target even in
  the most aggressive community-reported configuration.
- **Verdict:** No credible officially-supported ≤12 GB VRAM path exists, and the most permissive
  community path still exceeds the 32 GB RAM target. **NO-GO without physical qualification**, per
  the instructed default. Not reconsidered further in this package.

### Wan2.2-Animate-14B ("Move" mode) — STRONGEST CANDIDATE; ONE UNRESOLVED HARD GATE

- **A (official, strong):** Move mode drives a reference character's motion from an actual driving
  video via dedicated pose/face-extraction branches (`comfyui_controlnet_aux` in the official
  ComfyUI workflow), rather than relying on a text prompt to produce stepping. This is a genuine
  *architectural* answer to the PR-VID-150 gap — walking, turning, and weight transfer are supplied
  by the driving video's actual motion, not requested in natural language and hoped for.
- **B (official, favorable vs. the VID-110 VACE failure):** Identity is carried by a single
  reference image on a separate conditioning path from motion, which is the deliberate design fix
  for the weak-reference-binding failure mode PR-VID-110 recorded for Wan2.1 VACE (VACE reproduced
  a *different* person with the driving clip's motion; Animate's stated design goal is to keep the
  reference person's identity while only importing motion).
- **C (mixed; corrected below):** The official `docs.comfy.org` Wan2.2-Animate workflow page states
  the required components (the fp8/bf16 diffusion checkpoint, `wan_2.1_vae`, `umt5_xxl` text
  encoder, `clip_vision_h`, plus the official workflow's additional `KJNodes` and
  `comfyui_controlnet_aux` custom-node dependencies for pose/face extraction) but **does not state
  a specific VRAM minimum** — its only memory-related guidance is to "use a small size for video
  generation, in case you don't have enough VRAM." The "24 GB+ for smooth 720p" figure in earlier
  drafting of this document was sourced from third-party tutorial/guide sites (e.g. Apatero,
  NextDiffusion-style guides surfaced in search results), not from official Wan-AI or Comfy
  documentation, and is corrected here to **community** evidence rather than an official
  requirement. Separately, a community GGUF conversion (`QuantStack/Wan2.2-Animate-14B-GGUF`) via
  the mature, widely-used `city96/ComfyUI-GGUF` node is reported (**community**) working at 12 GB
  VRAM up to Q8 with a 25-frame loop; Q4_K_M is reported at ~10–12 GB. **Official upstream does not
  establish a supported 12-GB Wan2.2-Animate path. Community GGUF/offload evidence makes 12-GB
  execution plausible enough to justify a bounded feasibility probe, but exact RTX 4070 Ti 12-GB
  VRAM and 32-GB host-RAM feasibility remain unproven.**
- **D (the decisive open risk):** This is the gate that cannot be resolved from secondhand evidence:
  - **Community** guidance (tutorial/guide sites, not an official Wan-AI/Comfy source) for T5-XXL
    CPU offload on the base Wan-14B line states "32 GB minimum, strongly recommended" for that
    offload strategy — i.e., our exact ceiling, with zero documented margin. No official upstream
    source stating an explicit host-RAM minimum for Wan2.2-Animate was found either way.
  - An **open, unresolved** upstream issue on `kijai/ComfyUI-WanVideoWrapper` — the same wrapper
    the official Animate workflow references for its fp8 checkpoint —
    ([#1017](https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1017)) reports a 64 GB-RAM /
    24 GB-VRAM machine consuming 100 GB+ combined RAM+swap ("eating swap alive") running plain
    Wan2.2 I2V at only 480p, with no maintainer response recorded.
  - StableNew's **own accepted telemetry** (PR-VID-140/150) already shows the much smaller 5B
    Wan2.2 model driving available host RAM to **~0.01–0.02 GB free** on this exact 32 GB machine.
    A 14B backbone plus additional pose/face-extraction branches is not expected to reduce that
    pressure, and has credible (if unresolved) upstream reports of materially worse behavior in
    the same model family and wrapper ecosystem.
  - This is real, evidence-backed risk, not a hypothetical one — it is the one gate this research
    package cannot close from documentation and forum evidence alone.
- **E (official):** Native ComfyUI workflow is documented at `docs.comfy.org`; Windows-compatible;
  no new external runtime.
- **F (inference, strong):** Same `backend_id="comfy"`, same StableNew-managed Comfy process. It
  could be cataloged as one more `workflow_id` entry alongside `wan22_ti2v_5b_i2v_v1` in the
  existing workflow catalog, routed through the unchanged `VideoExecutionResolver` /
  `VideoBackendRegistry` / `ComfyWorkflowVideoBackend`. The pose/face-extraction nodes are ordinary
  additional Comfy graph nodes, consistent with how ComfyUI workflows are already treated as opaque
  graphs behind the existing backend. No new queue, runner, or lifecycle authority is implied.
  (`Wan2GP`, a separate standalone low-VRAM runtime that also runs Wan2.2-Animate at ~12 GB VRAM,
  was found and is explicitly **not** recommended as an integration path — it is its own runtime
  and would require a new process-manager/lifecycle authority StableNew does not have. It is useful
  only as independent confirmation that a 12 GB-VRAM Wan2.2-Animate path exists somewhere in the
  ecosystem.)
- **G (official):** Apache 2.0 — same license already accepted for Wan2.2.
- **Maintenance (official):** Released September 2025, actively developed through 2026 (community
  GGUF conversions and Civitai/HF workflow activity ongoing), same lineage as the already-integrated
  Wan2.2 TI2V-5B.
- **Verdict:** Passes A, B, E, F, G on real evidence; C is plausible but unconfirmed at our exact
  settings; **D is the one hard, evidence-backed open question.**

### HunyuanVideo-1.5 — NO-GO on official hardware gate (per instructed policy)

- **Official minimum:** 14 GB VRAM with offloading — exceeds the 12 GB hard target.
- Community Q4/Q6 GGUF builds ("cosy variants") report 8–12 GB feasibility, but per this package's
  explicit instruction not to invent an unsupported quantization project merely to keep a candidate
  in contention, and since the *official* number remains 14 GB, this candidate is classified
  **NO-GO** on Gate C. Deprioritized; not carried into the decision framework further.

### Landscape scan — no newer candidate displaces Wan2.2-Animate

- **SkyReels-A2:** Wan2.1-based dual-stream reference injection for subject-to-video; older
  backbone, no locomotion-specific claim beyond general subject composition. Not a clear
  improvement over Wan2.2-Animate on either motion or identity.
- **MAGI-1 / MAGI-1.1:** The only currently *released* weights (24B) require 8×H100; the announced
  single-consumer-GPU 4.5B variant is not yet released. Not a current candidate.
- **Kandinsky 5.0 T2V Lite (2B):** Reported to run on 12 GB, but it is **text-to-video**, not
  image/reference-conditioned — wrong modality for this use case (source-image-driven directed
  motion). Screened out on input mode, not hardware.
- **Open-Sora 2.0, CogVideoX:** General-purpose T2V/I2V models with no specific human-locomotion or
  identity-binding claim found that would exceed Wan2.2-Animate's Move-mode design.
- No candidate found in this scan meets all of: image/reference-conditioned, strong claimed human
  body motion, plausible ≤12 GB VRAM, plausible ≤32 GB RAM, Windows/Comfy fit, usable licensing,
  and current maintenance, better than Wan2.2-Animate-14B does.

## Decision framework outcome

| Gate | FramePack | LTX-Video 2B | LTX-2 | Wan2.2-Animate-14B | HunyuanVideo-1.5 |
|---|---|---|---|---|---|
| A — whole-body motion | unverified | unverified | N/A (eliminated) | **official design goal** | unverified |
| B — identity/reference binding | unverified | unverified | N/A | **official design goal** | unverified |
| C — 12 GB VRAM | **contradicted** | unverified | **NO-GO** | plausible (community) | **NO-GO** (official) |
| D — 32 GB host RAM | undocumented, 1 bad data point | undocumented | **NO-GO** | **open risk, real evidence both ways** | eliminated |
| E — Windows/Comfy | standalone + 3rd-party nodes | official Comfy-native | N/A | **official Comfy-native** | eliminated |
| F — architecture fit | weak | strong | N/A | **strong** | eliminated |
| G — licensing | acceptable | acceptable | N/A | **acceptable, already accepted for Wan** | eliminated |
| Maintenance | active | **deprioritized by vendor** | N/A | **active, same lineage as accepted Wan** | eliminated |

No candidate cleanly clears every gate. Wan2.2-Animate-14B is the only candidate that clears every
gate except one, and clears it on genuine architectural/official-design evidence rather than
marketing claims. The one open gate (D, host RAM) is not a generic "more research needed" gap — it
is a specific, evidence-backed risk carried over from StableNew's own accepted Wan2.2 telemetry and
a real (if unresolved) upstream report in the same wrapper ecosystem the official workflow depends
on. This package's evidence cannot resolve Gate D by further reading; it requires one bounded,
StableNew-specific physical measurement to close.

## Required conclusion

**`BOUNDED_FEASIBILITY_PROBE_REQUIRED`**

Not because two candidates are tied — Wan2.2-Animate-14B (Move mode, GGUF-quantized, via the
existing managed-Comfy path) is the clear single lead, and every other researched candidate is
eliminated or materially weaker on the evidence above. The probe exists to resolve the one gate
(host-RAM feasibility at our exact 32 GB target) that secondhand documentation and forum evidence
cannot settle, before authorizing a full three-case physical motion characterization of the kind
PR-VID-150 ran for Wan2.2 TI2V-5B.

## Proposed next package (not authorized by this package)

**`PR-VID-160B — Wan2.2-Animate Target-Hardware Feasibility Probe`**

This is a **resource feasibility probe**, not a full motion-quality qualification, and is not
authorized here. Its first question is:

> Can the smallest credible Wan2.2-Animate GGUF/quantized Comfy path complete one bounded short
> Move-mode generation on RTX 4070 Ti 12 GB + 32 GB RAM without resource exhaustion, shared-memory
> collapse, GPU loss, or violating StableNew runtime ownership?

Only after that question passes should character-identity and locomotion quality be characterized
in a separate, later package.

If a future package is separately authorized to proceed:

1. Stage the smallest viable Wan2.2-Animate-14B GGUF asset set (Q4_K_M or Q8 quant, VAE, CLIP
   vision, text encoder, pose/face-extraction assets) behind the existing managed-Comfy process —
   this is model installation and is explicitly **not** authorized here.
2. Run **one** minimal, short-loop generation (e.g., the smallest supported frame count/loop, not
   PR-VID-150's full 49-frame case) through the canonical production path, with the existing
   `ResourceSampler` telemetry attached, watching `ram_available_min_gb` specifically.
3. Apply a hard stop rule: if available host RAM approaches exhaustion, the existing production
   resource-readiness guard blocks, shared-memory collapse is observed, or GPU loss occurs — stop
   and report; do not retry, do not lower the guard, and do not violate StableNew's existing
   runtime-ownership rules (no adopting/restarting an unmanaged process).
4. This single bounded run's purpose is narrowly the resource-feasibility question above — not to
   re-run PR-VID-150's A/B/C prompt-structure comparison, which is already answered, and not to
   characterize identity or locomotion quality yet.
5. Only if that probe survives cleanly should a PR-VID-150-style bounded motion-transfer
   characterization (identity retention, locomotion quality, varying driving-video complexity) be
   proposed as a separate, explicitly authorized package.

## StableNew architecture review

The selected candidate (Wan2.2-Animate-14B, if a future probe clears Gate D) maps onto the existing
architecture without new authority, conceptually reusing the same canonical path already accepted
for Wan2.2 TI2V-5B:

`Intent -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> VideoExecutionResolver
-> existing Comfy VideoBackend -> Artifact/History`

- Reuses the existing `VideoExecutionResolver` and `VideoBackendRegistry` — no new backend-selection
  authority.
- Reuses the existing managed Comfy process (`ComfyProcessManager`) — no new process manager.
- Would be cataloged as one more workflow-catalog entry (spec + experimental gate + resource-
  readiness policy), the same pattern `wan22_ti2v_5b_i2v_v1` already uses.
- Reuses the existing queue/history/replay/provenance path unchanged.
- The only genuinely new surface is the additional prepared-input type (a driving video, not just
  a still image) for Move mode, which fits the existing catalog-declared source-preparation pattern
  used for Wan2.2's image preparation and would need its own bounded declared preparation step —
  not a new lifecycle authority, but real new code if ever implemented.
- No candidate researched here would require a second production queue, runner, or history
  authority; `Wan2GP` (the one runtime that would require that) is explicitly not the recommended
  integration path.

## Resource-risk reconciliation

- PR-VID-140: Wan TI2V-5B landscape, ~11.6 GB VRAM peak, host RAM as low as ~0.01 GB available.
- PR-VID-150: three more Wan TI2V-5B runs, ~11.6–11.7 GB VRAM peak, 72–77 °C, 243–249 W, clean idle
  return, no crash recurrence.
- DIAG-GPU-120: remains observation-only; this package adds no new physical exposure.
- Wan2.2-Animate-14B is a **larger** model than the already-tight TI2V-5B baseline and is not
  expected to reduce host-RAM pressure; it is proposed here only behind a single bounded probe with
  an explicit stop rule, not a repeated qualification matrix.

## Remaining uncertainties

- Whether the community GGUF 12 GB VRAM reports hold at our exact 480×832/49-frame-equivalent
  settings (Gate C, plausible not confirmed).
- Whether 32 GB host RAM survives a Wan2.2-Animate-14B cold load on this exact machine (Gate D,
  the decisive unresolved question).
- Whether Move-mode motion transfer actually preserves identity as well as its design goal claims
  under real StableNew source material — this is a qualification question, not something this
  research package can answer.
- Whether current pose/face-extraction custom-node dependencies (`comfyui_controlnet_aux`) are
  compatible with StableNew's existing Comfy dependency-check pattern without modification.

## Validation

Research/documentation only. No tests, no ruff-relevant source, no GPU workload. `git diff --check`
run on the new file.

## Explicit confirmations

No model was downloaded or installed. No Python/CUDA/driver/environment change was made. No GPU
generation ran. No production `src/` file changed. No queue/history/runner/backend authority
changed. Wan production settings/governance are unchanged; Wan2.2 TI2V-5B remains the only
integrated Wan workflow and remains experimental. Integrating this research/decision document does
not authorize PR-VID-160B physical qualification, model installation, or environment mutation; it
only accepts the feasibility-probe direction and recommends the smallest next probe.
