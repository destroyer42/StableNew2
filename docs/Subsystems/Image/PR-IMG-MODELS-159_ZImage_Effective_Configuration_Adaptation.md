# PR-IMG-MODELS-159 - Z-Image effective configuration adaptation

## Execution Profile + Model/Reasoning Recommendation

Standard, cross-layer compiler/GUI repair inside existing architecture. Codex: GPT-6.1 Sol
High. Claude Code: Sonnet 5.5 High. Preferred host: Local/Desktop (Tk preview fixtures and
the exact-profile compile path). Stop conditions (loosening backend safety invariants,
changing frozen NJR semantics, widening the support envelope) did not occur.

## Controller Surface Assessment

No controller or coordinator change. The compile stays in the PromptPack builder and the
generic NJR builder; the GUI change is presentation only (one preview label, one control
projection entry).

## Reproduction on unchanged source (origin/main `c5d8a8c3`)

Production PromptPack builder, exact Z-Image profile, frozen run-level policy overlay:

| Stored/inherited state | Result before |
|---|---|
| global positive text, enabled | `global_positive_prompt is unsupported; apply_global_positive_txt2img True conflicts` |
| global positive text, **disabled** | `global_positive_prompt is unsupported` (the stored text alone refused) |
| prompt optimizer enabled (legacy pack) | `prompt_optimizer is unsupported` |
| `clip_skip` 2 | `clip_skip 2 conflicts with fixed 1` |
| inherited SDXL sampler/scheduler/steps/CFG | each conflicts with the fixed profile value |
| global negative enabled/disabled | accepted (already cleared before the validator) |

Cause: `apply_model_compile_policy()` ran on the inherited configuration, so the strict
validator rejected values the profile itself owns before shared adaptation could account for
them. In the generic (non-PromptPack) builder the same refusal was swallowed by the preview
path and surfaced as an empty preview.

## Behavior

### Effective configuration (executable config only)

The source configuration, the saved PromptPack and the structured intent are never edited;
the executable copy is normalized through the one profile projection
(`model_policy.normalize_profile_owned_values` -> `forge_zimage_profile.project_shared_baseline`,
the same projection PR-158 uses for Model Comparison arms) **before** the unchanged compile
policy and validator run. It replaces only inherited values the profile owns: sampler/scheduler/
steps/CFG/shift, CLIP skip, VAE, prompt optimizer and the global prompt terms and flags.
Geometry, image/batch counts, seed policy, stages, assets, backend and every optional feature are
untouched, so `validate_zimage_config`/`validate_zimage_njr` and the backend still refuse a
genuine conflict (576x1024, ADetailer/upscale/img2img, `images_per_prompt` > 1, `enable_hr`,
unresolved `<lora:...>`/weighted syntax in the final prompt).

### Global positive

For an exact Z-Image selection the executor cannot apply global positive terms, so the compiler
composes them: the stored terms (read exactly as the executor would - frozen config, or the
legacy config-manager value when the policy is unfrozen) are passed through the shared
`adapt_structured_prompt` prose rules together with the PromptPack positive (one summed
operation per rule), then prepended with the executor's own `merge_global_positive`
(`"terms, prompt"`) by `resolution_layer.compose_global_positive`. The executable configuration
carries `global_positive_prompt == ""` and `apply_global_positive_txt2img == False`, so neither
the executor nor the backend can apply them again. Disabled terms are ignored and recorded as
`global_positive_not_applied`.
`PackPromptIntent`'s frozen serialization is unchanged: the composed contribution travels beside
the intent (`AdaptedPackIntent.global_positive`) and is rendered into the NJR's positive prompt.

### Evidence (content-free)

`NJRProvenance.metadata['prompt_adaptation']` (contract `prompt_adaptation/1`, ruleset
`159.1`) gains `global_positive_composed`, `global_positive_not_applied` and
`profile_value_normalized {setting, from, to}` (sampling/CLIP-skip values and prompt-channel
`{setting, cleared: true}` - never prompt text). Existing codes (`negative_prompt_dropped_unsupported`,
`global_negative_not_applied`, `optimizer_not_applied`, flatten/BREAK/LoRA/embedding) are unchanged.
Replay uses the frozen NJR; nothing is adapted again.

### Generic (non-PromptPack) builder

`JobBuilderV2` applies the same normalization and global-positive composition for an exact
Z-Image selection (`src/pipeline/exact_profile_effective_config.py`), recording
`effective_configuration/1` provenance (owner-approved: inherited profile-owned sampling is
normalized and an unsupported manual negative prompt is omitted, both disclosed). The global
terms are adapted with the shared prose rules, and the adapter's own operations
(`weighted_attention_flattened`, `break_separator_normalized`, counts only) are recorded in the
same `{code, scope, effect, details}` vocabulary, so the NJR and Preview can say the terms were
rewritten. `global_negative` is recorded as `omitted` only when stored global negative terms
would have applied; a stored-but-disabled global negative makes no claim. It is a no-op after
the PromptPack builder.

