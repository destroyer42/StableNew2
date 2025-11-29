# PR-GUI-V2-LEARNING-3K: Batch Analytics & Scoring Curves (2025-11-26_0141)

## Summary
Implements **Batch Analytics & Scoring Curves** for the Learning Module.  
This PR adds visual and numerical tools to evaluate experiment results at scale.

### Reference Design  
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

---

## Problem
Users need insights beyond single ratings:
- How does CFG affect quality?
- Which sampler performs most consistently?
- Is there a performance plateau?

The system requires aggregated analysis.

---

## Goals
- Add analytics layer producing:
  - scoring curves
  - box plots (textual representation)
  - variance tables
  - summary statistics per parameter value
- Integrate analytics into LearningReviewPanel analytics tab

---

## Non‑Goals
- No graphical plotting libraries.
- No PDF output.
- No external data science libraries.

---

## Implementation Tasks

### 1. Create `learning_analytics.py`
Implement functions:
- compute_curve(records, parameter)
- compute_descriptive_stats(records)
- compute_value_distribution(records)
- generate_textual_chart(records)

Return simple data structures usable in GUI.

### 2. Integrate with LearningController
Add:
- get_analytics_for_experiment()
- get_scoring_curve()

### 3. UI Updates (LearningReviewPanel)
Add **Analytics Section**:
- “Curve View”: multi‑value sorted listing
- “Stats View”: mean, median, stddev
- “Variance Table”

Switch via buttons or tabs.

### 4. Performance
- Cache analytics results
- Recompute only when plan or ratings change

---

## Tests
- Analytics output correct for synthetic datasets.
- Edge cases:
  - Zero ratings
  - Single rating
  - High variance
- Controller wiring correct.

---

## Acceptance Criteria
- Analytics shown correctly in UI.
- Updates after learning runs complete.
- No GUI lockups.

---

## Rollback
Remove analytics file and controller/GUI integration.
