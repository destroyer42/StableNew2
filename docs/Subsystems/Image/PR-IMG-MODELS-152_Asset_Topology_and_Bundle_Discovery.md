# PR-IMG-MODELS-152 — Single-authority asset inventory, component compatibility and model-bundle discovery

Status: LOCAL IMPLEMENTATION COMPLETE; hosted CI and independent review pending. Class: Standard/substantial on a known
architecture. Claude Code Sonnet 5.5 High / Codex GPT-6.1 Sol High, Windows Local/Desktop. Controller Surface Assessment: no
controller or Tk change.

The package lets StableNew say, without loading a model or generating an image, **what is installed, what its bytes support,
which candidate component combinations are structurally plausible, and what remains unknown** — and nothing more. It makes
nothing executable: no profile, admission, selection, NJR, queue or runner behavior changes.

## One identity authority, two tiers

| Tier | Type | Carries | Written by |
| --- | --- | --- | --- |
| 1 — provisional observation | `ObservedFile` / `ObservedPackage` (`src/assets/observation.py`) | location, root, size, mtime fingerprint, bounded header/config evidence, errors, `IdentityStatus` | `AssetRegistry.observe()` (never persisted) |
| 2 — verified identity | `AssetRecord(sha256=...)` (unchanged) | fingerprint-validated SHA-256, merged locations, sidecars | `AssetRegistry.refresh()` (unchanged; v1/v2 cache, lock, atomic publication) |

An observation has **no** SHA-256 field of its own. `IdentityStatus` is `verified` only when the existing cache already holds
a digest whose size/mtime fingerprint still matches (`AssetRegistry.verified_sha256`, read-only); otherwise `pending`. A stale,
malformed or unfingerprinted cache entry is `pending`. Normal observation computes no hash, loads no weight, writes no cache
and starts no process. `text_encoder`, transformer packages and `models/embeddings` are deliberately **not** `AssetKind`
members, so the default `refresh()` never reads them and no second identity set exists.

## Observation (`src/assets/observation.py`)

* **Roots** (`AssetRegistry.observation_roots()`): `models/Stable-diffusion` (recursive, including nested folders),
  `models/text_encoder(s)`, `models/transformer`, `models/VAE`, `models/Lora`, `models/LyCORIS`, `<webui>/embeddings` and
  `models/embeddings`. A missing root is reported `not scanned`, never an error or an empty answer. Other registry roots are untouched.
* **Safety envelope** (`ScanLimits`): file, directory, depth and JSON-size quotas; cancellation checked per entry (a partial,
  clearly incomplete scan). Directory links/junctions are never descended into; a file link must resolve inside its root; one
  physical file is observed once (extra paths are `aliases`); same-name files in different locations stay separate
  observations. A file whose size/mtime changes while it is read yields `changed_during_scan`, not evidence.
* **Formats**: `.safetensors` through the one parser (`checkpoint_structure.read_tensor_table`); `.gguf` through a bounded
  container reader (`src/assets/gguf.py`: at most 1 MiB, quantization only from the container's declared `general.file_type`,
  never the name or size); `.pt/.pth/.ckpt/.bin` are `FORMAT_UNINSPECTED` and never deserialized.
* **Packages**: every `*.safetensors.index.json` is validated (plain shard names inside the directory, duplicate keys,
  mapping vs shard headers, missing/extra/conflicting shards, declared `total_size` vs the shard files) and grouped into one
  logical package *before* any pairing. Shards of a defective or index-less group are never standalone candidates. `config.json`
  and tokenizer/license files are associated only through a validated package boundary (or a directory with exactly one model
  file); a `config.json` shared by several model files is reported unassociated, and only allow-listed config keys are retained.

## Classification (`component_evidence.py`, `adapter_evidence.py`, `checkpoint_structure.py`)

One shape classifier (`classify_checkpoint_shapes`) serves both the registry path and component evidence: SD1.x/SD2.x are no
longer labelled SDXL; SDXL inpainting (9-channel input) and refiner are distinct; **Turbo** is a subtype only from embedded
metadata (`modelspec.*`, `ss_base_model_version`), never a name. Precision is reported as the full dtype histogram, byte
shares, scale/quantization keys and a layout (`plain`, `mixed_float`, `mixed_scaled`, `unknown`) with the dominant dtype named
*by tensor count* and *by bytes* separately — an FP8 checkpoint stores most tensors as F32 scales, so a single dtype is never the
layout. Added signatures were grounded on real headers: Z-Image DiT, Qwen-Image DiT, Qwen-Image VAE; VAEs carry latent channels
**and** family (`flux1_ae`, `flux2_vae`, `ldm_kl_4ch`, `qwen_image_vae`) **and** key format (native vs Diffusers). Anything without a
reliable signature (for example a Qwen2.5-VL encoder) stays `unrecognized`. LoRAs: kohya/PEFT/LoKr style, tensor family from
cross-attention width or FLUX-style block names, declared labels kept as claims, conflicts between `ss_base_model_version` and
`modelspec.architecture` (or the tensors) reported, and VAE-like/checkpoint-like tensor sets in a LoRA folder flagged as
*suspected* misplacement (never moved). Embeddings: suitability only from a positive signature, otherwise `unknown`.

