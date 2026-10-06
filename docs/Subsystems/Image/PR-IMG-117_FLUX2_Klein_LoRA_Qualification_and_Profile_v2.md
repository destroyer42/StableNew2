# PR-IMG-117 - FLUX.2 Klein 4B LoRA qualification and profile v2

Result class: **QUALIFIED, PRODUCTION SLICE** (`flux2_klein_4b_fp8` profile **v2**: exactly one explicitly Klein-4B-compatible
LoRA on text-to-image work). Klein remains a model profile on the existing `forge_webui` backend; there is no new backend,
queue, runner, compiler, LoRA scanner or runtime authority. Execution Profile: Standard (Claude Code: Sonnet 5.5 High).

Canonical path (unchanged):
`Intent -> Compiler -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> forge_webui -> Artifacts/History`.

## Previous restriction and root cause

Profile v1 (PR-IMG-116) rejected every LoRA. That was a statement about what had been *qualified*, not about the model:
Black Forest Labs documents training FLUX.2 Klein LoRAs against `FLUX.2-klein-base-4B` and running them on the distilled
4-step `FLUX.2-klein-4B`. Whether the pinned managed Forge and StableNew's existing `<lora:name:weight>` path execute such an
adapter correctly had to be proven physically, and StableNew needed a way to know that an adapter is for Klein 4B (generic
FLUX evidence cannot distinguish FLUX.1 from FLUX.2 Klein).

## Versions

| | v1 (PR-IMG-116) | v2 (this PR) |
|---|---|---|
| Identity | `flux2_klein_4b_fp8` version 1 | `flux2_klein_4b_fp8` version 2 |
| Assets, sampling, modes, geometry, host RAM | exact transformer/Qwen3/VAE, Euler/Beta/4/CFG 1.0, 768x1024 and 1024x1024, 32e9 bytes | identical (`dataclasses.replace` of v1) |
| LoRA | none: every LoRA is rejected | exactly one explicitly Klein-4B-compatible LoRA, text-to-image only |
| Negative prompt, global terms, optimizer, hires/refiner/ADetailer/upscale/ControlNet/hypernetwork | unsupported | unsupported (unchanged) |

v1 is never edited or upgraded: it stays registered, resolves exactly as before, and a persisted v1 NJR (and its replay, which
copies the immutable workload) keeps rejecting LoRA. Only `latest_klein_profile()` moved, so *newly constructed* Klein work is
stamped v2. The NJR still carries only `backend_options.image.model_profile = {id, version}`; no machine path is persisted.

## Compatibility evidence policy (`src/image_backends/forge_klein_lora.py`)

`AssetRegistry` stays the only local identity authority (SHA-256, safetensors header, per-location CivitAI-style sidecar).
The new module is a narrow *consumer* of the metadata the registry already preserves; it hashes nothing, scans nothing and
never rewrites user metadata. Matching is exact whole-value (no substring):

* accepted Klein-4B values: `flux2_klein_4b`, `black-forest-labs/FLUX.2-klein-4B`, `black-forest-labs/FLUX.2-klein-base-4B`
  (case- and slash-normalized) in a supported embedded field (`ss_base_model_version`, `modelspec.architecture`,
  `modelspec.base_model_version`) or sidecar field (`baseModel`, `base_model`);
* **compatible** only with such explicit evidence and no contradiction;
* **incompatible**: a resolved SD1/SD2/SDXL/SD3 family, or an explicit other FLUX variant (for example `flux2_klein_9b`,
  `FLUX.1-dev`);
* **conflicting**: Klein-4B evidence alongside any contradicting evidence;
* **unverified** (not runnable): generic FLUX, unknown or absent evidence, a name the registry does not know, or a name that
  matches more than one distinct file. The error says the adapter may be valid but StableNew cannot establish Klein-4B from
  its local metadata.

A filename, Forge listing the name, generic `ModelFamily.FLUX`, or the operator's choice never proves compatibility. The
generic compatibility module is deliberately unchanged (it does not recognize `flux2_klein_4b`; that is why a consumer was
needed rather than widening it into a profile framework).

