# LEARN-JOIN: keep and favourite rates by recipe

Status: implemented, awaiting merge (2026-11-27). Package 7 of the 2026-11-27 Value Assessment, formerly Way Forward item N10.
Builds on N5 (batch identity), N12 (canonical checkpoint key) and RG-100..140 (phone decisions as review evidence).

## Objective

- **Outcome.** One read-only Learning view that answers "what do I keep?": keep and favourite rates, with reason-tag
  counts, by model and, per model, by prompt slot value, LoRA and strength, embedding and strength, sampler, steps,
  CFG and PromptPack, plus by named batch.
- **Why.** The owner decides nearly everything on the phone. Those decisions already land in the Learning evidence
  file, but a decision row carries no prompt, slot, LoRA, embedding or batch data, Favorite and reason tags have no
  reader, and no screen shows a keep rate.
- **In scope:**
  - a read-time join of current image decisions to their job's immutable NJR snapshot;
  - the rates and a significance rule;
  - a batch stamp on new decision rows (job id is already stamped);
  - the view and its launcher on the Learning tab, in Simple and Advanced;
  - tests and canonical docs.
- **Explicit exclusions:**
  - No recommendation, score, Apply, publication, proposal or settings change reads this report. The
    recommendation engine's treatment of dispositions is unchanged.
  - No new history, store, cache file, index or schema change. Nothing is written when the report is built.
  - Videos, favourite weighting in recommendations, per-option "published but undecided" rates, and charts.
  - No backfill or rewrite of existing evidence rows.

## Definitions

- **Unit:** one image, identified by the SHA-256 of its bytes. Its **current** decision is the last disposition row
  for those bytes (desktop or phone). `retain` and `discard` count; `rework` and `cleared` do not.
- **Keep rate:** kept / (kept + deleted). **Favourite rate:** favourites / (kept + deleted). A favourite is a current
  Keep with `review_favorite`; only the phone sets it.
- **Join:** the row's `source_job_id` (carried forward from an earlier row for the same bytes if the latest lacks
  it) to `jobs.job_id`, read by primary key on a `mode=ro` connection in chunks.
- **Model:** `checkpoint_key` of the enabled generating stage's model.
- **Difference:** an option is compared with the other images of the same group (same model and factor) by a
  Newcombe (Wilson score) interval for the difference of proportions at 95%, Bonferroni-corrected for the number of
  comparisons in that group, and only when both sides have at least 30 images. If the interval includes zero the view
  says **not enough yet**. (Telling 85% from 80% reliably takes about 900 images per option.)

## Execution class and model recommendation

- Execution class: **Standard**. Read-only projection over existing authorities plus one additive metadata key.
- Execution location: local.
- Model recommendation: Claude Code Sonnet-class at moderate effort; Codex GPT-5-class at medium.

## Controller Surface Assessment

No controller or coordinator gains a responsibility. The view's data loader lives beside the other Learning GUI
adapters (`src/gui/controllers/`); `app_controller.py` is not touched.

## Design

| Piece | Owner |
|---|---|
| Decision selection, NJR facts, aggregation, intervals | `src/learning/decision_rates.py` (pure, Tk-free) |
| Bounded read-only snapshot read | `JobRepository.read_snapshots_for_jobs` |
| Published image digests (undecided count) | `review_gateway_store.read_published_image_digests` (`mode=ro`) |
| Composition of the three sources | `src/gui/controllers/keep_rates_loader.py` |
| Window | `src/gui/views/keep_rates_window.py`, opened from the Learning header |
| Batch stamp `review_batch` | `review_evidence.stamp_review_batch`; phone applier (injected reader) and desktop Review |

RG-100 invariant 6 holds: `review_gateway_apply` still has no reference to the queue, runner or `JobService`; the
batch reader is injected by `runtime_stack`, as the publisher's already is.

## Acceptance

1. A phone and a desktop decision for a PromptPack job both appear under that job's model, slot values, LoRAs,
   embeddings, sampler, steps, CFG, pack and batch.
2. A later decision replaces an earlier one for the same image; Undo removes it; Re-work is not counted.
3. A group below the data threshold, or whose interval includes zero, reads "not enough yet".
4. Building the report writes nothing: the database is opened `mode=ro`, and no file is created or changed.
5. The button is present in Simple mode; no tab is added.
6. The view says how many decisions could not be joined and how many published images are still undecided.
7. A new decision row for a batch job carries `review_batch`; a failed batch lookup never blocks the decision.

## Token-Efficient Validation Plan

Focused tests for the new module, repository read, stamp and window while building; then
`python tools/ci/run_pr_gate.py` once, plus `tests/learning`, `tests/system` and `tests/tools`; then one read-only
run of the report against the live data for counts.
