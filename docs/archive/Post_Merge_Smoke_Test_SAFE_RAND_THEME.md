# Post-Merge Smoke Test – SAFE + RAND + THEME PRs

Covers the combined impact of:
- PR-SAFE-ISOLATION-001 (Codex Safety & GUI/Utils Isolation)
- PR-RAND-SAN-001 (Randomizer / Matrix Sanitization & Preview–Pipeline Parity)
- PR-GUI-THEME-FIX-001 (Restore ASWF Theme Constants and Theme Class)

Use this as a **checklist** after all three PRs are merged onto your working branch.

---

## 0. Preconditions

1. Repo updated to the branch that includes all three PRs (SAFE, RAND, THEME).
2. Virtual environment / Python interpreter matches your standard StableNew dev setup.
3. Stable Diffusion WebUI (A1111) reachable at the configured URL and port (e.g., http://127.0.0.1:7860/).
4. No uncommitted local changes, or at least a clean working tree for this branch (so you can confidently rollback if needed).

---

## 1. Automated Test Pass – Layered

### 1.1 Safety Layer

Run:
- pytest tests/safety -v

Expectations:
- test_no_gui_imports_in_utils passes.
- test_randomizer_import_isolation passes.
- No failures or errors; skips are acceptable only if explicitly marked that way in safety tests.

### 1.2 Utils / Randomizer Layer

Run:
- pytest tests/utils -v

Expectations:
- All randomizer tests pass, including:
  - test_preview_and_pipeline_prompts_match_exactly_for_simple_matrix (or equivalent)
  - test_preview_and_pipeline_prompts_match_with_wildcards_and_matrices
  - test_randomizer_output_deterministic_for_given_seed
  - test_matrix_tokens_removed_after_expansion
  - test_wildcards_removed_after_expansion
  - test_malformed_matrix_raises_clear_error
  - test_matrix_rotate_advances_within_single_generate_call
- No new warnings or unexpected deprecation messages related to sanitization or randomizer imports.

### 1.3 Controller / Pipeline Layer

Run:
- pytest tests/controller -v
- pytest tests/pipeline -v

Expectations:
- Controller lifecycle tests pass (IDLE → RUNNING → STOPPING → IDLE and ERROR paths).
- AppController integration tests confirm correct PipelineConfig wiring and CancelToken behavior.
- Pipeline tests (if present in this tree) confirm stage orchestration behaves as expected, with no regressions from the new PipelineRunner design.

### 1.4 GUI Layer

Run:
- pytest tests/gui -v

Expectations:
- No ImportErrors from src.gui.theme:
  - ASWF_BLACK, ASWF_GOLD, etc. all resolve.
  - Theme class is importable and used where expected.
- tests/gui/test_theme_baseline.py passes.
- Other GUI tests either:
  - Pass normally, or
  - Are skipped with the existing “Tkinter/Tcl not available” messages.
- No GUI test fails due to theme or randomizer/sanitizer issues.

### 1.5 Full Suite

Run:
- pytest -v

Expectations:
- All non-skipped tests pass.
- Any skips are known/intentional (e.g., missing Tk/Tcl), not new regressions.

---

## 2. Module Import Sanity Checks

From the repo root, run small import checks via Python:

1. Import randomizer in isolation:
   - python -c "import src.utils.randomizer; print('randomizer OK')"
   - Expect: prints “randomizer OK” with no stack trace and no GUI/Tk errors.

2. Import theme and Theme:
   - python -c "from src.gui.theme import ASWF_BLACK, Theme; print('theme OK', ASWF_BLACK)"
   - Expect: prints “theme OK #221F20” (or equivalent) with no errors.

3. Import main window and stable GUI entry point:
   - python -c "from src.gui.main_window import StableNewGUI; print('GUI OK')"
   - Expect: no ImportError; Tk/Tcl errors are acceptable only if the environment lacks Tk, but they should be the same as under pytest.

---

## 3. Application-Level Smoke Tests

### 3.1 Launch & Basic GUI Health

1. Start Stable Diffusion WebUI manually.
2. From repo root, start StableNew:
   - python -m src.main
3. Confirm:
   - The main window opens without crashing.
   - The ASWF black/gold theme is applied:
     - Background appears dark.
     - Buttons show gold/black contrast.
     - Labels and headings use consistent fonts and sizes.

### 3.2 Theme Sanity

Within the running GUI:
1. Look at the Prompt Pack panel:
   - Background should match ASWF dark grey tones.
   - Selected items should be legible (no unreadable foreground/background combinations).

2. Check StageChooser and status bar:
   - Stage chooser buttons/labels use the same theme tones.
   - Status bar text is readable and not clashing with the background.

3. Confirm there are no obvious “unstyled” widgets (pure Tk grey) in primary panels that should be themed.

---

## 4. Randomizer & Sanitization Functional Checks

These checks validate that the behavior covered in tests holds in real gameplay.

### 4.1 Preview vs Pipeline Prompt Parity

1. Choose a Prompt Pack or a simple text prompt that includes:
   - A matrix, e.g., [[knight,wizard]]
   - A wildcard/placeholder if you use them.

2. Set a fixed seed in the UI.

3. Use any Preview/Inspect function available (e.g., preview prompt or summary panel):
   - Note the final prompt text you see (no __wildcard__ or [[matrix]] tokens should remain).

4. Run a small pipeline (1–2 images):
   - After completion, inspect any available manifest/log where the final prompt is recorded.
   - Confirm the prompt string recorded there matches the preview exactly (barring whitespace formatting).

Expectations:
- No [[...]] or __...__ tokens in the API payload/manifest.
- No mismatch between preview prompt and pipeline prompt.

### 4.2 Rotate Mode Matrix Behavior

1. Configure a prompt that uses rotate mode in the matrix, similar to your new test:
   - For example: a matrix that chooses between “wolf” and “lion” plus a Style=A/B matrix.

2. Set the fanout or variant count to generate multiple variants in one run.

3. Run the pipeline once and observe each generated image’s logged prompt (or metadata if available).

Expectations:
- For a single run with multiple variants, matrix rotate mode advances between variants within that call.
- You see a pattern like:
  - Variant 1: wolf / style A
  - Variant 2: lion / style B
  - Variant 3: wolf / style A (or similar, depending on your matrix configuration and test).

4. Re-run with the same seed and configuration:
   - Confirm that the sequence is deterministic (same order as the first run).

### 4.3 Malformed Syntax Handling

1. Intentionally include malformed matrix or wildcard syntax in a prompt:
   - Example: [[knight,wizard   (missing closing ]])
2. Attempt to run a small, 1-image pipeline.

Expectations:
- The GUI reports an error (dialog, status bar, or log) indicating a randomizer/matrix syntax problem.
- The pipeline does not hang; it fails fast and returns to a safe state.
- Logs contain a clear error message (RandomizerError or equivalent) rather than a generic traceback deep in the pipeline.

---

## 5. Controller & Lifecycle Checks (GUI + Pipeline)

These verify that SAFE + RAND changes did not break core Run/Stop behavior.

### 5.1 Normal Run (IDLE → RUNNING → IDLE)

1. Configure a simple txt2img-only pipeline (no upscale, 1–2 images).
2. Start the pipeline via the GUI Run button.

Expectations:
- Run button disables while the pipeline is active; Stop button enables (or equivalent state).
- Status bar/log shows a clear transition from idle to running and back to idle after completion.
- No uncaught exceptions in the logs.

### 5.2 Cancel During Long-Running Stage

1. Configure a slightly heavier pipeline (e.g., txt2img + upscale, 3–5 images).
2. Start the pipeline.
3. While an upscale or later stage is running, click Stop.

Expectations:
- Controller transitions to STOPPING and then IDLE.
- CancelToken is honored; no new images or stages start after cancellation.
- UI returns to a ready-to-run state (Run button re-enabled, Stop disabled).
- Logs/manifests show that the run was cancelled, not “completed normally”.

### 5.3 Error Handling Path (Controlled Failure)

1. Temporarily misconfigure the WebUI URL/port in your config (e.g., wrong port).
2. Attempt a small run.

Expectations:
- Controller transitions IDLE → RUNNING → ERROR → IDLE (or ERROR then back to IDLE after showing error).
- Error is presented clearly via GUI and/or logs.
- App remains responsive and does not need a restart.

---

## 6. Logs, Manifests, and Sanity Checks

1. Check structured logger output (if enabled):
   - Confirm that each run wrote a manifest with:
     - Final prompt string (sanitized)
     - PipelineConfig details (model, sampler, steps, resolution, etc.).

2. Search logs for any unexpected tracebacks related to:
   - randomizer
   - theme
   - Tk/Tcl initialization

3. Confirm no new warnings or errors appear that weren’t present before these PRs.

---

## 7. Exit Criteria

You can consider the combined SAFE + RAND + THEME merge stable when:

- tests/safety, tests/utils, tests/controller, tests/pipeline, and tests/gui behave as described above.
- pytest -v is fully green aside from known/intentional skips (e.g., Tk/Tcl not installed).
- StableNew launches cleanly and shows a coherent ASWF-themed GUI.
- Randomizer behaves predictably and deterministically:
  - Preview == pipeline prompts.
  - Matrix rotate mode advances as designed.
- Lifecycle (Run/Stop/Error) behaves correctly for normal, cancelled, and failed runs.
- No new regressions were introduced in logs/manifests or UX.

If any check fails, capture:
- The exact command you ran.
- Full traceback or log.
- What you expected vs. what you observed.

Then we can design a targeted PR to address that specific issue without disturbing the rest of the system.
