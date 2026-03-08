# VAE Empty String Handling Fix

## Issue
When users selected "No VAE (model default)" in the GUI, the system was still submitting a VAE to the job. Looking at the manifest files, even though the config had `"sd_vae": ""` (empty string), the final job would have `"vae": "sdxl_vae.safetensors"`.

## Root Cause
Multiple locations in the pipeline were using the `or` operator with a fallback value when handling VAE config:

```python
# OLD BUGGY CODE:
requested_vae = config.get("vae") or config.get("vae_name") or "Automatic"
```

Python's `or` operator treats empty strings as falsy, so when the config had `"sd_vae": ""`, it would default to `"Automatic"`. WebUI would then interpret "Automatic" and select its default VAE (e.g., `sdxl_vae.safetensors`).

## Solution
Changed VAE handling to distinguish between:
- **Key not present** (`None`) → Don't set VAE (let WebUI use its current setting)
- **Empty string** (`""`) → User explicitly selected no VAE (don't send to WebUI)
- **Non-empty value** → Set the specified VAE

```python
# NEW CORRECT CODE:
requested_vae = config.get("vae") if "vae" in config else config.get("vae_name")
if requested_vae:  # Only set if non-empty
    self.client.set_vae(requested_vae)
```

## Files Modified

### 1. `src/pipeline/executor.py`
Fixed VAE handling in 5 methods:
- `_run_txt2img_impl()` (line ~1428)
- `run_img2img_stage()` (line ~1664)
- `_run_img2img_impl()` (line ~1821)
- `run_adetailer()` (line ~1960)
- `run_txt2img_stage()` (line ~3254-3275)
- `run_upscale_stage()` (line ~3744)

### 2. `src/pipeline/payload_builder.py`
Fixed `_build_base_payload()` (line ~114):
```python
"sd_vae": config.get("vae") if "vae" in config else config.get("vae_name"),
```

### 3. `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
Fixed initial VAE mapping (line ~165) to be consistent:
```python
self._vae_name_map[self.NO_VAE_DISPLAY] = ""  # Empty string means no VAE selected
```

## Verification
Created `test_vae_empty_string.py` to verify:
- ✅ Empty string VAE is preserved (not defaulted to "Automatic")
- ✅ Missing VAE key returns None
- ✅ Specified VAE is preserved

## Expected Behavior After Fix

### When user selects "No VAE (model default)":
- GUI sets config: `"vae": ""`
- Pipeline checks: `if requested_vae:` → `False` (empty string is falsy)
- Pipeline action: **Does not call** `client.set_vae()`
- WebUI uses: Model's baked VAE (if present) or its default
- Manifest shows: Whatever WebUI reports as current VAE

### When user selects a specific VAE:
- GUI sets config: `"vae": "sdxl_vae.safetensors"`
- Pipeline checks: `if requested_vae:` → `True`
- Pipeline action: Calls `client.set_vae("sdxl_vae.safetensors")`
- WebUI uses: The specified VAE
- Manifest shows: `"vae": "sdxl_vae.safetensors"`

### When VAE is not in config (legacy/missing):
- Config has no `vae` key
- Pipeline gets: `requested_vae = None`
- Pipeline checks: `if requested_vae:` → `False`
- Pipeline action: **Does not call** `client.set_vae()`
- WebUI uses: Current VAE (whatever was last set)
- Manifest shows: Query WebUI for current VAE

## Testing Recommendations
1. Test with SDXL model with baked VAE (e.g., Juggernaut XL)
   - Select "No VAE (model default)"
   - Verify manifest does NOT show external VAE
   
2. Test with model without baked VAE (e.g., SD 1.5)
   - Select "No VAE (model default)"
   - Verify manifest shows WebUI's default/Automatic VAE
   
3. Test with explicit VAE selection
   - Select specific VAE
   - Verify manifest shows the selected VAE

## Related Files
- GUI VAE selection: `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- Pipeline execution: `src/pipeline/executor.py`
- Payload building: `src/pipeline/payload_builder.py`
- WebUI client: `src/api/client.py`

## Impact
This fix ensures that models with baked VAEs (like most modern SDXL models) can be used without forcing an external VAE, which can cause color oversaturation or other issues.
