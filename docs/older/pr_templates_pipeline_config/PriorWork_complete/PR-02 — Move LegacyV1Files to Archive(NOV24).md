PR-02 — Move Legacy/V1 Files to Archive

## Summary

Using the outputs from PR-01, create a clear separation between active V2 code and legacy/V1 code by moving legacy files into dedicated `archive/` directories. Ensure that the app still runs and that no archived modules are imported in normal operation.

---

## Motivation

- The mixture of V1 and V2 files is confusing for maintainers and automated tools.  
- Removing legacy code is risky; archiving it is safer while still reducing noise.  
- Future work (V2 app spine, theme, layout, learning system) should operate on a clearly-labelled V2 codebase.

---

## Scope

**In scope:**

- Creating `archive/` directories for GUI, pipeline, and other legacy code.  
- Moving V1/legacy files into those directories.  
- Fixing imports for any modules that depended on moved files, if still needed.

**Out of scope:**

- Rewriting the logic of any module beyond minimal import adjustments.  
- Implementing the V2 app spine (that is PR-03).

---

## Implementation Plan

1. **Define archive structure**  
   - Create directories such as:
     - `archive/gui_v1/`  
     - `archive/pipeline_v1/`  
     - `archive/tools_legacy/`  
   - Add a short `README.md` in `archive/` explaining purpose and retention policy.

2. **Select files to move**  
   - Start with `docs/LEGACY_CANDIDATES.md` from PR-01.  
   - For each candidate file:
     - Confirm that it is **not** imported (or that imports are only from other legacy modules).  
     - Double-check that there is a newer V2 equivalent when applicable.  
   - Maintain a mapping file, e.g. `archive/ARCHIVE_MAP.md`, that lists:
     - Original path → archive path.  
     - Reason for archival.

3. **Move files**  
   - Physically move the selected files to the appropriate archive directory.  
   - Update any remaining imports that refer to them and are still legitimately needed (for example, a tool that still expects an old module):
     - Either change the import path to point into `archive/...`, or  
     - Mark the dependent module as legacy and move it too.

4. **Guard against accidental imports**  
   - Add a simple mechanism to detect archive imports from active code, for example:
     - A check in `src/main.py` or a small unit test that fails if `archive.` appears in the import tree.  
   - Alternatively, agree that archived modules should only be imported by scripts in `archive/` and enforce that by convention.

5. **Update documentation**  
   - Update `ACTIVE_MODULES.md` to reflect that archived code is no longer considered active.  
   - Explain archive usage briefly in `docs/` or the repo README.

---

## Files Expected to Change / Be Added

- **New:** `archive/README.md`  
- **New:** `archive/ARCHIVE_MAP.md`  
- **Moved:** Various V1/legacy modules (GUI, pipeline, tools), paths to be determined from `LEGACY_CANDIDATES.md`.  
- **Updated:** `docs/ACTIVE_MODULES.md`  
- **Updated:** Any files that require import path adjustments due to the moves.

---

## Tests & Validation

- Run the app entrypoint: `python -m src.main`  
  - App should start successfully using the current GUI (even if it is still visually rough).  
- Run a basic pipeline job to confirm there are no obvious runtime errors.  
- Optionally run a simple script that tries to import all `src.` modules and fails if any import from `archive.` is detected in the active path.

---

## Acceptance Criteria

- All clearly legacy/V1 modules are moved under `archive/` directories.  
- The StableNew app still starts and can run a simple job.  
- `ACTIVE_MODULES.md` no longer lists archived files as active.  
- There is a documented map of which files were archived and why.
