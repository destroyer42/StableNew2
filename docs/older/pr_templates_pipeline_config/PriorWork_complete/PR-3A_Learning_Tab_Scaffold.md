# PR‑3A — Add Learning Tab Scaffold

### Goal
Introduce the new **Learning** tab in the Notebook (full‑width post‑PR‑00).  
This PR adds only the structural tab — no logic or UI beyond a placeholder frame.

### Changes
- Add a new tab labeled **Learning** in `MainWindowV2`.
- Create `LearningTabFrame` with a simple placeholder label.
- Ensure tab order becomes: **Prompt | Pipeline | Learning**.
- No controllers, no state, no actions.

### Deliverables
- Learning tab appears in the Notebook.
- No functional impact on Prompt or Pipeline.
