# PR-VID-WAN-321F: A14B target-hardware feasibility

Two separate conclusions, deliberately not merged:

- **Owner acceptance (2026-10-23):** the feasibility investigation gave sufficient information to close the research
  objective, and the owner closed WAN-321F.
- **Frozen technical verdict: INCONCLUSIVE.** Teardown verification did not pass (`teardown.json` `verified: false`).
  This is not a successful qualification against every frozen criterion, and the verdict is not reclassified here.

What one physical session showed: all three attempts produced 81 valid frames inside the limits with no safety stop,
device loss or allocation failure. See "Physical session result" and "Owner disposition".
No physical-quality claim. This evidence does not authorize WAN-321 integration.

Execution profile: Standard, qualification-only. Model recommendation: Claude Code Sonnet 5.5 High /
Codex GPT-6.1 Sol High, Local/Desktop for local assets and Windows evidence. Expected order of magnitude:
1M cache-read / 20k output tokens. Controller Surface Assessment: no controller/coordinator or production
code changes. Token-Efficient Validation Plan: focused deterministic qualification controls plus existing
workflow-version preservation tests; one canonical local gate using the existing Python 3.14 `.venv`;
hosted CI only after separately authorized publication. No environment rebuild.

## Authority and scope

Base: `991aebc6c409b7174d7d10e2df20b337f28fbc5d`, local `main` / cached `origin/main`, checked out
initially at `C:/Users/rob/projects/StableNew-main`. Worktree:
`C:/Users/rob/projects/StableNew-main/tmp/wan321f`, branch `qual/wan321f-a14b-480p`.
Root `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md`, `VIDEO_PIPELINE.md` and the accepted
`docs/audits/2026-10-20_video_experience_roadmap.md` govern. Accepted WAN-321 findings from the preceding
investigation are reused, including upstream revisions, LFS checksums, license declarations and stock-node schemas.
No upstream research was repeated. Current local file checks are fresh evidence.

The owner's final restriction requires separate authorization for downloads, generation and runtime restart.
Memory abort thresholds and the whole-session limit must be accepted before execution. The owner accepted a
300-second per-attempt limit and three attempts total, including at most one retry of a positively resolved failure.
The offline CLI (`python -m tools.qualification.wan321f`) only writes an offline freeze. The physical adapter is a separate
module, `tools/qualification/wan321f/physical.py` (exclusive session claim, sampling/interrupt loop, output verification,
event-log collection), run once with `--authorize-plan <digest>`. Its tests use fakes only.

No catalog registration, NJR, queue, GUI, runner, backend ownership or workflow-governance changes. Every published
TI2V-5B version stays unchanged. Physical operations never bypass the production submission path for product jobs;
this package is isolated operator qualification tooling, following the retained qualification harness convention.

## Frozen candidate

`tools/qualification/wan321f/plan.py::frozen_plan()` is the machine-readable proposal. Its canonical JSON SHA-256:
`7b47d278e1519574330a3d912009fb14dba54d3090b5788ee6164c481562b976`.
Changing any asset, path, prompt, seed, graph, runtime command or safety proposal changes that digest and requires
acceptance of the new plan before physical execution.

All six destinations are under `E:/Users/rober/ComfyUI/models/`. Exact filenames, full SHA-256 values, sizes,
upstream paths and revisions are in `ASSETS` and each frozen `plan.json`:

