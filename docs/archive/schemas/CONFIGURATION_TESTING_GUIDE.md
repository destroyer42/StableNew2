# Configuration Testing Guide

This document explains how to maintain configuration parameter integrity in StableNew.

## Overview

The StableNew pipeline uses a hierarchical configuration system that flows from:
1. **GUI Forms** → 2. **Configuration Objects** → 3. **Pipeline Methods** → 4. **WebUI API Payloads**

Configuration drift (parameters getting lost along this chain) can cause unexpected generation results, so we validate parameter pass-through with automated testing.

## Running Validation Tests

**ALWAYS run this test when making configuration-related changes:**

```bash
python tests/test_config_passthrough.py
```

**Expected results:**
- Success rate should be 90-100% for each preset
- Missing parameters indicate pipeline issues that need fixing
- Value changes are flagged but some are expected (like prompt modifications)

## When to Run the Test

**Required scenarios:**
- Adding new parameters to `src/utils/config.py`
- Modifying pipeline methods in `src/pipeline/executor.py`
- Updating GUI form handling in `src/gui/main_window.py`
- Creating new presets in `presets/` directory
- Modifying API client methods in `src/api/client.py`

**Optional scenarios:**
- Before major releases
- When investigating generation inconsistencies
- When onboarding new developers

## Adding New Configuration Parameters

### Step-by-Step Process:

1. **Update Configuration Schema** (`src/utils/config.py`):
   ```python
   def get_default_config():
       return {
           "txt2img": {
               # ... existing parameters ...
               "new_parameter": default_value,  # Add here
           }
       }
   ```

2. **Add GUI Controls** (`src/gui/main_window.py`):
   - Add form widget in appropriate tab
   - Update `_get_config_from_forms()` method
   - Update `_load_config_into_forms()` method

3. **Update Pipeline Methods** (`src/pipeline/executor.py`):
   - Add parameter to appropriate payload in `run_txt2img()`, `run_img2img()`, or upscale methods

4. **Test Configuration Pass-Through**:
   ```bash
   python tests/test_config_passthrough.py
   ```

5. **Update Presets** (if needed):
   - Add parameter to relevant preset files in `presets/` directory

### Validation Test Maintenance

The validation test (`tests/test_config_passthrough.py`) automatically detects new parameters, but you may need to update it for special cases:

**Parameter Categories in Validation:**
- `separate_api_params`: Set via separate API calls (model, vae)
- `optional_params`: May be absent from payload when empty/disabled
- `modified_ok_params`: Expected to be modified (prompt, negative_prompt)

**To add special handling for new parameters:**
```python
# In validate_stage_parameters method around line 170
separate_api_params = {"model", "vae", "new_special_param"}
optional_params = {"styles", "hr_second_pass_steps", "new_optional_param"}
modified_ok_params = {"negative_prompt", "prompt", "new_modified_param"}
```

## Understanding Test Results

### Success Indicators:
- ✅ **Parameter validated**: Found in payload with expected value
- 🔄 **Modified as expected**: Parameter changed but change is allowed
- ➖ **Optional parameter**: Empty/disabled parameter not included (normal)
- 🔄 **Separate API call**: Set via model/VAE switching (normal)

### Failure Indicators:
- ❌ **Missing parameter**: Should be in payload but isn't found
- ⚠️ **Value changed**: Parameter value differs from config (investigate)

### Typical Success Rates:
- **Default preset**: Should achieve 100% (all parameters standard)
- **High-quality preset**: Should achieve 95-100% (may have optional parameters)
- **Custom presets**: Should achieve 90-100% (depending on optional features)

## Common Issues and Solutions

### Low Success Rate (< 90%)
**Probable causes:**
- New parameters added to config but not included in pipeline payloads
- Parameter names don't match between config and API
- Pipeline methods not updated after config changes

**Solutions:**
- Check pipeline methods in `src/pipeline/executor.py`
- Verify parameter names match WebUI API documentation
- Ensure GUI forms are correctly reading/writing config

### Parameters Not Appearing in Payloads
**Check:**
1. Is the parameter included in the payload construction in pipeline methods?
2. Are there typos in parameter names?
3. Is the parameter conditionally excluded (check if conditions)?

### GUI Changes Not Reflected
**Check:**
1. Are form values being read in `_get_config_from_forms()`?
2. Is the config being passed correctly to the pipeline?
3. Are form widgets properly bound to config values?

## Preset-Specific Considerations

When creating new presets, ensure they work with the validation system:
- Use standard parameter names from `get_default_config()`
- Include all required parameters for your use case
- Test the preset with the validation script before committing

## Debugging Tips

**Enable verbose logging:**
```python
# In tests/test_config_passthrough.py, modify logging level
logging.basicConfig(level=logging.DEBUG)
```

**Inspect captured payloads:**
The test captures all API payloads. You can modify the test to print them:
```python
print(f"Captured payload: {json.dumps(payload, indent=2)}")
```

**Test individual presets:**
```python
# Modify the key_presets list to test specific presets
key_presets = ["your_specific_preset"]
```

Remember: **Configuration integrity is critical for consistent generation results!**
