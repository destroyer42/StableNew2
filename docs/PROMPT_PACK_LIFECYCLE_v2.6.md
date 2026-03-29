PROMPT_PACK_LIFECYCLE_v2.6.md

(Canonical)

StableNew - PromptPack Lifecycle Specification (v2.6)
Last Updated: 2026-03-29
Status: Canonical, Binding

## 0. Scope

This document defines the lifecycle of PromptPack-based image authoring in
StableNew.

PromptPack is the primary image authoring surface. It is not the only valid
intent surface in the product. Other surfaces are governed by
`docs/ARCHITECTURE_v2.6.md` and their own subsystem docs.

This document covers:

- PromptPack structure
- PromptPack authoring and validation
- PromptPack selection and draft usage
- PromptPack resolution through the builder path
- PromptPack provenance inside NJR, history, replay, and learning

## 1. PromptPack Definition

A PromptPack is defined by exactly two files with the same basename:

- `{name}.txt` for positive prompt rows
- `{name}.json` for metadata, matrix values, and defaults

No PromptPack exists without both.

PromptPack JSON may also carry optional template authoring metadata per slot:

- `template_id` to reference a curated cinematic prompt template
- `template_variables` to hold placeholder values used during prompt expansion

Template metadata is authoring-time input only. The TXT companion remains the
resolved prompt surface used by the builder path.

## 2. PromptPack Lifecycle

The PromptPack lifecycle is:

Author -> Validate -> Store -> Select -> Draft -> Resolve -> Expand -> Build NJR -> Queue -> Run -> History -> Learning

This lifecycle applies only to PromptPack-authored work.

## 3. Authoring Rules

PromptPacks may be authored or edited through:

- the PromptPack builder/editor surface
- direct file editing when the files remain schema-valid

Required rules:

- rows must be UTF-8 text
- comments may exist, but executable rows must not be empty
- JSON must be schema-valid
- template references must resolve against the prompt template catalog when
  present
- matrix slots and placeholders must reconcile cleanly
- defaults must map to valid PromptPack-side image configuration

Forbidden at authoring time:

- embedding executor logic in prompt rows
- inventing alternate runtime payloads inside pack files
- using PromptPack files as a transport for backend workflow JSON

## 4. Selection and Draft Phase

The pipeline surface may select:

- pack
- row subset
- randomization settings
- config sweeps
- runtime overrides allowed by the canonical builder path

Selection creates draft state only. It does not execute anything and does not
mutate the PromptPack.

## 5. Validation Phase

PromptPack validation includes:

- file existence
- TXT row parsing
- JSON structure
- matrix slot reconciliation
- default-value normalization
- stage legality for the PromptPack image path

Invalid PromptPacks may not be used to build new NJR-backed work.

## 6. Resolution and Expansion Phase

For PromptPack-authored jobs, the builder path performs:

- row selection
- template expansion
- matrix substitution
- randomization expansion
- config sweep expansion
- actor provenance carry-through from linked intent surfaces when present
- prompt-layer resolution
- stage-ready config normalization
- final NJR construction

When PromptPack image intent is derived from `story_plan`, scene-level and
shot-level actor metadata may already be deterministically merged onto
`plan_origin` before NJR construction. That actor metadata remains canonical
builder input rather than a separate runtime path.

Prompt resolution may use carried actor provenance to:

- preserve `story_plan` and `plan_origin` metadata through canonical
  intent/config layering
- inject resolved actor trigger phrases into the positive prompt
- prepend resolved actor LoRA tags ahead of pack-authored LoRA tags with stable
  de-duplication

All PromptPack expansion is complete before queue submission.

## 7. NJR Construction and Ownership

The PromptPack builder path stores PromptPack provenance in the NJR, including:

- pack identity
- row identity
- resolved prompt text
- resolved matrix values
- normalized execution config
- carried actor provenance from `plan_origin` when present
- variant metadata

After NJR creation:

- PromptPack files are no longer consulted during execution
- execution uses NJR-backed normalized config only
- carried actor provenance remains part of NJR-backed build output, not
  runner-side reconstruction
- the PromptPack remains provenance, not a live runtime dependency

## 8. Queue, Runner, History, and Learning

For PromptPack-authored jobs:

- queue stores NJR-backed jobs only
- runner executes NJR-backed normalized config only
- history stores NJR provenance and canonical result summaries
- learning consumes outputs and ratings from executed results; it does not
  rewrite PromptPack files directly

## 9. Ownership Rules

PromptPack owns:

- row text
- matrix definitions
- pack-local defaults
- pack-level provenance metadata

The builder pipeline owns:

- resolution
- expansion
- normalized execution config
- NJR creation

Queue and runner own:

- execution lifecycle
- stage orchestration
- result and artifact recording

## 10. Forbidden Behaviors

The following are forbidden:

- GUI-side prompt construction outside the canonical builder path
- modifying PromptPack files during execution
- resolving pack defaults inside the runner
- treating PromptPack as the universal input source for non-PromptPack surfaces
- rebuilding fresh runtime state from PromptPack after NJR submission

## 11. Relationship To Other Intent Surfaces

StableNew also supports:

- reprocess
- image edit
- replay
- learning-generated submissions
- CLI
- video workflow

Those are valid intent surfaces, but they do not change PromptPack lifecycle
rules. They simply have their own builder/compiler entrypoints.
