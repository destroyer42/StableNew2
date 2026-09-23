# PR-ASSET-DISCOVERY-100 — Local A1111 Asset Census and Source-Root Authority

Status: complete evidence/tooling package. This is not an Asset Registry or a
dynamic recommendation implementation.

## Outcome

This package establishes a repeatable, offline way to identify installed local
asset bytes and records the observed A1111 root topology. It preserves the
existing distinction between:

- local-file identity and metadata; and
- the resource names and loaded state exposed by a running A1111 instance.

The canonical execution path is unchanged:

`Intent -> Compiler -> immutable NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

Asset discovery is pre-compilation factual context only. It does not mutate an
existing NJR, submit work, call a model loader, or create a queue, history,
compiler, runner, or live resource authority.

## Execution profile

- Class: Standard; Local/Desktop.
- Model/reasoning recommendation: GPT-5.6 Terra — High. Local access is
  required for the A1111 configuration, installed files, extension cache, and
  live read-only API snapshot. This is the lowest effective profile because
  careful evidence joining and safe metadata parsing avoid expensive retries.
- Controller surface assessment: not applicable. No controller/coordinator
  code changed; `src/controller/app_controller.py` was preserved as unrelated
  local user work.
- Token-efficient validation plan: fixture tests exercise the parser and
  deterministic output once; the complete local byte census reuses the
  persisted hash cache on subsequent runs. No GPU, A1111 launch, model load,
  network request, or real-library fixture is required by tests.

## Reusable offline tool

`tools/asset_census.py` accepts repeatable explicit `--root KIND=PATH`
arguments and emits deterministic JSON. It is deliberately an operator tool,
not a production scanner or registry. It:

- considers common model-file extensions only;
- streams SHA-256 in 1 MiB chunks and persists a size/mtime-validated local
  hash cache;
- reads only the safetensors header and its `__metadata__` object, never
  tensors or GPU/ML libraries;
- records sidecar metadata when present, conservative family hints, and
  exact-byte duplicate or same-name/different-hash relationships;
- can ingest `lora-keywords-finder` cache records only when explicitly passed;
  and
- has no network code or A1111 process/API interaction.

Machine-local output belongs under ignored `data/asset_census/`; no catalog,
absolute local paths, hashes, or third-party metadata is committed.

## Observed source-root authority

The local A1111 command line had no model-root override arguments. Its source
default for `--embeddings-dir` is the root-level `embeddings/` directory, and
the running API's `/sdapi/v1/embeddings` response corroborated that root.

| Category | A1111/configured discovery roots | Local census result |
|---|---|---|
| Checkpoints | `models/Stable-diffusion` | 45 file-backed checkpoints; API exposed 45. |
| VAEs / approximate VAEs | `models/VAE`, `models/VAE-approx` | 10 VAEs (also 10 API-visible) and 2 approximate VAEs. |
| LoRAs / LyCORIS | `models/LoRA`, `models/LyCORIS` | 46 LoRAs; the LyCORIS root was absent. |
| Textual inversions | `embeddings/` | 16 file-backed embeddings; 15 loaded and 1 skipped by the live API. |
| Upscalers / restorers | `models/ESRGAN`, `models/RealESRGAN`, `models/GFPGAN`, `models/Codeformer` | 2 ESRGAN, 2 RealESRGAN, 3 GFPGAN, and 1 CodeFormer file-backed assets. |
| Other local model groups | `models/ControlNet`, `models/BLIP` | 3 ControlNet and 1 BLIP asset. |
| ADetailer | `models/adetailer` plus the installed Hugging Face cache used by ADetailer | configured ADetailer root was empty; six cached detector bytes were found. Four additional API-visible MediaPipe entries are runtime capabilities, not standalone model files. |

Runtime-enumerated capabilities were captured separately from file bytes:
45 checkpoint names, 10 VAE names, 20 samplers, 12 schedulers, 14 upscalers,
2 face restorers, and 10 ADetailer choices. The latter includes the six cached
detector files plus four MediaPipe capabilities. Runtime counts are a snapshot,
not a claim that the local byte census owns the live A1111 projection.

## Embedding-root conclusion

**`embeddings/` is authoritative. `models/embeddings/` is legacy/inactive.**

Evidence:

1. No configured command-line override selects `models/embeddings/`.
2. A1111's textual-inversion code registers `cmd_opts.embeddings_dir`, whose
   default is root-level `embeddings/`.
3. The live A1111 API exposed 15 loaded names and one skipped name from that
   root.
4. `models/embeddings/` contains five exact duplicate files and one unique
   legacy `.pt` file; none of its unique content appeared in the live API.
5. StableNew's `EmbeddingScanner` and `WebUIResourceService.list_embeddings`
   already scan root-level `embeddings/`.

No production root correction is needed. There is a bounded future gap:
StableNew's filesystem projection includes the root-level file that A1111
reported as skipped, because it does not consume A1111's embeddings endpoint.
That is not a discovery-root mismatch. A future Asset Registry should retain
local-byte availability separately from a live A1111 loaded/skipped projection.

## Metadata and enrichment findings

The safe parser found embedded safetensors metadata on 16 checkpoints, 41
LoRAs, 3 VAEs, and 2 embeddings. The remaining formats are represented by
path, size, timestamp, extension, and streamed SHA-256; this package does not
deserialize pickle/checkpoint payloads.

The installed `lora-keywords-finder` revision has legacy `known/<sha>.json`
files only; it has no `metadata_cache/` directory. All 14 recognized cache
records are plain keyword-list evidence, and 13 join exactly to installed LoRA
bytes. They are optional historical enrichment only. The tool can also retain
future rich-object cache records, but StableNew neither imports the extension
nor calls CivitAI.

The local census found seven exact-byte duplicate groups: five are the
root/legacy embedding copies; one is a duplicate VAE under different names;
and one is an upscale model present in both ESRGAN directories. It found no
same-display-name/different-hash group in the scoped model-file inventory.
No files were moved, renamed, deleted, or deduplicated.

## Future Asset Registry ingestion boundary

The future registry should be one local-file identity service, fed by explicit
configured roots and recording immutable-ish file facts (path, root, size,
mtime, streamed SHA-256, safe header/sidecar metadata, duplicate relation,
and provenance). It should project optional enrichment such as CivitAI cache
data with its source and freshness rather than treating it as canonical.

It must consume the existing live A1111 resource projection as a separate
read-only observation: e.g., visible model name, loaded/skipped embedding
state, samplers, schedulers, upscalers, and ADetailer choices. It must not make
the extension, CivitAI, or a new filesystem scanner into a second production
authority.

Proposed later schema additions are `asset_kind`, `local_path`,
`discovery_root`, `byte_size`, `sha256`, `embedded_metadata`,
`technical_family_hint` with provenance/confidence, `duplicate_of`,
`sidecar_metadata`, and optional `enrichment_observations`. A separate live
projection can attach `a1111_visible_name`, `available`, `loaded`, `skipped`,
and observation time without mutating job provenance.

## Validation and next package

`tests/tools/test_asset_census.py` covers header-only safetensors parsing,
streamed hash identity/cache, duplicate detection, dual-root behavior,
same-name/different-hash detection, legacy-list versus rich-object cache
records, corrupt metadata, offline CLI behavior, and deterministic output.

The next coherent package is a narrow Asset Registry design/implementation
package that selects its durable local-file identity boundary and a separate
live-A1111 projection contract. It must not begin recommendation logic for
model/VAE/sampler/scheduler/CFG/steps/LoRA/embedding settings.
