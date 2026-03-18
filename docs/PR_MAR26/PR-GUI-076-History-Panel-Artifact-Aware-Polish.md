# PR-GUI-076: History Panel Artifact-Aware Polish

## Goal

Continue GUI modernization only after the runtime substrate is stable by making the
V2 job history panel reflect the canonical artifact contract instead of legacy
best-effort result fields.

## Scope

- Make history output-folder derivation artifact-aware.
- Make the Images column derive from canonical artifact counts and paths.
- Disable "Animate with SVD" for history entries whose primary artifact is already a video.
- Keep the change limited to GUI presentation and action gating.

## Runtime Alignment

Recent PRs standardized canonical artifacts for images, replay, SVD, and AnimateDiff.
This PR updates the GUI to consume that contract rather than treating every completed
history row as an image-only job.

## Changes

### History Panel

- Prefer canonical artifact records from:
  - `result["artifact"]`
  - `result["metadata"]["svd_native_artifact"]`
  - `result["metadata"]["animatediff_artifact"]`
  - canonicalized variant entries
- Use canonical primary output paths to derive the display/output folder.
- Use canonical artifact counts/paths to populate the Images column.
- Gate the SVD action off the primary artifact type.

### Tests

- Added GUI coverage for disabling SVD on video history entries.
- Added display coverage for canonical artifact count and output-folder extraction.

## Result

The V2 history panel now behaves like a consumer of the stabilized runtime contracts,
not a legacy guesser over ad hoc result payloads.
