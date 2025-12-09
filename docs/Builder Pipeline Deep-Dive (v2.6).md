#CANONICAL
Builder Pipeline Deep-Dive (v2.6).md
How Prompt Pack Substitution, Matrix Expansion, Overrides, and Normalization Work Internally

Version: 2.6
Status: Canonical / Drop-In Doc
Last Updated: Today
Subsystems Covered: ConfigMergerV2 • RandomizationEngineV2 • UnifiedPromptResolver • UnifiedConfigResolver • JobBuilderV2

1. Purpose

This document explains, in exact implementation detail:

How prompt substitution works

How matrix slot values are selected and substituted

How matrix combinations or rotations are expanded into variants

How runtime overrides influence substitution without violating PromptPack-Only

How the builder pipeline produces normalized, reproducible jobs

This is not design theory; it describes the actual ordering, data flows, and internal responsibilities as defined in the architecture.

2. The Builder Pipeline: High-Level Flow

From PROMPT_PACK_LIFECYCLE_v2.6.md:
Prompt text comes ONLY from the Prompt Pack TXT. Matrix metadata comes from the Prompt Pack JSON. Overrides come from Pipeline Tab. No GUI component may do any text substitutions.

The full pipeline is:

Preset Snapshot + Pack JSON + Overrides
        ↓
ConfigMergerV2            (merges base config)
        ↓
RandomizationPlanV2       (describes matrix-enabled variant production)
        ↓
RandomizerEngineV2        (generates variant configs + matrix slot selections)
        ↓
PromptPack TXT Row        (raw prompt with [[slots]])
        ↓
UnifiedPromptResolver     (slot substitution, negative layering)
        ↓
UnifiedConfigResolver     (stage chain + final config)
        ↓
JobBuilderV2              (produce NormalizedJobRecord objects)

3. Detailed Stage Walkthrough
3.1 ConfigMergerV2 — What Gets Merged?

ConfigMergerV2 is pure (no I/O) and only merges configs, never touches text.

Input layers:

PresetConfig (global defaults)

Pack JSON Config (pack-specific SDXL settings)

StageOverridesBundle (Pipeline tab override flags)

Merge rules (from PROMPT_PACK_LIFECYCLE_v2.6.md + ARCHITECTURE_v2.6.md):

Overrides apply only when explicitly selected.

Disabled stages stay disabled even if pack config enables them.

Pack JSON’s randomization metadata is preserved.

No mutation of underlying pack json; deep copies only.

Output: MergedRunConfig for a single row prior to randomization.

3.2 RandomizationPlanV2 — Describing Substitution Intent

The plan records:

Whether randomization is enabled

The mode ("rotate" or "combine")

prompt_mode ("prepend" or "replace")

Matrix slots + slot arrays (e.g., environment = ["volcanic lair", "ruined cathedral"])

Max variants

Seed behavior

An example extracted from the pack JSON:

"randomization": {
  "enabled": true,
  "matrix": {
    "mode": "rotate",
    "prompt_mode": "prepend",
    "slots": {
      "environment": ["volcanic lair", "ruined cathedral"],
      "lighting": ["hellish backlight", "golden hour"]
    }
  }
}


RandomizationPlanV2 does not perform substitution; it only encodes intent.

3.3 RandomizerEngineV2 — Producing the Variant Grid

RandomizerEngineV2 takes:

MergedRunConfig + RandomizationPlanV2


It produces:

3.3.1 VariantConfig List

Each variant represents:

The resolved slot selection (environment = "volcanic lair")

Variant index and total

A config signature for reproducibility

Seed assignment (deterministic)

3.3.2 How slot values are chosen

Mode = rotate

Environment[0] + Lighting[0]

Environment[1] + Lighting[1]

Wrap if lengths mismatch

Mode = combine

Full cross-product:

environment × lighting × camera × style …

3.3.3 Explicit Guarantees

Deterministic with fixed seed

Independent of prompt text

Never edits strings; only chooses which slot value is passed forward

Output: A list of VariantConfig objects — each with a concrete set of chosen slot values.

4. Prompt Substitution Layer

This stage performs the actual insertion of slot values into the prompt text.

It follows exactly the rules from PROMPT_PACK_LIFECYCLE_v2.6.md:

“Prompt structure stays in TXT. Randomization metadata stays in JSON. Only Prompt Pack authoring subsystem modifies the pack.”

4.1 Inputs to UnifiedPromptResolver

For each row and variant:

TXT Row String  (e.g. "A warrior in [[environment]] under [[lighting]]")
VariantConfig   (e.g. { environment: "volcanic lair", lighting: "hellish backlight" })
Pack JSON negatives
Global negative
Row-level negatives
Prompt_mode ("prepend" or "replace")

