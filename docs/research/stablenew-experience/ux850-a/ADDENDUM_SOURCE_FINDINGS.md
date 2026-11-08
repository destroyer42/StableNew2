# UX-850-A addendum — five additional source findings

**Status:** read-only research addendum to the merged [UX-850-A package](README.md). It adds findings; it changes no classification, decision, `STATUS.md` or source, and implements nothing. Nothing here is a qualification verdict or a safety clearance.

**Evidence cut:** application source at `d05d4a2d769d7076c902b3b3a63d626fea192112` (`main` after PR #265). `src/` is unchanged from the UX-850-A evidence cut `3399f8032182b65bd904f8f27818d927909cd6a3`, so every anchor below was re-read at this commit.

**Provenance:** found by independent read-only tracer sessions (Claude Code, `claude:b8f909b4-f50d-4268-bbeb-dac19ed77799`) that were running when UX-850-A was completed elsewhere. Each finding was then re-verified by direct source reading at the cut above. The tracers' decision-level classification differences are not asserted here because those are judgment calls against the merged matrix; only source-verified facts are listed.

Findings are static-source facts. Whether each produces an operator-visible failure at runtime was not exercised (no GUI, no generation).

## Findings

### A-1 — Smart Review opens the mask editor without History lineage

- **Fact:** `_default_open_editor` constructs `MaskEditorDialog(self._master, source_path=…, controller=…, suggested_mask=…, suggested_source_sha256=…)` and passes no `lineage` ([smart_review_dialog.py:531-540](../../../../src/gui/smart_review_dialog.py)). The dialog accepts an optional `lineage` argument ([mask_editor_dialog.py:41](../../../../src/gui/mask_editor_dialog.py)) and derives its History baseline from it (`bind_history_lineage`, line 180).
- **Why it matters:** an AI-suggested mask opened through Smart Review from a History image starts with no recorded parent, unlike the direct mask-editor route that supplies one. Bears on UX-DEC-003 (parent/child comparison) and the AI-assist provenance expectations.
- **Not established:** whether the controller backfills lineage later; not traced.

### A-2 — Prompt-tab Load replaces unsaved pack edits without a dirty check

- **Fact:** the `workspace_state.dirty` guard runs in the New-pack path ([prompt_tab_frame_v2.py:1225](../../../../src/gui/views/prompt_tab_frame_v2.py)). `_on_load_selected_pack` ([:1787](../../../../src/gui/views/prompt_tab_frame_v2.py)) calls `workspace_state.load_pack(...)` directly, and `load_pack` resets `dirty` to `False` ([prompt_workspace_state.py:38-41](../../../../src/gui/prompt_workspace_state.py)). `MainWindow._on_close` ([main_window_v2.py:1418](../../../../src/gui/main_window_v2.py)) contains no dirty, save or confirmation check.
- **Why it matters:** selecting another pack (or double-clicking one, [:336](../../../../src/gui/views/prompt_tab_frame_v2.py)) silently discards unsaved edits to the working pack. Directly relevant to UX-DEC-008 (draft/working-copy protection).
- **Not established:** whether other pack-switch paths or autosave elsewhere mitigate this.

### A-3 — Evidence catalog import silently overwrites records with a matching ID

- **Fact:** the import merge is `{r.record_id: r for r in (*self.catalog.records, *imported.records)}` ([model_evidence_window.py:881](../../../../src/gui/views/model_evidence_window.py)); the imported record wins on a `record_id` collision, with no conflict report or confirmation. The surrounding code preserves the previous revision only on cancellation.
- **Why it matters:** an imported catalog can replace an existing reviewed claim with a different one under the same ID without the operator being told, which weakens traceability of advisory evidence (UX-DEC-071 evidence-integrity expectations).
- **Not established:** whether `EvidenceCatalog.load` or `select_operator_catalog` rejects duplicate or divergent IDs elsewhere; not traced.

### A-4 — Profile publication pools ratings across experiments with equal weight

- **Fact:** samples are grouped by `(experiment, setting)` ([profile_publication.py:384](../../../../src/learning/profile_publication.py)); snapshot, seed, variant-count and rating-count checks run per experiment. Cohorts that pass are then merged by setting only (`qualified[setting].extend(cohort)`, [:402](../../../../src/learning/profile_publication.py)) and winners are chosen by mean rating over the pooled samples (comment at [:408-411](../../../../src/learning/profile_publication.py)), each rating counted equally.
- **Why it matters:** comparability is enforced within an experiment but not across experiments for the same setting, and a large experiment dominates a smaller one in the pooled mean. This feeds a consequential publication decision (UX-DEC-071 requirements 1 and 4: comparable cohorts, no overstated confidence).
- **Not established:** how often multiple qualifying experiments for one setting occur in practice, or whether downstream confidence compensates.

### A-5 — `STATUS.md:51` reads as if original pixels are restored for mask editing too

- **Fact:** `STATUS.md:51` states "original pixels restored at artifact finalization" for "Review mask editing and canvas extension (outpainting)". The executor restores protected original pixels only when `frozen_outpaint` is set (`preserve_original`, [executor.py:5710-5723](../../../../src/pipeline/executor.py)); there is no equivalent restoration call for the masked-edit path. The masked-edit path uses the frozen edit input and mask (`frozen_edit`, [:5552-5556](../../../../src/pipeline/executor.py), [:5631](../../../../src/pipeline/executor.py)).
- **Why it matters:** the sentence can be read as a guarantee for both features. The merged matrix already notes the distinction at decision 013; the canonical status line itself is unchanged.
- **Not established:** whether the backend inpainting path preserves unmasked pixels (backend behavior, not app-side restoration); not exercised. `STATUS.md` is not edited by this addendum; whether the wording should change is an owner/maintainer call.

## Handling

These are inputs for the downstream lanes and for any owner triage. None is classified as a defect to repair here, none authorizes a repair, and none changes a decision status in [DECISION_TRACEABILITY.md](DECISION_TRACEABILITY.md).
