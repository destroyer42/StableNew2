# StableNewV2 – GUI V2 Progress Summary (PR-1 → PR-2)
### Reference Document for Repo History & Architecture Continuity  
### Version: 2025-11  

## Overview
This document summarizes all work completed between the Prompt Tab development sequence (PR-1A → PR-1H), the structural Notebook refactor (PR-MAIN-TAB-HOST-REF-001), and the early Pipeline Tab wiring (PR-2A → PR-2B).  

---

# PR-00 — Global Notebook Refactor  
## PR-MAIN-TAB-HOST-REF-001 – Notebook now owns the entire workspace

### Problem
Previously the GUI had global left/right panels visible regardless of tab, restricting usable space and causing unrelated UI to remain visible.

### Work Completed
- Removed global left/right panels  
- Notebook now spans entire workspace  
- Each tab owns its own three-column layout  
- StatusBarV2 remains global  

### Result
Prompt, Pipeline, Learning tabs are now fully isolated workspaces.

---

# PR-1 — Advanced Prompt Editor Development  
*(PR-1A → PR-1H Completed)*

## PR-1A — Add Prompt Tab Scaffold
- Created `PromptTabFrame`  
- Added placeholder label  

## PR-1B — Three-Column Layout
- Added left “Prompt Packs”, center “Editor Grid”, right “Metadata”  

## PR-1C — PromptPackModel + PromptWorkspaceState
- Added stable model + state classes  
- Introduced default Untitled pack  

## PR-1D — Parsing Utilities
- Implemented lora/embedding parser  
- Added matrix helper dialog  

## PR-1E — Wiring Text Editor + Metadata
- Editable prompt slots  
- Live metadata parsing  
- Matrix helper integration  

## PR-1F — Save/Load Prompt Packs
- JSON-based prompt pack format  
- New/Open/Save/Save As  
- Dirty-state tracking  

## PR-1G — Prompt → Pipeline Preview
- Added read-only accessors  
- Metadata preview extended  
- Pipeline preview stub added  

## PR-1H — Pipeline Prefers PromptWorkspaceState
- Execution reads active prompt from PromptWorkspaceState  
- Backward-compatible fallback  

---

# PR-2 — Pipeline Workspace Development  
*(PR-2A → PR-2B Completed)*

## PR-2A — Pipeline Tab Scaffold
- Created `PipelineTabFrame`  
- Placeholder label  

## PR-2B — Pipeline Layout Skeleton
- Added RunControlBar placeholder  
- Added PipelineConfigPanel, StageCardsPanel, PreviewPanel placeholders  

---

# Required Documentation Updates

## ARCHITECTURE_v2_COMBINED.md
- Update GUI structure to match full-width Notebook  
- Document Prompt/Pipeline/Learning workspace separation  

## StableNew_GUI_V2_Program_Plan  
- Add PR-00 summary  
- Add PR-1 and PR-2 milestones  

## Phase2 Layout & Wiring Docs
- Replace outdated left/center/right global layout diagrams  

## ACTIVE_MODULES.md
Add:
- prompt_pack_model  
- prompt_workspace_state  
- lora_embedding_parser  
- matrix_helper_widget  

## Phase4 Testing Docs
- Add prompt save/load  
- Add metadata parsing  
- Add RunPlan testing requirements  

---

# Summary
This document records all structural and functional changes performed between PR-1 and PR-2 and should be retained as a stable reference point for future architectural work.
