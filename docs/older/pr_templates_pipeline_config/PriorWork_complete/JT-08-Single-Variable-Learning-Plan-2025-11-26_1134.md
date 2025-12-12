
# JT-08 — Single-Variable Learning Plan (Journey Test Specification)
### Version: 2025-11-26_1134
### StableNewV2 — High-Fidelity Journey Test

## 1. Summary
Validates the complete Learning tab workflow for single-parameter experiments, ensuring proper experiment definition, plan generation, automated execution, manual rating collection, and reliable persistence of LearningRecord JSONL entries for machine learning optimization.

## 2. Problem
Learning experiments must be reliable and reproducible. Poor experiment definition, execution failures, or rating data loss can corrupt the learning dataset and compromise model training. Single-variable experiments establish the baseline for more complex multi-variable learning scenarios.

- Build experiment (e.g., CFG sweep)
- Generate plan variants
- Execute variants
- Rate outputs
- Persist LearningRecordWriter JSONL entries

## 3. Preconditions

- Pipeline baseline selected
- Learning tab implemented PR‑3A→3F

## 4. Steps

1. Go to Learning tab
2. “Use current pipeline config”
3. Select stage: txt2img
4. Variable under test: CFG
5. Values: 4, 7, 11
6. Build plan
7. Run plan
8. Rate images
9. Confirm records saved

## 5. Acceptance Criteria

- Plan table correct
- Images generated per variant
- Ratings persisted reliably

## 6. Goals

- Validate single-variable experiment workflow end-to-end
- Ensure LearningRecord JSONL persistence is reliable
- Confirm rating collection and storage mechanisms
- Establish baseline for multi-variable experiments

## 7. Non-Goals

- Multi-variable experiments (covered in JT-09)
- Learning algorithm validation
- Statistical analysis of results
- Model training optimization

## 8. Expected Artifacts

### Learning Records

- `data/job_history.jsonl` entries for each experiment variant
- Structured JSONL format with experiment metadata
- Rating data properly embedded in records

### Generated Images

- Output images for each CFG variant (4, 7, 11)
- Proper file naming with experiment identifiers
- Images stored in timestamped run directories

### Plan Manifest

- Experiment plan table with all variants
- Parameter sweep configuration
- Execution status tracking

## 9. Edge Cases

### Execution Failures

- Network timeout during image generation
- Invalid CFG values causing pipeline errors
- Disk space exhaustion during batch execution

### Rating Collection Issues

- User cancels rating dialog mid-experiment
- Rating scale validation (must be 1-5)
- Concurrent rating sessions

### Data Persistence Problems

- JSONL file corruption during writes
- Permission denied on data directory
- Race conditions in LearningRecordWriter

## 10. Rollback Plan

### Data Recovery

- Backup `data/job_history.jsonl` before test
- Restore from backup if corruption detected
- Verify JSONL integrity with validation script

### State Cleanup

- Remove test-generated image directories
- Clear experiment plan tables
- Reset Learning tab to clean state

### System Restoration

- Restart application if needed
- Clear WebUI cache if rating dialogs fail
- Verify pipeline baseline remains intact
