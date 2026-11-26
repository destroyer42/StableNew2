# AI-VL-240: Review label export for a real-image evaluation set

## Objective

- Outcome: a read-only exporter, `python -m tools.qualification.vl240`, that turns the operator's existing human Review
  evidence into one real-image evaluation export (schema `stablenew.vl240.review_export/1`) with a hash manifest, plus an
  operator guide (`docs/runbooks/ai_visual_real_set.md`). The set is the human-labelled real-image evidence that the
  [visual evaluation contract](../../Subsystems/AiAssist/PR-AI-VL-220_Visual_Evaluation_Contract.md) and the
  [roadmap](../../Subsystems/AiAssist/INTELLIGENT_IMAGE_REVIEW_ROADMAP.md) require before any visual candidate can be judged.
- In scope: `tools/qualification/vl240/`, `tests/tools/test_ai_vl240_export.py`, this document, the runbook, one line each in
  `STATUS.md` and `docs/CODEX_MAP.md`.
- Explicit exclusions: any change under `src/`; any write to Review, Learning, History or queue state; running a model, the
  app, a backend or GPU work; the conversion of the export into VL-220 cases and labels and the scoring (AI-VL-242); the
  evaluation driver (AI-VL-241); any real image, prompt or label in Git.

## Execution class and model recommendation

- Execution class: Standard (new tool package, no runtime or architecture change).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5, medium effort; Codex GPT-5.x, medium effort. The work is a bounded reader over
  known stores with deterministic tests; no design decision needs a stronger tier.
- Expected usage: about 10M cache-read tokens, 100k output.

## Exact start state and authorities

