# StableNew v2.6 Stage-Aligned Preset Pack

These presets are explicitly shaped to match the StableNew v2.6 preset JSON structure shown in your example.

## Stage alignment
- `txt2img`: base generation stage
- `img2img`: optional stage (disabled in most presets by default)
- `adetailer`: optional refinement stage (usually face-only; disabled for wide scenes/monsters)
- `upscale`: optional upscale + polish stage (enabled for most)
- `pipeline`: stage toggles + output settings

## Important notes
- `pipeline.output_dir` is set to `output` for portability. Change to your absolute output folder if needed.
- Prompts/negatives should remain PromptPack-driven (PromptPack-only prompt sourcing); these presets are config-only.

Generated: 2025-12-20T23:32:16.426433Z