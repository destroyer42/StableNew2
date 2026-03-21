# Verdict - Deep GPU Memory and Stall Investigation

Status: Reference Verdict  
Date: 2026-03-21  
Source Report: `docs/Research Reports/deep-research-report-DEEP GPU memory and stall investigation.md`

## 1. Overall Verdict

The report is directionally useful on symptoms and prioritization, but it mixes
two different execution layers:

1. StableNew's main still-image path, which is primarily WebUI-backed over HTTP
2. StableNew's local in-process video workers, which do own PyTorch pipelines

Because of that, several findings are correct at the operational level, while
some of the proposed fixes are aimed at the wrong layer for the failing
`txt2img -> adetailer -> upscale` path.

Overall verdict:

- Symptom diagnosis: **mostly confirmed**
- Root-cause framing: **partially confirmed**
- Proposed implementation path: **partially refuted**

## 2. Confirmed Findings

### 2.1 GPU pressure is real and central

Confirmed.

This aligns with:

- `docs/WebUI GPU Pressure and Stall Investigation 2026-03-21.md`
- pressure assessment and admission logic in `src/pipeline/executor.py`

The workload class is genuinely heavy for a 12 GB SDXL card:

- `1024 x 1536` txt2img
- ADetailer face + hand passes
- `1.5x` upscale

### 2.2 Current guardrails can arrive too late

Confirmed.

`PR-HARDEN-256` improved classification and observability, but real-world
validation still showed that work could be admitted into an already degraded or
poisoned runtime state.

### 2.3 Resolution and downstream geometry materially affect failure risk

Confirmed.

The report is right that even moderate increases in width/height create a large
memory multiplier once ADetailer and upscale are added.

### 2.4 Stronger preflight admission logic is warranted

Confirmed.

This directly matches the intent of
`docs/PR_Backlog/PR-HARDEN-257-WebUI-State-Recovery-and-Admission-Control.md`.

### 2.5 Lower-memory WebUI launch policies are relevant

Confirmed.

StableNew already supports a launch-profile model in `src/config/app_config.py`,
including:

- `standard`
- `sdxl_guarded`
- `low_memory`

Using `--medvram-sdxl` as a managed guarded profile is a valid and appropriate
direction for this hardware class.

## 3. Partially Confirmed Findings

### 3.1 Orphan/lifecycle issues may worsen instability

Partially confirmed.

Lifecycle and duplicate-process problems can absolutely amplify instability, and
StableNew has already had to harden this area in:

- `src/api/webui_process_manager.py`
- `src/utils/process_inspector_v2.py`

But they are not the primary explanation for the failure pattern. GPU pressure
and poisoned runtime reuse remain the dominant issues.

### 3.2 Memory cleanup matters between jobs

Partially confirmed.

Cleanup does matter, but the correct surface for the main image path is the
WebUI/API boundary, not local in-process PyTorch object deletion.

StableNew already has cleanup mechanisms in:

- `src/api/client.py` via `free_vram(...)`
- `src/pipeline/executor.py`
- `src/pipeline/pipeline_runner.py`

So the report is right about the need for cleanup, but wrong about the exact
mechanism for the still-image path.

## 4. Refuted Findings

### 4.1 The main image pipeline should call `pipe.to(torch.float16)` and enable XFormers directly

Refuted for the main image path.

Reason:

StableNew's failing still-image stages are primarily executed through
Automatic1111/WebUI over HTTP in `src/api/client.py`, not through a local
HuggingFace or diffusers image pipeline that StableNew directly owns.

That means:

- there is no main-image `pipe` in StableNew to cast to `torch.float16`
- StableNew cannot fix main-image VRAM pressure by calling local diffusers
  methods in the still-image executor

This recommendation is relevant to local video workers under `src/video/`, not
to the main WebUI-backed `txt2img` / `adetailer` / `upscale` path.

### 4.2 Each image job instantiates models freshly inside StableNew

Refuted for the main image path.

The heavy model lifecycle for still images is primarily inside the external
WebUI process, not inside StableNew's Python executor object.

### 4.3 `torch.cuda.empty_cache()` and `del pipe` are the primary image fix

Refuted for the main image path.

That advice is appropriate for local PyTorch ownership, but the main failing
path is WebUI-backed. The better equivalents here are:

- guarded WebUI launch defaults
- WebUI-side unload/free operations
- early refusal of unsafe work
- clean restart of poisoned WebUI state

### 4.4 A new per-job inference subprocess is the right fix

Mostly refuted for still-image execution.

StableNew already isolates that work in an external managed WebUI process via
`src/api/webui_process_manager.py`. Adding another subprocess layer inside
StableNew for the same path would add complexity without addressing the actual
failure mode cleanly.

## 5. Recommendation

The report should be used as a pressure/stall diagnosis reference, not as an
implementation spec.

Recommended action set:

1. **Accept**
   - pressure-aware admission control
   - guarded WebUI launch profile use for SDXL-heavy work
   - stronger runtime recovery and process diagnostics
   - better failure damping and watchdog/diagnostics suppression
   - user/operator warnings for unsafe geometry and stage combinations

2. **Reject**
   - FP16/XFormers changes inside StableNew's main image executor as the
     primary remedy
   - `torch.cuda.empty_cache()` / local model deletion as the main still-image
     fix
   - a new per-job subprocess inference model for the WebUI-backed image path

3. **Continue current roadmap direction**
   - finish validating `PR-HARDEN-257`
   - determine whether a follow-on hardening PR is required for:
     - stricter poisoned-runtime refusal
     - remaining model-drift/runtime-state issues
     - launch-profile default changes

## 6. Final Recommendation

Treat the report as **60-70% correct overall**:

- good on the operational problem
- mixed on the actual architecture-aware remedies

The right next move is not a local PyTorch refactor of the image path.
The right next move is:

1. validate `PR-HARDEN-257`
2. tighten WebUI state admission and recovery if needed
3. review whether SDXL-heavy workloads should default to `sdxl_guarded`
4. separately pursue any local-PyTorch memory work only in the subsystems that
   actually own those models
