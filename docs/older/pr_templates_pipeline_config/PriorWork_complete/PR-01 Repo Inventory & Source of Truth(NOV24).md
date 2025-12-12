# PR-01 — Repo Inventory & Source of Truth Declaration

## Summary

Create a small, focused tooling layer that inventories the repository, identifies active modules used by the running app, and flags likely legacy/V1 files. This PR does **not** move or delete anything; it only observes and records.

This is the foundation for subsequent cleanup and refactors.

---

## Motivation

- The repository currently contains a mix of V1 and V2 GUI and pipeline files.  
- Without a clear understanding of what is actually used at runtime, refactors are risky and brittle.  
- Automated tools (e.g., CODEX) need a machine-readable view of the codebase to make safe modifications.

---

## Scope

**In scope:**

- New inventory script(s) and supporting modules.  
- New documentation files summarizing active modules and legacy candidates.  

**Out of scope:**

- Moving or deleting any code.  
- Changing `src/main.py` or the current runtime behaviour of the app.

---

## Implementation Plan

1. **Create tooling module**  
   - Add a `tools/` or `scripts/` package (e.g., `tools/inventory_repo.py`).  
   - This script must be runnable via `python -m tools.inventory_repo` from the repo root.

2. **Walk the code tree**  
   - Recursively walk key directories (at minimum `src/`, optionally `tests/`, `docs/`).  
   - For each `*.py` file record:
     - Path (relative to repo root).  
     - Whether it imports `tkinter` / `ttk`.  
     - Whether the filename or top-level comment contains `v1`/`V1`.  
     - Simple metrics (e.g., line count) to help eyeball complexity.

3. **Static import graph**  
   - Attempt to build a simple import graph starting from `src/main.py`:  
     - Use `ast` or a basic heuristic to find `import ...` and `from ... import ...` statements.  
     - Traverse reachable modules to mark them as “active”.  
   - This does not need to be perfect — a best-effort static analysis is sufficient.

4. **Outputs**  
   - `repo_inventory.json` (machine-readable):
     - per-file info, plus flags like `"is_gui": true`, `"has_v1_marker": true`, `"reachable_from_main": true`.  
   - `ACTIVE_MODULES.md` (human-readable):
     - summarise main packages and modules used by the running app.  
   - `LEGACY_CANDIDATES.md` (human-readable):
     - list of files suspected to be V1 or unused, grouped by probable category (GUI, pipeline, tools).

5. **Developer convenience**  
   - Add a short section to `README` or `docs/` explaining how to run the inventory script and what the outputs mean.

---

## Files Expected to Change / Be Added

- **New:** `tools/inventory_repo.py` (or equivalent path).  
- **New:** `repo_inventory.json` (generated, may be git-ignored depending on policy).  
- **New:** `docs/ACTIVE_MODULES.md`  
- **New:** `docs/LEGACY_CANDIDATES.md`  
- **Possible:** minor additions to `README.md` or `docs/` index.

No existing source files should be modified for this PR beyond minor documentation updates.

---

## Tests & Validation

- Run the script locally: `python -m tools.inventory_repo`  
  - Confirm that it completes without throwing exceptions.  
  - Confirm that `repo_inventory.json` is populated with all expected `.py` files.  
  - Confirm that `ACTIVE_MODULES.md` and `LEGACY_CANDIDATES.md` are generated and readable.

- Manual spot-checks:
  - Verify that known active modules (e.g., the current GUI entrypoint and pipeline client) show as reachable from `src/main.py`.  
  - Verify that obviously legacy/V1 files appear in `LEGACY_CANDIDATES.md`.

---

## Acceptance Criteria

- The repository contains a runnable inventory script.  
- After running the script, the three output artifacts (`repo_inventory.json`, `ACTIVE_MODULES.md`, `LEGACY_CANDIDATES.md`) exist and correctly list files.  
- No runtime behaviour of the StableNew app is changed by this PR.