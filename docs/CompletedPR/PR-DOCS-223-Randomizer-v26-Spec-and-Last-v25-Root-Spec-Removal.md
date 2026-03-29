# PR-DOCS-223 - Randomizer v2.6 Spec and Last v2.5 Root-Spec Removal

Status: Completed 2026-03-19

## Purpose

Replace the last retained active v2.5 root spec with a true v2.6 subsystem
document and remove the final v2.5 spec from the active root docs set.

## Delivered

### New active subsystem spec

Added:

- `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md`

The new spec reflects current repo truth:

- config-level randomization via `src/randomizer/`
- prompt and matrix randomization via `src/utils/randomizer.py`
- builder-time only randomization
- NJR-backed queue-first execution

### Root-doc cleanup

Moved the old retained root doc:

- `docs/Randomizer_Spec_v2.5.md` ->
  `docs/archive/reference/Randomizer_Spec_v2.5.md`

### Canonical reference updates

Updated:

- `docs/GOVERNANCE_v2.6.md`
- `docs/Canonical_Document_Ownership_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`

## Result

No v2.5 subsystem specs remain in the active root docs set.

The active randomizer guidance is now a real v2.6 doc aligned with the current
post-unification architecture.
