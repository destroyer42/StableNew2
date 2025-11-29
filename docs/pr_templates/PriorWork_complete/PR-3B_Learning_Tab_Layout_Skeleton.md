# PR‑3B — Learning Tab Layout Skeleton  
### Header + Three‑Column Workspace Scaffolding

### Goal
Replace the placeholder Learning tab with its internal structural layout:
- A header at the top
- A three‑column body (Design / Plan Table / Review)
- No logic or data binding yet

### Layout Structure
Inside `LearningTabFrame`:

1. **LearningHeader**  
   Placeholder label only.

2. **LearningBodyFrame** — Three Columns  
   - **Left:** `ExperimentDesignPanel` (placeholder)  
   - **Center:** `LearningPlanTable` (placeholder)  
   - **Right:** `LearningReviewPanel` (placeholder)

### Changes
- Create view classes:
  - `experiment_design_panel.py`
  - `learning_plan_table.py`
  - `learning_review_panel.py`
- Add placeholder UI in each panel.
- Integrate panels into LearningBodyFrame.

### Deliverables
- Full-width 3‑column Learning workspace scaffold.
- No behavior or state wiring.
