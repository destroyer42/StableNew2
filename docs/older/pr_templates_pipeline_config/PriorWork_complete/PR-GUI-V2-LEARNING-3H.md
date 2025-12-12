# PR-GUI-V2-LEARNING-3H: Rating & Review Integration (2025-11-26_0124)

## Summary
Implements the Learning Review Panel rating workflow, enabling the user to view finished variant results and submit 1–5 ratings stored via LearningRecordWriter.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
Completed variant outputs appear in the preview panel but there is no structured rating workflow.

## Goals
- Add rating controls (1–5 stars or buttons)
- Display image + metadata
- Store ratings to jsonl using LearningRecordWriter
- Integrate with LearningController.record_rating()

## Implementation Tasks
1. Enhance LearningReviewPanel
   - Image display
   - Metadata block
   - Rating controls: five buttons or star widgets

2. Implement LearningRecordWriter usage
   - Append jsonl entries:
     - prompt
     - stage
     - variable under test
     - value
     - seed
     - cfg/steps/etc.
     - user_rating

3. Connect table → review panel
   - Clicking a row loads the variant result

4. Wire controller
   - record_rating triggers write to LearningRecordWriter
   - UI gives “Rating saved” feedback

## Acceptance Criteria
- User can click a variant, view it, and rate it
- Ratings written correctly to jsonl
- No interference with Pipeline or Prompt tabs
