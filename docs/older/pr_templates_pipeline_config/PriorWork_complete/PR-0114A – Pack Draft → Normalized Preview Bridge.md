PR-0114A – Pack Draft → Normalized Preview Bridge.md
Intent

Bridge the pack draft path (Add to Job) into the normalized preview pipeline, so that:

Adding packs from the sidebar populates AppStateV2.job_draft and enough metadata for the preview to render a real job summary (prompt, stages, randomizer).

PipelineTabFrameV2._refresh_preview_from_pipeline_jobs() can return a NormalizedJobRecord representing the current draft(s), so PreviewPanelV2.set_jobs() shows a real job summary instead of “No job selected.”

Risk Tier: Tier 2 (controller + GUI + job builder; no queue/executor changes yet).

Subsystems / Files

Controller / Pipeline

src/controller/app_controller.py

on_pipeline_add_packs_to_job

_run_config_with_lora

Any helper needed to access pipeline_controller / state manager.

src/controller/pipeline_controller.py

_build_normalized_jobs_from_state

Any helper we add for “build normalized jobs for a pack selection.”

GUI State + Preview

src/gui/app_state_v2.py

PackJobEntry

JobDraft

AppStateV2.add_packs_to_job_draft

src/gui/views/pipeline_tab_frame_v2.py

_on_job_draft_changed

_get_pipeline_preview_jobs

src/gui/preview_panel_v2.py

set_jobs

update_from_job_draft

_update_action_states

Prompt pack helpers

src/utils/prompt_packs.py (for building run-configs from packs, if needed)

src/pipeline/job_builder_v2.py

src/pipeline/job_models_v2.py

NormalizedJobRecord

JobUiSummary / to_ui_summary helpers

Tests

tests/gui_v2/test_pipeline_pack_selector_job_actions_v2.py

tests/controller/test_app_controller_add_to_queue_v2.py (may get helper coverage)

New tests:

tests/controller/test_pack_draft_to_normalized_preview_v2.py

Key Changes

Enrich PackJobEntry payload

Extend PackJobEntry in src/gui/app_state_v2.py:

Currently: pack_id, pack_name, config_snapshot.

Add fields so the preview can render a proper JobUiSummary:

prompt_text: str (representative text / joined prompts from pack)

negative_prompt_text: str | None

stage_flags: dict[str, bool] (e.g., {"txt2img": True, "img2img": False, "upscale": False, "adetailer": False})

randomizer_metadata: dict[str, Any] | None (seed mode, max variants, etc., if applicable)

JobDraft stays packs: list[PackJobEntry], but now each entry carries the metadata Codex said was missing.

Populate richer PackJobEntry in on_pipeline_add_packs_to_job

In AppController.on_pipeline_add_packs_to_job:

After pack = self._find_pack_by_id(pack_id):

Pull pack data (from whatever structure PromptPackInfo or the pack loader uses).

Build a pack-specific RunConfig or metadata via a helper. Avoid copying full pipeline logic here; instead:

Use something like build_run_config_from_prompt_pack or a small helper in prompt_packs.py to get prompts + keys.

Or at least:

prompt_text ← first/primary prompt in pack.

negative_prompt_text ← any default negative prompt if present.

stage_flags ← derived from enabled stages in the GUI state (txt2img/img2img/upscale/adetailer).

randomizer_metadata ← from state manager’s randomizer metadata helper if available (_extract_metadata("randomizer_metadata") in PipelineController is already a pattern).

Build PackJobEntry with those fields + config_snapshot=_run_config_with_lora().

Continue to call self.app_state.add_packs_to_job_draft(entries) as today.

Let preview fall back to draft metadata when normalized jobs cannot be built

PipelineTabFrameV2._on_job_draft_changed currently:

job_draft = self.app_state.job_draft
if not self._refresh_preview_from_pipeline_jobs():
    self.preview_panel.update_from_job_draft(job_draft)


That’s already correct; we just need update_from_job_draft to understand the richer PackJobEntry.

In PreviewPanelV2.update_from_job_draft:

When job_draft.packs is non-empty:

Build a minimal JobUiSummary from the first PackJobEntry:

prompt_short ← entry.prompt_text[:N]

negative_prompt_short ← entry.negative_prompt_text[:N]

model, sampler, steps, cfg_scale, etc. from config_snapshot.

stage_flags from entry.stage_flags.

randomizer_summary from entry.randomizer_metadata.

Call _render_summary(summary, total=len(packs)).

Ensure _update_action_states(job_draft) is called so “Add to Queue” enables.

This gives you a “real job” preview even before we wire draft → normalized jobs.

(Optional but recommended) Make PipelineController._build_normalized_jobs_from_state aware of pack drafts

Inside _build_normalized_jobs_from_state in PipelineController:

Inspect AppStateV2.job_draft (through whatever state manager hook exists).

If job_draft.packs is non-empty:

Build one NormalizedJobRecord per PackJobEntry, using JobBuilderV2 and the same metadata we just added.

Return that list of records for preview and queue submission.

Otherwise, fall back to current behavior (manual prompt / randomizer path).

This step is what ultimately lets the preview panel’s “normalized path” work. If it’s too big for A, you can move it to PR-0114B, but I’d keep at least the preview aspect in A.

Tests

New tests/controller/test_pack_draft_to_normalized_preview_v2.py:

Build an AppStateV2 with a JobDraft containing one PackJobEntry.

Wire a PipelineTabFrameV2 with a fake PipelineController that returns a NormalizedJobRecord (or, in the fallback path, rely on update_from_job_draft).

Assert:

Preview label shows Job: 1 / Job Draft: ….

Prompt text widget gets a non-empty prompt.

Stage flags label reflects stage_flags.

Update tests/gui_v2/test_pipeline_pack_selector_job_actions_v2.py:

Extend to assert that after clicking “Add to Job,” AppStateV2.job_draft.packs[0] includes prompt_text, stage_flags, etc.

Docs / Changelog

Docs

docs/ARCHITECTURE_v2.5.md: add a short subsection under GUI → Controller → Pipeline describing the “Pack Draft → Preview” flow and the role of PackJobEntry.

docs/Randomizer_Spec_v2.5.md (if pack/randomizer metadata is cross-referenced): add note that pack drafts carry randomizer_metadata.

CHANGELOG.md

New entry for PR-0114A (date, summary: “Pack drafts now carry prompt/stage/randomizer metadata and feed the preview panel”).