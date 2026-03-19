# Prompt pack field coverage vs. V2 pipeline controls

Prompt pack JSON files live under `packs/*.json` (for example `packs/heroes.json`). They bundle legacy txt2img/img2img/upscale/adetailer parameters plus auxiliary sections such as `pipeline`, `randomization`, `video`, `api`, and `aesthetic`. The V2 pipeline UI only exposes a subset directly via the new stage cards, so this note tracks what is still unmatched and whether it should be integrated.

## Stage-level gaps

### txt2img

Current V2 controls surface `model`, `vae`, `sampler`, `scheduler`, `steps`, `CFG scale`, `width`, `height`, `clip skip`, and `seed`. The legacy pack also records:

- `negative_prompt` – V2 currently stores the primary prompt via the sidebar prompt entry; a dedicated negative prompt control would be needed to respect this field automatically.
- `seed_resize_from_h/seed_resize_from_w`, `enable_hr`, `hr_*`, `denoising_strength`, `hypernetwork`, `styles`, `refiner_*` – these high-resolution, refinement, and style knobs have no UI yet and likely belong in future advanced mode dialogs (or a “HiRes/refiner” panel).

Recommendation: Continue treating these as future additions; ensure the run/preset payload carries the values so they can be surfaced later.

### img2img

Stage card supports `model`, `vae`, `sampler`, `steps`, `CFG`, `denoise`, `width`, `height`, `mask mode`, plus a seed field via `SeedSection`. Packs introduce `clip_skip`, `prompt_adjust`, `negative_adjust`, `scheduler`, and the underlying `seed`/`hypernetwork` fields.

Recommendation: The missing controls align with “advanced img2img tooling” and should be fulfilled by the same future story that brings HiRes/LoRA-style knobs back into the UI.

### upscale

Current UI provides `upscaler`, `mode`, `steps`, `denoise`, `scale`, `tile size`, and `face restore`. Packs also set `sampler_name`, `scheduler`, `gfpgan_visibility`, `codeformer_visibility`, `codeformer_weight`, plus `upscale_mode`/`upscaling_resize`.

Recommendation: The sampler/scheduler combo could be captured when we wire up WebUI resource lists; the restoration/face-restore fields (gfpgan/codeformer) should be surfaced once the Upscale stage is expanded with those checkboxes.

### adetailer

The new ADetailer card only exposes model, detector, confidence, mask blur, merge mode, and face/hand toggles. Pack configs carry a richer set (`adetailer_enabled`, `adetailer_scheduler`, `adetailer_steps`, `adetailer_denoise`, `adetailer_cfg`, `adetailer_prompt`, `adetailer_negative_prompt`, etc.).

Recommendation: When enhancing the ADetailer card (PR-034 follow-ups) add mappings for the scheduler/step/CFG fields and negative prompt so prompt pack load/save remains lossless.

## Pipeline/randomization/support sections

- `pipeline` section: we now honor `*_enabled` flags + adetailer toggles. Fields such as `allow_hr_with_stages`, `refiner_compare_mode`, and the per-stage `apply_global_negative_*` switches are not yet surfaced; consider centralizing them under the pipeline configuration card if/when that card grows.
- `randomization` / `randomization_enabled` / `max_variants`: the PipelineConfigPanelV2 already has placeholders for randomizer state (see `_apply_randomizer_from_config`), but pack files still store wildcard/matrix rules that aren't rendered today. These belong to the planned randomizer UI in the pipeline config card.
- `video`: no video encoder UI exists in V2 yet; keep this as legacy metadata.
- `api`: base URL/timeout belong in engine settings (already managed elsewhere, so no action needed).
- `aesthetic`: these advanced learning/innate aesthetic controls currently have no card in the V2 UI; treat them as deferred enhancements or convert them into Learning/Script settings later.

## Summary

For now, the most urgent gaps are `negative_prompt`, `adetailer_*`, and the Upscale/Img2Img advanced switches. The current run/preset payload already preserves the extra fields, so when we expand the UI we can rebuild the full fidelity. The new `load_config` wiring and preset helper should make it easier to prove round-tripping once those controls arrive.
