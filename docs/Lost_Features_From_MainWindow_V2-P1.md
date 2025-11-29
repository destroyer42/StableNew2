
# Lost Features From Legacy main_window.py — StableNewV2
**Version:** V2-P1  
**Type:** Architecture + PR Mapping + Migration Readiness + Test Planning

---

## 1. Executive Summary

The legacy `main_window.py` (≈7,380 LOC) served as a monolithic orchestrator for GUI layout, pipeline wiring, WebUI lifecycle, configuration logic, tooltips/scroll helpers, learning features, and advanced prompt editing.  
StableNewV2 replaces it with a modular, zone-based architecture (`MainWindowV2`, PanelsV2, ViewsV2, AppControllerV2).  
While major pipeline, logging, and status functionality is preserved, several UX and subsystem integrations were lost during archive.

This document delivers:

- A **full inventory** of lost, partially-migrated, and fully-migrated features.
- A **subsystem-oriented architecture analysis** to map what legacy components did vs V2 equivalents.
- A **PR roadmap** (PR-014 → PR-019) to fully restore or modernize missing functionality.
- A **test plan** to validate completeness before proceeding deeper into Phase 2.

---

## 2. Feature Inventory (Legacy → V2 Mapping)

### 2.1 Fully Migrated (No Further Action Required)
| Feature | Status | Notes |
|--------|--------|-------|
| Pipeline execution | ✔️ Complete | Orchestrated via PipelineRunner + AppController |
| API/WebUI healthcheck | ✔️ Complete | Using WebUIProcessManager + healthcheck V2 |
| Status updates | ✔️ Complete | StatusBarV2 + controller events |
| Logging backbone | ✔️ Complete | PR-009/010/012 logging improvements |

---

## 3. Lost or Partially Migrated Features

### 3.1 Advanced Prompt Editor (Orphaned)
- **Legacy behavior:** dedicated tab, deep prompt editing tools, preset integration.
- **Current V2:** file exists, no wiring, no entrypoint.

### 3.2 Engine Settings Dialog (Stubbed)
- **Legacy behavior:** editable engine settings, validation, saving, reloading.
- **Current V2:** stub only in `AppController.on_open_settings()`.

### 3.3 Rich Log Console (Lost)
- Multiple view modes, filtering by level, scrolling panel.
- V2 has only minimal log region inside StatusBarV2.

### 3.4 ConfigPanelUX / PipelineControls (Partially Migrated)
- Legacy had strong validation, banners, advanced behaviors.
- V2 has new panels, but lacks parity with earlier UX.

### 3.5 Tooltips + Scroll Helpers (Removed)
- Legacy: ubiquitous tooltips, scrollwheel helpers.
- V2: not applied anywhere.

### 3.6 Learning UX (Partially Missing)
- Legacy handled learning-mode toggles and review dialog.
- V2: LearningTabFrame exists, but no wiring or UI triggers.

### 3.7 Advanced WebUI Lifecycle UI (Missing)
- Legacy had retry, reconnect, launch/re-launch controls.
- V2 has backend logic, but no GUI actions or banners.

---

## 4. Architecture Mapping (Subsystem-Oriented)

### 4.1 GUI Architecture

**Legacy:**  
`toplevel → notebook tabs → ad-hoc panels → monolithic event binding`.

**V2:**  
`MainWindowV2 → Layout Zones → PanelsV2 → ViewsV2 → Controller`.

Missing glue points:
- Advanced Editor wiring
- Learning dialog wiring
- Settings dialog shell
- Rich log panel
- Retry/reconnect shell

---

### 4.2 Controller Architecture

Legacy controller logic was embedded inside the massive GUI class.  
V2 uses clean controller boundaries:
- AppControllerV2
- LearningExecutionController
- PipelineController

Missing controller triggers:
- Open advanced editor
- Launch review dialog
- Retry WebUI lifecycle states

---

### 4.3 Pipeline Architecture

Legacy pipeline UX included:
- advanced validation banners
- “incomplete config” states
- dynamic sampler/model switching

V2 pipeline frames need:
- restored validation
- misinformation banners
- dynamic refresh triggers

---

## 5. PR Bundles (Codex-Ready) — Summary

### PR-014 — Advanced Prompt Editor (V2 Integration)
Reattach orphaned component into Prompt Tab as tab or modal.

### PR-015 — Engine Settings Dialog (Modernized)
Wire settings UI through AppController + ConfigManager.

### PR-016 — Pipeline UX Validation Parity
Restore validation UX lost when ConfigPanel/PipelineControlsPanel were removed.

### PR-017 — Tooltips + Scroll Helpers (V2)
Reintroduce scroll+hover enhancements.

### PR-018 — Learning UX (Review Dialog + Toggle)
Full lifecycle from LearningTabFrame to controller to review modal.

### PR-019 — WebUI Lifecycle UX (Retry / Reconnect)
Add user-facing retry controls + banners in V2.

---

## 6. Prioritized Roadmap (Architecture + UX)

### Phase 1.5 (Required Before Phase 2 Learning Integration)
1. PR-016 – Pipeline validation restoration  
2. PR-017 – Scroll & tooltip reintroduction  
3. PR-019 – WebUI retry/reconnect UX

### Phase 2 (Learning Integration)
1. PR-018 – Full learning UX  
2. PR-014 – Advanced editor anchoring  

### Phase 3 (Settings + Polishing)
1. PR-015 – Engine settings dialog  
2. Rich log console extensions from PR-012  

---

## 7. Test Plan (Coverage Extension)

### 7.1 GUI V2 Tests
- Validate advanced editor opens + saves text.
- Validate tooltips render on key fields.
- Validate scroll helpers operate on left zone lists.
- Validate pipeline validation banners appear at correct times.

### 7.2 Controller Tests
- AppController settings→dialog mapping.
- LearningExecutionController triggers post-processing.
- Retry/reconnect states propagate to GUI.

### 7.3 Integration Tests
- Flow: open settings, modify field, persist → reload.
- Flow: learning toggle → run → review dialog.

---

## 8. Final Notes
This document fully replaces any placeholder documentation.  
It serves as the canonical index of lost features, required migration steps, and V2 alignment tasks.