| Role | Destination relative to model root | Bytes | Local verification |
|---|---|---:|---|
| High expert | `diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | 14,294,742,832 | Missing |
| Low expert | `diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | 14,294,742,832 | Missing |
| UMT5 | `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6,735,906,897 | Hash matches |
| VAE | `vae/wan_2.1_vae.safetensors` | 253,815,318 | Hash matches |
| High LoRA | `loras/wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors` | 634,645,944 | Missing |
| Low LoRA | `loras/wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors` | 739,472,104 | Missing |

Experts/encoder/VAE: `Comfy-Org/Wan-2.2` revision `ee6f4a40737a995bf5818954cfce6d59443b0f04`.
LoRAs: `lightx2v/Wan2.2-Distill-Loras` revision `57adea585d1d21085e2dfc91ce3c7b646cdd9345`.
Accepted primary-source declarations are Apache-2.0; original Wan2.2, Wan2.1 and Google UMT5 declarations were
also checked in WAN-321. These are publisher declarations, not a new legal opinion. Missing weights have no
local digest verdict. No downloads are performed by this package.

Input: `C:/Users/rob/qual/vid184/env/inputs/source_fullbody.png`, 385,055 bytes, 480x832,
SHA-256 `362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb`.
It is the already retained synthetic full-body reference, not the driving-video workload. The freeze copies its
verified bytes to `wan321f-source.png`. Recheck that snapshot before staging it into Comfy's isolated input directory.

ComfyUI 0.38.0 revision `6b747c0428c343e1417219641db93a4fb7cb69ae`, installed at
`C:/Users/rob/AppData/Local/StableNew/ManagedComfy/v0.38.0-py313`. The exact proposed command is frozen in the plan:
isolated port 8197 and input/output/temp/user directories under `reports/wan321f/runtime`, existing managed interpreter,
`--disable-pinned-memory --disable-auto-launch --disable-all-custom-nodes`, default cache and memory policy.
No cache, precision, attention, offload, model, graph or launch-flag fallback. No process adoption or restart.
An occupied endpoint refuses the run. Future operations must use `ComfyProcessManager`, not `OwnedComfy`'s historical
direct-Popen launcher or a new process authority.

Stock graph: two scaled-FP8 `UNETLoader` -> model-only LoRAs (strength 1) -> `ModelSamplingSD3` shift 5;
CPU UMT5 `CLIPLoader(type=wan)`; Wan **2.1** VAE; `LoadImage` -> `WanImageToVideo` (480x832, 81 frames,
batch 1) -> two `KSamplerAdvanced` nodes -> `VAEDecode` -> `SaveImage`.
Four total Euler/simple steps, CFG 1: high steps [0,2), add noise and retain leftover noise;
low steps [2,4), no new noise and full final denoise. Both passes share their attempt's seed and conditioning.
The three candidate seeds are 321001/321002/321003; only seed and output prefix differ, so sampling is recomputed
rather than reusing cached outputs. First attempt is cold; subsequent attempts may reuse weights/conditioning.
Expected output: 81 full-resolution PNG frames (intended playback 16 fps), no RIFE or video encoding.
The dynamic arm and 720p are excluded.

The accepted publisher example uses custom nodes and explicit sigmas; it is **not** imported or executed.
Local-source inspection adds the stock schedule translation: `ModelSamplingDiscreteFlow.set_parameters` creates
1000 points, `simple_scheduler` selects indices 999/749/499/249 and appends zero. Shift 5 produces
`[1, 0.9375, 0.8333333333, 0.625, 0]`, matching the accepted example within rounding. This establishes numerical
schedule correspondence, not physical output equivalence. The five local source-file hashes are pinned in the plan
and verified by the offline freeze without importing Comfy/Torch.

## Capacity and safety proposal awaiting acceptance

Snapshot: 2026-10-22 21:43 EDT (`2026-10-23T01:43:52Z`). Six assets total **36,953,325,927 bytes**;
four missing assets require **29,963,603,712 additional bytes** at their frozen E: destinations.
E: free **143,206,596,608 bytes**. C: free **126,574,559,232 bytes**; reserve **1,364,875,264 bytes** for
three uncompressed RGB frame sets plus a 1 GiB evidence/log allowance. Capacity suffices for these byte budgets.
This excludes temporary download copies, which need their own staging allowance/authorization. Recheck before execution.
Disk size does not establish peak RAM, commit or VRAM residency.

The owner accepted the **300-second per-attempt limit**. Historical `vid160c` / `vid184r` memory limits and
the whole-session ceiling below remain proposals, **not accepted for this package**:

| Signal | Proposed stop |
|---|---|
| Windows system commit | >=97% for 2 consecutive samples |
| Commit headroom | <1 GiB for 2 consecutive samples |
| Available physical RAM | <0.25 GiB for 2 consecutive samples |
| Sampling | Every 0.5 s; missing/invalid telemetry or gap >2 s stops immediately |
| Per attempt (owner accepted) | 300 s |
| Whole session (proposal) | 3600 s, including startup and teardown |
| GPU status, device-loss log marker, CUDA OOM/allocation failure | Immediate stop, end entire session, preserve evidence |

Reuse `vid160c.win_memory.read_system_commit` and `read_process_memory` for system and **owned PID** memory in GiB.
Use driver/NVML observations for VRAM, GPU health and device loss, plus the existing bounded GPU hang recorder if
separately authorized. Do not reuse `CommitAwareResourceSampler` unchanged: its missing-GPU/commit reads can silently
omit samples; the new guard requires a complete, timestamped sample and stops on missing data. VRAM is measured;
no speculative A14B readiness floor is borrowed from TI2V-5B. Record working set and private commit without inventing
a process-memory floor. Freeze any additional owner-required limit before execution.

Owner-accepted budget: **three total attempts, including at most one retry** of a positively resolved failure;
no 720p or fallback. This is permission for the budget, not a new execution/download authorization. No automatic
retry is implemented. An ambiguous dispatch consumes its identity and ends the session; `prompt_id` is correlation,
never an idempotency key. No safety-stop, allocation-failure or device-loss retry.

## Deterministic evidence and future physical acceptance

The offline tests cover graph wiring/sampler handoff, version preservation, complete file refusals, changed hashes,
limits and telemetry loss, durable dispatch-intent-before-call, one dispatch per identity (including process interruption
and ambiguous reply), disk-write refusal, evidence non-replacement and manager-owned cleanup/external refusal.
They exercise fakes, not the future physical loop. Startup containment and process-tree cleanup remain under the
existing manager. Exclusive evidence-directory claims survive interruption; no earlier attempt directory may be reused.

Before a physical attempt: verify exact accepted plan/source/asset/input hashes and runtime identity; persist graph,
command, baseline, owner decision, intended attempt and session claim. Start telemetry before the owned runtime.
Persist telemetry incrementally with flush/fsync, collect bounded runtime logs and Windows GPU/WHEA events.
Stop submission on a safety stop, interrupt only the acknowledged owned prompt, then clean up only the manager-owned
process tree. Unknown dispatch is never replayed or inferred successful from HTTP responsiveness.

For each completed attempt require exactly 81 decodable RGB-compatible 480x832 PNGs; record paths, frame order,
hashes, runtime history and timing. Reject missing/extra/wrong-size/corrupt frames; a prompt acknowledgement alone
is not success. Record observed commit/working-set/private-memory/VRAM peaks, minimum headroom/physical RAM,
sample gaps, baseline outside-GPU use, log faults, and positive teardown evidence. Hash and preserve all partial
artifacts on failure; never delete prior evidence or rewrite the plan after execution.

Proposed verdict rules: PASS requires completion of the accepted workload/budget with valid frames, no safety stop
or device-loss/allocation failure, complete telemetry and verified owned teardown. A demonstrated memory/commit
safety stop or allocation failure is NO-GO for that exact configuration. Missing assets/authorization, ambiguous
dispatch, incomplete telemetry, infrastructure failure or unverified teardown is INCONCLUSIVE. Stop after any
unsafe/ambiguous attempt. A physical PASS does not qualify motion/identity quality or authorize promotion.

Offline artifact: `C:/Users/rob/projects/StableNew-main/reports/wan321f/offline-freeze-20261022-300s/`
contains the proposal, three graphs, verified input snapshot and disk/refusal evidence. The earlier preliminary
freezes, including the original Stage 1 proposal, remain preserved; only the digest above is the proposal of record. These machine-local artifacts
are ignored, not source or authority.

Reproduce the offline freeze (new destination only):

```powershell
C:/Users/rob/projects/StableNew-main/.venv/Scripts/python.exe -m tools.qualification.wan321f --out <new-evidence-directory>
```

This command has no physical option. Do not treat historical roadmap download/spike decisions as
the current named authorization required by the owner's closing restriction.

## Physical session result (2026-10-23)

Run by `tools/qualification/wan321f/physical.py` at `6fc4a906` against plan digest `7b47d278...b976`, on a host with no
competing gate processes (started with 31.6 GiB commit headroom and 16.4 GiB physical RAM free). Evidence:
`reports/wan321f/physical-001/` (ignored, machine-local). The session claim is spent: this budget of three dispatches is
used, and the owner's three-attempt allowance is exhausted.

| Item | Result |
|---|---|
| Dispatches / completed | 3 / 3, seeds 321001-321003, one dispatch each, no retry |
| Output | 81 decodable 480x832 PNG frames per attempt, validated and hashed |
| Prompt time | 124.9 s (cold), 92.3 s, 90.6 s; all under the 300 s limit |
| Safety stop, allocation failure, device loss, WHEA or System events | none |
| System commit | baseline 22.5 GiB, peak 37.6 GiB (67.5%), minimum headroom 18.1 GiB |
| Physical RAM | minimum available 4.8 GiB |
| VRAM | peak 9,596 MiB of 12,282; minimum free 2,686 MiB (baseline 1,420 MiB in use) |
| Telemetry | 613 samples at about 0.5 s, maximum gap 0.68 s, no missing sample |

Why the frozen verdict is INCONCLUSIVE: `teardown.json` recorded `verified: false` with child PID 8940 still present when
it was written, about 1 s after the last Comfy log write, following a `grace_seconds=0` stop followed by a single `pid_exists` check.
Both observed children and the owned PID were absent when checked afterward (`post-hoc-teardown-check.json`), which makes an
asynchronous job-object kill plausible, but PID reuse cannot be excluded, so it is not a teardown verification.

Adapter defects found (not fixed after execution, to keep the evidence tied to the executed SHA):

1. Teardown is checked once with no bounded wait for the contained tree to exit.
2. Per-process memory sampled only the owned PID, which is the 4.7 MB launcher stub (about 0.0009 GiB private in every
   sample). The Comfy worker's working set and private commit were never measured. System-level commit, RAM and VRAM
   figures are unaffected and are the evidence above.

What this does and does not show: on the frozen stock-node plan the A14B pair ran three times to completion on the
target host with the memory guard never near a limit. It does not establish motion or identity quality, does not qualify
720p or the dynamic arm, and does not authorize catalog registration or promotion. A teardown-verified repeat needs
the two adapter fixes, a new session identity and a new owner decision on the budget.

## Owner disposition (2026-10-23)

The owner accepted that the investigation provided sufficient information to close the research objective and closed this
package. That is an acceptance of research closure, not a successful qualification against every frozen criterion: the
recorded frozen technical verdict (INCONCLUSIVE, `teardown.json` `verified: false`) is kept as evidence and was not edited.
No repeat session, catalog registration, promotion or WAN-321 integration is authorized by this disposition.

To be addressed during full implementation (carried forward, not fixed here):

1. Teardown of the managed Comfy tree must be verified with a bounded wait before a result is recorded, and the
   check must cover the whole process tree, not a single `pid_exists` call.
2. Per-process memory must be sampled for the worker tree (the launcher stub the adapter measured reads about 0.001 GiB),
   so the worker's working set and private commit are evidence, not only system-level commit, RAM and VRAM.
3. The A14B resource envelope above (system commit peak 37.6 GiB, minimum available RAM 4.8 GiB, VRAM peak 9,596 MiB)
   was observed on a quiet host with a managed Comfy only; production integration must re-establish it beside the
   other managed runtimes and the transition policy.
