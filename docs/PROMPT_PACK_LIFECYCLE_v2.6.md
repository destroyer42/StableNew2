#CANONICAL
PROMPT_PACK_LIFECYCLE_v2.6.md
Authoritative Reference for Prompt Authoring, Pack Configs, Randomization, and Overrides in StableNew

Version: 2.6
Status: Canonical
Last Updated: 2025-12-08

0. Purpose

The Prompt Pack Lifecycle defines:

Where prompts originate

How Prompt Packs are authored, stored, and versioned

How their associated configuration (pack JSON) is created and edited

Where and how global negatives, randomization matrices, and slot values are defined

How runtime config overrides and config sweeps work without violating PromptPack-only architecture

This document is required reading for all developers working within PR-CORE-A/B/C/D.

1. PromptPack-Only Principle

StableNew v2.6 uses the following architectural invariant:

All pipeline jobs MUST originate from a saved Prompt Pack.
GUI-owned free-text prompt fields are forbidden in the Pipeline Tab.
Only the Advanced Prompt Builder can author prompt content.

This eliminates ambiguity, ensures reproducibility, and dramatically stabilizes testing, debugging, and learning.

2. Prompt Pack Components

Each Prompt Pack consists of two files, always stored together:

2.1 Prompt Pack TXT

Human-authored content from the Advanced Prompt Builder, including:

Positive embedding tags

Negative embedding tags

Style/quality line

Subject template(s)

Per-row negative blocks

Optional randomization tokens:

[[environment]]

[[lighting]]

[[camera]]

[[style]]

[[world_flavor]]

etc.

This file contains all semantic prompt structure.

No other subsystem is allowed to modify or generate prompt text.

2.2 Prompt Pack JSON

Machine-readable configuration associated with the pack, created on the first save of a pack.

Includes:

A. SDXL pipeline configuration

txt2img block

img2img block

upscale block

adetailer block

pipeline (looping, batch, variant mode)

aesthetic settings

B. Randomization Matrix (if enabled)
randomization: {
    enabled: true,
    matrix: {
        mode: "rotate" | "combine",
        prompt_mode: "prepend" | "replace",
        slots: {
            "environment": [...],
            "lighting": [...],
            "style": [...],
            ...
        }
    }
}

C. Pack-level metadata

prompt_pack_id

version/hash

authoring timestamp

D. Negative prompt layers

Config-level negatives are allowed here, separate from row negatives.

3. Lifecycle Stage 1 — Pack Creation
Step 1: User authors content inside Advanced Prompt Builder

User creates:

Embedding lines

Style lines

Subject line(s) (with or without matrix tokens)

Per-row negatives

Step 2: User saves the pack

Controller writes:

pack_name.txt

pack_name.json (initialized skeleton)

The JSON skeleton contains default config and no matrix slot values yet.

4. Lifecycle Stage 2 — Pack Configuration & Matrix Editor

(OPTION A – Official & Canonical)

Prompt Pack JSON is enriched only inside Advanced Prompt Builder via the Pack Config / Randomization Editor panel.

This editor:

Automatically detects [[tokens]] in the TXT file

Creates corresponding empty matrix.slots entries

Provides a UI for adding values (e.g., “volcanic lair”, “ruined cathedral”)

Allows switching mode and prompt_mode

Allows toggling randomization.enabled

Example workflow:

User adds [[environment]] and [[lighting]] in TXT
→ Pack Config Editor displays these slots
→ User enters values
→ Controller updates pack JSON


This ensures:

Prompt structure stays in TXT

Randomization metadata stays in JSON

Only Prompt Pack authoring subsystem modifies the pack

Pipeline Tab never edits packs

5. Lifecycle Stage 3 — Global Negative Handling

Global negative exists outside any pack and is layered during prompt resolution.

Ownership:

Global negative lives in app settings (e.g., app_settings.json).

It is not editable in the Pipeline Tab.

It is not stored in pack JSON unless explicitly chosen.

During prompt resolution, final negative is:
final_negative_prompt =
    PromptPackRow.negatives
  + PromptPackJSON.txt2img.negative_prompt (optional)
  + global_negative_prompt (from app settings)
  + runtime_negative_override (optional & controlled)


