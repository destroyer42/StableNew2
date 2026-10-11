# PR-IMG-MODELS-158 - Cross-workflow model compatibility and preflight

## Execution Profile + Model/Reasoning Recommendation

Standard, substantial cross-surface compatibility repair (no new runtime authority, no
new model capability or qualification). Codex: GPT-6.1 Sol High. Claude Code: Sonnet 5.5
High. Preferred host: Local/Desktop (Windows/Tk fixtures and exact-profile source
continuity). Stop conditions were architecture-ownership ambiguity or a new model
capability/qualification decision; neither occurred.

## Controller Surface Assessment

`AppController._submit_reprocess_njrs` now delegates to
`src/controller/reprocess_admission.py` (one function, no queue/runner/backend logic).
`app_controller.py` shrank by four physical lines and its ratchet ceiling was lowered
(7678 -> 7674). No other controller, coordinator, process manager, SQLite schema, NJR
identity, queue, runner or replay change.

## Reproduced failure boundaries (before any edit)

Reproduced with the production builders, no GPU/Forge/network:

| Finding | Result |
|---|---|
| A. Z-Image + SDXL Model Comparison from a shared 1024x1024 baseline with ordinary SDXL sampling, enabled optimizer and global-negative intent | **Confirmed.** The Z-Image arm failed inside `apply_zimage_compile_policy` because the SDXL baseline's sampler/scheduler/steps/CFG, optimizer and global-negative flag were copied into the arm as if they were requirements. SDXL+Klein built fine (Klein's compile policy normalizes them). |
| B. Review/reprocess of a Z-Image-sourced artifact with img2img / ADetailer / upscale / a 3-image batch | **Confirmed.** `ReprocessJobBuilder` built the NJR and `JobService` validation accepted it; only `ForgeWebUIImageBackend.validate_njr_intent` refused, at dispatch, after queue admission. An explicit Klein edit already validated before queueing. |
| C. PromptPack structural validity vs target compilation (Z-Image at 576x1024) | **Confirmed**, and worse: the editor's Validate read `matrix_config`, a key native documents do not contain, so it checked nothing, read the selected file on disk rather than the editor's unsaved state, and printed "Pack ... is valid!". The compiler rejected the same pack ("width 576 conflicts with fixed 1024"). |
| D. Ordinary Z-Image Learning exposes unsupported controls | **Disproved - not a defect.** The projection offers no variables (steps/CFG/sampler/scheduler/VAE `fixed`, LoRA `lora_unsupported`, Model `model_policy_comparison_unavailable`) and img2img/ADetailer/upscale are unsupported stages. Only regression tests were added. |

## Behavior

### Shared read-only assessment

`src/image_backends/operation_compatibility.py` projects the canonical `ModelPolicy`
(and therefore the immutable exact profile) onto one requested operation: backend, stage
chain, explicit single-reference edit, source-image count and geometry. It owns no model
table or default, performs no I/O, never rewrites a request and never narrows a target
without an exact profile (ordinary SDXL, unverified and unknown models are unchanged).
Backend validation (`validate_njr_intent`, `validate_profile_intent`, `validate_zimage_njr`)
remains the independent final authority; conformance tests assert both agree.

### Review/reprocess preflight

`submit_reprocess_njrs` assesses the whole built NJR batch first, then crosses
`JobService.submit_njrs` once. Every reprocess-NJR submitter shares it: the Review tab, the
Reprocess panel, mask edits, photo-optimize and staged-curation advancement
(`LearningController.submit_staged_curation_advancement`). One unsupported item refuses the entire request with an
explanation before queue admission; nothing is queued, omitted, rerouted or rewritten.
Z-Image v1 refuses img2img, ADetailer, upscale and multi-image reprocess. Klein's
explicit single-reference edit (frozen `klein_single_reference_edit` metadata, exactly one
image, source digest) keeps its existing admission; a Klein img2img that was *not*
explicitly requested is now refused before queueing with that reason (previously the
backend refused the already-queued job). The model is the artifact's own recorded
checkpoint; no replacement is inferred from the GUI or the image.

The Review effective-settings summary shows the same projection as a `Readiness:` line
(`ReprocessEffectiveSettingsPreview.effective_model`,
`ReviewWorkflowAdapter.assess_readiness`). With the explicit Klein edit toggle it assesses the
qualified Klein profile, because submission freezes that checkpoint over the artifact's own
model, so a Z-Image or SDXL artifact is not shown a false "not ready".

### Model Comparison

