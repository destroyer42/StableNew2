# StableNew – Agent Instructions (V2/V2.5 Enforcement)

These instructions govern how coding agents work anywhere inside this repository.  
They override default behavior. Agents should treat these as authoritative and only explore when a file is clearly outdated.

---

## 1. Architectural Boundaries (Strict)

Agents must obey these boundaries at all times:

**GUI layer (`src/gui/`)**
- May call: controller, utils.
- Must NOT call: pipeline, learning, api, cluster, ai.
- Avoid adding new Tk dependencies outside the GUI layer.

**Controller layer (`src/controller/`)**
- Mediator between GUI ↔ pipeline/learning/api.
- GUI never directly calls pipeline or learning.

**Pipeline layer (`src/pipeline/`)**
- Pure logic. No GUI imports. Minimal cross-dependencies.
- Orchestrates txt2img → img2img → upscale execution.

**Learning layer (`src/learning/`)**
- Houses learning records, datasets, weight updates.
- No Tk imports. Must not reference GUI modules.

**API / Process layer (`src/api/`)**
- Handles SD/WebUI process start/stop, network calls, async status checks.
- Must not import GUI.

**archive/**
- Read-only. Never add new code.
- Used only for reference if migrating V1 → V2.

Agents **must not** introduce cross-layer calls that violate the above.

---

## 2. Rules for Modifying Files

When editing existing files, agents should:

1. **Respect existing naming patterns**  
   - V2 modules end in `_v2.py` or exist under `panels_v2/`.  
   - New intermediate designs follow `V2.5_YYYY-MM-DD` suffixes when in docs or non-code files.

2. **Prefer minimal diffs**  
   - Modify only what is needed for correctness.  
   - Avoid repo-wide transformations unless explicitly requested.

3. **Never expand legacy modules**  
   - V1 files: marked with `(OLD)` or located under `archive/`.
   - Do NOT import them from V2 code.

4. **Maintain syntax & lint correctness**  
   Agents must check their work and ensure:
   - No stray parentheses.
   - No indentation drift.
   - Imports resolved.
   - Ruff passes for touched files.

5. **Add or update tests as needed**  
   - Tests mirror the `src/` structure.
   - New features require tests in the corresponding folder.

6. **Prefer composition over rewriting**  
   - Extend controllers before extending GUI or pipelines where appropriate.

---

## 3. Commands Agents Should Assume

**Run app:**
```bash
python -m src.main
Run tests:

bash
Copy code
pytest -q
Run full verbose tests:

bash
Copy code
pytest -vv
Lint:

bash
Copy code
ruff check src
Agents should assume all changes must pass both linting and tests.

4. Exploration Rules
Agents should NOT:

Search root recursively for “how to build” unless instructions are missing.

Invent new folder structures.

Modify GitHub workflows or suppress test failures.

Introduce new dependencies without explicit approval.

Agents MAY:

Perform minimal search for the exact symbol/function referenced in a change request.

Inspect the architecture docs under docs/ for confirmation.

5. V1/V2 Migration Awareness
Agents should treat:

src/gui, src/controller_v2, src/gui/panels_v2, src/gui/app_layout_v2
as living V2.

archive/**, *_OLD.py, and any legacy directories
as dead code, used only as reference during migration.

Agents should ALWAYS default to V2 logic and never re-enable V1 paths.

6. Use of File Access Logger (V2.5)
Agents should:

Respect src/utils/file_access_log_v2.5_* as the canonical place for runtime file auditing.

Not modify the logger unless explicitly requested.

Assume the logger is part of the V2.5 cleanup process and must not break.

7. When in Doubt
Agents should:

Prefer existing patterns already present in V2 modules.

Trust these instructions over ad-hoc exploration.

Avoid guessing architecture or flow when documentation exists.

If truly necessary, agents may search locally for definitions—but only after consulting these rules.