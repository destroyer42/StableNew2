# PR-VID-184 - Wan-Animate-2 Reference Capability, Target-Hardware & Integration Feasibility

Status: **`PR-VID-184 — IN PROGRESS — PHASE A-C/F COMPLETE; PHASE D BLOCKED PENDING OWNER
AUTHORIZATION`**. This is a research/feasibility-planning package. No Animate-2 output has been
generated, no Comfy Cloud run has occurred, no production `src/` change was made, no workflow was
registered, and no GPU/Comfy-config/pagefile/driver setting was changed. Q1-Q4 (see below) are not
yet answered; Phase D (the remote official-Comfy reference-capability gate) is the blocking
prerequisite and requires two explicit owner decisions before it can run (see "Phase D status and
owner decisions required").

## Execution profile

- **Execution class:** Terra High equivalent — bounded multi-source research, evidence-anchored
  planning, and qualification-tooling authoring; no architecture decision made.
- **Model/reasoning recommendation:** Claude Sonnet 5, High effort for synthesis/writing; a
  general-purpose web-research subagent (current, dated, source-tagged) for Phase A, per the
  repository's provider-neutral Terra guidance.
- **Controller surface assessment:** none. No `src/` production controller, coordinator, resolver,
  backend, runner, or graph changed. `src/video/video_backend_types.py` and
  `src/video/video_workflow_intent.py` were inspected read-only for Phase F contract mapping.
- **Token-efficient validation plan:** deterministic scoring-contract tests only (no GPU/network);
  Ruff/format on the new Python surfaces; `git diff --check`; required GitHub Python 3.11/3.12 CI.
  Do not chase informational full-suite/Journey debt unrelated to this package.

## Accepted prior evidence (not repeated)

PR-VID-150 through PR-VID-183 discovery is treated as established (see `STATUS.md` and each
package's own report under `docs/Subsystems/Video/`). In particular: native SVD XT remains the only
production/default backend; Wan2.2 TI2V-5B prompt-directed motion is
`local_motion_viable_locomotion_weak`; Wan2.2-Animate v1 became resource-feasible and 480x832
interpretable, real detector-derived pose materially improved gesture transfer, but clean
reference-bound locomotion/root translation was never demonstrated — locomotion repeatedly produced
either a planted reference subject or a separate moving/ghost figure, including after basic
retargeting (PR-VID-183: `BASIC_RETARGET_APPLIES; REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`).
Background instability remained cross-case. Animate v1 remains unregistered. This package does not
spend further effort tuning Animate v1, `face_video`, FLUX enhanced retargeting, sampling settings,
or more v1 pose preprocessing.

---

## Phase A — Current upstream / Comfy inventory

Researched 2026-09-26 via a dedicated web-research pass (current sources only; first-party facts
distinguished from community reports; no community anecdote used as acceptance evidence).

**Naming.** The model is "Wan-Animate-2" (paper/GitHub org) but shipped files/HF repos use
"Wan2.2-Animate-2-14B" branding; both names refer to the same released model. [FIRST-PARTY]

1. **Upstream repo/release.** `github.com/Wan-Video/Wan-Animate-2` (Wan-Video org, Alibaba Tongyi
   Lab). Released 2026-08-07: inference scripts plus Base and Distillation weights. Paper:
   arXiv:2608.06009, "Wan-Animate-2: Pushing the Application Boundaries of Character Animation"
   (submitted 2026-08-06). HF model: `Wan-AI/Wan2.2-Animate-2-14B`. [FIRST-PARTY]
2. **Released variants.** Base (14B) and Distillation are actually released (weights + code,
   2026-08-07). **Lite is NOT released** — described in the paper/README as a real-time
   self-forcing-distillation method, but no weights/code are out; two open, unanswered upstream
   issues (#2, #4, opened 2026-08-09/08-11) ask when/if it will ship. [FIRST-PARTY]
3. **License.** Apache License 2.0 (GitHub README + HF model card). No commercial restriction
   found. [FIRST-PARTY]
4. **Official inference settings.** Base: 40 sampling steps with classifier-free guidance,
   demonstrated up to 720P (8xA800) / 480P (2xA800) in the README's own example flags. Distillation:
   `--step 10`, `--sample_guide_scale 1.0` (no CFG). [FIRST-PARTY, GPU-count/resolution pairing
   lightly paraphrased from README prose]
5. **Official Comfy workflows — the working hypothesis is confirmed.** Two distinct official
   supported-model pages exist:
   - Base-oriented: `wan_animate_2_int8_convrot.safetensors` (INT8 ConvRot) used with the LightX2V
     LoRA `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` for step-reduced sampling.
   - Native distilled: `wan_animate_2_distill_int8_convrot.safetensors`, a separate model file.
   Official tutorial: `docs.comfy.org/tutorials/video/wan/wan-animate-2`, template
   `video_wan_animate2`. **Both INT8 ConvRot files are quantized — neither is pristine bf16 upstream
   Base.** A `wan_animate_2_bf16.safetensors` full-precision file exists separately for users who
   want unmodified Base weights (and `wan_animate_2_distill_bf16.safetensors` for unmodified
   Distillation). So: the "official Comfy Base-oriented workflow" is an accelerated/modified Base,
   not pristine upstream Base. [FIRST-PARTY; some exact filenames via page summarization, corroborated
   across two independent fetches]
6. **Comfy version/nodes.** Docs specify current/nightly ComfyUI (announcement 2026-08-08). No
   third-party custom nodes required — implemented as core ComfyUI nodes (`WanAnimate2ToVideo`,
   `WanAnimate2Cache`, `WanAnimate2LoopSampler`). [FIRST-PARTY]
7. **Assets.** Model/LoRA/text-encoder/CLIP-vision/VAE filenames are listed in the paragraph above
   and the tutorial; **no file sizes were surfaced** in any reachable source. [FIRST-PARTY names /
   UNKNOWN sizes]
8. **Frame/geometry conventions.** The official `WanAnimate2Cache` doc's own reference example uses
   480x832, 81 frames, bf16. Comfy Cloud's landing page cites "81 frames, 18 fps, 640x640, 4-step"
   as its credit-cost example. 720P/480P are the named supported tiers. An open, unresolved upstream
   issue (#1, opened 2026-08-09) reports driving-clip length effectively capped near 5 seconds in
   practice (81 frames at ~16 fps is ~5.06 s) — consistent with 81 frames being close to the
   practical duration ceiling, not an arbitrary example number. [FIRST-PARTY figures; COMMUNITY
   practical-ceiling complaint]
9. **`WanAnimate2Cache` — confirmed speed-for-memory tradeoff, hypothesis correct.** It caches the
   pose-branch per-block activations once so they are not recomputed every sampling step, roughly
   **halving generation time** at the cost of **extra memory** (~12.5 GB system RAM at
   480x832/81 frames/bf16, scaling with resolution/length/context-window count). It defaults to
   `device="cpu"` (RAM) because VRAM usually cannot hold cache plus model; int8/int4 cache-dtype
   options reduce but do not eliminate the cost; only the `static_standard` schedule reuses the
   cache correctly. This is unambiguously a speed-for-memory tradeoff, not a memory saver: the
   "default OFF for memory-constrained qualification" recommendation is well-supported by the
   documented mechanism, now with a concrete quantified cost (~12.5 GB extra RAM). [FIRST-PARTY]
10. **RAM/VRAM/consumer-GPU evidence.** No official 12-GB-class benchmark was found for Wan-Animate-2
    specifically. A materially relevant open first-party bug report exists: **upstream issue #5**
    (opened 2026-08-12, unresolved) — `set_default_dtype` is called *after* the transformer is
    built, so the DiT may end up resident in fp32 instead of bf16 on **single-GPU** setups (roughly
    65.6 GB vs. an expected ~32.8 GB); multi-GPU sharded setups mask the bug. **This is directly
    load-bearing for the RTX 4070 Ti 12 GB single-GPU target** (see Q2/Phase E) and is treated as an
    open risk, not a confirmed blocker, since it has not been independently reproduced here.
    General Wan2.2-family community guidance (not Animate-2-specific) recommends GGUF-quantized
    loaders and small resolutions for 8 GB cards and warns full fp16 will OOM a 12 GB card; no direct
    Wan-Animate-2 12 GB OOM report was found. [FIRST-PARTY bug report #5; COMMUNITY general Wan2.2
    guidance, not confirmed Animate-2-specific]
11. **Comfy Cloud compatibility.** A live "Run Wan Animate 2" template exists at
    `comfy.org/wan-animate-2/`; the cloud Templates panel is kept current with stable ComfyUI
    releases. Pricing: Standard/Creator/Pro/Team tiers at $20/$35/$100/$700/month (~20% less billed
    yearly), metered via GPU-time credits (4,200/7,400/21,100/147,700 respectively); a 5-second
    Wan2.2-class video costs roughly ~11 credits. **5 free GPU runs are offered with no card
    required.** Whether the cloud template runs the official workflow completely unmodified versus a
    Comfy-hosted variant was **not confirmed** by any reachable source. [FIRST-PARTY pricing/
    availability; UNKNOWN on unmodified-workflow claim]
12. **Driving-video ingestion — confirmed single-stage.** "The driving video goes straight into the
    transformer. No intermediate motion extractor sits between your source footage and the model"
    (official announcement), matching the paper's decoupled dual-branch attention / time-aligned
    positional encoding / sparse reference attention claims. This removes the v1 intermediate
    pose-extractor chain entirely. [FIRST-PARTY]
13. **Reference-bound locomotion / identity binding / ghosting — the single most important, and
    weakest-answered, question.** The paper claims improved motion fidelity and identity
    preservation, including cross-identity transfer across very different body shapes, attributed to
    removing the old pose-extractor chain — but this is the authors' own claim, not independent
    validation. A credible independent counter-report exists: **upstream issue #6** (opened
    2026-08-22, unresolved) reports character-consistency drift, with InsightFace similarity scores
    dropping to 40-50% in non-degenerate views. **No first-party or community source specifically
    addresses "ghosting"/duplicate-person artifacts during walking/locomotion** — no locomotion
    benchmark or gallery example was found either confirming or ruling this out. **Net: the exact
    PR-VID-181/183 failure mode (planted reference subject with motion carried by a separate
    figure) is neither confirmed nor ruled out anywhere in current upstream/community sources for
    Wan-Animate-2.** This is why Phase D's own controlled test — not further literature review — is
    the only way to answer Q1.
14. **Other current open upstream issues** (all unresolved as of 2026-09-26): #7 multi-camera
    animation control unclear (2026-09-21); #6 identity drift (see 13); #5 possible fp32/2x-memory
    bug (see 10); #4/#2 Lite release status (see 2); #1 practical duration ceiling (see 8); #3
    README correction request (2026-08-10).

### Base vs Distilled

Neither is assumed superior. The **official Comfy Base-oriented path** (INT8 ConvRot + LightX2V
LoRA) is an accelerated/modified Base, not pristine upstream Base — a separate unaccelerated
`wan_animate_2_bf16.safetensors` exists for anyone who wants the pristine checkpoint. The **official
Comfy native Distilled path** (`wan_animate_2_distill_int8_convrot`) is upstream's own distillation,
using lower-step/no-CFG-style inference per current upstream settings (`--step 10`,
`--sample_guide_scale 1.0`).

---

## Phase B — Frozen reference-capability experiment (not yet run)

The strongest existing candidate is **PR-VID-181 Case B** ("Mixkit #583 — Woman doing warm-up
exercises," a real single-person stock clip): one intended person, clear lateral
locomotion/root-translation across the frame (driving-control centroid moved 0.29 -> 0.69 of frame
width), static camera, full body visible, no bystanders. It is the same case PR-VID-181/183 already
used, so reusing it preserves direct historical comparability against the documented Animate-v1
failure (`ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY` / `BASIC_RETARGET_APPLIES;
REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`).

**Blocker 1 (license) is resolved by explicit owner risk-acceptance, not by a favorable license
reading.** Direct verification of Mixkit's actual terms (`mixkit.co/terms/`, `mixkit.co/llm-info/`,
corroborated by an independent third-party license guide) found the operative clause: *"rent,
license, sublicense, sell, resell or otherwise commercially exploit or make Mixkit or any Item
available to any third party,"* summarized elsewhere as *"cannot redistribute raw, unedited clip
files... on any platform."* No source found an explicit carve-out for using a clip as input to a
third-party AI/ML processing service, and Mixkit's own AI-focused FAQ page (`mixkit.co/llm-info/`)
does not address AI/ML use at all. This remains genuinely ambiguous, not clearly permitted. The
product owner was given this exact finding and explicitly directed proceeding anyway, on the basis
that a two-run internal qualification test (not redistribution, not a competing stock-media use) is
low-risk enough to accept: **"Accept the risk explicitly... a two-run internal qualification test,
not redistribution or competing-service use, is low-risk enough to proceed anyway"** (owner
decision, 2026-09-26). This authorizes uploading this specific clip to Comfy Cloud for this specific
two-run (Case A/B) qualification test; it is not a general finding that the license permits
third-party AI use, and does not extend to any other reuse.

**Blocker 2 (duration) is a recorded limitation, not resolved.** The existing driving window is
1.2 s / 29 frames at 24 fps. Phase A found the practical duration ceiling for Wan-Animate-2 sits near
81 frames / ~5 s (item 8); using the existing 1.2 s window materially under-fills that envelope and
weakens the "prefer the normal 81-frame reference envelope" instruction, though it does not
invalidate a shorter-window test on its own. Proceeding with the existing PR-VID-181 case accepts
this as a documented caveat on Case B's result, exactly as PR-VID-181/183 already did for their own
generations.

**Still blocking Phase D:** the separate Comfy Cloud account-creation/upload authorization (see
"Phase D status and owner decisions required" below) has not yet been given.

No source/reference substitution has been made. The PR-VID-181 Case A (gesture)/Case B (locomotion)
pair is therefore the frozen Phase D case, pending only the remaining Comfy Cloud
account/upload authorization below. Reusing `identity_hist_mean` and
`camera_drift_px`/`motion_area_fraction` metrics from `tools/qualification/vid110/metrics.py`
remains planned for scoring once the runs execute; no new metric implementation was needed for
those three.

---

## Phase C — Pre-registered scoring contract (frozen)

`tools/qualification/vid184/scoring_contract.py` freezes the Phase D/E evaluation plan **before**
any Animate-2 output exists, with `FROZEN_CONTRACT_SHA256` pinning the exact metric set/thresholds
(`tests/tools/test_vid184_scoring_contract.py`, 8 deterministic tests, no GPU/network, all passing).

| Metric | Gate | Threshold | Anchor |
| --- | --- | --- | --- |
| `motion_curve_correlation` | pass/fail | >= 0.30 | PR-VID-181 Case A (accepted pass) = 0.419; Case B (accepted fail) = -0.132; synthetic noise floor (PR-VID-180) = -0.089 to 0.005 |
| `root_translation_fraction` | pass/fail | >= 0.15 | PR-VID-181's own driving control moved 0.40 of frame width; the documented failure case produced ~0 displacement |
| `primary_subject_continuity` | pass/fail | >= 0.90 frame coverage | New metric; deliberately cannot alone detect a planted-but-present subject — must be read with `root_translation_fraction` |
| `ghost_actor_persistence` | pass/fail | <= 2 consecutive frames | PR-VID-181/180 documented a persistent second figure carrying the driven motion while the reference stayed planted |
| `identity_hist_mean`, `camera_drift_px`, `motion_area_fraction` | corroborating only | none | PR-VID-181 states these are corroboration, not sole truth, and that background hallucination contaminates optical flow |
| `human_visual_rubric` | manual, raw 1-5, not averaged | none (qualitative) | Same rubric/convention as PR-VID-181/183 |

`motion_curve_correlation`, `identity_hist_mean`, `camera_drift_px`, and `motion_area_fraction` are
**reused** from `tools/qualification/vid110/metrics.py` (`motion_curve`, `curve_correlation`,
`clip_metrics`) without modification. `primary_subject_continuity` and `ghost_actor_persistence`
are **new** and require the disposable CPU-only person-detector environment used by
`tools/qualification/vid181/preprocess_launcher.py`; their thresholds are frozen now so they cannot
be tuned after seeing results, but their executable implementation is deferred to Phase D/E, which
has not been authorized (see below). No threshold was chosen after viewing any Animate-2 output —
none has been generated.

---

## Phase D status and owner decisions required (BLOCKED — not yet run)

Phase D requires Comfy Cloud execution of the official Base-oriented and native Distilled workflows
against the frozen Case A/B driving/reference pair, at the normal official 81-frame envelope where
supported. **This has not happened.** Per this package's own external-service authorization
boundary and Hard Stops, one explicit owner decision remains before it can proceed:

1. **Driving-video license/source decision — RESOLVED 2026-09-26 by explicit owner risk-acceptance.**
   See "Phase B" above: the license terms are genuinely ambiguous (verified directly, not assumed);
   the owner was given that exact finding and explicitly directed proceeding with the existing
   PR-VID-181 Case A/B Mixkit clips for this specific two-run internal qualification test, accepting
   the disclosed risk. This is not a finding that the license clearly permits the use.
2. **Cloud account/upload authorization — STILL OPEN.** Comfy Cloud offers 5 free GPU runs with no
   card required (Phase A item 11), so the two planned runs (Case A, Case B) may be able to complete
   at **zero monetary cost** if that free-tier claim holds and no payment method is required to
   create the account. Regardless of cost, this package does not create a third-party account or
   upload any media without explicit owner authorization naming the provider (Comfy Cloud) and
   confirming acceptance of its retention/privacy terms (not independently verified beyond the
   pricing/availability facts in item 11). If the free tier turns out to require payment info or is
   otherwise unavailable, report that and stop before incurring any cost.

No files have been uploaded and no cloud spend has occurred. Per this package's own instruction,
completing this no-cost/no-upload preparation and asking once is sufficient; **this same
session/package resumes once authorization is given rather than requiring a new work-package
prompt.**

Q1 (reference-bound locomotion capability) cannot be answered without Phase D. Given Phase A item
13's finding that no upstream/community source addresses the ghosting/locomotion question either
way, there is no literature substitute for running the controlled test.

---

## Phase E — Target-hardware feasibility (not started; gated on Phase D passing or being strong enough to justify local testing)

Not performed. Recorded here only as a Q2-relevant risk carried forward from Phase A: upstream issue
#5 (a possible fp32-residency bug doubling DiT memory to ~65.6 GB on single-GPU setups) is directly
adverse to the RTX 4070 Ti 12 GB / 32 GB RAM target and must be checked (patched/avoided or
confirmed not to reproduce) before any physical local budget is built, in addition to the existing
cache-OFF-by-default and CUDA Sysmem Fallback research the package specifies. No local Animate-2 GPU
workload has run, and none is authorized in PR-VID-184 regardless of Phase D's outcome.

---

## Phase F — Backend-neutral contract mapping (complete; read-only, no production change)

Inspected `src/video/video_backend_types.py` and `src/video/video_workflow_intent.py`.

- `src/video/video_backend_types.py` defines `KNOWN_VIDEO_CONTROLS` including
  `CONTROL_CONTROL_VIDEO` ("control_video") and `CONTROL_POSE_VIDEO` ("pose_video") as backend-neutral
  semantic input forms on `VideoExecutionRequest`. Confirmed unchanged by this package.
- `src/video/video_workflow_intent.py` currently contains **no reference** to `control_video` or
  `pose_video` (confirmed via search) — the Video Workflow producer does not yet emit either
  control, matching this package's starting fact.
- A raw Wan-Animate-2 driving video is a single continuous motion source consumed directly by the
  transformer (Phase A item 12), not a pre-extracted pose representation. It is closer in shape to
  the existing `pose_video` semantic (a video-shaped motion-conditioning input) than to
  `control_video` (which in the current contract is undifferentiated video conditioning generally),
  but neither existing control was defined with Wan-Animate-2's single-stage architecture in mind,
  and reusing `pose_video` for a raw un-preprocessed driving clip would be a semantic stretch — the
  existing v1 pipeline's `pose_video` was always a *rendered pose representation*, not a raw driving
  video. A future, distinct neutral concept such as `motion_source_video` is more honest to what
  Wan-Animate-2 actually consumes, but **no contract change is made in this package**: PR-VID-184
  does not add a new video task or control merely to reserve one, per this package's own
  instruction, and no Animate-2 integration is authorized yet regardless.
- `VideoExecutionRequest.workflow_inputs` (a `dict[str, Any]`) and `backend_options` (opaque,
  adapter-private) already exist and could carry a resolved driving-video path without any schema
  change, the same way other backend-specific inputs are threaded today — this was confirmed by
  reading the dataclass, not by adding code.
- Architecture requirement preserved: StableNew semantic intent must never expose Comfy node names
  (`WanAnimate2ToVideo`, `WanAnimate2Cache`), backend socket names, or model filenames; any future
  adapter would translate a neutral motion/control-source semantic into Comfy-specific inputs
  privately, exactly as the existing native-SVD and Wan2.2 v1 adapters already do.
- **Conclusion for Q3 (pending Q1/Q2):** the existing
  `Intent -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr ->
  VideoExecutionResolver -> backend_id=comfy -> versioned experimental workflow` path can carry a
  future Animate-2 adapter without adding a second queue, runner, process manager, lifecycle
  authority, or model-specific controller. The smallest future contract change, if capability and
  feasibility are both established, is likely a new neutral control (tentatively
  `motion_source_video`) rather than overloading `pose_video`; this is a recommendation for a future
  package, not a decision made or contract change applied here.

---

## Package outcome — Q1-Q4

- **Q1 (reference capability):** **NOT YET ANSWERED.** Blocked on Phase D (see above). No current
  upstream/community source resolves it either way (Phase A item 13).
- **Q2 (target-hardware feasibility):** **NOT YET ANSWERED.** Blocked on Q1 passing or being strong
  enough to justify local testing, per the decision tree (Phase G). A material new risk (upstream
  issue #5, possible fp32 2x-memory bug on single-GPU setups) is now on record for whoever runs
  Phase E.
- **Q3 (backend-neutral integration fit):** **Answered, conditionally.** Yes — the existing
  backend-neutral contract can carry a future Animate-2 adapter without adding a second queue,
  runner, lifecycle authority, or model-specific controller (Phase F). No production change was made
  or is authorized.
- **Q4 (product decision):** **Not reached.** The pre-decided decision tree (Phase G, Outcomes 1-5)
  requires Q1 first. No classification is assigned yet; `REMOTE_REFERENCE_GATE_BLOCKED` is not
  claimed as a terminal classification either, because the gate is blocked on pending owner
  authorization, not on a technical inability to run it (Comfy Cloud does host the required official
  workflows per Phase A item 11) — those are different situations and this package does not conflate
  them.

## Validation

- `tools/qualification/vid184/scoring_contract.py` and `tests/tools/test_vid184_scoring_contract.py`:
  `ruff check` clean, `ruff format --check` clean, `python -m pytest
  tests/tools/test_vid184_scoring_contract.py -q`: **8 passed**, no GPU/network/Comfy dependency.
- `git diff --check`: clean.
- No `src/` production file was modified; `src/video/video_backend_types.py` and
  `src/video/video_workflow_intent.py` were read-only inspected.
- No model, Comfy config, pagefile, driver, or GPU setting was changed. No workflow was registered.
  No cloud account was created and no media was uploaded.

## Docs / Git

New: this report, `tools/qualification/vid184/scoring_contract.py`,
`tests/tools/test_vid184_scoring_contract.py`, the `STATUS.md` entry, and the `docs/CODEX_MAP.md`
row for PR-VID-184. Not committed: any downloaded/cloud test media (none was downloaded or
generated in this package).

## What is explicitly NOT authorized next

- Any Comfy Cloud account creation, media upload, or spend, until the owner answers the remaining
  cloud-authorization decision above.
- Any local physical Animate-2 GPU workload (Phase E execution).
- Any production `src/` change, workflow registration, GUI/controller change, new backend, or model
  promotion.
- Any Comfy config, pagefile, driver, or GPU-setting mutation (including the CUDA Sysmem Fallback
  Policy research question, which remains research-only in this package).
- Beginning the local physical Animate-2 qualification or an experimental production vertical slice
  in this same package, even after Phase D authorization is given — those remain separate,
  separately authorized future packages per the decision tree (Phase G).
