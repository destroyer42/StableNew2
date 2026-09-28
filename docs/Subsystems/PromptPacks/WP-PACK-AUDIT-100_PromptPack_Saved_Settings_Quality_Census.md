# WP-PACK-AUDIT-100 — PromptPack & Saved-Settings Quality Census

Status: complete; read-only/observational tooling and one real-machine census.
No PromptPack, preset, `.default_preset` pointer, `settings.json`, or asset
was modified. No network, A1111/Comfy, GPU, or model-load action occurred.

## Outcome

`tools/promptpack_quality_census.py` is a new offline, deterministic operator
tool that answers, from raw persisted JSON rather than typed/normalized
views:

1. Are current PromptPacks structurally valid and normalization-safe?
2. Which local LoRA/embedding/model/VAE references resolve to installed
   file-backed assets?
3. Where does Asset-120 show resolved family compatibility, explicit family
   conflict, or unknown evidence?
4. Which saved generation settings contain internally contradictory
   aliases/stage settings or malformed values?
5. Which findings are genuine defects, which are compatibility/quality debt,
   and which cannot be adjudicated offline?

It does not implement recommendations, warning UX, PromptPack repair, or a
second model-family taxonomy; it consumes `src.assets.AssetRegistry` and its
Asset-120 `CompatibilityProfile` exactly as they exist rather than
re-inferring compatibility.

## Why raw JSON, not typed loading

`PromptPackModel.load_from_file()` (and `ConfigManager`'s preset merge with
defaults) silently repairs or hides several classes of persisted problem
before a human or a later consumer would ever see them: duplicate/negative
slot indexes collapse to enumeration order, malformed LoRA weight entries
would raise inside `float()` rather than being reported, and preset defaults
fill in any field a contradictory alias left ambiguous. The census
deliberately inspects the raw document first, before any of that
normalization runs, then separately checks whether typed loading would
repair or crash on what it found.

## Canonical sources audited

- **PromptPacks**: the current production authority resolved by
  `src.promptpacks.paths.resolve_prompt_pack_dir()` — the per-user
  StableNew data directory (or `STABLENEW_PROMPTPACK_DIR` when set), never
  the repository-relative `packs/` corpus, which is historical/interchange
  evidence only.
- **Saved generation settings**: each native PromptPack's raw `preset_data`,
  standalone preset JSON files in the active `ConfigManager.presets_dir`, and
  the `.default_preset` pointer. `settings.json` is discovered by the same
  `*.json` glob `ConfigManager.list_presets()` uses, so the census reports its
  presence as a finding (`settings_json_surfaced_as_preset`) rather than
  auditing its contents as a generation recipe.
- **Asset evidence**: `src.assets.AssetRegistry`, refreshed once against an
  audit-owned cache path (never the operator's normal
  `state/asset_registry_v1.json`), and its Asset-120 `CompatibilityProfile`.

## Confirmed alias/stage contradictions checked

Every alias group the census checks is reused, not invented, from the
production normalizer at `src/pipeline/config_normalizer.py`
(`normalize_stage_payload_config` / `normalize_pipeline_config`) and one
directly-observed dual-flag site in `src/controller/app_controller.py`:

- `model` / `model_name` / `sd_model`, `vae` / `vae_name` / `sd_vae`,
  `sampler_name` / `sampler`, `scheduler` / `scheduler_name` (txt2img,
  img2img)
- `refiner_model_name` / `refiner_checkpoint`, `refiner_enabled` /
  `use_refiner`, `enable_hr` / `hires_enabled` (txt2img)
- `adetailer_model` / `ad_model`, `enabled` / `adetailer_enabled` (adetailer)
- `upscaler` / `upscaler_name` / `upscaler_1` (upscale)
- cross-section stage enablement: `pipeline.<stage>_enabled` vs.
  `<stage>.enabled` for txt2img, img2img, adetailer, upscale, animatediff,
  and video_workflow
- cross-section hires-fix enablement: top-level `hires_fix.enabled` vs.
  `txt2img.hires_enabled`/`txt2img.enable_hr`

A disagreement is reported only when two or more of a confirmed group are
persisted with materially different non-empty values; an omitted field is
never treated as a contradiction, since defaults intentionally fill it.

## Asset-reference resolution and family compatibility

For each PromptPack, the census resolves its `txt2img` checkpoint reference
(`model`/`model_name`/`sd_model`), VAE, refiner checkpoint, and every
structured slot LoRA/embedding reference against the Asset Registry,
classifying each as `resolved_unique`, `resolved_duplicate_bytes` (one
content identity with multiple same-kind aliases), `ambiguous_same_name`
(one reference name maps to more than one distinct SHA-256),
`missing_file_backed_asset`, or `offline_unverified` (Asset Registry/WebUI
root coverage unavailable). Duplicate-bytes/ambiguity classification is
scoped to the reference's own asset kind, so an unrelated checkpoint and LoRA
that happen to share bytes are never conflated.

When the checkpoint resolves to one asset with an Asset-120
`CompatibilityProfile`, every other reference that also resolves uniquely is
compared against it: matching resolved families are `family_compatible`,
differing resolved families are `family_mismatch`, either side being
`conflicting` is `family_evidence_conflicting`, and either side being
`unknown` is `family_unknown`. No explicit checkpoint reference at all is
`no_explicit_base_context` — the census never assumes the global/default
checkpoint. A mismatch on a disabled stage (e.g. a disabled refiner) is
retained, not omitted, but downgraded to informational dormant debt rather
than presented as an active failure.

## Real-machine census result