## Bundles and relationships (`src/assets/bundles.py`)

`ModelBundleEvidence` is a pure, advisory projection: primary file or logical package, family/variant/packaging, quantization
evidence, external requirements with their basis (`header`, `documented`, `header+documented`), and per-role relationships with
outcomes `possible | incompatible | missing | unknown | conflicting`. Candidates are judged on header facts (encoder family and
hidden size, VAE family + latent channels + key format); a 4B (2560) Qwen3 never satisfies a 4096 requirement, a quantized
encoder is `unknown`, Qwen-Image's Qwen2.5-VL requirement is never filled by Qwen3, and a Diffusers-key 32-channel VAE is
`incompatible` with a Forge-native FLUX.2 layout. Readiness is separated into `installed`, `header_identified`,
`dependencies_feasible`, `served_in_forge`, `selected_in_forge`, `exact_profile_admitted`, `hardware_qualified` and
`job_result_evidence`; the last five start `not_checked` and no value is ever `ready` or `qualified` from file evidence.
LoRA/embedding hints are counts plus a bounded name list of tensor-family matches, never an admission.

## Report and reconciliation

`python tools/asset_topology_report.py [--json PATH|-] [--include-paths] [--forge-url URL]` (thin CLI over
`AssetRegistry.observe()` and `inventory_report.build_report`). Default output is offline, deterministic (no clock), bounded
(list caps and a 2 MiB ceiling, with `omitted` counts) and carries no absolute path, prompt text or raw metadata; paths appear only
with `--include-paths`. Sections: roots scanned/not scanned, file vs logical-model counts, unrecognized, collisions
(different size or two different verified digests prove `different`; equal name and size stay `unverified`), exact-path aliases,
packages, adapters, bundles, the five operator `Not Working` cases classified separately, a ranked qualification backlog and
the recorded candidate-specific outcome. `Not Working` is operator-provided status, never a verdict. The PR-151 `NO_GO_RESOURCE_RISK`
is attached only to the exact evaluated file (name + size, or the recorded SHA prefix/suffix when identity is verified); a
same-structure sibling is reported as unevaluated.

`--forge-url` (`src/image_backends/model_inventory_reconcile.py`) is the only runtime contact: GET-only reads of an
endpoint that is already running, identity-checked through `classify_client_runtime`. A failed read is `unavailable`, a
successful empty module catalog is `empty` (the existing tri-state), `/sd-models` returning `[]` is `unavailable` (its legacy
client cannot distinguish failure), and an unverified or non-Forge endpoint is `unverified_runtime` and not attributed
managed-Forge qualification. No process launch, port probing, option write, module POST or selection.

## Acceptance coverage

`tests/assets/test_asset_topology_152.py` (A1–A17, synthetic headers only) and `tests/tools/test_asset_topology_report_152.py`.
A15 is held by the unchanged PR-150 gate, D110 normalization, Klein 4B and A1111 suites plus a source-level guard that the new
modules contain no write/launch/network call. Mutation proof: eleven injected regressions (hashing during observation, ignored
hidden size/key format/fingerprint, basename dedup, incomplete-package-as-complete, followed links, size-implies-equality,
dominant-dtype-as-layout, name-derived Turbo, attributed unverified runtime) each fail the suite.

## Known limits and next decision

* Observation-only kinds (encoders, transformer packages, `models/embeddings`) have no explicit-verification entry point through
  `refresh()`; byte equality for them stays `pending` until a later, separately authorized change (PR-151's read-only `--hash` tool
  remains the precedent). No second hash cache was added.
* File-symlink and file-alias tests skip where the OS refuses symlink creation; directory junction/guard paths are covered
  regardless. Hard links are not detected as aliases.
* Documented (non-header) requirements are a small labelled table (FLUX.2/Z-Image/Qwen-Image); loader support in the pinned
  Forge is **not** established by any structural match, and GGUF content is unverified.
* Recommended next qualification candidate: **Z-Image-Turbo FP8-scaled** — header evidence finds a `possible` hidden-2560 Qwen3
  encoder and FLUX.1-style AE; the next step is a read-only pinned-loader/quantization feasibility check, with a physical
  qualification only on new owner approval.
