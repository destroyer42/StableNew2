# PR-GUI-V2-LEARNING-3J: Automated Parameter Recommendation Engine (2025-11-26_0141)

## Summary
Implements the **Automated Parameter Recommendation Engine (APRE)**.  
This PR adds logic for analyzing historical LearningRecordWriter data, building parameter‑performance models, and generating recommended settings for any prompt + stage + workflow.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

---

## Problem
The Learning Module can now run experiments (PR‑3D–3F) and produce ratings (PR‑3H), but nothing uses that data. The system lacks the ability to derive recommendations, detect trends, or suggest optimized settings.

---

## Goals
- Create a standalone Recommendations Engine module.
- Train/update statistical models from jsonl learning logs.
- Provide a controller API:
  - get_recommendations(prompt, stage)
- Display recommendations in the LearningReviewPanel sidebar.
- Update automatically when new ratings are added.

---

## Non‑Goals
- No machine‑learning libraries (pure Python + statistics).
- No real-time graphing (future PR‑3M).
- No influence over Pipeline defaults yet.

---

## Implementation Tasks

### 1. Create `recommendation_engine.py`
Contains:
- RecommendationEngine class
- Methods:
  - load_history(path)
  - score_records(records)
  - compute_optimal_settings(records, stage)
  - find_trends_across_variables(records)
  - recommend(prompt_text, stage)

Data model:
- Use mean rating per parameter value.
- Weight recent runs slightly higher.
- Compute:
  - best sampler
  - best scheduler
  - optimal cfg
  - optimal steps
  - optimal LoRA strength(s)

### 2. Integrate with LearningController
Add methods:
- update_recommendations()
- get_best_settings_for_active_prompt()

Trigger updates when:
- A rating is added
- A completed job is processed
- User selects “Refresh Recommendations”

### 3. UI Integration (LearningReviewPanel)
Add:
- “Recommended Settings” box
- Content updates when new data is available
- Include:
  - Parameter name
  - Recommended value
  - Confidence score

### 4. Caching & Performance
- Cache parsed history in memory
- Reload only on file change timestamps

---

## Tests
- Feed synthetic records and verify optimal settings chosen correctly.
- Test for multiple parameter types (numeric & discrete).
- Test recommendations across multiple stages.

---

## Acceptance Criteria
- LearningReviewPanel shows recommendations.
- Recommendations update when new ratings appear.
- No GUI freezes.

---

## Rollback
Delete recommendation_engine.py and remove controller + UI references.
