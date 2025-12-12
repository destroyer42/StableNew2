# PR-CORE-PHASE1-SYNTAX-AND-TEST-HARNESS-007_V2-P1

**Snapshot Baseline:** Most recent repo state after Codex partially applied:
- `CLEANUP-GUI-V1-ARCHIVE`-style changes (several GUI files replaced with `Moved to archive/...`)
- GUI V2 wiring PRs (entrypoint → `MainWindowV2`)
- Some theme/test changes

This PR is designed to be **tolerant** of the current partial state and focuses on two things only:

1. **Fix hard syntax errors** introduced by “Moved to archive …” placeholder lines so that pytest can collect tests again.
2. **Establish a deterministic Phase-1 test harness** (a curated set of tests and commands) to quickly assess whether the repo is in a working state and to get a sense of test coverage.

It does **not** make any new architectural changes to GUI V2 or the pipeline.

---

## 1. Problem Summary

From Codex’s last assessment:

- Several GUI modules were replaced with a single bare line like:

  ```text
  Moved to archive/gui_v1/scrolling.py
  ```

  which is **invalid Python** and produces `SyntaxError` as soon as those modules are imported.
- `src/gui/theme.py` also contains a placeholder snippet (`(...existing code...)` or similar), which is not valid code. It is still imported by active modules (`pipeline_panel_v2`, `preview_panel_v2` in your current working tree, so collection stops immediately.
- `scrolling.py` (with a bare placeholder) is imported by `advanced_prompt_editor` → `main_window`, which again kills collection.
- More files (`log_panel.py`, `center_panel.py`, `pipeline_command_bar_v2.py`, `prompt_pack_panel.py`, `tooltip.py`, `stage_chooser.py`, `txt2img_stage_card.py`, `upscale_stage_card.py`) have the same placeholder pattern.

As a result:

> **pytest isn’t failing tests; it’s failing to even collect them because of SyntaxError in these stubbed modules.**

We need **valid stub modules** and a **known-good test subset**.

---

## 2. Goals

### 2.1 Syntax & Import Fixes

- Replace bare “Moved to archive…” placeholders with **minimal valid Python stubs**.
- Make `src/gui/theme.py` a valid, backward-compatible shim that delegates to `theme_v2`, so any remaining imports don’t crash.
- Do **not** reintroduce legacy behavior – these are stubs, not functional restorations.

### 2.2 Phase-1 Test Harness

- Define a **deterministic, curated set of tests**:
  - GUI V2 basic layout & entrypoint.
  - Core app/controller/config tests.
  - Pipeline skeleton / last-run store.
- Provide commands and a small helper manifest so humans and tools can run the same suite every time.
- Provide guidance for measuring coverage via `pytest-cov` (if installed).

---

## 3. Files to Fix (Syntax Stubs)

> Note: The exact placeholder text may vary slightly (`Moved to archive/gui_v1/…` vs `# Moved…`). The goal is the same: replace any non-Python placeholders with valid modules.

### 3.1 `src/gui/theme.py` — turn into a shim on `theme_v2`

**Current problem:**
- Contains a non-Python placeholder line and/or partial code.
- Still imported by active modules (`pipeline_panel_v2`, `preview_panel_v2`, some V2 panels) in your current repo state.

**Action:**
Replace the entire file with a small shim that re-exports everything from `theme_v2`:

```diff
diff --git a/src/gui/theme.py b/src/gui/theme.py
index 0000000..0000000 100644
--- a/src/gui/theme.py
+++ b/src/gui/theme.py
@@ -1,999 +1,18 @@
-<existing placeholder or legacy content>
+""" 
+Legacy theming shim.
+
+Phase-1 note:
+    New code should import from `src.gui.theme_v2` directly.
+    This module exists only to keep any remaining imports from crashing
+    while we finalize the V2-only GUI path.
+"""
+
+from __future__ import annotations
+
+# Re-export all public symbols from theme_v2 so imports that still use
+# `from src.gui import theme as theme_mod` continue to work.
+from src.gui.theme_v2 import *  # noqa: F401,F403
+
+__all__ = [name for name in globals() if not name.startswith("_")]
```

> This keeps Phase-1 safe: nobody should be adding new imports from `theme`, but anything that still exists won’t cause SyntaxError.

---

### 3.2 Stub out GUI legacy modules with valid no-op code

The following files are known to contain **bare placeholder lines** that produce SyntaxError:

- `src/gui/center_panel.py`
- `src/gui/log_panel.py`
- `src/gui/pipeline_command_bar_v2.py`
- `src/gui/prompt_pack_panel.py`
- `src/gui/scrolling.py`
- `src/gui/stage_chooser.py`
- `src/gui/tooltip.py`
- `src/gui/txt2img_stage_card.py`
- `src/gui/upscale_stage_card.py`

> If additional files are found with the same pattern, apply the same treatment.

#### 3.2.1 Generic stub template

Use this minimal, valid Python for modules that no longer need to function at all (they’re fully superseded by V2):

```python
"""
Legacy GUI module archived to `archive/gui_v1/<name>.py`.

Phase-1 behavior:
    This stub exists only to prevent SyntaxError on import.
    Any remaining imports should be migrated to the V2 equivalents.
"""

from __future__ import annotations

# No runtime behavior.
```

#### 3.2.2 Example patches

Below are sample diffs for a few key files. Codex should apply similar changes to all of the listed modules.

**`src/gui/scrolling.py`**

```diff
diff --git a/src/gui/scrolling.py b/src/gui/scrolling.py
index 0000000..0000000 100644
--- a/src/gui/scrolling.py
+++ b/src/gui/scrolling.py
@@ -1,5 +1,18 @@
-Moved to archive/gui_v1/scrolling.py
+"""
+Legacy GUI scrolling helpers archived to `archive/gui_v1/scrolling.py`.
+
+Phase-1:
+    Use `src.gui.widgets.scrollable_frame_v2.ScrollableFrame` instead.
+    This stub exists to keep imports from crashing.
+"""
+
+from __future__ import annotations
+
+# Minimal stub for compatibility. Advanced behavior is deprecated.
+class ScrollableFrame:  # type: ignore[too-many-ancestors]
+    def __init__(self, *args, **kwargs) -> None:
+        # No-op stub; real logic lives in scrollable_frame_v2.
+        pass
```

> This is slightly richer than a generic stub and ensures that if any code still tries to instantiate `ScrollableFrame`, it won’t crash.

**`src/gui/center_panel.py`**

```diff
diff --git a/src/gui/center_panel.py b/src/gui/center_panel.py
index 0000000..0000000 100644
--- a/src/gui/center_panel.py
+++ b/src/gui/center_panel.py
@@ -1,3 +1,16 @@
-Moved to archive/gui_v1/center_panel.py
+"""
+Legacy center panel (V1 layout) archived to `archive/gui_v1/center_panel.py`.
+
+Phase-1:
+    Center layout is owned by `MainWindowV2` + `LayoutManagerV2`.
+"""
+
+from __future__ import annotations
+
+# Empty stub – any remaining imports should be migrated to V2 layouts.
```

**`src/gui/log_panel.py`**

```diff
diff --git a/src/gui/log_panel.py b/src/gui/log_panel.py
index 0000000..0000000 100644
--- a/src/gui/log_panel.py
+++ b/src/gui/log_panel.py
@@ -1,3 +1,16 @@
-Moved to archive/gui_v1/log_panel.py
+"""
+Legacy log panel (V1) archived to `archive/gui_v1/log_panel.py`.
+
+Phase-1:
+    Logging is handled via the structured logger and status bar V2.
+"""
+
+from __future__ import annotations
+
+# Empty stub – no runtime behavior.
```

**`src/gui/stage_chooser.py`, `src/gui/tooltip.py`, `src/gui/pipeline_command_bar_v2.py`,  
`src/gui/prompt_pack_panel.py`, `src/gui/txt2img_stage_card.py`, `src/gui/upscale_stage_card.py`**

Apply the **generic stub template** to each of these files.

Example for `src/gui/tooltip.py`:

```diff
diff --git a/src/gui/tooltip.py b/src/gui/tooltip.py
index 0000000..0000000 100644
--- a/src/gui/tooltip.py
+++ b/src/gui/tooltip.py
@@ -1,3 +1,16 @@
-Moved to archive/gui_v1/tooltip.py
+"""
+Legacy tooltip helpers archived to `archive/gui_v1/tooltip.py`.
+
+Phase-1:
+    Any GUI hints/tooltips should be implemented directly in V2 widgets.
+"""
+
+from __future__ import annotations
+
+# Empty stub – no runtime behavior.
```

---

### 3.3 Ensure `tests/gui_v2/conftest.py` has no inline imports

Codex previously reported a syntax error from an inline import inside `DEFAULT_TXT2IMG_CFG` in `tests/gui_v2/conftest.py`:

> `from src.app_factory import build_v2_app` was sitting inside `DEFAULT_TXT2IMG_CFG`.

Confirm that:

- All imports in `tests/gui_v2/conftest.py` live at the top level of the module.
- There are **no** stray `from src.app_factory import build_v2_app` inside dicts or data structures.

If any remain:

```diff
diff --git a/tests/gui_v2/conftest.py b/tests/gui_v2/conftest.py
index 0000000..0000000 100644
--- a/tests/gui_v2/conftest.py
+++ b/tests/gui_v2/conftest.py
@@ -1,5 +1,9 @@
-DEFAULT_TXT2IMG_CFG = {
-    "some_key": "some_value",
-    "factory": from src.app_factory import build_v2_app,  # <-- invalid
-}
+from src.app_factory import build_v2_app
+
+DEFAULT_TXT2IMG_CFG = {
+    "some_key": "some_value",
+    # `build_v2_app` is imported at module scope; do not inline imports here.
+}
```

> Exact structure may differ; the key point is: **no inline imports** inside dicts or config literals.

---

## 4. Phase-1 Deterministic Test Harness

Once the syntax issues are fixed, we want a **known, deterministic set of tests** that:

- Exercise the core app wiring and pipeline.
- Exercise GUI V2 layout and entrypoint.
- Are *intended* to be green in Phase 1 (or else clearly documented as WIP).

### 4.1 New doc: `docs/Phase1_Test_Harness_V2-P1.md`

Create a new markdown file:

```diff
diff --git a/docs/Phase1_Test_Harness_V2-P1.md b/docs/Phase1_Test_Harness_V2-P1.md
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/docs/Phase1_Test_Harness_V2-P1.md
@@ -0,0 +1,120 @@
+# Phase-1 Test Harness (V2-P1)
+
+This document defines a **deterministic subset of tests** that should be
+green when the Phase-1 V2 GUI + pipeline are in a healthy state.
+
+The goals:
+
+- Quickly answer: “Is the repo basically working?”
+- Provide a stable target for Codex / CI to aim for.
+- Give us a baseline for future coverage improvements.
+
+---
+
+## 1. Quick Smoke (Tier 0)
+
+Run:
+
+```bash
+pytest +  tests/test_main_single_instance.py +  tests/test_api_client.py +  tests/api/test_webui_healthcheck.py +  -q
+```
+
+This validates:
+
+- Basic entrypoint wiring and single-instance protection.
+- API client basic behavior.
+- WebUI healthcheck plumbing (using whatever stubs/mocks are configured in tests).
+
+---
+
+## 2. Core Controller + Pipeline (Tier 1)
+
+Run:
+
+```bash
+pytest +  tests/controller/test_app_controller_config.py +  tests/controller/test_app_controller_packs.py +  tests/controller/test_app_controller_pipeline_flow_pr0.py +  tests/controller/test_app_controller_pipeline_integration.py +  tests/pipeline/test_last_run_store_v2_5.py +  tests/pipeline/test_stage_sequencer_plan_builder.py +  -q
+```
+
+This validates:
+
+- AppController config + packs behavior.
+- Basic pipeline flow and integration.
+- Last-run store mechanics.
+- Stage sequencer planning.
+
+---
+
+## 3. GUI V2 Core (Tier 2)
+
+Run:
+
+```bash
+pytest +  tests/gui_v2/test_gui_v2_layout_skeleton.py +  tests/gui_v2/test_entrypoint_uses_v2_gui.py +  tests/gui_v2/test_theme_v2.py +  -q
+```
+
+This validates:
+
+- `MainWindowV2` is used by both `src.main` and `src.gui.main_window`.
+- GUI V2 zones and panels (`sidebar_panel_v2`, `pipeline_panel_v2`, `preview_panel_v2`,
+  `status_bar_v2`, `pipeline_controls_panel`, `run_pipeline_btn`) exist and are wired
+  consistently.
+- `theme_v2` styles apply without importing legacy `theme.py` logic.
+
+---
+
+## 4. Running the Full Phase-1 Harness
+
+To run all the above in one go:
+
+```bash
+pytest +  tests/test_main_single_instance.py +  tests/test_api_client.py +  tests/api/test_webui_healthcheck.py +  tests/controller/test_app_controller_config.py +  tests/controller/test_app_controller_packs.py +  tests/controller/test_app_controller_pipeline_flow_pr0.py +  tests/controller/test_app_controller_pipeline_integration.py +  tests/pipeline/test_last_run_store_v2_5.py +  tests/pipeline/test_stage_sequencer_plan_builder.py +  tests/gui_v2/test_gui_v2_layout_skeleton.py +  tests/gui_v2/test_entrypoint_uses_v2_gui.py +  tests/gui_v2/test_theme_v2.py +  -q
+```
+
+> If any of these tests are failing for known Phase-1 gaps, they should
+> be annotated with `xfail` or documented in a Phase-1 issues list so
+> that “red” is always meaningful.
+
+---
+
+## 5. Coverage (Optional, Recommended)
+
+If `pytest-cov` is available, run:
+
+```bash
+pytest +  --cov=src +  --cov-report=term-missing +  tests +  -q
+```
+
+This shows:
+
+- Overall coverage percentage across `src/`.
+- Which modules are completely untested (0%).
+
+For Phase-1, the priority is:
+
+- `src/gui/main_window_v2.py`
+- `src/gui/panels_v2/*`
+- `src/controller/*`
+- `src/pipeline/*`
```

> This file is purely documentation; it does not affect runtime.

---

### 4.2 Optional: `tests/phase1_test_suite.txt`

To make it easy for tools to consume the Phase-1 harness, add a simple manifest file:

```diff
diff --git a/tests/phase1_test_suite.txt b/tests/phase1_test_suite.txt
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/phase1_test_suite.txt
@@ -0,0 +1,20 @@
+tests/test_main_single_instance.py
+tests/test_api_client.py
+tests/api/test_webui_healthcheck.py
+tests/controller/test_app_controller_config.py
+tests/controller/test_app_controller_packs.py
+tests/controller/test_app_controller_pipeline_flow_pr0.py
+tests/controller/test_app_controller_pipeline_integration.py
+tests/pipeline/test_last_run_store_v2_5.py
+tests/pipeline/test_stage_sequencer_plan_builder.py
+tests/gui_v2/test_gui_v2_layout_skeleton.py
+tests/gui_v2/test_entrypoint_uses_v2_gui.py
+tests/gui_v2/test_theme_v2.py
```

This allows:

- Humans: `pytest $(cat tests/phase1_test_suite.txt) -q`
- Tools: parse the file to know which tests belong in the Phase-1 harness.

---

## 5. Validation & Definition of Done

### 5.1 Validation Steps

1. **Syntax check**:

   ```bash
   python -m py_compile \
     src/gui/theme.py \
     src/gui/scrolling.py \
     src/gui/center_panel.py \
     src/gui/log_panel.py \
     src/gui/pipeline_command_bar_v2.py \
     src/gui/prompt_pack_panel.py \
     src/gui/tooltip.py \
     src/gui/stage_chooser.py \
     src/gui/txt2img_stage_card.py \
     src/gui/upscale_stage_card.py
   ```

   All should compile without error.

2. **Test collection**:

   ```bash
   pytest --maxfail=1 -q
   ```

   - Pytest should now **collect tests fully**.
   - Failures (if any) should stem from real test assertions, not SyntaxError.

3. **Phase-1 harness**:

   ```bash
   pytest $(cat tests/phase1_test_suite.txt) -q
   ```

   - Ideally green, or any failing tests clearly documented as expected WIP.

### 5.2 Definition of Done

This PR is complete when:

1. All previously “placeholder” GUI modules are valid Python files (no SyntaxError).
2. `src/gui/theme.py` is a clean shim over `theme_v2` and no longer contains broken placeholder text.
3. `tests/gui_v2/conftest.py` has no inline imports and imports compile correctly.
4. `pytest` can collect the full suite without SyntaxError.
5. The Phase-1 harness defined in `docs/Phase1_Test_Harness_V2-P1.md` runs deterministically, providing a stable signal of repository health.
