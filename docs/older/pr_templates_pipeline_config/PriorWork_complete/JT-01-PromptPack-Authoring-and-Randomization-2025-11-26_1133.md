
# JT-01 — Prompt Pack Authoring and Randomization (Journey Test Specification)
### Version: 2025-11-26_1133
### StableNewV2 — High-Fidelity Journey Test Document

## 1. Summary
Validates complete authoring workflow of Prompt Packs: 10 prompts, 5-line structure, randomization tokens, LoRA/embedding markers, global negative prompt, save/load fidelity, and Pipeline metadata integration.

## 2. Problem
Prompt Packs must be reliable sources of truth. Broken parsing or save/load fidelity disrupts Pipeline and Learning subsystems.

## 3. Goals
- Create new Prompt Pack
- Populate structured prompt text
- Use randomization tokens like {{sunset|sunrise|night}}
- Add LoRA tokens <lora:name:0.8> and embedding:name
- Save/load with 100% fidelity
- Confirm LoRA/embedding metadata appears in Pipeline tab

## 4. Non-Goals
- Running a pipeline
- Learning integration
- Styles/presets

## 5. Preconditions
- PR-1A through PR-1H implemented
- Prompt tab operational
- PromptWorkspaceState stable

## 6. Test Steps
1. Launch StableNew
2. New Prompt Pack
3. Fill P1–P10 with multi-line text
4. Add randomization tokens {{A|B|C}} in several lines
5. Add global negative prompt
6. Add LoRA markers <lora:foo:0.7>
7. Save Prompt Pack
8. Reload; ensure full fidelity
9. Open Pipeline tab; verify metadata present

## 7. Expected Artifacts
- Prompt Pack file
- Metadata structures populated

## 8. Edge Cases
- Nested randomization {{{A|B}|C}}
- Unicode
- LoRA without strength
- Negative prompt containing {}

## 9. Acceptance Criteria
- 100% save/load fidelity
- Correct metadata parsing in both tabs

## 10. Rollback
- Collect logs
- Revert Prompt parser or workspace if regression detected
