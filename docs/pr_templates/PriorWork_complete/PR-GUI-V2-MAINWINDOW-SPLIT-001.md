# PR-GUI-V2-MAINWINDOW-SPLIT-001
## Title
MainWindow Decomposition into Modular V2 Panels

## Summary
This PR restructures `main_window.py` by extracting major UI regions into modular panels:
- SidebarPanelV2
- PipelinePanelV2 (existing)
- RandomizerPanelV2
- PreviewPanelV2
- StatusBarV2
Reduces main_window size; improves maintainability.

## Scope
- Create new panel modules under src/gui/panels_v2/
- Move UI construction logic from MainWindow
- Maintain existing wiring and callbacks
- No visual redesign; structural only

## Implementation Details
### 1. New Modules
- sidebar_panel_v2.py
- preview_panel_v2.py
- layout_manager_v2.py (optional)
- status_bar_v2.py (existing but updated)

### 2. MainWindow Changes
- Replace inline widget trees with panel instances
- Move helper functions to panel classes
- Add registration hooks for callbacks

### 3. Tests
- test_gui_v2_mainwindow_split_structure.py
- test_gui_v2_panel_wiring.py

## Risks / Mitigations
- Callback miswiring → covered via tests
- Layout drift → snapshot tests

## Migration Notes
- No breaking changes to external API.
- All V1 tests remain in legacy folder.

## Next Steps
- Advanced stage-panel features
- AI-driven config surfaces
- Learning loop integration
