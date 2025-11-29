# Matrix Prompt Mode Feature

## Overview
The matrix randomization system now supports three modes for how the `base_prompt` relates to your pack prompts:

1. **Replace** (default) - Matrix base_prompt completely replaces pack prompt
2. **Append** - Matrix expansions are added to the end of pack prompts
3. **Prepend** - Matrix expansions are added before pack prompts

## Configuration

### JSON Config
```json
{
  "randomization": {
    "enabled": true,
    "matrix": {
      "enabled": true,
      "mode": "fanout",
      "prompt_mode": "append",  // NEW: "replace", "append", or "prepend"
      "limit": 8,
      "slots": [
        {"name": "lighting", "values": ["soft rim light", "dramatic shadows"]},
        {"name": "angle", "values": ["close-up", "medium shot"]}
      ],
      "base_prompt": "[[lighting]], [[angle]]"
    }
  }
}
```

### GUI Controls
Located in the **Randomization → Matrix** section:
- **Prompt mode**: Radio buttons to select Replace / Append / Prepend

## Use Cases

### Replace Mode (Original Behavior)
**When to use:** Pack prompts are templates/placeholders that should be completely replaced by matrix expansions.

**Example:**
- Pack prompt: `"hero portrait"`
- Base prompt: `"portrait of a [[race]] [[job]]"`
- Slots: `race: [human, elf]`, `job: [warrior, mage]`
- Output:
  - `"portrait of a human warrior"`
  - `"portrait of a elf mage"`
  - *(pack prompt is completely replaced)*

### Append Mode (NEW)
**When to use:** Pack prompts have detailed character descriptions, and you want to add variations without losing the original detail.

**Example:**
- Pack prompt: `"close-up portrait of a noble knight in ornate armor, scarred expression"`
- Base prompt: `"[[lighting]], [[mood]]"`
- Slots: `lighting: [soft rim light, dramatic shadows]`, `mood: [determined, weary]`
- Output:
  - `"close-up portrait of a noble knight in ornate armor, scarred expression, soft rim light, determined"`
  - `"close-up portrait of a noble knight in ornate armor, scarred expression, dramatic shadows, weary"`
  - *(matrix variations appended to pack prompt)*

### Prepend Mode (NEW)
**When to use:** Add artistic style prefixes or modifiers before your pack prompts.

**Example:**
- Pack prompt: `"portrait of a hero in armor"`
- Base prompt: `"[[style]], [[mood]]"`
- Slots: `style: [oil painting, watercolor]`, `mood: [vibrant, dark]`
- Output:
  - `"oil painting, vibrant, portrait of a hero in armor"`
  - `"watercolor, dark, portrait of a hero in armor"`
  - *(matrix variations prepended before pack prompt)*

## Separator
Append and prepend modes use `, ` (comma-space) as the separator between pack prompt and matrix expansion.

## Backward Compatibility
- If `prompt_mode` is omitted, defaults to `"replace"` (original behavior)
- Existing configs without `prompt_mode` will continue to work unchanged

## Implementation Notes
- The prompt_mode is applied in `PromptRandomizer.generate()` before any other transformations (S/R, wildcards)
- Empty `base_prompt` causes `prompt_mode` to be ignored (pack prompt used as-is)
- Labels track matrix slot replacements regardless of prompt_mode
