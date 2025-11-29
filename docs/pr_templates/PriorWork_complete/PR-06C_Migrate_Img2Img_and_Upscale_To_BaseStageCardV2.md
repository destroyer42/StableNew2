# PR-06C — Migrate Advanced Img2Img & Upscale Stage Cards to BaseStageCardV2

## Summary

This PR continues the migration started in PR-06B:

- `advanced_img2img_stage_card_v2` and `advanced_upscale_stage_card_v2` are refactored to:
  - Subclass `BaseStageCardV2`
  - Use shared components where appropriate

The goal is to align all **advanced** stage cards with the new componentized architecture while preserving their existing behavior.

---

## Goals

1. Make both advanced img2img and upscale cards use `BaseStageCardV2`.  
2. Share prompt/sampler/seed UI patterns with txt2img via components where it makes sense.  
3. Keep external interfaces and controller interactions stable.

---

## Implementation

### 1. Refactor `advanced_img2img_stage_card_v2`

File:

```text
src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py
```

Changes:

- Import the base and components:

```python
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.components import PromptSection, SamplerSection, SeedSection
```

- Subclass `BaseStageCardV2` and implement `_build_body` similarly to txt2img, but respecting any img2img-specific fields (e.g., strength/denoise):

```python
class AdvancedImg2ImgStageCardV2(BaseStageCardV2):
    def __init__(self, master, controller, initial_values, **kwargs):
        super().__init__(
            master,
            title="Image to Image",
            description="Transform an input image using your prompt and settings.",
            **kwargs,
        )
        self.controller = controller
        self.initial_values = initial_values

    def _build_body(self, parent: ttk.Frame) -> None:
        self.prompt_section = PromptSection(parent, title="Prompt")
        self.prompt_section.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        self.sampler_section = SamplerSection(parent)
        self.sampler_section.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        # Denoise/strength control (img2img-specific)
        # Preserve any existing behavior/limits:
        self._build_strength_controls(parent, row=2)

        self.seed_section = SeedSection(parent)
        self.seed_section.grid(row=3, column=0, sticky="ew")

        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        parent.rowconfigure(2, weight=0)
        parent.rowconfigure(3, weight=0)
```

- Factor out any img2img-specific custom bits (e.g., a `_build_strength_controls` helper) to keep `_build_body` readable.

### 2. Refactor `advanced_upscale_stage_card_v2`

File:

```text
src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py
```

Changes:

- Import the base and relevant components:

```python
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.components import SamplerSection, SeedSection
```

- Subclass `BaseStageCardV2` and only include relevant sections (upscale may not need a full prompt entry):

```python
class AdvancedUpscaleStageCardV2(BaseStageCardV2):
    def __init__(self, master, controller, initial_values, **kwargs):
        super().__init__(
            master,
            title="Upscale",
            description="Upscale generated or existing images using the configured upscaler.",
            **kwargs,
        )
        self.controller = controller
        self.initial_values = initial_values

    def _build_body(self, parent: ttk.Frame) -> None:
        # Upscale-specific controls go here: factor, upscaler choice, tile size, etc.
        # Where sampler/seed apply (e.g. when using certain models), reuse components.
        # Example:

        # Upscale factor and mode controls (preserve existing behavior)
        self._build_upscale_controls(parent, row=0)

        self.seed_section = SeedSection(parent)
        self.seed_section.grid(row=1, column=0, sticky="ew")

        parent.rowconfigure(0, weight=0)
        parent.rowconfigure(1, weight=0)
        parent.columnconfigure(0, weight=1)
```

Where possible, reuse component sections to avoid duplicated code.  
Where not appropriate (e.g., upscaler-specific knobs), keep the existing widget code, just placed inside the `body_frame`.

### 3. Keep Interfaces Stable & Tests Passing

- Do **not** rename these classes or modules.  
- Keep constructor signatures aligned with current call sites. Where adjustments are necessary, update the corresponding imports/instantiations (e.g., in `PipelinePanelV2`).  
- Update `tests/gui_v2` tests that look at img2img/upscale cards to inspect the new structure, but keep assertions focused on “controls exist and behave” rather than exact widget hierarchy.

---

## Files Touched

**Updated:**

- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`
- Any GUI tests that explicitly validate these cards (under `tests/gui_v2/`).

**Not Touched:**

- Txt2img card (already migrated in PR-06B).  
- Prototype stage cards in `src/gui/`.

---

## Acceptance Criteria

- App launches and both img2img and upscale stage cards are visible and functional.  
- All GUI V2 tests pass (with updated expectations where necessary).  
- All advanced stage cards now inherit from `BaseStageCardV2` and use components where appropriate.
