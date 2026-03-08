# Outstanding Issues Resolution Plan — Comprehensive PR Suite

**Generated**: December 27, 2025  
**Status**: Ready for Implementation  
**Total PRs**: 4

---

## Overview

This document indexes the comprehensive PR suite created to address all remaining issues from [Outstanding Issues-26DEC2025-1649.md](../Oustanding%20Issues-26DEC2025-1649.md).

**Previously Completed**: 26 issues resolved via:
- PR-GUI-DARKMODE-001
- PR-GUI-FUNC-001
- PR-GUI-LAYOUT-001
- PR-GUI-FUNC-002
- PR-GUI-CLEANUP-001

**This PR Suite**: 14 remaining issues across 4 new PRs

---

## PR Suite Summary

| PR | Issues Addressed | Priority | Effort | Risk |
|----|------------------|----------|--------|------|
| [PR-GUI-TOOLTIPS-001](#pr-gui-tooltips-001) | 2h, 2i, 2j, 2l | Medium | 4-6h | Low |
| [PR-GUI-FUNC-003](#pr-gui-func-003) | 2d, 2f, 3d, 3g | High | 6-8h | Medium |
| [PR-GUI-LAYOUT-002](#pr-gui-layout-002) | 2a, 2g, 2k, 3b, 3c | Medium | 8-10h | Medium |
| [PR-GUI-DARKMODE-002](#pr-gui-darkmode-002) | 2c, 2e, 3a, 3e, 1f, 1n | Low | 4-6h | Low |

**Total Estimated Effort**: 22-30 hours  
**Total Issues Resolved**: 14 issues + verification tasks

---

## PR-GUI-TOOLTIPS-001

**Add Help Text & Tooltips for ADetailer Configuration**

### Issues Addressed
- **2h**: Add tooltips for Confidence, Max detections, Mask blur, Mask merge mode
- **2i**: Add tooltips for Mask filtering section
- **2j**: Add tooltips for Mask Processing section
- **2l**: Add tooltips for Inpaint Settings

### Implementation Components
1. Create `HoverTooltip` widget component
2. Define comprehensive help text for all configs
3. Add inline help labels + hover tooltips to ADetailer stage card
4. Add inline help labels + hover tooltips to Img2Img inpaint settings

### Key Features
- Reusable tooltip system for entire GUI
- Centralized help text documentation
- Short inline descriptions + detailed hover tooltips
- Dark mode compatible

### Files Modified
- `src/gui/widgets/tooltip_widget.py` (CREATE)
- `src/gui/help_text/adetailer_help.py` (CREATE)
- `src/gui/help_text/inpaint_help.py` (CREATE)
- `src/gui/stage_cards_v2/adetailer_stage_card_v2.py` (MODIFY)
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py` (MODIFY)

### Testing
- Unit tests for tooltip widget behavior
- Manual testing of tooltip display for all configs
- Verification of layout integrity

**Estimated Effort**: 4-6 hours  
**Risk**: Low (GUI-only, no logic changes)

---

## PR-GUI-FUNC-003

**Functional Enhancements (Refiner Default, Hires Logic, Queue Feedback, Output Fix)**

### Issues Addressed
- **2d**: SDXL Refiner Start default needs to be 80%
- **2f**: Hires fix "Use base model during hires" functionality
- **3d**: Queue reordering visual feedback
- **3g**: Variant counter and output folder path

### Implementation Components
1. Set refiner_start default to 0.8 (80%) when loading configs
2. Implement hires "Use base model" checkbox auto-sync with dropdown disable
3. Add immediate visual feedback when reordering queue jobs
4. Fix variant counter incrementing logic
5. Fix "Open Output Folder" to use actual job output directory

### Key Features
- Smart defaults for SDXL refiner
- Automatic model syncing for hires fix
- Real-time queue reordering feedback
- Correct output folder navigation

### Files Modified
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py` (MODIFY)
- `src/gui/panels_v2/queue_panel_v2.py` (MODIFY)
- `src/pipeline/output_manager_v2.py` (MODIFY - if needed)
- `src/controller/app_controller.py` (MODIFY - if needed)

### Testing
- Unit tests for default values
- Unit tests for hires model sync
- Unit tests for queue reordering display
- Manual testing of all functional enhancements

**Estimated Effort**: 6-8 hours  
**Risk**: Medium (controller interaction required)

---

## PR-GUI-LAYOUT-002

**Layout Optimizations (CFG Slider, Dropdowns, Prompts, Preview)**

### Issues Addressed
- **2a**: CFG slider should span full frame width
- **2g**: Adetailer Mask merge mode dropdown width
- **2k**: Prompt field sizing (3 lines with scrollbars)
- **3b**: Preview frame layout optimization
- **3c**: Preview panel prompt display

### Implementation Components
1. Make CFG slider expand to full width (responsive)
2. Reduce ADetailer dropdown width to align with spinboxes
3. Convert prompt fields from Entry to Text widgets (3 lines + scrollbars)
4. Redesign preview panel with two-column layout (thumbnail right, info left)
5. Expand prompt display in preview to show full text

### Key Features
- Responsive slider widths
- Multi-line prompt fields with scrollbars
- Better space utilization in preview panel
- Full prompt text visibility

### Files Modified
- `src/gui/enhanced_slider.py` (INVESTIGATE/MODIFY)
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py` (MODIFY)
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py` (MODIFY)
- `src/gui/stage_cards_v2/adetailer_stage_card_v2.py` (MODIFY)
- `src/gui/preview_panel_v2.py` (MODIFY)
- `src/gui/widgets/multi_line_prompt_field.py` (CREATE - optional)

### Testing
- Unit tests for layout configurations
- Manual testing of responsive behavior
- Verification of Text-to-StringVar sync
- Layout regression testing

**Estimated Effort**: 8-10 hours  
**Risk**: Medium (significant layout changes)

---

## PR-GUI-DARKMODE-002

**Remaining Dark Mode Fixes & Verification Tasks**

### Issues Addressed
- **2c**: SDXL Refiner label dark mode
- **2e**: Hires fix label dark mode
- **3a**: Preview thumbnail checkbox dark mode
- **3e**: Running Job seed display and text field dark mode
- **1f**: Global Prompts functionality verification
- **1n**: Reprocess 'Refresh filter' button purpose

### Implementation Components
1. Verify/fix LabelFrame.Label style in theme
2. Add dark mode styles to Running Job panel labels
3. Verify seed value population in Running Job panel
4. Verify Global Prompts save/load functionality
5. Verify Global Prompts prepending logic (or implement if missing)
6. Clarify Refresh Filter button purpose with rename/tooltip

### Key Features
- Complete dark mode coverage
- Functional Global Prompts system
- Clear button purposes with tooltips

### Files Modified
- `src/gui/theme_v2.py` (VERIFY/MODIFY)
- `src/gui/panels_v2/running_job_panel_v2.py` (MODIFY)
- `src/gui/sidebar_panel_v2.py` (VERIFY)
- `src/controller/app_controller.py` (VERIFY/MODIFY)
- `src/controller/job_builder_v2.py` (VERIFY/MODIFY)
- `src/gui/panels_v2/reprocess_panel_v2.py` (VERIFY/MODIFY)

### Testing
- Unit tests for styling completeness
- Unit tests for global prompts logic
- Manual testing of dark mode consistency
- Verification of Global Prompts behavior
- Clarification of Refresh Filter functionality

**Estimated Effort**: 4-6 hours  
**Risk**: Low (mostly verification, minor fixes)

**Special Note**: If Global Prompts prepending logic is missing, this may require escalation to a separate feature PR.

---

## Implementation Order Recommendation

### Phase 1: Quick Wins (Low Risk)
1. **PR-GUI-DARKMODE-002** - Complete dark mode coverage and verification tasks
2. **PR-GUI-TOOLTIPS-001** - Add helpful tooltips and documentation

### Phase 2: Functional Improvements (Medium Risk)
3. **PR-GUI-FUNC-003** - Critical functional enhancements

### Phase 3: Layout Polish (Medium Risk)
4. **PR-GUI-LAYOUT-002** - Layout optimizations requiring extensive testing

**Rationale**: Start with low-risk styling and documentation, then tackle functional fixes, finally handle complex layout changes that require more testing.

---

## Testing Strategy

### Unit Testing
- Create test files for each PR
- Test widget creation and configuration
- Test functional logic separately from GUI
- Achieve >80% code coverage for new code

### Manual Testing
- Test each feature in isolation
- Test feature interactions
- Test on different window sizes
- Test with different prompt pack configurations
- Test with different models and settings

### Regression Testing
- Verify previously completed PRs still work
- Check that no existing functionality breaks
- Validate dark mode consistency across all changes
- Confirm no performance degradation

---

## Tech Debt Addressed

Across all PRs:
- ✅ Incomplete dark mode coverage
- ✅ Missing user guidance (tooltips)
- ✅ Inconsistent defaults
- ✅ Poor visual feedback
- ✅ Layout inefficiencies
- ✅ Broken navigation
- ✅ Unclear button purposes
- ✅ Limited prompt visibility

---

## Documentation Updates Required

After completing all PRs:

1. **Outstanding Issues Document**:
   - Mark all 14 issues as FIXED or VERIFIED
   - Update summary counts
   - Archive completed issues

2. **User Documentation**:
   - Document Global Prompts feature
   - Document ADetailer configuration options
   - Document queue management features
   - Document keyboard shortcuts

3. **Developer Documentation**:
   - Document tooltip system usage
   - Document multi-line prompt field component
   - Document layout patterns for future development

4. **CHANGELOG**:
   - Add entries for all 4 PRs
   - Highlight user-facing improvements
   - Note any breaking changes (unlikely)

---

## Post-Implementation Review

After all PRs are completed:

1. **User Testing Session**:
   - Have actual users test the GUI
   - Collect feedback on tooltip helpfulness
   - Verify layout improvements are intuitive
   - Check for any missed issues

2. **Performance Check**:
   - Verify no performance degradation
   - Check memory usage
   - Validate responsive behavior

3. **Code Quality**:
   - Run linters on all modified files
   - Check for code duplication
   - Verify consistent naming conventions
   - Ensure proper error handling

4. **Future Improvements**:
   - Identify remaining polish opportunities
   - Document enhancement ideas
   - Prioritize next round of GUI improvements

---

## Estimated Timeline

**Assuming single developer working sequentially:**

- PR-GUI-DARKMODE-002: 1 day
- PR-GUI-TOOLTIPS-001: 1 day
- PR-GUI-FUNC-003: 1-2 days
- PR-GUI-LAYOUT-002: 1-2 days
- Testing & Refinement: 1 day
- Documentation: 0.5 days

**Total**: 5-7 days (1 week sprint)

**With parallel work** (2 developers):
- Developer A: PR-GUI-DARKMODE-002 + PR-GUI-TOOLTIPS-001 (2 days)
- Developer B: PR-GUI-FUNC-003 + PR-GUI-LAYOUT-002 (3-4 days)
- Joint: Testing & Documentation (1 day)

**Total**: 4-5 days

---

## Success Metrics

### Completion Criteria
- ✅ All 14 issues marked as FIXED or VERIFIED
- ✅ All unit tests passing
- ✅ Manual testing confirms all features work
- ✅ No regressions in existing functionality
- ✅ Dark mode consistent across entire GUI
- ✅ Outstanding Issues document updated

### Quality Metrics
- Code coverage >80% for new code
- Zero critical bugs
- <3 minor bugs requiring follow-up
- Positive user feedback on improvements
- Maintainable, documented code

---

## Conclusion

This PR suite provides a comprehensive solution to all remaining GUI issues in the Outstanding Issues document. Each PR is:

- **Well-scoped**: Clear boundaries and file lists
- **Testable**: Detailed unit and manual testing requirements
- **Documented**: Implementation plans and notes
- **Safe**: Architecture-compliant (no pipeline changes)
- **Trackable**: Clear definition of done and post-implementation tasks

All PRs follow the v2.6 governance model and respect architectural boundaries. They can be implemented sequentially or in parallel, depending on resource availability.

**Next Step**: Review and approve PRs, then proceed with implementation in recommended order.
