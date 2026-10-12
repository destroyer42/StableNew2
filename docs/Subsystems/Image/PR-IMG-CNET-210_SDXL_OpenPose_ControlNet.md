# PR-IMG-CNET-210 - SDXL PromptPack OpenPose ControlNet

## Execution Profile + Model/Reasoning Recommendation

Standard: a substantial cross-file implementation with input-integrity risk, entirely inside
existing ownership (PromptPack storage, the compiler, the immutable NJR, the Forge
backend/executor, the asset registry). No new queue, runner, history, compiler or lifecycle
authority, so no architectural decision was needed. Codex: GPT-6.1 Sol XHigh. Claude Code: Sonnet 5.5 XHigh. Preferred host: local
desktop. Physical generation was **not** performed and needs separate owner authorization.

## Controller Surface Assessment

No ratcheted controller changed (`app_controller.py`, `job_service.py`, `job_history_service.py`,
`pipeline_controller.py` are untouched). Compilation lives in `src/pipeline/openpose_compile.py`
called from `PromptPackNormalizedJobBuilder`; the editor logic lives in a widget and a
toolkit-neutral view model; the existing background Preview already runs the compiler off Tk.

## Outcome

An operator selects a previously rendered OpenPose reference image from a scannable library,
attaches it to an individual PromptPack slot much like a LoRA, edits ControlNet settings, saves the
pack and submits it through the normal queue-first Forge SDXL workflow. The image is **conditioning
input, not prompt text**: it is frozen into the immutable NJR (identity and verified bytes, never a
base64 blob), sent to Forge as exactly one ControlNet unit on the base txt2img request, and recorded
in artifact/history provenance and replay.

## Operator setup

1. **WebUI root.** The library lives under the Stable Diffusion WebUI root StableNew already uses
   for LoRAs and embeddings (`STABLENEW_WEBUI_ROOT` / the configured root).
2. **Reference library:** `<WebUI root>/models/OpenPose/`. Nested folders are allowed and their
   relative path is the image's identity (`Standing/relaxed.png`).

   ```
   <WebUI root>/models/
     ControlNet/   <- SDXL OpenPose model weights (installed by you)
     OpenPose/     <- pre-rendered OpenPose images
       Standing/relaxed.png
       Walking/walking_forward.png
   ```

   Accepted: PNG, JPEG, WEBP; 64-4096 px per side; at most 20 MiB. Each file is validated and
   hashed on a worker the first time it is used.
3. **ControlNet model.** Install an **SDXL** OpenPose ControlNet into `models/ControlNet` and make
   sure the Forge runtime lists it (`GET /controlnet/model_list`). StableNew never downloads,
   installs, enables or restarts anything. The editor lists installed weights and labels each by
   header evidence: *SDXL*, *not SDXL* (refused) or *unverified* (not identifiable from its header;
   still allowed, clearly labelled).
4. **Runtime and checkpoint.** The configured image backend must be **Forge** (the built-in Forge Neo
   ControlNet extension) and the selected checkpoint must be an **SDXL** base checkpoint. A1111,
   FLUX.2 Klein and Z-Image are refused (see the matrix below).
5. **Author.** Prompt tab -> select a slot -> *ControlNet OpenPose*: choose an image, choose the
   model, adjust strength/guidance/modes, save the pack, then add it to the queue as usual.

### Limitations of pre-rendered OpenPose maps

The image must already *be* an OpenPose map (the coloured stick-figure skeleton on black produced
by an OpenPose/DWPose editor). The preprocessor is fixed at `None`: StableNew does **not** extract
a pose from an ordinary photograph. Automatic extraction, multi-ControlNet stacking, non-SDXL
conditioning and image-edit conditioning are deliberately deferred.

## PromptPack declaration (`openpose.v1`)

Optional, per native JSON slot. Absent means "no conditioning" and existing packs are unchanged.

```json
{
  "controlnet_openpose": {
    "contract": "openpose.v1",
    "enabled": true,
    "asset": "Standing/relaxed.png",
    "model": "xinsir_openpose_sdxl",
    "weight": 1.0,
    "guidance_start": 0.0,
    "guidance_end": 1.0,
    "control_mode": "Balanced",
    "resize_mode": "Resize and Fill",
    "preprocessor": "None"
  }
}
```

