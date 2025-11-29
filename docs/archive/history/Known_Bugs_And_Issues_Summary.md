# StableNew – Known Bugs & Issues Summary (v1.0)

_Last updated: 2025-11-15_

This document catalogs the main stability, correctness, and UX issues that have been observed in StableNew. It is the primary input to the **Stability & Refactor** phases of the roadmap.

Each issue is described in terms of:

- **Symptom**
- **Likely cause / contributing factors**
- **Risk**
- **Suggested approach** (to be turned into tests + PRs)

---

## 1. Stability & Lifecycle Issues

### 1.1 GUI Hang / Freeze on Second Run

**Symptom**

- First pipeline run completes (or is cancelled), but a subsequent run causes:
  - GUI freeze / non-responsive window.
  - In some cases, needing to kill `python.exe` from Task Manager.

**Likely Causes**

- Lifecycle of worker thread and cancellation token not fully reset between runs.
- Event handlers (Stop button, close window) not correctly resetting state machine.
- Residual references to stale pipeline instances or controllers.

**Risk**

- High: makes StableNew feel unreliable.
- Leads to users force-closing, risking partial outputs and corrupted manifests.

**Suggested Approach**

- Create focused journey tests around:
  - “Run → Stop → Run again” scenarios.
  - “Run → Complete → Run again” scenarios.
- Ensure GUI state machine transitions back to a clean `IDLE` state.
- Introduce explicit “reset pipeline state” helper invoked before each new run.
- Tie fixes to TDD-style tests in `tests/gui/test_main_window_pipeline.py` (or equivalent).

---

### 1.2 Zombie `python.exe` Processes After Exit (Partially Fixed)

**Symptom**

- Closing StableNew leaves background `python.exe` processes running.

**Status**

- PR10 single-instance lock and `_graceful_exit()` significantly improved this:
  - Single-instance lock prevents multiple concurrent GUIs.
  - `_graceful_exit()` persists preferences, stops controller, tears down Tk, and calls `os._exit(0)` if needed.

**Remaining Issues**

- Need to re-validate behavior after new refactors and ensure:
  - Exit routines always execute.
  - No new code paths bypass `_graceful_exit()`.

**Suggested Approach**

- Add tests (unit + manual checklist) for:
  - Single instance behavior.
  - Clean process exit after closing window or hitting Exit.
- Consider a small “smoke test” script that launches StableNew, closes it, and verifies no extra processes remain (documented for manual testing).

---

### 1.3 Thread-Safety Problems in GUI (Partially Fixed)

**Symptom**

- Past crashes and intermittent `TclError` when refreshing models, VAEs, upscalers, or schedulers from background threads.

**Status**

- `THREADING_FIX.md` describes:
  - New `_refresh_*_async()` methods that perform API calls in a worker thread and schedule widget updates via `root.after(0, ...)`.
  - Error dialogs also marshaled back to the main thread.

**Remaining Risks**

- Any new code that updates Tk widgets from background threads risks reintroducing this issue.
- Need consistent pattern and tests.

**Suggested Approach**

- Audit `main_window` and related panels for:
  - Direct widget manipulation inside background threads.
- Add/extend GUI tests that exercise:
  - Async refresh paths.
  - Error pathways.
- Document a clear “Tk thread-safety contract” in the architecture doc.

---

## 2. Pipeline & Upscale Issues

### 2.1 Upscale Tile Size and Crashes

**Symptom**

- Upscale stage crashing or failing when large tile sizes (e.g., 1920x1920) are used with certain upscalers (UltraSharp, R-ESRGAN).
- Logs showed defaults like:
  - `img_max_size_mp=16, ESRGAN_tile=1920, DAT_tile=1920`

**Likely Causes**

- Over-aggressive default tile sizes for specific model/VRAM combinations.
- Lack of dynamic tile sizing logic based on image resolution, VRAM, or scale factor.
- Possibly mismatched WebUI defaults vs StableNew overrides.

**Risk**

- High for users at the boundary of VRAM limits.
- Undermines trust in the upscale step and encourages disabling it.

**Suggested Approach**

- Add tests around the upscale config passed to WebUI:
  - “Safe max tile size” for common resolutions (1024, 2048, etc.).
  - Behavior under large batches or large scale factors.
- Implement a “tile size safety” helper:
  - Compute recommended tiles based on resolution and an adjustable safety factor.
  - Allow user override, but use conservative defaults.
- Make upscale-only and midstream flows use the same logic.

---

### 2.2 Retry / Backoff Behavior (Specified but Not Fully Implemented)

**Symptom**

- Transient failures (e.g., `txt2img` returning `None`) are not robustly retried.
- Tests in `test_pipeline_journey.py` describe expected behavior for retry/backoff and manifest reflection, but implementation is partial.

**Risk**

- Occasional WebUI hiccups cause entire runs to fail abruptly.
- Harder to understand when failures are transient vs real.

**Suggested Approach**

- Implement a small retry wrapper around critical API calls (especially `txt2img`):
  - Exponential backoff with max attempts.
  - Capture retry count and outcome.
- Make manifests include retry metadata (`retry_count`, `last_error`, etc.).
- Update journey tests so they assert on concrete retry behavior, not just “txt2img in results”.

---

## 3. Randomization, Matrix, and Prompt Handling

### 3.1 Inconsistent Randomization Paths (Fixed but Needs Guardrails)

**Symptom (historical)**

