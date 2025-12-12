# PR-8: Preview Payload & Validate Implementation Details

**Date:** November 12, 2025
**Author:** GitHub Copilot
**Scope:** `src/gui/main_window.py`

## Overview

Implemented the "Preview Payload & Validate (Dry Run)" feature to give users confidence in prompt assembly before executing full pipelines. This prevents wasted time on runs with malformed prompts or misconfigured randomizers.

## What Was Changed

### 1. Effective Config Resolver (`_effective_cfg_for_pack`)

Added a centralized method to determine the active configuration for a pack based on the current `ConfigContext.source`:

- **GLOBAL_LOCK**: Uses `ctx.locked_cfg` if set
- **PRESET**: Uses `ctx.editor_cfg`
- **PACK**: Loads pack-specific config, falls back to `ctx.editor_cfg` defaults

This ensures preview uses the same config resolution as actual runs.

### 2. Preview Handler (`_ui_preview_payload`)

- Validates pack selection before proceeding
- Runs preview assembly in background thread to avoid UI blocking
- Marshals results back to main thread for display
- Shows user-friendly error dialogs for failures

### 3. Pack Preview Logic (`_preview_pack_payload`)

For each selected pack:
- Reads pack data using `read_prompt_pack()`
- Extracts prompt text
- Creates `PromptRandomizer` with effective config
- Generates up to 3 prompt variants for preview
- Runs diagnostics checks

### 4. Diagnostics Engine (`_check_prompt_diagnostics`)

Comprehensive validation of prompts and randomizer config:

**Unresolved Tokens**: Detects `[[slot]]` patterns without rules
**S/R Rules**: Validates search/replacement pairs exist
**Wildcards**: Checks token definitions have values
**Matrix Slots**: Identifies empty slots, counts total combinations

### 5. Result Formatting (`_format_preview_results`)

Structures output as:
```
=== Payload Preview (Dry Run) ===

Pack: example_pack
  Total variants: 24
  Preview variants:
    1. A beautiful landscape with mountains
    2. A beautiful landscape with forests
    3. A beautiful landscape with rivers
  Diagnostics:
    ⚠️ Matrix will generate 24 combinations
```

### 6. UI Integration

- Added "Preview Payload (Dry Run)" button to action bar
- Results displayed in modal dialog (temporary; designed for future panel integration)
- Button positioned after "Apply Editor → Pack(s)" for logical workflow

## Why These Changes

### Problem Solved
Users could spend significant time waiting for pipeline runs only to discover issues like:
- Unresolved `[[tokens]]` causing literal text in prompts
- Empty randomizer slots producing identical outputs
- Matrix configurations generating unexpected combination counts
- Typos in S/R rules or wildcard definitions

### Design Decisions

**Dry-Run Only**: No SD WebUI API calls to keep it fast and network-independent. Uses existing `PromptRandomizer` logic for accuracy.

**Limited Variants**: Shows 3 variants maximum to avoid overwhelming output while demonstrating randomization.

**Thread-Safe**: All heavy computation in background threads with proper Tkinter marshaling.

**Config Consistency**: Reuses exact same config resolution as `Pipeline.run()` to ensure preview matches actual execution.

**Diagnostic Focus**: Prioritizes actionable warnings over exhaustive validation, focusing on common mistakes.

### Technical Implementation Notes

- **Imports**: Leverages existing `PromptRandomizer`, `read_prompt_pack` utilities
- **Error Handling**: Comprehensive exception catching with user-friendly messages
- **Performance**: Background threading prevents UI freeze during complex matrix calculations
- **Extensibility**: Modular design allows easy addition of new diagnostic checks

## Testing

### Manual Test Case
1. Create pack with `[[unresolved_slot]]` in prompt
2. Enable randomizer with empty matrix slot
3. Click "Preview Payload (Dry Run)"
4. Verify warnings appear for both issues
5. Confirm no SD WebUI calls made (check logs)

### Integration Points
- Works with all config sources (PACK, PRESET, GLOBAL_LOCK)
- Compatible with existing pack selection system
- No interference with actual pipeline execution

## Future Enhancements

- **Dedicated Preview Panel**: Replace modal dialog with scrollable text area below editor
- **Dry-Run Checkbox**: Optional toggle next to Run button to preview before execution
- **Advanced Diagnostics**: Syntax validation, token dependency analysis
- **Export Preview**: Save preview results to file for debugging

## Risk Assessment

**Low Risk**: Pure addition with no changes to existing execution paths. All new code is defensive and thread-safe. Rollback simply removes the button and methods.</content>
<parameter name="filePath">c:\Users\rober\projects\StableNew\docs\PR8_PREVIEW_PAYLOAD_IMPLEMENTATION.md