### Where the behavior applies (not universal)

| Workflow | Global positive | Inherited profile-owned values | Prompt text |
|---|---|---|---|
| PromptPack builder (Preview/Run Now/Send Job) | composed once | normalized with evidence | prose adapted |
| Generic Pipeline builder | composed once (terms adapted) | normalized with evidence | manual prompt validated, **not** adapted |
| Model Comparison arms | **omitted** (deferred to PR-IMG-MODELS-160) | normalized (PR-158) | prose adapted |
| CLI builder (`cli_njr_builder`) | strict, unchanged | strict, unchanged | validated |

Manual prompts stay strict: weighted or adapter syntax in a manual prompt is refused, whereas
PromptPack prose is flattened and the generic path flattens only the global terms.

### Preview and controls

The Preview shows the NJR's final positive/negative channels and effective sampler/steps/CFG,
plus a compact one-line, content-free notice from the manifest
(`src/gui_v2/adaptation_notice.py`, `PreviewPanelV2.adaptation_label`). The Z-Image projection
no longer locks the global positive toggle (it is safely composed); the global negative toggle
and negative editor stay locked, and the policy note states the adaptations. Stored values are
never rewritten and restore on model switch; PR-GUI-112 draft recovery is untouched.

### Unchanged

SDXL keeps executor-owned global terms, optimizer and sampling; Klein keeps its own compile
policy (no composition, no new evidence). Model Comparison reuses the same projection and
adaptation; its arms do not compose a global positive (the shared baseline's term stays
replaced, as in PR-158).

## Token-Efficient Validation Plan

Failing-before reproduction first; then `tests/pipeline/test_zimage_effective_config_159.py`
(23), `tests/pipeline/test_exact_profile_effective_config_159.py` (10),
`tests/gui_v2/test_zimage_effective_config_159_gui.py` (5) and
`tests/integration/test_pr_img_159_zimage_effective_config.py` (5, real compiler, JobService,
SQLite queue/runner, executor and fake Forge transport); then affected pipeline/adaptation/
policy/Learning/GUI/integration suites, Ruff, mypy smoke and `run_pr_gate.py` once. Reuse
unchanged PR-155/157/158 evidence. No physical model launch or generation.

## Validation evidence (local)

- New tests: 43 pass (23 + 10 + 5 + 5). The final repair pass added regression coverage for the
  disabled-global-negative notice and for weighted/BREAK evidence on the generic path; mutation
  checks confirmed each fails if its fix is reverted. A mutation check confirmed the checkpoint-key selection
  test fails if the Z-Image selection branch is removed.
- Affected suites (pipeline, image_backends, learning_v2/learning, gui_v2, controller, review,
  promptpacks, integration, system, operator-journey GUI): 4,815 passed, 1 skipped, 34 failed.
  All 34 are environment failures: 33 fail identically on an unchanged `origin/main` worktree
  (runtime-transition errors because a real Forge instance occupies the WebUI endpoint on this
  machine), and the 34th (`test_njr_queue_runner_transport`) passes alone on both trees. After
  the independent review's fixes, the affected Z-Image/preview/prompt/builder/comparison subset
  was rerun: 2,045 passed.
- One independent read-only review found no blocking defect; its low-severity items were fixed
  (weighted global terms now follow the shared prose rules on the generic path; the notice reads
  generic-path evidence and no longer lists cleared channels as "profile values set"; Z-Image is
  selected by every recognized checkpoint key; direct generic-path tests added).

## Remaining limitations

- **PR-IMG-MODELS-160 (deferred, bounded follow-up):** Z-Image Model Comparison arms still
  replace a shared global positive term without composing it or recording an operation
  (unchanged from PR-158). Parity changes frozen-arm prompt evidence and is not part of PR-159.
  The sidebar global positive toggle is now operable for Z-Image, so the gap is more visible.
- The generic builder clears (rather than refuses) a manual negative prompt and collapses
  inherited sampling variants for an exact Z-Image selection (owner-approved); the evidence is in
  `effective_configuration/1` and the Preview notice. Exact backend validation and Learning
  controlled-variable requirements are unchanged.
- An unfrozen generic configuration composes no global positive (the executor would have read
  mutable state); controllers always freeze it.
- `cli_njr_builder` remains strict, so three compile surfaces differ in strictness (see table).

- Several pre-existing runner/executor tests fail on this machine on unchanged `origin/main`
  because a real Forge instance occupies the configured WebUI endpoint; they are unrelated.
- Model Comparison Z-Image arms still drop (not compose) a shared positive term; adding
  composition there needs its own frozen-arm evidence decision.
- Manual (non-PromptPack) prompts are validated, not adapted, as before.
