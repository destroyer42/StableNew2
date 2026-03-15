---
applyTo: "src/gui*/**/*.py"
---

# GUI Instructions

- Keep UI modules thin and event-driven.
- Do not add pipeline, queue, history, learning, or randomizer logic to GUI files.
- Use explicit controller entrypoints rather than string dispatch or hidden hooks.
- Keep UI updates thread-safe and non-blocking.
- Preserve existing theme and layout patterns unless the approved scope explicitly changes them.
- Mirror behavior changes with deterministic GUI or integration tests where practical.
- **File placement**: `src/gui/` is the active Tk runtime; `src/gui_v2/` is toolkit-agnostic adapters only (no Tk imports). See `docs/GUI_Ownership_Map_v2.6.md` for full placement rules.
