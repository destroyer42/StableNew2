# PR-IMG-116 - FLUX.2 Klein 4B FP8 Forge production slice

Result class: **PRODUCTION SLICE** on the existing `forge_webui` backend. There is no new backend, queue, runner,
compiler or history authority. A1111 remains the repository default and the rollback; Forge stays selectable, never
forced. Execution Profile: Standard / substantial known-architecture PR (Claude Code: Sonnet 5.5 High).

Canonical path (unchanged):
`Intent -> Compiler -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> forge_webui -> Artifacts/History`.

## What is supported (profile `flux2_klein_4b_fp8` version 1)

| | |
|---|---|
| Backend | `forge_webui` only (a profile on any other backend is rejected, never switched) |
| Model | FLUX.2 Klein 4B FP8 (`flux-2-klein-4b-fp8.safetensors`) with the Qwen3-4B text encoder and the FLUX.2 VAE |
| Modes | text-to-image (`txt2img`) and single-reference edit (`img2img`, one source image) |
| Fixed sampling | Euler, Beta, 4 steps, CFG 1.0, empty negative prompt, no global prompt terms, no prompt optimizer |
| Edit semantics | init image is the one Klein reference, denoise 1.0, no `ImageStitch Integrated` |
| Qualified geometry | 768x1024 and 1024x1024 (anything else is rejected before dispatch) |
| Host RAM | the qualified machine class only (see "Host-memory readiness") |
| Not supported | multi-reference / `ImageStitch`, ADetailer, upscale, hires fix, refiner, LoRA, ControlNet, prompt optimizer, negative prompts, any other sampler/scheduler/steps/CFG, Klein 9B/Base/BF16/GGUF/NVFP4 |

The profile is a small frozen dataclass in `src/image_backends/forge_klein_profile.py`. A published version never
changes; a change is a new version. It is deliberately not a model-profile framework (PR-IMG-130 owns that).

### Immutable intent

The NJR persists only `backend_options.image.model_profile = {"id": "flux2_klein_4b_fp8", "version": 1}` next to
`backend_options.image.backend_id = "forge_webui"`. No machine-local path is persisted. The reference survives NJR
serialization and replay (a replay is a new NJR identity with parent lineage); an unknown profile id or version
fails closed and is never reinterpreted as SDXL work.

## Assets (exact, from the accepted PR-IMG-115 record)

| Role | Repo @ revision | File | Bytes | SHA-256 |
|---|---|---|---|---|
| Transformer | `black-forest-labs/FLUX.2-klein-4b-fp8` @ `5b4408e59397a4a37ccb46afe426d8ed86379441` | `flux-2-klein-4b-fp8.safetensors` | 4,070,624,520 | `97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6` |
| Text encoder | `Comfy-Org/vae-text-encorder-for-flux-klein-4b` @ `5f526678002e43af5551dadb73ce2e8c91b43afe` | `qwen_3_4b.safetensors` | 8,044,982,048 | `6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a` |
| VAE | same repo and revision | `flux2-vae.safetensors` | 336,211,292 | `868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3` |

The identities live in the profile and in `config/forge_klein_assets.json`; a test pins the two together. Weights are
never committed or downloaded by StableNew. They belong in the **managed Forge user-data model tree**, not the A1111
library and not the Forge source/venv:

```
%LOCALAPPDATA%\StableNew\Forge\neo-d70373eb\data\models\Stable-diffusion\flux-2-klein-4b-fp8.safetensors
%LOCALAPPDATA%\StableNew\Forge\neo-d70373eb\data\models\text_encoder\qwen_3_4b.safetensors
%LOCALAPPDATA%\StableNew\Forge\neo-d70373eb\data\models\VAE\flux2-vae.safetensors
```

### Installing

```powershell
powershell -File scripts\install_forge_klein_assets.ps1 -SourceDir <folder holding the three files>
powershell -File scripts\install_forge_klein_assets.ps1 -CheckOnly      # verify the destinations only
```

The tool verifies every source's size and SHA-256 **before** it changes anything, classifies every destination
(missing / correct / conflicting) first, refuses to overwrite a same-name file with a different hash, no-ops on a
correct file, stages each copy beside its destination, hashes it, renames it atomically and hashes the final file
again. It performs no network access and never touches the A1111 library, the Forge source or the venv; it refuses to
run when the managed Forge data directory does not exist.

## Forge multi-module correctness

`ForgeWebUIClient.set_additional_modules([...])` resolves every module against `/sdapi/v1/sd-modules` (an
unavailable module raises before any write), sends the complete list in one `/options` write, reads `/options` back
and compares the effective set exactly; a mismatch raises and generation cannot proceed. `set_vae()` is now a
one-module call through the same single write authority (SDXL behavior and messages unchanged); the A1111 client is
untouched. The executor passes a backend-projected module set to this operation instead of the single-VAE path, and
re-verifies it read-only before reuse.