- Task start: 2026-11-15T07:18:25-05:00 (this session, `claude/ai-vl-240-review-label-export-a1ee0a`, started from the
  AI-VL-24x sibling group's coordinator session).
- Start SHA: `1e58eda4`, fast-forwarded to `origin/main` `bbc63978` before any change (it adds IMG-REVIEW-400, PR #312, which
  this package audits).
- Authorities read: `AGENTS.md`, `STATUS.md`, the roadmap, `docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md` section 3.3.3,
  `docs/Subsystems/Learning/LEARNING.md`, and the code cited below.

## Surface assessment

- Files allowed to change: the paths above only.
- Controller or coordinator surface touched: No. The tool imports nothing from `src/controller` except the visibility
  resolver (read-only) and writes nowhere that the application reads.
- Controller Surface Assessment: not applicable; no controller file changes and no ratchet ceiling moves.
- Architecture authority or invariant changed: No. The exporter reads; it is not a queue, runner, history, compiler or
  Review write path.

## 1. Audit: what Review records today

All paths and lines are on `bbc63978`.

### Where each fact lives

| Fact | Recorded? | Where, and how it is bound |
| --- | --- | --- |
| Finding (category, region, certainty, confirmation) | **Not persisted.** `Finding` exists only as the dialog's in-memory list (`src/gui/guided_review_dialog.py:79`, `_record` :375, `_store_finding` :422) and is dropped when the dialog closes; the contract says "Finding text stays in the inspection session" (`PHOTO_REVIEW_REPROCESS.md` 3.3.3). | Taxonomy: `Category` (`src/review/findings.py:18`): Face, Hands, Anatomy, Composition, Rendering artifact, Prompt adherence, General / local issue. Region: half-open stored-pixel box or whole image (:55). Confirmation: Unreviewed, Confirmed, Rejected, Uncertain (:40). |
| **Severity** | **No.** `Finding` has no severity field (:90). | n/a |
| Who confirmed | Implicit only. `Origin` is Operator, Detector or External model (:28), but it is not persisted. A suggestion cannot be confirmed with its own text (`_record` :392-402), so a confirmed finding is always the operator's statement. | n/a |
| Defect confirmed for an image, **only when the operator queued a correction for it** | Yes, indirectly. `recommend()` offers an action only for a `Confirmed` finding (`src/review/correction_advice.py:187`), `_open_draft` re-checks the finding is unchanged (`guided_review_dialog.py:536`, :580), and the queued job's frozen provenance stores `guided_correction`: schema, action, category, region, source size (`src/review/findings.py:122`, written at `src/controller/masked_edit_service.py:244` and `src/controller/review_batch_service.py:150`). | Job repository, SQLite `jobs.njr_snapshot` (`src/queue/job_repository.py:306`) at `normalized_job.provenance.metadata.guided_correction`; the source digest is `parent_artifact_id` as `sha256:<hex>` (:341-342). The image file is not named by digest, so the exporter finds it among paths the job records and accepts it only if its SHA-256 equals the claim. |
| **Confirmed clean ("inspected, no defect")** | **No.** There is no control, record or schema for it. The dialog's only outputs are findings (in memory), a correction draft and a pair judgment. | n/a |
| Improvement judgment on an original/corrected pair | Yes. Per-region outcome `improved / unchanged / worsened / uncertain` plus an overall preference (`src/review/improvement_evidence.py:227-267`, `VISUAL_OUTCOMES` in `src/pipeline/adetailer_effectiveness.py:31`). The roadmap's helped / no benefit / worse / inconclusive map one to one. | Learning record file `learning_records.jsonl` (append-only JSONL, `src/learning/learning_record.py:263`), `metadata.review_context.guided_improvement_review`, saved through `LearningController.save_review_feedback` (`src/gui/controllers/learning_controller.py:2477`) from `GuidedReviewDialog._save` (:724). Bound to both digests (`source_sha256`, `result_sha256`), the result job id and the result size, re-checked at the writer. Record id is the Learning `run_id`. The latest record for a job wins (Undo deletes one). |
| Intervention used | Yes, for guided corrections: `guided_correction.action` (Edit mask, ADetailer face pass, ADetailer hand pass, Reprocess with img2img) with category and region, plus the NJR's enabled stages and `source.kind`. A pair judged without a guided correction (an iterated History child) records `source.kind` and stages only. | Same `njr_snapshot`. |
| Image identity | Yes: SHA-256 and pixel size in the judgment record; source digest as `parent_artifact_id`; lineage through `parent_job_id`, `parent_artifact_id` and the History compare checks (`improvement_evidence.py:114`). Width and height are read from the file header. | See above. |
| Content visibility | Yes, on the image itself: `content_visibility` in the embedded v2.6 metadata payload, `corrupt` payloads treated as restricted (`src/review/inspection.py:59-63`), resolved by `ContentVisibilityResolver` (`src/controller/content_visibility_resolver.py:241`). The app default mode is `nsfw` (`review_tab_frame_v2.py:139`). | Embedded image metadata. |
| Model family | **Not recorded.** The NJR freezes a checkpoint file name, not the policy family; the family is resolved from the asset registry at run time. File names can reveal content, so the exporter does not copy them. | n/a |
| Subject count | **No.** | n/a |
| Per-element prompt adherence | **No.** Review has a 1-5 `prompt_adherence` subscore in the ordinary Review feedback record (`workflow_adapter.py:469`), bound to a path only, and the ordinary save may stamp the file and change its digest (`PHOTO_REVIEW_REPROCESS.md` 3.3.3). It is subjective, defaults from the overall rating, and has no per-element verdicts. | Not exported. |
| ADetailer face/hand outcome (`adetailer_outcome_review`) | Yes, but it names image **paths only**, no digest (`src/review/adetailer_outcome.py:89-114`), and the same save stamps the file, so the reviewed bytes cannot be proven. | Not exported (cannot bind to a hash). |

### What each roadmap dimension can use today

| Dimension | Available from Review today | Not available |
| --- | --- | --- |
| Anatomical defect triage | Confirmed category and region (no severity) on source images that the operator also queued a correction for. Face, Hands and Anatomy are the categories the correction path serves. | Defects the operator did not correct; severity; any image the operator inspected but did not correct. Recall of a confirmed region can be scored; **precision cannot**, because an unmarked region is not a negative. The set is biased to correctable defects on registry-verified SDXL models (the guided correction refuses other targets). |
| Clean-image false positives | Nothing. | The whole dimension: no confirmed-clean mark exists. |
| Before/after usefulness | The strongest dimension: per-region and overall human judgments on hash-bound original/corrected pairs, with the action used. | Pairs without a verified source lineage cannot be judged in Review, so they are absent. |
| Multi-subject consistency | Nothing. | Subject count is not recorded. |
| Prompt adherence | Nothing usable. | Per-element verdicts; the prompt text itself is deliberately not exported. |
| Hallucination | Nothing directly. | Needs confirmed-clean images (a claimed defect on a clean image) or confirmed absences. A model finding outside a confirmed region is not a proven hallucination, because operators mark only what they act on. |

## 2. What the exporter does

`python -m tools.qualification.vl240 describe|export|verify` (`tools/qualification/vl240/`):

- `describe`: counts by stratum and progress against the full or pilot targets (`--targets pilot`); no ids, paths or text.
- `export`: writes `<out>/vl240-<UTC stamp>/` (default `D:\StableNew-Assets\offline-ai\visual-evaluation\`) holding
  `review_export.json`, `manifest.json` and `images/<sha256>.<ext>` (copied, or hard-linked with `--link`). Refuses an output
  inside any Git work tree or an existing folder.
- `verify <folder>`: re-hashes everything against the manifest.
- Inputs default to this checkout's `data/learning/learning_records.jsonl` and `jobs.sqlite3`; `--learning-records` and
  `--job-repository` override. The record file is opened for reading, the repository `mode=ro`, `query_only`, and `immutable`
  when no `-wal` file exists. When a `-wal` file exists (the app is running) the repository is read from a private snapshot
  that is removed on exit, because SQLite cannot read a live WAL database read-only without creating `-shm` files beside it.
- Visibility: `--content-visibility sfw` (default, fail closed) withholds restricted items; `nsfw` exports them. Counts of
  what was withheld are reported. A pair needs both images visible.

### Export schema as implemented (`stablenew.vl240.review_export/1`)

```text
schema                      "stablenew.vl240.review_export/1"
images[]                    sorted by sha256
  image_id                  opaque "img-0001", assigned in hash order
  sha256, file              file = "images/<sha256>.<png|jpg|webp>"
  width, height             stored pixels, from the file header
  model_family              null (not recorded)
  clean_confirmed           false (no explicit human mark exists in Review)
  findings[]                {category (Review taxonomy), region [left,top,right,bottom]|null (whole image),
                             severity null (not recorded), record_id (job id of the queued correction)}
  subject_count             null (not recorded)
  roles[]                   "before" | "after" for images used in a pair
  record_ids[]              job ids and Learning run ids the facts came from
pairs[]                     sorted by before, after, job; only pairs with one human judgment
  pair_id                   opaque "pair-0001"
  before_image_id, after_image_id
  intervention              {kind, stages[]} and, for a guided correction, {action, category, region}
  judgment                  helped | no_benefit | worse | inconclusive
  region_judgments[]        {category, region [l,t,r,b]|null, judgment}
  overall_preference        prefer_original | prefer_result | no_preference | inconclusive | null
  record_ids                {learning_record, job}
mixed_pairs[]               same shape, judgment "mixed": the operator judged regions differently (for example hands
                            improved, face worsened). Kept apart so no consumer reads it as one of the four; counted by
                            `describe` but not toward the pair target
provenance                  {labeler "human", basis, sources, exported_at, exporter_version, content_visibility_mode,
                             contains_prompt_text false, availability{...}}
```

`provenance.availability` repeats which fields Review cannot supply, so a consumer never infers an absence. The manifest is
`{schema "stablenew.vl240.image_manifest/1", document {path, sha256}, files[{path, sha256, bytes}]}`. Refusals (codes only,
never content) are counted by `describe`: `image_unavailable`, `image_changed_since_review`, `job_not_found`,
`judgment_source_mismatch`, `no_recorded_source_digest`, `malformed_correction`, `malformed_judgment`, `malformed_digest`,
`not_an_operator_judgment`, `job_repository_unreadable`, `learning_records_unreadable`.

Only operator-confirmed facts are used: a guided-correction provenance block (which exists only because a confirmed finding
was acted on) and a record whose own `source` is `operator_review`. AI suggestions, unconfirmed findings, pixel-change
measures, 1-5 ratings and path-only records are never exported.

## 3. Gaps and the smallest change that would close each

None of these was added to `src/` by this package. Each needs its own authorization (a Review behavior change that stores a
new kind of operator evidence). One change, "Save inspection", closes the first four together.

**Status (2026-11-17): the first four rows are closed by AI-VL-243** (`docs/archive/work_packages/AI-VL-243_save_inspection.md`, owner
decision D25). The record that was implemented differs from the sketch below: it is a Review evidence kind `review_inspection`
(source `review_tab_inspection`, `src/review/review_evidence.py`) written through the same `LearningRecordWriter` by Inspect &
Improve's **Save inspection** / **No defect seen**, with `verdict`, `findings[]` of category, region, certainty and optional
severity (no observation text), and an optional `subject_count` of 1 to 12. The exporter reads it (`clean_confirmed`, findings,
severity, `subject_count`) and `describe` reports it. The last three rows remain open. The sections above describe the exporter
and the audit **as of AI-VL-240** (`clean_confirmed` always false, `subject_count` always null); sections 1 and 2 are history.

| Gap | Smallest change | What evaluation can do without it | Status |
| --- | --- | --- | --- |
| No confirmed-clean mark | An "Inspected, no defect seen" control in Inspect & Improve that saves, through the existing `_save_feedback` / `save_review_feedback` path and the same proof-at-the-writer rule used for pair judgments, a record `guided_inspection_review {schema, source: operator_review, image_sha256, image_size, verdict: no_defect_seen}`. Hash-bound, never stamps the file. | Score defect recall on confirmed regions and before/after usefulness. Report clean-image false positives, hallucination and refusal on clean input as NOT MEASURED. Do not use unmarked images as clean. | Closed by AI-VL-243: `verdict: no_defect_seen`. |
| Confirmed findings are not saved unless a correction is queued | The same record carries `findings[]` (category, region, certainty, confirmation; **no observation text**) when the operator saves the inspection. | Findings for corrected images only (exported now). | Closed by AI-VL-243: `verdict: defects_confirmed` with `findings[]`. |
| No severity | An optional two-value severity (`minor`, `major`, matching the VL-220 contract) on `Finding` and in the record. | Score category and region without severity; skip the severity check. | Closed by AI-VL-243: optional `Finding.severity` and `findings[].severity`. |
| No subject count | An optional "Subjects in image" integer in the same record. | Multi-subject consistency NOT MEASURED. | Closed by AI-VL-243: optional `subject_count` (1 to 12). |
| No per-element prompt adherence | Larger than the others. Smallest: operator-authored element rows (label, present / partly / absent) in the same record. The labels are prompt-derived text, so they need an explicit owner decision on whether private prompt-derived labels may be exported. | Adherence NOT MEASURED. The 1-5 subscore is neither hash-bound nor per-element and is not a label. | Open: needs an owner privacy decision on prompt-derived labels. |
| `adetailer_outcome_review` has no digest | Add the two SHA-256 digests to `reviewed_pair` and stop stamping in that path. | Superseded by the guided pair judgment, which is exported. | Open. |
| Model family not frozen | Record the policy family in the job's provenance at admission. | Stratify by nothing; the checkpoint name is withheld on purpose. | Open. |

## Acceptance and evidence reuse

- Required behavior: the exporter writes a schema-valid, hash-manifested export from synthetic Review evidence; exports only
  confirmed facts; applies visibility; refuses unbindable records with a code; leaks no prompt, note or file name into the
  export, stdout or exceptions; writes nothing to the stores it reads; uses no network and starts no process.
- Evidence: `tests/tools/test_ai_vl240_export.py` (deterministic, synthetic fixtures; a write-detecting fixture makes the
  record file and repository read-only, compares size and modification time and directory listings before and after, and
  includes a live WAL repository and snapshot cleanup; sockets, `subprocess.Popen` and `os.system` are patched to fail);
  `tests/tools` and the canonical PR gate.
- Qualification claim: N/A. The export is evidence input, not a qualification verdict.
- Not demonstrated: the exporter has not been run against the owner's data (the owner runs `describe`, which prints counts
  only); no model has been run; the shape of the owner's real records is known from code and tests, not observed.
- Known blockers or non-blocking debt: the gaps in section 3. About 33 runtime-transition tests fail locally against a live
  ComfyUI/Forge endpoint, and one golden-path journey test fails in worktrees; both are pre-existing.
- Stop condition: the acceptance contract above is true. Conversion to cases and scoring belong to AI-VL-242.

## Documentation impact

- `STATUS.md`: one line. `docs/CODEX_MAP.md`: one line. Roadmap, architecture and `AGENTS.md`: unchanged.
