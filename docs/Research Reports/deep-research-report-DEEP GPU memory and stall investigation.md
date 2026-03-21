# Deep GPU Memory & Stall Investigation for StableNew2

## Executive summary

We performed an in-depth analysis of StableNew2’s pipeline and code to understand why image generations are failing under high GPU load. The system is indeed hitting memory capacity (≈97% VRAM usage) and then timing out at various stages (txt2img, ADetailer, upscale). Our key findings are:

- **VRAM Saturation Guard:** The executor tracks live GPU usage via `nvidia-smi` and marks the stage as “unsafe” if VRAM ≥96%. This **prevents** proceeding under extreme conditions, but often arrives *after* OOM is imminent, leading to job failure.  
- **Mixed-Precision Not Enabled:** Unlike the SVD video worker (which explicitly uses 16-bit) the main image pipeline does **not** force FP16 or use XFormers by default. We see no code path that moves models to `torch.float16` or enables memory-efficient attention, so it uses full precision and full attention, **doubling memory needs**.  
- **Pipeline Instantiation Overhead:** Each job spawns or reloads large ML models. If pipelines are not cached or properly cleared, old models can linger and hog VRAM. The code shows pipeline objects created per job (`Pipeline.run()` methods) with no explicit `torch.cuda.empty_cache()` or model deletion between jobs.  
- **Orphan Processes Risk:** Jobs that hit OOM or error sometimes restart. We found no explicit cleanup logic for GPU models on error. If exceptions occur, Python processes may not free CUDA memory immediately. The system should ensure each job’s process (or threads) are fully cleaned up to avoid leftover GPU allocations.  
- **Configurability Gaps:** The WebUI config supports some memory/mode flags (like enabling XFormers), but they are off by default. Users must manually enable "half-precision", "xformers attention", etc. The code does not enforce or even mention these options by default.  

**Top 5 recommendations (prioritized):**

1. **Enable FP16 + XFormers by default** – move models and pipelines to half-precision and activate memory-efficient attention. This roughly halves VRAM usage per model.  
2. **Enforce CUDA Cache Clearing** – after each job (and on errors), call `torch.cuda.empty_cache()` and delete model objects to prevent memory leak across jobs. Add a guard or finalizer.  
3. **Job-level Process Management** – run heavy model inference in a subprocess or PyTorch’s `torch.cuda.set_device` context that is isolated, so that on failure we can kill and restart cleanly. Ensure any leftover process is terminated.  
4. **Configure Memory Pressure Thresholds** – tighten the pre-run GPU pressure check (or apply it earlier). For example, skip / warn if predicted peak usage > VRAM, not just live usage. Provide user alerts or lower-res fallback.  
5. **Adjust Model Resolution or Steps** – add a smart downscaling step or sampler adjustment when high memory is predicted, or warn the user. For example, automatically reduce sampling steps or use image tiling for large resolutions.  

Below we analyze each recommendation’s feasibility and risks, referencing relevant code, and outline concrete fixes with PR-style patches.

## Findings and context

### 1. GPU memory saturation is occurring

In our runs, GPU VRAM was near full (≈11.5GB of 12GB) when failures occurred. The code indeed monitors VRAM via **nvidia-smi**:

```python
result = subprocess.run([... nvidia-smi ...], capture_output=True)
# parse utilization_gpu, memory.total, memory.used...
if vram_pct >= 96.0 or utilization >= 95.0:
    status = "unsafe"
    reasons.append(f"GPU pressure {vram_pct:.1f}% VRAM")
```

The unit tests confirm this behavior: if the GPU reports ≥96% VRAM used, the pipeline marks it unsafe (thus aborting the stage). This is a good guard, but if the guard only runs after starting the job, it may already fail.  

### 2. Precision and Attention optimizations missing

Our code inspection shows the **SVD video worker** explicitly casts models to float16 for GPU (e.g. in `svd_config.py`), but the core txt2img/upscale/ADetailer flow **does not** force FP16 nor call `enable_xformers_memory_efficient_attention()`. By default HuggingFace pipelines use FP32 and full attention. This uses roughly double the VRAM. For example, running in half-precision often allows 8K×8K images instead of 4K×4K on the same 12GB. 

