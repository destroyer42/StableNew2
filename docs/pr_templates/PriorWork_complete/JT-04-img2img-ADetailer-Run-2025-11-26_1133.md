
# JT-04 — img2img and ADetailer Pipeline Run (Journey Test Specification)
### Version: 2025-11-26_1133
### StableNewV2 — High-Fidelity Journey Test Document

## 1. Summary
Validates img2img and ADetailer workflows, ensuring a base image is properly transformed using configured parameters.

## 2. Problem
img2img must consume a base image and produce a transformed image without losing prompt context or metadata.

## 3. Goals
- Validate img2img stage activation
- Validate correct handling of base image
- Validate ADetailer interactions
- Verify output images differ appropriately from input

## 4. Preconditions
- JT-03 generated a base image OR base test image available
- Pipeline tab fully operational

## 5. Test Steps
1. Load base image from disk or prior txt2img output
2. Switch to Pipeline tab
3. Enable img2img stage
4. Set denoise to 0.45
5. Enable ADetailer
6. Click Run stage only
7. Confirm:
   - Base image used
   - Output transformed correctly
   - Preview and metadata updated

## 6. Expected Artifacts
- img2img-transformed image
- Logs confirming correct input path
- Metadata including denoise level

## 7. Edge Cases
- Very low denoise values
- Missing base image path
- ADetailer misconfiguration

## 8. Acceptance Criteria
- img2img pipeline completes without error
- Output image respects configuration
- Base → transformed lineage trace is correct

## 9. Rollback
Remove img2img/ADetailer config binding changes if failures occur