## Backend projection and fail-closed behavior

`ForgeWebUIImageBackend` owns the Klein translation (`WebUIFamilyImageBackend` gained four inert hooks):

1. **Before dispatch** (runner, `validate_njr_intent`, and again per stage): backend must be `forge_webui`; the stage
   chain must be exactly `["txt2img"]` or `["img2img"]`; the checkpoint is the Klein transformer; sampler, scheduler,
   steps and CFG equal the fixed values; geometry is qualified; no negative prompt, global prompt terms, prompt
   optimizer, hires fix, refiner, LoRA, ControlNet, aesthetic embedding, hypernetwork or foreign VAE; an edit has exactly
   one source image. All conflicts are listed in one error. Nothing is rewritten silently.
2. **Host memory** (below), then **asset availability**: Forge must list the two modules and the checkpoint, otherwise
   the error names the missing asset and the installer command (the executor otherwise turns stage exceptions into a
   generic "no images" failure).
3. **Projection**: exact checkpoint, the module set `[qwen_3_4b, flux2-vae]`, the fixed sampling values, empty negative,
   frozen empty global terms; for edits denoise 1.0 and the source image's size.
4. **Evidence**: the stage result carries `image_backend_metadata.klein_profile` (profile id/version, mode, expected
   transformer/module names, sizes and SHA-256, fixed sampling values, host-memory readings, what Forge reported active,
   and for edits the source image name and SHA-256).

An A1111 job carrying a model profile is rejected by the shared base backend. There is no fallback to SDXL or A1111 and
no model substitution; the existing client's refusal to replay an ambiguous generation POST is unchanged.

## Operator paths

**Text-to-image (Pipeline tab).** Selecting the exact Klein transformer in the existing Base Generation model feed
projects the profile: Euler / Beta / 4 steps / CFG 1.0 are written into the controls and locked, the VAE is set to the
model default (the profile owns its modules), the resolution presets shrink to 768x1024 and 1024x1024, and the helper
text explains the fixed distilled settings. Selecting any other model restores the controls exactly. If the configured
backend is not Forge the same text shows that Klein needs the Forge backend and that StableNew will not switch it.
The compilers (`JobBuilderV2`, the PromptPack builder and the CLI builder) freeze the same values, clear negative text and
global terms and switch the (default-on) prompt optimizer off for the Klein checkpoint, and stamp the profile reference;
a job for a non-Forge configuration is rejected before dispatch with the same actionable message.

