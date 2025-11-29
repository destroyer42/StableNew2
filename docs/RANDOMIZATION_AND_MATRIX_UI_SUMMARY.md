# Randomization & Prompt Matrix UI - Implementation Summary

## What's Been Completed

### 1. Working Randomization Example ✅

Created **three files** to help you understand and use randomization:

#### `presets/randomization_example.json`
A complete preset demonstrating all three randomization types:
- **Prompt S/R**: `person => man | woman | child | elder`
- **Wildcards**: `__mood__`, `__weather__`, `__lighting__`
- **Matrix**: `[[time]]` and `[[location]]` combinations

#### `packs/randomization_test.txt`
Sample prompts that use all randomization features together.

#### `presets/RANDOMIZATION_EXAMPLE_README.md`
Detailed guide explaining:
- How each randomization feature works
- Expected log output
- How to adjust settings (fanout vs rotate, limits, etc.)
- Common mistakes (like missing slot names in matrix syntax)

### 2. Improved Prompt Matrix UI ✅

**Replaced the single text box with a structured interface:**

#### New Features
- **Base Prompt Field**: Enter your main prompt with `[[Slot]]` markers
- **Dynamic Slot Rows**: Each slot has:
  - Slot name entry
  - Options entry (pipe-separated: `option1 | option2`)
  - Remove button (−)
- **Add Slot Button**: `+ Add Combination Slot`
- **Legacy Text View**: Optional toggle for advanced users who prefer raw text editing

#### Backward Compatibility
- Config format unchanged - `slots` array and `raw_text` still saved
- Old presets load correctly into new UI
- New `base_prompt` field added to matrix config (optional)

#### How It Works

**Before** (old UI):
```
time: dawn | noon | dusk
location: forest | beach
```

**Now** (new UI):
```
Base prompt: [___A scene at [[time]] in a [[location]]___]

Slot: [_time_] Options: [___dawn | noon | dusk___] [−]
Slot: [_location_] Options: [___forest | beach___] [−]

[+ Add Combination Slot]
```

Much easier to visualize!

## How to Test Randomization

### Step 1: Load the Example Preset
1. Launch StableNew
2. File → Load Preset → `randomization_example.json`

### Step 2: Verify Randomization is Enabled
1. Go to **Randomization** tab
2. Check that "Enable randomization for the next run" is **checked**
3. You should see:
   - Prompt S/R enabled with rules
   - Wildcards enabled with tokens
   - Matrix enabled with slots

### Step 3: Select Test Pack
1. In pack list, select `randomization_test.txt`
2. Make sure you have only one pack selected

### Step 4: Run and Watch Logs
1. Click **Run Pipeline**
2. Watch the log panel for messages like:
   ```
   🎲 Randomization: person->woman; pose->sitting; __mood__=contemplative; ...
   ```

You should see **multiple variations** of each prompt (up to 8 due to matrix limit setting).

## Using the New Matrix UI

### Creating a Matrix from Scratch

1. Go to **Randomization** tab
2. Scroll to **Prompt Matrix** section
3. Check "Enable prompt matrix expansion"
4. Enter base prompt:
   ```
   A portrait of a [[character]] in [[setting]], [[style]]
   ```
5. Click `+ Add Combination Slot` three times
6. Fill in slots:
   - Slot: `character` | Options: `warrior | mage | rogue`
   - Slot: `setting` | Options: `forest | castle | tavern`
   - Slot: `style` | Options: `realistic | anime | oil painting`
7. Set combination cap to 8 (prevents 3×3×3 = 27 combinations)
8. Choose mode:
   - **Fan-out**: Generates all combinations (up to limit)
   - **Rotate**: Picks one combo per prompt (cycles through)

### Editing Existing Matrix Config

When you load a preset with matrix config, the UI will:
- Populate base prompt field (if present)
- Create slot rows automatically
- You can add/remove/edit slots immediately

### Advanced: Legacy Text View

Check "Show advanced text editor (legacy format)" to see the raw text representation:
```
# Base: A portrait of a [[character]] in [[setting]], [[style]]
character: warrior | mage | rogue
setting: forest | castle | tavern
style: realistic | anime | oil painting
```

Changes sync both ways - edit either UI and the other updates!

## Troubleshooting

### "I don't see randomization working"

**Check these 4 things:**

1. **Master toggle**: Is "Enable randomization for the next run" checked?
2. **Sub-toggles**: Is at least ONE of these enabled?
   - Prompt S/R
   - Wildcards
   - Matrix
3. **Rules defined**: Are there actual rules/tokens/slots configured? Empty config = no randomization!
4. **Prompt markers**: Does your prompt contain the tokens?
   - For wildcards: `__token__` syntax
   - For matrix: `[[Slot]]` syntax
   - For S/R: The search terms

### "Matrix slots are empty after loading preset"

**Old presets had incorrect syntax:**
```
"raw_text": "option1 | option2 | option3"  ❌ Wrong!
```

**Should be:**
```
"raw_text": "slot_name: option1 | option2 | option3"  ✅ Correct!
```

Fix: Edit the preset JSON, or use the new UI to rebuild the slots correctly.

### "Too many combinations!"

Set `matrix.limit` to a reasonable number (default: 8).

Or switch `matrix.mode` to `"rotate"` - this picks ONE combo per prompt instead of all.

## Technical Details

### Config Structure

The matrix config now has:
```json
{
  "matrix": {
    "enabled": true,
    "mode": "fanout",
    "limit": 8,
    "base_prompt": "Optional separate base prompt",
    "slots": [
      {"name": "slot1", "values": ["opt1", "opt2"]},
      {"name": "slot2", "values": ["opt3", "opt4"]}
    ],
    "raw_text": "slot1: opt1 | opt2\nslot2: opt3 | opt4"
  }
}
```

`base_prompt` is **new** but optional - for users who want to separate the base prompt from slot definitions.

### Code Changes

**Files Modified:**
- `src/gui/main_window.py`:
  - Added matrix UI widgets (base prompt, slot rows, canvas, scrollbar)
  - `_add_matrix_slot_row()`, `_remove_matrix_slot_row()`, `_clear_matrix_slot_rows()`
  - `_toggle_matrix_legacy_view()`, `_sync_matrix_ui_to_text()`, `_sync_matrix_text_to_ui()`
  - Updated `_collect_randomization_config()` to read from UI fields
  - Updated `_load_randomization_config()` to populate UI fields

**Tests Added:**
- `tests/gui/test_matrix_ui.py`: Unit tests for add/remove/load/save operations

**Backward Compatibility:**
- Old presets load correctly (slots parsed from raw_text)
- Old `raw_text` format still saved for users who manually edit JSON
- Legacy text editor available via checkbox

## Next Steps

1. **Test the example preset** - verify you see randomization logs
2. **Create your own matrix** - use the new UI to build slot combinations
3. **Experiment with modes** - try fanout vs rotate to see the difference
4. **Combine features** - use S/R + wildcards + matrix together for maximum variety

## Notes

- The **variant system** (model matrix, hypernetworks) is **separate** from randomization
- Randomization expands prompts **before** the pipeline runs
- Variant system switches models **between** pipeline runs
- Both can be used together for even more combinations!

---

**Questions?** Check `RANDOMIZATION_EXAMPLE_README.md` for detailed usage guide.
