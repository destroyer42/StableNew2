# JSON Unification - Fix for Pack/Config Collision

## Problem
When a prompt pack was created, it generated a JSON file (`packs/<name>.json`) with matrix information. When you applied a pipeline config to that pack, it would write to the same file, overwriting the matrix data and causing data loss.

## Root Cause
Two independent systems writing to the same file:

1. **PromptPackModel** (Prompt Tab): Saved `name`, `slots`, `matrix` to `packs/<name>.json`
2. **ConfigManager** (Pipeline Tab): Saved `pipeline`, `txt2img`, `img2img`, etc. to `packs/<name>.json`

Last writer wins = data loss for the other system.

## Solution: Unified JSON Format

Both data structures now coexist in a single JSON file with two top-level sections:

### New Unified Structure
```json
{
  "pack_data": {
    "name": "mypack",
    "slots": [...],
    "matrix": {
      "enabled": true,
      "mode": "fanout",
      "limit": 8,
      "slots": [...]
    }
  },
  "preset_data": {
    "pipeline": {...},
    "txt2img": {...},
    "img2img": {...},
    "refiner": {...},
    "hires": {...},
    "upscale": {...},
    "adetailer": {...}
  }
}
```

## Implementation Changes

### 1. PromptPackModel (src/gui/models/prompt_pack_model.py)

**Added:**
- `preset_data` field to dataclass to store pipeline config
- Unified JSON save: wraps pack data in `pack_data` section, preserves existing `preset_data`
- Unified JSON load: reads from `pack_data` section, loads `preset_data` if present
- Backward compatibility: handles legacy formats (direct fields at root)

**save_to_file():**
- Builds `pack_data` section with name, slots, matrix
- Preserves existing `preset_data` (doesn't overwrite pipeline config)
- Writes unified structure with both sections

**load_from_file():**
- Detects unified format (`pack_data` present) vs legacy format
- Extracts pack data from appropriate section
- Loads `preset_data` into `pack.preset_data` field

### 2. ConfigManager (src/utils/config.py)

**get_pack_config():**
- Reads JSON file
- Extracts config from `preset_data` section if unified format
- Falls back to root-level fields for legacy format
- Distinguishes between pack data files and config files

**save_pack_config():**
- Loads existing JSON first (read-modify-write)
- Preserves `pack_data` section (doesn't overwrite matrix)
- Updates only `preset_data` section with new pipeline config
- Converts legacy formats to unified on first save

## Migration

**migrate_pack_json.py** script:
- Scans `packs/*.json` files
- Detects legacy format (fields at root level)
- Wraps in appropriate section (`pack_data` or `preset_data`)
- Creates `.json.bak` backup before migrating
- Handles edge cases (corrupted files with both types mixed)

**To migrate existing packs:**
```bash
python migrate_pack_json.py
```

## Testing

**test_json_unification.py** verifies:
1. Save prompt pack with matrix → writes `pack_data`
2. Apply pipeline config → writes `preset_data`, preserves `pack_data`
3. Reload pack → matrix data intact
4. Load config → pipeline data intact
5. Round-trip: no data loss when alternating saves

**Test result:** ✓ ALL TESTS PASSED

## Backward Compatibility

Both systems handle legacy formats gracefully:

- **Legacy pack file** (name, slots, matrix at root):
  - Load: reads from root
  - Save: wraps in `pack_data`, creates empty `preset_data`

- **Legacy config file** (pipeline, txt2img at root):
  - Load: reads from root
  - Save: wraps in `preset_data`, creates minimal `pack_data`

- **Unified format**: both systems read/write their sections without touching the other

## Benefits

✅ **No data loss**: Matrix and pipeline configs coexist safely  
✅ **Single file**: Simpler file structure (no separate config files)  
✅ **Atomic updates**: Each system updates only its section  
✅ **Backward compatible**: Handles all legacy formats  
✅ **Future-proof**: Easy to add more sections (e.g., learning data, usage stats)

## Files Changed

- `src/gui/models/prompt_pack_model.py` - Unified save/load
- `src/utils/config.py` - Section-aware config management
- `test_json_unification.py` - Integration test
- `migrate_pack_json.py` - Migration utility

## User Impact

Users can now safely:
1. Edit prompt pack matrix in Prompt Tab → Save
2. Switch to Pipeline Tab → Apply config → Apply
3. Return to Prompt Tab → Matrix data is preserved ✓
4. Switch back to Pipeline Tab → Config is preserved ✓

No more accidental data loss when working across tabs!
