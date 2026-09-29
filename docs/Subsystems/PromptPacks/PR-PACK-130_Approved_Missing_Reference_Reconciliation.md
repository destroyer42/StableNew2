# PR-PACK-130 — Approved Missing-Reference Reconciliation

Status: implemented and executed against real user data, with explicit
owner authorization for these exact actions. Merge not yet performed;
stopped for owner review per the authorizing task.

## Outcome

`tools/pack130_approved_reference_reconciliation.py` executed the
owner-approved subset of PR-PACK-120's 24 missing-reference triage items:

| Missing reference | Owner determination | Action | Items | Occurrences |
|---|---|---|---|---|
| `BetterThanWords-merged-SDXL-LoRA-v3` | A checkpoint/model, not a separately-applied LoRA | Remove the structured LoRA reference | 3 | 13 |
| `babesByStableYogiPony_xlV4` | A checkpoint/model, not a separately-applied LoRA | Remove the structured LoRA reference | 8 | 54 |
| literal `"None"` refiner checkpoint | A placeholder/sentinel, not an asset identity | Clear to `""` | 4 | 4 |
| `DreamyStyle_xl` | Identity/original role unknown | **Leave unresolved** | 9 | 63 |

**71** occurrence-level actions across **15** distinct PromptPack sources.
**0** replacements were made; no checkpoint/model/VAE selection was ever
touched. **DreamyStyle_xl was deliberately left untouched** — every one of
its 63 occurrences, across 9 sources, survives byte-for-byte semantically
identical (same name, same weight, same position relative to its
neighbors).

## Why no replacement was performed

The owner determined both `BetterThanWords-merged-SDXL-LoRA-v3` and
`babesByStableYogiPony_xlV4` are themselves checkpoint/model identities
that had been mistakenly recorded as separately-applied LoRA references —
not LoRAs with a missing file that should be replaced by a similarly-named
installed LoRA. Removing the erroneous structured entry is therefore the
correct action, not finding a replacement candidate. PR-PACK-120's
same-kind candidate evidence for both names topped out around a ~0.5–0.57
similarity score against installed LoRAs — consistent with "no good LoRA
match exists" rather than "an obvious rename exists," reinforcing that
removal (not replacement) was the right call.

## Why checkpoint/model selection was not changed

This package's policy surface has exactly three actions —
`remove_lora`, `clear_optional_refiner`, and `leave_unresolved` — and no
fourth "replace" action exists anywhere in it (`tools/
pack130_approved_reference_reconciliation.py`'s `_POLICY` mapping is the
entire decision surface). A structured LoRA-list removal or a scalar
refiner-checkpoint clear can never touch `preset_data`'s (or nested
`txt2img`'s) `model`/`model_name`/`sd_model`/`vae` fields — the semantic-diff
guard proves this for every one of the 15 real writes, refusing the whole
batch if any unauthorized key had changed.

## Reconciliation contract

