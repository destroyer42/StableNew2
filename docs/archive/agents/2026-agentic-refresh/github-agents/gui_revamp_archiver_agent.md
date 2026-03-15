---
name: gui_revamp_archiver_agent
description: Fixing issues with GUI
---

# My Agent

Copilot Agent — 

Role: Senior Python engineer + UX-minded Tk/ttk designer
Repo goals:

## Purpose
Eliminate GUI crashes from early logging and missing config metadata. Replace fragile `self.log_text` usage with a stable LogPanel API and fix NameErrors/late-binding in config-panel callbacks. Keep changes minimal and visual-logic neutral.

## Scope / Files
- `src/gui/log_panel.py` — expose `append(msg, level="INFO")` API; keep internal `Text` disabled; `see("end")`.
- `src/gui/main_window.py` (or `StableNewGUI`):
  - Create `self.log_panel` early.
  - Add proxy `self.add_log = self.log_panel.append`.
  - Add legacy alias `self.log_text = getattr(self.log_panel, "text", None)`.
  - Replace `_add_log_message` to use `self.add_log` with a safe fallback (`print`).
  - Initialize metadata attrs: `self.schedulers`, `self.upscaler_names`, `self.vae_names` as empty lists.
  - Replace lambdas with `functools.partial` (or capture defaults) when scheduling UI updates.
- `src/gui/config_panel.py` (or equivalent):
  - Combos disabled until data arrives.
  - `set_schedulers(names)`, `set_upscalers(names)`, `set_vaes(names)` enable `readonly` when non-empty.
- **Tests (new)**
  - `tests/gui/test_logpanel_binding.py`
  - `tests/gui/test_config_meta_updates.py`

## Guardrails
- Tk main thread **non-blocking** (no `join()` from GUI/tests).
- Headless-safe: GUI tests must skip gracefully if Tcl/Tk/display missing.
- No business-logic/pipeline changes; strictly stability & wiring.
- Use package imports (e.g., `from src.gui.theme import theme`); no `sys.path` hacks.

## Implementation Checklist
- [ ] **LogPanel**: implement `append(msg, level="INFO")` that enables → inserts → disables; preserves scroll; keeps raw buffer intact.
- [ ] **GUI init**: instantiate `self.log_panel` before any log call; add `self.add_log` proxy and `self.log_text` alias.
- [ ] **_add_log_message**: route to `self.add_log(msg, level)`; on error, `print` as a last resort.
- [ ] **Metadata attrs**: initialize `self.schedulers`, `self.upscaler_names`, `self.vae_names` to empty lists.
- [ ] **Apply metadata**: after fetch, set attrs, then `root.after(0, partial(config_panel.set_*, list(...)))`.
- [ ] **Combos**: start disabled; become `readonly` once values arrive.
- [ ] **Defensive**: if metadata missing, warn once and keep controls disabled.

## Minimal reference snippets
```python
# main_window.py (early init)
self.log_panel = LogPanel(self, ...)
self.add_log = self.log_panel.append
self.log_text = getattr(self.log_panel, "text", None)  # legacy compat

def _add_log_message(self, msg, level="INFO"):
    try:
        self.add_log(msg, level)
    except Exception:
        print(f"[{level}] {msg}")

# metadata wiring
from functools import partial
self.schedulers, self.upscaler_names, self.vae_names = [], [], []

def on_metadata_ready(self, meta):
    self.schedulers = meta.get("schedulers", [])
    self.upscaler_names = meta.get("upscalers", [])
    self.vae_names = meta.get("vaes", [])
    self.root.after(0, partial(self.config_panel.set_schedulers, list(self.schedulers)))
    self.root.after(0, partial(self.config_panel.set_upscalers, list(self.upscaler_names)))
    self.root.after(0, partial(self.config_panel.set_vaes, list(self.vae_names)))

Tests & Validation (must pass in CI)

Commands

pre-commit run --all-files

pytest -q

Focused:

pytest tests\gui\test_logpanel_binding.py -q

pytest tests\gui\test_config_meta_updates.py -q

New tests

tests/gui/test_logpanel_binding.py

GUI creates log_panel, exposes add_log proxy and log_text alias.

Calling _add_log_message("hello") updates the buffer (or stubs safely).

tests/gui/test_config_meta_updates.py

Combos disabled initially; after on_metadata_ready({...}), values applied and combos become readonly.

PR Rules

Branch from postGemini: feature/gui-log-config-stability

Small, focused diffs; conventional commits:

fix(gui): add early log panel + proxy to avoid AttributeError

fix(gui): make config updates safe; capture values in partials

test(gui): add logpanel and config meta update tests

Use the repo PR template; attach short notes (no UX changes).

Definition of Done

No more AttributeError: 'StableNewGUI' object has no attribute 'log_text'.

No more NameError for schedulers/upscalers/vaes; combos populate safely.

Headless-safe tests pass; CI green.

No behavioral regressions in pipeline flow.

Rollback

Revert PR; no schema/config changes introduced, so revert is clean.