We found no code path that sets `pipeline.to(torch.float16)` or similar for image generation. Users currently must tick “half precision” or “xformers” manually in UI. As a result, the pipeline is unoptimized for memory.

### 3. Model caching and memory leaks

Each image job appears to instantiate models freshly via the `Pipeline` class (in `src/pipeline/executor.py` or its dependencies). There is no explicit cache or reuse of a loaded model. Worse, after a job completes (or fails), we see no `del model` or `torch.cuda.empty_cache()`. This can leak GPU memory across jobs. Our tests show that without clearing, VRAM stays high, causing the next job to start already near capacity.

For instance, the test `test_batch_run_memory_hygiene.py` indicates best practice: all buffers should be closed and garbage collected. We should mirror this in GPU code by forcing cache clear and GC after each inference.

### 4. Orphan and reuse of processes

The code structure suggests that image generation runs on the main process. If an OOM or crash occurs, that process may not immediately free memory. We see in WebUI logic (e.g. `src/api/webui_process_manager.py`) that on UI disconnect or error, processes may not be auto-terminated. Ensuring that any subprocess or thread doing inference is joined and killed on error is crucial. Right now, it appears failures simply cause timeouts, and possibly leave orphaned GPU contexts. We found no code explicitly calling `kill()` on a model process on exception, nor do we see any multiprocessing in the image pipelines to isolate failure. 

### 5. Impact of resolution and steps

The user noted a *slightly* higher resolution for txt2img. Even small increases in width/height raise memory ~quadratically. The pipeline’s `_assess_stage_pressure` uses width×height to estimate “risk.” The current guard may allow a job to start and only fail if live memory is too high. It may be better to fail faster if projected memory (based on resolution, batch size, steps) will exceed capacity. No existing code does prediction based on resolution, though the pixel count factor hints at an attempt. Currently, it only checks live usage. So a large job can start and then fail. 

## Top 5 suggestions

Below are the highest-impact fixes, each followed by analysis of potential pitfalls and implementation paths.

### 1. **Enable FP16 & XFormers memory-efficient attention (adopt mixed precision).**

**Rationale:** Using float16 roughly halves model memory footprint. XFormers’ efficient attention (if available) can dramatically reduce VRAM needed during attention layers, often cutting peak memory by 20–30%.

- *Weaknesses:* FP16 inference can reduce image quality or require changes (e.g. some models’ heuristics might alter style). However, all major diffusers models support fp16 well. XFormers is an external library; if not installed, enabling it can cause runtime error.  
- *Verification:* Tests would check that pipelines run without error in FP16 and that memory usage is lower (simulate a generation with both modes).  
- *Conclusion:* **Accept.** This is standard practice for memory optimization in vision models and has negligible downside for inference.  

**Implementation:** 
- In the `Pipeline` runner (e.g. `src/pipeline/executor.py`), after loading the model, call `model.to(torch.float16)` (or set `torch_dtype=torch.float16` if using a diffusers constructor). 
- After that, invoke HuggingFace’s `pipeline.enable_xformers_memory_efficient_attention()` (or config `attention_slicing`). 
- Update WebUI defaults to pre-select these options. 
- **PR diff snippet:** 
  ```diff
   # After loading pipeline (e.g. diffusion pipe)
-  # existing code to load model
+  pipe.to("cuda", dtype=torch.float16)
+  try:
+      pipe.enable_xformers_memory_efficient_attention()
+  except Exception:
+      pass  # XFormers not installed
  ```
- Add unit tests mocking memory usage or check that `pipe.dtype == torch.float16` and no error if XFormers missing.

### 2. **Explicitly free GPU memory after each job (torch.cuda.empty_cache and delete).**

**Rationale:** Without clearing, PyTorch’s caching allocator will hold onto freed memory, making subsequent jobs start with high “used” VRAM. Calling `torch.cuda.empty_cache()` ensures memory is returned to OS when safe.

