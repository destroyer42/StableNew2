# N5: packs × models batch builder

Status: in progress (2026-11-26). Way Forward item N5, after N12 (one canonical checkpoint key).

## Objective

- **Outcome.** One panel where the owner:
  - picks several PromptPacks and several checkpoints;
  - optionally turns ADetailer and upscale on or off for the batch;
  - names the batch;
  - before anything is queued, sees the exact job and image totals, an estimated time and every N1 warning once;
  - queues everything as one named batch.

  Each job records the batch identity, so the phone review gateway can later group its inbox by batch rather than by
  output run folder.
- **Why.** About 95% of 56k jobs are PromptPack jobs across many models. Today each pack × model combination is its
  own select-model, add-packs, preview and queue round. Usage data also shows about 3,350 bulk cancellations, which
  suggests batches turn out larger than expected. An exact count up front addresses that.
- **In scope:**
  - a pure batch planning and compile service;
  - batch identity in NJR provenance;
  - the dialog, a launcher on the Pipeline tab, and tests.
- **Explicit exclusions:**
  - The gateway protocol, store and inbox grouping change. The manifest `display` allows only `model`,
    `prompt_excerpt`, `job_id` and `workflow` (`src/app/review_gateway_protocol.py`), so grouping by batch is a
    separate RG package that reads the provenance written here.
  - Per-model ETA calibration.
  - Applying a model's saved generation profile per model (see owner question 3).
  - Video, img2img and reprocess sources.
  - Any new queue, runner, submission path or job model.

## Execution class and model recommendation

- Execution class: **Standard**. It is a new GUI surface plus one service, on the existing compile and submission
  path. Batch identity is additive provenance metadata of the kind N1 already writes, with no schema version change.
- Execution location: local.
- Model recommendation: Claude Code Opus-class at moderate effort; Codex GPT-5-class at medium.
- Expected usage: about 10M cache-read and 100k output.

## Exact start state and authorities

- Task start: 2026-11-26T15:17:24Z. Session claude:559b0b20-dd8d-49ce-82de-33c2630f36a4, shared with N12. The
  orchestrator is session 3d36ca46.
- Branch `claude/n5-batch-builder`, stacked on N12 `13ad601e` (`claude/n12-checkpoint-key-16971d`), which sits on
  `origin/main` 7bdaefad.
- Authorities: `AGENTS.md` sections 2 and 4–6; `STATUS.md`; `docs/Subsystems/PromptPacks/PROMPTPACKS_AND_PROMPTING.md`.

## Design

### Path (unchanged canonical path)

```
BatchBuilderDialog (Tk: capture intent, render plan)
  -> PackModelBatchService.plan()          worker thread: read pack rows, compile every cell
       build_pack_config / build_pack_entries   (pack_draft_service, as Add to Job does)
       PromptPackNormalizedJobBuilder.build_jobs  (a batch-owned instance, selection_review=None)
  -> BatchPlan (cells, NJRs, totals, ETA, warnings, per-cell problems)
  -> Queue: stamp_batch(records, identity) -> QueueSubmissionService.submit_normalized_jobs
       (sort by canonical model key, freeze N1 warnings) -> JobService.submit_njrs (all or none)
```

- **One cell = one pack × one model.** The cell's config snapshot is the Pipeline tab's working settings (captured
  on the GUI thread, exactly as `prepare_pack_draft` does). The only changes are `txt2img.model` (and
  `model_name`) set to that model, and the batch's ADetailer and upscale stage flags. Each model's compile policy is
  still applied per prompt by the builder (`compile_model_policy`).
- **The count is the compiled count, not an estimate.** Every cell compiles before the summary shows. So "N jobs,
  M images" is the number of NJRs Queue will submit, and their summed `estimated_image_count()`. Matrix and
  randomizer expansion is included, and the summary names any cell the matrix limit truncated
  (`provenance.metadata.matrix_expansion`).
- **Per-cell problems are shown, not hidden.** If a cell fails to compile, the summary lists it with its reason and
  the rest of the batch can still be queued. Examples: a Klein checkpoint that needs a LoRA selection review
  (`KleinSelectionError`) or an unreadable pack. This follows N1 "warn, don't block": a real block stays a block,
  but it is reported before Queue and scoped to its cell.
- **N1 warnings once per batch.** The union of `shown_model_warnings(record)` and `pending_warnings(record)` across
  every compiled NJR, de-duplicated by `PolicyWarning.key`, is listed once with each warning's why and fix. Queue on
  that summary is the acceptance. `submit_normalized_jobs` then freezes the warnings on every NJR as it already does.
