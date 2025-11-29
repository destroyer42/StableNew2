# Randomization Example - How to Use

This preset demonstrates all three randomization features working together.

## What This Example Does

When you run `randomization_test.txt` with this preset:

### Prompt S/R (Search & Replace)

- Replaces `person` with random choice: man, woman, child, or elder
- Replaces `pose` with random choice: standing, sitting, walking, or running

### Wildcards (`__token__` syntax)

- `__mood__` → happy, sad, angry, contemplative, or serene
- `__weather__` → sunny, cloudy, rainy, foggy, or stormy
- `__lighting__` → golden hour, blue hour, midday sun, moonlight, or dramatic lighting

### Matrix (`[[Slot]]` syntax)

- `[[time]]` × `[[location]]` creates combinations:
  - dawn/forest, dawn/beach, dawn/mountain, dawn/city
  - noon/forest, noon/beach, noon/mountain, noon/city
  - (etc... 16 total combinations, capped at 8 due to limit setting)

## Expected Output

For the first prompt in `randomization_test.txt`:

```text
A person in a pose, __mood__ expression, __weather__ day, __lighting__, at [[time]] in a [[location]]
```

You'll get **UP TO 8 VARIATIONS** (matrix limit), each with:

- Random person type (S/R)
- Random pose (S/R)
- Random mood (wildcard)
- Random weather (wildcard)
- Random lighting (wildcard)
- Different time/location combinations (matrix)

## Log Output You'll See

```text
📦 Processing pack: randomization_test.txt
⚙️ Using override configuration for randomization_test.txt
🎛️ Variant plan (fanout) with 0 combo(s)
📝 Prompt 1/2: A person in a pose, __mood__ expression...
🎲 Randomization: person->woman; pose->sitting; __mood__=contemplative; __weather__=foggy; __lighting__=moonlight; [time]=dawn; [location]=forest
✅ Generated 1 image(s) for prompt 1 (random: person->woman; pose->sitting; ...)
🎲 Randomization: person->man; pose->walking; __mood__=serene; __weather__=sunny; __lighting__=golden hour; [time]=noon; [location]=beach
✅ Generated 1 image(s) for prompt 1 (random: person->man; pose->walking; ...)
... (up to 8 variations)
```

## Testing Instructions

1. **Load the preset**: File → Load Preset → `randomization_example.json`
2. **Check randomization is enabled**: Go to Randomization tab, verify "Enable randomization for the next run" is checked
3. **Select the test pack**: Choose `randomization_test.txt` from pack list
4. **Run**: Click Run Pipeline
5. **Watch the logs**: You should see `🎲 Randomization:` messages showing what changed

## Adjusting Settings

### Reduce Combinations

- Set `matrix.limit` to lower value (e.g., 4)
- Switch `matrix.mode` to "rotate" (picks one combo per prompt instead of all)

### Change Selection Modes

- `prompt_sr.mode`: "random" or "round_robin"
- `wildcards.mode`: "random" or "sequential" (cycles through values)
- `matrix.mode`: "fanout" (all combos) or "rotate" (one per prompt)

### Disable Specific Features

Set `enabled: false` for any of:

- `randomization.prompt_sr.enabled`
- `randomization.wildcards.enabled`
- `randomization.matrix.enabled`

## Matrix Syntax Note

The **correct** matrix syntax is:

```text
slot_name: option1 | option2 | option3
```

Then use `[[slot_name]]` in your prompts.

**Wrong** (will be ignored):

```text
option1 | option2 | option3
```

This is missing the slot name and colon!