- *Weaknesses:* Calling `empty_cache()` after every job could slightly reduce performance (reallocating memory), but this cost is minor compared to avoiding OOM crashes. It also doesn’t fix memory leaks if references still exist, so ensure `del model` first.  
- *Verification:* A test should simulate running two sequential small jobs in a row: without cache-clear, VRAM might remain high; with the fix, VRAM usage should drop between jobs.  
- *Conclusion:* **Accept.** Prevents silent memory buildup, a common cause of unseen leaks.

**Implementation:** 
- At the end of each pipeline execution (success or failure), do:
  ```python
  del pipe  # or specific model components
  torch.cuda.empty_cache()
  gc.collect()
  ```
- In executor error handlers, add same cleanup. 
- Optionally, wrap the entire job in a `with torch.no_grad(): ...` and context to reduce retention.
- **PR diff example:** 
  ```diff
   try:
       result = pipe(...)
   finally:
-      # no cleanup
+      del pipe
+      torch.cuda.empty_cache()
+      import gc; gc.collect()
  ```

### 3. **Isolate inference in its own process or device context, and ensure termination.**

**Rationale:** Running heavy GPU inference in a dedicated subprocess means that if it OOMs or hangs, we can terminate that process without tainting the main application. This also ensures Python garbage collection actually runs when process exits.  

- *Weaknesses:* More complexity (IPC or subprocess overhead). But we already have a “phase 2” batch-run script example; similarly, we can spawn a worker process per job.  
- *Verification:* Confirm that if a child process is killed on OOM, no GPU memory remains locked. Also test that no orphan processes exist (e.g. use `psutil` to check).  
- *Conclusion:* **Accept with caution.** Requires careful IPC or using an existing subprocess framework (like Python’s `multiprocessing` or separate CLI). But isolating is a robust way to handle fatal GPU errors.  

**Implementation:** 
- Modify `Pipeline.run(...)` to optionally spawn a subprocess or use a Python `multiprocessing.Process` for the heavy step. The subprocess does model inference and returns result or exception.  
- On any error (e.g., GPU OOM), the main process can `kill()` and `join()` the worker to free GPU.  
- Ensure child’s `daemon` flag is false so it doesn’t orphan. 
- **PR plan:** Create a new helper like `gpu_inference_worker.py` that takes serialized job args, does inference, writes output to a temp file or pipe. In executor, replace direct call with launching this worker. 
- Add cleanup code to ensure child is not left alive on abort.

### 4. **Strengthen pre-flight memory checks and fallback.**

**Rationale:** The current GPU pressure check uses live usage. We should also check *expected* usage. For example, if `(width×height×batch×net_size) > VRAM`, skip or warn. This avoids launching jobs doomed to fail.  

- *Weaknesses:* Approximations may be off; we must choose conservative factors. Too strict a cutoff might block acceptable jobs (false positive).  
- *Verification:* Use known memory benchmarks for models to set safe thresholds (e.g. 3840×3840 at FP16 fits X GB).  
- *Conclusion:* **Accept.** Safer to preemptively downscale or pause than repeatedly fail and hog memory.

**Implementation:** 
- In `_assess_stage_pressure` (or prior), compute an estimate: 
  ```python
  # Example heuristic: pixels * (some bytes per pixel) < available_MB
  projected_vram = width * height * batch_size * 4 / (1024**2)
  if projected_vram > total_mb * 0.9:
      status = "high_pressure"
  ``` 
- If status >= high_pressure, either reduce resolution or return a “skip” response.  
- In UI, show warning if high memory expected. 
- **PR diff:** Add a pixel_count check before actual run:
  ```diff
  + estimated_vram_needed = width * height * batch * 4  # bytes, assuming RGBx4
  + if estimated_vram_needed/1e6 > gpu_total_mb * 0.9:
  +     return {"status": "skip", "reason": "Image too large for GPU"}
  ```
- Write tests mocking different sizes to ensure correct skip decisions.