4.2 Substitution Algorithm (Exact)
let final_prompt = row_text

for slot_name, slot_value in variant_config.slots:
    final_prompt = final_prompt.replace(f"[[{slot_name}]]", slot_value)


Details:

If a slot exists in the TXT but NOT in JSON slots → error
(This ensures editor consistency.)

If a slot exists in JSON but NOT in TXT → no-op
(Unused metadata is allowed.)

4.3 prompt_mode Behavior
prompt_mode = "replace"

Replaces the entire row with slot selection text.

Example:

Row: "A warrior portrait"
Slot value: "volcanic lair"
Final prompt: "volcanic lair"

prompt_mode = "prepend"

Adds slot value(s) before the resolved row:

"volcanic lair, hellish backlight, A warrior portrait"


Order is deterministic: alphabetical by slot name unless otherwise specified.

4.4 Negative Prompt Construction

NEGATIVE =

Row.negatives
+ Pack JSON negatives (txt2img.negative_prompt, etc.)
+ Global negative (from app settings)
+ Runtime negative override (optional; does not mutate pack)


From PROMPT_PACK_LIFECYCLE_v2.6.md:

“Final negative is row negatives + pack JSON negatives + global negative + runtime negative override”

No component combines or rewrites text outside this rule.

5. UnifiedConfigResolver — Producing Executable Stage Chains

After prompt substitution, UnifiedConfigResolver creates:

StageChain (canonical order)

Stage config objects (refiner, hires, upscale…)

Loop/batch metadata

Output settings

Final resolution, sampler, scheduler, cfg

This must align exactly with the runner’s required schema in ARCHITECTURE_v2.6.md:

“Builder Pipeline is the only subsystem allowed to build StageChain.”

6. JobBuilderV2 — Final Normalization

JobBuilderV2 combines:

Resolved prompt + Resolved negative
Resolved pipeline config (UnifiedConfigResolver)
Variant index
Batch index
Seed (deterministic)
Pack provenance (pack_id, row_index)
Randomization metadata
Output settings


It produces NormalizedJobRecord, which is:

Immutable

Self-contained

Fully resolved

Queue-safe

Runner-ready

History/Learning-ready

From ARCHITECTURE_v2.6.md:

“Queue/Runner consume NormalizedJobRecords only; they never modify jobs.”

7. Worked Example (Concrete)

Prompt Pack TXT contains:

A mythical beast in [[environment]] with [[lighting]] ambiance.


Pack JSON contains:

"slots": {
  "environment": ["volcanic lair", "ruined cathedral"],
  "lighting": ["hellish backlight", "amber torchlight"]
},
"prompt_mode":"prepend"

Step 1 — RandomizerEngineV2 (mode = rotate)

Variant 0:

environment = "volcanic lair"

lighting = "hellish backlight"

Variant 1:

environment = "ruined cathedral"

lighting = "amber torchlight"

Step 2 — UnifiedPromptResolver

Variant 0 prompt:

"volcanic lair, hellish backlight, A mythical beast in volcanic lair with hellish backlight ambiance."


Variant 1 prompt:

"ruined cathedral, amber torchlight, A mythical beast in ruined cathedral with amber torchlight ambiance."


Negatives constructed per the 4-part rule.

Step 3 — UnifiedConfigResolver

Resolve model, sampler, scheduler, steps

Build canonical StageChain

Attach per-stage configs

Step 4 — JobBuilderV2

Two NormalizedJobRecord objects produced, each ready for queueing.

8. Failure Modes Caught Early

The following are enforced:

Missing slot definitions in JSON → error

Missing slot tokens in TXT → allowed

Unresolved tokens after substitution → error

Empty prompt after substitution → error

Any mutation of prompts outside the resolver → forbidden

Any GUI attempt to produce text → forbidden

9. Testing Requirements (from Coding & Testing Standards)

Pipeline tests MUST assert:

Substitution correctness

Slot-to-token mapping

prompt_mode behavior

Randomization variant ordering

Deterministic seeds

Merged negatives

JSON slot/txt token mismatch handling

GUI tests must not test substitution—GUI cannot perform substitution.

10. Summary

Substitution happens only inside UnifiedPromptResolver.
Slot values are chosen only by RandomizerEngineV2.
Stage construction happens only in UnifiedConfigResolver + JobBuilderV2.
The GUI never constructs prompts, never substitutes tokens, and never edits packs.

This preserves:

Determinism

Reproducibility

Clean subsystem boundaries

Reasonable testability

PromptPack-Only architecture integrity