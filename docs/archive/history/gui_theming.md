# GUI Theming

## Overview

StableNew uses a centralized theming system based on ASWF (Academy Software Foundation) color tokens to ensure consistent dark mode styling across all GUI components.

## Theme System

All GUI styling must go through `src/gui/theme.py`. This file defines:

- **Color tokens**: ASWF-compliant colors for backgrounds, text, accents, and states
- **Font tokens**: Consistent typography sizing and family
- **Theme class**: Methods to apply consistent styling to Tkinter widgets

## Color Palette

| Token | Hex Value | Usage |
|-------|-----------|-------|
| `ASWF_BLACK` | `#221F20` | Primary backgrounds, root window |
| `ASWF_GOLD` | `#FFC805` | Primary buttons, headings, accents |
| `ASWF_DARK_GREY` | `#2B2A2C` | Secondary backgrounds, frames |
| `ASWF_MED_GREY` | `#3A393D` | Input fields, listboxes, tertiary elements |
| `ASWF_LIGHT_GREY` | `#4A4950` | Regular text, labels |
| `ASWF_ERROR_RED` | `#CC3344` | Error states, danger buttons |
| `ASWF_OK_GREEN` | `#44AA55` | Success states |

## Typography

| Token | Value | Usage |
|-------|-------|-------|
| `FONT_FAMILY` | `Calibri` | Primary font family |
| `FONT_SIZE_BASE` | `10` | Base font size |
| `FONT_SIZE_LABEL` | `11` | Labels and regular text |
| `FONT_SIZE_BUTTON` | `11` | Button text |
| `FONT_SIZE_HEADING` | `13` | Headings and titles |

## Usage Guidelines

### For Panel Classes

1. **Import theme constants** at the top of GUI panel files:

   ```python
   from src.gui.theme import ASWF_BLACK, ASWF_GOLD, ASWF_DARK_GREY
   ```

2. **Use ttk styles** defined in `main_window.py`:

   - `"Dark.TFrame"` for frames
   - `"Dark.TLabel"` for labels
   - `"Dark.TButton"` for buttons
   - `"Primary.TButton"` for primary actions
   - `"Danger.TButton"` for destructive actions

3. **Apply theme to tk widgets** using theme methods:

   ```python
   # In panel __init__ or _build_ui methods
   self.theme = Theme()  # Get from parent or create instance
   self.theme.style_listbox(self.my_listbox)
   self.theme.style_entry(self.my_entry)
   ```

### For tk Widgets (not ttk)

When using raw Tkinter widgets that don't support ttk styles:

```python
from src.gui.theme import ASWF_MED_GREY, ASWF_LIGHT_GREY, ASWF_GOLD

# Apply colors directly
listbox = tk.Listbox(parent, bg=ASWF_MED_GREY, fg=ASWF_LIGHT_GREY,
                    selectbackground=ASWF_GOLD)
```

## Implementation Notes

- **No hard-coded hex colors** in panel classes
- **No hard-coded fonts** in panel classes
- All styling goes through the theme system for consistency
- ttk widgets use styles defined in `main_window.py`
- tk widgets use theme constants directly
- Panels with potentially long content (randomization, advanced editor tabs, etc.) must wrap their bodies with the shared `make_scrollable` helper from `src/gui/scrolling.py` instead of hand-rolling canvas logic.
- Favor descriptive labels with dynamic `wraplength` updates over horizontal scrollbars; only controls that truly require horizontal space (e.g., log consoles) should scroll sideways.

## Testing

Theme functionality is tested in `tests/gui/test_theme_baseline.py`:

- Verifies theme application to root window
- Tests all style methods apply correct colors/fonts
- Validates theme constants are properly defined
- Skips tests in headless environments

## Future Extensions

The theme system is designed to be extensible:

- Additional style methods can be added to the `Theme` class
- New color tokens can be added for specific use cases
- Font variations can be introduced for different contexts
- Theming could be made configurable via user preferences
