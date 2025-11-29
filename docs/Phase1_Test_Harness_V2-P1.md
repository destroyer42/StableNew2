# Phase-1 Test Harness (V2-P1)

This document defines a **deterministic subset of tests** that should be
green when the Phase-1 V2 GUI + pipeline are in a healthy state.

The goals:

- Quickly answer: “Is the repo basically working?”
- Provide a stable target for Codex / CI to aim for.
- Give us a baseline for future coverage improvements.

---

## 1. Quick Smoke (Tier 0)

Run:

```bash
pytest +  tests/test_main_single_instance.py +  tests/test_api_client.py +  tests/api/test_webui_healthcheck.py +  -q
```

This validates:

- Basic entrypoint wiring and single-instance protection.
- API client basic behavior.
- WebUI healthcheck plumbing (using whatever stubs/mocks are configured in tests).

---

## 2. Core Controller + Pipeline (Tier 1)

Run:

```bash
pytest +  tests/controller/test_app_controller_config.py +  tests/controller/test_app_controller_packs.py +  tests/controller/test_app_controller_pipeline_flow_pr0.py +  tests/controller/test_app_controller_pipeline_integration.py +  tests/pipeline/test_last_run_store_v2_5.py +  tests/pipeline/test_stage_sequencer_plan_builder.py +  -q
```

This validates:

- AppController config + packs behavior.
- Basic pipeline flow and integration.
- Last-run store mechanics.
- Stage sequencer planning.

---

## 3. GUI V2 Core (Tier 2)

Run:

```bash
pytest +  tests/gui_v2/test_gui_v2_layout_skeleton.py +  tests/gui_v2/test_entrypoint_uses_v2_gui.py +  tests/gui_v2/test_theme_v2.py +  -q
```

This validates:

- `MainWindowV2` is used by both `src.main` and `src.gui.main_window`.
- GUI V2 zones and panels (`sidebar_panel_v2`, `pipeline_panel_v2`, `preview_panel_v2`,
  `status_bar_v2`, `pipeline_controls_panel`, `run_pipeline_btn`) exist and are wired
  consistently.
- `theme_v2` styles apply without importing legacy `theme.py` logic.

---

## 4. Running the Full Phase-1 Harness

To run all the above in one go:

```bash
pytest +  tests/test_main_single_instance.py +  tests/test_api_client.py +  tests/api/test_webui_healthcheck.py +  tests/controller/test_app_controller_config.py +  tests/controller/test_app_controller_packs.py +  tests/controller/test_app_controller_pipeline_flow_pr0.py +  tests/controller/test_app_controller_pipeline_integration.py +  tests/pipeline/test_last_run_store_v2_5.py +  tests/pipeline/test_stage_sequencer_plan_builder.py +  tests/gui_v2/test_gui_v2_layout_skeleton.py +  tests/gui_v2/test_entrypoint_uses_v2_gui.py +  tests/gui_v2/test_theme_v2.py +  -q
```

> If any of these tests are failing for known Phase-1 gaps, they should
> be annotated with `xfail` or documented in a Phase-1 issues list so
> that “red” is always meaningful.

---

## 5. Coverage (Optional, Recommended)

If `pytest-cov` is available, run:

```bash
pytest +  --cov=src +  --cov-report=term-missing +  tests +  -q
```

This shows:

- Overall coverage percentage across `src/`.
- Which modules are completely untested (0%).

For Phase-1, the priority is:

- `src/gui/main_window_v2.py`
- `src/gui/panels_v2/*`
- `src/controller/*`
- `src/pipeline/*`
