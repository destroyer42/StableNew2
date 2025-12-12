# PR-06 — Stage Card Componentization (V2)

## Summary

The V2 GUI uses **stage cards** (e.g., for txt2img, img2img, upscale) to present pipeline stages in a modular, GUI-friendly way. Right now, each stage card has its own layout and widget composition, with duplicated patterns for:

- Headers and labels  
- Prompt/negative prompt sections  
- Sampler/steps/CFG sliders  
- Seed / randomization toggles  
- “Run” / “Apply” style controls

This PR introduces a **componentized stage-card UI** so that:

- Common UI elements are factored into reusable components.  
- Advanced stage cards (`stage_cards_v2/advanced_*_stage_card_v2.py`) share the same building blocks.  
- Future stages (e.g., control, batch, LoRA tweaking) can be built quickly and consistently.

> This PR is about **UI structure and reuse**, not logic changes. The intent and behavior of each card remain the same.

---

## Goals

1. Introduce a **common base class** for V2 stage cards that handles shared header/structure.  
2. Create **reusable subcomponents** (widgets) for common sections (prompt, sampling, seed, toggles, etc.).  
3. Refactor existing advanced stage cards to use these components internally without changing external behavior or signatures.  
4. Prepare the card layer to integrate cleanly with `AppStateV2` and controllers in future PRs.

---

## Non-Goals

- No new pipeline features or parameters.  
- No changes to underlying pipeline execution logic.  
- No archiving or removal of old stage-card variants yet (older/prototype cards stay for now).  
- No major theming changes (they use existing theme styles).

---

## Existing Stage Card Landscape

From the current repo and prior V2 PRs:

- V2 advanced stage cards live under:

  - `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
  - `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
  - `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`
  - Plus shared helper(s) like `validation_result.py`

- There are also **prototype stage cards** in `src/gui/`:

  - `src/gui/txt2img_stage_card.py`
  - `src/gui/img2img_stage_card.py`
  - `src/gui/upscale_stage_card.py`

  These are conceptually part of the V2 card journey and should **not** be treated as legacy yet.

This PR will **focus on the V2 advanced cards under `stage_cards_v2/`**, and introduce a base/component structure there.  
The older prototype cards remain untouched for now, but may later be migrated or retired.

---

## Design Overview

### 1. Base Class for Stage Cards

Introduce a shared base class in:

```text
src/gui/stage_cards_v2/base_stage_card_v2.py
```

Responsibility:

- Own the outer frame and card styling.  
- Provide a common header area with title + optional description.  
- Provide standard hooks for building the inner content area.  
- Optionally host common validation / error display region.

Example skeleton:

```python
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from src.gui.theme_v2 import BACKGROUND_ELEVATED  # if needed
from src.gui.stage_cards_v2.validation_result import ValidationResult


class BaseStageCardV2(ttk.Frame):
    """Base class for V2 stage cards.

    Handles the card frame, header, and validation area.
    Concrete cards override `_build_body` to add their specific controls.
    """

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        description: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, style="Card.TFrame", **kwargs)

        self._title = title
        self._description = description

        self._build_header()
        self._build_body_container()
        self._build_validation_area()

    def _build_header(self) -> None:
        self.header_frame = ttk.Frame(self, style="Card.TFrame")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        self.title_label = ttk.Label(self.header_frame, text=self._title, style="Heading.TLabel")
        self.title_label.pack(side="left")

        if self._description:
            self.description_label = ttk.Label(
                self.header_frame,
                text=self._description,
                style="Muted.TLabel",
                wraplength=400,
                justify="left",
            )
            self.description_label.pack(side="left", padx=(8, 0))

    def _build_body_container(self) -> None:
        self.body_frame = ttk.Frame(self, style="Card.TFrame")
        self.body_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self._build_body(self.body_frame)

    def _build_validation_area(self) -> None:
        self.validation_frame = ttk.Frame(self, style="Card.TFrame")
        self.validation_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))

        # The card can use ValidationResult to display errors/warnings
        self.validation_label = ttk.Label(
            self.validation_frame,
            text="",
            style="Muted.TLabel",
        )
        self.validation_label.pack(side="left")

    # --- API for subclasses ---

    def _build_body(self, parent: ttk.Frame) -> None:
        """Subclasses must override to add main controls into `parent`."""
        raise NotImplementedError

    def show_validation_result(self, result: ValidationResult) -> None:
        # Example integration, real behavior may be richer
        self.validation_label.config(text=result.message)
```

> CODEX should adapt this skeleton to match the existing ValidationResult usage and card behavior.

### 2. Subcomponents for Common Sections

Introduce a small set of **subcomponent classes** that stage cards can reuse. These can live in:

