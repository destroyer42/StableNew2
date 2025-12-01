✅ PR-048 — V2 Core Classification & Archive System (Updated for Snapshot 20251130-190519)
Purpose: create a repeatable, automated V1/V2 file classifier, archive leftovers, and generate a human-readable inventory.
1. Summary

The repository contains mixed V1 and V2 artifacts spread across src/, tests/, and docs/. Some V1 files are manually archived, but classification is inconsistent and not automated. This PR introduces:

A classification script that scans the entire repo.

A predictable output:

tools/v2_classify_and_archive.py

docs/StableNew_V2_Inventory.md

inventory/stable_v2_inventory.json

Automatic detection of V1 vs V2 vs Unknown files.

A repeatable safe-move mechanism that moves V1 artifacts to /archive (but only after explicit confirmation).

No functional code changes; this is purely a structural maintenance PR.

2. Allowed Files

New:

tools/v2_classify_and_archive.py

inventory/stable_v2_inventory.json

docs/StableNew_V2_Inventory.md

May be modified:

archive/ folder organization (moving files only)

tests/ (only if new classification tests are added)

3. Forbidden Files

src/pipeline/executor.py

src/main.py

All GUI code (src/gui/**)

Any module under src/controller/**

src/api/**

These MUST NOT be changed.

4. Implementation Details
4.1 Classification Rules (Snapshot-Aware)

The classifier inspects file paths and content patterns:

Category	Criteria
V2	Files under: src/gui_v2/, src/gui/views/*_v2.py, src/gui/stage_cards_v2/, src/controller/app_controller.py (V2), src/app_factory.py, src/gui/main_window_v2.py, all V2 tests.
V1	Files under src/gui/ without _v2 suffix, legacy stage cards (txt2img_stage_card.py, etc.), V1 tests in archive/tests_v1.
Shared	Utility modules (src/utils/**), config modules, non-GUI models (queue, runner, history).
Unknown	Anything else, requiring manual labeling.

Script creates output JSON with fields:

{
  "v2_modules": [...],
  "v1_modules": [...],
  "shared": [...],
  "unknown": [...]
}

4.2 Markdown Inventory Generation

The script creates:

docs/StableNew_V2_Inventory.md:

Table of all modules grouped by category

Reachability notes (based on WIRING_V2_5_ReachableFromMain)

Links to archived files

Summaries per subsystem (GUI, controller, pipeline, api)

4.3 Optional Archiving

When run with --archive, the script:

Moves all V1-classified files into /archive/{folder} matching original tree.

Logs the moves.

Ensures imports are not affected (V1 code should be unused anyway).

5. Tests

Add optional tests:

tests/tools/test_v2_classify_and_archive.py

Ensures classifier identifies V1 vs V2 using sample file fixtures.

Verifies JSON output format.

6. Definition of Done

Classification script added.

JSON inventory generated.

Markdown inventory generated.

Optional archive process works safely.

No production code changed.