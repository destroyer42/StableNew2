# PR-ASSET-120 â€” Provenance-Rich Asset Metadata and Compatibility Profiles

Status: implemented; offline and observational only.

## Boundary

`AssetRegistry` remains the sole local-file identity and discovery authority:
SHA-256 identifies bytes and paths are only locations. `AssetMetadataService`
is a read-only projection over those identities. It adds no asset identity
database, network access, background polling, GUI/controller wiring, queue
state, NJR field, or generation policy.

The layer is intentionally ordered:

`asset identity -> factual metadata/enrichment -> compatibility profile -> future policy`

It does not select a checkpoint/VAE, alter prompt construction, weights,
sampler settings, embeddings, or any other generation behavior.

## Typed facts and provenance

Each normalized value has a `MetadataValue` and `MetadataProvenance`. Sources
are explicit embedded file metadata, exact-hash sidecar/cache metadata,
creator-local documentation, deterministic technical inference, or unknown.
Evidence strength is discrete: explicit, strong inference, weak inference, or
unknown. Unknown family and activation requirement are explicit typed states,
not creator claims.

The deterministic factual precedence is embedded metadata, exact-hash
sidecar/cache, creator-local documentation, technical inference, then unknown.
Disagreeing lower-precedence values remain in `MetadataConflict`; they are not
silently overwritten.

Safetensors inspection reads only bounded headers. The raw embedded metadata is
retained for diagnostics, while the product-facing projection is limited to
recognized family/architecture, adapter, creator/model/version, source URL,
activation, examples, and explicitly supplied weight guidance fields.

## Compatibility and local evidence

`CompatibilityProfile` describes factual asset kind, model family, optional
ecosystem subfamily, adapter type, embedding dimension/text-encoder evidence,
and known family incompatibilities. APIs return only `compatible`,
`incompatible`, or `unknown`; they never recommend an asset. Pony evidence is
represented as the `pony` ecosystem subfamily while retaining SDXL technical
family compatibility.

Embedding inference uses safetensors tensor structure only: `clip_l` plus
`clip_g` is strong SDXL dual-encoder evidence; one 768-dimensional embedding
is strong SD1.x-style evidence; unsupported structure remains unknown. Filenames
never establish family.

Adjacent `.civitai.info` files are joined to the already identified local asset
and remain below embedded metadata. Adjacent TXT/README parsing accepts only
explicit labels for activation words, prompts, activation requirements, and
weight guidance. Quoted README words are not treated as activation tokens.

The optional `lora-keywords-finder` adapter reads supplied local `known` or
`metadata_cache` roots only. SHA-named JSON records join solely by exact
registry SHA; the extension is never required or imported. Empty records mean
unknown/no cached keywords, never no trigger requirement.

## Refresh and query API

The service keeps a bounded in-memory derivative cache keyed by registry SHA
plus local sidecar/document/cache fingerprints. Changing local enrichment
sources refreshes the projection without forcing a model-byte rehash; a changed
SHA gets a distinct projection. Public read-only queries include metadata,
profiles, field provenance, activation facts, conflicts, unknown-family assets,
and asset/family compatibility.

## Execution profile and validation

- Execution class: Standard, Local/Desktop. Model recommendation: GPT-5.6
  Terra High, justified by provenance precedence and compatibility semantics.
- Controller surface assessment: no controller/coordinator changed or grew.
- Token-efficient validation: deterministic temporary fixtures prove precedence,
  conflicts, exact-SHA cache joins, sidecar refresh, malformed local sources,
  embedding structure, and existing scanner compatibility. Real-library
  acceptance is read-only and reuses registry hash-cache behavior.

Known unknowns remain factual: unsupported embedding structure, absent local
metadata, and non-explicit activation requirement are `unknown`; no network is
used to fill them.

Next package after acceptance: `PR-ASSET-130 â€” Evidence-Based Asset
Recommendation Policy and Checkpoint-Aware Defaults`.