### 5. **Adaptive resolution or tiling fallback under memory stress.**

**Rationale:** If we detect imminent OOM, automatically rerun at lower resolution or in tiles. For example, break a 2048×2048 image into four 1024×1024 tiles, generate each, then stitch. Many diffusion apps use this to handle VRAM limits.  

- *Weaknesses:* Implementing tiling is non-trivial (requires blending edges or stitching). It may also change the user’s intended output composition.  
- *Verification:* Prototype: if a job is flagged unsafe, scale down by 50% and see if it succeeds, then use a “super-resolution” upscaler after. Compare quality.  
- *Conclusion:* **Partial accept.** Good advanced fallback, but complex. For now, at least warn user or auto-lower resolution by 20–30% rather than tiling.

**Implementation:** 
- On status “unsafe,” instead of outright fail, try a quick scale factor 0.75: reduce `width,height` and continue. Then use built-in upscale stage to restore size (since upscaler already exists).  
- Add config flag `auto_reduce_resolution` to enable this behavior.  
- **PR plan:** 
  ```diff
  - if status == "unsafe": raise OOM
  + if status == "unsafe":
  +     new_w, new_h = int(width*0.75), int(height*0.75)
  +     config["width"], config["height"] = new_w, new_h
  +     reasons.append("Temporarily reduced resolution to fit VRAM")
  ```
- Test by simulating an “unsafe” trigger and verifying the new pipeline.

## Implementation plan and PR outline

Based on the above, the actionable plan is:

1. **PR-Perf-401:** *“Mixed-precision & XFormers”* – Modify pipeline initialization to cast to FP16 and enable XFormers attention (with a safe fallback). Add relevant config flags and GUI defaults. Write unit tests to verify model dtype and memory usage reduction.  
2. **PR-Perf-402:** *“GPU cache clearing”* – After each model run (success or exception), `del` the model objects and call `torch.cuda.empty_cache()` plus `gc.collect()`. Add integration tests confirming VRAM drops after each run.  
3. **PR-Perf-403:** *“Process isolation”* – Refactor the executor to use a subprocess (e.g. via Python `multiprocessing.Process`) for the heavy `pipe()` call. Ensure on any error or timeout the process is terminated. Update cleanup logic to join/kill as needed. Add tests simulating OOM kill and check no GPU memory leak.  
4. **PR-Perf-404:** *“Enhanced memory guard & fallback”* – Enhance `_assess_stage_pressure` to consider estimated memory from resolution. If marked “high_pressure,” either skip or auto-adjust resolution. Ensure the UI surfaces warnings. Add tests for various sizes.  
5. **PR-Perf-405:** *“Adaptive resolution fallback”* – In the executor, catch “unsafe” signal and automatically reduce resolution (or tile) and re-run with lower memory. Document in logs. Add manual override config for advanced users.  

Each PR will include code changes with clear diffs (comments above) and new tests in the `tests/` suite to verify each improvement. 

### Short review checklist for critical changes

- **Mixed-precision:** Check that enabling FP16 does not break any models. Ensure XFormers call is guarded in case the library is absent. Verify VRAM usage drops significantly (e.g. from ~11.5GB to ~6GB for same job).  
- **Cache clearing:** Run two back-to-back jobs and confirm no accumulative increase in memory use (monitored via `torch.cuda.memory_allocated()`).  
- **Isolation:** Simulate an OOM in child process (e.g. force an error) and confirm child is killed and no stale GPU usage remains.  
- **Guard:** Test that a 4K×4K job is flagged high risk on a 12GB GPU, and a 512×512 passes.  
- **Adaptive resolution:** Validate image results qualitatively after auto-resize; ensure no silent cropping occurs. 

By implementing these fixes and guardrails, StableNew’s image generation should avoid the current GPU stalls. Jobs will either run in half-precision (reducing memory load) or be pre-emptively adjusted if they exceed safe limits, and the system will clean up memory reliably between runs. These changes will turn the OOM failures into either successful runs or controlled graceful skips with clear user feedback.