## v2 admission and evidence

Rejected **before any generation POST** (runner and per-stage, `ForgeWebUIImageBackend`): more than one effective LoRA
(`<lora:...>`/`<lyco:...>` tags in the rendered prompt), a malformed tag, a non-finite weight or one outside `(0, 2.0]`,
`lora_strengths` overrides, a LoRA declared by the NJR that is not in the prompt Forge receives (never silently dropped), a
LoRA with a single-reference edit, plus every other Klein restriction (negative prompt, global terms, optimizer, ...).
Immediately before dispatch the backend also requires that the serving Forge lists the adapter (`GET /sdapi/v1/loras`, new
read-only `ForgeWebUIClient.get_loras`) and that the path Forge reports is a location the registry identified, so a same-named
different file is refused.

The stage result's `image_backend_metadata.klein_profile.lora` carries, without machine paths: profile id/version (alongside),
logical name, requested weight, registry SHA-256, the compatibility status with the exact evidence source and raw value that
admitted it, whether Forge listed it and the path was bound to the registry identity, and Forge's own application record when
observable. If Forge's log says it did **not** apply the adapter (`[LORA] LoRA mismatch ...`) the job fails instead of recording
a LoRA result. Absence of a log line is recorded as unobserved (Forge caches an identical adapter set), never as failure.

## Operator surface

Selecting the Klein checkpoint keeps the fixed sampling/size projection and the cleared, disabled-in-effect negative prompt; the
helper now says the qualified distilled path uses no standard negative prompt (CFG 1.0 ignores negative text) and to describe
what is wanted positively, and that one LoRA whose metadata names FLUX.2 Klein 4B is supported. The Prompt tab's LoRA picker
annotates each selected LoRA with the admission decision (`verified for FLUX.2 Klein 4B` or `not verified for FLUX.2 Klein 4B
(<status>): <reason>`) and the Base Generation helper text surfaces a selection that would be rejected. Selections are never
removed or rewritten; choosing an ordinary model clears every annotation and restores the helper text exactly. The GUI reads
only the registry's persisted snapshot (no scan or hashing on the Tk thread); admission always refreshes, so a stale cache can
only make the GUI more cautious.

## Physical acceptance

Qualification adapter: `Norod78/flux2-klein-4b-lora-old-gods` (92,426,800 bytes, SHA-256
`0d028797b10e46e049cf2953bf14c486cbf511c336a6d99df7848979cf90f4bd`; text-to-image; trained with AI Toolkit on
`FLUX.2-klein-base-4B`; its model card states it works with the distilled 4B at weight 0.5-1.0; license `other` = follow the
base-model terms). Its safetensors header carries `ss_base_model_version = flux2_klein_4b` (the explicit evidence admitted) and
160 `diffusion_model.*` rank-32 tensors. The file was fetched once with owner authorization and kept outside the repository in
the owner's LoRA directory.

One managed Forge session (started and stopped only through `WebUIProcessManager`), three jobs through the production path
`build_cli_njr -> JobService -> SQLite -> SingleNodeJobRunner -> PipelineRunner.run_njr -> forge_webui`
(`tools/acceptance/img_117_klein_lora_acceptance.py`; profile v2 selected for that process only until acceptance), identical
prompt, seed 424242, 768x1024, Euler/Beta/4/CFG 1.0, no negative, no globals, no optimizer:

