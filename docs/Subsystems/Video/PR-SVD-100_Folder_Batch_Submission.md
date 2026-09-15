# PR-SVD-100 — Folder Batch Submission

Status: COMPLETE / ACCEPTED / INTEGRATED ON MAIN
Owner: Rob
Execution profile: Standard — GPT-5.6 Terra, High, Local/Desktop.

## Outcome

Folder Batch is a non-recursive SVD submission convenience. It discovers and
probes direct compatible image files, compiles one immutable ordinary SVD NJR per
source, and submits the complete list once through `JobService.submit_njrs`.
The established path remains:

`Folder intent -> discovery/admission -> immutable SVD NJRs -> JobService -> SQLite queue -> PipelineRunner.run_njr -> existing SVD backend -> artifacts/history/replay`

This package does not introduce a batch job model, group lifecycle, runner,
backend, SQLite, artifact, history, replay, cancellation, or seed-policy change.

## Contract

- `src.video.svd_preprocess` is the sole supported-image/discovery/probe
  authority: `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff`, and `.tif`.
- Discovery is direct-folder only, resolved-path deduplicated, and deterministic
  by case-insensitive filename/path ordering. Unsupported files are reported;
  supported-extension files that cannot be probed block the complete batch.
- Submission-time discovery is authoritative. Persisted UI state stores only
  source mode and folder path; it never persists an enumerated image list.
- Folder mode is explicit and never places a directory into `source_image_var`.
  Browse Image, latest-output, and recent-source handoff return to single mode.
- The displayed SVD settings are common batch intent. Fixed target presets are
  copied into every NJR; Match Source Aspect resolves each probed source via
  `select_svd_target_size` before that NJR is built.
- Fixed seeds remain fixed for every job and blank seeds remain blank. No
  per-file seed derivation or randomization is added.
- Common config/runtime/postprocess admission occurs once where possible; each
  source is individually existence/type/decodability/dimension checked.
- Any invalid supported candidate or common-admission failure submits nothing.
  A successful folder uses exactly one `JobService.submit_njrs(all_njrs,
  SubmissionPolicy())` call in deterministic discovery order.
- Auto-run, manual Send, queue persistence, cancellation, reordering, history,
  replay, artifacts, and provenance remain per-job existing behavior.

## Controller assessment

`SVDController` owns discovery, admission, per-source target resolution, NJR
planning, and the single queue submission. `AppController` is a thin form-data
validation/delegation bridge that refreshes and flushes queue projection once.
No controller is permitted to call the runner, backend, repository, or a
per-image submission loop.

## Accepted closeout evidence

- Focused changed-behavior tests: 16 passed.
- Raw Ruff and the controller-surface ratchet passed.
- Required GitHub CI run `34992485523` passed Python 3.11 and 3.12 for final
  source SHA `63140acac5ef6aa567819332f1fc546f24fd3395`.
- The local PR gate was attempted once and reported the established tooling
  blocker: local `mypy` and `ruff` are not discoverable by its preflight, even
  though direct pinned Ruff passed. No environment rebuild was performed.
- No real SVD inference/GPU acceptance was rerun; the execution boundary is
  unchanged and accepted runtime evidence remains reusable.

## Token-efficient validation plan

Run deterministic discovery, SVD controller, AppController bridge, and headless
SVD-tab tests first; then raw Ruff, the controller ratchet, one local PR-gate
attempt where practical, `git diff --check`, aggregate diff review, and required
GitHub Python 3.11/3.12 CI. Reuse accepted SVD runtime evidence: this package
does not alter SVD execution or GPU/model boundaries, so no real inference is a
package requirement.
