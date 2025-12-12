# CLASSIFY-FUTURE-SUBSYSTEMS-003_V2-P1 — Mark Learning / Queue / Cluster / AI / GUI Adapters as Phase 3+

**Snapshot Baseline:** `StableNew-snapshot-20251128-144410.zip`  
**Inventory Baseline:** `docs/StableNew_V2_Inventory_V2-P1.md` + `repo_inventory.json`

> Phase-1 Objective Alignment:  
> - “Phase 1 = stabilize GUI V2 + pipeline payloads.”  
> - “Learning, randomizer, queue/cluster are later phases; don’t let half-wired systems destabilize Phase 1.”

This PR **does not delete any code**. Instead, it:

- **Formally classifies** the learning, queue, cluster, AI settings, GUI adapter stack, and certain utils as **Phase 3+ / future subsystems**.
- Adds **lightweight header comments** to those modules.
- Updates **inventory/roadmap docs** so humans and tools (Codex, Copilot, LLMs) know these pieces are **not required to work in Phase 1**.

---

## 1. Goal & Scope

### Goal

- Make it explicit which modules are **Phase-1 critical** vs. **Phase-3+ future systems**.
- Reduce confusion and “false failures” by clearly labeling subsystems that are:
  - Not wired to the current V2 GUI.
  - Allowed to be broken / incomplete during Phase 1.

### In Scope

- Code modules for:
  - Learning
  - Queue / job system
  - Cluster
  - AI settings generator
  - GUI adapter stack (`src/gui_v2/*`)
  - Selected GUI V2 “extras”
  - Selected utils used only by those subsystems
- Documentation:
  - `docs/StableNew_V2_Inventory_V2-P1.md`
  - `docs/Future_Learning_Roadmap_*`
  - `docs/Cluster_Compute_Vision_v2.md` (for references only, optional mention)

### Out of Scope

- Any change to runtime behavior or imports.
- Any test moves (covered by `CLEANUP-GUI-TEST-QUARANTINE-002`).
- GUI V1 archival (covered by `CLEANUP-GUI-V1-ARCHIVE-001`).

---

## 2. Code Modules to Mark as “Phase 3+ / Future Subsystem”

For each module in the lists below, **add a small header comment or docstring** at the top of the file:

```python
# Phase 3+ subsystem:
# This module is not wired into the Phase 1 GUI/pipeline.
# It will be activated and refactored in later phases (learning/randomizer/queue/cluster).
```

or, when more specific:

```python
# Phase 3+ Learning subsystem:
# Not required for Phase 1 stability; used by future learning workflows only.
```

No behavior changes; no imports added/removed.

### 2.1 Learning Subsystem (Phase 3)

Under `src/learning/`:

- `src/learning/dataset_builder.py`
- `src/learning/feedback_manager.py`
- `src/learning/learning_adapter.py`
- `src/learning/learning_contract.py`
- `src/learning/learning_execution.py`
- `src/learning/learning_feedback.py`
- `src/learning/learning_plan.py`
- `src/learning/learning_runner.py`
- `src/learning/model_profiles.py`

And related GUI/adapter pieces:

- `src/gui/controllers/learning_controller.py`
- `src/gui/learning_review_dialog_v2.py`
- `src/gui/views/experiment_design_panel_v2.py`
- `src/gui/views/learning_plan_table_v2.py`
- `src/gui/views/learning_review_panel_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui_v2/adapters/learning_adapter_v2.py`

Mark all of the above as **“Phase 3+ Learning subsystem”**.

### 2.2 Queue / Job System (Phase 5)

Under `src/queue/`:

- `src/queue/job_history_store.py`
- `src/queue/job_model.py`
- `src/queue/job_queue.py`
- `src/queue/single_node_runner.py`

And any central `__init__.py` if present.

Mark as **“Phase 5 Queue/Job subsystem”**.

### 2.3 Cluster & Worker Registry (Phase 5)

Under `src/cluster/`:

- `src/cluster/worker_model.py`
- `src/cluster/worker_registry.py`
- `src/cluster/__init__.py`

Mark as **“Phase 5 Cluster subsystem”**.

### 2.4 AI Settings Generator (Future AI Subsystem)

Under `src/ai/`:

- `src/ai/settings_generator_adapter.py`
- `src/ai/settings_generator_contract.py`
- `src/ai/settings_generator_driver.py`

Mark as **“Future AI settings subsystem”**.

### 2.5 GUI Adapter Stack (`src/gui_v2/*`)

Under `src/gui_v2/`:

- `src/gui_v2/adapters/__init__.py`
- `src/gui_v2/adapters/learning_adapter_v2.py`
- `src/gui_v2/adapters/pipeline_adapter_v2.py`
- `src/gui_v2/adapters/randomizer_adapter_v2.py`
- `src/gui_v2/adapters/status_adapter_v2.py`
- `src/gui_v2/randomizer_adapter.py`
- `src/gui_v2/validation/__init__.py`
- `src/gui_v2/validation/pipeline_txt2img_validator.py`

