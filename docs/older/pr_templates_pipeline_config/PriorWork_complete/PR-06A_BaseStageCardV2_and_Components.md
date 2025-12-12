# PR-06A — Introduce BaseStageCardV2 & Shared Components (No Usage Yet)

## Summary

This PR is the **first, low-risk step** toward stage-card componentization.  
It introduces new, reusable building blocks for V2 stage cards without changing any existing behavior.

- Add a `BaseStageCardV2` class under `stage_cards_v2/` that defines the common card shell (header, body, validation area).
- Add a small set of shared UI components for common sections (prompt, sampler, seed, etc.).
- **Do not** modify any existing stage card modules or tests yet.

> After this PR, nothing in the app should behave differently. The new classes just exist, unused but ready.

---

## Goals

1. Provide a **single base class** for V2 stage cards to inherit from in later PRs.
2. Provide **shared components** for common UI patterns (prompt, sampler, seed) to avoid duplication.
3. Keep the change **purely additive** so tests and runtime behavior are unaffected.

---

## Implementation

### 1. Add `BaseStageCardV2`

Create a new file:

```text
src/gui/stage_cards_v2/base_stage_card_v2.py
```

Implementation sketch (adapt to existing imports / ValidationResult semantics):

```python
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from src.gui.stage_cards_v2.validation_result import ValidationResult


class BaseStageCardV2(ttk.Frame):
    """Base class for V2 stage cards.

    Handles the card frame, header, and validation area.
    Concrete cards override `_build_body` to define main controls.
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
                wraplength=420,
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

        self.validation_label = ttk.Label(
            self.validation_frame,
            text="",
            style="Muted.TLabel",
        )
        self.validation_label.pack(side="left", anchor="w")


    # ---- API for subclasses ----

    def _build_body(self, parent: ttk.Frame) -> None:
        """Subclasses must override to add their controls into `parent`."""
        raise NotImplementedError

    def show_validation_result(self, result: ValidationResult) -> None:
        # Simple example behavior; can be expanded later
        self.validation_label.configure(text=result.message)
```

> This base class should not be imported or used anywhere yet.

### 2. Add Shared Components

Create:

```text
src/gui/stage_cards_v2/components.py
```

Initial component set (keep small and generic):

```python
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui import theme_v2


class PromptSection(ttk.Frame):
    def __init__(self, master: tk.Misc, *, title: str = "Prompt", height: int = 3, **kwargs) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)

        self.label = ttk.Label(self, text=title, style="Muted.TLabel")
        self.label.grid(row=0, column=0, sticky="w", pady=(0, 2))

        self.text = tk.Text(
            self,
            height=height,
            wrap="word",
            bg=theme_v2.BACKGROUND_ELEVATED,
            fg=theme_v2.TEXT_PRIMARY,
            insertbackground=theme_v2.TEXT_PRIMARY,
        )
        self.text.grid(row=1, column=0, sticky="nsew")

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)


class SamplerSection(ttk.Frame):
    def __init__(self, master: tk.Misc, *, sampler_values: list[str] | None = None, **kwargs) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)

        ttk.Label(self, text="Sampler", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.sampler_var = tk.StringVar()

        self.sampler_combo = ttk.Combobox(self, textvariable=self.sampler_var, state="readonly")
        if sampler_values:
            self.sampler_combo["values"] = sampler_values

        self.sampler_combo.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(self, text="Steps", style="Muted.TLabel").grid(row=2, column=0, sticky="w")
        self.steps_var = tk.IntVar(value=20)
        self.steps_scale = ttk.Scale(self, from_=1, to=100, orient="horizontal", variable=self.steps_var)
        self.steps_scale.grid(row=3, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(self, text="CFG", style="Muted.TLabel").grid(row=4, column=0, sticky="w")
        self.cfg_var = tk.DoubleVar(value=7.0)
        self.cfg_scale = ttk.Scale(self, from_=1.0, to=20.0, orient="horizontal", variable=self.cfg_var)
        self.cfg_scale.grid(row=5, column=0, sticky="ew")

        self.columnconfigure(0, weight=1)


class SeedSection(ttk.Frame):
    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)

        ttk.Label(self, text="Seed", style="Muted.TLabel").grid(row=0, column=0, sticky="w")

        self.seed_var = tk.StringVar()
        self.seed_entry = ttk.Entry(self, textvariable=self.seed_var, width=12)
        self.seed_entry.grid(row=1, column=0, sticky="w", pady=(0, 4))

        self.randomize_var = tk.BooleanVar(value=True)
        self.randomize_check = ttk.Checkbutton(
            self,
            text="Randomize each run",
            variable=self.randomize_var,
            style="TCheckbutton",
        )
        self.randomize_check.grid(row=2, column=0, sticky="w")

        self.columnconfigure(0, weight=1)
```

These components are intentionally generic and **do not know about controllers or AppState yet**.

### 3. Optional Minimal Test

Add a tiny unit test to ensure the imports and base class are valid, e.g.:

```text
tests/gui_v2/test_stagecard_base_v2.py
```

```python
import tkinter as tk

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2


class DummyCard(BaseStageCardV2):
    def _build_body(self, parent):
        pass


def test_base_stage_card_v2_smoke(monkeypatch):
    root = tk.Tk()
    card = DummyCard(root, title="Dummy")
    card.destroy()
    root.destroy()
```

Keep it minimal so it doesn’t constrain future layout decisions.

---

## Files Touched

**New:**

- `src/gui/stage_cards_v2/base_stage_card_v2.py`
- `src/gui/stage_cards_v2/components.py`
- (optional) `tests/gui_v2/test_stagecard_base_v2.py`

**None of the existing stage cards should be modified in this PR.**

---

## Acceptance Criteria

- New base and component modules exist and import cleanly.  
- All existing GUI V2 tests still pass.  
- The running app behaves exactly as before this PR (no visual or behavioral change yet).
