# WebUI GPU Pressure and Stall Investigation 2026-03-21

Status: Active Investigation Record  
Date: 2026-03-21  
Scope: StableNew image pipeline runtime instability under GPU pressure

## 1. Executive Summary

StableNew is currently experiencing a compound failure mode, not a single bug.

The dominant pattern is:

1. high-memory image workloads push Automatic1111/WebUI close to VRAM exhaustion
2. under that pressure, WebUI becomes extremely slow, stops responding, or dies
3. StableNew then amplifies the unhealthy state with aggressive readiness polling,
   repeated diagnostics bundles, and repeated watchdog triggers
4. current diagnostics capture is too noisy and too incomplete to distinguish a
   true GPU/OOM failure from shutdown thrash or restart churn
5. there is still unresolved live model-switch drift in the WebUI runtime even
   when saved manifests for the failing run appear correctly pinned

This means the current problem is best described as:

`GPU pressure + weak failure damping + over-sensitive watchdog/reporting + unresolved live model drift`

It is not adequately explained by a single short HTTP timeout, a single orphan
process bug, or a single bad manifest.

## 2. Evidence Collected

### 2.1 Current GPU state

Live `nvidia-smi` during the failing session reported:

- RTX 4070 Ti
- `11708 MiB / 12282 MiB` dedicated VRAM in use
- `100%` GPU utilization

This is a near-saturation state for SDXL-class generation plus ADetailer and
upscale work.

### 2.2 Current run dimensions and pressure profile

Recent successful and failing manifests show:

- `txt2img`: `1024 x 1536`, `30` steps, SDXL model
- `adetailer`: same base dimensions, face and hand passes enabled
- `upscale`: single-image upscale at `1.5x`

That upscale path produces a target image of roughly `1536 x 2304`, which is a
large post-detail image for a 12 GB card once prior model, VAE, and extension
state are already resident.

### 2.3 WebUI runtime evidence

Recent WebUI stdout shows:

- repeated model loads between `juggernautXL_ragnarokBy` and
  `realismFromHadesXL_2ndAnniversary`
- tiled upscale steps hanging for extreme durations, including one case with
  tile progress effectively stalling for more than 11 minutes

Important detail:

- the saved ADetailer and upscale manifests for the recent run are pinned to
  `juggernautXL_ragnarokBy`
- the live WebUI logs still show switching back to `realismFromHades...`

So the saved request surface is not sufficient to explain the live model flips.

### 2.4 Repeated connection and readiness failures

`logs/stablenew.log.jsonl` shows severe recurrence of:

- `WinError 10061` connection refusal
- readiness timeouts for `/sdapi/v1/options`
- repeated orphan-monitor starts
- extremely frequent `ui_heartbeat_stall` diagnostics

This is consistent with WebUI becoming unavailable and StableNew repeatedly
probing/recovering without enough damping.

### 2.5 Duplicate StableNew GUI processes

The current session had two active `src.main` processes:

- one parent StableNew GUI process
- one child StableNew GUI process which owned the WebUI child

This is a serious lifecycle integrity warning. It does not fully explain the GPU
pressure, but it absolutely weakens orphan detection and restart reasoning.

### 2.6 Diagnostics weakness

Recent diagnostics bundles were generated every 10 to 20 seconds.

Problems with current diagnostics:

- many bundles were triggered for `ui_heartbeat_stall`
- recent bundles did not include process state or WebUI tail by default
- thread dumps often showed `MainThread` already dead during shutdown while the
  watchdog was still firing

So current diagnostics are both too noisy and not informative enough for this
class of failure.

### 2.7 Current WebUI launch flags

Current `webui-user.bat` launches with:

- `--api`
- `--xformers`

There is no active explicit low-memory mode such as:

- `--medvram`
- `--medvram-sdxl`
- `--lowvram`

The installed WebUI codebase does support those flags.

## 3. Findings

### Finding 1: The primary failure source is GPU pressure, not a normal API timeout

Accepted.

Why:

- GPU is near fully saturated
- workload is heavy for 12 GB SDXL
- WebUI tiled upscale showed multi-minute blocking behavior
- failures happen across `txt2img`, `adetailer`, and `upscale`, which is what a
  pressure-driven instability pattern looks like

### Finding 2: StableNew is amplifying unhealthy runtime states after WebUI destabilizes

Accepted.

Why:

