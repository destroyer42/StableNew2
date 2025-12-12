# PR-GUI-V2-STAGE-PANELS-ADVANCED-001  
**Title:** Advanced Pipeline Stage Panels (Txt2Img / Img2Img / Upscale) — V2 Architecture Expansion  
**Status:** Ready for CODEX Execution  
**Applies To:** StableNew-MoreSafe-11-21-2025-0818.zip (current repo baseline)  
**Author:** ChatGPT (Architect)  
**Target Implementer:** CODEX 5.1-max  
**Safety Profile:** Full SAFE wrapper required  

---

# 1. Purpose

This PR expands the StageCard architecture introduced earlier and upgrades the GUI V2 pipeline panels into *production-grade*, feature-complete stage editors.  
The goal is to replace legacy ConfigPanel complexity with a predictable, maintainable, modular system that is:

- **Fully stage-isolated**  
- **Tk-safe and import-safe**  
- **Compatible with the central PipelineAdapterV2**  
- **Composable for cluster-based orchestration later**  
- **Prepared for learning-mode feature integration**

---

# 2. Motivation

V1’s GUI grew organically over hundreds of commits and became:

- Bloated  
- Hard to test  
- Hard to read  
- Impossible to safely refactor  

The new architecture transitions the system into **modular stage panels**, each owning:

1. Their Tk widget layout  
2. Their validation rules  
3. Their config load/merge logic  
4. Their adaptive UI states  

This PR implements the **advanced stage panels** that bring the Txt2Img, Img2Img, and Upscale editors toward final production form.

---

# 3. Scope

### **Included**
- Full implementation of **Advanced Txt2ImgStageCardV2**, **Img2ImgStageCardV2**, **UpscaleStageCardV2**
- Validation frameworks for each stage  
- Improved layout: labeled sections, grouping, tooltips  
- Conversion helpers:
  - `load_from_config`
  - `to_config_dict`
  - `validate() → ValidationResult`
- Integration with `PipelinePanelV2`
- Updates to:
  - `app_layout_v2.py`
  - `PipelineAdapterV2`
  - GUI V2 tests
- New tests:
  - Stage card layout tests  
  - Roundtrip tests  
  - Validation tests  
  - Safety tests  

### **Not Included**
- No executor changes  
- No WebUI / backend changes  
- No learning-mode integration (future)  
- No cluster scheduling logic  
- No AI-setting generator modifications  

---

# 4. Architectural Details

## 4.1 New Files
```
src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py
src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py
src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py
src/gui/stage_cards_v2/validation_result.py
```

## 4.2 Updated Files
```
src/gui/pipeline_panel_v2.py
src/gui/app_layout_v2.py
src/pipeline/pipeline_adapter_v2.py
src/gui_v2/adapters/pipeline_adapter_v2.py
```

## 4.3 Key Concepts

### **StageCardV2 Base Contract**
All stage panels implement:

```python
class StageCardV2:
    def load_from_config(self, cfg: dict): ...
    def to_config_dict(self) -> dict: ...
    def validate(self) -> ValidationResult: ...
    @property
    def panel_header(self) -> str: ...
```

### **ValidationResult**
```
class ValidationResult:
    ok: bool
    message: Optional[str]
```

### **Txt2Img Advanced Capabilities**
- Sampler  
- Scheduler  
- Steps  
- CFG scale  
- Width/height  
- Clip skip  
- Model dropdown  
- VAE dropdown  
- Tooltips for best practices  

### **Img2Img Advanced Capabilities**
- Denoising strength  
- Reuse seed toggle  
- Strength curves  
- Resolution locks  

### **Upscale Advanced Capabilities**
- Upscaler type  
- Model  
- Factor  
- Tile size  
- Face restore toggle  

---

# 5. Detailed Implementation Requirements

## 5.1 Implement Advanced Txt2ImgStageCardV2

Must include:

