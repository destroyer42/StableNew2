# PR-CORE-V2-CLASSIFY-ARCHIVE-V1-001 — V1 Classification & Archive Script (Phase 1)

## Intent

Introduce a **single, explicit classification script** to identify:

- Canonical V2 files
- Legacy V1 files (to be archived)
- V2 experimental files (new, but not yet wired)
- Unknown/unclassified files

…and provide a **safe, opt-in archive path** for V1 files and V1-only tests.

This PR must **not** modify any runtime logic outside of:

- Adding the new script
- Adding documentation
- Moving clearly identified V1/V1-test files into `archive/` (when the script is run with an explicit flag)

The goal is to:

- Make V1 vs V2 boundaries explicit
- Prepare for a clean V2-only world
- Avoid accidental imports of V1 code during Phase 1

---

## Scope

**In scope**

1. Add a new classification & archive tool:

   - `tools/v2_classify_and_archive.py`

   Responsibilities:

   - Walk the repo (starting at repo root or `src/` and `tests/`)
   - Classify `.py` files into:
     - `v2_canonical`
     - `legacy_v1`
     - `v2_experimental`
     - `unknown`
   - Write outputs to:
     - `repo_inventory_classified.json` (machine-friendly)
     - `docs/StableNew_V2_Inventory.md` (human-readable)
   - Optionally (explicit flag only) move V1 files into an `archive/` tree.

2. Introduce archive structure (created only when the archive step runs):

   - `archive/gui_v1/`
   - `archive/api_v1/`
   - `archive/tests_v1/`
   - `archive/misc_v1/`

3. Retire V1-only tests by **moving** them under `archive/tests_v1/` and ensuring they are no longer discovered by `pytest` (e.g., directory is outside `tests/` and/or files renamed so they no longer start with `test_`).

4. Add documentation:

   - `docs/StableNew_V2_Inventory.md` — human-readable index of V1/V2/experimental files.
   - A short section in `docs/StableNew_Dev_Doctrine.md` (if it exists) or a new doc note explaining:
     - How to run the script in `--report` mode
     - How to run it with `--apply-archive` (after review)

**Out of scope**

- Any edits to:
  - GUI V2 files (e.g., `main_window_v2.py`, `pipeline_panel_v2.py`, `advanced_txt2img_stage_card_v2.py`)
  - Pipeline/executor logic
  - Controller logic
  - WebUI healthcheck / discovery logic
- Any non-move content changes to existing `.py` or test files.

---

## Guardrails

1. **Snapshot required before changes**

   - Before running this script in any destructive mode, you MUST:
     - Run the snapshot script (`snapshot_and_inventory.bat` or equivalent).
     - Record the snapshot name in this PR under “Verification”.

2. **Two-stage operation**

   - **Stage 1 (safe):** Classification-only
     - `python tools/v2_classify_and_archive.py --mode report`
     - Generates JSON + Markdown inventory.
     - No files moved.
   - **Stage 2 (destructive, opt-in):** Apply archive
     - `python tools/v2_classify_and_archive.py --mode archive --apply-archive`
     - Moves V1 + V1 tests into `archive/`.
     - Only run this after snapshot + manual review of the report.

3. **No implicit magic**

   - Script must:
     - Stick to transparent, documented heuristics.
     - Log decisions per-file (why something is considered V1 vs V2).

4. **Tests must still run**

   - After V1 tests are moved to `archive/tests_v1`, `pytest` must:
     - Still run successfully.
     - Not try to discover/run archived tests by default.

---

## Classification Rules (Heuristics)

The script should classify `.py` files using **explicit heuristics**:

1. **Skip archive itself**

   - Any path under `archive/` is skipped.

2. **V2 Canonical**

   A file is **v2_canonical** if ANY of the following:

   - Filename contains `_v2` (e.g., `main_window_v2.py`, `pipeline_panel_v2.py`, `advanced_txt2img_stage_card_v2.py`)
   - It lives in an explicit V2 directory (if present), e.g., `src/gui/v2/`
   - It is directly imported by:
     - `src/main.py`
     - `src/app_factory.py`
     - `src/pipeline/executor.py`
     - Other clearly V2 entrypoints (e.g., `test_entrypoint_uses_v2_gui.py`)
   - Tests referencing it are clearly V2 (their names contain `_v2`, or test docstring mentions V2 GUI).

3. **Legacy V1**

   A file is **legacy_v1** if ANY of the following:

   - There is a `_v2` sibling:
     - e.g., `src/gui/main_window.py` + `src/gui/main_window_v2.py`
       - classify `main_window.py` as `legacy_v1`, `main_window_v2.py` as `v2_canonical`
   - Tests that target it have V1 signaling:
     - Filenames like `test_gui_v1_*`, `test_main_window_legacy.py`, or mention “V1 GUI” in comments.
   - The file itself contains markers such as:
     - `# LEGACY`, `# V1 GUI`, `# TODO: remove when V2 is stable`, etc. (if present)
   - It is only imported by other files classified as `legacy_v1`.

4. **V2 Experimental**

   A file is **v2_experimental** if:

   - It has `_v2` in its name or V2-style class naming,
   - But it is **not referenced** by:
     - `main.py`, `app_factory.py`, `executor.py`, or
     - Any currently active tests under `tests/`.
   - Example: future randomization engine v2, advanced prompt editor v2, learning hooks v2.

