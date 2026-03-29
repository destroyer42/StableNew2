PR-CORE-010 – Performance and Memory Optimization

Status: Specification
Priority: MEDIUM
Effort: MEDIUM
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableNew’s video generation pipeline combines large diffusion models (SDXL, JuggernautXL, etc.), LoRA overlays, and optional ControlNet or interpolation stages. These operations are memory‑intensive and, without optimization, can exceed the capacity of consumer GPUs (8–12 GB). The research exsum notes missing performance optimizations
newtab
. Meanwhile, diffusers offers XFormers memory‑efficient attention and half‑precision (FP16) to reduce memory consumption and improve throughput. This PR introduces performance and memory optimizations, including optional XFormers, configurable precision, and efficient memory management across the pipeline.

Goals & Non‑Goals
Goal: Enable XFormers memory‑efficient attention in StableNew’s SVD pipeline and ComfyUI nodes where available. Provide a configuration switch (use_xformers) that can be toggled globally or per job.
Goal: Allow users to choose precision mode (FP32 vs FP16) for inference. Default to FP16 on GPUs with sufficient support; allow fallback to FP32 on CPUs or older GPUs.
Goal: Optimize tensor and pipeline caching to reduce re‑initialization costs. For example, reuse loaded diffusers pipelines between jobs when the same model and LoRAs are used.
Goal: Document GPU memory requirements and provide guidelines (e.g. recommended batch sizes, memory usage when using LoRAs or ControlNet) to help users avoid out‑of‑memory (OOM) errors.
Non‑Goal: This PR does not implement multi‑GPU or distributed training/inference; such advanced scaling is deferred to future research.
Guardrails
Default behaviour must remain stable on CPUs and older GPUs without XFormers or FP16 support. When enabling XFormers or FP16 fails, the system should catch the exception, log a warning, and continue in FP32 mode with standard attention.
Precision settings must not degrade output quality significantly; users should be informed of any trade‑offs.
Pipeline caching must account for LoRA or model changes; if the model or LoRAs differ from the cached instance, reload the pipeline to ensure correctness.
Allowed Files
Files to Modify
src/video/svd_service.py – update the pipeline initialization code to check for use_xformers and use_half_precision flags in the configuration. If enabled and the GPU supports it, call pipe.enable_xformers_memory_efficient_attention() and set dtype=torch.float16 or torch.bfloat16 as appropriate. Provide try/except to handle import errors.
src/video/svd_runner.py or equivalent runner – propagate performance flags from the job config to the SVD service.
src/pipeline/config_contract_v26.py – add optional fields use_xformers (bool) and precision (enum of fp16, fp32, bf16) to the intent schema.
src/utils/preferences.py – allow users to set default performance preferences in settings.
src/gui/views/settings_frame.py – add checkboxes or drop‑downs to enable XFormers and select precision. Provide tooltips explaining memory impact.
tests/video/test_performance_flags.py – new unit tests verifying that enabling XFormers and half precision calls the appropriate diffusers APIs and that the system falls back gracefully when unsupported.
Files to Create
tests/video/test_performance_flags.py – as described.
Forbidden Files
Do not modify model checkpoint files or diffusers internals. All optimizations must use public APIs.
Implementation Plan
Add config options: Extend the configuration schema to include use_xformers (default false) and precision (default fp16 on CUDA GPUs, otherwise fp32). Provide CLI flags and UI settings to override these values.
Modify SVD service: During pipeline initialization, inspect these flags. If use_xformers is true, attempt to import xformers and call pipe.enable_xformers_memory_efficient_attention(). Catch ImportError and disable the flag. Set the pipeline’s dtype to torch.float16 or torch.bfloat16 when precision is fp16 or bf16. Document that FP16 may not be supported on all GPUs.
Cache pipelines: Implement caching logic keyed by (model_id, use_xformers, precision, lora_hashes) to reuse loaded pipelines across jobs. Use a simple dictionary in svd_service.py. Ensure that when LoRAs or models change, the cache entry is invalidated.
UI integration: Add toggles in the settings panel. When saving settings, update the default config. Expose these settings in the “Advanced” section of job submission forms.
Testing: Write unit tests mocking the diffusers pipeline to verify that enabling XFormers calls the correct API and that invalid states fall back gracefully. Write integration tests to verify that the configuration flags propagate from UI to svd_service.
Documentation: Provide a table of memory usage estimates and guidelines. For example, note that SDXL at 1024×1024 in FP16 uses ~8 GB without LoRAs, and adding LoRAs or ControlNet increases this by ~2 GB. Recommend reducing resolution if memory is insufficient.
Testing Plan
Unit tests: Mock a diffusers pipeline and assert that enable_xformers_memory_efficient_attention is called when use_xformers is true. Test that the pipeline dtype is set based on precision. Test that caching yields the same pipeline instance for identical configs.
Integration tests: Simulate a job submission with use_xformers and verify that the SVD service logs the correct mode. Use a dummy pipeline to avoid GPU requirements.
Manual tests: On a GPU machine, run sample jobs with and without XFormers/FP16 and monitor memory consumption using tools like nvidia-smi.
Verification Criteria
The configuration schema includes performance options and defaults behave correctly across CPU and GPU environments.
Enabling XFormers yields a measurable reduction in memory usage (verify via manual tests) and does not crash on platforms without XFormers.
Selecting precision=fp16 or bf16 sets the pipeline dtype accordingly and does not degrade the quality of generated images/videos.
Caching reuses pipelines when appropriate, reducing initialization times.
All new tests pass and existing functionality is unaffected.
Risk Assessment
Medium risk: While enabling XFormers can drastically reduce memory usage, it depends on the underlying CUDA environment and may introduce instability on unsupported GPUs. Mitigate by detecting support and falling back gracefully.
Quality risk: Lower precision may introduce subtle artefacts or degrade colour fidelity. Provide warnings and allow users to opt out.
Complexity: Pipeline caching must be implemented carefully to avoid reusing pipelines across incompatible jobs. Validate model and LoRA hashes to ensure correctness.
Tech Debt Analysis

Introducing performance flags addresses a critical usability issue for users with limited hardware. However, toggling these flags across multiple modules (UI, config, service) adds code paths. Consolidate flag handling in a utility module to reduce duplication. Future debt includes exploring additional optimizations (e.g. Torch compile/traced models) and multi‑GPU support.

Documentation Updates
Update configuration and user guide to explain the new performance options and how to enable them.
Provide guidelines on selecting precision and using XFormers, including hardware prerequisites.
Dependencies
Requires xformers to be available in the environment. Update requirements-svd.txt or installation instructions. Provide fallbacks if xformers is not installed.
No other external dependencies.
Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @infra‑team
Approval Status: Pending

Next Steps

After enabling XFormers and FP16, monitor performance and memory usage in real workflows. Gather feedback and consider exposing additional controls (e.g. batch size, gradient checkpointing) or integrating advanced memory optimizations. Explore multi‑GPU and CPU‑offload strategies in subsequent releases.