This preserves:

PromptPack-only ownership of semantic prompt text

ability for the user to define a global negative

no architectural violations

6. Lifecycle Stage 4 — Runtime Overrides & Config Sweeps

Even under PromptPack-only architecture, users must be able to:

Run the same prompt multiple times with different configs
(e.g., testing different cfg, sampler, steps, or stage chains)

This is fully supported via runtime overrides and/or config sweeps.

6.1 Runtime Overrides

User selects:

A Prompt Pack

A config snapshot (preset or pack JSON baseline)

Selectively overrides config parameters in the Pipeline tab:

cfg

steps

sampler

resolution

aDetailer on/off

hires on/off

etc.

The override is passed to:

ConfigMergerV2 → UnifiedConfigResolver → JobBuilderV2


Overrides affect only the current run, not the pack.

6.2 Config Sweep (multi-config testing)

User selects:

“Run same prompt 5 times, each with a different config.”

This is implemented as:

Pipeline Tab builds a ConfigVariantPlan

Builder treats each config variation as a variant

JobBuilder expands rows × config variants × batch

This allows:

Config experiments

Hyperparameter sweeps

Learning comparison studies

While preserving prompt integrity.

7. Lifecycle Stage 5 — Job Construction (PR-CORE-B)

Builder expands:

Rows × Variants × Batches


into a list of immutable NormalizedJobRecord objects, each containing:

PromptPack provenance

Fully resolved prompt

Matrix slot selections

Embeddings + LoRAs

Stage chain

Config parameters

Seeds

Variant and batch indices

run_mode + queue_source

All downstream subsystems consume these records as-is.

8. Lifecycle Stage 6 — Queue / Runner Execution

Queue and Runner:

Accept only NormalizedJobRecord

Never perform prompt or config resolution

Never mutate jobs

Write history entries with full metadata for Learning

Emit lifecycle events for GUI and Debug Hub

This guarantees predictability & reproducibility.

9. Lifecycle Stage 7 — History & Learning

Each completed job yields:

Output images

Full NormalizedJobRecord snapshot

Pack ID + Pack row index

Matrix slot values

Config signature

Variant & batch metadata

This supports:

Learning feedback loops

Reproduce previous results

Compare config sweeps

Debug accuracy

10. Summary Diagram — Prompt Pack Lifecycle
[Advanced Prompt Builder]
    ↓
Create TXT  ────────────────────────┐
Create JSON skeleton                │
    ↓                               │
[Pack Config / Matrix Editor]       │
    ↓                               │
Enrich JSON with slots/values       │
    ↓                               │
Save Pack                           │
    ↓                               ▼
  PromptPack = { TXT + JSON }  <────────────→  Editable only in Advanced Prompt Builder
    ↓
[Pipeline Tab]
Select Pack + Config + Overrides
    ↓
ConfigMergerV2 → RandomizerEngine → UnifiedPromptResolver → UnifiedConfigResolver → JobBuilderV2
    ↓
list[NormalizedJobRecord]
    ↓
Queue → Runner → History → Learning

11. Key Ownership Boundaries (Critical to Architecture)
Area	Owner	Notes
Prompt Text	PromptPack TXT	Only authored in Advanced Prompt Builder
Randomization Slot Definitions	PromptPack JSON	Edited only in Pack Config/Matrix Editor
Randomization Values	PromptPack JSON	Never created by Pipeline Tab
Global Negative	App Settings	Only layered in during prompt resolution
Runtime Config Overrides	Pipeline Tab	Allowed; does not mutate Pack JSON
Config Sweeps	Pipeline Tab	Implemented as VariantConfigs
Prompt Resolution	Builder Pipeline	Never done by GUI
Job Construction	Builder Pipeline	Produces full NormalizedJobRecord
Job Execution	Queue + Runner	Do not alter job records
12. Why This Lifecycle Matters

This lifecycle enables:

Reproducible prompting

Stable debugging

Deterministic randomization

Better testability

Clear data ownership

Fewer GUI failures

Better Learning inputs

Easy config experimentation

Without prompt fragmentation or architectural drift.

END – PROMPT_PACK_LIFECYCLE_v2.6.md