| | baseline (no LoRA) | LoRA weight 0.8 | LoRA weight 0.4 |
|---|---|---|---|
| Result | completed, 30.6 s (includes the model load) | completed, 7.7 s | completed, 6.3 s |
| Artifact SHA-256 | `7646f49e687429ef...` | `8b34908aa6d64fd2...` | `9389fbd512d7dada...` |
| Seed | requested 424242, actual 424242 | same | same |
| Profile / persisted intent | v2 | v2; `<lora:flux2-klein-4b-lora-old-gods:0.8>` in the snapshot prompt | v2; `...:0.4>` |
| Forge sampling runs | 1 | 1 | 1 |
| Forge's own record | n/a | `[LORA] Loaded flux2-klein-4b-lora-old-gods.safetensors for KModel-UNet with 80 keys at weight 0.8 (skipped 0 keys)` | same at weight 0.4 |
| Total / available RAM before dispatch | 34.11 / 16.91 GB | 34.11 / 10.26 GB | 34.11 / 6.86 GB |
| Commit headroom before dispatch | 22.45 GB | 7.99 GB | 4.03 GB |
| Minimum available RAM during the job | 0.76 GB | 6.17 GB | 6.27 GB |
| Forge-tree private-memory peak | 26,276 MiB | 26,538 MiB | 25,061 MiB |
| Dedicated VRAM peak | 10,187 MiB | 10,487 MiB | 10,562 MiB |

Runtime and identity: managed ownership true (`runtime_identity == forge_webui`); Forge reported checkpoint
`flux-2-klein-4b-fp8.safetensors` with modules `qwen_3_4b` + `flux2-vae`; the three asset SHA-256s were re-verified before the
run; Forge listed 47 LoRAs and the adapter's reported path matched the registry location. No OOM, no GPU reset, no Windows
hardware or GPU event; the owned tree stopped, nothing listened on 7871 afterwards, and the one "surviving PID" the stop record
shows is the same transient the IMG-116 evidence shows (the PID was gone, not listening, on the next check).

**Visual verification.** The baseline is an ordinary elderly craftsman. At weight 0.8 the adapter transforms the same
seed/composition into the adapter's "old gods" look (extra eyes, tentacle-like beard) - a clearly material effect. At 0.4 the
effect is visibly partial (weathered skin, small growths) - the weight is honored.

**Disclosed observation defects found by the run (fixed afterwards, evidence unchanged).** (1) The in-job consumption observer
did not understand Forge's console wrapping (each `[LORA]` record is split across lines), so the persisted v2 evidence of the
two LoRA jobs records `observation.consumed = null`; the consumption proof for this acceptance is Forge's own log above. The
parser now normalizes wrapped records and was verified against that real log (80 keys, skipped 0). (2) The driver's first
dispatch counter matched an access-log line Forge does not print; sampling runs (one `Total progress: 0%` bar per dispatch;
three for three jobs) are the dispatch evidence and the counter was changed. Neither affects production dispatch behavior.

## Known limitations and remaining work

* One adapter was qualified physically; admission is by metadata evidence, so adapters without explicit Klein-4B evidence
  (including valid ones) stay non-runnable until their owner adds sidecar evidence. StableNew does not write that evidence.
* Multi-LoRA, LoRA with single-reference edit, Klein 9B/Base/BF16/GGUF/NVFP4 and adapters trained for edit workflows are
  unqualified. The weight bound `(0, 2.0]` is this slice's conservative limit, not a model claim (the adapter card says 0.5-1.0).
* Consumption observation reads the managed runtime's bounded stdout tail; a repeated identical adapter set may legitimately log
  nothing and is recorded as unobserved.
* Host memory: the third job ran with 4.03 GB commit headroom after two earlier jobs in one session; no threshold is derived
  from these samples. The general model-profile framework remains PR-IMG-130.

## Validation

Deterministic: `tests/image_backends/test_forge_klein_lora.py` (exact evidence tokens and near misses, real `AssetRegistry`
records, conflict/incompatible/unverified, prompt-tag parsing, weights, wrapped-log observation),
`tests/integration/test_pr_img_117_klein_lora_canonical_path.py` (v1/v2 resolution and immutability, one admitted LoRA with
path-free evidence, every rejection before the generation POST, served-file binding, mismatch fails, replay preserves version
and LoRA, ordinary SDXL unchanged), `tests/pipeline/test_klein_compile_policy.py` (real PromptPack slot LoRA),
`tests/gui_v2/test_klein_lora_gui_117.py`, `tests/tools/test_img_117_klein_lora_acceptance_driver.py`, plus the existing
IMG-116 suites (updated only where they asserted that new work is stamped v1). Controller surface: no ratcheted controller was
touched.
