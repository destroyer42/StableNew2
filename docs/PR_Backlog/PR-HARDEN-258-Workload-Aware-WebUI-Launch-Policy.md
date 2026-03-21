# PR-HARDEN-258 - Workload-Aware WebUI Launch Policy

Status: Implemented 2026-03-21
Priority: HIGH
Effort: SMALL
Phase: Runtime Stability Hardening

## 1. Why This PR Exists

`PR-HARDEN-257` materially stabilized the heavy SDXL image workload, but the
successful validation depended on running under the managed `sdxl_guarded`
profile.

StableNew should not flip the global default away from `standard` for every
user and every workload. It should, however, automatically upgrade to
`sdxl_guarded` when the active SDXL workload shape is predictably heavy.

## 2. Goals

1. Keep `standard` as the conservative global default profile.
2. Automatically prefer `sdxl_guarded` for SDXL-heavy geometry/stage chains.
3. Apply the upgrade through the existing managed WebUI restart path.
4. Treat `low_memory` as already satisfying the guarded requirement.

## 3. Non-Goals

1. Do not redesign the launch-profile system.
2. Do not add GUI profile controls in this PR.
3. Do not make `sdxl_guarded` the unconditional global default.

## 4. Implementation Summary

- added workload-profile helpers in `src/config/app_config.py`
- added executor-side proactive launch-policy upgrade before runtime admission
  for heavy `txt2img`, `adetailer`, and `upscale` stages
- used remaining stage-chain context so heavy `txt2img -> adetailer -> upscale`
  SDXL workloads can upgrade before the first failure spiral begins
- treated `low_memory` as an acceptable guarded profile to avoid pointless
  restart churn

## 5. Key Files

- `src/config/app_config.py`
- `src/pipeline/executor.py`
- `tests/api/test_webui_launch_profile_v2.py`
- `tests/pipeline/test_stage_admission_control_v2.py`

## 6. Verification

- `pytest tests/api/test_webui_launch_profile_v2.py tests/pipeline/test_stage_admission_control_v2.py -q`

## 7. Outcome

StableNew now keeps the global WebUI launch default conservative while
automatically upgrading SDXL-heavy image workloads to `sdxl_guarded` through
the managed recovery path.
