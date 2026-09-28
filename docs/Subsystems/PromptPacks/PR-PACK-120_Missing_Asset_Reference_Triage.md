# PR-PACK-120 — Missing Asset Reference Triage & Explicit Reconciliation Workflow

Status: implemented; offline, read-only. This package performs no automatic
source mutation and makes no reconciliation decision for the owner.

## Outcome

New `tools/missing_asset_reference_triage.py` turns WP-PACK-AUDIT-100's
aggregated `missing_file_backed_asset` findings into precise, inspectable,
safely actionable reconciliation evidence:

1. **`scan`** re-opens each source read-only and maps the aggregated finding
   back to every exact raw persisted JSON occurrence that actually carries
   the missing value — never the census finding itself, which is
   intentionally aggregated across slots and cannot serve as a write
   locator.
2. For each finding it attaches deterministic, same-asset-kind-only
   candidate evidence from `AssetRegistry`, Asset-120 `CompatibilityProfile`
   context, and a narrow literal-placeholder classification (`"None"`,
   `"(None)"`, `"null"`).
3. It emits a decision template defaulting every item to
   `leave_unresolved` — no candidate ever becomes a decision automatically.
4. **`apply`** (dry-run by default; real writes require an explicit
   `--apply` flag) validates an operator-approved decisions file
   all-or-nothing before touching any file, backs up every file it will
   touch first, applies changes atomically per file, and restores every
   file in the batch from backup on any failure.

`apply` was implemented and tested against disposable fixtures only. **It
was never invoked against real user data in this package.**

## Why the census finding cannot be a write locator

`tools/promptpack_quality_census.py` aggregates LoRA/embedding references
across every slot in a PromptPack before resolving them against the Asset
Registry — one finding can correspond to many raw occurrences, or the
effective checkpoint/VAE/refiner value can come from any of several
accepted top-level or nested aliases. The triage `scan` step therefore
always re-opens the raw source and re-derives occurrences directly, rather
than trusting the finding's own aggregated identity as a location.

## Occurrence mapping

- **Checkpoint** (`model`/`model_name`/`sd_model`), **VAE**
  (`vae`/`vae_name`/`sd_vae`), and **refiner**
  (`refiner_model_name`/`refiner_checkpoint`): every accepted alias is
  checked at both the top level of `preset_data` (or a standalone preset's
  own top level) and nested under `txt2img`, and every location that
  actually holds the exact missing value is recorded — never every alias
  merely because one resolved.
- **LoRA**: `pack_data.slots[i].loras[j][0]`, preserving slot index, entry
  index, and the untouched weight at `[j][1]`.
- **Embedding**: `pack_data.slots[i].positive_embeddings[j]` /
  `negative_embeddings[j]`, supporting all three currently-normalized entry
  shapes (bare string, `{"name","weight"}`, `[name, weight]`) without
  re-serializing the entry during scan.
- A finding whose value cannot be found verbatim in the raw document is
  recorded as an explicit **unmapped/stale** item — the tool never guesses
  a location.

## Candidate evidence

Same-asset-kind-only, using `AssetRegistry`'s installed display names
(`normalize_model_name()`-normalized, the same harmless-variation
normalizer the census already uses) and stdlib
`difflib.SequenceMatcher.ratio()` — a documented, deterministic, reproducible
similarity method, never a network/fuzzy-download lookup. Ordering is
deterministic (descending score, then alphabetical), capped at 5 candidates
per item. Each candidate carries its own Asset-120 `resolved_family`/
`resolved_status` for context. Candidates are called exactly that —
`candidate evidence` — never "correct"/"best"/"recommended"; nothing in this
tool converts a similarity score into permission to act.

## Decision schema and safety contract

```json
{
  "schema_version": 1,
  "generated_from": {"source_sha": "...", "triage_report_sha256": "..."},
  "decisions": [
    {
      "triage_item_id": "...",
      "occurrence_ids": ["..."],
      "action": "leave_unresolved",
      "replacement": null,
      "expected_old_value": "...",
      "expected_source_sha256": "..."
    }
  ]
}
```

Supported actions: `leave_unresolved` (the template default), `replace_reference`,
`remove_reference` (structured LoRA/embedding entries only), and
`clear_optional_reference` (only fields in an explicit optional-field
allowlist — a required base checkpoint can never be cleared this way).

