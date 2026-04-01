# PR-CORE-014 - Multi-Character Support

Status: Completed 2026-03-31

## Summary

PR-CORE-014 extends the StableNew pipeline to support multiple characters per
scene or shot.  The `Actor` dataclass and `ScenePlan`/`ShotPlan` actor lists
already existed from PR-VIDEO-219; this PR closes the remaining gaps in the
config contract, builder wiring, safe manifest resolution, and GUI surface.

The primary-character-first LoRA ordering convention is codified in
`config_contract_v26` and enforced through existing `resolution_layer` ordering:
actors → pack row LoRAs → style LoRA.

## Delivered

- extended `config_contract_v26.py`:
  - added `"actors"` to `_EXECUTION_HINT_KEYS` and `_INTENT_TOP_LEVEL_KEYS`
  - special-cased `actors` in `canonicalize_intent_config` to preserve non-empty
    lists without treating them as empty Mappings
  - added `extract_actors_intent()` to extract and validate the actors list from
    any intent or layered config
  - added `validate_multi_character_actors()` to normalize actor arrays and
    reject malformed entries with clear semantics

- extended `training/lora_manager.py`:
  - added `resolve_actors_safe()` — identical to `resolve_actors()` but catches
    `ValueError` per-actor, logs a warning, and continues; satisfies the
    PR-CORE-014 guardrail "if a character is missing, provide a clear error
    message and skip generation"

- extended `pipeline/prompt_pack_job_builder.py`:
  - `_resolve_entry_actors()` now calls `resolve_actors_safe` instead of the
    raising `resolve_actors`
  - resolved actors are persisted into the NJR `intent_config` under the
    `"actors"` key with a fallback to raw actor declarations in the config
    snapshot; this enables replay without re-invoking the LoRAManager

- extended `pipeline/job_builder_v2.py` (`build_from_run_request` path):
  - actors are extracted from the config_snapshot and materialised as `LoRATag`
    instances on the NJR's `lora_tags` field
  - `extract_actors_intent` is included in the `intent_config` payload so that
    actors survive the NJR → history → replay round-trip

- added `src/gui/widgets/multi_character_selector.py`:
  - self-contained `MultiCharacterSelectorWidget` (`ttk.LabelFrame`)
  - lists registered characters from the LoRAManager manifest with
    checkbox + weight spinbox per character
  - `get_selected_actors()` returns an actors list ready for `intent_config`
  - `set_actors()` restores a prior selection for persistence/round-trip
  - `refresh()` reloads the manifest without restarting the UI

- added `tests/pipeline/test_prompt_pack_multi_character.py`:
  - 24 deterministic pytest unit tests covering:
    - prompt assembly (trigger phrases, ordering, de-duplication)
    - `validate_multi_character_actors` normalisation
    - `extract_actors_intent` and `canonicalize_intent_config` round-trips
    - `resolve_actors_safe` skip-and-warn behaviour
    - `StoryPlan` / `ScenePlan` actor round-trips and merge semantics
    - actors in NJR intent payload

- added `tests/services/test_prompt_pack_multi_character.py`:
  - integration-level tests spanning manifest lookup + prompt assembly +
    schema round-trips; satisfies the PR-CORE-014 spec's required file path

## Key Files

- `src/pipeline/config_contract_v26.py`
- `src/pipeline/prompt_pack_job_builder.py`
- `src/pipeline/job_builder_v2.py`
- `src/training/lora_manager.py`
- `src/gui/widgets/multi_character_selector.py`
- `tests/pipeline/test_prompt_pack_multi_character.py`
- `tests/services/test_prompt_pack_multi_character.py`

## LoRA Ordering Convention

Primary actor LoRAs → secondary actor LoRAs → pack-row LoRAs → style LoRA.
This ordering is preserved from insertion order in the actor list.  The
`resolution_layer` enforces this through `_actor_lora_tags()` (returns actor
tags) → pack_row.lora_tags → `_style_lora_tags()` applied in that sequence to
`_dedupe_lora_tags()`.

## Backwards Compatibility

- Single-character scenes continue to work: `actors` is an optional field; its
  absence is not an error anywhere.
- `resolve_actors` (the raising version) is preserved unchanged for callers that
  prefer strict failure; `resolve_actors_safe` is the new convention for the
  builder pipeline.
- Scenes/shots without an `actors` field produce NJRs with `lora_tags=[]` and
  no actor trigger phrases in the prompt, exactly as before.

## Validation

```
python -m pytest -q \
  tests/pipeline/test_prompt_pack_multi_character.py \
  tests/services/test_prompt_pack_multi_character.py \
  tests/video/test_story_plan_models.py \
  tests/training/test_lora_manager.py \
  tests/pipeline/test_prompt_pack_resolution.py
```

## Notes

- The `MultiCharacterSelectorWidget` is a standalone widget; it is not yet wired
  into the Prompt tab or story planner tab.  Follow-on work should embed it in
  `prompt_tab_frame_v2.py` or a dedicated scene-planner panel.
- Dynamic character weighting based on scene prominence (non-goal per PR spec)
  is deferred to future roadmap work.
- Model-compatibility warnings when mixing LoRAs from different base models
  (mentioned in risk section) are a follow-on; the manifest does not currently
  record the base model for each LoRA.
