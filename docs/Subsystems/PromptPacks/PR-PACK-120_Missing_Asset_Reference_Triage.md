# PR-PACK-120 — Missing Asset Reference Triage & Reconciliation-Decision Preparation

Status: implemented; offline, read-only operator triage and
reconciliation-decision preparation. This package performs no automatic
source mutation and makes no reconciliation decision for the owner. Actual
reconciliation (executing a replacement/removal/clear decision against a
real PromptPack or preset) is explicitly deferred to a later, separately
authorized package, once the owner has reviewed the 24-item decision set
below.

## Outcome

`tools/missing_asset_reference_triage.py` turns WP-PACK-AUDIT-100's
aggregated `missing_file_backed_asset` findings into precise, inspectable
reconciliation-decision evidence:

1. **`scan`** re-opens each source read-only and maps the aggregated finding
   back to every exact raw persisted JSON occurrence that actually carries
   the missing value — never the census finding itself, which is
   intentionally aggregated across slots and cannot serve as a write
   locator.
2. For each finding it attaches deterministic, same-asset-kind-only
   candidate evidence from `AssetRegistry`, Asset-120 `CompatibilityProfile`
   context, and a narrow literal-placeholder classification (`"None"`,
   `"(None)"`, `"null"`).
3. It emits a `decisions.template.json` defaulting every item to
   `leave_unresolved` — no candidate ever becomes a decision automatically,
   and generating the template implies no authorization to act.
4. `validate_decision`/`validate_batch` check only static, read-only
   properties of an operator-filled-in decisions file — that the triage
   item/occurrence still exists, the action is a known one, a proposed
   replacement resolves to exactly one installed same-kind asset, and the
   source fingerprint/expected old value are still current — so an operator
   can sanity-check a draft decision. They never write, back up, or
   transform a source file.

There is no code path in this module that writes to a PromptPack or preset
source. Its only filesystem writes are its own explicit output artifacts
(the triage report, its markdown summary, the decisions template) and an
audit-owned Asset Registry cache — never the application's normal
production cache. An earlier revision of this package carried a generic
apply/backup/rollback mutation engine; it was removed before merge (see
"Deferred: reconciliation execution" below) once review surfaced remaining
edge cases in that engine that had no bearing on the accepted read-only
scan evidence. The smallest coherent package is read-only triage; a
mutation engine is unnecessary risk before the owner has selected any
actual decisions.

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
- A finding whose value cannot be found verbatim in the raw document, or
  whose source file is missing/corrupt/valid-JSON-but-not-an-object, is
  recorded as an explicit **unmapped/stale** item — the tool never guesses
  a location, and scanning continues with the remaining sources rather than
  crashing on the first unexpected shape.

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

## Decision-template schema

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

Action vocabulary: `leave_unresolved` (the template default, and the only
action this package can produce unattended), `replace_reference`,
`remove_reference` (structured LoRA/embedding entries only), and
`clear_optional_reference` (only fields in an explicit optional-field
allowlist — a required base checkpoint could never be cleared this way).
**PR-PACK-120 does not execute any of these actions.** They represent
proposed owner decisions for a later, separately authorized reconciliation
package; a generated template with a non-`leave_unresolved` action implies
no authorization to act on it.

`validate_decision` checks, read-only: the triage item and every referenced
occurrence still exist; for any action other than `leave_unresolved`,
`expected_source_sha256` is present, a non-empty string, and equal to the
source file's *current* SHA-256 (missing/`null`/blank/stale all reject);
the expected old value is still present at every targeted occurrence; for
`replace_reference`, the proposed replacement resolves to exactly one
installed asset of the same kind; for `clear_optional_reference`, the
targeted field is in the optional-clearable allowlist. `validate_batch`
runs this over every decision in a file and returns one result per
decision. Neither function opens a source file for anything but reading,
and neither ever writes, backs up, or transforms one.

`scan`'s `--asset-cache` is optional; when `--webui-root` is given without
it, an audit-owned cache path is derived beside the requested output
(`<out-dir>/asset_registry_triage_cache.json`) rather than falling back to
`AssetRegistry`'s own default, which is StableNew's normal production Asset
Registry cache. This preserves the audit-isolation guarantee: the triage
workflow never reads from or writes to the cache the running application
itself uses.

## Deferred: reconciliation execution

An earlier revision of this tool included a generic `apply` command
(fingerprint-guarded, all-or-nothing, atomic-write, backup/rollback
mutation engine for the four actions above) and was validated against
disposable test fixtures only — it was never invoked against real
PromptPack/preset data. A second review pass identified four further
credible issues in that engine (decisions-file triage-report fingerprint
not enforced; certain complex interleaved-removal orderings could still
target a shifted index; dry-run did not exercise the exact same
transformation/semantic-diff path as a real write; source SHA was not
rechecked immediately before backup/write, leaving a TOCTOU window). None
of these affected the read-only scan evidence itself. Rather than carry
that risk inside PR-PACK-120 before any actual reconciliation decision has
been made, the owner scoped this package down to read-only triage: the
mutation engine, its tests, and its CLI `apply` subcommand were removed in
full. A future, separately authorized reconciliation package will
revalidate the operator's selected decisions against the sources' then-current
state before executing anything — it does not need to inherit today's
draft engine, since no real data has ever been written by it.

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
- Source-mutation verification: a full 60-file fingerprint (all PromptPacks
  + all standalone presets) was captured before and after the final
  scope-reduction rerun and confirmed byte-identical throughout,
  reproducing the same 24/24/16/20/4/134/4/0 counts above.

## Explicit non-scope

No automatic replacement, no automatic clearing of the `"None"` placeholder,
no model download, no CivitAI/network lookup, no asset rename/move/delete,
no Asset Registry or compatibility-taxonomy change, no repair of
`family_unknown`/`family_evidence_conflicting`, no naming-hygiene cleanup, no
PromptPack prompt/matrix change, no ADetailer stage-sync touch, no GUI/warning
UX, no recommendation engine, **no reconciliation execution of any kind**
(see "Deferred" above). The three existing `resolved_duplicate_bytes`
findings and the four deferred census-tool robustness items from
`WP-PACK-AUDIT-100` remain untouched.

## Tests

`tests/tools/test_missing_asset_reference_triage.py` covers census-finding
filtering (excluding `resolved_duplicate_bytes`/`ambiguous_same_name`),
checkpoint/VAE/refiner occurrence mapping at both nested and accepted
top-level aliases, LoRA occurrence with weight preservation, positive/negative
embedding occurrences, multi-slot multi-occurrence mapping, unmapped/stale
recording for an unfindable value, a missing source, and a source whose
top-level JSON decodes but is not an object (proving a co-scanned valid
source is unaffected), placeholder classification (including that an
ordinary unusual filename is never misclassified), same-kind-only
deterministic candidate evidence with attached family context, the
decision template's non-mutating default and its source-fingerprint/old-value
evidence, every read-only validation guard (nonexistent/ambiguous/wrong-kind
replacement candidate, source-SHA and expected-old-value staleness including
a missing/`null`/blank/wrong/correct fingerprint, the base-checkpoint clear
rejection, an optional-scalar clear passing validation, batch validation
returning one result per decision), `scan` deriving an audit-owned Asset
Registry cache instead of the production default, scan's zero-mutation
guarantee, absence of any network/runtime import, that the module and its
CLI expose no source-write pathway (no `apply` subcommand, no mutation
functions), and deterministic output for unchanged inputs. All fixtures use
temporary roots; no real user PromptPack is used as a test fixture.

## Controller Surface Assessment

Not applicable / no controller changes.
