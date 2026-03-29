# GUI Ownership Map v2.6

**Status:** Canonical active reference  
**Authority tier:** Tier 3 (Subsystem Reference) — see [Canonical_Document_Ownership_v2.6.md](Canonical_Document_Ownership_v2.6.md)  
**Enforced by:** AGENTS.md, `.github/instructions/gui.instructions.md`

---

## 1. Purpose

This document answers one question for every GUI file decision:

> _Where does this code go?_

There are two active GUI source directories:

| Directory | Role |
|---|---|
| `src/gui/` | **Active Tk runtime** — the canonical GUI host layer |
| `src/gui_v2/` | **Adapter scaffolding** — toolkit-agnostic adapters and validation helpers |

---

## 2. `src/gui/` — Active Tk Runtime

### Canonical status

`src/gui/` is the canonical GUI host layer for StableNew v2.6.  
All new Tk widgets, panels, dialogs, and views go here.

### Contents

| Sub-path | Responsibility |
|---|---|
| `main_window.py`, `main_window_v2.py` | Top-level Tk window setup; `ENTRYPOINT_GUI_CLASS` |
| `app_layout_v2.py`, `layout_v2.py` | Frame layout and zone routing |
| `app_state_v2.py` | Runtime draft state (`AppStateV2`) — owned by GUI layer |
| `controllers/` | Tk-side controller wrappers (learning, pipeline, etc.) |
| `views/` | Tab frames and panel renders; render + event wiring only |
| `view_contracts/` | Toolkit-agnostic interaction contracts (no Tk imports) |
| `panels_v2/` | Named panel composites |
| `stage_cards_v2/` | Stage card widgets |
| `dialogs/` | Modal and non-modal dialogs |
| `widgets/` | Reusable Tk widget helpers |
| `models/` | GUI-local presentation models |
| `utils/` | GUI utility helpers (threading, event dispatching) |
| `ui_tokens.py` | Semantic style source-of-truth for all GUI hosts |
| `theme.py`, `theme_v2.py`, `design_system_v2.py` | Visual styling |

### Rules

1. **New Tk code goes in `src/gui/`** — no exceptions without a dedicated approved PR.
2. `view_contracts/` may NOT import Tk types — contracts are toolkit-agnostic by design.
3. `views/` performs render and event wiring only; non-render logic belongs in controllers or adapters.
4. `app_state_v2.py` is the one place runtime draft state lives; do not invent shadow state in sub-panels.
5. `ui_tokens.py` is the single style source-of-truth; do not hardcode colours or fonts in panels.
6. Controllers in `controllers/` orchestrate; they do not own prompt construction or job submission logic.
7. Controllers must not mutate Tk widgets directly. GUI-visible operator logs, queue/history/preview surfaces, and status indicators must flow through `AppStateV2` plus GUI-owned projection code.
8. Hot runtime surfaces in the pipeline shell are owned by `PipelineTabFrameV2`; child panels may render standalone, but when mounted in the pipeline shell they must not independently subscribe to hot runtime state.
9. Hidden or unmapped hot surfaces must defer expensive reconciliation until visible again, and filesystem/artifact lookup work must run through background query services with latest-request-wins semantics rather than on the Tk thread.

---

## 3. `src/gui_v2/` — Adapter Scaffolding

### Canonical status

`src/gui_v2/` contains **toolkit-agnostic adapters and validation helpers**.  
It is *not* a second GUI host. It does not render panels or widgets.

### Contents

| Sub-path | Responsibility |
|---|---|
| `adapters/` | Thin bridges: translate GUI events → controller calls, or controller results → GUI updates |
| `validation/` | Pure-Python field validators used by panels (no Tk dependency) |

### Rules

1. **No new Tk widgets belong in `src/gui_v2/`.**
2. Adapter modules in `adapters/` must not import Tk directly; they receive and return plain Python objects.
3. `validation/` modules must be side-effect free and pure-Python only.
4. New adapters written for the existing Tk runtime belong in `src/gui_v2/adapters/` only if they follow the strict no-Tk rule; otherwise they belong in `src/gui/utils/` or `src/gui/controllers/`.

---

## 4. Migration Boundary

`src/gui_v2/` exists as scaffolding for a potential future toolkit migration (PySide6 or other).  
As of v2.6, **no active migration is in progress**.

The boundary rule is:

> Everything in `src/gui_v2/` MUST remain importable without Tk.  
> Everything that requires Tk stays in `src/gui/`.

Any work that blurs this boundary (e.g., adding Tk imports to `src/gui_v2/`) requires an explicit approved PR and an architecture document update.

---

## 5. Addition Rules Summary

| I need to add... | Where it goes |
|---|---|
| New panel or tab frame | `src/gui/views/` or `src/gui/panels_v2/` |
| New widget | `src/gui/widgets/` |
| New dialog | `src/gui/dialogs/` |
| New learning or pipeline controller wrapper | `src/gui/controllers/` |
| Toolkit-agnostic validation logic | `src/gui_v2/validation/` |
| Adapter translating controller output → GUI | `src/gui_v2/adapters/` (must be Tk-free) |
| Style constant | `src/gui/ui_tokens.py` |
| Theme variable | `src/gui/theme_v2.py` |
| GUI-local presentation model | `src/gui/models/` |
| GUI utility (threading, dispatching) | `src/gui/utils/` |

---

## 6. Forbidden Patterns

The following patterns are defects regardless of which directory they appear in:

- Prompt construction in any GUI file (must happen in `src/pipeline/` via PromptPack)
- Job dict construction in any GUI file (must use `NormalizedJobRecord` from builder pipeline)
- Direct runner invocation from any GUI file (must go through `JobService`/queue)
- State mutation in a `view_contracts/` file
- Tk import in any `src/gui_v2/` file
- Shadow state for queue or history in any panel (the single truth lives in `AppStateV2` and the queue/history subsystems)
- Controller-side direct widget mutation such as `log_text.insert/delete/see` or status-label `.configure(...)` calls

---

## 7. Relationship to Other Documents

| Document | Relationship |
|---|---|
| [ARCHITECTURE_v2.6.md](ARCHITECTURE_v2.6.md) — §8 GUI Architecture | Canonical behavioural rules; this doc is the file-placement companion |
| `.github/instructions/gui.instructions.md` | Executor-level rules for Copilot/Codex when editing GUI files |
| [Canonical_Document_Ownership_v2.6.md](Canonical_Document_Ownership_v2.6.md) | Tier assignment and update governance for this document |
| `AGENTS.md` | Forbids GUI prompt construction, job-dict building, and direct runner calls at the agent level |