Each arm is prepared independently from the shared baseline:
`prepare_candidate_baseline` (dispatching to the profile's `project_shared_baseline`)
replaces only values the exact profile itself owns - sampling, VAE, `clip_skip`,
prompt optimizer, global prompt terms - and then the unchanged compile policy runs.
Geometry, sample count, seed/subseed policy, stages, ControlNet, refiner, hires and every
other requested feature are never altered, so a genuine conflict fails the **whole**
study with an arm-labelled, actionable message and no snapshot. Preview now dry-runs every
arm through the exact Run materialization boundary
(`verify_arms_admissible`, including `validate_profile_njr`), so refusal happens at
Preview and never mid-admission. Source digests, adaptation manifests, effective prompts,
seed policy, the noncausal interpretation and tamper detection are unchanged. Because a
Z-Image job is exactly one image, a shared sample count above one (or a subseed strength
above zero) is a genuine incompatibility, not something to normalize.

### PromptPack editor readiness

Validate now evaluates the editor's **in-memory** pack when it is the selected/open pack
(unsaved edits are what is checked; any other pack is read from its saved file) and reports
structure and target readiness separately (`src/prompting/pack_target_readiness.py`):
real Matrix structure checks, then, for the selected target, backend, the pack's saved
geometry (`preset_data`), unresolved inline tokens (the profile's own prompt validator over
the adapted text, per Matrix value) and the adaptations the compiler will apply. It labels
what it evaluated ("unsaved editor state" / "saved pack file"), never says "ready", never
mutates, adapts or saves the pack, and leaves model switching reversible.

**Smaller achieved scope (reported rather than expanded):** an exact compile preview of
unsaved state would have to rebuild the controller-owned configuration snapshot
(Pipeline-tab stages, "Override pack configs", stage-card values). That is a second compile
authority/major refactor, so execution readiness remains Preview's/the compiler's answer
and the dialog says so.

### Ordinary Learning

No production change. Tests lock that Z-Image exposes no adjustable controls, that
custom/current prompts are refused for fixed controls without translation, and that a
model switch after Preview never rewrites the frozen experiment or the executed NJR.

## Token-Efficient Validation Plan

Focused first: `tests/image_backends/test_operation_compatibility_158.py`,
`tests/controller/test_review_exact_profile_preflight_158.py`,
`tests/learning_v2/test_model_comparison_compat_158.py`,
`tests/learning_v2/test_ordinary_learning_zimage_158.py`,
`tests/gui_v2/test_pack_editor_readiness_158.py`; then the affected
learning/image_backends/pipeline/controller/integration/system/gui suites, Ruff, mypy on
the new modules and `run_pr_gate.py` once. Mutation checks confirmed that removing the
per-arm projection, the arm dry-run or the admission preflight fails the new tests.

## Validation evidence (local, source SHA recorded in the commit)

- Focused: 80 new/updated tests across `test_operation_compatibility_158`,
  `test_review_exact_profile_preflight_158`, `test_curation_exact_profile_preflight_158`,
  `test_model_comparison_compat_158`, `test_ordinary_learning_zimage_158` and
  `test_pack_editor_readiness_158` pass. Mutation checks: removing the per-arm projection, the
  arm dry-run, or the admission preflight fails the new tests.
- Affected suites (`tests/learning_v2`, `learning`, `image_backends`, `pipeline`, `controller`,
  `review`, `promptpacks`, `integration`, `system`, `gui_v2`, operator-journey GUI): 4,785 passed,
  1 skipped, 2 failed. Both failures are thread-shutdown timing tests
  (`test_clean_shutdown::test_shutdown_with_exception_in_thread`,
  `test_pr_mvp_060_phase3a_r1_queue::test_queue_panel_manual_and_auto_run_worker_lifecycle`) that
  pass when run alone on the same tree and touch no changed module; they are load-sensitive
  and not attributed to this change. After the independent review's fixes, the affected
  review/curation/prompt/learning/Klein/Z-Image subset was rerun: 966 passed.
- One independent read-only aggregate review found three real issues, all fixed with tests:
  Klein-edit readiness assessed the artifact's model rather than Klein; staged-curation
  advancement bypassed the preflight; one assertion could not fail.

## Remaining limitations

- Photo-optimize creates its staging directory while building NJRs, so a refused request can
  leave an empty directory (nothing is queued).
- A shared positive global term replaced for an exact-profile arm is visible in
  `executor_global_prompt_policy` but has no dedicated adaptation operation code (as for Klein).

- No physical generation was run; Z-Image v1 remains 1024x1024 one-image txt2img with
  unresolved clean-shutdown/repeated-run evidence (PR-IMG-MODELS-154B/155).
- Editor readiness is deliberately not an execution-readiness claim (see above).
- Klein NJR-level validation still needs live backend evidence and stays at dispatch.
