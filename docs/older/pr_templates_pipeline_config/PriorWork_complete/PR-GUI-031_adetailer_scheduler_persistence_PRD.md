# PR-GUI-031_adetailer_scheduler_persistence — ADetailer scheduler persistence in PromptPack editor

## 1. Title
PR-GUI-031_adetailer_scheduler_persistence — ADetailer scheduler persistence in PromptPack editor

## 2. Summary
The ADetailer scheduler dropdown in the PromptPack editor does not persist its value when using "Apply Editor → Pack(s)" and reloading the pack. The dropdown always shows "inherit" after reload, even when a specific scheduler (e.g. "Karras") was selected and applied.

This PR wires the ADetailer scheduler field through the PromptPack editor's save/load path so that:
- Editor → Pack: The scheduler selection is written into the pack configuration when applying changes.
- Pack → Editor: When a pack is loaded, the editor correctly initializes the ADetailer scheduler dropdown from the stored value.
- Packs without a scheduler field continue to default to "inherit" safely.

## 3. Problem Statement
Current observed behavior:
- ADetailer scheduler dropdown exists and defaults to "inherit".
- Changing the scheduler in the Editor and clicking "Apply Editor → Pack(s)" appears to succeed visually.
- After saving/loading or reloading the pack, the scheduler dropdown is back to "inherit" instead of the selected value.

This indicates that at least one of the following is true:
- The ADetailer scheduler is not written into the pack data when applying editor changes.
- It is written under a key the loader does not read.
- The loader ignores the stored scheduler and always falls back to the "inherit" default.

The result is that ADetailer scheduler configuration is not round-tripped through PromptPacks, breaking parity with the StableNew configuration model and Stable Diffusion WebUI's own ADetailer controls.

## 4. Goals
1. Ensure that the ADetailer scheduler selection in the PromptPack editor is persisted into the pack configuration when the user clicks "Apply Editor → Pack(s)".
2. Ensure that when a pack is loaded into the editor, the ADetailer scheduler dropdown reflects the stored value, or "inherit" if absent.
3. Keep pack schema changes minimal and backwards-compatible (older packs without this field must still work).

## 5. Non-goals
- No changes to the ADetailer runtime pipeline behavior (that is handled in separate PRs).
- No changes to sampler/scheduler behavior for the main txt2img/img2img pipeline beyond what already exists.
- No changes to CancelToken behavior, logging, or controller.
- No changes to PromptPack search, filtering, or other unrelated editor features.

## 6. Allowed Files
Exact file names should be confirmed against REPO_SNAPSHOT.md, but the allowed files are constrained by responsibility:

- GUI / PromptPack editor mapping:
  - The PromptPack editor GUI module (e.g. src/gui/prompt_pack_editor.py or similar) where:
    - The "Apply Editor → Pack(s)" button handler lives.
    - Editor widgets are mapped to an in-memory pack structure.
- ADetailer config panel, if needed for load/save glue:
  - src/gui/adetailer_config_panel.py or equivalent (only to ensure its API matches what the editor expects).
- Pack schema / IO (if present):
  - The module responsible for reading/writing PromptPack definitions to disk (e.g. src/utils/prompt_pack_io.py or similar), but only for adding/reading the ADetailer scheduler field.

- Tests:
  - tests/gui/test_prompt_pack_editor.py or the closest existing GUI test module that covers PromptPack editor behavior.
  - If there is no such module, a small new test module under tests/gui/ focused on PromptPack editor persistence is allowed.

## 7. Forbidden Files
- All controller modules (src/controller/...).
- Pipeline modules (src/pipeline/...).
- Randomizer/matrix modules (src/utils/randomizer.py, etc.).
- Structured logging/manifest modules.
- Configuration/build files (pyproject, requirements, etc.).

If a change appears necessary outside the allowed files, stop and request a new PR design rather than guessing.

## 8. Step-by-step Implementation

### 8.1 Identify the pack data model for ADetailer
1. Using REPO_SNAPSHOT.md, locate where PromptPack definitions are modeled. There will be a pack structure (dict/dataclass) that includes sections for:
   - txt2img settings,
   - img2img settings,
   - ADetailer settings (model, prompts, denoise, etc.).