- readiness checks repeat aggressively
- watchdog bundles fire repeatedly
- orphan monitor restarts are noisy
- diagnostics cadence is itself a source of load and confusion

### Finding 3: There is not yet strong evidence of a classic StableNew-side Python memory leak

Partially accepted, with caution.

Why:

- evidence strongly supports GPU pressure and runtime instability
- evidence does not yet show monotonic Python-side resident memory growth caused
  by StableNew alone
- current diagnostics do not capture enough process-state detail to prove or
  fully refute a leak

Conclusion:

- a leak is possible but unproven
- missing instrumentation is itself part of the problem

### Finding 4: Orphan/lifecycle control is not trustworthy enough in the current session

Accepted.

Why:

- duplicate `src.main` processes were present
- only one owned the WebUI child
- repeated orphan monitor starts are visible in logs

This means lifecycle enforcement needs hardening even if it is not the original
cause of the GPU pressure event.

### Finding 5: Model-switch drift is still unresolved in live execution

Accepted.

Why:

- recent manifests for the failing run are pinned to `juggernaut`
- live WebUI stdout still shows switches to `realismFromHades`

This suggests either:

- a remaining StableNew runtime path is still mutating global model state, or
- a WebUI/plugin/global option path is overriding request-local intent

Either way, the drift is real and should be surfaced and guarded.

## 4. Top 5 Remediation Candidates

### Candidate 1: Add GPU-pressure-aware guardrails and pre-stage admission control

Verdict: Accept

Rationale:

- this addresses the most likely root cause directly
- current executor does only limited system RAM checks, not GPU-pressure-aware
  checks
- StableNew should warn, downgrade, or refuse obviously unsafe combinations
  before sending them into WebUI

Recommended shape:

- compute estimated pixel pressure before `txt2img`, `adetailer`, and `upscale`
- classify runs as `normal`, `high_pressure`, or `unsafe`
- surface warnings before execution
- optionally auto-downgrade upscale ratio or suggest `medvram-sdxl`

### Candidate 2: Add failure damping so StableNew stops self-amplifying outages

Verdict: Accept

Rationale:

- the current unhealthy-state behavior is too noisy

## 5. Post-PR-256 Real-World Validation Addendum

`PR-HARDEN-256` was implemented and then validated against a real repeated image
workload using the same `AA LoRA Strength` prompt-pack/config class that had
been failing.

Validation summary:

- 10 sequential image jobs
- 3 complete `txt2img -> adetailer -> upscale` chains
- 7 failed jobs
- average wall time: `323.08s`
- peak GPU utilization: `100%`
- peak dedicated VRAM: `11956 MiB / 12282 MiB`
- peak system RAM: `98.6%`
- diagnostics bundles created: `214`

Important interpretation:

- `PR-HARDEN-256` improved observability and added some damping, but it did not
  materially stabilize the workload
- the run still entered poisoned runtime states and StableNew still admitted new
  work into those states
- watchdog/diagnostics spam remains materially too high
- a follow-on runtime-state recovery and admission-control PR is required before
  resuming the next runtime-heavy backend rollout

See:

- `docs/PR_Backlog/PR-HARDEN-257-WebUI-State-Recovery-and-Admission-Control.md`
- repeated readiness probes, watchdog triggers, and diagnostics bundles make the
  system harder to recover and harder to understand

Recommended shape:

- longer watchdog cooldowns
- suppression of heartbeat-stall diagnostics during shutdown or known long-running
  GPU phases
- restart backoff and circuit-breaker behavior after repeated WebUI failures

### Candidate 3: Switch WebUI launch policy to a lower-memory default for SDXL workloads

Verdict: Accept, but cautiously

Rationale:

- the installed WebUI supports `--medvram-sdxl`
- the current launch path uses only `--xformers`
- `--medvram-sdxl` is a pragmatic fit for a 12 GB card running large SDXL
  images plus ADetailer/upscale

Critical appraisal:

- this may reduce speed
- it may not be necessary for all users or all models
- it should be a managed StableNew launch policy, not a hard-coded universal
  flag with no visibility

Recommended shape:

- introduce an explicit StableNew launch policy tier:
  `standard`, `sdxl_guarded`, `low_memory`
- map `sdxl_guarded` to `--xformers --medvram-sdxl`
- make the active launch profile visible in diagnostics and logs

### Candidate 4: Increase HTTP timeouts further

Verdict: Refute as a primary fix

