# PR-ASSET-110 — Unified Local Asset Registry Identity Boundary

Status: implemented; no recommendation or network-enrichment behavior.

## Boundary

`src.assets.AssetRegistry` is StableNew's sole local-file identity and discovery
authority. It discovers supported A1111-compatible paths offline, streams
SHA-256, safely reads safetensors headers only, groups duplicate paths by
content identity, and persists its optimization cache at
`state/asset_registry_v1.json`. Filename and path are aliases, never identity.

The registry does not contact A1111, mutate an NJR, manage processes, queue
work, make recommendations, or persist live availability. `WebUIResourceService`
remains the separate read-only answer to what a running A1111 exposes.

The active embedding root is `<webui_root>/embeddings`; legacy
`<webui_root>/models/embeddings` is deliberately excluded. Supported defaults
cover checkpoints, VAE/approximate VAE, LoRA/LyCORIS, embeddings, ESRGAN and
RealESRGAN upscalers, GFPGAN/CodeFormer restoration, ControlNet, BLIP, and the
configured ADetailer root.

## Compatibility and lifecycle

`LoRAScanner` and `EmbeddingScanner` are now thin compatibility projections
over the registry. They retain picker-facing APIs and manual refresh behavior
but have no filesystem scan or independent JSON cache. Their named removal
condition is direct registry consumption by their remaining callers. Existing
`data/lora_cache.json` and `data/embedding_cache.json` are neither read nor
written.

Refresh validates normalized path, size, high-resolution modification time,
and kind before reusing a cached hash. Any mismatch, missing cache, or corrupt
cache recomputes streamed SHA-256 safely. A registry snapshot can therefore
contain locally installed bytes even when A1111 currently skips them.

## Execution profile and validation

- Execution class: Standard, Local/Desktop. Model recommendation: GPT-5.6
  Terra High; it minimizes retry risk across persistent identity and UI
  compatibility boundaries.
- Controller surface assessment: no controller changed or grew.
- Token-efficient validation: temporary fixtures cover SHA identity, duplicate
  paths, active embedding authority, hash-cache reuse/invalidation, corrupt
  cache recovery, and legacy projections without legacy cache writes.

Next package: `PR-ASSET-120 — Provenance-Rich Asset Metadata Enrichment and
Compatibility Profiles`; it must remain offline/observational until separately
authorized to add any recommendation behavior.
