
# JT-03 — txt2img Pipeline Run (Journey Test Specification)
### Version: 2025-11-26_1133
### StableNewV2 — High-Fidelity Journey Test Document

## 1. Summary
Validates the complete txt2img generation flow using the Pipeline tab.

## 2. Problem
Pipeline tab must correctly configure txt2img settings and deliver final images with correct metadata.

## 3. Goals
- Validate stage toggles
- Validate sampler, scheduler, CFG, steps, batch size inputs
- Confirm prompt injection from Prompt tab
- Generate final images
- Display preview with correct metadata

## 4. Preconditions
- WebUI reachable (READY state)
- JT-01 complete (prompt pack available)

## 5. Test Steps
1. Open Pipeline tab
2. Enable txt2img stage only
3. Select prompt pack entry
4. Set parameters:
   - sampler: Euler
   - scheduler: Karras
   - steps: 25
   - CFG: 7
   - batch size: 2
5. Click Run
6. Confirm:
   - Stage card shows running → complete
   - Image preview appears
   - Metadata matches configuration

## 6. Expected Artifacts
- Two generated images
- Image metadata (sampler, scheduler, seed, CFG)

## 7. Edge Cases
- Empty negative prompt fallback
- Prompt with multiple randomization tokens
- Invalid parameter input (negative steps)

## 8. Acceptance Criteria
- Successful image generation
- Metadata accuracy
- No UI freeze or exceptions

## 9. Rollback
Disable Pipeline parameter delta logic if run fails due to misbinding