- Header: “Txt2Img Configuration”
- Labeled fields with ttk widgets
- Tk variables:
  - `model_var`
  - `vae_var`
  - `sampler_var`
  - `scheduler_var`
  - `steps_var`
  - `cfg_var`
  - `width_var`
  - `height_var`
  - `clip_skip_var`
- Validation:
  - Steps >= 1  
  - CFG between 1–30  
  - Width/height divisible by 8  
- `to_config_dict()` mapping to:
  ```
  {
      "model_name": ...,
      "vae_name": ...,
      "sampler_name": ...,
      "scheduler_name": ...,
      "steps": ...,
      "cfg_scale": ...,
      "width": ...,
      "height": ...,
      "clip_skip": ...
  }
  ```

## 5.2 Implement Advanced Img2ImgStageCardV2

Required fields:

- Denoise strength (0–1)
- Sampler
- CFG scale
- Width/height (optional override)
- Mask mode (future placeholder)

## 5.3 Implement Advanced UpscaleStageCardV2

Required fields:

- Upscaler type dropdown
- Factor (integer)
- Tile size
- Face restore toggle

---

# 6. GUI Wiring

Update:

### `pipeline_panel_v2.py`
- Replace simple placeholder cards with full advanced cards  
- Ensure cards are instantiated in consistent order  
- Add `validate_full_pipeline()`  
- Update calls to adapter

### `app_layout_v2.py`
- Ensure advanced cards appear in correct layout zone  
- Maintain visual hierarchy  

---

# 7. Tests

## New test files:
```
tests/gui_v2/test_gui_v2_advanced_stage_cards_layout.py
tests/gui_v2/test_gui_v2_advanced_stage_cards_roundtrip.py
tests/gui_v2/test_gui_v2_advanced_stage_cards_validation.py
tests/safety/test_advanced_stage_cards_import_safety.py
```

## Assertions:
- Stage cards build successfully  
- All Tk variables exist  
- Roundtrip load/save matches input  
- Validation catches invalid input  
- No Tk imports leak into adapters  

---

# 8. Safety Requirements

All new modules must include the SAFE wrapper:

1. No new Tk imports outside GUI directories  
2. No backend imports  
3. No file system writes  
4. All API surfaces typed  
5. No execution on import  

---

# 9. CODEX Execution Instructions (DROP INTO CODEX CHAT)

Copy/paste:

```
You are executing PR-GUI-V2-STAGE-PANELS-ADVANCED-001.

Follow these rules EXACTLY:

1. Modify ONLY the files listed in the PR.
2. Implement the full advanced stage panels:
   - AdvancedTxt2ImgStageCardV2
   - AdvancedImg2ImgStageCardV2
   - AdvancedUpscaleStageCardV2
3. Add ValidationResult and full validation paths.
4. Update PipelinePanelV2 and AppLayoutV2 to use the new cards.
5. Update PipelineAdapterV2 to consume stage card config dicts.
6. Ensure all GUI V2 tests pass or add new ones where specified.
7. Maintain ZERO Tk imports in non-GUI modules.
8. Maintain backwards compatibility in the adapter.
9. Do not modify executor or backend components.
10. All code must be SAFE-wrapper compliant.

After implementation:
- Run pytest tests/gui_v2 -v
- Run pytest tests/safety -v
- Run pytest -v
Report results.
```

---

# 10. Expected Outcome

- Stable, advanced stage editors  
- Predictable GUI V2 architecture  
- Full compliance with SAFE rules  
- No behavior regressions  
- Foundation for future features:
  - Learning-system auto-suggestions  
  - AI settings generator  
  - Cluster distributed pipelines  

---

# 11. Merge Checklist

- [ ] All GUI V2 tests pass  
- [ ] Validation is complete  
- [ ] Roundtrip tests pass  
- [ ] SAFE tests pass  
- [ ] No Tk import leaks  
- [ ] Visual layout matches spec  

---

This PR transitions the GUI from “functional skeleton” → **“production-ready stage editor architecture.”**
