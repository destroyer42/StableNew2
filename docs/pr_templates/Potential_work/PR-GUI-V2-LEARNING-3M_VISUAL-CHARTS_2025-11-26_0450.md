# PR-GUI-V2-LEARNING-3M_VISUAL-CHARTS (2025-11-26_0450)

## Summary
Implements **Visual Charts & Comparative Views** for Learning Tab analytics using ASCII/text-rendered curves, radar-style summaries, distribution bars, and ranked tables.  
Extends PR‑3K analytics into a visual interpretability layer usable by end users.

### Reference Design
`C:\Users\rob\projects\StableNew\docs\pr_templates\PR-GUI-V2-LEARNING-TAB-003.md`

## Problem
Analytics from PR‑3K are numeric only. Without visualization, users cannot see:
- Performance trends
- Variance patterns
- Curve shapes
- Plateaus or optimal ranges

## Goals
- Add ASCII‑based curve rendering (line plots, area blocks, bars)
- Add ranking and variance visual summaries
- Add “Charts” tab to LearningReviewPanel
- Integrate with analytics engine

## Non-Goals
- Real graphical plots (matplotlib, seaborn)
- PDF exports
- Multi-dimensional charts (PR‑3Q)

## Implementation Tasks
1. Add `visual_charts.py`
2. Implement:
   - ascii_line_plot(values)
   - ascii_distribution(counts)
   - ascii_ranking_table(items)
3. Integrate via LearningController:
   - get_visual_charts_for_experiment()
4. Add UI “Charts” section to LearningReviewPanel
5. Add caching to avoid re-rendering every update

## Tests
- Render curves for synthetic datasets
- Verify alignment in monospace fonts
- Stress test long parameter lists

## Acceptance Criteria
- Charts visible in LearningReviewPanel
- Updates on rating/analytics refresh
