# PR-CORE-PHASE1-COVERAGE-REPORT-008_V2-P1

**Snapshot Baseline:**  
Repository state _after_ applying:

- `PR-CORE-PHASE1-SYNTAX-AND-TEST-HARNESS-007_V2-P1`  
  (Phase-1 test harness + syntax stub fixes)
- `PR-CORE-CLASSIFY-FUTURE-SUBSYSTEMS-003_V2-P1-ROBUST`  
  (Subsystem classification headers)

This PR is intentionally small and focused. It does **not** modify core behavior.  
It adds a **coverage workflow + report document** so we have a concrete view of:

- What the Phase-1 test harness actually covers.
- Which modules are hotspots (well-covered) vs. blind spots (poor or zero coverage).

---

## 1. Goals

1. Run the **Phase-1 test harness** with coverage enabled.
2. Generate a **human-readable coverage summary** in:
   - `docs/Test_Coverage_Report_V2-P1.md`
3. Categorize modules into:
   - High coverage (>= 80%)
   - Medium coverage (50–79%)
   - Low coverage (1–49%)
   - No coverage (0%)

This is a **documentation/report PR**. No production code paths are changed.

---

## 2. Pre-requisites

### 2.1 Ensure pytest-cov is installed

If `pytest-cov` is not installed in the environment, install it:

```bash
pip install pytest-cov
```

---

## 3. Commands to Run (Phase-1 Coverage)

> All commands should be run from the repository root.

### 3.1 Run coverage for the Phase-1 suite only

If `tests/phase1_test_suite.txt` exists (from PR-007):

```bash
pytest   $(cat tests/phase1_test_suite.txt)   --cov=src   --cov-report=term-missing   -q
```

If that file does **not** exist yet, use the explicit list from `docs/Phase1_Test_Harness_V2-P1.md`:

```bash
pytest   tests/test_main_single_instance.py   tests/test_api_client.py   tests/api/test_webui_healthcheck.py   tests/controller/test_app_controller_config.py   tests/controller/test_app_controller_packs.py   tests/controller/test_app_controller_pipeline_flow_pr0.py   tests/controller/test_app_controller_pipeline_integration.py   tests/pipeline/test_last_run_store_v2_5.py   tests/pipeline/test_stage_sequencer_plan_builder.py   tests/gui_v2/test_gui_v2_layout_skeleton.py   tests/gui_v2/test_entrypoint_uses_v2_gui.py   tests/gui_v2/test_theme_v2.py   --cov=src   --cov-report=term-missing   -q
```

Capture the `--cov-report=term-missing` output; you’ll use it to build the report.

---

## 4. New Documentation File

Create this new file:

- `docs/Test_Coverage_Report_V2-P1.md`

Populate it using the structure below.  
Codex **must** fill the bullets and percentages based on the actual coverage results from the commands in Section 3.

