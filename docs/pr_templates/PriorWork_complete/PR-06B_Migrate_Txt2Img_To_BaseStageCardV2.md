# PR-06B — Migrate Advanced Txt2Img Stage Card to BaseStageCardV2

## Summary

This PR is the **first actual migration** onto the new componentized stage-card model.

- Only **one** card is migrated: `advanced_txt2img_stage_card_v2`.
- It is refactored to **subclass `BaseStageCardV2`** and use the new components.
- External behavior and controller interactions should remain the same.

> If anything breaks, it will be limited to the txt2img card, making it easy to debug.

---

## Goals

1. Prove that `BaseStageCardV2` + shared components can express the existing txt2img UI.  
2. Keep public interfaces (class name, constructor signature, controller hooks) stable.  
3. Update only the tests related to txt2img card layout/behavior as needed.

---

## Implementation

### 1. Refactor `advanced_txt2img_stage_card_v2`

File:

```text
src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py
```

Refactor to:

- Import the new base and components:

```python
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.components import PromptSection, SamplerSection, SeedSection
```

- Subclass `BaseStageCardV2`:

```python
class AdvancedTxt2ImgStageCardV2(BaseStageCardV2):
    def __init__(self, master, controller, initial_values, **kwargs):
        # Adapt arguments to existing expectations: keep the same signature used elsewhere.
        super().__init__(
            master,
            title="Text to Image",
            description="Generate images from text prompts.",
            **kwargs,
        )
        self.controller = controller
        self.initial_values = initial_values
```

- Implement `_build_body` using components and any existing widgets that must remain:

```python
    def _build_body(self, parent: ttk.Frame) -> None:
        # Prompt
        self.prompt_section = PromptSection(parent, title="Prompt")
        self.prompt_section.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        # Negative prompt (optional: second PromptSection or a dedicated widget)
        # If the existing card has negative-prompt handling, preserve it here.
        # ...

        # Sampler/steps/CFG
        self.sampler_section = SamplerSection(parent)
        self.sampler_section.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        # Seed/randomization
        self.seed_section = SeedSection(parent)
        self.seed_section.grid(row=2, column=0, sticky="ew")

        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        parent.rowconfigure(2, weight=0)
        parent.columnconfigure(0, weight=1)
```

- Reconnect existing controller glue:
  - Wherever the old card read/wrote prompt/sampler/seed values, map those interactions to the new components’ variables/fields.
  - Ensure any validation or `ValidationResult` use is preserved and routed via `show_validation_result` if appropriate.

> CODEX should open the current implementation of this card and ensure all fields/behaviors are preserved, just reorganized.

### 2. Keep External Interface Stable

- The class name **must stay** `AdvancedTxt2ImgStageCardV2`.  
- The module path remains the same.  
- Any code that imports and instantiates this card (e.g., `PipelinePanelV2`) should not need changes beyond adapting to minor constructor differences, if any.

Aim to keep the constructor signature identical; if that’s not feasible, update only the direct call sites.

### 3. Update Tests That Touch Txt2Img Layout

If there are GUI tests under `tests/gui_v2/` that instantiate or inspect the txt2img card:

- Update expectations that assume a particular widget hierarchy (e.g., direct children of the root frame) to look inside `body_frame` or components instead.
- Prefer asserting **“it creates expected key controls”** (prompt text, sampler dropdown, seed entry) rather than brittle widget tree structures.

No new tests are strictly required, but a small smoke test that constructs the advanced txt2img card and checks that `prompt_section`, `sampler_section`, and `seed_section` exist would be helpful.

---

## Files Touched

**Updated:**

- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- Possibly some tests in `tests/gui_v2/` that directly reference the txt2img card.

**Not Touched:**

- `advanced_img2img_stage_card_v2.py`
- `advanced_upscale_stage_card_v2.py`
- Prototype stage cards in `src/gui/`.

---

## Acceptance Criteria

- App still launches and txt2img stage card is visible and functional.  
- All existing GUI V2 tests pass after necessary adjustments.  
- The advanced txt2img card uses `BaseStageCardV2` and the shared components internally.  
- No other stage cards are modified in this PR.
