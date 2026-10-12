# PR-VID-BATCH-200 — Multi-Source Video Workflow Batch Submission

Status: **implemented and locally verified; pending owner review; not pushed or merged.** Validation is CPU /
fake-runtime only; no physical GPU run and no installed model or runtime was touched. "Eligible to queue" is a
software/admission statement, never a qualification of the installed GPU or runtime.

## 1. What it is

Turn 1–25 selected source images into **independent** Video Workflow jobs that share one workflow, one version and
one set of settings. Each source becomes its own immutable `NormalizedJobRecord`; the whole batch is admitted with
one `JobService.submit_njrs` call, so admission is all-or-none. It is not an experiment (PR-VID-194 varies one control
over ONE source) and not native SVD folder batching (a different backend and path).

No new queue, scheduler, runner, history, compiler or backend. The canonical path is unchanged:
`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`.

## 2. Source entry paths

| Path | Behavior |
|---|---|
| Single Image | Unchanged: editable Source Image, Browse, Use Latest Output, Queue Video Workflow. Choosing/browsing/handing off a single image returns the tab to single mode; while a batch preview, scan or queue step is still running the choice is refused with a status message instead of being half-applied. |
| Selected Images | "Select Images..." multi-file picker. Order preserved; duplicate canonical paths (resolved, case-folded) removed and counted. |
| Folder | "Select Folder..." with an explicit **Include subfolders** checkbox (default on, matching the Review tab's recursive folder import). Deterministic order: case-insensitive relative path. The status line states recursive or top-level-only. The walk runs on a worker (never on Tk) and skips the file-stat for non-image names. Linked folders are followed with loop protection. A scan that cannot finish - 1000 matches, 20000 entries visited, or a folder that cannot be read - is **refused**, never returned as a short list, so a batch can never look complete while silently omitting images. |
| From Review | "Send Selected to Video Workflow" uses the Review Listbox's **highlighted rows** in list order: never every imported image and never only the previewed one. Nothing highlighted sends nothing. One image keeps the existing single-source handoff. Transfers intent only. |

More than 25 sources are held whole and refused at Preview ("exclude at least N"); nothing is silently truncated.
Changing the selection mode or editing the source list invalidates any preview. The batch list is transient and is
never saved with the form.

## 3. Assess, then prepare and freeze (`src/video/video_workflow_batch.py`)

`VideoWorkflowBatchService` lives beside `VideoWorkflowNjrBuilder`; `VideoWorkflowController` only delegates.

1. **Assessment (publishes nothing durable).** Its only filesystem touch is the writability probe
   below, which creates and immediately deletes one anonymous temp file in the output root (or its nearest
   existing ancestor when the root does not exist yet). Form validation through the existing builder (workflow/version,
   controls, experimental opt-in, anchors, driving video, depth input), then per source: existence, supported image
   type, full decode, EXIF-aware dimensions and orientation, the catalog-declared target size, content hash,
   prepared-image `create` vs `reuse`, duplicate-content warning. Destination: the output location is a folder that a
   real (self-deleting) temp-file probe can write to - `os.access` ignores Windows ACLs - and
   free space versus the (upper-bound) size of prepared PNGs that must be created — a block — and a low-free-space
   warning for sustained generation. No clip-size forecast is made. Reported: workflow id/version/backend/governance,
   requested controls and whether the workflow accepts each, effective prompt/negative/length, seed policy.
2. **Prepare and freeze (only when every source is accepted).** The existing `freeze_inputs` and `build_job` run per
   source; this is the step that may publish StableNew-owned, content-addressed prepared PNGs (existing ones are
   reused; nothing is deleted). The Preview button and status disclose that preparation. A source that fails here
   blocks the whole batch.

Blocked sources are shown with a specific reason and can be excluded (`Exclude Selected` / `Exclude Blocked`); the
operator must then build a fresh preview of the revised list. A preview with any blocker admits nothing — there is
no "submit the remainder".

## 4. Provenance (additive; Review jobs and single-source jobs are unchanged)

Every NJR of a batch carries, in `provenance.metadata`:

```json
"batch": {"schema": "stablenew.batch.v1", "batch_id": "<uuid hex>", "batch_kind": "video_workflow",
          "source_index": 0, "source_count": 25}
```

`source_index` is **0-based**; `source_count` is the number of accepted sources. `metadata.video_workflow.source_identity`
records original path + SHA-256, prepared path + SHA-256 and the preparation policy. Lineage: the Review handoff's
`source_job_id` / `source_artifact_id` hints, or — for a Review selection only — the image's own embedded StableNew
job stamp, populate `parent_job_id` / `parent_artifact_id`; otherwise no parent is invented and the content hash is
the only source identity. A single-source job has neither `batch` nor `source_identity`.

Job ids are unique; output names for every selectable Comfy workflow embed the job id (`{{request.job_id}}`), so jobs
that share a seed or prepared image cannot overwrite one another. There is no persisted batch lifecycle: queue and
history remain the only authority.

## 5. Seeds, freezing and stale-input refusal

Explicit seed: the same value for every job. Blank seed: an independent concrete seed per source, resolved when the
preview is prepared, shown per job, and carried unchanged through admission (queueing never re-rolls). Workflows that
declare no seed show none.

`FrozenVideoInputs` gained evidence-only `shared_files` (end anchor, mid anchors, uploaded depth map the workflow
actually uses). `freeze_shared_inputs` hashes the driving video and these files **once** per batch, and admission
verifies them once, not once per job. Admission re-verifies every source and prepared source (content hash, so a
same-size/same-mtime replacement is caught), the shared inputs, the batch descriptors, the plan digest and the per-job
experimental opt-in, then makes ONE `submit_njrs` call. Any failure admits zero jobs and tells the operator to
re-preview. The plan is single-use (a double click, repeated callback or late worker cannot admit twice); a failed
admission releases it for retry. If the repository transaction committed but a follow-up step raised, the admitted ids
are reported with a note, never "rolled back". Runner-start failure after admission is handled by `JobService` as
before (ids returned, jobs retained).

## 6. Threading

`VideoBatchSession` (`src/gui/view_contracts/video_batch_contract.py`) mirrors `VideoExperimentSession`:
`begin_*` on Tk (snapshots plain inputs), `run_*` on a `ThreadRegistry` worker, `finish_*` back on Tk through
`TkUiDispatcher`, with a token + input fingerprint that discards a late result after any edit. The folder walk,
hashing, decoding, preparation, NJR construction and admission never run on the Tk thread; choosing an explicit file list
only normalizes the dialog's paths on Tk. The compact source controls and the Preview / Queue
buttons live in the fixed tab header: one control row (plus one summary line while a batch exists; about +30 px, measured
151 px single-mode and 172 px with 25 sources at 1280x800). The per-source table, exclusion actions and preview text
are at the top of the scrolled body. Batch mode disables the single Queue button.

## 7. Unchanged

Single-source submission, one-variable experiments (their freeze now also covers file-backed anchors/depth),
catalog-pinned versions, experimental opt-in (default off), frame-count and operator controls, source-preparation
policies, native SVD folder batching, Review reprocessing, Comfy process ownership (an external runtime is never
adopted), PR-QUEUE-WEBUI-171 containment (batch jobs classify as independent video), sequential execution, and the
`app_controller.py` ceiling.

## 8. Evidence and limits

`tests/video/test_pr_vid_batch_200_multisource.py` (service, provenance, stale inputs, atomic admission against a real
`JobService`/SQLite, rollback, runner-start failure, and 25 jobs dispatched through the real sequential runner with a
fake backend) and `tests/gui_v2/test_video_workflow_batch_ui.py` (session, Tk tab, Review handoff). Not covered:
physical generation, real Comfy runtime behavior, and any real disk-usage measurement.

Follow-ups left out on purpose: per-source prompts, cross-workflow batches, persisted batch history, a
recycle-aware scheduler for owned-Comfy per-job restarts.
