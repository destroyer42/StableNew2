# PR-GUI-V2-MIGRATION-005
## Title
V2 Stage Card Scaffolding — txt2img/img2img/upscale Panels + Unified Stage Registry

## Scope
Introduce Stage Cards for the three major pipeline stages:
- txt2img
- img2img
- upscale (ESRGAN/hiresfix/aux upscalers)

These are **empty-but-structured** cards prepared for future configuration fields.

## Included Changes
### 1. Stage Card Classes
Create:
- `src/gui/stages/txt2img_stage_card.py`
- `src/gui/stages/img2img_stage_card.py`
- `src/gui/stages/upscale_stage_card.py`

Each StageCard:
- is a ttk.Frame subclass
- has a header (e.g., “txt2img Stage”)
- has a scrollable body frame
- declares `load_from_config()` and `to_config_delta()` (stub)

### 2. Unified Stage Registry
Add:
```
src/gui/stages/stage_registry.py
```
Which:
- registers available stages
- declares order of rendering
- exposes `iter_stages()`
- is used by the central “PipelinePanelV2” to render stages automatically

### 3. PipelinePanelV2 Integration
Modify V2 pipeline panel to:
- auto-render StageCards based on the registry
- expose `stage_cards` dict
- merge deltas from each StageCard into the final config snapshot

### 4. Minimal Styling
Apply Theme v2 headers and card backgrounds.

### 5. Tests
Under:
```
tests/gui_v2/test_gui_v2_stage_cards.py
```
Tests verify:
- all StageCards import
- panel renders expected number of cards
- roundtrip stubs don’t crash
- registry ordering is respected

## Non-Goals
- no real config fields yet
- no per-stage logic
- no img2img source image binding
- no upscaler runtime behavior

## Success Criteria
- GUI V2 layout now includes StageCards
- tests/gui_v2 all pass
- StageRegistry integrated without affecting legacy GUI
