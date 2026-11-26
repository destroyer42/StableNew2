# N1b: SDXL target evidence (warn for an unclassified checkpoint; observed runs outrank the registry)

Follow-up to `N1_warn_dont_block.md` ("Not done (follow-up N1b)").

## Outcome

Owner rule (2026-11-25): "Experimental evidence should trump anecdotal or registry evidence. If it works, it works."

The SDXL-only features used to refuse any checkpoint the asset registry had not classified as SDXL from its header
("registry-verified SDXL"). They now use one verdict, `src/image_backends/sdxl_target.py`, per (checkpoint, operation,
backend):

| Evidence | Verdict | Policy evidence |
| --- | --- | --- |
| Completed queue job here, same checkpoint, operation and backend | verified, no warning, "ran N times here" | `observed_execution` |
| Registry header says SDXL base | verified (as before) | `registry_evidence` |
| No record, unclassified or conflicting header, name hint only, refiner or inpaint variant | `PolicyWarning` (why and fix), runs as SDXL | `accepted_unverified` |
| Header positively says another family | real block with a fix; a warning (why and fix) when the file has observed runs (Q1) | `accepted_unverified` |
| Exact qualified profile (Klein, Z-Image, Qwen, FLUX.1, Ideogram) | real block, never outranked | unchanged |

Backend facts stay blocks: ControlNet and Review mask edits run on Forge only, and Embedding experiments stay verified
for Forge only.

Features covered:

- Learning Embedding, LoRA Composition, Prompt Slot, Two-Axis Grid, Model Comparison and Prompt x Model Matrix, and
  the study-eligibility projection.
- PromptPack ControlNet units and legacy OpenPose, including their compile, pack readiness, editor guidance and dispatch.
- The Review mask editor and outpaint, including preparation, admission and dispatch.
- Guided ADetailer and img2img.

Warnings travel as data:

- A Learning snapshot freezes them under `policy_warnings`.
- A compiled or prepared NJR carries them under `provenance.metadata.policy_warnings`.
- Queue (the desktop queue service, `submit_reprocess_njrs`, Learning variant materialization) records them in
  `provenance.metadata.accepted_warnings`.
- `PolicyWarning.as_dict()` and `SdxlTarget.as_dict()` are the surface-neutral records RG-140 (control S12) reads.
- Dispatch never refuses an unclassified family.

Observed execution (`src/history/observed_execution.py`):

- It is read-only, bounded and never on the calling thread. It keeps a per-checkpoint cache and schedules one background
  read of completed jobs on the repository's read-only connection: newest first, at most 20,000 rows and 200 matches,
  with a 5-minute freshness window. Until that read finishes it answers 0.
- A checkpoint is matched by name. Where a job recorded a SHA-256 and the registry knows the current file's, the two must
  match. Only Model Comparison and Matrix arms record one.
- It decides eligibility only. It never feeds `RecommendationEngine`, proposals or publication (Learning invariant 5).

## Owner decisions (2026-11-26)

Rob answered in chat, relayed word for word by session `local_3c210c34-814e-484a-99f8-98a9bc18072b`:

- **Q1, "Warn, then run".** This supersedes Rob's first answer ("Yes, runs win") after the refinement that a completed
  job does not prove the family (Forge finishes a job and skips a LoRA or embedding that does not match):
  - observed completed runs of the same operation fully outrank unclassified registry evidence (no warning, "ran N times
    here");
  - when the header positively names another family but this file has completed the same operation here, the block
    becomes a warning (why and fix) that Queue records in provenance;
  - exact qualified profiles (Klein, Z-Image, Qwen, FLUX.1) keep their limits.

  The rule is the code constant `OBSERVED_VS_REGISTRY_FAMILY = "warn"`, not an operator setting.
- **Q2, "By what the job does".** The same operation means the same capability level: txt2img, txt2img with embeddings,
  LoRAs or ControlNet (per modality), img2img, masked inpaint, outpaint or ADetailer. It does not mean the same study kind.
- **Q3, "Yes, allow it".** A study run on a warned model may be continued or pooled with a registry-verified study of the
  same model, and the accepted warning stays visible on the record (`compatible_context`).
- **Default kept.** Observed runs decide eligibility only and never feed `RecommendationEngine`.

## Not done

These gates still require registry SDXL. Each is listed for a follow-up:

- the phone steps follow-up (`src/app/site_phone_followup.py`);
- Learning evidence proposals (`src/learning/evidence_proposals.py`);
- the LoRA browser and the prompt optimizer view (`src/gui_v2/lora_browser.py`, `src/gui_v2/prompt_optimizer_view.py`);
- the Comfy SDXL profile (`src/image_backends/comfy_sdxl_profile.py`);
- generation-profile identity (`src/generation_profiles/identity.py`);
- a LoRA Strength axis on an unclassified model, refused by the controlled-variable LoRA rule;
- the Learning design panel's readiness line, which does not show the warning (Preview does).

A ControlNet weight whose SDXL structure is unverified is still a block. That check is about ControlNet weights, not the
checkpoint.

## Execution class and model recommendation

- Execution class: Standard. It applies the owner-approved N1 rule to more gates; no `AGENTS.md` change.
- Execution location: Local.
- Model recommendation: Claude Code Opus 5.5 High; Codex GPT-6 Astra High.

## Exact start state and authorities

- Task start: 2026-11-26T05:59:25-05:00. Session `claude:31314bb9-ceb8-4d6c-9db7-7c18baa8457b` plus one read-only
  Explore subagent. Started by session `local_3c210c34-814e-484a-99f8-98a9bc18072b` (N1).
- Branch `feature/n1b-observed-evidence`, cut from `claude/ecstatic-turing-1267bc` at 4d4057c0 (N1, PR #436, not yet
  merged). Rebase onto `main` after #436 merges.

## Surface assessment

- Controller surface touched: Yes. The queue submission service accepts pending warnings (+5). `reprocess_admission`,
  `masked_edit_service`, `outpaint_edit_service` and `review_batch_service` changed by a few lines each. None of the
  ratcheted controllers changed.
- No second queue, runner, compiler or history authority. Observed evidence is a read-only projection of the existing
  `JobRepository`.
