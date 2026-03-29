# PR-GUI-286 - Incremental Projection Reconciliation and Visibility Gating

Status: In Progress 2026-03-28

## Purpose

Finish the hot-surface projection side so invisible queue/history/preview work
does not keep consuming Tk time while jobs are running.

## Landed In This Pass

- pipeline hot-surface scheduler now defers queue/history/preview/running-panel
  work when the destination surface is unmapped
- deferred hot surfaces are retained and flushed when the pipeline tab maps again
- preview thumbnail async apply now skips hidden-widget image mutation and
  relies on cached lookup results for later visible refreshes

## Still Open

- extend the same visibility-gated/background-query discipline to any remaining
  non-pipeline artifact/scan surfaces that still do work during runtime churn
- broaden deterministic interaction coverage around active review/photo-optimize
  browsing during queue pressure

## Key Files

- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/preview_panel_v2.py`
- `tests/gui_v2/test_pipeline_tab_callback_metrics_v2.py`
