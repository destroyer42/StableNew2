# PHONE-FAST — Fast, unblocked phone review

Status: in progress (2026-11-26). Extends the [review gateway](../Subsystems/ReviewGateway/REVIEW_GATEWAY.md) delivered
by RG-100 to RG-140. Not deployed or qualified until the living document says so.

## Problem (assessment of 2026-11-27)

- Almost every phone image downloads as a 1.5 MB original, never cached, with nothing useful prefetched.
- Publishing is newest first, one item per 30 s while busy, and stuck behind rows whose file is gone, so older items
  wait for hours.
- About 45,000 unpublished rows are video frames under `movie_clips`; unblocking the publisher would flood the phone.
- An image sent for a face or hands pass still asks for Keep or Delete before the result exists, and the result is not
  linked to it.

## Execution class and models

- Execution class: Standard (known design; additive contract and schema changes; no new authority).
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.
- Controller surface: none. `src/app/` services and the separate gateway; one composition function in
  `src/app/runtime_stack.py`.
- Validation: focused gateway and PC tests per commit; once at the end `tests/system`, the two GUI port guards,
  the code-map test, `tools/ci/run_pr_gate.py` and the ruff and mypy ratchets.

## Owner rules

Warn, don't block. No quotas. Phone decisions stay requests; the PC applies them (RG-100 invariants unchanged).

## Slices and acceptance

PR 1 holds (a) to (d); PR 2 holds (e) and (f).

### (a) Only authoritative outputs are published

- An image under `movie_clips` is never published (it is a video's working frame).
- An image a video manifest of its run folder lists as a frame is never published, whatever the output route.
- A clip recorded as the retained (un-smoothed) source is never published, including one written before files carried
  `output_role`.
- While a job runs, an image with no StableNew metadata waits (its job may not have written its manifest yet).
- Items already published stay published.

### (b) Publisher fixes

- A row whose file is gone is recorded as missing (retried a day later) and never keeps older rows waiting. A published
  item's ledger row is never overwritten.
- A row that fails for another reason is set aside for a while, so the rows behind it publish.
- The backfill window rolls: the last 3 days, or back to the last time the publisher had caught up if that is older;
  never further back than the first window.
- When a job completes, its outputs publish at once, even while the next job runs. Older items keep the slow busy rate.
  Nothing is transcoded while a job runs.

### (c) Phone rendition

- Every published image has a WebP rendition with a long side of at most 1080 px, also when the image is 1024 px.
- Items published before this without one get it while the PC is idle.
- The gateway serves renditions and thumbnails as cacheable and immutable for 7 days. Originals stay `no-store`.
- The phone prefetches the next 4 renditions.

### (d) Sent for rework, then compare

- Rework actions are Fix face, Fix hands and Fix both (they replace an image). More like this makes variations and does
  not change the original's state.
- Once the phone has queued a rework, the original counts as reviewed ("sent for rework") and leaves the unreviewed
  stream. A refused request returns it. It can still be decided from the run grid.
- The PC records which admitted job made which original's rework, and names the original (`parent`) in the result's
  manifest, only to a gateway that lists the `item_parent` feature.
- A result whose original is still on the gateway and not deleted is shown with it: tap to flip between the two, then
  "Keep original" or "Keep rework". The pick is kept and the other is discarded (to the archive), as two ordinary
  decisions.
- Lineage stays in the PC ledger (`rework_result`) and on the gateway item.

### (e) Continuous triage (PR 2)

- One stream across runs and batches; Undo of the last decision; "Keep the rest" and "Delete this run".

### (f) Housekeeping (PR 2)

- Undecided cached items purge after 30 days (configurable). A cache size cap warns. Every paired phone sees the PC's
  status and queue length.

## Compatibility

- Additive only: `schema_version` unchanged, new SQLite columns and tables, new optional manifest field behind a health
  feature.
- Older gateway, newer PC: no `features`, so no `parent`; renditions use the existing `preview_1080` variant.
- Newer gateway, older PC: no `parent` and no rendition; the phone shows the original, results are ordinary items.
  "Sent for rework" works because it is derived from the phone's own outbox record.

## Out of scope

Republishing or removing frames already on the gateway, video transcode changes, notifications, pagination.