```diff
diff --git a/docs/Test_Coverage_Report_V2-P1.md b/docs/Test_Coverage_Report_V2-P1.md
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/docs/Test_Coverage_Report_V2-P1.md
@@ -0,0 +1,140 @@
+# Test Coverage Report — Phase 1 (V2-P1)
+
+> This document summarizes the **current** test coverage for the Phase-1
+> StableNewV2 core, based on the Phase-1 test harness.
+
+**Date of run:** _<FILL-IN: YYYY-MM-DD>_  
+**Command used:**
+
+```bash
+pytest $(cat tests/phase1_test_suite.txt) --cov=src --cov-report=term-missing -q
+```
+
+If the explicit file list was used instead of `phase1_test_suite.txt`, note it here.
+
+---
+
+## 1. Overall Coverage Snapshot
+
+- **Overall src/ coverage:** _<FILL-IN: e.g. 37%>_
+- **Number of modules with >= 80% coverage:** _<FILL-IN>_
+- **Number of modules with 50–79% coverage:** _<FILL-IN>_
+- **Number of modules with 1–49% coverage:** _<FILL-IN>_
+- **Number of modules with 0% coverage:** _<FILL-IN>_
+
+> Method:
+> - Parsed from the `--cov-report=term-missing` output.
+> - Grouped by thresholds: 80+, 50–79, 1–49, 0.
+
+---
+
+## 2. High Coverage (>= 80%)
+
+These modules are strongly covered by the Phase-1 suite.
+
+- _Example format (Codex must fill real values):_
+  - `src/controller/app_controller.py` — **XX%**
+  - `src/pipeline/stage_sequencer.py` — **YY%**
+
+**Notes / Observations:**
+
+- _<FILL-IN: any interesting patterns, e.g., controllers are well covered while GUI panels are not>_
+
+---
+
+## 3. Medium Coverage (50–79%)
+
+Modules with decent coverage but room for improvement.
+
+- _Example format:_
+  - `src/pipeline/last_run_store_v2_5.py` — **XX%**
+  - `src/api/client.py` — **YY%**
+
+**Notes / Observations:**
+
+- _<FILL-IN: e.g., “Core pipeline orchestration covered via integration tests, but some branches are untested.”>_
+
+---
+
+## 4. Low Coverage (1–49%)
+
+Modules that are only lightly exercised by the Phase-1 suite.
+
+- _Example format:_
+  - `src/gui/main_window_v2.py` — **XX%**
+  - `src/gui/panels_v2/pipeline_panel_v2.py` — **YY%**
+  - `src/gui/panels_v2/sidebar_panel_v2.py` — **ZZ%**
+
+**Notes / Observations:**
+
+- _<FILL-IN: e.g., “GUI V2 panels are instantiated in layout tests but not deeply exercised.”>_
+
+---
+
+## 5. No Coverage (0%)
+
+Modules that are currently **not hit at all** by the Phase-1 harness.
+
+List each module with 0% coverage that matters for future phases, grouped by subsystem:
+
+### 5.1 Learning subsystem
+
+- _Example:_
+  - `src/learning/learning_runner.py` — **0%**
+  - `src/learning/learning_record.py` — **0%**
+
+### 5.2 Queue subsystem
+
+- e.g., `src/queue/job_queue.py` — **0%**
+
+### 5.3 Cluster subsystem
+
+- e.g., `src/cluster/worker_registry.py` — **0%**
+
+### 5.4 AI settings generator
+
+- e.g., `src/ai/settings_generator_adapter.py` — **0%**
+
+### 5.5 GUI / Adapters not yet exercised
+
+- e.g., `src/gui_v2/adapters/learning_adapter_v2.py` — **0%**
+- e.g., `src/gui_v2/adapters/randomizer_adapter_v2.py` — **0%**
+
+**Notes / Observations:**
+
+- _<FILL-IN: e.g., “All future-phase subsystems (learning, queue, cluster, AI, adapters) are intentionally untested in Phase 1 and should be targeted in later phases.”>_
+
+---
+
+## 6. Prioritized Follow-up Targets
+
+Based on the above buckets, identify **top follow-up targets** for Phase-1.5 / Phase-2:
+
+1. **Critical GUI V2 paths** (must be robust before adding more features):
+   - _<FILL-IN: main_window_v2, pipeline_panel_v2, etc., with current coverage>_
+2. **Pipeline core**:
+   - _<FILL-IN: modules with medium coverage that should move to high>_
+3. **API / WebUI integration**:
+   - _<FILL-IN: e.g., `src/api/webui_process_manager.py` coverage>_
+
+Each target should have:
+
+- Module name  
+- Current coverage %  
+- One-line suggestion:
+  - e.g., “Add a unit test for error paths when WebUI is down.”
+
+---
+
+## 7. How to Regenerate This Report
+
+To refresh this coverage report after adding tests or changing the harness:
+
+1. Run:
+
+   ```bash
+   pytest $(cat tests/phase1_test_suite.txt) --cov=src --cov-report=term-missing -q
+   ```
+
+2. Copy the new coverage summary.
+3. Update:
+   - The percentages in Sections 1–5  
+   - The follow-up targets in Section 6  
+   - The run date at the top of this document.
+
+Keep this file in sync with major changes to the Phase-1 test harness.
```

---

## 5. Validation & Definition of Done

### 5.1 Validation Steps

1. **Run coverage:**

   ```bash
   pytest $(cat tests/phase1_test_suite.txt) --cov=src --cov-report=term-missing -q
   ```

   - Ensure the command completes.
   - Note the overall coverage % and per-module lines.

2. **Populate `docs/Test_Coverage_Report_V2-P1.md`:**

   - Replace all `_<FILL-IN: ...>_` markers with real data from the coverage output.
   - Fill example module lists with actual modules and their percentages.

3. **Open the report and visually verify:**

   - Sections 1–7 are present.
   - Numbers are consistent with the coverage output.

### 5.2 Definition of Done

This PR is complete when:

1. `docs/Test_Coverage_Report_V2-P1.md` exists and contains **real coverage data**, not placeholders.
2. The report clearly identifies:
   - High / Medium / Low / No coverage modules.
   - Key hotspots and blind spots by subsystem (GUI, pipeline, API, learning, queue, cluster, AI, adapters).
3. A human can re-run the coverage command and update the report following Section 7 without ambiguity.