**Single-reference edit (Review tab).** One explicit checkbox, "FLUX.2 Klein single-reference edit (Forge)", selects
the mode (never inferred from an image's name or content): it forces `img2img` only, prompt mode Replace, no negative
and batch 1, and requires exactly one selected image and a prompt describing the edit. The existing Review handler builds
a normal immutable reprocess NJR through `ReprocessJobBuilder` (`src/pipeline/klein_edit_reprocess.py`): stage chain
`img2img`, `forge_webui`, Klein profile v1 frozen, one source image, the source's size, name and SHA-256 and the usual
parent lineage recorded in the NJR. Errors (backend, geometry, stages) surface in the Review dialog before anything is
queued. Normal Review reprocess is unchanged.

## Host-memory readiness

PR-IMG-115 proved the GPU fit (VRAM peak 9.7 GiB) but severe host-memory pressure (available RAM near 0 during the lazy
load, Forge tree private memory about 26 GiB). The initial requirement is a **32-GB-class host**. Before a Klein dispatch
the backend reads total and available physical RAM (and Windows commit headroom where available), records them in the
evidence, and:

- **fails** when total physical RAM is below **32,000,000,000 bytes** (decimal 32 GB). The threshold is deliberately not
  32 GiB and not machine-specific: a physically installed 32 GiB Windows machine reports somewhat less after hardware
  reservation (the qualified host reports 34,107,092,992 bytes);
- applies **no floor and no numeric warning to currently available RAM**. IMG-115 captured no trustworthy pre-dispatch
  baseline from which one could be derived, so available RAM is observational only until the production smokes
  establish evidence.

It is a read-only check: no scheduler, lease, memory release or process kill. The acceptance driver records, per smoke:
total physical RAM, available RAM before the runtime/model starts, available RAM immediately before generation dispatch,
minimum available RAM during the job, the Forge-tree private-memory peak and the dedicated VRAM peak.

## Multi-reference limitation

Two-reference editing is **not supported**. The pinned Forge's `ImageStitch Integrated` script-argument path is rejected
before inference (PR-IMG-115, `FORGE_API_INTEGRATION_GAP`); the profile has no multi-reference mode and no job carrying
more than one source image is accepted. It is tracked separately.

## Rollback

Nothing is forced. A1111 stays the default; `webui_runtime_identity` selects Forge. To roll back, choose another model
or set the runtime identity back to `a1111_webui`. Klein NJRs in history keep their recorded profile and are never
rerouted. Removing the three installed files is safe (jobs then fail early with the missing-asset message).

## Physical acceptance

Two production smokes through the real path (`tools/acceptance/img_116_klein_acceptance.py`; managed Forge started and stopped
only through `WebUIProcessManager`; production settings untouched; assets installed with the installer into the managed data
tree and re-hashed by the driver before each run). Evidence: `C:\Users\rob\qual\img_116\`.

| | Smoke A: production text-to-image | Smoke B: Review single-reference edit |
|---|---|---|
| Path | `build_cli_njr` -> `JobService` -> SQLite -> `run_njr` -> `forge_webui` | production `AppController.on_reprocess_images_with_prompt_delta` with the explicit Klein marker -> `ReprocessJobBuilder` -> same `JobService` |
| Intent | 768x1024, seed 424242, Euler/Beta/4/CFG 1.0, IMG-115 portrait prompt | `img2img` only, one source image, "keep the same person, face, pose, framing, hands, motorcycle, lighting and background; change only the jacket to deep red leather" |
| Job id | `img116-klein-a-1791115317` | `f0a820fcbf06458bace5a7c9a0bbea09` |
| Result | completed, 19.7 s (includes the model load) | completed, 16.7 s |
| Artifact SHA-256 | `eccf3c7b94a872a096b9f7c26826caf744fdc597cc596fee8e4fe22a5d384e72` | `a48c2b78fe2421101ce5766b43cac145573a723aee4edb5972c966a702a908a9` |
| Seed | requested 424242, returned 424242 | requested -1 (Review default), returned 2412197479 |
| Profile / modules | profile v1 persisted in the immutable snapshot; Forge reported `flux-2-klein-4b-fp8` with `qwen_3_4b` + `flux2-vae` | same |
| Source lineage | n/a | source path and SHA-256 recorded (`eccf3c7b...`, unchanged after the run); baseline from the source PNG's embedded metadata |
| Dispatches | 1 generation POST | 1 generation POST |
| Memory | total 34.11 GB; available 17.28 GB before the runtime started, 15.35 GB immediately before generation dispatch, **minimum 0.24 GB** during the job | total 34.11 GB; available 18.05 / 16.06 GB, **minimum 0.06 GB** |
| Forge-tree private peak | 26,286 MiB (RSS peak 16,507 MiB) | 26,294 MiB (RSS peak 15,715 MiB) |
| Dedicated VRAM peak | 9,538 MiB (baseline 856), 57 C | 9,795 MiB (baseline 869), 59 C |
| Windows / GPU events | none | none |
| Cleanup | owned tree stopped, no process left, port free | same |

The edit changed only the jacket (deep red leather); face, pose, hands, motorcycle, sign and street are preserved.

**First attempt of Smoke A (disclosed).** The first Smoke A job failed before any sampling (`You do not have Qwen3 state dict`):
Forge loaded Klein with no modules. The model-switch `/options` write consumed the client's 6 s options throttle, so the
module write was silently skipped (`set_vae` skip semantics) and the executor ignored the `False` return. No GPU work ran
and no GPU/system event occurred. The existing client then re-sent the HTTP 500 three times (its normal definite-error
retry), so three requests reached Forge, none past model load. The defect was fixed (strict module write that waits out the
throttle, executor refuses unconfirmed modules, regression test that fails on the old behavior) and the owner authorized the
retry. In total: 3 physical jobs executed (one failed pre-sampling), 2 completed generations.

**Available-RAM evidence and recommendation.** Pre-dispatch available RAM across the three launches was 15.35-16.06 GB
immediately before generation (17.1-18.05 GB before the runtime started), yet every completed run fell to 0.06-0.24 GB
available because the Forge tree's private memory (about 26.3 GiB, above physical RAM) is backed by the pagefile; Windows
commit headroom before dispatch was about 19.9-20.0 GB. The starting value therefore did not predict the dip, and three
samples cannot justify a numeric available-RAM warning threshold; none is implemented. If a threshold is wanted later,
commit headroom is the more meaningful candidate signal and needs more runs (including lower starting levels) first.

## Validation

Focused deterministic suites (fakes only): `tests/image_backends/test_forge_klein_profile.py`,
`tests/api/test_forge_client.py` (multi-module), `tests/integration/test_pr_img_116_klein_canonical_path.py`,
`tests/pipeline/test_klein_compile_policy.py`, `tests/gui_v2/test_klein_profile_gui.py`,
`tests/tools/test_install_forge_klein_assets.py`, `tests/tools/test_img_116_klein_acceptance_driver.py`.
Controller surface: no ratcheted controller was touched.
