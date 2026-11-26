# AI-VL-243: Review "Save inspection" (clean mark, confirmed findings, severity, subject count)

## Objective

- Outcome: the operator can record, in Review's **Inspect & Improve**, what they concluded about one exact image: either
  *no defect seen* (a confirmed-clean mark) or the set of defects they confirmed (category, region, certainty, optional
  severity), plus an optional subject count. The record is non-mutating Review evidence bound to the image bytes. The
  AI-VL-240 exporter reads it, so the real-image evaluation set can contain clean images, severity and subject counts. This
  closes the first four gaps of `docs/archive/work_packages/AI-VL-240_review_label_export.md` section 3. Owner decision D25.
- In scope: `src/review/review_evidence.py` (record kind `review_inspection`), `src/review/findings.py` (optional
  `Severity`), `src/gui/guided_review_dialog.py` (the controls), `src/gui/views/review_tab_frame_v2.py` and
  `src/gui/view_contracts/review_workspace_contract.py` (writer hand-off, Undo, one-line row indicator),
  `tools/qualification/vl240/` (reader and `describe`), tests, `docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md`,
  `docs/runbooks/ai_visual_real_set.md`, the AI-VL-240 gap table, this document, `STATUS.md` and `docs/CODEX_MAP.md` (one
  line each, last commit).
- Explicit exclusions (recorded as the follow-up below): per-element prompt adherence (it needs prompt-derived labels, which
  need a separate owner privacy decision), model family at admission, and the `adetailer_outcome_review` digest. Also out:
  any change to the canonical path, queue, runner, History, compiler or `LearningController`; running a model, the app, a
  backend or GPU work; any real image, prompt, note or label in Git, a log or a PR; `tools/qualification/vl220` (checked,
  unchanged) and contract `eval/2` (gate values and digests unchanged).

## Execution class and model recommendation

- Execution class: Standard (one new Review evidence kind on the existing writer, a bounded dialog change, a tool reader; no
  runtime ownership or architecture change).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5, medium effort; Codex GPT-5.x, medium effort. The design is fixed by D25 and
  mirrors the disposition record; the risk is in GUI gating and privacy tests, which are deterministic.
- Expected usage: about 15M cache-read tokens, 150k output.

## Exact start state and authorities

- Task start: 2026-11-17T05:16:31-05:00, Claude Code session `claude/ai-vl-243-save-inspection-e306a7`, started from the
  AI-VL-24x coordinator session; branch `feat/ai-vl-243-save-inspection`.