| Field | Rule |
|---|---|
| `asset` | library-relative POSIX path; no absolute path, drive, `.`/`..`/empty segment, control character; PNG/JPEG/WEBP |
| `weight` | 0-2 (default 1.0) |
| `guidance_start` / `guidance_end` | 0-1 and `start < end` (defaults 0.0 / 1.0) |
| `control_mode` | `Balanced` (default), `My prompt is more important`, `ControlNet is more important` |
| `resize_mode` | `Resize and Fill` (default), `Just Resize`, `Crop and Resize` |
| `preprocessor` | `None` only |
| `model` | the ControlNet model; may be empty in a saved pack (compile refuses until chosen) |

Unknown fields are refused at compile (they cannot be honored). The editor keeps whatever the file
holds verbatim: a malformed value is shown, never silently dropped, and is only removed by the
operator. Clone/copy-slot deep-copy it, clearing writes an explicit removal, and a slot that has
only a declaration (no text) is not discarded as padding. Flattened TXT/TSV export cannot represent
conditioning; exporting a pack that carries it logs a warning, and the native JSON keeps it.

## Architecture and ownership

```
PromptPack slot (controlnet_openpose)
  -> PackRow.conditioning (storage.prompt_pack_rows; follows the rendered row and every Matrix variant)
  -> OpenPoseCompiler (src/pipeline/openpose_compile.py, called by PromptPackNormalizedJobBuilder)
       target gate + library read once + SHA-256 + content-addressed snapshot
  -> immutable NJR  config["controlnet_openpose"]  (+ provenance.metadata["conditioning"])
  -> JobService -> SQLite -> PipelineRunner.run_njr
  -> ForgeWebUIImageBackend (validate_njr_intent, pre-dispatch admission)
  -> executor.run_txt2img_stage (final hash re-verification, one ControlNet unit)
  -> artifacts / history / replay
```

| Concern | Module |
|---|---|
| declaration contract, defaults, identity normalization | `src/conditioning/openpose.py` |
| safe resolve, bounded read, validation, thumbnails | `src/conditioning/openpose_library.py` |
| frozen record, job-owned snapshot, verification | `src/conditioning/openpose_snapshot.py` |
| registry-backed listing/search for the editor | `src/conditioning/openpose_catalog.py` |
| `AssetKind.OPENPOSE_IMAGE`, per-kind extension filtering | `src/assets/registry.py` |
| ControlNet weight header evidence | `src/assets/controlnet_structure.py` |
| target eligibility (a projection over `ModelPolicy`) | `src/image_backends/openpose_capability.py` |
| runtime admission and the wire unit | `src/image_backends/forge_controlnet.py` |
| read-only ControlNet catalog | `ForgeWebUIClient.get_controlnet_catalog` |
| editor widget / neutral view | `src/gui/widgets/openpose_picker_panel.py`, `src/gui_v2/openpose_conditioning_view.py` |

### Library as an asset kind

`AssetKind.OPENPOSE_IMAGE` (`models/OpenPose`) is distinct from `AssetKind.CONTROLNET` (weights).
Extension filtering is per kind: image files elsewhere are never indexed as checkpoints/LoRAs/
weights, and weight files in the OpenPose folder are not images. Image records carry byte identity
only (no compatibility evidence) and a file link that leaves the library is not indexed. The editor
reads the persisted snapshot or runs the incremental scan on a worker; nothing is scanned at import
or on Tk, and the first scan happens when the picker is first shown.

## Immutability and input integrity

The compiler reads the library file **once**; the hash, the decode validation and the snapshot all
come from those same bytes.

* Path containment: the identity is normalized, then resolved through the filesystem; a symlink or
  junction that leaves `models/OpenPose` is refused.
* Envelope: size, dimensions, format and a full decode are checked (a truncated or non-image file
  is refused with an actionable message, never "no images").