- **ETA.** `DurationStatsService.get_estimate_for_chain` (median of recent completed jobs with the same stage chain,
  falling back to per-stage defaults), summed over the NJRs. The summary says which source each part came from
  ("from N recent runs" or "default"). It does not yet scale with image count or model (owner question 2).

### Batch identity (provenance)

Each NJR's `provenance.metadata["batch"]` is stamped at Queue time, so Preview compilation stays deterministic:

```json
{"schema": "stablenew.batch.v1", "batch_id": "<uuid4>", "name": "<owner text>",
 "cell": {"pack_id": "...", "pack_name": "...", "model": "<as selected>", "model_key": "<N12 checkpoint_key>"},
 "cells": 6, "jobs": 240}
```

- The stamp uses the same `replace(record, provenance=...)` re-freeze as N1's accepted warnings, so the job's
  identity and plan are unchanged.
- `model_key` is N12's canonical key, so the gateway and Learning can join on it.
- Reader: `batch_identity(record_or_snapshot) -> BatchIdentity | None` in the same module, for the later RG package.

### Where code lives (controller ratchets)

- `src/controller/pipeline_controller_services/pack_model_batch_service.py` (new, no Tk): `BatchRequest`, `BatchCell`,
  `BatchPlan`, `plan_batch`, `stamp_batch`, `batch_identity`.
- `src/gui/batch_builder_dialog.py` (new, Tk): a pack list, a model list, ADetailer and upscale checkboxes, a name
  field, a Plan button that runs on a worker, the summary, and Queue batch.
- `app_controller.py`, `pipeline_controller.py` and `job_service.py` are each exactly at their checked-in ceiling.
  Any line added there must be offset by a deletion, or the hook goes on a service the dialog reaches through the
  existing `_get_queue_submission_service()` accessor pattern.

## Owner UI questions (defaults used until answered)

1. **Where the panel lives.** Default: a **Packs × Models…** button on the Pipeline tab's PromptPack card opens a
   dialog. The alternative is a new top-level tab.
2. **ETA source.** Default: the existing Queue ETA source (history median per stage chain, per-stage defaults when
   history is thin). The alternative is a per-model, per-image calibrated estimate from history, as a follow-up.
3. **Per-model settings.** Default: one set of working settings from the Pipeline tab for every model, with each
   model's compile policy applied. Should a model with a saved generation profile (recipe) use its own sampler,
   steps and CFG in the batch instead?
4. **Default batch name.** Default: `YYYY-MM-DD <first pack> +N × <M> models`, editable.
5. **Large batches.** Default: no cap. A warning line shows above 500 images ("about Xh"), and Queue stays enabled.
6. **Gateway grouping.** Default: this PR only records the batch; inbox grouping is a follow-up RG package.

## Acceptance and evidence reuse

- Required behaviour:
  1. Planning two packs × two models compiles four cells through `PromptPackNormalizedJobBuilder` and shows exact
     job and image totals equal to what Queue submits.
  2. Queue makes one `JobService.submit_njrs` call (through `QueueSubmissionService.submit_normalized_jobs`) with
     every NJR stamped with one `batch_id` and its own cell.
  3. Warnings appear once in the summary and are frozen on each NJR.
  4. A failing cell is listed with its reason and excluded.
  5. Nothing compiles or reads files on the Tk thread.
- Evidence mode: deterministic tests (service, stamp and reader, the dialog with a fake service, and the
  no-second-queue boundary). Physical runtime: NOT RUN (the owner's live app runs from `StableNew-main`).
- Qualification claim: N/A.

## Token-Efficient Validation Plan

1. Run the focused tests for the service, the stamp and the dialog.
2. Run `tests/controller`, `tests/pipeline`, `tests/gui_v2` (alone) and `tests/system`.
3. Run `python tools/ci/run_pr_gate.py`, then `tests/system` and `tests/tools`, which the gate skips.
4. Run `git diff --check` and `tools/generate_code_map.py --check`.

## Stop conditions

- A controller ceiling cannot be met without raising it.
- Batch identity would need an NJR schema change.
- Answering an owner question changes the design materially.

## Documentation impact

- `docs/Subsystems/PromptPacks/PROMPTPACKS_AND_PROMPTING.md`: a "Packs × models batch" section.
- `STATUS.md`: one line, once the work merges.
- `docs/CODE_MAP.md`: regenerated.
