
# JT-10 — Ratings and Learning Review (Journey Test Specification)
### Version: 2025-11-26_1136
### StableNewV2 — High-Fidelity Journey Test

## 1. Summary
Validates the complete ratings and review workflow for learning experiments, ensuring proper variant navigation, rating modification capabilities, reviewer note management, JSONL persistence integrity, and data consistency across application sessions for reliable machine learning dataset curation.

## 2. Problem
Learning data quality depends on accurate and consistent rating workflows. Rating inconsistencies, JSONL corruption, or navigation failures can compromise the entire learning dataset. Review workflows must support iterative refinement while maintaining data integrity and preventing accidental data loss.

- Navigate variants/images
- Edit ratings multiple times
- Verify JSONL mutation works correctly
- Confirm consistency after reload

## 3. Preconditions

- Completed experiment (JT‑08 or JT‑09)

## 4. Steps

1. Open Learning tab → Review panel
2. Navigate through variants
3. Change ratings on multiple images
4. Add reviewer notes
5. Reopen experiment → confirm persistence

## 5. Acceptance Criteria

- Ratings persist across reload
- No duplicated or corrupted JSONL entries

## 6. Non-Goals

- Experiment creation or execution
- Statistical analysis of ratings
- Automated rating suggestions
- Bulk rating operations

## 7. Expected Artifacts

### Updated Learning Records

- Modified `data/job_history.jsonl` entries with updated ratings
- Preserved experiment metadata and parameter combinations
- Reviewer notes appended to appropriate records

### Review Session Logs

- Navigation history and rating change timestamps
- User interaction patterns for review workflow
- Session persistence markers

### Rating Consistency Validation

- Before/after rating comparisons
- JSONL integrity verification
- Cross-session data consistency checks

## 8. Edge Cases

### Rating Modification Issues

- Rapid successive rating changes before persistence
- Rating values outside valid range (1-5)
- Concurrent rating modifications from multiple sessions

### Navigation Problems

- Large experiment sets causing UI lag
- Missing or corrupted image files during review
- Navigation state loss during application restart

### Data Persistence Failures

- JSONL file write failures during rating updates
- Partial record updates leaving inconsistent state
- File system permissions preventing saves

### Session Management

- Application crashes during review workflow
- Browser tab closure without proper cleanup
- Network interruptions during rating saves

## 9. Rollback Plan

### Rating Recovery

- Backup `data/job_history.jsonl` before review session
- Restore from backup if rating modifications cause corruption
- Validate JSONL structure and rating integrity

### Session State Recovery

- Clear review navigation state and return to experiment list
- Reset any cached rating modifications
- Reinitialize review workflow from clean state

### Data Consistency Restoration

- Run JSONL validation and repair scripts
- Cross-reference ratings with original experiment data
- Remove orphaned or inconsistent rating entries

### Application State Reset

- Restart application to clear any corrupted UI state
- Clear WebUI cache if review dialogs become unresponsive
- Verify Learning tab returns to baseline functionality
