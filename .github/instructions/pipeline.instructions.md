# Pipeline Folder Instructions

## Responsibilities
- Implement txt2img, img2img, upscale, and sequential pipeline execution.
- Keep logic pure; no Tk imports.
- Provide clear data models for stage configs.

## Rules
- Do not access GUI or read files directly that GUI should provide.
- Keep side effects minimal and confined to I/O functions in controlled modules.

## Testing
- Mirror all pipeline updates in `tests/pipeline/`.
