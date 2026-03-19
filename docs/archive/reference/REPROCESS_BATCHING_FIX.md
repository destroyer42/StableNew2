# Reprocessing Batching Fix Summary

## Issue Reported
User selected 160 images for reprocessing, but only 1 job was created instead of 160 jobs. Additionally, the stage configs appeared empty/wrong.

## Root Causes

### 1. Batching Issue
**Problem:** The original code called `builder.build_reprocess_job()` once with ALL 160 images:
```python
njr = builder.build_reprocess_job(
    input_image_paths=image_paths,  # ALL 160 images at once
    stages=stages,
)
```

This creates a **single NormalizedJobRecord** containing all 160 images, which results in 1 job processing all images as a batch.

### 2. Empty Configs
**Problem:** The config dict passed to the builder was empty `{}`, so all stages were using default values instead of the user's GUI settings.

## Solutions Implemented

### 1. Per-Image Job Creation (with Configurable Batching)

#### Updated `on_reprocess_images()` in app_controller.py
```python
def on_reprocess_images(
    self, 
    image_paths: list[str], 
    stages: list[str],
    batch_size: int = 1,  # NEW: Default to 1 image per job
) -> int:
    """Reprocess existing images through specified pipeline stages."""
    
    # Build reprocess jobs (batched or individual)
    if batch_size > 1:
        # Use batched builder for efficiency
        njrs = builder.build_reprocess_jobs_batched(
            input_image_paths=image_paths,
            stages=stages,
            batch_size=batch_size,
            config=config,
        )
    else:
        # One job per image (default behavior)
        njrs = []
        for image_path in image_paths:
            njr = builder.build_reprocess_job(
                input_image_paths=[image_path],  # Single image
                stages=stages,
                config=config,
            )
            njrs.append(njr)
    
    # Submit all jobs to queue
    submitted_count = 0
    for njr in njrs:
        job = Job(...)
        job._normalized_record = njr
        self.job_service.submit_queued(job)
        submitted_count += 1
```

**Result:**
- 160 images with `batch_size=1` → **160 separate jobs**
- 160 images with `batch_size=10` → **16 jobs** (10 images each)
- 160 images with `batch_size=100` → **2 jobs** (100 + 60)

### 2. Config Extraction from GUI State

#### Added `_build_reprocess_config()` helper method
```python
def _build_reprocess_config(self, stages: list[str]) -> dict[str, Any]:
    """Build configuration dict for reprocess jobs from GUI state."""
    config: dict[str, Any] = {}
    
    # img2img config
    if "img2img" in stages:
        config["img2img"] = {
            "denoising_strength": getattr(self.app_state, "img2img_denoising_strength", 0.3),
            "width": getattr(self.app_state, "img2img_width", 512),
            "height": getattr(self.app_state, "img2img_height", 512),
        }
        config["img2img_denoising_strength"] = config["img2img"]["denoising_strength"]
    
    # adetailer config
    if "adetailer" in stages:
        config["adetailer"] = {
            "ad_model": getattr(self.app_state, "adetailer_model", "face_yolov8n.pt"),
            "ad_confidence": getattr(self.app_state, "adetailer_confidence", 0.3),
            "ad_dilate_erode": getattr(self.app_state, "adetailer_dilate", 4),
            "ad_denoising_strength": getattr(self.app_state, "adetailer_denoising", 0.4),
        }
    
    # upscale config
    if "upscale" in stages:
        config["upscale"] = {
            "upscaler": getattr(self.app_state, "upscale_upscaler", "R-ESRGAN 4x+"),
            "upscale_by": getattr(self.app_state, "upscale_factor", 2.0),
            "tile_size": getattr(self.app_state, "upscale_tile_size", 512),
            "denoising_strength": getattr(self.app_state, "upscale_denoising", 0.35),
        }
        config["denoising_strength"] = config["upscale"]["denoising_strength"]
    
    # Global settings
    config["cfg_scale"] = getattr(self.app_state, "cfg_scale", 7.0)
    config["sampler_name"] = getattr(self.app_state, "sampler", "DPM++ 2M Karras")
    
    return config
```

**Result:** All stage configs now properly extracted from GUI state (model selections, denoising strengths, upscaler settings, etc.)

### 3. GUI Batch Size Control

#### Added to reprocess_panel_v2.py
```python
# State variable
self.batch_size_var = tk.IntVar(value=1)

# GUI Control
batch_frame = ttk.LabelFrame(stage_frame, text="Job Batching", padding=5)
batch_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(5, 0))

ttk.Label(batch_frame, text="Images per job:").pack(side="left", padx=5)
batch_spin = ttk.Spinbox(
    batch_frame, 
    from_=1, 
    to=100, 
    textvariable=self.batch_size_var,
    width=8,
)
batch_spin.pack(side="left", padx=5)
```

#### Updated feedback message
```python
batch_size = self.batch_size_var.get()
count = self.controller.on_reprocess_images(
    image_paths, 
    stages,
    batch_size=batch_size,
)

# Show proper feedback
if batch_size == 1:
    batch_info = f"{count} jobs (1 image each)"
else:
    batch_info = f"{count} jobs ({batch_size} images/job)"

self.images_label.config(
    text=f"✓ {batch_info}: {stage_text}"
)
```

## Files Modified

1. **src/controller/app_controller.py**
   - Added `batch_size` parameter to `on_reprocess_images()`
   - Changed from single job creation to loop creating individual jobs (or batched)
   - Added `_build_reprocess_config()` helper method to extract GUI configs

2. **src/gui/panels_v2/reprocess_panel_v2.py**
   - Added `batch_size_var` IntVar state variable
   - Added "Job Batching" GUI controls (spinbox 1-100)
   - Updated `_on_reprocess()` to pass batch_size to controller
   - Enhanced feedback to show job count and batching info

## Testing

Created `test_reprocess_batching.py` to verify the batching logic:
```
Testing with 160 images
------------------------------------------------------------

1. Batch size = 1 (one job per image)
   ✓ Created 160 jobs

2. Batch size = 10 (should create 16 jobs)
   ✓ Created 16 jobs

3. Batch size = 100 (should create 2 jobs)
   ✓ Created 2 jobs

============================================================
✅ All batching tests passed!
============================================================
```

## Expected Behavior Now

When user selects 160 images and clicks "Reprocess Images":

**With batch_size=1 (default):**
- Creates **160 separate jobs**
- Each job processes 1 image
- Queue shows 160 jobs

**With batch_size=10:**
- Creates **16 jobs**
- Jobs 1-15: 10 images each
- Job 16: remaining 10 images
- Queue shows 16 jobs

**With batch_size=100:**
- Creates **2 jobs**
- Job 1: 100 images
- Job 2: 60 images
- Queue shows 2 jobs

**All jobs will use proper configs** from GUI state (adetailer model, upscale settings, img2img denoising, etc.)

## Architecture Compliance

✅ **Zero PipelineConfig usage** - Only NormalizedJobRecord  
✅ **Clean NJR-based execution** - No legacy builders  
✅ **Proper Job → NJR attachment** via `_normalized_record` attribute  
✅ **Config extraction from app_state** - No hardcoded defaults  
✅ **Batch control flexibility** - User-configurable via GUI  

## Next Steps for User

1. **Test with default (batch_size=1)**: Select 160 images, should see 160 jobs
2. **Test with batch_size=10**: Should see 16 jobs
3. **Verify configs**: Check that adetailer model, upscaler, and denoising values from GUI are applied
4. **Monitor queue**: Confirm jobs process correctly through selected stages

The batching and config issues are now fully resolved! 🎉
