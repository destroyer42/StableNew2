# PR-ASSET-120 — Provenance-Rich Asset Metadata Enrichment and Compatibility Profiles

Status: implemented; offline/observational only, no recommendation or
network-enrichment behavior.

## Outcome

`src.assets.AssetRegistry` now enriches its existing local-file identity
records with local sidecar metadata and a conservative model-family
compatibility profile, while preserving the distinction between content
identity (SHA-256) and location-specific evidence.

This package answers only: *"what model-family evidence does this local
asset contain, and where did that evidence come from?"* It does not answer
*"should the user use this asset?"* — no recommendation, ranking, warning, or
enforcement behavior was added. `WebUIResourceService` remains the separate
read-only projection of what a running A1111 currently exposes; the two
authorities are not merged.

## What changed

- `AssetLocation` now carries location-scoped sidecar evidence: `sidecar_path`,
  `sidecar_metadata`, `sidecar_provenance`, `sidecar_error`. Sidecars enrich
  one file location, never the shared content identity, so identical bytes
  at two locations with disagreeing sidecars are preserved as two distinct
  locations rather than collapsed.
- `AssetRecord` now exposes `embedded_metadata_error` (previously computed
  but dropped before reaching the public snapshot) and a `compatibility:
  CompatibilityProfile` field.
- New `src.assets.compatibility` module: `ModelFamily` (`sd1`, `sd2`, `sdxl`,
  `sd3`, `flux`), `EvidenceConfidence` (`metadata`, `filename_hint`),
  `CompatibilityStatus` (`resolved`, `unknown`, `conflicting`),
  `FamilyEvidence`, and `CompatibilityProfile`.

## Sidecar convention

Local CivitAI-style sidecars use the same deterministic candidate precedence
already established by `tools/asset_census.py`: `<file>.<ext>.civitai.info`
checked before `<file-without-extension>.civitai.info`. Sidecars are local,
optional, JSON-only, never fetched from a network, and never required for an
asset to exist. A malformed or unreadable sidecar records `sidecar_error` and
never fails refresh.

## Family resolution

Evidence is gathered from three sources, and no supported field within a
source silently suppresses another:

1. **Embedded metadata** (content-level): every one of `ss_base_model_version`,
   `modelspec.architecture`, `modelspec.base_model_version` that is present
   and recognized contributes its own evidence record — not just the first
   one found.
2. **Sidecar metadata** (location-level): every one of `baseModel`,
   `base_model` that is present and recognized contributes its own evidence
   record, for the same reason.
3. **Filename** (location-level, weakest tier): consulted only when no
   embedded or sidecar evidence exists at all.

All three sources are matched against the same conservative, explicit token
set: kohya-style underscore versions (`sdxl`, `sd_xl`, `sd_v1`/`sd_v2`/`sd_v3`),
CivitAI-style space-separated labels (`sd xl`, `sd 1`/`sd 2`/`sd 3`), and
canonical ModelSpec architecture strings (`stable-diffusion-xl`,
`stable-diffusion-v1`/`v2`/`v3`), plus the bare `flux`/`sd1`/`sd2`/`sd3`/`sdxl`
tokens. A generic `"xl"` substring never implies SDXL, and a derivative
label such as `"Pony"` or `"Illustrious"` is never silently mapped onto
SDXL — it stays unrecognized unless an explicit token is actually present.

Embedded and sidecar evidence are peers: if any two recognized fields —
whether both embedded, both sidecar, or one of each — name different
families, the profile is `conflicting`, not a first-field-wins or
first-source-wins pick. The same rule applies across duplicate-content
locations with disagreeing sidecars. Unknown/unrecognized metadata is a
valid, expected `unknown`
result — conservative incomplete coverage over unsupported inference. All
evidence gathered is preserved on the profile even when it did not
ultimately decide the resolved family.

## Cache evolution

The on-disk cache moved from version 1 to version 2. A model file's SHA-256
and header metadata are reused unchanged whenever its recorded size/mtime
still match, exactly as before. Sidecar freshness is tracked independently
of model-byte freshness via a `size`/`mtime_ns` sidecar fingerprint, so a
changed or removed sidecar updates the projected metadata/profile on the
next refresh without forcing a model rehash, and vice versa. Existing
version-1 cache entries are accepted and upgraded lazily on first refresh
after this change; they are never discarded or forced to rehash merely
because the schema changed. A corrupt or unsupported-version cache still
recovers safely by starting from empty entries.

## Compatibility and lifecycle

`LoRAScanner` and `EmbeddingScanner` remain thin compatibility projections
over the registry; they consume only `AssetLocation.kind`/`display_name`/
`path`/`byte_size` and required no changes.

## Explicitly out of scope

No recommendation/"best model" logic, no automatic model/VAE/LoRA/embedding
selection, no compatibility-warning UI, no PromptPack audit, no live A1111
resource joining, no network/CivitAI calls, no model downloads, no GPU/model
loading, and no NJR/compiler/executor/backend-selection/controller change.

## Execution profile and validation

- Execution class: Standard, Local/Desktop.
- Controller surface assessment: not applicable; no controller/coordinator
  changed.
- Token-efficient validation: focused fixture tests over temporary roots
  cover embedded-only, sidecar-only, agreeing, and conflicting evidence;
  malformed-sidecar recovery; duplicate-content locations with distinct and
  conflicting sidecars; sidecar change/removal without rehashing; a
  version-1 cache upgrade path; existing hash-invalidation behavior; and
  the legacy `LoRAScanner`/`EmbeddingScanner` projections. No real user
  library, network access, or GPU/model work is required.

Next candidate consumer: `WP-PACK-AUDIT-100 — PromptPack & Saved-Settings
Quality Census`, whose compatibility checks may consume these profiles under
a separately defined acceptance contract.
