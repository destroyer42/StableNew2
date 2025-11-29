# PR-06D — Stage Card Prototype Cleanup (Optional, After Human Review)

> ⚠️ **This PR is intentionally marked as optional and should only be executed after a human has visually verified the V2 stage-card UX and confirmed that prototype cards are no longer needed.**

## Summary

By the time PR-06A/B/C are complete:

- All **advanced** stage cards under `src/gui/stage_cards_v2/` will:
  - Inherit from `BaseStageCardV2`
  - Use shared components
  - Be wired into the V2 pipeline

At that point, the earlier **prototype stage cards** in `src/gui/` may be fully superseded. This PR provides a **cleanup path** for those prototypes **if and only if** they are truly unused and not needed for future experiments.

This PR should be applied **only after human confirmation** that:

- The advanced V2 cards cover all required functionality.
- No tests, controllers, or future design docs depend on the older prototype cards.

---

## Candidates for Cleanup

Prototype / earlier stage-card modules that have been conceptually replaced by the advanced V2 cards:

- `src/gui/txt2img_stage_card.py`
- `src/gui/img2img_stage_card.py`
- `src/gui/upscale_stage_card.py`

> These were part of the V2 journey but are not currently wired into `MainWindowV2` and not referenced in V2 tests.

Before executing this PR, **re-run a reachability check** (e.g., `repo_inventory.json`) and confirm they are not imported anywhere in active code or tests.

---

## Cleanup Options

There are two approaches; choose one depending on how cautious you want to be.

### Option 1 — Archive Prototypes

Move the files into an archive folder instead of deleting them:

**From:**

```text
src/gui/txt2img_stage_card.py
src/gui/img2img_stage_card.py
src/gui/upscale_stage_card.py
```

**To:**

```text
archive/gui_stage_cards_prototypes/txt2img_stage_card.py
archive/gui_stage_cards_prototypes/img2img_stage_card.py
archive/gui_stage_cards_prototypes/upscale_stage_card.py
```

Update `archive/ARCHIVE_MAP.md` with entries like:

```text
src/gui/txt2img_stage_card.py -> archive/gui_stage_cards_prototypes/txt2img_stage_card.py  # V2 prototype card, superseded by advanced_*_stage_card_v2
```

This preserves the code for future reference with near-zero risk.

### Option 2 — Mark as Deprecated In-Place (No Move Yet)

If you prefer not to move files at all yet, but want to make their status explicit:

- Leave the files where they are.  
- Add a **module-level docstring** at the top of each prototype file:

```python
"""
DEPRECATED STAGE CARD PROTOTYPE.

This module is kept for historical/reference purposes. The active V2 stage cards
live under src/gui/stage_cards_v2/advanced_*_stage_card_v2.py and inherit from
BaseStageCardV2.

Do not add new functionality here. Prefer updating the advanced V2 cards instead.
"""
```

- Optionally, add a short note to `docs/` (e.g., `docs/V2_StageCard_Status.md`) explaining which cards are active vs. deprecated.

This approach changes **no imports, no paths, no runtime behavior** but clearly communicates intent.

---

## Implementation Steps (If Archiving)

1. Confirm via static analysis / `repo_inventory.json` that:
   - No active module imports: `txt2img_stage_card`, `img2img_stage_card`, `upscale_stage_card`.
   - No tests import them directly.

2. Create archive directory (if not already present):

```text
archive/gui_stage_cards_prototypes/
```

3. Move the three prototype files into that directory.

4. Update `archive/ARCHIVE_MAP.md` with one line per move.

5. Run tests:

```bash
pytest tests/controller -v
pytest tests/gui_v2 -v
```

6. Launch the app and confirm there is no functional change.

---

## Files Touched

Depending on chosen option:

**Option 1 (archive):**

- Move:
  - `src/gui/txt2img_stage_card.py` → `archive/gui_stage_cards_prototypes/txt2img_stage_card.py`
  - `src/gui/img2img_stage_card.py` → `archive/gui_stage_cards_prototypes/img2img_stage_card.py`
  - `src/gui/upscale_stage_card.py` → `archive/gui_stage_cards_prototypes/upscale_stage_card.py`
- Update:
  - `archive/ARCHIVE_MAP.md`
  - `archive/README.md` (optional note about prototypes)

**Option 2 (deprecate in-place):**

- Update:
  - `src/gui/txt2img_stage_card.py`
  - `src/gui/img2img_stage_card.py`
  - `src/gui/upscale_stage_card.py`

---

## Acceptance Criteria

- Human has explicitly confirmed that advanced V2 stage cards cover all needed functionality.  
- After applying the chosen cleanup path:
  - All tests still pass.
  - App behavior is unchanged.
- It’s clear from the codebase which stage cards are **active V2** and which are **deprecated prototypes**.
