## 2) Codex Prompt (to paste into Copilot / GPT-5.1-Max as the actual instructions)

```text
You are implementing PR-CORE-V2-CLASSIFY-ARCHIVE(P1V3)(11-28-2025)-001 in the StableNew repo.

GOAL
Add a classification + archive script that:
- Walks the repo and classifies Python files as v2_canonical, legacy_v1, v2_experimental, or unknown.
- Emits:
  - repo_inventory_classified.json (machine readable)
  - docs/StableNew_V2_Inventory.md (human readable)
- Provides an optional, explicit archive mode to move legacy_v1 files and V1-only tests into an archive/ tree.
DO NOT modify any runtime logic beyond adding this script and documentation and moving files in archive mode.

BRANCH
- Work on the current branch (e.g., cleanHouse), do NOT create a new one.

PRE-STEP (I will do this manually)
- I will run the snapshot script before using your changes.

CONSTRAINTS
- Do NOT edit:
  - src/main.py
  - src/app_factory.py
  - src/pipeline/executor.py
  - Any *_v2.py files.
- Do NOT change the content of existing .py or test files (only the new script, docs, and file moves for archived files).
- Do NOT touch WebUI behavior, GUI layouts, or controller logic.
- Do NOT add new third-party dependencies (stdlib only).
- Archive moves must be EXPLICITLY requested with a CLI flag; default behavior is report-only.

TASKS

1) Add classification script

Create: tools/v2_classify_and_archive.py

Behavior:
- CLI:
  - python tools/v2_classify_and_archive.py --mode report [--root .] [--verbose]
  - python tools/v2_classify_and_archive.py --mode archive --apply-archive [--root .] [--verbose]
- Modes:
  - report:
    - Walk src/ and tests/ (under the given root).
    - For each .py file (excluding archive/):
      - Classify as:
        - v2_canonical
        - legacy_v1
        - v2_experimental
        - unknown
      - Record reasons (list of strings).
    - Generate:
      - repo_inventory_classified.json in repo root.
      - docs/StableNew_V2_Inventory.md as a markdown report.
    - DOES NOT move any files.

  - archive:
    - First behaves like report (in-memory).
    - If --apply-archive is NOT provided:
      - Print what WOULD be moved (dry run) and exit with code 0.
    - If --apply-archive IS provided:
      - Create archive directories if missing:
        - archive/gui_v1/
        - archive/api_v1/
        - archive/tests_v1/
        - archive/misc_v1/
      - Move files classified as legacy_v1 into these directories based on path heuristics:
        - src/gui/* -> archive/gui_v1/
        - src/api/* -> archive/api_v1/
        - tests/* -> archive/tests_v1/
        - everything else -> archive/misc_v1/
      - For moved test files:
        - Optionally rename to ensure they are not discovered by pytest (e.g., keep names but they live outside tests/).
      - Update repo_inventory_classified.json and docs/StableNew_V2_Inventory.md after moves.

Classification heuristics (implement as clearly as possible):
- Skip anything already under archive/.
- v2_canonical if:
  - filename contains '_v2' (e.g., main_window_v2.py, pipeline_panel_v2.py, advanced_txt2img_stage_card_v2.py), OR
  - file lives in a v2-specific directory if such exists (e.g., src/gui/v2/), OR
  - referenced/imported by src/main.py, src/app_factory.py, src/pipeline/executor.py, or V2-focused tests.
- legacy_v1 if:
  - There exists a sibling _v2 variant (foo.py + foo_v2.py -> foo_v2 is v2_canonical, foo is legacy_v1), OR
  - File is only imported by other legacy_v1 files or V1-labeled tests (e.g., test_gui_v1_*.py), OR
  - File contains textual markers like 'LEGACY', 'V1 GUI', etc. (if present).
- v2_experimental if:
  - Filename contains '_v2' or key V2 markers, but there are no imports from main.py/app_factory/executor or active tests.
- unknown otherwise.

The JSON format should be:
{
  "generated_at": "...",
  "root": "...",
  "files": [
    {
      "path": "src/gui/main_window_v2.py",
      "classification": "v2_canonical",
      "reasons": ["filename_contains_v2", "imported_by: src/main.py"]
    },
    ...
  ]
}

The Markdown file docs/StableNew_V2_Inventory.md should contain:
- Generated timestamp
- Sections:
  - V2 Canonical
  - Legacy V1 (Candidates for Archive)
  - V2 Experimental
  - Unknown (Needs Manual Review)
Each section is just a bullet list of file paths.

2) Archive tree

- Do not pre-create archive directories in the repo; only create them from the script when needed in archive mode.
- Archive path rules:
  - src/gui/... -> archive/gui_v1/...
  - src/api/... -> archive/api_v1/...
  - tests/... -> archive/tests_v1/...
  - all other legacy_v1 -> archive/misc_v1/...

3) Tests

- After you implement the script, run:
  - python tools/v2_classify_and_archive.py --mode report
  - pytest -q
- Ensure:
  - The script runs in report mode without errors.
  - pytest still runs successfully (no new failures introduced by this PR).

DO NOT:
- Adjust any existing tests to depend on this script.
- Change how pytest is invoked.
- Modify runtime code, other than adding this script and docs.

OUTPUT
- Show me a summary of:
  - The new script structure (key functions, CLI handling).
  - Example commands to run the script.
  - Any caveats or assumptions you had to make about file locations.