2. Confirm whether the ADetailer scheduler field is already present in the pack model:
   - If present, note its key name (e.g. "scheduler", "adetailer_scheduler", etc.).
   - If absent, extend the ADetailer section to include a scheduler field with a clear, simple key (e.g. "scheduler"), defaulting to "inherit" when not specified.

   This extension must be backwards-compatible:
   - Older packs without the field must still load (scheduler defaults to "inherit").
   - New packs may include the field.

### 8.2 Wire Editor → Pack mapping for ADetailer scheduler
3. In the PromptPack editor GUI module (e.g. PromptPackEditor), locate the method that:
   - Reads all editor widgets (including ADetailer fields).
   - Writes them into the pack data structure when "Apply Editor → Pack(s)" is clicked.

4. Ensure the ADetailer scheduler dropdown's variable (e.g. self.adetailer_scheduler_var or an accessor on ADetailerConfigPanel) is included in that mapping:
   - Read its value (e.g. value = self.adetailer_scheduler_var.get()).
   - Map it into the ADetailer section of the pack, using the agreed key (e.g. "scheduler").

   Behavior:
   - If the value is an empty string, treat it as "inherit".
   - If the value is "inherit", store "inherit" explicitly or omit the field, depending on existing schema conventions. If omitted, the loader must default to "inherit".

### 8.3 Wire Pack → Editor mapping for ADetailer scheduler
5. In the same or related module, locate the method that loads a pack definition into the editor widgets (e.g. _load_pack_into_editor(pack)).

6. Update the mapping for ADetailer settings so that:
   - It reads the scheduler from the ADetailer section, using the same key as above.
   - If the field is absent, default to "inherit".
   - Sets the editor dropdown variable accordingly:
     - self.adetailer_scheduler_var.set(stored_value_or_inherit), or the equivalent panel setter.

7. If needed, ensure that ADetailerConfigPanel provides a clean getter/setter or config accessor for the scheduler value that the PromptPack editor can use, rather than reaching into internal widgets directly.

### 8.4 Tests for persistence
8. Add tests under tests/gui/ to verify ADetailer scheduler persistence. For example, in tests/gui/test_prompt_pack_editor.py (or a new file):

   - test_adetailer_scheduler_round_trip_in_prompt_pack_editor:

     1. Create an in-memory pack with no ADetailer scheduler field.
     2. Initialize the editor with this pack.
     3. Assert that the ADetailer scheduler dropdown shows "inherit".
     4. Change the dropdown to "Karras".
     5. Invoke the editor's "apply to pack" helper (the same logic that the button uses).
     6. Assert that the resulting pack structure now contains "scheduler": "Karras" under the ADetailer section.
     7. Re-initialize a fresh editor instance from this updated pack.
     8. Assert that the ADetailer scheduler dropdown now shows "Karras".

   - Add a second test to ensure backwards compatibility with older packs:

     - test_adetailer_scheduler_defaults_to_inherit_when_missing:

       1. Create an in-memory pack that has no ADetailer scheduler key at all.
       2. Load into the editor.
       3. Assert that the dropdown shows "inherit" and no errors occur.

## 9. Required Tests
After implementing this PR:

- Run GUI-focused tests:

  - pytest tests/gui/test_prompt_pack_editor.py -v  (or the actual module you touch)

- Run a quick sanity check on the broader suite:

  - pytest tests/gui -v
  - pytest

## 10. Acceptance Criteria
- Changing the ADetailer scheduler in the PromptPack editor and clicking "Apply Editor → Pack(s)" updates the pack configuration with the correct scheduler value.
- Reloading the same pack shows the scheduler dropdown with the previously saved value (e.g. "Karras") rather than "inherit".
- Packs without a scheduler field still load with "inherit" as the dropdown value, and no errors.
- No regressions in other PromptPack editor features.

## 11. Rollback Plan
- Revert changes to:
  - The PromptPack editor GUI module.
  - Any pack IO/schema modules touched.
  - Newly added or modified tests.
- Re-run pytest to confirm behavior returns to the prior baseline.
