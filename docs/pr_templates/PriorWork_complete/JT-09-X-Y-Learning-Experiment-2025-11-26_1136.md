
# JT-09 — X/Y Two-Variable Learning Experiment (Journey Test Specification)
### Version: 2025-11-26_1136
### StableNewV2 — High-Fidelity Journey Test

## 1. Summary
Validates the complete X/Y two-variable learning experiment workflow, ensuring proper Cartesian grid generation, parallel execution of parameter combinations, ASCII heatmap visualization, comprehensive rating collection across all variants, and reliable persistence of multi-dimensional LearningRecord JSONL entries for advanced machine learning optimization.

## 2. Problem
Multi-variable learning experiments require careful orchestration of parameter combinations. Incorrect grid generation, execution failures, or visualization errors can lead to incomplete datasets and unreliable optimization results. X/Y experiments build upon single-variable baselines but introduce complexity in grid management, heatmap rendering, and multi-dimensional data analysis.

- Define X and Y parameters
- Generate Cartesian grid of variants
- Execute all variants
- Display ASCII heatmap
- Persist all learning records

## 3. Preconditions

- PR‑3Q and PR‑3R implemented
- LearningState supports X/Y mode

## 4. Steps

1. Choose baseline pipeline config
2. Open Learning tab → select X/Y mode
3. X param: CFG → values 4, 8
4. Y param: Steps → values 16, 32
5. Build plan → expect 4 variants
6. Run plan
7. Review heatmap
8. Rate images
9. Validate records saved

## 5. Acceptance Criteria

- Correct grid generation
- Heatmap displays aligned
- Ratings stored for all variants

## 6. Non-Goals

- Three or more variable experiments
- Advanced statistical analysis
- Automated parameter optimization
- Machine learning model training

## 7. Expected Artifacts

### Learning Records

- `data/job_history.jsonl` entries for all grid combinations
- Multi-dimensional parameter metadata in JSONL format
- Rating data for each X/Y coordinate

### Generated Images

- Images for each parameter combination (e.g., 4×4 = 16 images)
- Systematic file naming with X/Y parameter values
- Organized in timestamped experiment directories

### Heatmap Visualization

- ASCII heatmap display in Learning tab
- Color-coded rating visualization
- Parameter axis labels and legends

### Experiment Manifest

- Complete X/Y grid specification
- Execution status for all variants
- Performance metrics and timing data

## 8. Edge Cases

### Grid Generation Issues

- Invalid parameter combinations causing pipeline errors
- Memory exhaustion with large grids (e.g., 10×10 = 100 variants)
- Parameter value conflicts or constraints

### Execution Failures

- Partial grid completion with some variants failing
- Network timeouts during batch execution
- Resource contention between parallel variants

### Visualization Problems

- Heatmap rendering failures with extreme rating values
- Display corruption with non-standard terminal sizes
- Color scheme issues in different environments

### Rating Collection Challenges

- Incomplete rating coverage across grid
- Rating dialog timeouts during large experiments
- Concurrent user interactions during rating phase

## 9. Rollback Plan

### Data Recovery

- Backup `data/job_history.jsonl` before grid execution
- Incremental backup after each rating batch
- Restore from backup if JSONL corruption detected

### State Cleanup

- Remove experiment image directories and subdirectories
- Clear X/Y grid tables and heatmap displays
- Reset Learning tab to baseline state

### Partial Execution Recovery

- Resume incomplete grids from last successful variant
- Re-execute failed combinations individually
- Merge partial results with existing ratings

### System Restoration

- Clear WebUI cache if rating dialogs become unresponsive
- Restart application if memory leaks detected
- Verify pipeline configuration remains intact