Before any real write: every decision in the batch is validated —
source file still exists, its SHA-256 still matches the decision's
`expected_source_sha256`, the expected old value is still present at every
targeted occurrence, and (for `replace_reference`) the proposed replacement
resolves to exactly one installed asset of the same kind. One invalid
decision refuses the entire batch — no partial writes. All backups for a
batch complete before the first write. Each write is atomic
(temp-file-then-`os.replace`); a semantic-diff guard compares the full
document before/after and refuses any change outside the explicitly
authorized occurrence(s); any failure restores every file already changed
in that operation from its byte-exact backup and re-verifies the restored
SHA-256.

## Real read-only triage result

Run against source SHA `2b90e2e52c0e7b37693816accf8ecca352872a44` (current
census total: 1,010 findings; unchanged since `PR-PACK-110`):

- **24** `missing_file_backed_asset` findings -> **24** triage items (no
  collapse in this run) across **16** distinct PromptPack sources — all 24
  are `source_type=promptpack`; zero are standalone-preset findings.
- By asset kind: **20** `lora`, **4** `refiner_checkpoint`.
- **4** unique missing reference names: `BetterThanWords-merged-SDXL-LoRA-v3`,
  `DreamyStyle_xl`, `babesByStableYogiPony_xlV4`, and the literal placeholder
  string `"None"`.
- **134** exact raw occurrences after re-mapping (many packs reference the
  same missing LoRA across several slots — one source alone accounts for 10
  occurrences of a single missing name).
- **4** placeholder-literal items (all four `refiner_checkpoint` findings —
  the persisted value is the literal text `"None"`, not an actual filename).
- **0** unmapped/stale items — every finding's value was found verbatim in
  its raw source.
- Candidate evidence: every one of the 24 items has same-kind candidates
  (capped at 5); none scored highly enough to look like an obvious rename —
  the strongest same-kind similarity seen was ~0.57, consistent with these
  being genuinely absent assets rather than simple renames.
- Base-checkpoint family context: all 24 items' base checkpoint resolves to
  Asset-120 `unknown` (the checkpoint asset itself carries no embedded or
  sidecar metadata establishing a family) — `family_unknown` is exactly what
  `WP-PACK-AUDIT-100`'s own independent resolution already reported for
  these same sources, confirming this triage's context matches the accepted
  census.
- Source-mutation verification: a full 59-file fingerprint (all PromptPacks
  + all standalone presets + `.default_preset`) was captured before and
  after the run and confirmed byte-identical throughout.

## Explicit non-scope

No automatic replacement, no automatic clearing of the `"None"` placeholder,
no model download, no CivitAI/network lookup, no asset rename/move/delete,
no Asset Registry or compatibility-taxonomy change, no repair of
`family_unknown`/`family_evidence_conflicting`, no naming-hygiene cleanup, no
PromptPack prompt/matrix change, no ADetailer stage-sync touch, no GUI/warning
UX, no recommendation engine. The three existing `resolved_duplicate_bytes`
findings and the four deferred census-tool robustness items from
`WP-PACK-AUDIT-100` remain untouched.

## Tests

`tests/tools/test_missing_asset_reference_triage.py` covers census-finding
filtering (excluding `resolved_duplicate_bytes`/`ambiguous_same_name`),
checkpoint/VAE/refiner occurrence mapping at both nested and accepted
top-level aliases, LoRA occurrence with weight preservation, positive/negative
embedding occurrences, multi-slot multi-occurrence mapping, unmapped/stale
recording (never guessing), placeholder classification (including that an
ordinary unusual filename is never misclassified), same-kind-only
deterministic candidate evidence with attached family context, the
decision template's non-mutating default, every replacement guard
(nonexistent/ambiguous/wrong-kind candidate), source-SHA and expected-old-value
staleness guards, the base-checkpoint clear rejection, dry-run mutation scope
for replace/remove/clear, all-or-nothing batch validation, a simulated backup
failure and a simulated mid-write failure both resulting in zero/rolled-back
writes, a semantic-diff guard catching an unauthorized change, scan's
zero-mutation guarantee, absence of any network/runtime import, and
deterministic output for unchanged inputs. All fixtures use temporary roots;
no real user PromptPack is used as a test fixture.

## Controller Surface Assessment

Not applicable / no controller changes.
