# PR-DOCS-065: Docs Index, README, and Current-State Refresh

## Summary

Refresh the public and canonical documentation entrypoints so they match the
current v2.6 runtime:

- rewrite `README.md` around the v2.6 canonical path
- update `docs/DOCS_INDEX_v2.6.md` so it explicitly treats `README.md` as the
  top-level entrypoint and keeps it in sync
- replace the stale and encoding-corrupted Top 20 recommendations doc with a
  clean ASCII v2.6-aligned version

## Allowed Files

- `README.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/StableNew_Revised_Top20_Recommendations.md`
- `docs/PR_MAR26/PR-DOCS-065-Docs-Index-README-Current-State-Refresh.md`

## Implementation

1. Rewrite `README.md` so it reflects:
   - v2.6 status
   - NJR-first canonical runtime
   - the preferred still-image flow
   - current development workflow and canonical docs entrypoints
2. Update `docs/DOCS_INDEX_v2.6.md`:
   - refreshed `Updated` date
   - add `README.md` as the top-level operator/reference entrypoint
   - require README updates when the summarized runtime story changes
3. Replace the stale Top 20 recommendations doc with a clean version that:
   - fixes collection counts
   - records current Phase 0/1 status
   - stops presenting already-executed migration work as purely hypothetical

## Verification

- light grep for stale README references to v2.5 docs
- `python -m compileall` not required for docs-only files
- targeted file review of the updated docs set

## Rollback

Revert the four touched documentation files together. No runtime behavior is
intended in this PR.