This is a **purpose-built, one-time tool**, not a rebuild of PR-PACK-120's
removed generic apply engine. It recognizes exactly the four
`(asset_kind, missing_reference_name)` keys in the table above; anything
else (an unrecognized name, a non-`promptpack` source, an unmapped item, an
unexpected occurrence shape, more than one refiner-clear target per source,
a refiner value that isn't the exact literal `"None"`) makes the **entire
batch** refuse — no fallback, no fuzzy matching, no partial action.

Before any real write:

- `build_plan` re-validates the fresh triage evidence against the exact
  owner-approved shape (24 items; 3/13, 8/54, 4/4, 9/63 items/occurrences
  per name; 15 actionable sources; 71 total occurrence actions) and
  refuses if the current data has drifted from what the owner reviewed.
- `preflight_check` re-reads every actionable source, confirms its current
  SHA-256 still matches the triage evidence, confirms the exact old value
  is still present at every targeted pointer, and — for every refiner
  clear — confirms the refiner is not explicitly enabled
  (`refiner_enabled`/`use_refiner`, the confirmed production alias
  contract) at that source before permitting the clear.
- Every actionable source is backed up (byte-exact, SHA-verified) before
  the first write, into `C:\Users\rob\AppData\Local\StableNew\Backups\
  PR-PACK-130\<run-id>\promptpack\` — outside PromptPack discovery, never
  committed.
- Immediately before writing, `preflight_check` runs again (TOCTOU
  protection): if any source changed after its backup was taken, the batch
  aborts before writing that source.
- Each source's transformation is applied to an in-memory copy and proven,
  via a full before/after semantic diff, to have changed *only* the
  authorized LoRA-list removal(s) (verified at the structured list level:
  the post-removal list must equal the pre-removal list with exactly the
  approved indexes excluded, applied highest-index-first) and/or the one
  authorized scalar clear — anything else aborts the whole batch.
- Writes are atomic (temp-file + `os.replace`).

**Rollback contract.** Rollback tracks only the sources this process
itself successfully, atomically replaced — never a source that was merely
backed up, loaded, or in the middle of being transformed. A source the
tool never got as far as writing is left exactly as it was found (its own
concurrent edit, if any, is not overwritten, and it is never "restored"
from a backup it didn't need). Before restoring a successfully-replaced
source, rollback re-reads its current bytes and confirms they still equal
the bytes this run itself wrote; if something else has modified that
source in the meantime, rollback refuses to overwrite that newer external
edit, preserves it, and raises `RollbackConflict` (identifying the
affected source, with the triggering failure chained as its cause) rather
than silently claiming a clean rollback. The mutation loop catches
`BaseException`, not just `Exception`, so an operator interruption
(Ctrl-C / `KeyboardInterrupt`) after one or more successful writes still
triggers this same scoped rollback — verifying every restored source's
SHA-256 — before the original `KeyboardInterrupt` is re-raised unmodified.

## Real reconciliation result

Fresh preflight (subphase 1) reproduced the exact owner-reviewed evidence
before any write: 24 `missing_file_backed_asset` findings → 24 triage
items, 16 sources, 20 `lora` + 4 `refiner_checkpoint`, 134 occurrences, 4
placeholders, 0 unmapped — and specifically 3/13 `BetterThanWords...`, 8/54
`babesByStableYogiPony_xlV4`, 9/63 `DreamyStyle_xl`, 4/4 literal `"None"`.
All four `"None"` refiner sources had neither `refiner_enabled` nor
`use_refiner` present anywhere — refiner disabled by the production
default, safe to clear.

A dry run reproduced the plan (15 sources, 67 LoRA removals, 4 refiner
clears, 71 total actions) with zero source-byte changes. The real
reconciliation then executed exactly that plan:

- **15** PromptPack files changed, all 15 backed up and SHA-verified first.
- **67** structured LoRA entries removed (13 `BetterThanWords...` + 54
  `babesByStableYogiPony_xlV4`).
- **4** literal `"None"` refiner-checkpoint values cleared to `""`.
- Every surviving LoRA entry (including all 63 `DreamyStyle_xl`
  occurrences) verified to retain its exact name, weight, and relative
  ordering — spot-checked directly, e.g. `Beautiful_people_fullbody_
  Variant`'s slot 1 LoRA list went from `[add-detail-xl, CinematicStyle_v1,
  DetailedEyes_V3, babesByStableYogiPony_xlV4, DreamyStyle_xl]` to exactly
  `[add-detail-xl, CinematicStyle_v1, DetailedEyes_V3, DreamyStyle_xl]`,
  with `DreamyStyle_xl`'s weight unchanged at `0.75`.
- Every sibling refiner field (e.g. `refiner_switch_at`) unchanged.
- **45** other real files (all remaining PromptPacks + all standalone
  presets) confirmed byte-identical before/after via a full 60-file
  fingerprint.

Post-write verification:

- A fresh WP-PACK-AUDIT-100 census: `missing_file_backed_asset` **24 → 9**;
  overall census total **1,010 → 995**. Every other finding category
  unaffected.
- A fresh PR-PACK-120 triage against that fresh census: **9** items, **9**
  sources, **63** occurrences, **0** unmapped — and the missing-reference
  identity set is *exactly* `{DreamyStyle_xl}`. No new missing name
  appeared; no `BetterThanWords...`, `babesByStableYogiPony_xlV4`, or
  `"None"` placeholder remains.

## `DreamyStyle_xl` remains intentionally unresolved

All 9 `DreamyStyle_xl` triage items and 63 occurrences survive this
package completely untouched. Its identity and original role are unknown
(possibly a removed historical LoRA, possibly something else) — no
automatic replacement, removal, or weight change is authorized for it.
Resolving it remains an open owner decision for a future, separately
authorized package.

## Explicit non-scope

No replacement of either removed LoRA reference with a checkpoint. No
checkpoint/model/VAE selection change. No model download, asset
move/rename, or CivitAI/network lookup. No inference or action of any kind
on `DreamyStyle_xl`. No clearing of any non-`"None"` refiner value. No edit
to any standalone preset or legacy text pack (this package's actionable
scope is `source_type=promptpack` canonical JSON only). No generic
mutation engine (PR-PACK-120's removed apply engine was not rebuilt; this
tool recognizes only the four fixed policy keys above). No PR-PACK-120
scan-behavior change. No image generation, A1111/Comfy process, or GPU
use.

## Tests

`tests/tools/test_pack130_approved_reference_reconciliation.py` (41 tests,
no real PromptPack used as a fixture) covers: exact removal of both
approved LoRA names; unrelated LoRA and weight survival; the real-world
`DreamyStyle_xl`-beside-`babesByStableYogiPony_xlV4` overlap pattern;
first/middle/multi-slot/multi-occurrence removal with highest-index-first
ordering; refusal for any unrecognized name, non-`promptpack` source type,
unmapped item, or non-literal refiner value; the refiner-enabled safety
stop; that `DreamyStyle_xl` is recognized as leave-only and that no
`replace` action exists anywhere in the policy surface; that one source
with multiple occurrences is grouped once, never duplicated; stale-SHA and
missing-old-value preflight refusals; a simulated concurrent edit between
backup and write causing refusal without touching either file (TOCTOU);
backup-hash-mismatch causing zero writes; a simulated mid-write failure
rolling back all prior sources to byte-identical originals; the
semantic-diff guard catching both a prompt-text tamper and an unrelated
setting tamper; unknown extension fields surviving; dry-run performing
zero writes; a successful apply changing only the approved fields; a
re-run against an already-reconciled fixture refusing safely; a full
owner-approved-shape integration test (24 items, exact 3/13/8/54/4/4/9/63
breakdown, 15 actionable sources, 71 actions) through `build_plan` →
`preflight_check` → dry-run → real apply, plus that same shape refusing
outright if any count drifts; and the rollback-scoping contract above: a
three-source scenario where a concurrent edit lands on an as-yet-unwritten
source and that source retains the edit exactly (never restored merely
because it was backed up) while an already-written sibling is rolled back
byte-exact; a failure before any successful write restoring nothing; a
`KeyboardInterrupt` after one successful write rolling that one write back
and re-raising the original interrupt unmodified; and a second,
independent edit landing on an already-written source before rollback can
run, which `RollbackConflict` (chaining the triggering failure) reports
rather than silently overwriting.

## Controller Surface Assessment

Not applicable / no controller changes.