- Preview payload (dry run) and actual pipeline produced different prompts.
- Raw `[[matrix]]` slots and `__wildcard__` tokens leaked to WebUI.

**Status**

- PR9 unified randomization paths and introduced `sanitize_prompt()`.
- Logs now show matrix summary, and randomization is applied consistently.

**Remaining Risks**

- Future code changes might bypass `sanitize_prompt()` or reintroduce divergent paths.
- Complex interactions between prompt packs, presets, and per-run overrides.

**Suggested Approach**

- Lock in behavior with tests:
  - For both preview and pipeline, ensure prompts are identical post-sanitization.
  - Assert no `[[slot]]` or `__token__` markers reach the API payload.
- Treat randomization/matrix functions as part of a “prompt pipeline” module that can be unit-tested in isolation.

---

## 4. GUI Layout & UX Issues

### 4.1 Scrollbars Inside Scrollbars / Layout Clutter

**Symptom**

- Some panels have nested scrollable areas.
- Horizontal and vertical scrollbars show up in confusing combinations.
- On smaller screens or high DPI, key controls become hard to reach or clipped.

**Likely Causes**

- Incremental additions to `main_window` without a global layout strategy.
- Reuse of ad-hoc frame/scrolling patterns in multiple panels.

**Risk**

- Medium: hurts usability and perceived quality.
- High risk of regressions when modifying layout, because structure is fragile.

**Suggested Approach**

- GUI overhaul (Phase 3 in the roadmap):
  - Define a layout grid and consistent zones in Figma first.
  - Simplify scroll areas: one main scrollable region where needed, instead of stacking.
  - Refactor `main_window` into smaller view/controller classes or “panels” with clear responsibilities.
- Add a small set of golden-path UI tests to prevent regressions (window sizing, visibility of key controls).

---

### 4.2 Button Placement & Behavioral Confusion

**Symptom**

- Buttons for important actions (Run, Stop, Preview, Randomization toggles, etc.) are not always where the user expects.
- Some actions are overloaded or hidden in secondary panels.

**Risk**

- Medium: reduces discoverability and slows workflows.
- Also increases risk that future changes attach new behavior to already overloaded controls.

**Suggested Approach**

- As part of the Figma-first GUI redesign:
  - Define a clear “command bar” pattern for primary pipeline actions.
  - Group related actions (Run/Stop/Preview/Queue) together.
  - Use progressive disclosure for advanced features.
- Current status: Run / Stop / Queue controls are now grouped in a dedicated command bar on the V2 pipeline panel; remaining UX
  work should focus on preview and advanced controls.

---

### 4.3 Cramped Prompt Editing (Partially Addressed)

**Symptom**

- Main prompt input is small and hard to use for long-form prompts.
- No obvious way to review or edit prompt text without losing context.

**Status**

- V2 now exposes an Advanced Prompt Editor overlay for long-form prompt editing without changing pipeline semantics.
- Negative prompt editing and deeper validation are future follow-ups.

**Suggested Approach**

- Continue refining the advanced editor UX (negative prompt area, validation hints, shortcut to open from prompt field).
- Keep edits flowing back to the existing prompt field to avoid changing pipeline/controller behavior.
- Add guardrail tests that opening the editor pre-fills from the main prompt and applying updates the main field while cancel
  leaves it unchanged.

---

## 5. Testing Gaps & TDD Discipline

### 5.1 Tests Not Keeping Up With Features

**Symptom**

- Some new features (e.g., more advanced randomization or advanced preset fields) were added without corresponding tests.
- Some tests act more like documentation of aspirational behavior than hard contracts.

**Risk**

- High: regressions sneak in when GUI or pipeline code is changed.
- AI-assisted changes (GPT/Codex) are more dangerous when tests are incomplete.

**Suggested Approach**

- Enforce TDD as a rule:
  - Write or update a failing test first.
  - Implement the fix or feature.
  - Run the full suite and keep PRs small.
- Prioritize:
  1. Pipeline correctness and config pass-through.
  2. GUI lifecycle (Run/Stop/Exit).
  3. Randomization/prompt handling.
  4. Upscale and video integration.

---

## 6. Documentation & Architecture Drift

### 6.1 Outdated `ARCHITECTURE.md`

**Symptom**

- `ARCHITECTURE.md` lives in an archive path and no longer fully matches:
  - Current GUI structure.
  - Updated pipeline flows (StageChooser, ADetailer, video integration).
  - Randomization/matrix behavior.
  - Single-instance lock and exit behavior.

**Risk**

- Contributors (and AI) may follow the wrong mental model.
- Architecture doc can mislead tests and refactors.

**Suggested Approach**

- Treat current `ARCHITECTURE.md` as historical.
- Plan a rewrite after Phase 1 (Stability) and Phase 2 (GUI refactor) land, so the new document reflects the modern structure.
- Keep the old one in `/docs/archive/` clearly marked as obsolete.

---

This document should be updated whenever a significant bug is fixed, a new class of issue is discovered, or the architecture shifts in a way that changes the risk profile.

### 4.4 Prompt pack visibility gap between legacy and V2 (addressed)

- Legacy GUI exposed prompt packs prominently; V2 layout hid them, forcing users back to legacy for pack workflows.
- PR-50 adds a PromptPackPanelV2 + adapter in the V2 sidebar so packs can be browsed and applied without touching controller/pipeline logic.
- Continue to keep pack discovery/parsing unchanged; only the GUI surface moved.