Rationale:

- some endpoints already have long timeouts
- the real failures include connection refusal and prolonged hangs
- longer timeouts would only hide failure longer and worsen operator feedback

Timeout tuning may still be useful in narrow places, but it is not the main fix.

### Candidate 5: Add stronger process-state and VRAM diagnostics

Verdict: Accept

Rationale:

- current diagnostics are too incomplete for GPU-pressure incidents
- current bundles often fire on synthetic heartbeat conditions without enough
  runtime state attached

Recommended shape:

- include process state, WebUI tail, and launch command profile by default for
  pressure/stall reasons
- add a lightweight GPU snapshot if `nvidia-smi` is available
- attach whether shutdown was already in progress when the watchdog fired

## 5. Critical Appraisal of the Top 5

### 5.1 GPU-pressure guardrails

Strongest recommendation.

Pros:

- addresses the most likely root cause
- reduces user-facing failure rate
- gives the product a principled warning/downgrade path

Cons:

- requires heuristics rather than perfect measurement
- can be conservative and occasionally over-warn

Final decision: Accept

### 5.2 Failure damping and circuit breakers

Strong recommendation.

Pros:

- lowers log spam
- reduces runaway diagnostics/restart churn
- makes recovery behavior more deterministic

Cons:

- if overdone, could hide real failures or delay recovery

Final decision: Accept

### 5.3 Lower-memory WebUI launch policy

Good recommendation with explicit caveat.

Pros:

- directly aligned with observed SDXL pressure
- supported by the installed WebUI codebase

Cons:

- can reduce throughput
- should not be globally forced without visibility and policy control

Final decision: Accept with managed rollout

### 5.4 Bigger timeouts

Weak recommendation.

Pros:

- easy to do

Cons:

- treats symptoms, not root cause
- can worsen the user experience by making dead periods longer

Final decision: Refute as primary remedy

### 5.5 Better diagnostics and pressure instrumentation

Strong recommendation.

Pros:

- turns guesswork into observable evidence
- helps separate OOM, stall, shutdown, and restart loops

Cons:

- does not prevent failure by itself

Final decision: Accept as part of the same hardening PR

## 6. Accepted Remediation Package

The most valid combined remedy is:

1. GPU-pressure admission and warning logic
2. managed low-memory WebUI launch policy for SDXL-heavy workloads
3. failure damping for readiness, watchdog, and restart behavior
4. improved diagnostics for stall/pressure incidents
5. explicit model-drift guardrails and warnings

## 7. Recommended Immediate Next Step

Do not continue with the next video runtime rollout PR until the image/runtime
stability issue is hardened.

Recommended interstitial PR:

- `PR-HARDEN-256-WebUI-Pressure-Guardrails-and-Failure-Damping`

This PR should land before additional runtime-complexity work such as
`PR-VIDEO-238`.

## 8. Post-PR-257 Validation Addendum

`PR-HARDEN-257` was then implemented and validated by rerunning the same heavy
`AA LoRA Strength` workload class used in the failed `PR-HARDEN-256` check.

Validation summary:

- 10 sequential image jobs
- 10 complete `txt2img -> adetailer -> upscale` chains
- 0 failed jobs
- average wall time: `117.358s`
- 0 timeout events
- 0 connection-refused events
- 0 diagnostics bundles created
- launch profile used during validation: `sdxl_guarded`

Pressure observations remained real but manageable:

- peak GPU utilization: `100%`
- peak dedicated VRAM: `11935 MiB / 12282 MiB`
- peak system RAM: `92.1%`

Interpretation:

- GPU pressure is still present, but `PR-HARDEN-257` materially improved
  runtime stability
- guarded restart plus runtime admission control prevented the earlier poisoned
  runtime/retry spiral
- diagnostics and watchdog single-flight hardening eliminated the earlier crash
  bundle flood
- the runtime is now stable enough to resume the blocked video sequence

Updated verdict:

- `PR-HARDEN-256` alone was not sufficient
- `PR-HARDEN-256` plus `PR-HARDEN-257` is sufficient to unblock
  `PR-VIDEO-238`

Recommended follow-on:

- no blocking hardening PR is required before resuming `PR-VIDEO-238`
- one non-blocking follow-on is still worth planning: workload-aware automatic
  selection of `sdxl_guarded` for SDXL-heavy image workloads while keeping the
  global default launch profile conservative
