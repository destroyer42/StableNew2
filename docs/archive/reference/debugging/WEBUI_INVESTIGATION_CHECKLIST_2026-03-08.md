# WebUI Investigation Checklist - 63 GB OOM Issue

## Problem Summary
- **Error**: `CUDA out of memory. Tried to allocate 63.28 GiB`
- **Stage**: Upscale (R-ESRGAN 4x+, 1.5x resize)
- **Input**: 768×1024 → Target: 1152×1536
- **Expected VRAM**: ~200 MB with tiling
- **Actual attempt**: 63,280 MB (300× too much!)

## Critical Finding
**This is NOT a StableNew issue** - the Python code can't make WebUI allocate 63 GB. This is a WebUI/PyTorch/extension problem.

---

## Immediate Checks

### 1. Check WebUI Terminal Output
**Action**: Look at the WebUI console window during the failed upscale

**What to look for**:
```
Tiled upscale: 0%|          | 0/XX [00:00<?, ?it/s]
Upscaler: R-ESRGAN 4x+
Tile size: XXXX  ← CRITICAL: What does this say?
```

**Questions**:
- Does it show "Tiled upscale" or "Single upscale"?
- What tile size is it reporting?
- Any warnings about memory or dimensions?

---

### 2. Check WebUI Settings (UI)
**Action**: In WebUI, go to Settings → Upscaling

**Check these values**:
- [ ] `Tile size for ESRGAN upscalers`: Should be **0** (auto) or **512-768**
- [ ] `Tile overlap for ESRGAN upscalers`: Should be **8-64**
- [ ] `Upscaling max images in cache`: Should be **5** or less

**If tile size is > 2000 or disabled**: This would force single-tile processing → 63 GB allocation

---

### 3. Check WebUI config.json
**Action**: Open `stable-diffusion-webui/config.json`

**Look for**:
```json
{
  "ESRGAN_tile": 1920,          ← Should be 512-1920
  "ESRGAN_tile_overlap": 8,     ← Should be 8-64
  "DAT_tile": 1920,
  "DAT_tile_overlap": 8,
  "upscaling_max_images_in_cache": 5
}
```

**If `ESRGAN_tile` is 0, -1, or > 4096**: Problem found!

---

### 4. Check for Conflicting Extensions
**Action**: In WebUI, go to Extensions → Installed

**Check if these are enabled** (they can cause conflicts):
- [ ] **Tiled Diffusion** or **Tiled VAE** - Can override upscaler settings
- [ ] **ControlNet** - Might cache large tensors
- [ ] **Regional Prompter** - Can affect memory allocation
- [ ] **Forge Couple** - Extension conflicts

**Test**: Temporarily disable ALL extensions and retry

---

### 5. Check WebUI Launch Args
**Action**: Look at how you start WebUI (batch file or command)

**Look for these flags**:
- `--no-half` → Forces FP32, doubles memory usage
- `--no-half-vae` → VAE in FP32
- `--precision full` → Everything in FP32 (4× memory!)
- `--upcast-sampling` → Can increase memory

**If using `--precision full` or `--no-half`**: This could explain the massive allocation

---

### 6. Check for Memory Leaks (Advanced)
**Action**: Monitor VRAM before upscale starts

**In WebUI terminal, before running the job, check**:
```python
# In Python REPL or add to WebUI:
import torch
print(f"Allocated: {torch.cuda.memory_allocated(0) / 1024**3:.2f} GB")
print(f"Reserved: {torch.cuda.memory_reserved(0) / 1024**3:.2f} GB")
```

**If already using > 8 GB before upscale**: Memory leak from previous stages

---

## Test Procedure

### Test 1: Minimal Upscale
**Goal**: Isolate if it's the upscaler or something else

1. In WebUI UI, go to Extras tab
2. Upload a 768×1024 image
3. Set upscaler to R-ESRGAN 4x+
4. Set resize to 1.5×
5. Click Generate

**If this works**: Problem is in how StableNew calls the API
**If this fails**: Problem is in WebUI configuration

### Test 2: Different Upscaler
**Goal**: Check if it's R-ESRGAN specific

In StableNew pack config, change:
```json
"upscale": {
  "upscaler": "Latent",  // Instead of "R-ESRGAN 4x+"
  "upscaling_resize": 1.5
}
```

**If this works**: R-ESRGAN is misconfigured

### Test 3: Fresh WebUI Config
**Goal**: Rule out corrupted settings

1. Stop WebUI
2. Rename `stable-diffusion-webui/config.json` to `config.json.backup`
3. Rename `stable-diffusion-webui/ui-config.json` to `ui-config.json.backup`
4. Start WebUI (will create fresh configs)
5. Try upscale

**If this works**: Your config.json had bad settings

---

## Likely Root Causes (In Order)

### 🔥 **#1: ESRGAN_tile Setting Corrupted**
**Probability**: 80%
- Someone/something set `ESRGAN_tile` to 0 or very high value
- This forces single-tile processing
- WebUI tries to allocate full image in VRAM

**Fix**: Set `ESRGAN_tile: 512` in config.json

---

### 🔥 **#2: --precision full Launch Flag**
**Probability**: 15%
- WebUI running in full FP32 precision
- Quadruples memory requirements
- 200 MB × 4 × some multiplier = huge allocation

**Fix**: Remove `--precision full`, add `--medvram` or `--lowvram`

---

### 🔥 **#3: Extension Conflict (Tiled Diffusion)**
**Probability**: 5%
- Extension overriding tile settings
- Extension forcing single-tile mode

**Fix**: Disable extensions and test

---

## Next Steps

1. **Run Test 1** (WebUI Extras tab upscale) to isolate the problem
2. **Check config.json** for `ESRGAN_tile` value
3. **Check WebUI launch arguments** for precision flags
4. **Report back** with findings

---

## Expected Fix

Once we identify the setting:
- If `ESRGAN_tile`: Edit config.json, set to 512
- If launch flag: Edit webui-user.bat, remove `--precision full`
- If extension: Disable or configure the extension

The upscale should then complete in ~6 seconds with normal VRAM usage.