Run against source SHA `cad09a06c43c905eb3de248f85e3d125430d7daa`: 39
PromptPack files (canonical per-user directory) and 17 standalone presets
(active `presets/` directory) examined, with full Asset Registry/WebUI
coverage available. 1,020 total findings.

| Finding class | Count |
|---|---|
| asset_resolution | 508 |
| family_compatibility | 437 |
| identity_duplication | 46 |
| format_schema | 2 |
| saved_setting_contradiction | 11 |
| slot_normalization_risk | 4 |
| matrix_structure | 12 |

Selected finding codes: `resolved_unique` 481, `family_unknown` 431,
`missing_file_backed_asset` 24, `resolved_duplicate_bytes` 3,
`family_evidence_conflicting` 5, `duplicate_native_pack_name` 26,
`pack_name_filestem_mismatch` 20, `saved_setting_stage_contradiction` 10,
`enabled_matrix_slot_no_values` 12, `malformed_json` 1,
`unversioned_schema` 1, `settings_json_surfaced_as_preset` 1,
`no_explicit_base_context` 1, `duplicate_slot_index` 2,
`duplicate_structured_reference` 1, `sparse_or_noncanonical_slot_indexes` 1.

Notable, verified-genuine patterns (not tool false positives — each was
individually inspected against the raw source before being reported here):

- The overwhelming majority of asset references (481 of ~513 checkpoint/VAE/
  LoRA/embedding references) resolve uniquely; the real defect surface is
  small and specific, not systemic.
- **A systematic stage-enablement contradiction** recurs identically across
  five distinct real packs (`SDXL_epic_structures_Fantasy`,
  `Juggernaut_MedievalHeroes_RandomizerAligned_v1b`,
  `Photoreal_Character_Juggernaut_SDXL`, `Testing`, `default`): each persists
  `pipeline.adetailer_enabled=true` alongside `adetailer.enabled=false`. The
  same underlying inconsistency is reported by both the pipeline-cross-section
  check and the within-section `enabled`/`adetailer_enabled` check, so it
  appears twice per pack in the raw report.
- At least one real reference is a literal stringified placeholder rather
  than a genuine filename: `SDXL_epic_structures_Fantasy` persists
  `refiner_checkpoint: "None"` (the text "None", not a null/omitted field),
  which correctly reports as `missing_file_backed_asset` but is worth
  distinguishing from an ordinary renamed/deleted-file miss.
- 26 of 39 packs share a `pack_data.name` with at least one other pack
  (mostly copy/variant/test packs never renamed after duplication), and 20
  have a `pack_data.name` that no longer matches their current filename —
  both are naming hygiene debt, not correctness defects.
- One initial finding class was caught and removed before this evidence was
  finalized: the census's first pass flagged `mode="random"` as an
  "unsupported matrix mode" in 26 packs. Re-reading
  `src/pipeline/prompt_pack_job_builder.py` showed `random` is an explicitly
  handled, working production mode — the check was a false positive from an
  incomplete assumption (a stale docstring comment on `MatrixConfig`, not the
  actual execution contract) and was deleted from the tool rather than left
  in with a caveat.

## Candidate follow-on packages

The census evidence supports selecting one of these next, under the current
one-active-package posture (not both at once):

1. **Saved-setting stage-enablement repair** — bounded, high-confidence: fix
   the `pipeline.adetailer_enabled` vs `adetailer.enabled` write/sync path so
   the two representations cannot diverge, then correct the five already-
   identified real packs. Smallest, most concretely evidence-backed change.
2. **Missing/ambiguous asset-reference cleanup** — operator-facing: surface
   the 24 `missing_file_backed_asset` and 3 `ambiguous_same_name`/
   `resolved_duplicate_bytes` references (including the literal `"None"`
   placeholder case) so the owner can correct or intentionally retire them;
   this is manual owner triage, not automatic repair.

Lower priority / explicitly deferred: pack naming-hygiene cleanup
(`duplicate_native_pack_name`, `pack_name_filestem_mismatch`) is cosmetic and
not correctness debt; family-mismatch/unknown/conflicting evidence (437
findings) is observational input for a future compatibility-advisory package,
not something to act on without a separate product decision.

## Execution profile and validation

- Execution class: Standard, Local/Desktop. Controller surface assessment:
  not applicable — no controller/coordinator changed.
- Token-efficient validation: 34 focused fixture tests over temporary
  PromptPack/preset/WebUI roots cover every required behavior class:
  malformed/unversioned/non-object documents, slot index and normalization
  risk, malformed LoRA/embedding entries, raw asset tokens in nominally pure
  text, matrix structural defects, identity/duplication, every confirmed
  alias/stage-contradiction group, a dangling default preset, the
  `settings.json` glob collision, all five asset-resolution classes, all four
  family-compatibility classes plus the no-explicit-base-context and
  dormant-disabled-stage cases, deterministic output, and a proof that the
  tool never mutates the PromptPack/preset files it reads. No real user
  library is used as a test fixture.
- The one real-machine run used the operator's actual per-user PromptPack
  directory, the repository's active `presets/` directory, and the
  configured local WebUI root, with an audit-owned Asset Registry cache — no
  network, A1111/Comfy connection, GPU, or model load occurred, and a
  read-only size/mtime fingerprint of every examined PromptPack/preset file
  was confirmed unchanged before and after the run.

## Next package

`WP-PACK-AUDIT-100` produces evidence only. The next coherent package should
be selected from the candidate follow-on list above under the current
one-active-package execution posture; it must not attempt PromptPack/preset
repair or begin recommendation/warning UX without a separate owner decision.
