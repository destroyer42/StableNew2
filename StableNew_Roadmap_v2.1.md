
# StableNew Roadmap v2.1

## Strategic Pivot Summary (V1 → V2)
StableNew V2 is a rebuild of the product around modularity, learning-driven optimization, distributed pipelines, and UI/UX designed for clarity and power. The pivot replaces the tangled V1 stack with a layered architecture, strong adapter boundaries, testable pipeline engines, and a UI based on composable “stage cards”.

## Phase 0 — Foundation (Complete)
- GUI V2 skeleton
- Stage cards (Txt2Img, Img2Img, Upscale)
- Adapters for pipeline/status/randomizer/learning
- Learning groundwork (records, metadata, dataset builder)
- Randomizer V2
- StatusBarV2
- PipelineIO contracts
- Stage Sequencer
- Safety isolation

## Phase 1 — Under-the-Hood Finalization (Next)
1. PR-GUI-V2-MAINWINDOW-REDUCTION-001  
   Refactor main_window.py into layout vs. lifecycle vs. event binder vs. adapter bridge.

2. PR-GUI-V2-PANEL-CONSOLIDATION-001  
   Normalize panel structure for future Learning UI, Variant Explorer, AI Settings Wizard.

3. PR-V2-PIPELINE-STAGE-ENGINE-001  
   Introduce StageEngines enabling distributed execution, stage-level introspection, and debugging.

4. PR-GUI-V2-RANDOMIZER-UX-002 (Completed)  
   Full randomizer UI with matrix UX, previews, risk bands.

5. PR-AI-V2-SETTINGS-GENERATOR-001 (Completed)  
   Stub LLM-driven settings generator.

6. PR-GUI-V2-LEARNING-UI-001  
   UI for rating outputs and improving future runs.

7. PR-V2-DISTRIBUTED-PIPELINE-001  
   Controller–worker architecture for running pipelines across multiple machines.

## Philosophy
Learning-first for accuracy. Randomizer-first for variety. UI and architecture developed together, not sequentially.