5. **Unknown**

   If no heuristics match:

   - classify as `unknown`.
   - These should be listed separately in the report for manual review.

---

## Script Behaviors

### Location

- Add: `tools/v2_classify_and_archive.py`

### CLI Interface

- Example usage:

  ```bash
  # Report-only mode (safe)
  python tools/v2_classify_and_archive.py --mode report

  # Archive V1 files + tests (destructive, only after snapshot & review)
  python tools/v2_classify_and_archive.py --mode archive --apply-archive
Arguments:

--mode (required): report or archive

--root (optional): repo root (default: .)

--apply-archive (required flag for actually moving files; otherwise archive mode should be a dry-run)

--verbose (optional): emit detailed per-file logging

Outputs
JSON inventory

repo_inventory_classified.json at repo root:

jsonc
Copy code
{
  "generated_at": "2025-11-28T03:21:45Z",
  "root": ".",
  "files": [
    {
      "path": "src/gui/main_window_v2.py",
      "classification": "v2_canonical",
      "reasons": ["filename_contains_v2", "imported_by: src/main.py"]
    },
    {
      "path": "src/gui/main_window.py",
      "classification": "legacy_v1",
      "reasons": ["sibling_v2_exists: src/gui/main_window_v2.py"]
    },
    {
      "path": "src/randomization/randomizer_v2.py",
      "classification": "v2_experimental",
      "reasons": ["filename_contains_v2", "no_imports_detected"]
    }
  ]
}
Markdown summary

docs/StableNew_V2_Inventory.md:

Sections:

markdown
Copy code
# StableNew V2 Inventory (Generated)

- Generated at: 2025-11-28T03:21:45Z

## V2 Canonical

- src/gui/main_window_v2.py
- src/gui/pipeline_panel_v2.py
- ...

## Legacy V1 (Candidates for Archive)

- src/gui/main_window.py
- src/gui/pipeline_panel.py
- ...

## V2 Experimental

- src/learning/learning_hooks_v2.py
- src/prompt/advanced_prompt_editor_v2.py
- ...

## Unknown (Needs Manual Review)

- src/misc/old_helper.py
- ...
Archive actions (only with --apply-archive)

V1 files moved:

src/gui/main_window.py → archive/gui_v1/main_window_v1 (OLD).py

src/gui/pipeline_panel.py → archive/gui_v1/pipeline_panel_v1 (OLD).py

src/api/webui_healthcheck_legacy.py → archive/api_v1/webui_healthcheck_legacy (OLD).py

V1 tests moved:

tests/test_gui_v1_main_window.py → archive/tests_v1/gui/test_gui_v1_main_window_archived.py

tests/test_main_window_legacy.py → archive/tests_v1/gui/test_main_window_legacy_archived.py

Archived test files must not be picked up by pytest:

They live outside tests/, and

Optionally names not starting with test_.

Files to Add
tools/v2_classify_and_archive.py

docs/StableNew_V2_Inventory.md (auto-generated; committed after first run in --mode report)

If not present:

docs/StableNew_Dev_Doctrine.md (or edit existing to reference this script briefly)

Files to Modify
None content-wise, except:

If you need to add archive/ to .gitignore patterns (if not desired to track everything).
Otherwise, archive files remain fully tracked.

Files to Move (when running archive mode)
These moves are performed by the script, not hand-edited.
Exact list will depend on actual repo inventory.

src/gui/* legacy V1 files → archive/gui_v1/…

src/api/* legacy V1 helpers → archive/api_v1/…

tests/* legacy V1 tests → archive/tests_v1/…

Forbidden
For this PR:

❌ Do not modify:

src/main.py

src/app_factory.py

src/pipeline/executor.py

Any *_v2.py files

❌ Do not change the contents of any existing .py or test file (other than file moves).

❌ Do not adjust WebUI behavior, GUI layouts, or controller behavior.

❌ Do not introduce new third-party dependencies (stick to stdlib).

Developer / Codex Checklist
Before coding

 Run snapshot script (e.g., snapshot_and_inventory.bat) and record name here:
Snapshot used: ______________________

 Note current branch: cleanHouse (or as appropriate)

Implementation

 Add tools/v2_classify_and_archive.py with CLI as described.

 Implement classification heuristics.

 Write JSON + Markdown outputs.

 Implement archive move logic (guarded by --apply-archive).

Verification

Classification only

 Run: python tools/v2_classify_and_archive.py --mode report

 Inspect repo_inventory_classified.json

 Inspect docs/StableNew_V2_Inventory.md

Archive (manual decision)

 (Optional for this PR) Run:
python tools/v2_classify_and_archive.py --mode archive --apply-archive

 Confirm V1 files/tests moved correctly under archive/.

Tests

 Run: pytest -q

 Confirm no archived tests run; active tests still execute.

Notes for Future Phases
This script + inventory is the foundation for:

Phase 1: V2-only GUI scaffold & wiring

Phase 2+: safely reintroducing V2 experimental features (randomization, advanced prompt editor, learning hooks) intentionally.

End of PR spec.