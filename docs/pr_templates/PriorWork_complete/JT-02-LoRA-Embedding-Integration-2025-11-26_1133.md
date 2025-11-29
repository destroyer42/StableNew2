
# JT-02 — LoRA and Embedding Integration (Journey Test Specification)
### Version: 2025-11-26_1133
### StableNewV2 — High-Fidelity Journey Test Document

## 1. Summary
Validates Prompt → Pipeline metadata continuity for LoRA and embedding tokens.

## 2. Problem
LoRA tokens must be parsed consistently, preserved across save/load, and surfaced as runtime controls in Pipeline tab.

## 3. Goals
- Detect LoRA syntax <lora:name:strength>
- Detect embedding markers embedding:name
- Verify controls appear in Pipeline tab
- Ensure LoRA/embedding influence prompt preview metadata

## 4. Preconditions
- JT-01 completed successfully
- Prompt pack with LoRA and embedding tokens exists

## 5. Test Steps
1. Load Prompt Pack containing LoRA markers
2. Inspect Prompt metadata panel
3. Switch to Pipeline tab
4. Confirm:
   - LoRA names appear as sliders
   - Embeddings appear in metadata list
5. Change LoRA slider values
6. Confirm metadata updates before run

## 6. Expected Artifacts
- Correctly populated LoRAModelConfig entries
- PromptWorkspaceState → PipelineState transfer validated

## 7. Edge Cases
- Multiple LoRAs in same prompt
- Missing strength value
- Embedding tokens combined with randomization

## 8. Acceptance Criteria
- Pipeline tab exposes all LoRAs/embeddings defined in prompt text
- No parse errors or omissions

## 9. Rollback
Revert LoRA/Embedding parsing logic if needed
