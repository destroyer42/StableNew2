
# JT-11 — Presets and Styles (Journey Test Specification)
### Version: 2025-11-26_1136
### StableNewV2 — High-Fidelity Journey Test

## 1. Summary
Validates the complete presets and styles workflow, ensuring proper creation, saving, loading, and application of reusable configuration templates that capture complete pipeline states, prompt configurations, LoRA settings, and metadata for consistent image generation workflows across sessions.

## 2. Problem
Configuration consistency is critical for reproducible results. Preset corruption, incomplete saves, or loading failures can lead to inconsistent outputs and wasted user time. Style management must handle complex parameter combinations while maintaining data integrity and providing reliable restoration across application sessions.

- Save pipeline + prompt as a Style
- Reload Style in new session
- Confirm UI fields and metadata restore exactly

## 3. Preconditions

- Preset/Style system implemented

## 4. Steps

1. Configure prompt + pipeline
2. Save Style
3. Restart application
4. Load Style
5. Verify:
   - prompt text
   - sampler/scheduler
   - LoRAs
   - upscale settings

## 5. Acceptance Criteria

- 100% fidelity on reload

## 6. Non-Goals

- Preset sharing or export/import
- Style versioning or history
- Automated style recommendations
- Bulk preset operations

## 7. Expected Artifacts

### Style Configuration Files

- JSON preset files in `presets/` directory
- Complete parameter serialization including prompts, pipeline settings, and metadata
- Timestamped and named style files

### Loaded Configuration State

- UI fields populated with exact saved values
- Pipeline parameters restored to saved configuration
- Prompt text and LoRA settings applied correctly

### Style Management Interface

- Style list displaying saved configurations
- Load/delete operations functional
- Style metadata display (creation date, description)

## 8. Edge Cases

### Configuration Corruption

- Partial saves leaving incomplete preset files
- JSON corruption during serialization/deserialization
- File system permissions preventing saves or loads

### Parameter Compatibility

- Loading presets with deprecated or missing parameters
- Version mismatches between saved and current configurations
- Invalid parameter values in saved configurations

### UI State Management

- Loading presets while pipeline is running
- Concurrent preset operations from multiple tabs
- UI field conflicts during preset application

### File System Issues

- Preset directory missing or inaccessible
- File name conflicts during saves
- Disk space exhaustion during serialization

## 9. Rollback Plan

### Configuration Recovery

- Backup `presets/` directory before modifications
- Restore from backup if preset corruption occurs
- Validate JSON integrity of saved configurations

### State Cleanup

- Clear loaded preset state and return to default configuration
- Remove any partially saved preset files
- Reset UI fields to baseline values

### File System Restoration

- Recreate missing `presets/` directory structure
- Clean up orphaned or corrupted preset files
- Restore proper file permissions

### Application State Reset

- Restart application to clear any corrupted preset state
- Clear WebUI cache if preset loading becomes unresponsive
- Verify preset system returns to functional state
