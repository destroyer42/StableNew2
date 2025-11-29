
# JT-05 — Upscale Stage Run (Journey Test Specification)
### Version: 2025-11-26_1134
### StableNewV2 — High-Fidelity Journey Test Document

## 1. Summary
Validates the Upscale stage as both a standalone operation and as the final step in a multi-stage pipeline (txt2img → upscale). Ensures proper image routing, model selection, upscale factor application, and metadata preservation through the enlargement process.

## 2. Problem
The Upscale stage must correctly accept input images, apply model-specific enlargement algorithms, and output properly sized final images without losing critical metadata. Multi-stage pipelines must seamlessly pass images between stages while maintaining workflow integrity.

## 3. Goals

- Validate standalone Upscale stage operation with various models and factors
- Confirm correct image routing from Pipeline tab to Upscale processing
- Verify upscale factor, tile size, and model selection parameters
- Test multi-stage flow: txt2img → Upscale pipeline execution
- Ensure metadata preservation through upscale transformation
- Validate output resolution calculations and image quality

## 4. Non-Goals

- Video pipeline integration
- Learning system upscale experiments
- Custom model training or fine-tuning
- Performance benchmarking beyond basic functionality
- Upscale model comparison or optimization

## 5. Preconditions

- JT-03 (txt2img Pipeline Run) completed successfully or baseline test image available
- Pipeline tab fully operational with stage configuration
- Upscale models (UltraSharp, ESRGAN, etc.) available in WebUI
- AppController and PipelineState properly initialized
- WebUI connection established and responsive

## 6. Test Steps

### 6.1 Standalone Upscale Test

1. Launch StableNewV2 application
2. Load a baseline test image (512x512 or known resolution)
3. Navigate to Pipeline tab
4. Disable all stages except Upscale
5. Configure Upscale parameters:
   - Upscale factor: 2.0x
   - Model: UltraSharp
   - Tile size: 512 (if applicable)
   - Denoise strength: 0.3 (if applicable)
6. Execute Upscale stage
7. Validate output:
   - Image resolution is correctly doubled (1024x1024)
   - Image quality maintained without artifacts
   - Metadata preserved (prompt, parameters, etc.)

### 6.2 Multi-Stage Pipeline Test (txt2img → Upscale)

1. Reset Pipeline tab configuration
2. Enable txt2img stage with basic parameters:
   - Prompt: "a beautiful landscape"
   - Steps: 20
   - Resolution: 512x512
3. Enable Upscale stage with:
   - Factor: 2.0x
   - Model: ESRGAN
4. Execute full pipeline (txt2img → upscale)
5. Validate intermediate and final outputs:
   - txt2img produces 512x512 image
   - Upscale receives txt2img output as input
   - Final output is 1024x1024 with expected quality
   - Pipeline metadata shows both stages executed

### 6.3 Parameter Variation Test

1. Test different upscale factors (1.5x, 2.0x, 4.0x)
2. Test different models (UltraSharp, ESRGAN, 4x-UltraSharp)
3. Test tile size variations (256, 512, 1024)
4. Verify resolution calculations for each combination

## 7. Expected Artifacts

- Standalone upscaled image with correct resolution (e.g., 1024x1024 from 512x512)
- Multi-stage pipeline output showing txt2img base + upscaled result
- Pipeline execution logs showing stage progression
- Metadata files containing upscale parameters and model information
- StructuredLogger entries documenting the upscale operations

## 8. Edge Cases

- Upscale factor resulting in non-integer dimensions (e.g., 1.5x on 512px = 768px)
- Very large upscale factors (4x, 8x) on small input images
- Upscale on already high-resolution images (2048x2048 → 4096x4096)
- Model unavailability or WebUI upscale model errors
- Pipeline interruption between txt2img and upscale stages
- Memory constraints with large tile sizes on limited RAM
- Unicode characters in upscale model names or parameters

## 9. Acceptance Criteria

- Standalone upscale produces correctly sized output image
- Multi-stage txt2img → upscale pipeline executes successfully
- Upscale factors (1.5x, 2x, 4x) produce expected resolution changes
- Multiple upscale models (UltraSharp, ESRGAN) are selectable and functional
- Metadata preservation through upscale transformation
- Pipeline state correctly tracks upscale stage execution
- Error handling for invalid upscale parameters or model failures
- Image quality maintained without significant artifacts or distortion

## 10. Rollback Plan

- If upscale stage fails: Disable upscale stage, verify txt2img still works independently
- If multi-stage fails: Test stages individually, check PipelineState serialization
- Collect WebUI logs and StructuredLogger entries for debugging
- Revert to previous Pipeline configuration if regression detected
- Verify baseline image processing still functions without upscale
