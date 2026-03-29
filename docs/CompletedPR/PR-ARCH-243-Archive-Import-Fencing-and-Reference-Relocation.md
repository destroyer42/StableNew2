# PR-ARCH-243 - Archive Import Fencing and Reference Relocation

Status: Completed 2026-03-29

## Delivered

- live Python archive modules were removed from `src/**/archive/**`
- reference-only legacy pipeline-config code now lives under `tools/archive_reference/`
- compat-only legacy coverage imports the relocated reference package explicitly
- enforcement now fails if Python modules reappear under `src/**/archive/**` or if active source imports archive/reference modules

## Validation

- `tests/safety/test_no_archive_python_modules_under_src.py`
- `tests/system/test_architecture_enforcement_v2.py`
- `tests/system/test_test_taxonomy_enforcement_v26.py`
- `tests/compat/test_end_to_end_legacy_submission_modes.py`