- Start SHA: `19dcb479` (`origin/main`, merge of PR #331).
- Authorities read: `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md`, `docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md`
  (3.3.3, 3.7, 5.3), `src/review/review_evidence.py`, `src/review/findings.py`, `src/gui/guided_review_dialog.py`, the
  Review save path in `src/gui/views/review_tab_frame_v2.py` and `LearningController.save_review_feedback`, and
  `tools/qualification/vl240/`, `tools/qualification/vl220/review_export.py`.

## Surface assessment

- Controller or coordinator surface touched: **No.** `LearningController` and every ratcheted controller are unchanged. The
  inspection reaches the one writer exactly as a disposition does: the Review frame (a view) resolves
  `learning_record_writer` and calls `review_evidence.save_inspection`. No ceiling moves.
- Controller Surface Assessment: not applicable (no file under `src/controller` or `src/gui/controllers` changes).
- Architecture authority or invariant changed: **No.** No job, NJR, queue entry, history row or runner call is created.
  Review evidence still has one writer (`LearningRecordWriter`). The inspection is not a decision: it does not change an
  image's Review state, the re-work scope or any filter.

## Design as implemented

### Record

`review_evidence.build_inspection_record` / `save_inspection` append one `LearningRecord` (same shape as a disposition: no
base config, one randomizer plan). `metadata`:

```text
source                      "review_tab_inspection"      own source: rating listing, "Undo" and disposition lookup never see it
record_kind                 "review_inspection"
image_path                  locator only
artifact_sha256             SHA-256 of the reviewed bytes (the identity)
inspection_schema           "stablenew.review-inspection"
inspection_schema_version   1
verdict                     "no_defect_seen" | "defects_confirmed" | "cleared" (cleared is written only by Undo)
findings[]                  exactly {category, region, certainty, severity}
  category                  Category value (Face, Hands, Anatomy, Composition, Rendering artifact, Prompt adherence,
                            General / local issue)
  region                    [left, top, right, bottom] half-open stored pixels, or null (whole image)
  certainty                 Certainty value (Unknown, Tentative, Clear to the operator)
  severity                  "minor" | "major" | null (not recorded)
subject_count               integer 1-12, or null ("not recorded")
reviewed_at                 sub-second UTC time (orders two saves within one second)
source_job_id               optional, as for dispositions
```

Rules, each enforced at build and again on read (`parse_inspection_row`):

- `no_defect_seen` has no findings; `defects_confirmed` has at least one; `cleared` has none and no subject count.
- Only findings whose `confirmation` is `Confirmed` are stored. `Finding` cannot be `Confirmed` without the operator's own
  observation text, and the dialog refuses to confirm an imported AI or detector suggestion with the suggestion's own text,
  so a confirmed finding is the operator's statement. Origin, suggestion label and observation text are **never stored**: the
  record is closed vocabulary, and a stored finding with any other key is refused on read.
- Two findings with the same category and region are stored once (the first). More than 24 findings is refused.
- A region is checked against the image's stored size at save (`Region.validate`) and again by the exporter against the file.
- Latest row per digest wins (file order). A malformed latest row is reported as malformed and never replaced by an earlier
  one. A row whose recorded bytes differ from the file at that path is reported `changed` and never applied.
- Undo writes a `cleared` row (nothing is deleted or rewritten); lookups then report no inspection.

Readers next to the existing lookups: `lookup_inspection(records_path, image_path, digest) -> InspectionLookup`,
`EvidenceIndex.inspection(...)` (one pass over the file, used by the Review workspace) and
`EvidenceIndex.inspection_rows()` (the latest raw row per digest, which the exporter parses with `parse_inspection_row`).

### Finding severity

`Finding` gains `severity: Severity | None = None` as its last field, `Severity` is `minor` / `major` (the VL-220 values).
Nothing existing reads or serializes it: `correction_context` (the provenance a queued correction freezes) is unchanged, and
a finding constructed as before compares equal to one with `severity=None`. (There is no serializer of `Finding` itself;
`dataclasses.asdict` would show the new key, and nothing calls it.)

### Dialog

In **Inspect & Improve**: a **Severity (optional)** list per finding (Not recorded / minor / major), a **Subjects in image
(optional)** field, and two explicit buttons.

- **Save inspection** is enabled only when at least one finding is Confirmed, and saves exactly the Confirmed findings as
  `defects_confirmed`. Rejected, Uncertain and Unreviewed findings are not saved.
- **No defect seen** is enabled only when no finding is Confirmed. It is an explicit click, never a default. It is also
  refused while any finding is marked Uncertain (a decision within D25: an "Uncertain" finding means the operator is not
  sure there is no defect, so a clean label would be unsafe; set it to Confirmed or Rejected first).
- Refused with a plain message, and nothing written: Learning evidence not connected; the dialog's image not yet read, not
  a PNG/JPEG/WebP still image, hidden by the content visibility mode, or no longer the image shown; a subject count that is
  not a whole number from 1 to 12 (empty means "not recorded"); the image's bytes changed since the dialog opened
  (re-verified against the opened digest on the worker, immediately before the write).
- It does not queue a correction, create a job, open a draft or stamp the file, and it changes no existing action. After a
  save the dialog stays open, so a correction can still be drafted; saving again appends a newer row (latest wins).
- The write and the digest check run on the dialog's `EditWorkRunner` worker, never on the Tk thread.

### Review workspace

After a save, the image's one-line row in the Review list shows `(inspected: no defect)` or `(inspected: defects)`: the
verdict only, in the one place that already shows an image's decision state and rating (`row_text`). The status line says
that the file was not changed and no job was queued. `ItemFacts.inspection` is read from the evidence file with the other
facts (so it survives a restart), a local save or Undo made after a refresh began is not overwritten by that refresh, and a
changed file shows nothing. **Undo (U)** and the Undo button undo the most recent of {decision, inspection, rating}; for an
inspection it records a `cleared` row and the indicator disappears.

### Exporter (`tools/qualification/vl240`)

Schema id `stablenew.vl240.review_export/1` and every spelling AI-VL-242 relies on are unchanged; `EXPORTER_VERSION` is 2.

- `clean_confirmed` is true only from a latest `no_defect_seen` row. `findings[]` come from the guided-correction source and
  from a latest `defects_confirmed` row, merged on category and region (the operator's saved severity fills one a correction
  did not carry); `severity` and `subject_count` are exported from the row.
- The image file is found only through the record's own `image_path` (or an image already bound by another source) and is
  accepted only when its SHA-256 equals the recorded digest. Changed bytes: excluded and counted
  (`inspection_image_changed_since_review`); a missing file: `inspection_image_unavailable`.
- A clean mark plus a confirmed finding on the same bytes (from a queued correction) is reported
  (`clean_contradicts_confirmed_finding`) and neither label is exported; an image that belongs to no judged pair then leaves
  the export. A malformed row (including any finding with free text) is `malformed_inspection`.
- A cleared latest row exports nothing and is counted. Visibility applies as for every image (`withheld_by_visibility`
  gains `inspection_image`).
- `describe` adds `counts.clean_confirmed_images`, `counts.inspections_by_verdict`, `counts.images_with_subject_count`,
  `counts.subject_counts` (1, 2, 3, 4, 5_or_more) and `counts.findings_with_severity`. Clean-image and multi-subject targets
  are now `recordable_in_review: true`. `provenance.availability` states where each label comes from. Still counts only: no
  ids, paths or text.
- `tools/qualification/vl220/review_export.py` already accepts `clean_confirmed: true`, an empty `findings`, an integer
  `subject_count` of 0 or more and ignores `severity`; it was checked with a test and **not changed**.

## Acceptance and evidence reuse

- Required behavior: see the tests below; every Tk dialog is patched; fixtures are synthetic.
- Completion evidence expected: evidence mode deterministic test; qualification claim N/A. The record, readers, dialog,
  workspace indicator, Undo and exporter are demonstrated on synthetic data only.
- Tests: `tests/review/test_review_inspection_243.py` (record build and validation, closed vocabulary and no observation text,
  verdict/findings consistency, subject-count bounds, digest identity including changed bytes, latest wins and Undo, rating /
  disposition / Undo behaviors unchanged, `Finding` without severity unchanged), `tests/gui_v2/test_review_inspection_243_gui.py`
  (save, No defect seen, refusals, no job created, workspace indicator, Undo), `tests/tools/test_ai_vl240_export.py`
  (clean, defects, merge, contradiction, changed-bytes exclusion, describe counts, no content in output, zero writes to the
  stores it reads, vocabulary pinned to Review, the VL-242 converter accepting the fields).
- Not demonstrated: physical GUI behavior in the live app (the owner has not tried it); the exporter on the owner's data; any
  model run. The change is unproven in the live app until the owner tries it.
- Known blockers or non-blocking debt: about 33 runtime-transition tests fail locally against a live ComfyUI/Forge endpoint;
  one golden-path journey test fails in worktrees. Both pre-exist.
- Review/Repair Budget: one batched repair cycle.
- Stop condition: the acceptance contract above is true.

## Token-Efficient Validation Plan

1. Focused: the three test files above, then `tests/review`, `tests/gui_v2` and `tests/tools`.
2. `ruff check` / `ruff format --check` on the touched files, `git diff --check`.
3. `python tools/ci/run_pr_gate.py` in an isolated worktree (after the baseline census if `main` moved).
4. Required CI (`required`, `full-suite`, `windows`) on the exact head, then the AGENTS section 5 check, then merge.

## Follow-ups (not done here)

- **Per-element prompt adherence** needs operator-authored, prompt-derived labels. Exporting them needs a separate owner
  privacy decision. Until then prompt adherence stays NOT MEASURED (a `Prompt adherence` finding is exported by the exporter
  and dropped by the VL-242 converter, as before).
- **Model family at admission**: record the policy family in the job's provenance so the set can be stratified without
  exporting checkpoint names.
- **`adetailer_outcome_review` digest**: add the two SHA-256 digests to `reviewed_pair` and stop stamping in that path.
- **Undo restores nothing**: Undo of an inspection writes `cleared` (D25), so it also hides an earlier inspection of the same
  bytes. Re-saving restores it. Restoring the previous row would be a small change if the owner prefers it.
- **Inspection closed during a save**: if the dialog is closed while a save is on the worker, the record is still written but
  the row indicator appears at the next refresh.

## Documentation impact

`PHOTO_REVIEW_REPROCESS.md` (3.3.3, 3.7, 5.3), `ai_visual_real_set.md`, the AI-VL-240 gap table, `STATUS.md` and
`docs/CODEX_MAP.md` (one line each). `docs/CODE_MAP.md` is generated from module docstrings and needs no entry (no new
module). Roadmap, architecture and `AGENTS.md`: unchanged.