* The NJR carries identity (`asset`), `asset_sha256`, `asset_size`, image facts and the job-owned
  `snapshot.path`. The snapshot is a byte copy named `<sha256>.<ext>` under
  `state/conditioning_inputs/openpose/` (StableNew's mutable state directory), written atomically
  and idempotently.
* Replacing a library file afterwards can never change a queued or replayed job. A same-name,
  different-bytes replacement freezes a different digest on the next compile.
* The record is re-verified by hash at admission (`validate_njr_intent` / `_before_dispatch`) and
  again immediately before the POST. A missing or changed snapshot fails the job **before any
  generation POST** with an explicit message; nothing is refrozen from the library silently.
* Persisted jobs without the field are unaffected; no migration.

## Target eligibility (matrix)

| Target | Result |
|---|---|
| SDXL checkpoint (registry/header evidence), Forge backend, base txt2img | supported |
| checkpoint StableNew has not identified | *unverified*: the compiler checks the checkpoint header by name (exactly one local file, no hashing); refused unless confirmed SDXL |
| identified SD1.x/SD2.x/other family, or conflicting evidence | refused |
| FLUX.2 Klein, Z-Image (exact profiles) | refused (their existing "ControlNet unsupported" validators remain) |
| A1111 backend | refused before dispatch (capability flag `supports_openpose_conditioning` is false) |
| img2img / ADetailer / upscale / any non-base stage | never conditioned; ADetailer keeps its own script entry untouched |

The generic `controlnet` model-policy feature stays **unsupported** everywhere and the persisted
policy contract that frozen Learning studies compare against is unchanged; eligibility is a pure
projection over the existing `ModelPolicy`. A saved selection is never deleted when the target is
unsupported: the editor shows why and keeps it, Validate lists it as a refusal for the row, and
compile refuses before any NJR exists.

## Forge request

For admitted work the base `POST /sdapi/v1/txt2img` gains exactly one unit; other
`alwayson_scripts` entries (for example the Aesthetic script) are preserved and an existing
`ControlNet` entry is never overwritten:

```json
{"alwayson_scripts": {"ControlNet": {"args": [{
  "enabled": true, "module": "None", "model": "<exact name Forge advertises>",
  "image": "<base64 of the verified snapshot>", "weight": 1.0,
  "guidance_start": 0.0, "guidance_end": 1.0,
  "control_mode": "Balanced", "resize_mode": "Resize and Fill", "pixel_perfect": false}]}}}
```

Admission (read-only, before any module write or POST): the ControlNet extension must answer
`/controlnet/model_list` and `/controlnet/module_list`; the selected model must resolve to exactly
one advertised name (exact match, else name-without-`[hash]`/extension; ambiguity is refused); the
`None` module must be advertised; the weight file's safetensors header (cross-attention width /
conditioning width) must not prove a non-SDXL model. Absent extension, absent or ambiguous model
and a missing `None` module each fail the job with an actionable message and **no fallback to
ordinary txt2img**.

The image bytes exist only in the request: the executor logs and manifests use the unit-free copy
plus content-free evidence (`controlnet_openpose` in the manifest/variant,
`image_backend_metadata.openpose_conditioning` for admission evidence), failure records keep the
request shape with nested image data replaced by a size marker, and the NJR/history never hold
base64.

## Replay and provenance

Replay compiles a fresh job identity with parent lineage on the same path; the frozen record is
carried unchanged, so it reproduces from the job-owned snapshot even if the library file changed.
If the snapshot is unavailable the replay fails explicitly before dispatch (retry-selected-failed
admission re-verifies it by hash like other frozen inputs). Provenance
(`provenance.metadata["conditioning"]`, manifests, history variants) records asset identity, digest,
model, settings and why the target was admitted (family and its evidence source).

## Other consumers

Learning experiments and Model Comparison freeze prompt text only. A selected PromptPack row that
carries **enabled** conditioning is refused there with a clear message instead of silently
producing images that ignore the pose.

## Tests (deterministic, no GPU/network)

`tests/conditioning/*_210.py`, `tests/assets/test_openpose_image_kind_210.py`,
`tests/assets/test_controlnet_structure_210.py`, `tests/image_backends/test_openpose_capability_210.py`,
`tests/image_backends/test_forge_controlnet_210.py`, `tests/image_backends/test_openpose_surfaces_210.py`,
`tests/promptpacks/test_openpose_promptpack_210.py`, `tests/pipeline/test_openpose_compile_210.py`,
`tests/gui_v2/test_openpose_picker_panel_210.py`, `tests/gui_v2/test_prompt_tab_openpose_210.py`,
`tests/integration/test_pr_img_cnet_210_canonical_path.py` (PromptPack -> NJR -> JobService ->
SQLite -> runner -> Forge backend -> executor -> fake Forge transport, mixed three-slot batch,
replay, refusals, ADetailer/upscale coexistence).

## Not claimed / remaining

* **Physical verification is outstanding.** Mocked tests prove the request contract and lifecycle,
  not that a real Forge Neo (pinned `d70373eb`) accepts exactly these unit field names or that the
  pose measurably influences an SDXL image. One owner-authorized physical Forge run (one pose, one
  SDXL checkpoint, one SDXL OpenPose model) is required before this is called physically validated.
* Snapshots are content-addressed and small but are not garbage-collected; pruning is a follow-up.
* The header family check for an unidentified checkpoint matches by file name under
  `models/Stable-diffusion`; the Forge-served file is not independently re-read at dispatch.
* ControlNet weight SDXL evidence is header-observational, not a model qualification.
