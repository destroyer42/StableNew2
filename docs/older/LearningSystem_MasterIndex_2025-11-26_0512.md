# StableNewV2 Learning System — Master Index & Roadmap (2025-11-26_0512)

# StableNewV2 Learning System — Master Index & Roadmap
### Comprehensive Reference for PR‑3A through PR‑3R

This document provides a **single, authoritative index** for the entire Learning Module development series.  
It connects every PR, subsystem, UI element, and workflow into a structured, coherent roadmap.

---

# 1. High‑Level System Overview

The Learning Module is designed to:
- Run controlled parameter experiments
- Capture results & ratings
- Analyze trends
- Generate recommendations
- Auto-tune pipeline settings
- Potentially refine itself adaptively

It operates alongside the Prompt and Pipeline tabs but remains fully modular.

---

# 2. Architecture Layers

## 2.1 UI Layer (Tabs, Panels, Views)
- ExperimentDesignPanel
- LearningPlanTable
- LearningReviewPanel
- Charts View
- Analytics View
- X/Y Heatmap View

## 2.2 Controller Layer
- LearningController
  - update_experiment_design
  - build_plan
  - run_plan
  - record_rating
  - update_recommendations
  - get_visual_charts
  - get_xy_heatmap
  - auto‑tuning pipeline integration (PR‑3O)

## 2.3 State Layer
- LearningState
  - current_experiment
  - plan
  - variants
  - adaptive learning history
  - caching layer (PR‑3N)

## 2.4 Data Layer
- jsonl LearningRecordWriter
- analytics engine
- recommendation engine
- visual chart engine
- persistence/session store

---

# 3. Complete PR Roadmap

## Phase 1 — Tab, Layout, & State (PR‑3A through PR‑3C)
- **PR‑3A** — Learning Tab Scaffold  
- **PR‑3B** — Three-column layout  
- **PR‑3C** — LearningState + LearningController skeleton  

---

## Phase 2 — Core Features (PR‑3D through PR‑3F)
- **PR‑3D** — ExperimentDesignPanel full UI  
- **PR‑3E** — Build Learning Plan  
- **PR‑3F** — Run Learning Plan  

Workflow after Phase 2:
1. User defines experiment  
2. System builds plan  
3. System runs plan  

---

## Phase 3 — Review & Ratings (PR‑3G through PR‑3H)
- **PR‑3G** — Live Variant Status Table updates  
- **PR‑3H** — Rating & Review integration  

After Phase 3:
- User reviews images  
- Rates variants  
- Generates record data  

---

## Phase 4 — Analytics, Models, & Optimization (PR‑3J through PR‑3L)
- **PR‑3J** — Recommendation Engine  
- **PR‑3K** — Analytics Engine (scoring curves, stats)  
- **PR‑3L** — Adaptive Learning Loop  

After Phase 4:
- Recommendations update automatically  
- Analytics summarize trends  
- System can refine itself  

---

## Phase 5 — Visualizations & Persistence (PR‑3M through PR‑3N)
- **PR‑3M** — Visual ASCII Charts  
- **PR‑3N** — Session Persistence & Caching  

Adds durability and visual interpretability.

---

## Phase 6 — Pipeline Integration & Documentation (PR‑3O through PR‑3P)
- **PR‑3O** — Pipeline Auto‑Tuning Integration  
- **PR‑3P** — Complete Documentation Bundle  

Connects the Learning Module back to the core system.

---

## Phase 7 — X/Y Experiments (PR‑3Q through PR‑3R)
- **PR‑3Q** — Two‑Variable Sweeping Engine  
- **PR‑3R** — X/Y UX Refinements  

Enables multi-parameter interaction studies.

---

# 4. End‑to‑End Learning Workflow Summary

1. **Design Experiment**  
   - Select stage  
   - Choose variable(s)  
   - Ranges or discrete values  

2. **Build Plan**  
   - System builds variants  
   - X or X/Y grid  

3. **Run Plan**  
   - Pipeline executes each variant  
   - Results stored  

4. **Review Results**  
   - Visual previews  
   - Metadata listing  

5. **Rate Outputs**  
   - JSONL entries created  

6. **Analyze Trends**  
   - Curves  
   - Stats  
   - Variance  
   - Heatmaps  

7. **Get Recommendations**  
   - Best sampler, scheduler, CFG, steps, LoRA strength  

8. **Auto‑Tune Pipeline**  
   - Pipeline settings updated  

9. **Adaptive Loop (Optional)**  
   - System refines range  
   - Repeats as needed  

---

# 5. File Map

### UI
- `learning_tab_frame.py`
- `experiment_design_panel.py`
- `learning_plan_table.py`
- `learning_review_panel.py`

### Controllers
- `learning_controller.py`

### State
- `learning_state.py`

### Analytics
- `learning_analytics.py`
- `visual_charts.py`
- `recommendation_engine.py`

### Persistence
- `learning_session_store.py`
- `learning_record_writer.py` (existing)

---

# 6. Future Extensions

- PR‑3S: Full statistical regression and modeling  
- PR‑3T: Bayesian optimization layer  
- PR‑3U: Neural preference modeling  
- PR‑3V: GPU-accelerated analytics backend  
- PR‑3W: Auto-scheduler per‑prompt regimes  

---

# 7. Conclusion

This index defines the entire Learning System architecture and roadmap from PR‑3A through PR‑3R, covering UI, logic, analytics, recommendation, and experimentation subsystems.  
It serves as the top-level reference for developers and future maintainers.

