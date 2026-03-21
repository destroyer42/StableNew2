# PR-HARDEN-258 - Workload-Aware WebUI Launch Policy

Status: Completed 2026-03-21

## Summary

This PR added a small but important policy layer on top of the `PR-HARDEN-257`
runtime recovery work. StableNew now keeps `standard` as the global WebUI
default, but automatically upgrades to `sdxl_guarded` when the active SDXL
workload geometry and stage chain are heavy enough to justify the guarded
profile.

## Delivered

- added workload-profile recommendation helpers in `src/config/app_config.py`
- added proactive launch-policy upgrade in `src/pipeline/executor.py` before
  runtime admission for heavy `txt2img`, `adetailer`, and `upscale` stages
- used remaining stage-chain context so heavy SDXL chains can upgrade before
  later stages fail under `standard`
- treated `low_memory` as already guarded so StableNew does not bounce between
  low-memory profiles unnecessarily

## Key Files

- `src/config/app_config.py`
- `src/pipeline/executor.py`
- `tests/api/test_webui_launch_profile_v2.py`
- `tests/pipeline/test_stage_admission_control_v2.py`

## Tests

Focused verification passed:

- `pytest tests/api/test_webui_launch_profile_v2.py tests/pipeline/test_stage_admission_control_v2.py -q`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/PR-HARDEN-258-Workload-Aware-WebUI-Launch-Policy.md`

## Notes

This is intentionally non-blocking hardening. It does not replace
`PR-HARDEN-257`; it builds on it so StableNew can choose `sdxl_guarded`
automatically for the workload classes that actually need it.