```text
src/gui/stage_cards_v2/components.py
```

Example components:

- `PromptSection` — prompt + negative prompt fields (or single prompt), with labels and optional token count display.
- `SamplerSection` — sampler dropdown, steps slider, CFG slider.
- `SeedSection` — seed entry, “randomize” checkbox, “lock” toggle.
- `SizeSection` — width/height controls for txt2img/img2img.
- `ActionRow` — buttons like “Run Stage”, “Preview”, “Reset to Defaults”.

Skeleton examples:

```python
class PromptSection(ttk.Frame):
    def __init__(self, master: tk.Misc, *, title: str = "Prompt", **kwargs) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)

        self.label = ttk.Label(self, text=title, style="Muted.TLabel")
        self.label.grid(row=0, column=0, sticky="w", pady=(0, 2))

        self.text = tk.Text(self, height=3, wrap="word")
        self.text.grid(row=1, column=0, sticky="nsew")

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
```

Each component should:
- Receive references or callback hooks to interact with `AppStateV2` / controllers (later PRs).  
- Use `theme_v2` colors for `tk.Text` where needed.  
- Avoid hard-coding pipeline logic.

### 3. Refactor Advanced Stage Cards to Use Components

For each advanced stage card:

- `advanced_txt2img_stage_card_v2.py`
- `advanced_img2img_stage_card_v2.py`
- `advanced_upscale_stage_card_v2.py`

Refactor them to:

1. Subclass `BaseStageCardV2`.
2. Implement `_build_body(parent)` to compose components from `components.py`.

Example sketch for txt2img:

```python
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.stage_cards_v2.components import PromptSection, SamplerSection, SeedSection


class AdvancedTxt2ImgStageCardV2(BaseStageCardV2):
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            title="Text to Image",
            description="Generate images from text prompts using your configured pipeline.",
            **kwargs,
        )

    def _build_body(self, parent: ttk.Frame) -> None:
        self.prompt_section = PromptSection(parent, title="Prompt")
        self.prompt_section.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        self.sampler_section = SamplerSection(parent)
        self.sampler_section.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.seed_section = SeedSection(parent)
        self.seed_section.grid(row=2, column=0, sticky="ew")

        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        parent.rowconfigure(2, weight=0)
        parent.columnconfigure(0, weight=1)
```

The intent is **not** to change what knobs are exposed, but to express them **through shared components**.

### 4. Keep External Interfaces Stable

Where existing code imports or instantiates stage cards (e.g., in `pipeline_panel_v2` or controller glue):

- Maintain the same class names and signatures used externally.
- If necessary, add lightweight adapter or compatibility wrapper classes that subclass the new base while presenting the old initialization interface.

Avoid breaking tests in `tests/gui_v2` that validate stage card presence or behavior.

### 5. (Optional) Light AppStateV2 Hooks

As a preparatory step for future PRs, components may accept optional references to `AppStateV2` or simple callbacks (e.g., `on_prompt_changed`).

However, in this PR:

- Do not change where the data actually lives.  
- You may wire **internal callbacks** (e.g., when prompt text changes, call a no-op callback) to make later integration easier.  
- Keep all existing side-effects and controller interactions intact.

---

## Files Expected to Change / Be Added

**New:**

- `src/gui/stage_cards_v2/base_stage_card_v2.py`
- `src/gui/stage_cards_v2/components.py`

**Updated:**

- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`

**Not Touched:**

- `src/gui/txt2img_stage_card.py`
- `src/gui/img2img_stage_card.py`
- `src/gui/upscale_stage_card.py`
- Any pipeline or controller internals (beyond necessary imports).

---

## Tests & Validation

### Manual

1. Launch the app and navigate to the pipeline area that uses advanced stage cards.  
2. Confirm:
   - Stage cards still appear as expected.  
   - Controls (prompt, sampler, seed, etc.) are present and functional.  
   - Card headers and validation areas look consistent across cards.

3. Run a simple txt2img and upscale pipeline and confirm behavior matches pre-refactor behavior.

### Automated

- Run existing GUI tests:

  ```bash
  pytest tests/gui_v2 -v
  ```

- If tests covered advanced stage cards before, they should continue to pass.  
- Optionally add a small test to instantiate `BaseStageCardV2` and each advanced card in a `Tk` root to catch wiring issues.

---

## Acceptance Criteria

- A `BaseStageCardV2` exists and is used by advanced stage cards.  
- Shared UI patterns (header, layout, validation region, common control sections) are implemented as reusable components.  
- All three advanced stage cards function as before (no behavior regressions), but with cleaner, more maintainable internals.  
- No prototype or older stage card modules are removed or archived in this PR.  
- All GUI V2 tests pass.