Mark as **“Legacy V2 adapter stack / future integration point”** with a note:

```python
# Note: Current MainWindowV2 + LayoutManagerV2 do not use this adapter stack.
# Retained as a design reference for future refactors.
```

### 2.6 GUI V2 “Extras” Not Required in Phase 1

Under `src/gui/`:

- `src/gui/adetailer_config_panel.py`  (explicit “maybe” from Rob)
- `src/gui/job_history_panel_v2.py`
- `src/gui/randomizer_panel_v2.py`

Mark as **“Phase 3+/4 GUI extras”** (adetailer, job history, randomizer GUI).

### 2.7 Utils Used by Future Subsystems

Under `src/utils/` (only those not on the Phase-1 path from `src/main.py`):

- `src/utils/aesthetic.py`
- `src/utils/aesthetic_detection.py`
- `src/utils/randomizer.py`
- `src/utils/state.py`
- `src/utils/webui_discovery.py`
- `src/utils/webui_launcher.py`

Mark as **“Phase 3+ helpers (learning/randomizer/webui automation)”**.

> Do **not** mark or modify core Phase-1 helpers like `config.py`, `preferences.py`, or generic logging unless you are certain they are solely used by future subsystems.

---

## 3. Documentation Updates

### 3.1 `docs/StableNew_V2_Inventory_V2-P1.md`

Add or update sections to clearly group modules into:

1. **Phase 1 — Core Runtime:**
   - GUI V2: `MainWindowV2`, `LayoutManagerV2`, `panels_v2/*`, `views/*_v2.py`, `theme_v2.py`, `app_state_v2.py`.
   - Pipeline runtime & WebUI client.
   - Minimal config/preferences used for pipeline runs.

2. **Phase 3 — Learning:**
   - All `src/learning/*` modules.
   - `src/gui/controllers/learning_controller.py`
   - Learning-related GUI views (`experiment_design_panel_v2`, `learning_plan_table_v2`, etc.).
   - `src/gui_v2/adapters/learning_adapter_v2.py`

3. **Phase 4 — Randomizer / Advanced Prompting:**
   - `src/gui/randomizer_panel_v2.py`
   - `src/gui/advanced_prompt_editor.py` (if you choose to classify here)
   - `src/utils/randomizer.py`
   - `src/gui_v2/randomizer_adapter.py`
   - `src/gui_v2/adapters/randomizer_adapter_v2.py`

4. **Phase 5 — Queue / Cluster:**
   - All `src/queue/*` modules.
   - All `src/cluster/*` modules.
   - Any tests in `tests/queue/*`, `tests/cluster/*` (referenced here, not moved by this PR).

5. **Future AI Settings:**
   - `src/ai/settings_generator_*`

Explicitly state for each group:

- “Not required to be passing/working for Phase 1 stability.”
- “Kept as design assets and will be revisited in the appropriate Phase.”

### 3.2 Learning & Cluster Docs (Light Touch)

- `docs/Future_Learning_Roadmap_*.md`
- `docs/LearningSystem_MasterIndex_*.md` (if present)
- `docs/Cluster_Compute_Vision_v2.md`

Update only if needed, to:

- Cross-reference the classification in `StableNew_V2_Inventory_V2-P1.md`.
- Clarify that the code under `src/learning`, `src/queue`, `src/cluster`, `src/ai` is **parked** until Phase 3+.

---

## 4. Files **Not** to Touch

To avoid accidental behavior changes:

- Do **not** modify:
  - `src/main.py`
  - `src/app_factory.py`
  - `src/pipeline/executor.py`
  - `src/controller/app_controller.py`
  - `src/gui/main_window_v2.py`
  - `src/gui/layout_v2.py`
  - `src/gui/theme_v2.py`
  - Any `src/gui/panels_v2/*`
- Do **not** delete any modules in this PR – only add comments and adjust docs.

---

## 5. Validation & Definition of Done

### Validation

- Run:

  ```bash
  pytest -q
  ```

  - Expect **no new failures** caused by this PR (it is comments + docs only).
- Confirm imports:
  - No new imports were added.
  - No module paths were renamed or removed.

### Definition of Done

This PR is complete when:

1. Every module listed in §2 has a clear Phase-3+ style header comment.
2. `docs/StableNew_V2_Inventory_V2-P1.md` has explicit sections for Phase 1, Phase 3 (learning), Phase 4 (randomizer/advanced), Phase 5 (queue/cluster), and future AI settings.
3. Learning / cluster / queue / AI modules are recognized across docs as **not required** for Phase-1 “it boots, it runs a pipeline, dropdowns populate” stability.
4. No runtime behavior has changed and all existing tests behave exactly as they did prior to this PR.

