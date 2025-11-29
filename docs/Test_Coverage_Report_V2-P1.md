# Test Coverage Report – Phase 1 (V2-P1)

> This document summarizes the **current** test coverage for the Phase-1
> StableNewV2 core, based on the Phase-1 test harness.

**Date of run:** 2025-11-28  
**Command used:**

```bash
pytest $(cat tests/phase1_test_suite.txt) --cov=src --cov-report=term-missing -q
```

Note: The run completed with controller/GUI test failures (theme shim missing legacy color tokens and missing legacy GUI helpers), but coverage output was still produced.

---

## 1. Overall Coverage Snapshot

- **Overall src/ coverage:** 18.97%
- **Number of modules with >= 80% coverage:** 18
- **Number of modules with 50–79% coverage:** 5
- **Number of modules with 1–49% coverage:** many (majority of active modules)
- **Number of modules with 0% coverage:** large (all future-phase subsystems and most legacy stubs)

> Method:
> - Parsed from the `--cov-report=term-missing` output.
> - Grouped by thresholds: 80+, 50–79, 1–49, 0.

---

## 2. High Coverage (>= 80%)

These modules are strongly covered by the Phase-1 suite (often because they are thin shims/stubs or simple initializers):

- `src/pipeline/stage_sequencer.py` — **100%**
- `src/pipeline/__init__.py` — **100%**
- `src/pipeline/last_run_store_v2_5.py` — **95.12%**
- `src/controller/__init__.py` — **100%**
- `src/gui/__init__.py` — **100%**
- `src/gui/layout_v2.py` — **100%**
- `src/gui/main_window.py` — **100%**
- `src/gui/theme.py` (shim) — **100%**
- `src/gui/panels_v2/__init__.py` — **100%**
- `src/gui/panels_v2/pipeline_panel_v2.py` — **100%**
- `src/gui/panels_v2/preview_panel_v2.py` — **100%**
- `src/gui/panels_v2/randomizer_panel_v2.py` — **100%**
- `src/gui/panels_v2/sidebar_panel_v2.py` — **100%**
- `src/gui/panels_v2/status_bar_v2.py` — **100%**
- `src/gui/pipeline_controls_panel.py` — **100%** (stub)
- `src/gui/config_panel.py` — **100%** (stub)
- `src/gui/views/__init__.py` — **100%**
- `src/gui_v2/adapters/__init__.py` — **100%**

**Notes / Observations:**

- Many high-coverage entries are stubs or very small shims; true functional depth remains in lower buckets.
- `stage_sequencer` and `last_run_store_v2_5` are genuinely exercised.

---

## 3. Medium Coverage (50–79%)

Modules with decent coverage but room for improvement:

- `src/controller/app_controller.py` — **60.45%**
- `src/gui/api_status_panel.py` — **56.52%**
- `src/gui/gui_invoker.py` — **55.00%**
- `src/gui/prompt_pack_list_manager.py` — **50.00%**
- `src/gui/theme_v2.py` — **73.08%**

**Notes / Observations:**

- Controller happy-paths are exercised, but error branches and more complex flows are untested.
- GUI support helpers get partial coverage via layout and status tests; deeper state changes are not covered.

---

## 4. Low Coverage (1–49%)

Modules that are only lightly exercised by the Phase-1 suite:

- `src/gui/main_window_v2.py` — **34.60%**
- `src/gui/prompt_pack_panel_v2.py` — **37.21%**
- `src/gui/sidebar_panel_v2.py` — **31.82%**
- `src/gui/pipeline_panel_v2.py` — **24.53%**
- `src/gui/preview_panel_v2.py` — **21.28%**
- `src/gui/app_state_v2.py` — **46.27%**
- `src/gui/prompt_pack_adapter_v2.py` — **47.83%**
- `src/gui/status_bar_v2.py` — **49.57%**
- `src/gui/randomizer_panel_v2.py` — **13.71%**
- `src/pipeline/pipeline_runner.py` — **26.42%**
- `src/main.py` — **17.94%**
- Numerous other GUI panels and adapters fall into this range.

**Notes / Observations:**

- GUI V2 panels are instantiated in tests but not deeply exercised (callbacks, error paths, theme args).
- Controller ↔ pipeline integration is only partially covered; many branches untested.

---

## 5. No Coverage (0%)

Modules currently **not hit at all** by the Phase-1 harness.

### 5.1 Learning subsystem

- `src/learning/learning_adapter.py`, `learning_execution.py`, `learning_feedback.py`, `learning_plan.py`, `learning_profile_sidecar.py`, `learning_record_builder.py`, `recommendation_engine.py`, etc. — **0%**

### 5.2 Queue subsystem

- `src/queue/job_queue.py`, `job_history_store.py`, `job_model.py`, `single_node_runner.py`, `src/queue/__init__.py` — **0%**

### 5.3 Cluster subsystem

- `src/cluster/worker_model.py`, `worker_registry.py`, `src/cluster/__init__.py` — **0%**

### 5.4 AI settings generator

- `src/ai/settings_generator_adapter.py`, `settings_generator_contract.py`, `settings_generator_driver.py` — **0%**

### 5.5 GUI / Adapters not yet exercised

- `src/gui/learning_*` dialogs/panels (non-V2), `src/gui/views/learning_*_v2.py`, many V1/V2 experimental views — **0%**
- `src/gui_v2/adapters/randomizer_adapter_v2.py` (mostly untested), other adapter variants — **0%**

**Notes / Observations:**

- Future-phase subsystems (learning, queue, cluster, AI) are intentionally untested in Phase 1 and remain at 0%.
- Legacy GUI stubs also register as 0% when they contain no executable lines.

---

## 6. Prioritized Follow-up Targets

1. **Critical GUI V2 paths**
   - `src/gui/main_window_v2.py` — 34.60%: add tests around zone creation, theme args, and controller wiring to avoid crashes (e.g., missing theme tokens).
   - `src/gui/prompt_pack_panel_v2.py` / `src/gui/sidebar_panel_v2.py` — 37.21% / 31.82%: cover apply-pack flows and theme fallbacks.
2. **Pipeline core**
   - `src/pipeline/pipeline_runner.py` — 26.42%: add unit tests for success/error paths and cancellation.
   - `src/main.py` — 17.94%: cover single-instance lock and async WebUI bootstrap branches.
3. **API / WebUI integration**
   - `src/controller/webui_connection_controller.py` — 28.95%: add tests for retry/error paths.
   - `src/gui/status_bar_v2.py` — 49.57%: cover status updates and WebUI panel sync.

---

## 7. How to Regenerate This Report

To refresh this coverage report after adding tests or changing the harness:

1. Run:

   ```bash
   pytest $(cat tests/phase1_test_suite.txt) --cov=src --cov-report=term-missing -q
   ```

2. Copy the new coverage summary.
3. Update:
   - The percentages in Sections 1–5  
   - The follow-up targets in Section 6  
   - The run date at the top of this document.

Keep this file in sync with major changes to the Phase-1 test harness.
